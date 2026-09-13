"""Шаблоны комментариев. DDL — только в database.init_database (миграции)."""
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)
MAX_TEMPLATE_LEN = 500


def get_comment_templates(project_path: str) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT template_id, text, is_system
            FROM comment_templates
            ORDER BY is_system DESC, text
        """)
        return [dict(row) for row in cursor.fetchall()]


def add_comment_template(project_path: str, text: str) -> bool:
    if not text or not text.strip():
        raise ValueError("Пустой шаблон")
    text = text.strip()
    if len(text) > MAX_TEMPLATE_LEN:
        raise ValueError("Шаблон слишком длинный")
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO comment_templates (text, is_system, created_at)
            VALUES (?, 0, ?)
        """, (text, utcnow()))
        return cursor.rowcount > 0


def delete_comment_template(project_path: str, template_id: int) -> bool:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM comment_templates
            WHERE template_id = ? AND is_system = 0
        """, (template_id,))
        return cursor.rowcount > 0


def get_user_templates(project_path: str) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT template_id, text
            FROM comment_templates
            WHERE is_system = 0
            ORDER BY text
        """)
        return [dict(row) for row in cursor.fetchall()]
