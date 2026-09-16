"""Пользовательские теги: создание, использование, удаление неиспользуемых."""
import logging
import re
from database import db, utcnow

logger = logging.getLogger(__name__)


def list_tags(project_path: str) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute(
            "SELECT tag_id, tag_code, tag_name, is_system FROM tags "
            "ORDER BY tag_name").fetchall()
        return [dict(r) for r in rows]


def create_tag(project_path: str, name: str) -> int:
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValueError("Название тега 1–64 символа")
    code = "user_" + re.sub(r"\W+", "_", name.lower()).strip("_")[:48] or "user_x"
    with db(project_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO tags (tag_code, tag_name, is_system, created_at)
                VALUES (?, ?, 0, ?)
            """, (code, name, utcnow()))
        except Exception as e:
            raise ValueError(f"Тег «{name}» уже есть") from e
        return cur.lastrowid


def usage_count(project_path: str, tag_id: int) -> int:
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT COUNT(DISTINCT case_id) AS c FROM case_tags WHERE tag_id=?",
            (tag_id,)).fetchone()
        return row["c"] if row else 0


def delete_tag(project_path: str, tag_id: int) -> None:
    """Удаление только неиспользуемого тега (иначе — сначала сними с кейсов)."""
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT tag_name FROM tags WHERE tag_id=?",
                          (tag_id,)).fetchone()
        if not row:
            raise ValueError("Тег не найден")
        used = cur.execute("SELECT COUNT(*) AS c FROM case_tags WHERE tag_id=?",
                           (tag_id,)).fetchone()["c"]
        if used:
            raise ValueError(f"Тег «{row['tag_name']}» висит на {used} кейсах — "
                             "сначала сними его (вручную или bulk «убрать тег»)")
        cur.execute("DELETE FROM tags WHERE tag_id=?", (tag_id,))
