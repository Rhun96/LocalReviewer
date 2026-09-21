"""Отчёты: единый доступ к БД, валидация limit, корректный GROUP BY."""
import logging
import math
from datetime import date, timedelta
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
        cursor.execute(f"SELECT COUNT(*) as total FROM cases c "
                       f"JOIN files f ON f.file_id = c.file_id{file_condition}", params)
        total = cursor.fetchone()["total"]
        cursor.execute(f"""
            SELECT COALESCE(a.status, 'unreviewed') as status, COUNT(*) as count
            FROM cases c
            JOIN files f ON f.file_id = c.file_id
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
        else:
            # Без скоупа файла сироты удалённых файлов не считаются.
            file_condition = (" AND ct.case_id IN (SELECT c.case_id FROM cases c "
                              "JOIN files f ON f.file_id = c.file_id)")
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
        else:
            # Без скоупа файла сироты удалённых файлов не считаются.
            file_condition = (" WHERE cc.case_id IN (SELECT c.case_id FROM cases c "
                              "JOIN files f ON f.file_id = c.file_id)")
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


def get_personal_stats(project_path: str) -> dict:
    """Личная аналитика (ТЗ V2 §23): разметка, ошибки, баги, регрессии, тренд."""
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    with db(project_path) as conn:
        cur = conn.cursor()
        overall = get_overall_report(project_path)
        by_day = [dict(r) for r in cur.execute("""
            SELECT date(updated_at) AS day, COUNT(*) AS n FROM annotations
            WHERE updated_at IS NOT NULL
            GROUP BY date(updated_at) ORDER BY day DESC LIMIT 30
        """).fetchall()]
        errors = [dict(r) for r in cur.execute("""
            SELECT COALESCE(ec.name, '(без категории)') AS category,
                   COUNT(*) AS n
            FROM case_errors e
            LEFT JOIN error_categories ec ON ec.category_id = e.category_id
            GROUP BY category ORDER BY n DESC
        """).fetchall()]
        bugs = [dict(r) for r in cur.execute("""
            SELECT status, COUNT(*) AS n FROM bug_reports
            GROUP BY status
        """).fetchall()] if _has_table(cur, "bug_reports") else []
        regs = {}
        if _has_table(cur, "regression_runs"):
            r = cur.execute("""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN gate_result='PASS' THEN 1 ELSE 0 END) AS passed,
                       COALESCE(SUM(regressions), 0) AS regressions,
                       COALESCE(SUM(improvements), 0) AS improvements
                FROM regression_runs
            """).fetchone()
            regs = dict(r)
            regs["passed"] = regs.get("passed") or 0
        try:
            fp = cur.execute("SELECT COUNT(*) AS n FROM case_check_verdicts "
                             "WHERE verdict='false_positive'").fetchone()["n"]
        except Exception:
            fp = 0
    buckets = {k: overall.get(k, 0) for k in
               ("total", "reviewed", "good", "bad", "uncertain", "duplicate", "skip")}
    return {"review": buckets, "by_day": by_day, "errors": errors,
            "bugs": bugs, "regressions": regs, "base_map_known": bool(mapping),
            "false_positives": fp}


def _has_table(cursor, name: str) -> bool:
    return bool(cursor.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone())


def _base_lists(project_path: str) -> tuple:
    """(unreviewed-codes, bad-codes) с учётом своих кодов профилей."""
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    unrev = ["unreviewed"] + [c for c, b in mapping.items()
                              if b == "unreviewed" and c != "unreviewed"]
    bad = [c for c, b in mapping.items() if b == "bad"] or ["bad"]
    return unrev, bad


def get_product_report(project_path: str, file_id=None) -> list:
    """По продуктам из metadata: всего / проверено / плохих."""
    unrev, bad = _base_lists(project_path)
    uph = ",".join(["?"] * len(unrev))
    bph = ",".join(["?"] * len(bad))
    cond = "AND c.file_id = ?" if file_id else ""
    p = [file_id] if file_id else []
    with db(project_path) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"""
            SELECT COALESCE(NULLIF(json_extract(c.metadata_json, '$.product'), ''),
                            '(без продукта)') AS product,
                   COUNT(*) AS total,
                   COUNT(CASE WHEN COALESCE(a.status, 'unreviewed') NOT IN ({uph})
                              THEN 1 END) AS reviewed,
                   COUNT(CASE WHEN COALESCE(a.status, 'unreviewed') IN ({bph})
                              THEN 1 END) AS bad
            FROM cases c
            JOIN files f ON f.file_id = c.file_id
            LEFT JOIN annotations a ON a.case_id = c.case_id
            WHERE 1=1 {cond}
            GROUP BY product ORDER BY total DESC
        """, (*unrev, *bad, *p)).fetchall()
        return [dict(r) for r in rows]


def get_error_top(project_path: str, file_id=None, limit=5) -> list:
    """Топ причин ошибок: категория / подкатегория / критичность / число."""
    cond = "AND c.file_id = ?" if file_id else ""
    p = [file_id] if file_id else []
    with db(project_path) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"""
            SELECT COALESCE(ec.name, '(без категории)') AS category,
                   COALESCE(es.name, '') AS subcategory,
                   COALESCE(e.severity, '') AS severity,
                   COUNT(*) AS n
            FROM case_errors e
            JOIN cases c ON c.case_id = e.case_id
            JOIN files f ON f.file_id = c.file_id
            LEFT JOIN error_categories ec ON ec.category_id = e.category_id
            LEFT JOIN error_categories es ON es.category_id = e.subcategory_id
            WHERE 1=1 {cond}
            GROUP BY category, subcategory, severity
            ORDER BY n DESC LIMIT {int(limit)}
        """, p).fetchall()
        return [dict(r) for r in rows]


def get_velocity(project_path: str, file_id=None, days=14) -> dict:
    """Скорость разметки по событиям истории + прогноз завершения."""
    from review_queue_service import queue_stats
    cond = "AND c.file_id = ?" if file_id else ""
    p = [file_id] if file_id else []
    with db(project_path) as conn:
        cur = conn.cursor()
        rows = cur.execute(f"""
            SELECT date(h.created_at) AS day, COUNT(*) AS n
            FROM history h
            JOIN cases c ON c.case_id = h.case_id
            JOIN files f ON f.file_id = c.file_id
            WHERE h.event_type = 'status_changed' {cond}
            GROUP BY day ORDER BY day DESC LIMIT ?
        """, (*p, int(days))).fetchall()
    per_day = [{"day": r["day"], "n": r["n"]} for r in rows]
    active = [d["n"] for d in per_day if d["n"] > 0]
    avg = round(sum(active) / len(active), 1) if active else 0
    stats = queue_stats(project_path, file_id=file_id)
    remaining = stats["remaining"]
    if remaining == 0:
        eta_days = 0
    elif avg:
        eta_days = math.ceil(remaining / avg)
    else:
        eta_days = None
    eta_date = None
    if eta_days is not None:
        try:
            eta_date = (date.today() + timedelta(days=eta_days)).isoformat()
        except Exception:
            eta_date = None
    return {"per_day": per_day, "avg_per_day": avg,
            "active_days": len(active), "total": stats["total"],
            "reviewed": stats["reviewed"], "remaining": remaining,
            "eta_days": eta_days, "eta_date": eta_date}


def get_model_leaderboard(project_path: str) -> list:
    """По прогонам: ответы, разметка, победы в парах, gate-кандидаты."""
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    with db(project_path) as conn:
        cur = conn.cursor()
        runs = [dict(r) for r in cur.execute(
            "SELECT run_id, name, model_name FROM model_runs "
            "ORDER BY run_id").fetchall()]
        out = []
        for r in runs:
            rid = r["run_id"]
            good = bad = reviewed = 0
            for a in cur.execute("SELECT status, COUNT(*) AS n FROM output_reviews "
                                 "WHERE run_id=? GROUP BY status", (rid,)).fetchall():
                st, n = a["status"], a["n"]
                if not st or st == "unreviewed":
                    continue
                reviewed += n
                base = mapping.get(st, st)
                if base == "good":
                    good += n
                elif base == "bad":
                    bad += n
            total = cur.execute("SELECT COUNT(*) AS c FROM run_answers WHERE run_id=?",
                                (rid,)).fetchone()["c"]
            wins = cur.execute("""
                SELECT COUNT(*) AS c FROM run_preferences
                WHERE (run_a_id=? AND verdict='a_better')
                   OR (run_b_id=? AND verdict='b_better')""", (rid, rid)).fetchone()["c"]
            pairs = cur.execute("""
                SELECT COUNT(*) AS c FROM run_preferences
                WHERE run_a_id=? OR run_b_id=?""", (rid, rid)).fetchone()["c"]
            gates = cur.execute("""
                SELECT COUNT(*) AS c,
                       COALESCE(SUM(CASE WHEN gate_result='PASS' THEN 1 ELSE 0 END), 0)
                       AS passed
                FROM regression_runs WHERE candidate_run_id=?""", (rid,)).fetchone()
            out.append({"run_id": rid, "name": r["name"], "model_name": r["model_name"],
                        "answers": total, "reviewed": reviewed,
                        "good": good, "bad": bad, "wins": wins, "pairs": pairs,
                        "gates": gates["c"], "gates_passed": gates["passed"]})
        return out


def consistency_check(project_path: str, file_id=None) -> dict:
    """Сверка: все разрезы дают один тотал (защита от «цифры не бьются»)."""
    from review_queue_service import queue_stats
    overall = get_overall_report(project_path, file_id)
    total = overall.get("total", 0)
    parts = sum(overall.get(k, 0) for k in
                ("good", "bad", "uncertain", "duplicate", "skip"))
    checks = [{"name": "Статусы сходятся",
               "ok": parts == overall.get("reviewed", 0),
               "expected": overall.get("reviewed", 0), "actual": parts}]
    prod_total = sum(r["total"] for r in get_product_report(project_path, file_id))
    checks.append({"name": "Продукты сходятся", "ok": prod_total == total,
                   "expected": total, "actual": prod_total})
    with db(project_path) as conn:
        if file_id:
            f_total = conn.execute("SELECT COUNT(*) AS c FROM cases "
                                   "WHERE file_id=?", (file_id,)).fetchone()["c"]
        else:
            f_total = conn.execute(
                "SELECT COUNT(DISTINCT c.case_id) AS c FROM cases c "
                "JOIN files f ON f.file_id = c.file_id").fetchone()["c"]
    checks.append({"name": "Файлы сходятся", "ok": f_total == total,
                   "expected": total, "actual": f_total})
    qs = queue_stats(project_path, file_id=file_id)
    checks.append({"name": "Очередь сходится",
                   "ok": qs["total"] == total and qs["reviewed"] == overall.get("reviewed", 0),
                   "expected": (total, overall.get("reviewed", 0)),
                   "actual": (qs["total"], qs["reviewed"])})
    return {"checks": checks, "ok": all(c["ok"] for c in checks)}


def get_golden_info(project_path: str) -> dict:
    """Замороженные эталоны: список + свежесть (дней самому старому)."""
    with db(project_path) as conn:
        cur = conn.cursor()
        if not _has_table(cur, "dataset_versions"):
            return {"frozen": [], "count": 0, "oldest_days": None}
        rows = cur.execute("""
            SELECT d.name AS ds_name, v.version_number, v.frozen_at, v.case_count
            FROM dataset_versions v
            JOIN datasets d ON d.dataset_id = v.dataset_id
            WHERE v.status = 'frozen'
            ORDER BY v.frozen_at""").fetchall()
    frozen = []
    oldest = None
    today = date.today()
    for r in rows:
        age = None
        try:
            age = (today - date.fromisoformat(str(r["frozen_at"])[:10])).days
        except Exception:
            pass
        frozen.append({"dataset": r["ds_name"], "version": r["version_number"],
                       "frozen_at": (r["frozen_at"] or "")[:10],
                       "cases": r["case_count"], "age_days": age})
        if age is not None and (oldest is None or age > oldest):
            oldest = age
    return {"frozen": frozen, "count": len(frozen), "oldest_days": oldest}


STALE_DAYS = 30


def get_alerts(project_path: str) -> list:
    """Сигналы без сервера: сироты, серия FAIL, застой, нет эталона."""
    out = []
    try:
        import maintenance_service as _maint
        orphans = _maint.integrity_report(project_path).get("orphan_cases", 0)
    except Exception:
        orphans = 0
    if orphans:
        out.append({"level": "warning",
                    "text": f"Сироты в базе: {orphans} — Экран проекта → Целостность"})
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            last_two = [r["gate_result"] for r in cur.execute(
                "SELECT gate_result FROM regression_runs "
                "ORDER BY regression_id DESC LIMIT 2").fetchall()] \
                if _has_table(cur, "regression_runs") else []
    except Exception:
        last_two = []
    if len(last_two) == 2 and all(g == "FAIL" for g in last_two):
        out.append({"level": "critical", "text": "Gate FAIL дважды подряд"})
    try:
        unrev, _bad = _base_lists(project_path)
        uph = ",".join(["?"] * len(unrev))
        with db(project_path) as conn:
            stale = conn.execute(f"""
                SELECT COUNT(*) AS c FROM cases c
                JOIN files f ON f.file_id = c.file_id
                LEFT JOIN annotations a ON a.case_id = c.case_id
                WHERE COALESCE(a.status, 'unreviewed') IN ({uph})
                  AND date(c.created_at) <= date('now', ?)
            """, (*unrev, f"-{STALE_DAYS} days")).fetchone()["c"]
    except Exception:
        stale = 0
    if stale:
        out.append({"level": "warning",
                    "text": f"Не тронуто >{STALE_DAYS} дней: {stale}"})
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            has_marks = cur.execute(
                "SELECT 1 FROM annotations WHERE COALESCE(status, 'unreviewed') "
                "!= 'unreviewed' LIMIT 1").fetchone()
            has_frozen = cur.execute(
                "SELECT 1 FROM dataset_versions WHERE status='frozen' LIMIT 1"
                ).fetchone() if _has_table(cur, "dataset_versions") else None
    except Exception:
        has_marks, has_frozen = None, True
    if has_marks and not has_frozen:
        out.append({"level": "info", "text": "Нет замороженного эталона"})
    return out


def get_quality_trend(project_path: str) -> list:
    """Bad-rate по версиям датасетов (динамика качества)."""
    unrev, bad = _base_lists(project_path)
    bph = ",".join(["?"] * len(bad))
    with db(project_path) as conn:
        cur = conn.cursor()
        if not _has_table(cur, "dataset_versions"):
            return []
        rows = cur.execute(f"""
            SELECT v.version_id, d.name AS ds_name, v.version_number,
                   v.status, COUNT(dc.case_id) AS total,
                   COUNT(CASE WHEN COALESCE(dc.status, 'unreviewed') IN ({bph})
                              THEN 1 END) AS bad
            FROM dataset_versions v
            JOIN datasets d ON d.dataset_id = v.dataset_id
            LEFT JOIN dataset_cases dc ON dc.version_id = v.version_id
            GROUP BY v.version_id ORDER BY v.version_id
        """, bad).fetchall()
    out = []
    for r in rows:
        total = r["total"] or 0
        out.append({"version_id": r["version_id"], "dataset": r["ds_name"],
                    "version": r["version_number"], "status": r["status"],
                    "total": total, "bad": r["bad"],
                    "bad_rate": round(r["bad"] / total, 4) if total else None})
    return out
