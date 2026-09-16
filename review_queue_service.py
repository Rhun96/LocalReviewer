"""Умная очередь ревью (ТЗ §8-11): режимы + приоритет без ML + индикатор."""
import logging
from filter_service import build_filter_query
from database import db

logger = logging.getLogger(__name__)

QUEUE_MODES = ("normal", "unreviewed", "problematic")

SEV_WEIGHT = {"critical": 100, "error": 60, "warning": 20, "info": 5}

DEFAULT_WEIGHTS = {"w_crit": 100, "w_multi": 50, "w_single": 30,
                   "w_discuss": 30, "w_unrev": 10, "w_rev": -20}


def get_priority_weights(project_path: str) -> dict:
    """Настраиваемые веса приоритета (ТЗ §9). Хранятся в settings."""
    out = dict(DEFAULT_WEIGHTS)
    try:
        with db(project_path) as conn:
            rows = conn.cursor().execute(
                "SELECT key, value FROM settings WHERE key LIKE 'prio_w_%'").fetchall()
        for r in rows:
            short = r["key"][len("prio_"):]
            if short in out:
                try:
                    out[short] = int(r["value"])
                except (TypeError, ValueError):
                    pass
    except Exception as e:
        logger.warning("priority weights fallback: %s", e)
    return out


def compute_priority(has_checks: bool, max_sev: str, checks_count: int,
                     status: str, needs_discussion: bool = False,
                     weights: dict | None = None) -> tuple:
    """Возвращает (score, reasons). Формула из ТЗ §9, без ML."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        w.update({k: v for k, v in weights.items() if k in w})
    score, reasons = 0, []
    if max_sev in ("critical", "error"):
        score += w["w_crit"]
        reasons.append("критическая автопроверка")
    elif has_checks:
        score += w["w_multi"] if checks_count > 1 else w["w_single"]
        reasons.append(f"автопроверок: {checks_count}")
    if needs_discussion:
        score += w["w_discuss"]
        reasons.append("требует обсуждения")
    if status == "unreviewed":
        score += w["w_unrev"]
        reasons.append("статус не установлен")
    else:
        score += w["w_rev"]
    return score, reasons


def build_queue(project_path: str, mode: str = "normal", filters: dict = None) -> tuple:
    """Возвращает (ordered_ids, reasons_map)."""
    if mode not in QUEUE_MODES:
        mode = "normal"
    base_filters = dict(filters or {})
    if mode == "unreviewed":
        from review_profile_service import code_to_base as _ctb2
        _m = _ctb2(project_path)
        base_filters = dict(base_filters)
        base_filters["statuses"] = ["unreviewed"] + [
            c for c, b in _m.items() if b == "unreviewed" and c != "unreviewed"]

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
        weights = get_priority_weights(project_path)
        # Свои коды профилей: проверяемость — по base-семантике.
        from review_profile_service import code_to_base as _ctb
        _mapping = _ctb(project_path)
        # Проблемные первыми: подтягиваем checks + статусы одним проходом.
        # severity берём как MAX по весу (не произвольный GROUP BY).
        scored = []
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            rows = cur.execute(f"""
                SELECT c.case_id, COALESCE(a.status,'unreviewed') AS status,
                       MAX(CASE cc.severity
                           WHEN 'critical' THEN 100 WHEN 'error' THEN 60
                           WHEN 'warning' THEN 20 WHEN 'info' THEN 5 ELSE 0 END
                       ) AS max_w,
                       COUNT(cc.check_id) AS n
                FROM cases c
                LEFT JOIN annotations a ON a.case_id = c.case_id
                LEFT JOIN case_checks cc ON cc.case_id = c.case_id
                WHERE c.case_id IN ({ph})
                GROUP BY c.case_id
            """, chunk).fetchall()
            discuss = {r["case_id"] for r in cur.execute(f"""
                SELECT ct.case_id FROM case_tags ct
                JOIN tags t ON t.tag_id = ct.tag_id
                WHERE t.tag_code = 'needs_discussion' AND ct.case_id IN ({ph})
            """, chunk).fetchall()}
            for r in rows:
                n = r["n"] or 0
                max_w = r["max_w"] or 0
                if max_w >= 60:
                    max_sev = "error"
                elif max_w >= 20:
                    max_sev = "warning"
                elif n:
                    max_sev = "info"
                else:
                    max_sev = "info"
                score, reasons = compute_priority(
                    bool(n), max_sev, n,
                    "unreviewed" if _mapping.get(r["status"], r["status"])
                    == "unreviewed" else "good",
                    r["case_id"] in discuss, weights)
                scored.append((r["case_id"], score, reasons))
        # исходный порядок как tiebreak
        order = {cid: i for i, cid in enumerate(ids)}
        scored.sort(key=lambda t: (-t[1], order.get(t[0], 0)))
        return [c for c, _, _ in scored], {c: r for c, _, r in scored}


def queue_stats(project_path: str, file_id=None) -> dict:
    """Для индикатора: всего / проблемных / обработанных.

    file_id задан → статистика только по файлу (режим ревью одного файла),
    иначе — по всему проекту (режим «все файлы»).
    Обработан = base(status) != 'unreviewed' (свои коды профилей учитываются).
    """
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    unrev_codes = ["unreviewed"] + [c for c, b in mapping.items()
                                    if b == "unreviewed" and c != "unreviewed"]
    bad_codes = [c for c, b in mapping.items() if b == "bad"] or ["bad"]
    ph = ",".join(["?"] * len(unrev_codes))
    bad_ph = ",".join(["?"] * len(bad_codes))
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
            WHERE COALESCE(a.status, 'unreviewed') NOT IN ({ph}) {fcond_ann}
        """, (*unrev_codes, *p)).fetchone()["c"]
        bad = cur.execute(f"""
            SELECT COUNT(*) AS c FROM annotations a
            JOIN cases c ON c.case_id = a.case_id
            WHERE COALESCE(a.status, 'unreviewed') IN ({bad_ph}) {fcond_ann}
        """, (*bad_codes, *p)).fetchone()["c"]
        problematic = cur.execute(f"""
            SELECT COUNT(DISTINCT cc.case_id) AS c FROM case_checks cc
            JOIN cases c ON c.case_id = cc.case_id
            WHERE 1=1 {fcond_cc}
        """, p).fetchone()["c"]
    return {"total": total, "reviewed": reviewed, "problematic": problematic,
            "bad": bad, "remaining": max(0, total - reviewed), "file_id": file_id}
