import json
import hashlib
from datetime import datetime
from pathlib import Path
from database import get_db_connection


def compute_content_hash(row_data: dict) -> str:
    content = json.dumps(row_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(content.encode()).hexdigest()


def import_file(
    project_path: str,
    file_path: str,
    file_type: str,
    sheet_name: str,
    header_row: int,
    mapping: dict,
    data: list
) -> tuple:
    """
    Импортирует файл в базу данных проекта.
    Если несколько столбцов назначены в одну роль — их значения объединяются.
    Возвращает: (file_id, cases_count)
    """
    conn = get_db_connection(project_path)
    cursor = conn.cursor()
    now = datetime.now().isoformat()
    file_name = Path(file_path).name

    cursor.execute("""
        INSERT INTO files (
            file_name, file_path, file_type, sheet_name,
            header_row, row_count, imported_at, mapping_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        file_name, file_path, file_type, sheet_name,
        header_row, len(data), now,
        json.dumps(mapping, ensure_ascii=False)
    ))
    file_id = cursor.lastrowid

    # Группируем колонки по ролям
    role_columns = {}
    metadata_cols = []
    for col_name, role in mapping.items():
        if role == "metadata":
            metadata_cols.append(col_name)
        else:
            if role not in role_columns:
                role_columns[role] = []
            role_columns[role].append(col_name)

    def get_role_value(row, role):
        """Возвращает значение для роли. Если несколько колонок — объединяет."""
        cols = role_columns.get(role, [])
        if not cols:
            return None
        values = []
        for col in cols:
            v = row.get(col, '')
            if v is not None and str(v).strip():
                values.append(str(v).strip())
        if not values:
            return None
        if len(values) == 1:
            return values[0]
        return "\n\n".join(values)

    cases_count = 0
    for row_index, row in enumerate(data):
        primary_text = get_role_value(row, 'primary_text') or ''
        response_text = get_role_value(row, 'response_text')
        group_name = get_role_value(row, 'group_name')
        source_id = get_role_value(row, 'source_id')
        comment_from_source = get_role_value(row, 'comment_source')

        # Метаданные
        metadata = {}
        for col in metadata_cols:
            metadata[col] = row.get(col, '')

        # Дополнительные роли в метаданные
        for role_key in ['ticket_number', 'product', 'operator_response']:
            val = get_role_value(row, role_key)
            if val:
                metadata[role_key] = val

        raw_json = json.dumps(row, ensure_ascii=False)
        content_hash = compute_content_hash(row)

        cursor.execute("""
            INSERT INTO cases (
                file_id, row_index, source_id, content_hash,
                primary_text, response_text, group_name,
                comment_from_source, metadata_json, raw_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_id, row_index, source_id, content_hash,
            primary_text, response_text, group_name,
            comment_from_source,
            json.dumps(metadata, ensure_ascii=False) if metadata else None,
            raw_json, now
        ))
        case_id = cursor.lastrowid

        cursor.execute("""
            INSERT INTO annotations (case_id, status, comment, updated_at)
            VALUES (?, 'unreviewed', NULL, ?)
        """, (case_id, now))

        cases_count += 1

    conn.commit()
    conn.close()
    return file_id, cases_count