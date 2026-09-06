from database import get_db_connection
from datetime import datetime

DEFAULT_TEMPLATES = [
    "Слишком коротко",
    "Не по задаче",
    "Нарушен формат",
    "Сомнительные факты",
    "Есть ссылка",
    "Похоже на дубль",
    "Требуется исправление",
    "Нужно обсудить",
    "Грамматические ошибки",
    "Стилистические проблемы",
]


def _ensure_table(cursor):
    cursor.execute("""
        SELECT name FROM sqlite_master
        WHERE type='table' AND name='comment_templates'
    """)
    if not cursor.fetchone():
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS comment_templates (
                template_id INTEGER PRIMARY KEY AUTOINCREMENT,
                text TEXT NOT NULL UNIQUE,
                is_system INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            )
        """)
        now = datetime.now().isoformat()
        for t in DEFAULT_TEMPLATES:
            cursor.execute("""
                INSERT OR IGNORE INTO comment_templates (text, is_system, created_at)
                VALUES (?, 1, ?)
            """, (t, now))


def get_comment_templates(project_path: str) -> list:
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        _ensure_table(cursor)
        conn.commit()
        cursor.execute("""
            SELECT template_id, text, is_system
            FROM comment_templates
            ORDER BY is_system DESC, text
        """)
        result = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return result
    except Exception:
        return []


def add_comment_template(project_path: str, text: str) -> bool:
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        _ensure_table(cursor)
        now = datetime.now().isoformat()
        cursor.execute("""
            INSERT OR IGNORE INTO comment_templates (text, is_system, created_at)
            VALUES (?, 0, ?)
        """, (text.strip(), now))
        conn.commit()
        added = cursor.rowcount > 0
        conn.close()
        return added
    except Exception:
        return False


def delete_comment_template(project_path: str, template_id: int) -> bool:
    """Удаляет пользовательский шаблон. Системные удалить нельзя."""
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM comment_templates
            WHERE template_id = ? AND is_system = 0
        """, (template_id,))
        conn.commit()
        deleted = cursor.rowcount > 0
        conn.close()
        return deleted
    except Exception:
        return False


def get_user_templates(project_path: str) -> list:
    """Только пользовательские шаблоны (для удаления)."""
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        _ensure_table(cursor)
        conn.commit()
        cursor.execute("""
            SELECT template_id, text
            FROM comment_templates
            WHERE is_system = 0
            ORDER BY text
        """)
        result = [dict(row) for row in cursor.fetchall()]
        conn.close()
        return result
    except Exception:
        return []