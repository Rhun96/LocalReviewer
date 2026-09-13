"""Сохранённые фильтры (ТЗ §28-30)."""
import json
from database import db, utcnow


def list_saved_filters(project_path: str) -> list:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("SELECT filter_id, name, filter_json, sort_order FROM saved_filters ORDER BY sort_order, name")
        return [{"filter_id": r["filter_id"], "name": r["name"],
                 "filters": json.loads(r["filter_json"]), "sort_order": r["sort_order"]}
                for r in cur.fetchall()]


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
