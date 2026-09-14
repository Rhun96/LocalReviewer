"""Умная очередь ревью (ТЗ §8-11): режимы + приоритет без ML + индикатор."""
import logging
from filter_service import build_filter_query
from database import db

logger = logging.getLogger(__name__)

QUEUE_MODES = ("normal", "unreviewed", "problematic")

SEV_WEIGHT = {"critical": 100, "error": 60, "warning": 20, "info": 5}


def compute_priority(has_checks: bool, max_sev: str, checks_count: int,
                     status: str, needs_discussion: bool = False) -> tuple:
    """Возвращает (score, reasons). Формула из ТЗ §9, без ML."""
    score, reasons = 0, []
    if max_sev in ("critical", "error"):
        score += 100
        reasons.append("критическая автопроверка")
    elif has_checks:
        score += 50 if checks_count > 1 else 30
        reasons.append(f"автопроверок: {checks_count}")
    if needs_discussion:
        score += 30
        reasons.append("требует обсуждения")
    if status == "unreviewed":
        score += 10
        reasons.append("статус не установлен")
    else:
        score -= 20
    return score, reasons


def build_queue(project_path: str, mode: str = "normal", filters: dict = None) -> tuple:
    """Возвращает (ordered_ids, reasons_map)."""
    if mode not in QUEUE_MODES:
        mode = "normal"
    base_filters = dict(filters or {})
    if mode == "unreviewed":
        base_filters = dict(base_filters)
        base_filters["statuses"] = ["unreviewed"]

    if base_filters:
        query, params = build_filter_query(base_filters)
    else:
        query, params = ("SELECT c.case_id FROM cases c "
                         "JOIN files f ON c.file_id = f.file_id "
                         "ORDER BY f.imported_at, c.row_index"), []

    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(query, params)
        ids = [r["case_id"] for r in cur.fetchall()]
        if not ids or mode == "normal":
            return ids, {}
        # Проблемные первыми: подтягиваем checks + статусы одним проходом
        scored = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            rows = cur.execute(f"""
                SELECT c.case_id, COALESCE(a.status,'unreviewed') AS status,
                       cc.severity AS sev, COUNT(cc.check_id) AS n
                FROM cases c
                LEFT JOIN annotations a ON a.case_id = c.case_id
                LEFT JOIN case_checks cc ON cc.case_id = c.case_id
                WHERE c.case_id IN ({ph})
                GROUP BY c.case_id
            """, chunk).fetchall()
            for r in rows:
                n = r["n"] or 0
                score, reasons = compute_priority(bool(n), r["sev"] or "info", n, r["status"])
                scored.append((r["case_id"], score, reasons))
        # исходный порядок как tiebreak
        order = {cid: i for i, cid in enumerate(ids)}
        scored.sort(key=lambda t: (-t[1], order.get(t[0], 0)))
        return [c for c, _, _ in scored], {c: r for c, _, r in scored}


def queue_stats(project_path: str, file_id=None) -> dict:
    """Для индикатора: всего / проблемных / обработанных.

    file_id задан → статистика только по файлу (режим ревью одного файла),
    иначе — по всему проекту (режим «все файлы»).
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        fcond_cases = "WHERE c.file_id = ?" if file_id else ""
        fcond_ann = "AND c.file_id = ?" if file_id else ""
        fcond_cc = "AND c.file_id = ?" if file_id else ""
        p = [file_id] if file_id else []
        total = cur.execute(
            f"SELECT COUNT(*) AS c FROM cases c {fcond_cases}", p).fetchone()["c"]
        reviewed = cur.execute(f"""
            SELECT COUNT(*) AS c FROM annotations a
            JOIN cases c ON c.case_id = a.case_id
            WHERE a.status != 'unreviewed' {fcond_ann}
        """, p).fetchone()["c"]
        problematic = cur.execute(f"""
            SELECT COUNT(DISTINCT cc.case_id) AS c FROM case_checks cc
            JOIN cases c ON c.case_id = cc.case_id
            WHERE 1=1 {fcond_cc}
        """, p).fetchone()["c"]
    return {"total": total, "reviewed": reviewed, "problematic": problematic,
            "remaining": max(0, total - reviewed), "file_id": file_id}
