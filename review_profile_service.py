"""Профили ревью (ТЗ §31-36): схема статусов, хоткеи, обязательные поля.

v1: статусы — подмножество 6 базовых кодов (отчёты/матрица завязаны на коды),
переименование отображения, вкл/выкл, хоткеи, обязательность причины для «Плохо».
Произвольные новые коды статусов — следующим этапом (тронут отчёты и экспорт).
"""
import copy
import json
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

BASE_CODES = ("good", "bad", "uncertain", "duplicate", "skip")
COMMENT_MODES = ("none", "warn", "required", None)


def _default_config() -> dict:
    from migrations import DEFAULT_PROFILE_CONFIG
    return copy.deepcopy(DEFAULT_PROFILE_CONFIG)


def validate_config(config: dict) -> dict:
    """Проверяет и нормализует конфиг. Возвращает нормализованный."""
    if not isinstance(config, dict):
        raise ValueError("Конфиг должен быть объектом")
    statuses = config.get("statuses")
    if not isinstance(statuses, list) or not statuses:
        raise ValueError("Нужен непустой список статусов")
    seen_codes, seen_hotkeys, out = set(), set(), []
    for s in statuses:
        code = (s.get("code") or "").strip()
        name = (s.get("name") or "").strip()
        hotkey = (s.get("hotkey") or "").strip()
        enabled = bool(s.get("enabled", True))
        if code not in BASE_CODES:
            raise ValueError(f"Неизвестный код статуса: {code!r}")
        if code in seen_codes:
            raise ValueError(f"Дубль статуса: {code!r}")
        if not name or len(name) > 32:
            raise ValueError(f"Плохое имя статуса {code!r}")
        if hotkey:
            if len(hotkey) != 1:
                raise ValueError(f"Хоткей — один символ: {hotkey!r}")
            if hotkey in seen_hotkeys:
                raise ValueError(f"Дубль хоткея: {hotkey!r}")
            seen_hotkeys.add(hotkey)
        seen_codes.add(code)
        out.append({"code": code, "name": name, "hotkey": hotkey, "enabled": enabled})
    if not any(s["enabled"] for s in out):
        raise ValueError("Хотя бы один статус должен быть включён")
    req_cat = bool(config.get("require_category_for_bad", False))
    req_comment = config.get("require_comment_for_bad", None)
    if req_comment not in COMMENT_MODES:
        raise ValueError("require_comment_for_bad: none/warn/required")
    return {"statuses": out, "require_category_for_bad": req_cat,
            "require_comment_for_bad": req_comment}


def list_profiles(project_path: str) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute(
            "SELECT profile_id, name, description, config_json, is_default "
            "FROM review_profiles ORDER BY is_default DESC, name").fetchall()
        return [{"profile_id": r["profile_id"], "name": r["name"],
                 "description": r["description"] or "",
                 "config": json.loads(r["config_json"]),
                 "is_default": bool(r["is_default"])} for r in rows]


def get_profile(project_path: str, profile_id: int) -> dict | None:
    with db(project_path) as conn:
        r = conn.cursor().execute(
            "SELECT profile_id, name, description, config_json, is_default "
            "FROM review_profiles WHERE profile_id=?", (profile_id,)).fetchone()
        if not r:
            return None
        return {"profile_id": r["profile_id"], "name": r["name"],
                "description": r["description"] or "",
                "config": json.loads(r["config_json"]),
                "is_default": bool(r["is_default"])}


def get_active_profile(project_path: str) -> dict:
    """Активный профиль проекта; fallback — Default (ТЗ §36)."""
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT value FROM settings WHERE key='review_profile_id'").fetchone()
        pid = None
        if row and row["value"]:
            try:
                pid = int(row["value"])
            except (TypeError, ValueError):
                pid = None
    if pid is not None:
        prof = get_profile(project_path, pid)
        if prof:
            return prof
    with db(project_path) as conn:
        r = conn.cursor().execute(
            "SELECT profile_id, name, description, config_json, is_default "
            "FROM review_profiles WHERE is_default=1 LIMIT 1").fetchone()
        if r:
            return {"profile_id": r["profile_id"], "name": r["name"],
                    "description": r["description"] or "",
                    "config": json.loads(r["config_json"]),
                    "is_default": True}
    return {"profile_id": 0, "name": "Default", "description": "",
            "config": _default_config(), "is_default": True}


def set_active_profile(project_path: str, profile_id: int) -> None:
    if get_profile(project_path, profile_id) is None:
        raise ValueError("Профиль не найден")
    with db(project_path) as conn:
        conn.cursor().execute("""
            INSERT INTO settings (key, value, updated_at)
            VALUES ('review_profile_id', ?, ?)
            ON CONFLICT(key) DO UPDATE SET value=?, updated_at=?
        """, (str(profile_id), utcnow(), str(profile_id), utcnow()))


def create_profile(project_path: str, name: str, config: dict | None = None,
                   description: str = "") -> int:
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValueError("Название 1–64 символа")
    cfg = validate_config(copy.deepcopy(config) if config else _default_config())
    with db(project_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO review_profiles (name, description, config_json,
                                             is_default, created_at, updated_at)
                VALUES (?, ?, ?, 0, ?, ?)
            """, (name, description, json.dumps(cfg, ensure_ascii=False),
                  utcnow(), utcnow()))
        except Exception as e:
            raise ValueError("Профиль с таким именем уже есть") from e
        return cur.lastrowid


def update_profile(project_path: str, profile_id: int, name: str,
                   config: dict, description: str = "") -> None:
    name = (name or "").strip()
    if not name or len(name) > 64:
        raise ValueError("Название 1–64 символа")
    cfg = validate_config(copy.deepcopy(config))
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT is_default FROM review_profiles WHERE profile_id=?",
                          (profile_id,)).fetchone()
        if not row:
            raise ValueError("Профиль не найден")
        try:
            cur.execute("""
                UPDATE review_profiles
                SET name=?, description=?, config_json=?, updated_at=?
                WHERE profile_id=?
            """, (name, description, json.dumps(cfg, ensure_ascii=False),
                  utcnow(), profile_id))
        except Exception as e:
            raise ValueError("Имя уже занято") from e


def delete_profile(project_path: str, profile_id: int) -> None:
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT is_default FROM review_profiles WHERE profile_id=?",
                          (profile_id,)).fetchone()
        if not row:
            raise ValueError("Профиль не найден")
        if row["is_default"]:
            raise ValueError("Default-профиль удалить нельзя")
        cur.execute("UPDATE settings SET value=NULL WHERE key='review_profile_id' "
                    "AND value=?", (str(profile_id),))
        # SQLite: сравнение TEXT с числом — value хранится строкой, ок
        cur.execute("DELETE FROM review_profiles WHERE profile_id=?", (profile_id,))


def enabled_statuses(config: dict) -> list:
    return [s for s in config.get("statuses", []) if s.get("enabled")]
