"""Свои категории маппинга: хранение в настройках проекта.

Одна общая полка для мастера импорта кейсов и импорта прогонов:
категории переживают перезапуск и видны в обоих диалогах.
"""
import json
import logging

from database import db, utcnow

logger = logging.getLogger(__name__)

SETTINGS_KEY = "custom_mapping_cats"
MAX_NAME = 64
MAX_COUNT = 100


def _clean_names(names) -> list:
    out = []
    for n in names or []:
        s = str(n or "").strip()
        if not s or len(s) > MAX_NAME:
            raise ValueError("Название до 64 символов, без переносов")
        if any(ch in s for ch in "\n\r\t"):
            raise ValueError("Название до 64 символов, без переносов")
        if s not in out:
            out.append(s)
    if len(out) > MAX_COUNT:
        raise ValueError(f"Категорий не больше {MAX_COUNT}")
    return out


def load_custom_categories(project_path: str) -> list:
    """Имена своих категорий проекта (пусто — нет)."""
    try:
        with db(project_path) as conn:
            row = conn.cursor().execute(
                "SELECT value FROM settings WHERE key=?",
                (SETTINGS_KEY,)).fetchone()
        if not row or not row["value"]:
            return []
        data = json.loads(row["value"])
        return _clean_names(data) if isinstance(data, list) else []
    except ValueError:
        raise
    except Exception as e:
        logger.warning("custom categories load failed: %s", e)
        return []


def save_custom_categories(project_path: str, names: list) -> list:
    """Перезаписать список целиком. Возвращает итог."""
    cleaned = _clean_names(names)
    with db(project_path) as conn:
        conn.cursor().execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?",
            (SETTINGS_KEY, json.dumps(cleaned, ensure_ascii=False), utcnow(),
             json.dumps(cleaned, ensure_ascii=False), utcnow()))
    return cleaned


def add_custom_category(project_path: str, name: str) -> list:
    """Добавить категорию. Дубли и мусор — ValueError с текстом для UI."""
    name = str(name or "").strip()
    if not name:
        raise ValueError("Пустое название")
    current = load_custom_categories(project_path)
    if name in current:
        raise ValueError("Такая категория уже есть")
    return save_custom_categories(project_path, current + [name])


def remove_custom_category(project_path: str, name: str) -> list:
    """Убрать категорию. Нет такой — ValueError."""
    current = load_custom_categories(project_path)
    if name not in current:
        raise ValueError("Такой категории нет")
    return save_custom_categories(project_path, [n for n in current if n != name])


def custom_roles(project_path: str) -> list:
    """Роли для комбо маппинга: [(code, label)]."""
    try:
        names = load_custom_categories(project_path)
    except Exception:
        names = []
    return [(f"custom:{n}", f"📎 {n}") for n in names]


def reapply_mapping(headers: list, roles: list, saved: dict) -> dict:
    """header -> role: какие сохранённые роли дожили до перестройки."""
    valid = {code for code, _ in roles}
    return {h: (saved.get(h) if saved.get(h) in valid else None) for h in headers}
