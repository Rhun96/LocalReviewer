"""Регрессионное тестирование (ТЗ §49-60, §83).

Baseline — frozen-версия датасета или размеченный прогон (absolute-статусы
по stable_key). Candidate — прогон с output_reviews. Сравнение — по матрице
ТЗ §55 на base-семантике (свои коды профилей поддерживаются).
Gate (§59-60) только сообщает PASS/FAIL, ничего не выпускает.
"""
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

RESULTS = ("UNCHANGED", "IMPROVED", "REGRESSION", "NEW", "REMOVED", "UNRESOLVED")
RESULT_NAMES = {"UNCHANGED": "Без изменений", "IMPROVED": "Улучшено",
                "REGRESSION": "Регрессия", "NEW": "Новое",
                "REMOVED": "Удалено", "UNRESOLVED": "Не размечено"}
SEVERITY_NAMES = {"critical": "Критическая", "warning": "Предупреждение",
                  "info": "Инфо"}


def _base_of(project_path: str, status: str | None) -> str | None:
    if not status:
        return None
    try:
        from review_profile_service import code_to_base
        return code_to_base(project_path).get(status, status)
    except Exception:
        return status


def set_output_review(project_path: str, run_id: int, stable_key: str,
                      status: str, comment: str | None = None) -> None:
    """Absolute-разметка ответа прогона (своя на каждый run)."""
    import re
    if not re.match(r"^[a-z][a-z0-9_]{0,31}$", status or ""):
        raise ValueError(f"Плохой код статуса: {status!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        ans = cur.execute("SELECT case_id FROM run_answers WHERE run_id=? AND stable_key=?",
                          (run_id, stable_key)).fetchone()
        if not ans:
            raise ValueError("Ответ прогона не найден")
        cur.execute("""
            INSERT INTO output_reviews
                (run_id, stable_key, case_id, status, comment, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, stable_key) DO UPDATE SET
                status=?, comment=?, updated_at=?
        """, (run_id, stable_key, ans["case_id"], status, comment, now,
              status, comment, now))


def list_output_reviews(project_path: str, run_id: int) -> list:
    """Разметка ответов прогона + тексты для UI."""
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT a.stable_key, a.case_id, a.answer_text, a.prompt_text,
                    c.source_id, c.primary_text,
                   r.status AS review_status, r.comment AS review_comment
            FROM run_answers a
            LEFT JOIN cases c ON c.case_id = a.case_id
            LEFT JOIN output_reviews r
              ON r.run_id = a.run_id AND r.stable_key = a.stable_key
            WHERE a.run_id = ?
            ORDER BY a.stable_key
        """, (run_id,)).fetchall()
        return [dict(x) for x in rows]


def output_review_stats(project_path: str, run_id: int) -> dict:
    with db(project_path) as conn:
        cur = conn.cursor()
        total = cur.execute("SELECT COUNT(*) AS c FROM run_answers WHERE run_id=?",
                            (run_id,)).fetchone()["c"]
        reviewed = cur.execute("""
            SELECT COUNT(*) AS c FROM output_reviews
            WHERE run_id=? AND status IS NOT NULL AND status != 'unreviewed'
        """, (run_id,)).fetchone()["c"]
    return {"total": total, "reviewed": reviewed,
            "remaining": max(0, total - reviewed)}


def list_baseline_candidates(project_path: str) -> list:
    """Варианты baseline: версии датасетов + размеченные прогоны."""
    out = []
    with db(project_path) as conn:
        cur = conn.cursor()
        for r in cur.execute("""
                SELECT v.version_id, v.version_number, v.status, v.case_count,
                       d.name AS ds_name
                FROM dataset_versions v
                JOIN datasets d ON d.dataset_id = v.dataset_id
                ORDER BY d.name, v.version_number
            """).fetchall():
            from dataset_service import VERSION_STATUS_NAMES
            st = VERSION_STATUS_NAMES.get(r["status"], r["status"])
            out.append({"type": "dataset_version", "id": r["version_id"],
                        "label": f"Датасет «{r['ds_name']}» v{r['version_number']} "
                                 f"[{st}, {r['case_count']}]",
                        "frozen": r["status"] == "frozen"})
        for r in cur.execute("""
                SELECT r.run_id, r.name,
                       COUNT(rv.stable_key) AS reviewed
                FROM model_runs r
                LEFT JOIN output_reviews rv ON rv.run_id = r.run_id
                GROUP BY r.run_id
                ORDER BY r.name
            """).fetchall():
            out.append({"type": "run", "id": r["run_id"],
                        "label": f"Прогон «{r['name']}» (размечено: {r['reviewed']})",
                        "frozen": True})
    return out


def get_baseline_statuses(project_path: str, baseline_type: str,
                          baseline_id: int) -> dict:
    """stable_key -> {status, case_id}."""
    if baseline_type not in ("dataset_version", "run"):
        raise ValueError(f"Плохой baseline: {baseline_type!r}")
    out = {}
    with db(project_path) as conn:
        cur = conn.cursor()
        if baseline_type == "dataset_version":
            rows = cur.execute("SELECT stable_key, status, case_id FROM dataset_cases "
                               "WHERE version_id=?", (baseline_id,)).fetchall()
            if not rows and not cur.execute(
                    "SELECT 1 FROM dataset_versions WHERE version_id=?",
                    (baseline_id,)).fetchone():
                raise ValueError("Версия датасета не найдена")
            for r in rows:
                key = r["stable_key"] or f"case:{r['case_id']}"
                out.setdefault(key, {"status": r["status"], "case_id": r["case_id"]})
        else:
            if not cur.execute("SELECT 1 FROM model_runs WHERE run_id=?",
                               (baseline_id,)).fetchone():
                raise ValueError("Прогон не найден")
            for r in cur.execute("SELECT stable_key, status, case_id FROM output_reviews "
                                 "WHERE run_id=?", (baseline_id,)).fetchall():
                out[r["stable_key"]] = {"status": r["status"], "case_id": r["case_id"]}
    return out


def classify(project_path: str, baseline_status: str | None,
             candidate_status: str | None, candidate_present: bool) -> tuple:
    """(result, severity) по матрице ТЗ §55 на base-семантике."""
    if baseline_status is None:
        return ("NEW", "info")
    if not candidate_present:
        return ("REMOVED", "info")
    base_b = _base_of(project_path, baseline_status)
    base_c = _base_of(project_path, candidate_status)
    if base_b == "unreviewed" or not base_c or base_c == "unreviewed":
        return ("UNRESOLVED", "info")
    if base_b == base_c:
        return ("UNCHANGED", "info")
    if base_c == "bad" and base_b == "good":
        return ("REGRESSION", "critical")
    if base_c == "bad":
        return ("REGRESSION", "critical")
    if base_c == "uncertain" and base_b == "good":
        return ("REGRESSION", "warning")
    if base_c == "good" and base_b in ("bad", "uncertain"):
        return ("IMPROVED", "info")
    return ("UNCHANGED", "info")


def run_regression(project_path: str, name: str, baseline_type: str,
                   baseline_id: int, candidate_type: str, candidate_id: int,
                   gate_max_critical: int = 0,
                   gate_max_rate: float = 0.02) -> int:
    """Считает и сохраняет запуск регрессии. Возвращает regression_id.

    Кандидат — прогон или версия датасета (v20). Матрица и gate одинаковые;
    у версий нет текстов ответов (только статусы) — в экспорте пусто.
    """
    name = (name or "").strip()
    if not name or len(name) > 128:
        raise ValueError("Название 1–128 символов")
    if candidate_type not in ("dataset_version", "run"):
        raise ValueError(f"Плохой кандидат: {candidate_type!r}")
    if gate_max_critical < 0 or not 0 <= gate_max_rate <= 1:
        raise ValueError("Плохие пороги gate")
    base = get_baseline_statuses(project_path, baseline_type, baseline_id)
    cand = get_baseline_statuses(project_path, candidate_type, candidate_id)
    if candidate_type == "run":
        with db(project_path) as conn:
            cur = conn.cursor()
            if not cur.execute("SELECT 1 FROM model_runs WHERE run_id=?",
                               (candidate_id,)).fetchone():
                raise ValueError("Кандидат-прогон не найден")
            cand_answers = {r["stable_key"]: r["answer_text"] for r in cur.execute(
                "SELECT stable_key, answer_text FROM run_answers WHERE run_id=?",
                (candidate_id,)).fetchall()}
    else:
        cand_answers = {k: "" for k in cand}
    rows = []
    counts = {"total": 0, "regressions": 0, "improvements": 0, "unchanged": 0}
    both = 0
    for key in sorted(set(base) | set(cand_answers)):
        in_base, in_cand = key in base, key in cand_answers
        b_status = base[key]["status"] if in_base else None
        c_status = cand.get(key, {}).get("status")
        result, severity = classify(project_path, b_status, c_status, in_cand)
        if in_base and in_cand:
            both += 1
        case_id = (cand.get(key, {}).get("case_id")
                   or (base[key]["case_id"] if in_base else None))
        rows.append((key, case_id, b_status, c_status, result, severity))
        counts["total"] += 1
        if result == "REGRESSION":
            counts["regressions"] += 1
        elif result == "IMPROVED":
            counts["improvements"] += 1
        else:
            counts["unchanged"] += 1
    critical = sum(1 for r in rows if r[4] == "REGRESSION" and r[5] == "critical")
    rate = (counts["regressions"] / both) if both else 0.0
    gate_pass = critical <= gate_max_critical and rate <= gate_max_rate
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO regression_runs
                (name, baseline_type, baseline_id, candidate_type,
                 candidate_run_id, candidate_version_id,
                 gate_max_critical, gate_max_rate, gate_result,
                 total, regressions, improvements, unchanged, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (name, baseline_type, baseline_id, candidate_type,
              candidate_id if candidate_type == "run" else None,
              candidate_id if candidate_type == "dataset_version" else None,
              gate_max_critical, gate_max_rate,
              "PASS" if gate_pass else "FAIL",
              counts["total"], counts["regressions"], counts["improvements"],
              counts["unchanged"], now))
        rid = cur.lastrowid
        for key, case_id, b_status, c_status, result, severity in rows:
            cur.execute("""
                INSERT OR REPLACE INTO regression_results
                    (regression_id, stable_key, case_id, baseline_status,
                     candidate_status, result, severity)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (rid, key, case_id, b_status, c_status, result, severity))
    logger.info("regression %s: total=%s reg=%s imp=%s gate=%s",
                rid, counts["total"], counts["regressions"],
                counts["improvements"], "PASS" if gate_pass else "FAIL")
    return rid


def list_regressions(project_path: str) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT regression_id, name, baseline_type, baseline_id,
                   candidate_type, candidate_run_id, candidate_version_id,
                   gate_max_critical, gate_max_rate,
                   gate_result, total, regressions, improvements, unchanged,
                   created_at
            FROM regression_runs
            ORDER BY regression_id DESC
        """).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            # Совместимость: старые запуски (до v20) без candidate_type.
            if not d.get("candidate_type"):
                d["candidate_type"] = "run"
            out.append(d)
        return out


def candidate_label(project_path: str, reg: dict) -> str:
    """Подпись кандидата: прогон или версия датасета."""
    ctype = (reg or {}).get("candidate_type") or "run"
    try:
        if ctype == "dataset_version":
            vid = (reg or {}).get("candidate_version_id")
            with db(project_path) as conn:
                row = conn.execute("""
                    SELECT d.name, v.version_number, v.status
                    FROM dataset_versions v
                    JOIN datasets d ON d.dataset_id = v.dataset_id
                    WHERE v.version_id = ?
                """, (vid,)).fetchone()
            if row:
                return (f"Датасет «{row['name']}» v{row['version_number']} "
                        f"[{row['status']}]")
            return f"Версия #{vid} (удалена)"
        rid = (reg or {}).get("candidate_run_id")
        with db(project_path) as conn:
            row = conn.execute("SELECT name FROM model_runs WHERE run_id=?",
                               (rid,)).fetchone()
        return f"Прогон «{row['name']}»" if row else f"Прогон #{rid} (удалён)"
    except Exception:
        return "—"


def get_regression(project_path: str, regression_id: int) -> dict | None:
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT * FROM regression_runs WHERE regression_id=?",
            (regression_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        both = conn.cursor().execute(
            "SELECT COUNT(*) AS c FROM regression_results "
            "WHERE regression_id=? AND baseline_status IS NOT NULL "
            "AND candidate_status IS NOT NULL",
            (regression_id,)).fetchone()["c"]
        d["compared"] = both
        d["regression_rate"] = (d["regressions"] / both) if both else 0.0
        return d


def delete_regression(project_path: str, regression_id: int) -> None:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM regression_runs WHERE regression_id=?",
                    (regression_id,))
        if cur.rowcount == 0:
            raise ValueError("Запуск не найден")


def list_regression_results(project_path: str, regression_id: int,
                            result: str | None = None,
                            severity: str | None = None) -> list:
    query = """
        SELECT rr.stable_key, rr.case_id, rr.baseline_status,
               rr.candidate_status, rr.result, rr.severity,
               c.source_id, c.primary_text, c.response_text,
               an.comment AS case_comment,
               ec.name AS error_category
        FROM regression_results rr
        LEFT JOIN cases c ON c.case_id = rr.case_id
        LEFT JOIN annotations an ON an.case_id = rr.case_id
        LEFT JOIN case_errors e ON e.case_id = rr.case_id
        LEFT JOIN error_categories ec ON ec.category_id = e.category_id
        WHERE rr.regression_id = ?
    """
    params: list = [regression_id]
    if result:
        if result not in RESULTS:
            raise ValueError(f"Плохой фильтр: {result!r}")
        query += " AND rr.result = ?"
        params.append(result)
    if severity:
        query += " AND rr.severity = ?"
        params.append(severity)
    query += (' ORDER BY CASE rr.result WHEN \'REGRESSION\' THEN 0 '
              'WHEN \'UNRESOLVED\' THEN 1 ELSE 2 END, rr.stable_key')
    with db(project_path) as conn:
        return [dict(r) for r in conn.cursor().execute(query, params).fetchall()]


def export_regressions_xlsx(project_path: str, regression_id: int,
                            output_path: str) -> str:
    """Экспорт регрессий (ТЗ §83): case_id/query/ответы/статусы/тип/категория."""
    from export_service import _atomic_save, _resolve_output, safe_cell
    from openpyxl import Workbook
    reg = get_regression(project_path, regression_id)
    if not reg:
        raise ValueError("Запуск не найден")
    rows = list_regression_results(project_path, regression_id, result="REGRESSION")
    cand_answers = {}
    with db(project_path) as conn:
        cur = conn.cursor()
        if reg.get("candidate_type", "run") == "run" and reg.get("candidate_run_id"):
            for r in cur.execute("SELECT stable_key, answer_text FROM run_answers "
                                 "WHERE run_id=?", (reg["candidate_run_id"],)).fetchall():
                cand_answers[r["stable_key"]] = r["answer_text"]
        base_answers = {}
        if reg["baseline_type"] == "run":
            for r in cur.execute("SELECT stable_key, answer_text FROM run_answers "
                                 "WHERE run_id=?", (reg["baseline_id"],)).fetchall():
                base_answers[r["stable_key"]] = r["answer_text"]
    wb = Workbook()
    ws = wb.active
    ws.title = "regressions"
    ws.append(["case_id", "query", "baseline_response", "new_response",
               "baseline_status", "new_status", "regression_type",
               "category", "comment"])
    for r in rows:
        ws.append([
            safe_cell(r["case_id"] or r["source_id"] or r["stable_key"]),
            safe_cell(r["primary_text"] or ""),
            safe_cell(base_answers.get(r["stable_key"], r["response_text"] or "")),
            safe_cell(cand_answers.get(r["stable_key"], "")),
            safe_cell(r["baseline_status"] or ""),
            safe_cell(r["candidate_status"] or ""),
            safe_cell(f"{r['result']}/{r['severity']}"),
            safe_cell(r["error_category"] or ""),
            safe_cell(r["case_comment"] or ""),
        ])
    out = _resolve_output(output_path)
    _atomic_save(wb, out)
    return out


def bug_prefill(project_path: str, regression_id: int, stable_key: str) -> dict:
    """Префилл бага из строки регрессии (ТЗ V2 §11): baseline/candidate,
    ответы, статусы, версии модели/промптов — без ручного копирования."""
    reg = get_regression(project_path, regression_id)
    if not reg:
        raise ValueError("Запуск не найден")
    rows = list_regression_results(project_path, regression_id)
    row = next((r for r in rows if r["stable_key"] == stable_key), None)
    if not row:
        raise ValueError("Строка не найдена")
    with db(project_path) as conn:
        cur = conn.cursor()
        cand = None
        if reg.get("candidate_type", "run") == "run" and reg.get("candidate_run_id"):
            cand = cur.execute("SELECT answer_text FROM run_answers "
                               "WHERE run_id=? AND stable_key=?",
                               (reg["candidate_run_id"], stable_key)).fetchone()
        cand_ans = cand["answer_text"] if cand else ""
        base_ans = ""
        if reg["baseline_type"] == "run":
            b = cur.execute("SELECT answer_text FROM run_answers "
                            "WHERE run_id=? AND stable_key=?",
                            (reg["baseline_id"], stable_key)).fetchone()
            base_ans = b["answer_text"] if b else ""
            meta_run = cur.execute("SELECT model_name, model_version, prompt_version,"
                                   " system_prompt_version FROM model_runs WHERE run_id=?",
                                   (reg["baseline_id"],)).fetchone()
        else:
            meta_run = None
        if row["case_id"]:
            case = cur.execute("SELECT c.primary_text, c.response_text, c.group_name,"
                               " c.metadata_json, c.source_id, e.category_id,"
                               " e.subcategory_id FROM cases c "
                               "LEFT JOIN case_errors e ON e.case_id = c.case_id "
                               "WHERE c.case_id=?", (row["case_id"],)).fetchone()
        else:
            case = None
        cand_meta = None
        if reg.get("candidate_type", "run") == "run" and reg.get("candidate_run_id"):
            cand_meta = cur.execute("SELECT model_name, model_version, prompt_version,"
                                    " system_prompt_version FROM model_runs WHERE run_id=?",
                                    (reg["candidate_run_id"],)).fetchone()
    import json as _json
    case = dict(case) if case else {}
    try:
        m = _json.loads(case.get("metadata_json") or "{}")
        product = m.get("product", "") if isinstance(m, dict) else ""
        reference = (m.get("operator_response") or "").strip() if isinstance(
            m, dict) else ""
    except Exception:
        product, reference = "", ""
    if reg["baseline_type"] == "run" and meta_run:
        model_name = meta_run["model_name"] or ""
        model_version = meta_run["model_version"] or ""
        prompt_version = meta_run["prompt_version"] or ""
        system_prompt = meta_run["system_prompt_version"] or ""
    else:
        model_name = (cand_meta["model_name"] or "") if cand_meta else ""
        model_version = (cand_meta["model_version"] or "") if cand_meta else ""
        prompt_version = (cand_meta["prompt_version"] or "") if cand_meta else ""
        system_prompt = (cand_meta["system_prompt_version"] or "") if cand_meta else ""
    query = case.get("primary_text") or ""
    return {
        "case_id": row["case_id"],
        "source_id": case.get("source_id") or "",
        "query": query,
        "model_response": cand_ans or "",
        "reference": reference,
        "product": product,
        "group": case.get("group_name") or "",
        "review_status": row.get("candidate_status") or "unreviewed",
        "review_comment": "",
        "category_id": case.get("category_id"),
        "subcategory_id": case.get("subcategory_id"),
        "category_name": None,
        "subcategory_name": None,
        "model_name": model_name,
        "model_version": model_version,
        "prompt_version": prompt_version,
        "system_prompt_version": system_prompt,
        "expected_behavior": reference,
        "title_suggest": (f"[регрессия {reg['name']}] {query[:60]}").strip(),
        "description": (
            f"Регрессия {reg['name']}: {row.get('baseline_status')} → "
            f"{row.get('candidate_status')} ({row.get('result')}).\n"
            f"Было: {(base_ans or case.get('response_text') or '')[:500]}\n"
            f"Стало: {(cand_ans or '')[:500]}"),
    }
