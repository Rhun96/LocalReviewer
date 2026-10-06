"""Центр «Требует внимания» (W4): только реально применимые состояния.

Каждый пункт: {code, level, title, count, detail, action}.
action: {"screen": ..., "filters"|...} — dashboard превращает в переход.
Тяжёлые пары (противоречия/дубли) считаются отдельно, в фоне:
fast_snapshot (мгновенно) + heavy_counts (O(n^2), с cancel).
"""
import logging

from database import db

logger = logging.getLogger(__name__)


def _unrev_codes(project_path: str) -> list:
    from review_profile_service import code_to_base
    try:
        mapping = code_to_base(project_path) or {}
    except Exception:
        mapping = {}
    return ["unreviewed"] + [c for c, b in mapping.items()
                             if b == "unreviewed" and c != "unreviewed"]


def _bad_codes(project_path: str) -> list:
    from review_profile_service import code_to_base
    try:
        mapping = code_to_base(project_path) or {}
    except Exception:
        mapping = {}
    return [c for c, b in mapping.items() if b == "bad"] or ["bad"]


def _file_cond(file_id, alias="c"):
    if file_id:
        return f"AND {alias}.file_id = ?", [file_id]
    return "", []


def fast_snapshot(project_path: str, file_id=None) -> list:
    """Мгновенные детекторы (COUNT-запросы). Пусто — всё спокойно."""
    out = []
    unrev = _unrev_codes(project_path)
    bad = _bad_codes(project_path)
    uph = ",".join(["?"] * len(unrev))
    bph = ",".join(["?"] * len(bad))
    fc, fp = _file_cond(file_id)
    bc, bp = _file_cond(file_id, "b")
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            n_unrev = cur.execute(f"""
                SELECT COUNT(*) AS c FROM cases c JOIN files f
                    ON f.file_id = c.file_id
                WHERE COALESCE(c.hidden, 0) = 0 {fc}
                  AND COALESCE((SELECT status FROM annotations a
                                WHERE a.case_id = c.case_id),
                               'unreviewed') IN ({uph})
            """, (*fp, *unrev)).fetchone()["c"]
            if n_unrev:
                out.append({
                    "code": "unreviewed", "level": "warning",
                    "title": "Ожидают проверки",
                    "count": n_unrev,
                    "detail": "кейсы без вердикта",
                    "action": {"screen": "review",
                               "filters": {"statuses": ["unreviewed"]}}})
            n_new = cur.execute(f"""
                SELECT COUNT(*) AS c FROM cases c JOIN files f
                    ON f.file_id = c.file_id
                WHERE COALESCE(c.hidden, 0) = 0 {fc}
                  AND substr(c.created_at, 1, 10) >= date('now', '-7 days')
                  AND COALESCE((SELECT status FROM annotations a
                                WHERE a.case_id = c.case_id),
                               'unreviewed') IN ({uph})
            """, (*fp, *unrev)).fetchone()["c"]
            if n_new:
                out.append({
                    "code": "new_cases", "level": "info",
                    "title": "Новые непроверенные (7 дней)",
                    "count": n_new,
                    "detail": "свежий импорт ждёт разбор",
                    "action": {"screen": "review",
                               "filters": {"statuses": ["unreviewed"]}}})
            bad_nocause = [r["case_id"] for r in cur.execute(f"""
                SELECT c.case_id FROM cases c JOIN files f
                    ON f.file_id = c.file_id
                LEFT JOIN annotations a ON a.case_id = c.case_id
                LEFT JOIN case_errors e ON e.case_id = c.case_id
                WHERE COALESCE(c.hidden, 0) = 0 {fc}
                  AND COALESCE(a.status, 'unreviewed') IN ({bph})
                  AND e.case_id IS NULL
            """, (*fp, *bad)).fetchall()]
            if bad_nocause:
                out.append({
                    "code": "bad_no_cause", "level": "critical",
                    "title": "Плохие без причины",
                    "count": len(bad_nocause),
                    "detail": "из Bad без причины не уйти",
                    "action": {"screen": "review",
                               "filters": {"case_ids": bad_nocause}}})
            try:
                bugs_open = cur.execute("""
                    SELECT bug_id, title FROM bug_reports
                    WHERE COALESCE(status, '') NOT IN
                        ('Fixed', 'Rejected', 'Duplicate')
                """).fetchall()
            except Exception:
                bugs_open = []
            if bugs_open:
                try:
                    linked = {r["bug_id"] for r in cur.execute(
                        "SELECT DISTINCT bug_id FROM bug_report_cases"
                        ).fetchall()}
                except Exception:
                    linked = set()
                lonely = [r for r in bugs_open
                          if r["bug_id"] not in linked]
                out.append({
                    "code": "bugs_open", "level": "warning",
                    "title": "Открытые баги",
                    "count": len(bugs_open),
                    "detail": "требуют работы",
                    "action": {"screen": "bugs"}})
                if lonely:
                    out.append({
                        "code": "bugs_lonely", "level": "warning",
                        "title": "Баги без кейсов",
                        "count": len(lonely),
                        "detail": "не к чему привязаться",
                        "action": {"screen": "bugs"}})
            try:
                hanging = cur.execute("""
                    SELECT regression_id, name FROM regression_runs
                    WHERE COALESCE(gate_result, '') = ''
                """).fetchall()
            except Exception:
                hanging = []
            if hanging:
                out.append({
                    "code": "runs_hanging", "level": "warning",
                    "title": "Незавершённые запуски",
                    "count": len(hanging),
                    "detail": "замеры без gate",
                    "action": {"screen": "launches"}})
            try:
                bad_runs = cur.execute("""
                    SELECT COUNT(*) AS c,
                           COALESCE(SUM(regressions), 0) AS r
                    FROM regression_runs
                    WHERE gate_result = 'FAIL'
                      AND substr(created_at, 1, 10) >= date('now', '-30 days')
                """).fetchone()
            except Exception:
                bad_runs = None
            if bad_runs and (bad_runs["c"] or 0):
                out.append({
                    "code": "regressions", "level": "critical",
                    "title": "Свежие регрессии (FAIL за 30 дней)",
                    "count": int(bad_runs["r"] or 0),
                    "detail": f"запусков: {bad_runs['c']}",
                    "action": {"screen": "launches"}})
            try:
                import integrity_check_service as _ic
                rep = _ic.check_project(project_path)
                n_iss = len(rep.get("issues", []))
            except Exception:
                n_iss = 0
            if n_iss:
                out.append({
                    "code": "integrity", "level": "warning",
                    "title": "Предупреждения целостности",
                    "count": n_iss,
                    "detail": "сироты/битые ссылки",
                    "action": {"screen": "maintenance"}})
            try:
                import analytics_service as _an
                scope = {"file_id": file_id} if file_id else None
                for a in _an.detect_anomalies(project_path, scope):
                    ids = list(a.get("case_ids") or [])
                    out.append({
                        "code": f"anom_{a['code']}", "level": a["level"],
                        "title": f"Аномалия: {a['title']}",
                        "count": len(ids),
                        "detail": a.get("detail", ""),
                        "action": {"screen": "review",
                                   "filters": ({"case_ids": ids}
                                               if ids else {})}})
            except Exception as e:
                logger.warning("attention anomalies failed: %s", e)
    except Exception as e:
        logger.warning("attention snapshot failed: %s", e)
    return out


def heavy_counts(project_path: str, file_id=None,
                 progress_callback=None, cancel_event=None) -> list:
    """Противоречия + дубли (O(n^2)): только для фона."""
    from workers import Cancelled as _Cancelled
    out = []
    try:
        import consistency_service as _qc
        n_conf = _qc.find_conflicts(
            project_path, file_id=file_id, threshold=0.4, limit=2000,
            progress_callback=progress_callback, cancel_event=cancel_event)
        ids: list = []
        for p in (n_conf.get("pairs") or []):
            ids.extend([p["case_a"], p["case_b"]])
        ids = sorted(set(ids))
        if ids:
            out.append({
                "code": "conflicts", "level": "warning",
                "title": "Противоречия себе",
                "count": len(ids),
                "detail": "похожие с Good против Bad",
                "action": {"screen": "consistency"}})
    except _Cancelled:
        raise
    except Exception as e:
        logger.warning("attention conflicts failed: %s", e)
    try:
        import similarity_service as _sim
        be, _note = _sim.resolve_backend()
        n_dup = be.find_duplicates(project_path, file_id, 0.9, 1000,
                                   progress_callback, cancel_event)
        ids = []
        for p in (n_dup.get("pairs") or []):
            ids.extend([p["case_a"], p["case_b"]])
        ids = sorted(set(ids))
        if ids:
            out.append({
                "code": "duplicates", "level": "info",
                "title": "Похожие/дубли",
                "count": len(ids),
                "detail": "кандидаты на скрытие",
                "action": {"screen": "review"}})
    except _Cancelled:
        raise
    except Exception as e:
        logger.warning("attention duplicates failed: %s", e)
    return out
