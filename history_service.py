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
