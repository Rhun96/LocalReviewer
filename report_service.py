"""Отчёты: единый доступ к БД, валидация limit, корректный GROUP BY."""
import logging
from database import db

logger = logging.getLogger(__name__)


def get_files_list(project_path: str) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT file_id, file_name FROM files ORDER BY imported_at DESC")
        return [dict(row) for row in cursor.fetchall()]


def get_overall_report(project_path: str, file_id=None) -> dict:
    """Сводка по base-семантике: свои коды профилей складываются в base."""
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
        if file_id:
            file_condition = " WHERE c.file_id = ?"
            params.append(file_id)
        cursor.execute(f"SELECT COUNT(*) as total FROM cases c{file_condition}", params)
        total = cursor.fetchone()["total"]
        cursor.execute(f"""
            SELECT COALESCE(a.status, 'unreviewed') as status, COUNT(*) as count
            FROM cases c
            LEFT JOIN annotations a ON c.case_id = a.case_id
            {file_condition}
            GROUP BY COALESCE(a.status, 'unreviewed')
        """, params)
        status_counts = {row["status"]: row["count"] for row in cursor.fetchall()}
    buckets = {"unreviewed": 0, "good": 0, "bad": 0, "uncertain": 0,
               "duplicate": 0, "skip": 0}
    by_code = dict(status_counts)
    for code, count in status_counts.items():
        base = mapping.get(code, code)
        if base in buckets:
            buckets[base] += count
        # неизвестный base (битая разметка) — виден только в by_code
    buckets["total"] = total
    buckets["reviewed"] = total - buckets["unreviewed"]
    buckets["by_code"] = by_code
    return buckets


def get_files_report(project_path: str) -> list:
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    # Свои коды с base 'unreviewed' — тоже непроверенные.
    unrev_codes = ["unreviewed"] + [c for c, b in mapping.items()
                                    if b == "unreviewed" and c != "unreviewed"]
    ph = ",".join(["?"] * len(unrev_codes))
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute(f"""
            SELECT
                f.file_id,
                f.file_name,
                f.row_count,
                f.imported_at,
                COUNT(DISTINCT c.case_id) as cases_count,
                COUNT(DISTINCT CASE WHEN COALESCE(a.status, 'unreviewed')
                      NOT IN ({ph})
                      THEN c.case_id END) as reviewed_count
            FROM files f
            LEFT JOIN cases c ON f.file_id = c.file_id
            LEFT JOIN annotations a ON c.case_id = a.case_id
            GROUP BY f.file_id, f.file_name, f.row_count, f.imported_at
            ORDER BY f.imported_at DESC
        """, unrev_codes)
        return [dict(row) for row in cursor.fetchall()]


def get_tags_report(project_path: str, file_id=None) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
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
            GROUP BY t.tag_id, t.tag_name, t.is_system
            ORDER BY cases_count DESC, t.tag_name
        """, params)
        return [dict(row) for row in cursor.fetchall()]


def get_checks_report(project_path: str, file_id=None) -> list:
    """Срабатывания + precision по вердиктам (ТЗ §75-76, feedback loop)."""
    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
        if file_id:
            file_condition = " WHERE cc.case_id IN (SELECT case_id FROM cases WHERE file_id = ?)"
            params.append(file_id)
        cursor.execute(f"""
            SELECT
                cc.check_code as check_code,
                MIN(cc.check_name) as check_name,
                COUNT(*) as count,
                COUNT(DISTINCT CASE WHEN v.verdict='confirmed'
                      THEN v.case_id END) as confirmed,
                COUNT(DISTINCT CASE WHEN v.verdict='false_positive'
                      THEN v.case_id END) as false_positive
            FROM case_checks cc
            LEFT JOIN case_check_verdicts v
              ON v.case_id = cc.case_id AND v.check_code = cc.check_code
            {file_condition}
            GROUP BY cc.check_code
            ORDER BY count DESC
        """, params)
        out = []
        for row in cursor.fetchall():
            d = dict(row)
            total_v = (d["confirmed"] or 0) + (d["false_positive"] or 0)
            d["precision"] = (d["confirmed"] / total_v) if total_v else None
            out.append(d)
        return out


def get_history_report(project_path: str, limit: int = 100, file_id=None) -> list:
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        limit = 100
    limit = max(1, min(limit, 5000))
    with db(project_path) as conn:
        cursor = conn.cursor()
        file_condition = ""
        params: list = []
        if file_id:
            file_condition = " WHERE c.file_id = ?"
            params.append(file_id)
        params.append(limit)
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
        return [dict(row) for row in cursor.fetchall()]
