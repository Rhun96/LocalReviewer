"""Поиск по истории (ТЗ V2 §12, §32): текст, даты, тип, кейс, поле."""
import logging
from database import db

logger = logging.getLogger(__name__)


def search_history(project_path: str, text: str = "", event: str | None = None,
                   case_ids: list | None = None, field: str | None = None,
                   date_from: str | None = None, date_to: str | None = None,
                   limit: int = 500) -> list:
    """Строки history: поиск по event/field/old/new/comment + фильтры.

    date_from/date_to — 'YYYY-MM-DD' (по created_at). limit clamp 1..5000.
    """
    try:
        limit = max(1, min(int(limit), 5000))
    except (TypeError, ValueError):
        limit = 500
    conds, params = [], []
    if event == "check_verdict":
        conds.append("h.event_type IN "
                     "('check_confirmed','check_rejected','check_verdict_cleared')")
    elif event:
        conds.append("h.event_type = ?")
        params.append(event)
    if case_ids is not None:
        ids = list(dict.fromkeys(int(c) for c in case_ids))
        if not ids:
            return []
        conds.append(f"h.case_id IN ({','.join(['?'] * len(ids))})")
        params.extend(ids)
    if field:
        conds.append("h.field_name = ?")
        params.append(field)
    if date_from:
        conds.append("date(h.created_at) >= date(?)")
        params.append(date_from)
    if date_to:
        conds.append("date(h.created_at) <= date(?)")
        params.append(date_to)
    text = (text or "").strip()
    if text:
        esc = text.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = f"%{esc}%"
        conds.append("""(lower_ru(COALESCE(h.event_type,'')) LIKE ? ESCAPE '\\'
            OR lower_ru(COALESCE(h.field_name,'')) LIKE ? ESCAPE '\\'
            OR lower_ru(COALESCE(h.old_value,'')) LIKE ? ESCAPE '\\'
            OR lower_ru(COALESCE(h.new_value,'')) LIKE ? ESCAPE '\\'
            OR lower_ru(COALESCE(h.comment,'')) LIKE ? ESCAPE '\\')""")
        params.extend([like] * 5)
    query = """
        SELECT h.history_id, h.case_id, h.event_type, h.field_name,
               h.old_value, h.new_value, h.comment, h.created_at,
               c.source_id, f.file_name
        FROM history h
        LEFT JOIN cases c ON c.case_id = h.case_id
        LEFT JOIN files f ON f.file_id = c.file_id
    """
    if conds:
        query += " WHERE " + " AND ".join(conds)
    query += " ORDER BY h.created_at DESC LIMIT ?"
    params.append(limit)
    with db(project_path) as conn:
        return [dict(r) for r in conn.cursor().execute(query, params).fetchall()]


def distinct_fields(project_path: str) -> list:
    """Значения field_name для фильтра (непустые)."""
    with db(project_path) as conn:
        rows = conn.cursor().execute(
            "SELECT DISTINCT field_name FROM history "
            "WHERE field_name IS NOT NULL AND field_name != '' "
            "ORDER BY field_name").fetchall()
        return [r["field_name"] for r in rows]


_TRACKED_FIELDS = (
    ("status", "Статус"),
    ("comment", "Комментарий"),
    ("error", "Причина"),
    ("tags", "Теги"),
    ("viewed", "Просмотрено"),
)


def case_lifecycle(project_path: str, case_id: int) -> dict:
    """Сводка жизненного цикла кейса по существующей истории."""
    try:
        cid = int(case_id)
    except (TypeError, ValueError):
        raise ValueError(f"Плохой кейс: {case_id!r}") from None
    events = search_history(project_path, case_ids=[cid], limit=5000)
    out = {"case_id": cid, "total": len(events), "status_changes": 0,
           "comments": 0, "categories": 0, "tags_added": 0,
           "tags_removed": 0, "bugs": 0, "first": None, "last": None}
    for e in events:
        t = e.get("event_type") or ""
        if t == "status_changed":
            out["status_changes"] += 1
        elif t == "comment_changed":
            out["comments"] += 1
        elif t == "category_changed":
            out["categories"] += 1
        elif t == "tag_added":
            out["tags_added"] += 1
        elif t == "tag_removed":
            out["tags_removed"] += 1
        elif t.startswith("BUG_"):
            out["bugs"] += 1
    if events:
        try:
            asc = sorted(events,
                         key=lambda e: (e.get("created_at") or "",
                                        e.get("history_id") or 0))
            out["first"] = asc[0].get("created_at")
            out["last"] = asc[-1].get("created_at")
        except Exception:
            pass
    return out


def _error_names(project_path: str) -> dict:
    try:
        with db(project_path) as conn:
            return {str(r["category_id"]): r["name"] for r in conn.execute(
                "SELECT category_id, name FROM error_categories").fetchall()}
    except Exception:
        return {}


def _state_at(events_asc: list, upto_id: int, err_names: dict) -> dict:
    """Значения полей после события upto_id (включительно)."""
    st: dict = {"status": None, "comment": None, "error": None,
                "tags": set(), "viewed": None}
    for e in events_asc:
        try:
            hid = int(e.get("history_id") or 0)
        except (TypeError, ValueError):
            continue
        if hid > upto_id:
            break
        t = e.get("event_type") or ""
        if t == "status_changed" and (e.get("field_name") or "") == "status":
            st["status"] = e.get("new_value")
        elif t == "comment_changed":
            st["comment"] = e.get("new_value")
        elif t == "category_changed":
            v = e.get("new_value")
            st["error"] = err_names.get(str(v), v) if v else None
        elif t == "tag_added":
            v = e.get("new_value") or e.get("old_value")
            if v:
                st["tags"].add(str(v))
        elif t == "tag_removed":
            v = e.get("new_value") or e.get("old_value")
            st["tags"].discard(str(v))
        elif t == "viewed_changed":
            st["viewed"] = e.get("new_value")
    return st


def _display(value, is_tags: bool = False) -> str:
    if is_tags:
        return ", ".join(sorted(value)) if value else "(нет)"
    if value is None or value == "":
        return "(нет)"
    return str(value)


def _live_state(project_path: str, cid: int, err_names: dict) -> dict:
    """Текущие значения полей (для сравнения «событие → сейчас»)."""
    st: dict = {"status": None, "comment": None, "error": None,
                "tags": set(), "viewed": None}
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            a = cur.execute("SELECT status, comment, viewed FROM annotations "
                            "WHERE case_id=?", (cid,)).fetchone()
            if a:
                if (a["status"] or "") not in ("", "unreviewed"):
                    st["status"] = a["status"]
                if (a["comment"] or "") != "":
                    st["comment"] = a["comment"]
                if a["viewed"] is not None:
                    st["viewed"] = str(a["viewed"])
            e = cur.execute("SELECT category_id FROM case_errors "
                            "WHERE case_id=?", (cid,)).fetchone()
            if e and e["category_id"]:
                st["error"] = err_names.get(str(e["category_id"]),
                                            e["category_id"])
            try:
                st["tags"] = {str(r["tag_id"]) for r in cur.execute(
                    "SELECT tag_id FROM case_tags WHERE case_id=?",
                    (cid,)).fetchall()}
            except Exception:
                pass
    except Exception:
        pass
    return st


def compare_states(project_path: str, case_id: int,
                   hid_a: int, hid_b: int | None = None) -> dict:
    """Два состояния кейса: что было / что стало / что изменилось.

    Состояния reconstruct'ятся из существующей истории (новых сущностей
    нет): значение поля на момент = последнее new_value не позже события.
    hid_b=None — сравнить событие с ТЕКУЩИМ состоянием.
    """
    try:
        cid = int(case_id)
        a = int(hid_a)
        b = None if hid_b is None else int(hid_b)
    except (TypeError, ValueError):
        raise ValueError("Плохие ID кейса/событий") from None
    if b is not None and a == b:
        raise ValueError("Выбери два разных события")
    events = search_history(project_path, case_ids=[cid], limit=5000)
    by_id = {e.get("history_id"): e for e in events}
    if a not in by_id or (b is not None and b not in by_id):
        raise ValueError("События не найдены (чужой кейс?)")
    asc = sorted(events, key=lambda e: (int(e.get("history_id") or 0)))
    names = _error_names(project_path)
    lo, hi = (a, b) if b is None or a < b else (b, a)
    sa, sb = _state_at(asc, lo, names), (
        _state_at(asc, hi, names) if b is not None
        else _live_state(project_path, cid, names))
    rows = []
    for key, label in _TRACKED_FIELDS:
        va = _display(sa[key], is_tags=(key == "tags"))
        vb = _display(sb[key], is_tags=(key == "tags"))
        if va == "(нет)" and vb == "(нет)":
            continue
        rows.append({"field": key, "label": label, "a": va, "b": vb,
                     "changed": va != vb})
    return {"case_id": cid, "a_id": lo, "b_id": hi,
            "a_at": by_id[lo].get("created_at"),
            "b_at": by_id[hi].get("created_at") if hi is not None else None,
            "rows": rows}
