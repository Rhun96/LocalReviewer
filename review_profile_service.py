"""Профили ревью (ТЗ §31-36): схема статусов, хоткеи, обязательные поля.

Статусы — произвольные коды (например Safety Dataset: safe/edge/target),
каждый с base-семантикой из 6 базовых: отчёты, очередь и регрессия работают
по base, отображение — по имени из профиля. Старые проекты — Default-профиль.
"""
import copy
import json
import logging
import re
from database import db, utcnow

logger = logging.getLogger(__name__)

BASE_CODES = ("good", "bad", "uncertain", "duplicate", "skip")
BASE_SET = ("unreviewed",) + BASE_CODES
COMMENT_MODES = ("none", "warn", "required", None)
_CODE_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


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
        base = (s.get("base") or "").strip() or None
        if not _CODE_RE.match(code):
            raise ValueError(f"Плохой код статуса: {code!r} (латиница, цифры, _)")
        if code in seen_codes:
            raise ValueError(f"Дубль статуса: {code!r}")
        if not name or len(name) > 32:
            raise ValueError(f"Плохое имя статуса {code!r}")
        if base is None:
            # Базовые коды маппятся сами на себя; свои требуют явный base.
            if code not in BASE_SET:
                raise ValueError(f"Статусу {code!r} нужен base из {list(BASE_SET)}")
            base = code
        elif base not in BASE_SET:
            raise ValueError(f"Плохой base {base!r} для {code!r}")
        if hotkey:
            if len(hotkey) != 1:
                raise ValueError(f"Хоткей — один символ: {hotkey!r}")
            if hotkey in seen_hotkeys:
                raise ValueError(f"Дубль хоткея: {hotkey!r}")
            seen_hotkeys.add(hotkey)
        seen_codes.add(code)
        out.append({"code": code, "name": name, "hotkey": hotkey,
                    "enabled": enabled, "base": base})
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


def code_to_base(project_path: str) -> dict:
    """Код статуса -> base-семантика по активному профилю.

    Базовые коды и 'unreviewed' маппятся сами; неизвестные коды (старая
    разметка, удалённый профиль) считаются 'unreviewed' только если это
    буквально 'unreviewed', иначе — как есть для отображения, а для
    reviewed/base-агрегации используется сам код при отсутствии в маппинге.
    Возвращает dict; отсутствующий код означает «не базовый, смотри как есть».
    """
    mapping = {c: c for c in BASE_SET}
    try:
        prof = get_active_profile(project_path)
        for s in prof.get("config", {}).get("statuses", []):
            base = s.get("base") or s.get("code")
            if base in BASE_SET:
                mapping[s["code"]] = base
            elif s.get("code") in BASE_SET:
                mapping[s["code"]] = s["code"]
    except Exception as e:
        logger.warning("code_to_base fallback: %s", e)
    return mapping


def status_base(project_path: str, code: str) -> str:
    """Base-семантика кода (для очереди/отчётов/строгости «Плохо»)."""
    if not code:
        return "unreviewed"
    return code_to_base(project_path).get(code, code)


def status_display_name(project_path: str, code: str) -> str:
    """Имя статуса для показа: профиль -> константы -> сам код."""
    try:
        prof = get_active_profile(project_path)
        for s in prof.get("config", {}).get("statuses", []):
            if s.get("code") == code:
                return s.get("name") or code
    except Exception:
        pass
    try:
        from constants import STATUS_NAMES
        return STATUS_NAMES.get(code, code)
    except Exception:
        return code


def status_options(project_path: str) -> list:
    """[(code, name)] для фильтров: включённые профиля + legacy-коды из БД."""
    opts: list = []
    seen: set = set()
    try:
        prof = get_active_profile(project_path)
        for s in enabled_statuses(prof.get("config", {})):
            opts.append((s["code"], s.get("name") or s["code"]))
            seen.add(s["code"])
    except Exception:
        pass
    if "unreviewed" not in seen:
        opts.insert(0, ("unreviewed", "Не проверено"))
        seen.add("unreviewed")
    try:
        with db(project_path) as conn:
            rows = conn.cursor().execute(
                "SELECT DISTINCT status FROM annotations WHERE status IS NOT NULL"
            ).fetchall()
        for r in rows:
            code = r["status"]
            if code and code not in seen:
                opts.append((code, f"{code} (в разметке)"))
                seen.add(code)
    except Exception:
        pass
    return opts
