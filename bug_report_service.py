"""Bug Reports (ТЗ V2 §6-11): баги, связь многие-ко-многим с кейсами, трекер.

История — в общей history (без отдельной таблицы): события бага пишутся
на связанные кейсы (CASE_ADDED/REMOVED — на конкретный).
"""
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

STATUSES = ("New", "Confirmed", "In Progress", "Fixed", "Rejected", "Duplicate")
SEVERITIES = ("Low", "Medium", "High", "Critical")
BUG_STATUS_NAMES = {"New": "Новый", "Confirmed": "Подтверждён",
                    "In Progress": "В работе", "Fixed": "Исправлен",
                    "Rejected": "Отклонён", "Duplicate": "Дубль"}
BUG_SEVERITY_NAMES = {"Low": "Низкая", "Medium": "Средняя", "High": "Высокая",
                      "Critical": "Критическая"}

_EDITABLE = ("title", "description", "status", "severity", "category_id",
             "subcategory_id", "model_name", "model_version", "prompt_version",
             "system_prompt_version", "external_tracker", "external_id",
             "external_url", "actual_behavior", "expected_behavior",
             "internal_comment")


def _check_taxonomy(cursor, category_id, subcategory_id) -> None:
    if category_id is None:
        if subcategory_id is not None:
            raise ValueError("Подкатегория без категории")
        return
    cat = cursor.execute("SELECT category_id FROM error_categories WHERE category_id=?",
                         (category_id,)).fetchone()
    if not cat:
        raise ValueError("Категория не найдена")
    if subcategory_id is not None:
        sub = cursor.execute("SELECT parent_id FROM error_categories WHERE category_id=?",
                             (subcategory_id,)).fetchone()
        if not sub or sub["parent_id"] != category_id:
            raise ValueError("Подкатегория не принадлежит категории")


def _bug_history(cursor, bug_id: int, event: str, case_ids: list,
                 old: str | None = None, new: str | None = None) -> None:
    now = utcnow()
    for cid in case_ids:
        cursor.execute("""
            INSERT INTO history (case_id, event_type, field_name, old_value,
                                 new_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (cid, event, f"bug:{bug_id}", old, new, now))


def _linked_case_ids(cursor, bug_id: int) -> list:
    return [r["case_id"] for r in cursor.execute(
        "SELECT case_id FROM bug_report_cases WHERE bug_id=?", (bug_id,))]


def create_bug(project_path: str, title: str, case_ids: list | None = None,
               **fields) -> int:
    """Создаёт баг (минимум — title; остальное опционально)."""
    title = (title or "").strip()
    if not title or len(title) > 256:
        raise ValueError("Заголовок 1–256 символов")
    case_ids = list(dict.fromkeys(int(c) for c in (case_ids or [])))
    status = fields.get("status", "New")
    severity = fields.get("severity", "Medium")
    if status not in STATUSES:
        raise ValueError(f"Плохой статус: {status!r}")
    if severity not in SEVERITIES:
        raise ValueError(f"Плохой severity: {severity!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        _check_taxonomy(cur, fields.get("category_id"), fields.get("subcategory_id"))
        for cid in case_ids:
            if not cur.execute("SELECT 1 FROM cases WHERE case_id=?",
                               (cid,)).fetchone():
                raise ValueError(f"Кейс #{cid} не найден")
        cols = ["title", "status", "severity", "created_at", "updated_at"]
        vals: list = [title, status, severity, now, now]
        for key in ("description", "category_id", "subcategory_id", "model_name",
                    "model_version", "prompt_version", "system_prompt_version",
                    "external_tracker", "external_id", "external_url",
                    "actual_behavior", "expected_behavior", "internal_comment"):
            if fields.get(key) is not None:
                cols.append(key)
                vals.append(fields[key])
        cur.execute(f"INSERT INTO bug_reports ({','.join(cols)}) "
                    f"VALUES ({','.join(['?'] * len(cols))})", vals)
        bug_id = cur.lastrowid
        for cid in case_ids:
            cur.execute("INSERT INTO bug_report_cases (bug_id, case_id, added_at)"
                        " VALUES (?, ?, ?)", (bug_id, cid, now))
        if case_ids:
            _bug_history(cur, bug_id, "BUG_CREATED", case_ids, None, title)
    logger.info("bug #%s created (%s cases)", bug_id, len(case_ids))
    return bug_id


def get_bug(project_path: str, bug_id: int) -> dict | None:
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT * FROM bug_reports WHERE bug_id=?",
                          (bug_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["cases"] = [dict(r) for r in cur.execute("""
            SELECT bc.case_id, c.source_id, c.primary_text
            FROM bug_report_cases bc
            LEFT JOIN cases c ON c.case_id = bc.case_id
            WHERE bc.bug_id = ?
            ORDER BY bc.case_id
        """, (bug_id,)).fetchall()]
        if d.get("category_id"):
            cat = cur.execute("SELECT name FROM error_categories WHERE category_id=?",
                              (d["category_id"],)).fetchone()
            d["category_name"] = cat["name"] if cat else None
        if d.get("subcategory_id"):
            sub = cur.execute("SELECT name FROM error_categories WHERE category_id=?",
                              (d["subcategory_id"],)).fetchone()
            d["subcategory_name"] = sub["name"] if sub else None
        return d


def list_bugs(project_path: str, status: str | None = None,
              severity: str | None = None, category_id: int | None = None,
              model: str | None = None, tracker: str | None = None,
              has_external: bool | None = None, search: str = "") -> list:
    """Список для экрана (§21): фильтры + поиск по title/desc/case/external."""
    conds, params = [], []
    if status:
        conds.append("b.status = ?")
        params.append(status)
    if severity:
        conds.append("b.severity = ?")
        params.append(severity)
    if category_id:
        conds.append("(b.category_id = ? OR b.subcategory_id = ?)")
        params.extend([category_id, category_id])
    if model:
        conds.append("b.model_name = ?")
        params.append(model)
    if tracker:
        conds.append("b.external_tracker = ?")
        params.append(tracker)
    if has_external is True:
        conds.append("(b.external_id != '' AND b.external_id IS NOT NULL)")
    elif has_external is False:
        conds.append("(b.external_id IS NULL OR b.external_id = '')")
    search = (search or "").strip()
    if search:
        # lower_ru с обеих сторон: встроенный LOWER знает только ASCII.
        conds.append("""(lower_ru(b.title) LIKE ? ESCAPE '\\'
            OR lower_ru(b.description) LIKE ? ESCAPE '\\'
            OR lower_ru(b.internal_comment) LIKE ? ESCAPE '\\'
            OR lower_ru(b.external_id) LIKE ? ESCAPE '\\'
            OR EXISTS (SELECT 1 FROM bug_report_cases bc JOIN cases c
                       ON c.case_id = bc.case_id
                       WHERE bc.bug_id = b.bug_id
                       AND (lower_ru(c.source_id) LIKE ? ESCAPE '\\'
                            OR CAST(c.case_id AS TEXT) = ?)))""")
        esc = search.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        params.extend([f"%{esc}%"] * 4 + [f"%{esc}%", search])
    query = """
        SELECT b.bug_id, b.title, b.status, b.severity, b.category_id,
               b.model_name, b.model_version, b.external_tracker, b.external_id,
               b.created_at, b.updated_at,
               COUNT(DISTINCT bc.case_id) AS cases
        FROM bug_reports b
        LEFT JOIN bug_report_cases bc ON bc.bug_id = b.bug_id
    """
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " GROUP BY b.bug_id ORDER BY b.updated_at ASC, b.bug_id ASC"
    with db(project_path) as conn:
        return [dict(r) for r in conn.cursor().execute(query, params).fetchall()]


def update_bug(project_path: str, bug_id: int, **fields) -> None:
    """Редактирование (только _EDITABLE). Статус/external — отдельными событиями."""
    patch = {k: v for k, v in fields.items() if k in _EDITABLE}
    if "status" in patch and patch["status"] not in STATUSES:
        raise ValueError(f"Плохой статус: {patch['status']!r}")
    if "severity" in patch and patch["severity"] not in SEVERITIES:
        raise ValueError(f"Плохой severity: {patch['severity']!r}")
    if "title" in patch and (not (patch["title"] or "").strip()
                             or len(patch["title"]) > 256):
        raise ValueError("Заголовок 1–256 символов")
    if not patch:
        return
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        old = cur.execute("SELECT * FROM bug_reports WHERE bug_id=?",
                          (bug_id,)).fetchone()
        if not old:
            raise ValueError("Баг не найден")
        old = dict(old)
        if "category_id" in patch or "subcategory_id" in patch:
            _check_taxonomy(cur,
                            patch.get("category_id", old["category_id"]),
                            patch.get("subcategory_id", old["subcategory_id"]))
        sets = ", ".join(f"{k}=?" for k in patch) + ", updated_at=?"
        cur.execute(f"UPDATE bug_reports SET {sets} WHERE bug_id=?",
                    (*patch.values(), now, bug_id))
        cases = _linked_case_ids(cur, bug_id)
        if "status" in patch and patch["status"] != old["status"]:
            _bug_history(cur, bug_id, "BUG_STATUS_CHANGED", cases,
                         old["status"], patch["status"])
        ext_changed = any(patch.get(k) != old.get(k)
                          for k in ("external_tracker", "external_id", "external_url")
                          if k in patch)
        if ext_changed:
            _bug_history(cur, bug_id, "BUG_EXTERNAL_LINKED", cases,
                         old.get("external_id"), patch.get("external_id"))
        if set(patch) - {"status", "external_tracker", "external_id", "external_url"}:
            _bug_history(cur, bug_id, "BUG_UPDATED", cases, None, patch.get("title"))


def add_case(project_path: str, bug_id: int, case_id: int) -> bool:
    """Привязать кейс (похожие добавляются только вручную, §8)."""
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        if not cur.execute("SELECT 1 FROM bug_reports WHERE bug_id=?",
                           (bug_id,)).fetchone():
            raise ValueError("Баг не найден")
        if not cur.execute("SELECT 1 FROM cases WHERE case_id=?",
                           (case_id,)).fetchone():
            raise ValueError(f"Кейс #{case_id} не найден")
        cur.execute("INSERT OR IGNORE INTO bug_report_cases (bug_id, case_id, added_at)"
                    " VALUES (?, ?, ?)", (bug_id, case_id, now))
        if cur.rowcount == 0:
            return False
        cur.execute("UPDATE bug_reports SET updated_at=? WHERE bug_id=?", (now, bug_id))
        _bug_history(cur, bug_id, "BUG_CASE_ADDED", [case_id], None, str(case_id))
        return True


def remove_case(project_path: str, bug_id: int, case_id: int) -> bool:
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM bug_report_cases WHERE bug_id=? AND case_id=?",
                    (bug_id, case_id))
        if cur.rowcount == 0:
            return False
        cur.execute("UPDATE bug_reports SET updated_at=? WHERE bug_id=?", (now, bug_id))
        _bug_history(cur, bug_id, "BUG_CASE_REMOVED", [case_id], str(case_id), None)
        return True


def cases_for_bug(project_path: str, bug_id: int) -> list:
    with db(project_path) as conn:
        return [dict(r) for r in conn.cursor().execute("""
            SELECT bc.case_id, c.source_id, c.primary_text,
                   COALESCE(a.status, 'unreviewed') AS status
            FROM bug_report_cases bc
            LEFT JOIN cases c ON c.case_id = bc.case_id
            LEFT JOIN annotations a ON a.case_id = bc.case_id
            WHERE bc.bug_id = ?
            ORDER BY bc.case_id
        """, (bug_id,)).fetchall()]


def bugs_for_case(project_path: str, case_id: int) -> list:
    """Баги кейса для карточки (ID/status/severity/title, §10)."""
    with db(project_path) as conn:
        return [dict(r) for r in conn.cursor().execute("""
            SELECT b.bug_id, b.title, b.status, b.severity
            FROM bug_report_cases bc
            JOIN bug_reports b ON b.bug_id = bc.bug_id
            WHERE bc.case_id = ?
            ORDER BY b.updated_at ASC
        """, (case_id,)).fetchall()]


def delete_bug(project_path: str, bug_id: int) -> None:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM bug_reports WHERE bug_id=?", (bug_id,))
        if cur.rowcount == 0:
            raise ValueError("Баг не найден")


def build_from_case(project_path: str, case_id: int) -> dict:
    """Автоперенос контекста кейса в баг (ТЗ V2 §7).

    Expected behavior НЕ придумываем: только из reference (operator_response),
    иначе пусто. Версии модели — из последнего прогона с этим кейсом.
    """
    import json as _json
    with db(project_path) as conn:
        cur = conn.cursor()
        c = cur.execute("""
            SELECT c.case_id, c.source_id, c.primary_text, c.response_text,
                   c.group_name, c.metadata_json,
                   COALESCE(a.status, 'unreviewed') AS status,
                   a.comment AS comment
            FROM cases c
            LEFT JOIN annotations a ON a.case_id = c.case_id
            WHERE c.case_id = ?
        """, (case_id,)).fetchone()
        if not c:
            raise ValueError(f"Кейс #{case_id} не найден")
        case = dict(c)
        err = cur.execute("""
            SELECT e.category_id, e.subcategory_id, e.severity,
                   ec.name AS category_name, es.name AS subcategory_name
            FROM case_errors e
            LEFT JOIN error_categories ec ON ec.category_id = e.category_id
            LEFT JOIN error_categories es ON es.category_id = e.subcategory_id
            WHERE e.case_id = ?
        """, (case_id,)).fetchone()
        run = cur.execute("""
            SELECT r.model_name, r.model_version, r.prompt_version,
                   r.system_prompt_version
            FROM run_answers a
            JOIN model_runs r ON r.run_id = a.run_id
            WHERE a.case_id = ?
            ORDER BY r.run_id DESC LIMIT 1
        """, (case_id,)).fetchone()
    meta = {}
    try:
        meta = _json.loads(case.get("metadata_json") or "{}")
    except Exception:
        pass
    if not isinstance(meta, dict):
        meta = {}
    reference = (meta.get("operator_response") or "").strip()
    return {
        "case_id": case_id,
        "source_id": (case.get("source_id") or "").strip(),
        "query": case.get("primary_text") or "",
        "model_response": case.get("response_text") or "",
        "reference": reference,
        "product": meta.get("product", ""),
        "group": case.get("group_name") or "",
        "review_status": case.get("status") or "unreviewed",
        "review_comment": case.get("comment") or "",
        "category_id": err["category_id"] if err else None,
        "subcategory_id": err["subcategory_id"] if err else None,
        "category_name": err["category_name"] if err else None,
        "subcategory_name": err["subcategory_name"] if err else None,
        "model_name": run["model_name"] if run else "",
        "model_version": run["model_version"] if run else "",
        "prompt_version": run["prompt_version"] if run else "",
        "system_prompt_version": run["system_prompt_version"] if run else "",
        # Expected НЕ придумываем: только reference, иначе пусто.
        "expected_behavior": reference,
        "title_suggest": (f"[{meta.get('product', '')}] "
                          f"{(case.get('primary_text') or '')[:60]}".strip()),
    }
