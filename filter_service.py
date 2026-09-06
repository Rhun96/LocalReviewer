from database import get_db_connection


def get_filtered_case_ids(project_path: str, filters: dict) -> list:
    if not filters:
        return get_all_case_ids(project_path)

    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    query = """
        SELECT DISTINCT c.case_id
        FROM cases c
        JOIN files f ON c.file_id = f.file_id
        LEFT JOIN annotations a ON c.case_id = a.case_id
    """
    conditions = []
    params = []

    # Фильтр по статусам
    statuses = filters.get('statuses', [])
    if statuses:
        placeholders = ','.join(['?' for _ in statuses])
        conditions.append(f"COALESCE(a.status, 'unreviewed') IN ({placeholders})")
        params.extend(statuses)

    # Фильтр по файлу
    file_id = filters.get('file_id')
    if file_id:
        conditions.append("c.file_id = ?")
        params.append(file_id)

    # Фильтр по комментарию
    has_comment = filters.get('has_comment')
    if has_comment is True:
        conditions.append("a.comment IS NOT NULL AND a.comment != ''")
    elif has_comment is False:
        conditions.append("(a.comment IS NULL OR a.comment = '')")

    # Фильтр по тегам
    tags = filters.get('tags', [])
    if tags:
        placeholders = ','.join(['?' for _ in tags])
        query += f"""
            JOIN case_tags ct ON c.case_id = ct.case_id
            JOIN tags t ON ct.tag_id = t.tag_id
        """
        conditions.append(f"t.tag_id IN ({placeholders})")
        params.extend(tags)

    # Фильтр по автопроверкам
    checks = filters.get('checks', [])
    if checks:
        placeholders = ','.join(['?' for _ in checks])
        query += f"""
            JOIN case_checks cc ON c.case_id = cc.case_id
        """
        conditions.append(f"cc.check_code IN ({placeholders})")
        params.extend(checks)

    # Текстовый поиск
    search_text = filters.get('search_text', '')
    if search_text:
        conditions.append("(c.primary_text LIKE ? OR c.response_text LIKE ?)")
        sp = f"%{search_text}%"
        params.extend([sp, sp])

    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY f.imported_at, c.row_index"

    try:
        cursor.execute(query, params)
        case_ids = [row['case_id'] for row in cursor.fetchall()]
        conn.close()
        return case_ids
    except Exception:
        conn.close()
        return []


def get_all_case_ids(project_path: str) -> list:
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT c.case_id
            FROM cases c
            JOIN files f ON c.file_id = f.file_id
            ORDER BY f.imported_at, c.row_index
        """)
        case_ids = [row['case_id'] for row in cursor.fetchall()]
        conn.close()
        return case_ids
    except Exception:
        return []