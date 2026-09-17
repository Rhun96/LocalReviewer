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


def _resolve_text_output(output_path: str, suffix: str) -> Path:
    p = Path(output_path)
    if not p.parent.exists():
        raise FileNotFoundError(f"Папка не найдена: {p.parent}")
    if p.suffix.lower() != suffix:
        raise ValueError(f"Файл экспорта должен иметь расширение {suffix}")
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


JSONL_BASE = ("id", "case_id", "query", "response", "status", "category",
              "subcategory", "severity", "comment")
JSONL_OPTIONAL = ("tags", "group", "file", "source_id", "reviewed_at")


def export_results_jsonl(project_path: str, output_path: str, file_id=None,
                         extra_fields: list | None = None) -> int:
    """Экспорт JSONL (ТЗ V2 §14, §35): один кейс — одна строка, UTF-8.

    Стабильная схема: base-поля всегда, extra — по выбору (tags/group/file/
    source_id/reviewed_at). id = source_id из маппинга, иначе case_id строкой.
    """
    import json as _json
    extra = [f for f in (extra_fields or []) if f in JSONL_OPTIONAL]
    out = _resolve_text_output(output_path, ".jsonl")
    tmp = str(out) + ".part"
    count = 0
    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
        if file_id:
            file_condition = " WHERE c.file_id = ?"
            params.append(file_id)
        cursor.execute(f"""
            SELECT
                c.case_id, c.source_id, c.primary_text, c.response_text,
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
        cols = [d[0] for d in cursor.description]
        with open(tmp, "w", encoding="utf-8") as fh:
            while True:
                batch = cursor.fetchmany(2000)
                if not batch:
                    break
                for r in batch:
                    row = dict(zip(cols, r, strict=True))
                    sid = (row["source_id"] or "").strip()
                    obj = {
                        "id": sid or str(row["case_id"]),
                        "case_id": row["case_id"],
                        "query": row["primary_text"] or "",
                        "response": row["response_text"] or "",
                        "status": row["status"],
                        "category": row["error_category"] or "",
                        "subcategory": row["error_subcategory"] or "",
                        "severity": row["error_severity"] or "",
                        "comment": row["review_comment"] or "",
                    }
                    if "tags" in extra:
                        obj["tags"] = []
                    if "group" in extra:
                        obj["group"] = row["group_name"] or ""
                    if "file" in extra:
                        obj["file"] = row["file_name"] or ""
                    if "source_id" in extra:
                        obj["source_id"] = sid
                    if "reviewed_at" in extra:
                        obj["reviewed_at"] = row["reviewed_at"] or ""
                    fh.write(_json.dumps(obj, ensure_ascii=False) + "\n")
                    count += 1
    if "tags" in extra:
        # Теги — вторым проходом по чанкам (таблица может быть большой).
        with db(project_path) as conn:
            cursor = conn.cursor()
            ids = [r["case_id"] for r in cursor.execute(
                "SELECT case_id FROM cases" +
                (" WHERE file_id = ?" if file_id else ""),
                ([file_id] if file_id else [])).fetchall()]
            tag_map: dict = {}
            for i in range(0, len(ids), 2000):
                chunk = ids[i:i + 2000]
                ph = ",".join(["?"] * len(chunk))
                for t in cursor.execute(f"""
                        SELECT ct.case_id, tg.tag_name FROM case_tags ct
                        JOIN tags tg ON tg.tag_id = ct.tag_id
                        WHERE ct.case_id IN ({ph})
                    """, chunk).fetchall():
                    tag_map.setdefault(t["case_id"], []).append(t["tag_name"])
        import json as _json2
        lines = open(tmp, encoding="utf-8").read().splitlines()
        with open(tmp, "w", encoding="utf-8") as fh:
            for line in lines:
                try:
                    obj = _json2.loads(line)
                except ValueError:
                    continue
                obj["tags"] = tag_map.get(obj.get("case_id"), [])
                fh.write(_json2.dumps(obj, ensure_ascii=False) + "\n")
    Path(tmp).replace(out)
    logger.info("exported %s jsonl rows -> %s", count, out)
    return count


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
