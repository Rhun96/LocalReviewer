from database import get_db_connection
from datetime import datetime


def get_files_list(project_path: str) -> list:
    """Возвращает список файлов проекта."""
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        cursor.execute("SELECT file_id, file_name FROM files ORDER BY imported_at DESC")
        files = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return files
    except Exception:
        return []


def get_overall_report(project_path: str, file_id=None) -> dict:
    """
    Общий отчёт по проекту.
    Если указан file_id — отчёт только по этому файлу.
    """
    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    file_condition = ""
    params = []
    if file_id:
        file_condition = " WHERE c.file_id = ?"
        params.append(file_id)

    # Всего кейсов
    cursor.execute(f"SELECT COUNT(*) as total FROM cases c{file_condition}", params)
    total = cursor.fetchone()['total']

    # По статусам
    cursor.execute(f"""
        SELECT COALESCE(a.status, 'unreviewed') as status, COUNT(*) as count
        FROM cases c
        LEFT JOIN annotations a ON c.case_id = a.case_id
        {file_condition}
        GROUP BY COALESCE(a.status, 'unreviewed')
    """, params)
    status_counts = {row['status']: row['count'] for row in cursor.fetchall()}
    conn.close()

    return {
        'total': total,
        'unreviewed': status_counts.get('unreviewed', 0),
        'good': status_counts.get('good', 0),
        'bad': status_counts.get('bad', 0),
        'uncertain': status_counts.get('uncertain', 0),
        'duplicate': status_counts.get('duplicate', 0),
        'skip': status_counts.get('skip', 0),
        'reviewed': total - status_counts.get('unreviewed', 0),
    }


def get_files_report(project_path: str) -> list:
    """Отчёт по файлам."""
    conn = get_db_connection(project_path)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT
            f.file_id,
            f.file_name,
            f.row_count,
            f.imported_at,
            COUNT(DISTINCT c.case_id) as cases_count,
            COUNT(DISTINCT CASE WHEN COALESCE(a.status, 'unreviewed') != 'unreviewed'
                  THEN c.case_id END) as reviewed_count
        FROM files f
        LEFT JOIN cases c ON f.file_id = c.file_id
        LEFT JOIN annotations a ON c.case_id = a.case_id
        GROUP BY f.file_id
        ORDER BY f.imported_at DESC
    """)
    files = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return files


def get_tags_report(project_path: str, file_id=None) -> list:
    """
    Отчёт по тегам.
    Если указан file_id — только по кейсам этого файла.
    """
    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    file_condition = ""
    params = []
    if file_id:
        file_condition = " AND ct.case_id IN (SELECT case_id FROM cases WHERE file_id = ?)"
        params.append(file_id)

    cursor.execute(f"""
        SELECT
            t.tag_id,
            t.tag_name,
            t.is_system,
            COUNT(ct.case_id) as cases_count
        FROM tags t
        LEFT JOIN case_tags ct ON t.tag_id = ct.tag_id{file_condition}
        GROUP BY t.tag_id
        ORDER BY cases_count DESC, t.tag_name
    """, params)
    tags = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return tags


def get_checks_report(project_path: str, file_id=None) -> list:
    """
    Отчёт по автопроверкам.
    Если указан file_id — только по кейсам этого файла.
    """
    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    file_condition = ""
    params = []
    if file_id:
        file_condition = " WHERE cc.case_id IN (SELECT case_id FROM cases WHERE file_id = ?)"
        params.append(file_id)

    cursor.execute(f"""
        SELECT
            check_code,
            check_name,
            COUNT(*) as count
        FROM case_checks cc
        {file_condition}
        GROUP BY check_code
        ORDER BY count DESC
    """, params)
    checks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return checks


def get_history_report(project_path: str, limit: int = 100, file_id=None) -> list:
    """История изменений."""
    conn = get_db_connection(project_path)
    cursor = conn.cursor()

    file_condition = ""
    params = [limit]
    if file_id:
        file_condition = " WHERE c.file_id = ?"
        params.insert(0, file_id)

    cursor.execute(f"""
        SELECT
            h.event_type,
            h.field_name,
            h.old_value,
            h.new_value,
            h.created_at,
            c.case_id
        FROM history h
        JOIN cases c ON h.case_id = c.case_id
        {file_condition}
        ORDER BY h.created_at DESC
        LIMIT ?
    """, params)
    events = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return events