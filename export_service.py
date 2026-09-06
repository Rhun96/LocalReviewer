import json
from datetime import datetime
from pathlib import Path
from database import get_db_connection


def export_results_to_xlsx(project_path: str, output_path: str, file_id=None):
    """
    Экспортирует результаты разметки в Excel.
    Если указан file_id — только кейсы этого файла.
    """
    import openpyxl
    from openpyxl.styles import Font, PatternFill, Alignment

    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    file_condition = ""
    params = []
    if file_id:
        file_condition = " WHERE c.file_id = ?"
        params.append(file_id)

    cursor.execute(f"""
        SELECT
            c.case_id,
            c.row_index,
            c.source_id,
            c.primary_text,
            c.response_text,
            c.group_name,
            c.comment_from_source,
            c.raw_json,
            f.file_name,
            COALESCE(a.status, 'unreviewed') as status,
            a.comment as review_comment,
            a.updated_at as reviewed_at
        FROM cases c
        JOIN files f ON c.file_id = f.file_id
        LEFT JOIN annotations a ON c.case_id = a.case_id
        {file_condition}
        ORDER BY f.imported_at, c.row_index
    """, params)
    rows = cursor.fetchall()

    # Загружаем теги
    case_ids = [row['case_id'] for row in rows]
    tags_map = {}
    if case_ids:
        placeholders = ','.join(['?' for _ in case_ids])
        cursor.execute(f"""
            SELECT ct.case_id, t.tag_name
            FROM case_tags ct
            JOIN tags t ON ct.tag_id = t.tag_id
            WHERE ct.case_id IN ({placeholders})
        """, case_ids)
        for row in cursor.fetchall():
            case_id = row['case_id']
            if case_id not in tags_map:
                tags_map[case_id] = []
            tags_map[case_id].append(row['tag_name'])

    conn.close()

    # Создаём книгу Excel
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Результаты разметки"

    headers = [
        "№", "Файл", "Строка", "Запрос", "Ответ", "Группа",
        "Статус", "Теги", "Комментарий", "Дата проверки"
    ]

    header_font = Font(bold=True, color="00FF41")
    header_fill = PatternFill(
        start_color="003300", end_color="003300", fill_type="solid"
    )

    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    status_names = {
        'unreviewed': 'Не проверено',
        'good': 'Хорошо',
        'bad': 'Плохо',
        'uncertain': 'Сомневаюсь',
        'duplicate': 'Дубль',
        'skip': 'Пропустить',
    }

    for row_idx, row in enumerate(rows, 2):
        tags = tags_map.get(row['case_id'], [])
        ws.cell(row=row_idx, column=1, value=row_idx - 1)
        ws.cell(row=row_idx, column=2, value=row['file_name'])
        ws.cell(row=row_idx, column=3, value=row['row_index'] + 1)
        ws.cell(row=row_idx, column=4, value=row['primary_text'] or '')
        ws.cell(row=row_idx, column=5, value=row['response_text'] or '')
        ws.cell(row=row_idx, column=6, value=row['group_name'] or '')
        ws.cell(
            row=row_idx, column=7,
            value=status_names.get(row['status'], row['status'])
        )
        ws.cell(row=row_idx, column=8, value=', '.join(tags))
        ws.cell(row=row_idx, column=9, value=row['review_comment'] or '')
        ws.cell(row=row_idx, column=10, value=row['reviewed_at'] or '')

    # Ширина колонок
    column_widths = [5, 20, 8, 50, 50, 15, 12, 25, 30, 20]
    for i, width in enumerate(column_widths, 1):
        col_letter = chr(64 + i) if i <= 26 else 'A' + chr(64 + i - 26)
        ws.column_dimensions[col_letter].width = width

    wb.save(output_path)
    return len(rows)


def export_report_to_xlsx(project_path: str, output_path: str, file_id=None):
    """
    Экспортирует отчёт в Excel.
    Если указан file_id — отчёт только по этому файлу.
    """
    import openpyxl
    from openpyxl.styles import Font
    from report_service import (
        get_overall_report, get_files_report, get_tags_report, get_checks_report
    )

    wb = openpyxl.Workbook()

    # Лист 1: Общий отчёт
    ws1 = wb.active
    ws1.title = "Общий отчёт"
    overall = get_overall_report(project_path, file_id)

    overall_data = [
        ("Всего кейсов", overall['total']),
        ("Проверено", overall['reviewed']),
        ("Не проверено", overall['unreviewed']),
        ("Хорошо", overall['good']),
        ("Плохо", overall['bad']),
        ("Сомневаюсь", overall['uncertain']),
        ("Дубль", overall['duplicate']),
        ("Пропущено", overall['skip']),
    ]

    ws1.cell(row=1, column=1, value="Показатель").font = Font(bold=True)
    ws1.cell(row=1, column=2, value="Значение").font = Font(bold=True)
    for i, (name, value) in enumerate(overall_data, 2):
        ws1.cell(row=i, column=1, value=name)
        ws1.cell(row=i, column=2, value=value)
    ws1.column_dimensions['A'].width = 20
    ws1.column_dimensions['B'].width = 15

    # Лист 2: По файлам
    ws2 = wb.create_sheet("По файлам")
    files = get_files_report(project_path)
    file_headers = ["Файл", "Всего", "Проверено", "Дата импорта"]
    for col, header in enumerate(file_headers, 1):
        ws2.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, f in enumerate(files, 2):
        ws2.cell(row=i, column=1, value=f['file_name'])
        ws2.cell(row=i, column=2, value=f['cases_count'])
        ws2.cell(row=i, column=3, value=f['reviewed_count'])
        ws2.cell(row=i, column=4, value=f['imported_at'])
    ws2.column_dimensions['A'].width = 30
    ws2.column_dimensions['B'].width = 12
    ws2.column_dimensions['C'].width = 12
    ws2.column_dimensions['D'].width = 20

    # Лист 3: По тегам
    ws3 = wb.create_sheet("По тегам")
    tags = get_tags_report(project_path, file_id)
    tag_headers = ["Тег", "Кейсов", "Системный"]
    for col, header in enumerate(tag_headers, 1):
        ws3.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, tag in enumerate(tags, 2):
        ws3.cell(row=i, column=1, value=tag['tag_name'])
        ws3.cell(row=i, column=2, value=tag['cases_count'])
        ws3.cell(row=i, column=3, value="Да" if tag['is_system'] else "Нет")
    ws3.column_dimensions['A'].width = 25
    ws3.column_dimensions['B'].width = 12
    ws3.column_dimensions['C'].width = 12

    # Лист 4: Автопроверки
    ws4 = wb.create_sheet("Автопроверки")
    checks = get_checks_report(project_path, file_id)
    check_headers = ["Проверка", "Срабатываний"]
    for col, header in enumerate(check_headers, 1):
        ws4.cell(row=1, column=col, value=header).font = Font(bold=True)
    for i, check in enumerate(checks, 2):
        ws4.cell(row=i, column=1, value=check['check_name'])
        ws4.cell(row=i, column=2, value=check['count'])
    ws4.column_dimensions['A'].width = 30
    ws4.column_dimensions['B'].width = 15

    wb.save(output_path)
    return True