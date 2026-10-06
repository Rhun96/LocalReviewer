"""Готовность набора к заморозке/релизу (W1 рабочего контура).

Только агрегатор существующих проверок: ничего нового не считаем,
лишь собираем (разметка, причины, ID, конфликты, дубли, целостность,
всплески bulk) в вердикт Готов / Есть проблемы / Требуется проверка.
Каждая проблема — количество + drill-фильтр к тем же кейсам.
Тяжёлое (пары) — через progress/cancel наружу, вызывать из фона.
"""
import logging

from database import db

logger = logging.getLogger(__name__)

LEVELS = ("critical", "warning", "info")

VERDICTS = {
    "ready": "Готов",
    "issues": "Есть проблемы",
    "check": "Требуется проверка",
}


def _scope_ids(project_path: str, file_id=None) -> list:
    """Кейсы области (скрытые вне игры — они отложены осознанно)."""
    with db(project_path) as conn:
        cur = conn.cursor()
        if file_id:
            rows = cur.execute(
                "SELECT case_id FROM cases WHERE file_id=? "
                "AND COALESCE(hidden, 0) = 0", (file_id,)).fetchall()
        else:
            rows = cur.execute(
                "SELECT c.case_id FROM cases c JOIN files f "
                "ON f.file_id = c.file_id WHERE COALESCE(c.hidden, 0) = 0"
                ).fetchall()
    return [r["case_id"] for r in rows]


def _codes(project_path: str) -> tuple:
    """(unreviewed-codes, bad-codes) с учётом своих кодов профилей."""
    from review_profile_service import code_to_base
    try:
        mapping = code_to_base(project_path) or {}
    except Exception:
        mapping = {}
    unrev = ["unreviewed"] + [c for c, b in mapping.items()
                              if b == "unreviewed" and c != "unreviewed"]
    bad = [c for c, b in mapping.items() if b == "bad"] or ["bad"]
    return unrev, bad


def check_readiness(project_path: str, file_id=None,
                    dup_threshold: float = 0.9,
                    conflict_threshold: float = 0.4,
                    progress_callback=None,
                    cancel_event=None) -> dict:
    """Проверить готовность. Долго — звать из фона (как дубли)."""
    from workers import Cancelled as _Cancelled
    ids = _scope_ids(project_path, file_id)
    unrev, bad = _codes(project_path)
    checks = []

    def _add(code, level, title, count, detail="", filters=None):
        checks.append({"code": code, "level": level, "title": title,
                       "count": int(count), "detail": detail,
                       "filters": filters or {}})

    with db(project_path) as conn:
        cur = conn.cursor()
        idset = set(ids)
        # statuses/причины/ID — одним проходом по области
        status_of, err_of, sid_of = {}, {}, {}
        if ids:
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                ph = ",".join(["?"] * len(chunk))
                for r in cur.execute(f"""
                        SELECT c.case_id,
                               COALESCE(a.status, 'unreviewed') AS st,
                               c.source_id
                        FROM cases c LEFT JOIN annotations a
                            ON a.case_id = c.case_id
                        WHERE c.case_id IN ({ph})
                    """, chunk).fetchall():
                    status_of[r["case_id"]] = r["st"]
                    sid_of[r["case_id"]] = (r["source_id"] or "").strip()
                for r in cur.execute(f"""
                        SELECT case_id FROM case_errors
                        WHERE case_id IN ({ph})
                    """, chunk).fetchall():
                    err_of[r["case_id"]] = True
    unrev_ids = [c for c in ids if status_of.get(c, "unreviewed") in unrev]
    bad_ids = [c for c in ids if status_of.get(c) in bad]
    bad_no_cause = [c for c in bad_ids if c not in err_of]
    empty_sid = [c for c in ids if not sid_of.get(c)]
    seen: dict = {}
    dup_sid = set()
    for c in ids:
        s = sid_of.get(c)
        if not s:
            continue
        if s in seen:
            dup_sid.add(c)
            dup_sid.add(seen[s])
        else:
            seen[s] = c
    _scope_flt = {"file_id": file_id} if file_id else {}
    _add("unreviewed", "critical", "Не размечены",
         len(unrev_ids), "без вердикта — релизить нельзя",
         dict(_scope_flt, statuses=["unreviewed"],
              case_ids=unrev_ids) if unrev_ids else dict(_scope_flt))
    _add("bad_no_cause", "critical", "Плохие без причины",
         len(bad_no_cause), "уйдут из Bad только с причиной",
         dict(_scope_flt, case_ids=bad_no_cause) if bad_no_cause
         else dict(_scope_flt))
    _add("empty_id", "warning", "Пустой ID",
         len(empty_sid), "слепки и прогоны стыкуются хуже",
         dict(_scope_flt, case_ids=empty_sid) if empty_sid
         else dict(_scope_flt))
    _add("dup_id", "warning", "Дубли ID в области",
         len(dup_sid), "конфликты в датасетах",
         dict(_scope_flt, case_ids=sorted(dup_sid)) if dup_sid
         else dict(_scope_flt))

    def _prog(done, total, base, span):
        if progress_callback is None:
            return
        try:
            progress_callback(base + int(done / total * span)
                              if total else base, 100)
        except Exception:
            pass

    # Пары: конфликты (противоречия себе) и дубли.
    conflict_ids: list = []

    def _conf_prog(done, total):
        _prog(done, total, 0, 40)

    try:
        import consistency_service as _qc
        n_conf = _qc.find_conflicts(
            project_path, file_id=file_id, threshold=conflict_threshold,
            limit=2000, progress_callback=_conf_prog,
            cancel_event=cancel_event)
        for p in (n_conf.get("pairs") or []):
            conflict_ids.extend([p["case_a"], p["case_b"]])
    except _Cancelled:
        raise
    except Exception as e:
        logger.warning("readiness conflicts failed: %s", e)
        conflict_ids = []
    conflict_ids = sorted({c for c in conflict_ids if c in idset})
    _add("conflicts", "warning", "Противоречия себе",
         len(conflict_ids), "похожие с Good против Bad",
         dict(_scope_flt, case_ids=conflict_ids) if conflict_ids
         else dict(_scope_flt))
    dup_ids: list = []

    def _dup_prog(done, total):
        _prog(done, total, 40, 60)

    try:
        import similarity_service as _sim
        be, _note = _sim.resolve_backend()
        n_dup = be.find_duplicates(
            project_path, file_id, float(dup_threshold), 1000,
            _dup_prog, cancel_event)
        for p in (n_dup.get("pairs") or []):
            dup_ids.extend([p["case_a"], p["case_b"]])
    except _Cancelled:
        raise
    except Exception as e:
        logger.warning("readiness duplicates failed: %s", e)
        dup_ids = []
    dup_ids = sorted({c for c in dup_ids if c in idset})
    _add("duplicates", "warning", "Похожие/дубли",
         len(dup_ids), "кандидаты на скрытие или слияние",
         dict(_scope_flt, case_ids=dup_ids) if dup_ids
         else dict(_scope_flt))
    if progress_callback is not None:
        try:
            progress_callback(100, 100)
        except Exception:
            pass
    # Целостность — только на проекте (на файле врёт масштабом).
    if file_id is None:
        try:
            import integrity_check_service as _ic
            rep = _ic.check_project(project_path)
            n_iss = len(rep.get("issues", []))
            _add("integrity", "warning" if n_iss else "info",
                 "Целостность", n_iss,
                 "; ".join(i.get("text", "") for i in
                           rep.get("issues", [])[:3]),
                 {})
        except Exception as e:
            logger.warning("readiness integrity failed: %s", e)
    else:
        _add("integrity", "info", "Целостность",
             0, "считается на всём проекте, не на файле", {})
    # Всплески bulk за 7 дней — информация, не приговор.
    try:
        with db(project_path) as conn:
            n_bulk = conn.execute("""
                SELECT COUNT(*) AS c FROM bulk_operations
                WHERE created_at >= date('now', '-7 days')
            """).fetchone()["c"]
    except Exception:
        n_bulk = 0
    _add("bulk_week", "info", "Массовых операций за 7 дней",
         int(n_bulk or 0), "резкие правки видно здесь", {})
    crit = sum(c["count"] for c in checks if c["level"] == "critical")
    warn = sum(c["count"] for c in checks if c["level"] == "warning")
    if crit:
        verdict = "issues"
    elif warn:
        verdict = "check"
    else:
        verdict = "ready"
    return {"verdict": verdict, "verdict_text": VERDICTS[verdict],
            "checks": checks, "total": len(ids),
            "file_id": file_id}
