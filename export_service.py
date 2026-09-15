"""Экспорт в xlsx: защита от formula injection, чанки IN(), потоковая запись, атомарность."""
import logging
import os
import tempfile
from pathlib import Path

from constants import MAX_EXPORT_IN_CHUNK, STATUS_NAMES
from database import db

logger = logging.getLogger(__name__)


def safe_cell(v) -> str:
    """Защита от Excel formula injection: '=+-@' и управляющие в начале."""
    s = "" if v is None else str(v)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _resolve_output(output_path: str) -> Path:
    p = Path(output_path)
    if not p.parent.exists():
        raise FileNotFoundError(f"Папка не найдена: {p.parent}")
    if p.suffix.lower() != ".xlsx":
        raise ValueError("Файл экспорта должен иметь расширение .xlsx")
    return p


def _atomic_save(wb, output_path: Path) -> None:
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".xlsx", dir=str(output_path.parent))
    os.close(tmp_fd)
    try:
        wb.save(tmp_name)
        os.replace(tmp_name, output_path)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except OSError:
            pass


def _tags_chunked(cursor, case_ids: list) -> dict:
    tags_map: dict = {}
    for i in range(0, len(case_ids), MAX_EXPORT_IN_CHUNK):
        chunk = case_ids[i:i + MAX_EXPORT_IN_CHUNK]
        placeholders = ",".join(["?"] * len(chunk))
        cursor.execute(f"""
            SELECT ct.case_id, t.tag_name
            FROM case_tags ct
            JOIN tags t ON ct.tag_id = t.tag_id
            WHERE ct.case_id IN ({placeholders})
        """, chunk)
        for row in cursor.fetchall():
            tags_map.setdefault(row["case_id"], []).append(row["tag_name"])
    return tags_map


def export_results_to_xlsx(project_path: str, output_path: str, file_id=None):
    import openpyxl
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    out = _resolve_output(output_path)

    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
        if file_id:
            file_condition = " WHERE c.file_id = ?"
            params.append(file_id)
        cursor.execute(f"""
            SELECT
                c.case_id, c.row_index, c.primary_text, c.response_text,
                c.group_name, f.file_name,
                COALESCE(a.status, 'unreviewed') as status,
                a.comment as review_comment, a.updated_at as reviewed_at,
                ec.name as error_category, es.name as error_subcategory,
                e.severity as error_severity
            FROM cases c
            JOIN files f ON c.file_id = f.file_id
            LEFT JOIN annotations a ON c.case_id = a.case_id
            LEFT JOIN case_errors e ON e.case_id = c.case_id
            LEFT JOIN error_categories ec ON ec.category_id = e.category_id
            LEFT JOIN error_categories es ON es.category_id = e.subcategory_id
            {file_condition}
            ORDER BY f.imported_at, c.row_index
        """, params)
        rows = cursor.fetchall()
        case_ids = [r["case_id"] for r in rows]
        tags_map = _tags_chunked(cursor, case_ids) if case_ids else {}

    wb = openpyxl.Workbook(write_only=False)
    ws = wb.active
    ws.title = "Результаты разметки"
    headers = ["№", "Файл", "Строка", "Запрос", "Ответ", "Группа",
               "Статус", "Теги", "Комментарий", "Дата проверки",
               "Категория ошибки", "Подкатегория", "Критичность"]
    header_font = Font(bold=True, color="00FF41")
    header_fill = PatternFill(start_color="003300", end_color="003300", fill_type="solid")
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center")

    for row_idx, row in enumerate(rows, 2):
        tags = tags_map.get(row["case_id"], [])
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        ws.cell(row=row_idx, column=2, value=safe_cell(row["file_name"]))
        ws.cell(row=row_idx, column=3, value=row["row_index"] + 1)
        ws.cell(row=row_idx, column=4, value=safe_cell(row["primary_text"] or ""))
        ws.cell(row=row_idx, column=5, value=safe_cell(row["response_text"] or ""))
        ws.cell(row=row_idx, column=6, value=safe_cell(row["group_name"] or ""))
        ws.cell(row=row_idx, column=7, value=STATUS_NAMES.get(row["status"], row["status"]))
        ws.cell(row=row_idx, column=8, value=safe_cell(", ".join(tags)))
        ws.cell(row=row_idx, column=9, value=safe_cell(row["review_comment"] or ""))
        ws.cell(row=row_idx, column=10, value=row["reviewed_at"] or "")
        ws.cell(row=row_idx, column=11, value=safe_cell(row["error_category"] or ""))
        ws.cell(row=row_idx, column=12, value=safe_cell(row["error_subcategory"] or ""))
        ws.cell(row=row_idx, column=13, value=safe_cell(row["error_severity"] or ""))

    for i, width in enumerate([5, 20, 8, 50, 50, 15, 12, 25, 30, 20, 20, 20, 12], 1):
        ws.column_dimensions[get_column_letter(i)].width = width

    _atomic_save(wb, out)
    logger.info("exported %s rows -> %s", len(rows), out)
    return len(rows)


def export_report_to_xlsx(project_path: str, output_path: str, file_id=None):
    import openpyxl
    from openpyxl.styles import Font
    from report_service import (
        get_checks_report, get_files_report, get_overall_report, get_tags_report,
    )

    out = _resolve_output(output_path)
    wb = openpyxl.Workbook()

    ws1 = wb.active
    ws1.title = "Общий отчёт"
    overall = get_overall_report(project_path, file_id)
    ws1.cell(row=1, column=1, value="Показатель").font = Font(bold=True)
    ws1.cell(row=1, column=2, value="Значение").font = Font(bold=True)
    for i, (name, value) in enumerate([
        ("Всего кейсов", overall["total"]),
        ("Проверено", overall["reviewed"]),
        ("Не проверено", overall["unreviewed"]),
        ("Хорошо", overall["good"]),
        ("Плохо", overall["bad"]),
        ("Сомневаюсь", overall["uncertain"]),
        ("Дубль", overall["duplicate"]),
        ("Пропущено", overall["skip"]),
    ], 2):
        ws1.cell(row=i, column=1, value=name)
        ws1.cell(row=i, column=2, value=value)
    ws1.column_dimensions["A"].width = 20
    ws1.column_dimensions["B"].width = 15

    ws2 = wb.create_sheet("По файлам")
    files = get_files_report(project_path)
    if file_id:
        files = [f for f in files if f["file_id"] == file_id]
    for col, header in enumerate(["Файл", "Всего", "Проверено", "Дата импорта"], 1):
        ws2.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, f in enumerate(files, 2):
        ws2.cell(row=i, column=1, value=safe_cell(f["file_name"]))
        ws2.cell(row=i, column=2, value=f["cases_count"])
        ws2.cell(row=i, column=3, value=f["reviewed_count"])
        ws2.cell(row=i, column=4, value=f["imported_at"])
    ws2.column_dimensions["A"].width = 30
    ws2.column_dimensions["B"].width = 12
    ws2.column_dimensions["C"].width = 12
    ws2.column_dimensions["D"].width = 20

    ws3 = wb.create_sheet("По тегам")
    tags = get_tags_report(project_path, file_id)
    for col, header in enumerate(["Тег", "Кейсов", "Системный"], 1):
        ws3.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, tag in enumerate(tags, 2):
        ws3.cell(row=i, column=1, value=safe_cell(tag["tag_name"]))
        ws3.cell(row=i, column=2, value=tag["cases_count"])
        ws3.cell(row=i, column=3, value="Да" if tag["is_system"] else "Нет")
    ws3.column_dimensions["A"].width = 25
    ws3.column_dimensions["B"].width = 12
    ws3.column_dimensions["C"].width = 12

    ws4 = wb.create_sheet("Автопроверки")
    checks = get_checks_report(project_path, file_id)
    for col, header in enumerate(["Проверка", "Срабатываний"], 1):
        ws4.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, check in enumerate(checks, 2):
        ws4.cell(row=i, column=1, value=safe_cell(check["check_name"]))
        ws4.cell(row=i, column=2, value=check["count"])
    ws4.column_dimensions["A"].width = 30
    ws4.column_dimensions["B"].width = 15

    _atomic_save(wb, out)
    return True
