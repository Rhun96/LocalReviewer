"""Логика фильтрации: EXISTS вместо декартовых JOIN, экранирование LIKE, пагинация.

filter_from() — единый строитель условий для кейс-вида, таблицы и очередей,
чтобы фильтры везде работали одинаково (ТЗ §28).
"""
import logging
from database import db

logger = logging.getLogger(__name__)

BASE_FROM = """
    FROM cases c
    JOIN files f ON c.file_id = f.file_id
    LEFT JOIN annotations a ON c.case_id = a.case_id
"""


def _escape_like(s: str) -> str:
    return s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def filter_from(filters: dict):
    """Возвращает (extra_joins, conditions, params) для любого SELECT ... FROM cases c ..."""
    conditions: list = []
    params: list = []
    extra_joins = ""

    statuses = (filters or {}).get("statuses", [])
    if statuses:
        placeholders = ",".join(["?"] * len(statuses))
        conditions.append(f"COALESCE(a.status, 'unreviewed') IN ({placeholders})")
        params.extend(statuses)

    file_id = (filters or {}).get("file_id")
    if file_id:
        conditions.append("c.file_id = ?")
        params.append(file_id)

    has_comment = (filters or {}).get("has_comment")
    if has_comment is True:
        conditions.append("a.comment IS NOT NULL AND a.comment != ''")
    elif has_comment is False:
        conditions.append("(a.comment IS NULL OR a.comment = '')")

    tags = (filters or {}).get("tags", [])
    if tags:
        placeholders = ",".join(["?"] * len(tags))
        conditions.append(f"""EXISTS (
            SELECT 1 FROM case_tags ct
            JOIN tags t ON ct.tag_id = t.tag_id
            WHERE ct.case_id = c.case_id AND t.tag_id IN ({placeholders})
        )""")
        params.extend(tags)

    checks = (filters or {}).get("checks", [])
    if checks:
        placeholders = ",".join(["?"] * len(checks))
        conditions.append(f"""EXISTS (
            SELECT 1 FROM case_checks cc
            WHERE cc.case_id = c.case_id AND cc.check_code IN ({placeholders})
        )""")
        params.extend(checks)

    check_severities = (filters or {}).get("check_severities", [])
    if check_severities:
        placeholders = ",".join(["?"] * len(check_severities))
        conditions.append(f"""EXISTS (
            SELECT 1 FROM case_checks cc
            WHERE cc.case_id = c.case_id AND cc.severity IN ({placeholders})
        )""")
        params.extend(check_severities)

    error_category_id = (filters or {}).get("error_category_id")
    if error_category_id:
        conditions.append("""EXISTS (
            SELECT 1 FROM case_errors e
            WHERE e.case_id = c.case_id
              AND (e.category_id = ? OR e.subcategory_id = ?)
        )""")
        params.extend([error_category_id, error_category_id])

    error_severities = (filters or {}).get("error_severities", [])
    if error_severities:
        placeholders = ",".join(["?"] * len(error_severities))
        conditions.append(f"""EXISTS (
            SELECT 1 FROM case_errors e
            WHERE e.case_id = c.case_id AND e.severity IN ({placeholders})
        )""")
        params.extend(error_severities)

    search_text = ((filters or {}).get("search_text") or "").strip()
    if search_text:
        esc = _escape_like(search_text)
        conditions.append("(c.primary_text LIKE ? ESCAPE '\\' "
                          "OR c.response_text LIKE ? ESCAPE '\\')")
        params.extend([f"%{esc}%", f"%{esc}%"])

    return extra_joins, conditions, params


def build_filter_query(filters: dict):
    _joins, conditions, params = filter_from(filters)
    query = """
        SELECT DISTINCT c.case_id
        FROM cases c
        JOIN files f ON c.file_id = f.file_id
        LEFT JOIN annotations a ON c.case_id = a.case_id
    """
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY f.imported_at, c.row_index"
    return query, params


def get_filtered_case_ids(project_path: str, filters: dict,
                            limit: int = 0, offset: int = 0) -> list:
    """Ошибки БД пробрасываются (не маскируются под пустой результат)."""
    if not filters:
        return get_all_case_ids(project_path, limit=limit, offset=offset)
    query, params = build_filter_query(filters)
    if limit and limit > 0:
        query += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [row["case_id"] for row in cursor.fetchall()]


def get_all_case_ids(project_path: str, limit: int = 0, offset: int = 0) -> list:
    query = """
        SELECT c.case_id
        FROM cases c
        JOIN files f ON c.file_id = f.file_id
        ORDER BY f.imported_at, c.row_index
    """
    params: list = []
    if limit and limit > 0:
        query += " LIMIT ? OFFSET ?"
        params.extend([int(limit), int(offset)])
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return [row["case_id"] for row in cursor.fetchall()]


def count_filtered_cases(project_path: str, filters: dict) -> int:
    """Быстрый COUNT для индикатора «Найдено: N» без вытягивания id."""
    _joins, conditions, params = filter_from(filters or {})
    query = "SELECT COUNT(DISTINCT c.case_id) AS total " + BASE_FROM
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute(query, params)
        return cursor.fetchone()["total"]
