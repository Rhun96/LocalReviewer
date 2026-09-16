"""Шаблоны комментариев. DDL — только в database.init_database (миграции)."""
import logging
import re
from database import db, utcnow

logger = logging.getLogger(__name__)
MAX_TEMPLATE_LEN = 500

# Переменные шаблонов (ТЗ §25-26): подставляются из кейса/разметки,
# неизвестные запрашиваются у пользователя при вставке.
TEMPLATE_VARS = ("product", "category", "case_id", "source_id", "status",
                 "missing_part", "expected", "actual")
_VAR_RE = re.compile(r"\{(\w+)\}")


def get_comment_templates(project_path: str) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cols = {r[1] for r in cursor.execute(
            "PRAGMA table_info(comment_templates)").fetchall()}
        if {"category_id", "subcategory_id"} <= cols:
            cursor.execute("""
                SELECT template_id, text, is_system, category_id, subcategory_id
                FROM comment_templates
                ORDER BY is_system DESC, text
            """)
        else:
            cursor.execute("""
                SELECT template_id, text, is_system
                FROM comment_templates
                ORDER BY is_system DESC, text
            """)
        rows = []
        for r in cursor.fetchall():
            d = dict(r)
            d.setdefault("category_id", None)
            d.setdefault("subcategory_id", None)
            rows.append(d)
        return rows


def ordered_templates(project_path: str, category_id: int | None = None,
                      subcategory_id: int | None = None) -> list:
    """Шаблоны: сначала точное совпадение причины, затем категория, затем общие."""
    all_t = get_comment_templates(project_path)
    if not category_id:
        return all_t
    exact = [t for t in all_t if t.get("category_id") == category_id
             and t.get("subcategory_id") == subcategory_id]
    by_cat = [t for t in all_t if t.get("category_id") == category_id
              and t not in exact]
    rest = [t for t in all_t if t not in exact and t not in by_cat]
    return exact + by_cat + rest


def add_comment_template(project_path: str, text: str,
                         category_id: int | None = None,
                         subcategory_id: int | None = None) -> bool:
    if not text or not text.strip():
        raise ValueError("Пустой шаблон")
    text = text.strip()
    if len(text) > MAX_TEMPLATE_LEN:
        raise ValueError("Шаблон слишком длинный")
    with db(project_path) as conn:
        cursor = conn.cursor()
        cols = {r[1] for r in cursor.execute(
            "PRAGMA table_info(comment_templates)").fetchall()}
        if {"category_id", "subcategory_id"} <= cols:
            cursor.execute("""
                INSERT OR IGNORE INTO comment_templates
                    (text, is_system, created_at, category_id, subcategory_id)
                VALUES (?, 0, ?, ?, ?)
            """, (text, utcnow(), category_id, subcategory_id))
        else:
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


def template_vars(text: str) -> list:
    """Список {переменных} в шаблоне (порядок, без дублей)."""
    seen: list = []
    for m in _VAR_RE.finditer(text or ""):
        v = m.group(1)
        if v not in seen:
            seen.append(v)
    return seen


def render_template(text: str, context: dict) -> str:
    """Подставляет известные переменные; неизвестные оставляет как есть.

    Не придумывает содержимое (ТЗ §27): только ускоряет заполнение.
    """
    ctx = dict(context or {})

    def _sub(m):
        key = m.group(1)
        if key in ctx and ctx[key] not in (None, ""):
            return str(ctx[key])
        return m.group(0)
    return _VAR_RE.sub(_sub, text or "")


def build_template_context(project_path: str, case_id: int,
                           current_case: dict | None = None,
                           current_error: dict | None = None) -> dict:
    """Контекст для подстановки: берётся из кейса/метаданных/таксономии."""
    import json as _json
    ctx: dict = {}
    case = dict(current_case or {})
    if not case and case_id:
        try:
            with db(project_path) as conn:
                row = conn.cursor().execute("""
                    SELECT c.case_id, c.source_id, c.primary_text, c.response_text,
                           c.metadata_json, COALESCE(a.status,'unreviewed') AS status
                    FROM cases c LEFT JOIN annotations a ON a.case_id=c.case_id
                    WHERE c.case_id=?
                """, (case_id,)).fetchone()
                if row:
                    case = dict(row)
        except Exception:
            case = {}
    if case:
        ctx["case_id"] = case.get("case_id", case_id)
        ctx["source_id"] = (case.get("source_id") or "").strip()
        ctx["status"] = case.get("status", "")
        try:
            meta = _json.loads(case.get("metadata_json") or "{}")
            if isinstance(meta, dict) and meta.get("product"):
                ctx["product"] = meta["product"]
        except Exception:
            pass
    err = current_error
    if err is None and case_id:
        try:
            from taxonomy_service import get_case_error
            err = get_case_error(project_path, case_id)
        except Exception:
            err = None
    if err and err.get("category_name"):
        sub = f" → {err['subcategory_name']}" if err.get("subcategory_name") else ""
        ctx["category"] = f"{err['category_name']}{sub}"
    return ctx
