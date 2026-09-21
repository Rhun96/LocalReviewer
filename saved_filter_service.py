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


PRESET_VIEWS = (
    # V2.1 §13: готовые представления = обычные сохранённые фильтры + вид.
    # «Регрессия» отдельным пресетом не нужна: regression_results и так
    # сортируются REGRESSION первым (см. list_regression_results).
    ("Обычное ревью",
     {"filters": {"statuses": ["unreviewed"]},
      "queue_mode": "normal", "sort": "import"}),
    ("Разбор проблем",
     {"filters": {"statuses": ["unreviewed"]},
      "queue_mode": "problematic", "sort": "problematic_first"}),
    ("Баги",
     {"filters": {"statuses": ["bad"]},
      "queue_mode": "normal", "sort": "import"}),
)


_SEED_MARK = "presets_seeded_v1"


def ensure_preset_views(project_path: str) -> int:
    """Seed §13-пресетов один раз на проект (маркер в settings).

    Маркер вместо сверки имён: удалённый пользователем пресет не воскресает
    при каждом открытии, повторных чтений/записей тоже нет.
    """
    from database import db, utcnow
    try:
        with db(project_path) as conn:
            if conn.execute("SELECT 1 FROM settings WHERE key=?",
                            (_SEED_MARK,)).fetchone():
                return 0
    except Exception as e:
        logger.warning("preset views marker check failed: %s", e)
        return 0
    created = 0
    try:
        existing = {f["name"] for f in list_saved_filters(project_path)}
    except Exception as e:
        logger.warning("preset views list failed: %s", e)
        return 0
    for name, payload in PRESET_VIEWS:
        if name in existing:
            continue
        try:
            save_filter(project_path, name, payload)
            created += 1
        except Exception as e:
            logger.warning("preset view %r failed: %s", name, e)
    try:
        with db(project_path) as conn:
            conn.execute("INSERT OR IGNORE INTO settings (key, value, updated_at)"
                         " VALUES (?, '1', ?)", (_SEED_MARK, utcnow()))
    except Exception as e:
        logger.warning("preset views marker save failed: %s", e)
    if created:
        logger.info("seeded %s preset views", created)
    return created
