"""Сохранённые фильтры (ТЗ §28-30)."""
import json
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)


def _coerce(payload) -> dict | None:
    """Битый JSON/структура → None (строка пропускается, данные живут)."""
    if isinstance(payload, dict):
        # Новый формат {"filters": {...}, ...} или старый плоский условий.
        if isinstance(payload.get("filters"), dict) or "statuses" in payload:
            return payload
        return None
    return None


def list_saved_filters(project_path: str) -> list:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT filter_id, name, filter_json, sort_order "
                    "FROM saved_filters ORDER BY sort_order, name")
        out = []
        for r in cur.fetchall():
            try:
                payload = _coerce(json.loads(r["filter_json"]))
            except (ValueError, TypeError) as e:
                logger.warning("skip corrupt saved filter %r: %s", r["name"], e)
                continue
            if payload is None:
                logger.warning("skip corrupt saved filter %r: bad schema", r["name"])
                continue
            out.append({"filter_id": r["filter_id"], "name": r["name"],
                        "filters": payload, "sort_order": r["sort_order"]})
        return out


def save_filter(project_path: str, name: str, filters: dict) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Название фильтра пустое")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO saved_filters (name, filter_json, created_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(name) DO UPDATE SET filter_json=?, updated_at=?
        """, (name, json.dumps(filters or {}, ensure_ascii=False), now, now,
              json.dumps(filters or {}, ensure_ascii=False), now))
        row = cur.execute("SELECT filter_id FROM saved_filters WHERE name=?", (name,)).fetchone()
        return row["filter_id"]


def delete_saved_filter(project_path: str, filter_id: int) -> bool:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM saved_filters WHERE filter_id=?", (filter_id,))
        return cur.rowcount > 0
