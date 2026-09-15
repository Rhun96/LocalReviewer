"""Таксономия ошибок (ТЗ §19-23): категории, подкатегории, архив вместо удаления."""
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

SEVERITIES = ("low", "medium", "high", "critical")
SEVERITY_NAMES = {
    "low": "Низкая", "medium": "Средняя",
    "high": "Высокая", "critical": "Критическая",
}


def list_categories(project_path: str, include_archived: bool = False) -> list:
    """Дерево: [{category..., subs: [...]}]."""
    with db(project_path) as conn:
        cur = conn.cursor()
        cond = "WHERE parent_id IS NULL" if include_archived else (
            "WHERE parent_id IS NULL AND is_active=1")
        rows = cur.execute(f"""
            SELECT category_id, parent_id, code, name, description, sort_order, is_active
            FROM error_categories {cond}
            ORDER BY sort_order, name
        """).fetchall()
        cats = [dict(r) for r in rows]
        for cat in cats:
            subs = cur.execute("""
                SELECT category_id, parent_id, code, name, description, sort_order, is_active
                FROM error_categories
                WHERE parent_id = ?
                ORDER BY sort_order, name
            """, (cat["category_id"],)).fetchall()
            if not include_archived:
                subs = [s for s in subs if s["is_active"]]
            cat["subs"] = [dict(s) for s in subs]
    return cats


def get_category(project_path: str, category_id: int) -> dict | None:
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT * FROM error_categories WHERE category_id=?", (category_id,)).fetchone()
        return dict(row) if row else None


def create_category(project_path: str, name: str, parent_id: int | None = None,
                    code: str | None = None) -> int:
    name = (name or "").strip()
    if not name:
        raise ValueError("Пустое название категории")
    if len(name) > 64:
        raise ValueError("Название длиннее 64 символов")
    if code is None:
        import re
        code = "custom." + re.sub(r"\W+", "_", name.lower()).strip("_")[:48] or "custom.x"
    with db(project_path) as conn:
        cur = conn.cursor()
        if parent_id is not None and not cur.execute(
                "SELECT 1 FROM error_categories WHERE category_id=?", (parent_id,)).fetchone():
            raise ValueError("Родительская категория не найдена")
        try:
            cur.execute("""
                INSERT INTO error_categories
                    (parent_id, code, name, sort_order, is_active, created_at)
                VALUES (?, ?, ?, 0, 1, ?)
            """, (parent_id, code, name, utcnow()))
        except Exception as e:
            raise ValueError(f"Категория с кодом {code!r} уже есть") from e
        return cur.lastrowid


def rename_category(project_path: str, category_id: int, name: str) -> None:
    name = (name or "").strip()
    if not name:
        raise ValueError("Пустое название")
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE error_categories SET name=? WHERE category_id=?",
                    (name, category_id))
        if cur.rowcount == 0:
            raise ValueError("Категория не найдена")


def set_category_active(project_path: str, category_id: int, active: bool) -> None:
    with db(project_path) as conn:
        conn.cursor().execute("UPDATE error_categories SET is_active=? WHERE category_id=?",
                              (1 if active else 0, category_id))


def archive_category(project_path: str, category_id: int) -> None:
    """Архив вместо удаления: старая разметка живёт (ТЗ §22).

    Архивирует и всех детей (иначе дети остаются активными, а родитель скрыт —
    отчёт и UI расходятся).
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("UPDATE error_categories SET is_active=0 WHERE category_id=?",
                    (category_id,))
        cur.execute("UPDATE error_categories SET is_active=0 WHERE parent_id=?",
                    (category_id,))
    logger.info("archived category %s (+children)", category_id)


def delete_category(project_path: str, category_id: int) -> None:
    """Удаление только неиспользуемой категории (включая детей), иначе — архив."""
    with db(project_path) as conn:
        cur = conn.cursor()
        children = [r["category_id"] for r in cur.execute(
            "SELECT category_id FROM error_categories WHERE parent_id=?",
            (category_id,)).fetchall()]
        check_ids = [category_id, *children]
        ph = ",".join(["?"] * len(check_ids))
        used = cur.execute(
            f"SELECT 1 FROM case_errors WHERE category_id IN ({ph}) "
            f"OR subcategory_id IN ({ph}) LIMIT 1",
            (*check_ids, *check_ids)).fetchone()
        if used:
            raise ValueError("Категория используется в разметке — используйте архив")
        if children:
            cur.execute(f"DELETE FROM error_categories WHERE category_id IN ({ph})",
                        check_ids)
        cur.execute("DELETE FROM error_categories WHERE category_id=?", (category_id,))


def set_case_error(project_path: str, case_id: int, category_id: int | None,
                   subcategory_id: int | None = None,
                   severity: str = "medium") -> None:
    if severity not in SEVERITIES:
        raise ValueError(f"Плохой severity: {severity!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        old = cur.execute("SELECT * FROM case_errors WHERE case_id=?", (case_id,)).fetchone()
        if category_id is None:
            cur.execute("DELETE FROM case_errors WHERE case_id=?", (case_id,))
            if old:
                cur.execute("""
                    INSERT INTO history (case_id, event_type, field_name, old_value,
                                         new_value, created_at)
                    VALUES (?, 'category_changed', 'error', 'set', 'cleared', ?)
                """, (case_id, now))
            return
        cat = cur.execute("SELECT parent_id FROM error_categories WHERE category_id=?",
                          (category_id,)).fetchone()
        if not cat:
            raise ValueError("Категория не найдена")
        if subcategory_id is not None:
            sub = cur.execute("SELECT parent_id FROM error_categories WHERE category_id=?",
                              (subcategory_id,)).fetchone()
            if not sub or sub["parent_id"] != category_id:
                raise ValueError("Подкатегория не принадлежит категории")
        cur.execute("""
            INSERT INTO case_errors (case_id, category_id, subcategory_id, severity, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                category_id=?, subcategory_id=?, severity=?, updated_at=?
        """, (case_id, category_id, subcategory_id, severity, now,
              category_id, subcategory_id, severity, now))
        if not old or (old["category_id"], old["subcategory_id"]) != (category_id, subcategory_id):
            cur.execute("""
                INSERT INTO history (case_id, event_type, field_name, old_value,
                                     new_value, created_at)
                VALUES (?, 'category_changed', 'error', ?, ?, ?)
            """, (case_id, str(old["category_id"]) if old else None,
                  str(category_id), now))


def get_case_error(project_path: str, case_id: int) -> dict | None:
    with db(project_path) as conn:
        row = conn.cursor().execute("""
            SELECT e.case_id, e.category_id, e.subcategory_id, e.severity, e.updated_at,
                   c.name AS category_name, s.name AS subcategory_name
            FROM case_errors e
            LEFT JOIN error_categories c ON c.category_id = e.category_id
            LEFT JOIN error_categories s ON s.category_id = e.subcategory_id
            WHERE e.case_id = ?
        """, (case_id,)).fetchone()
        return dict(row) if row else None
