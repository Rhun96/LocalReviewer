"""Рабочее состояние V2.1 P0: последний проект + recent + per-project view-state.

Разделение (осознанно):
- глобальное — QSettings (не зависит от проекта): restore-флаг, last project,
  recent-список. Хранить это в settings-таблице проекта нельзя: до открытия
  проекта её негде прочитать.
- per-project — settings-таблица проекта (sess_* ключи, без миграции):
  screen/file/case/queue/filters/columns/sort/page/view.

Валидация при загрузке: битое состояние не восстанавливаем бесконечно —
возвращаем ближайшее живое (без кейса/фильтра), проект без базы — None.
"""
import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ORG = "LocalReviewer"
APP = "LocalReviewer"
RECENT_MAX = 5

_K_RESTORE = "session/restore"
_K_LAST = "session/last_project"
_K_RECENT = "session/recent"

SCREENS = ("project", "review", "runs", "bugs", "launches", "reports",
           "history", "backup", "settings")
QUEUES = ("normal", "unreviewed", "problematic")
SORTS = ("import", "unreviewed_first", "problematic_first")

SESS_KEYS = ("sess_screen", "sess_file_id", "sess_case_id", "sess_queue",
             "sess_filters", "sess_columns", "sess_sort", "sess_page",
             "sess_view")


def _qs():
    from PySide6.QtCore import QSettings
    return QSettings(ORG, APP)


# --- глобальное ---

def is_restore_enabled() -> bool:
    try:
        v = _qs().value(_K_RESTORE, True)
        if isinstance(v, str):
            return v.lower() not in ("0", "false", "no", "off")
        return bool(v)
    except Exception:
        return True


def set_restore_enabled(on: bool) -> None:
    try:
        _qs().setValue(_K_RESTORE, bool(on))
    except Exception as e:
        logger.warning("session restore flag save failed: %s", e)


def _valid_project(path: str | None) -> str | None:
    if not path:
        return None
    try:
        p = Path(path)
        if (p / "project.sqlite").exists():
            return str(p)
    except Exception:
        pass
    return None


def get_last_project() -> str | None:
    try:
        return _valid_project(_qs().value(_K_LAST, None))
    except Exception:
        return None


def set_last_project(path: str) -> None:
    try:
        _qs().setValue(_K_LAST, str(path))
    except Exception as e:
        logger.warning("last project save failed: %s", e)


def get_recent_projects() -> list:
    """Recent-список: доступные первыми, недоступные — с флагом (не удаляем)."""
    try:
        raw = _qs().value(_K_RECENT, [])
    except Exception:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            raw = [raw]
    if not isinstance(raw, list):
        return []
    out = []
    for p in raw:
        if not isinstance(p, str) or not p:
            continue
        ok = _valid_project(p) is not None
        out.append({"path": p, "available": ok})
    # доступные вверх, порядок recency внутри групп сохраняем
    out.sort(key=lambda d: (not d["available"],))
    return out[:RECENT_MAX]


def add_recent_project(path: str) -> list:
    try:
        qs = _qs()
        raw = qs.value(_K_RECENT, [])
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except Exception:
                raw = [raw]
        if not isinstance(raw, list):
            raw = []
        items = [p for p in raw if isinstance(p, str) and p and p != str(path)]
        items.insert(0, str(path))
        items = items[:RECENT_MAX]
        qs.setValue(_K_RECENT, items)
        qs.setValue(_K_LAST, str(path))
        return items
    except Exception as e:
        logger.warning("recent save failed: %s", e)
        return []


def clear_session() -> None:
    """'Начать с чистого': только сохранённая сессия, не данные проектов."""
    try:
        qs = _qs()
        qs.remove("session")
    except Exception as e:
        logger.warning("session clear failed: %s", e)


# --- per-project ---

def save_project_session(project_path: str, state: dict) -> None:
    """Пишет sess_*-ключи в settings проекта. Невалидное молча пропускаем."""
    from database import db, utcnow
    pairs: dict = {}
    screen = state.get("screen")
    if screen in SCREENS:
        pairs["sess_screen"] = screen
    fid = state.get("file_id")
    if isinstance(fid, int) and fid > 0:
        pairs["sess_file_id"] = str(fid)
    cid = state.get("case_id")
    if isinstance(cid, int) and cid > 0:
        pairs["sess_case_id"] = str(cid)
    q = state.get("queue")
    if q in QUEUES:
        pairs["sess_queue"] = q
    flt = state.get("filters")
    if isinstance(flt, dict):
        try:
            pairs["sess_filters"] = json.dumps(flt, ensure_ascii=False)[:20000]
        except Exception:
            pass
    cols = state.get("columns")
    if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
        try:
            pairs["sess_columns"] = json.dumps(cols[:64], ensure_ascii=False)
        except Exception:
            pass
    srt = state.get("sort")
    if srt in SORTS:
        pairs["sess_sort"] = srt
    page = state.get("page")
    if isinstance(page, int) and 0 <= page < 100000:
        pairs["sess_page"] = str(page)
    view = state.get("view")
    if isinstance(view, int) and view in (0, 1):
        pairs["sess_view"] = str(view)
    if not pairs:
        return
    try:
        now = utcnow()
        with db(project_path) as conn:
            for k, v in pairs.items():
                conn.execute(
                    "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                    "updated_at=excluded.updated_at", (k, v, now))
    except Exception as e:
        logger.warning("project session save failed: %s", e)


def load_project_session(project_path: str) -> dict:
    """Читает + валидирует sess_*-ключи. Битое → ближайшее живое."""
    from database import db
    try:
        with db(project_path) as conn:
            rows = {r["key"]: r["value"] for r in conn.execute(
                "SELECT key, value FROM settings WHERE key LIKE 'sess_%'").fetchall()}
    except Exception as e:
        logger.warning("project session load failed: %s", e)
        return {}
    out: dict = {}
    if rows.get("sess_screen") in SCREENS:
        out["screen"] = rows["sess_screen"]
    try:
        fid = int(rows.get("sess_file_id") or 0)
        if fid > 0:
            out["file_id"] = fid
    except (TypeError, ValueError):
        pass
    try:
        cid = int(rows.get("sess_case_id") or 0)
        if cid > 0:
            out["case_id"] = cid
    except (TypeError, ValueError):
        pass
    if rows.get("sess_queue") in QUEUES:
        out["queue"] = rows["sess_queue"]
    if rows.get("sess_filters"):
        try:
            flt = json.loads(rows["sess_filters"])
            if isinstance(flt, dict):
                out["filters"] = flt
        except Exception:
            pass
    if rows.get("sess_columns"):
        try:
            cols = json.loads(rows["sess_columns"])
            if isinstance(cols, list) and all(isinstance(c, str) for c in cols):
                out["columns"] = cols
        except Exception:
            pass
    if rows.get("sess_sort") in SORTS:
        out["sort"] = rows["sess_sort"]
    try:
        if rows.get("sess_page") is not None:
            out["page"] = max(0, int(rows["sess_page"]))
    except (TypeError, ValueError):
        pass
    try:
        if rows.get("sess_view") in ("0", "1"):
            out["view"] = int(rows["sess_view"])
    except (TypeError, ValueError):
        pass
    # Сверка с реальностью: файл/кейс могли исчезнуть.
    try:
        from database import db as _db
        with _db(project_path) as conn:
            if "file_id" in out and not conn.execute(
                    "SELECT 1 FROM files WHERE file_id=?",
                    (out["file_id"],)).fetchone():
                out.pop("file_id", None)
            if "case_id" in out and not conn.execute(
                    "SELECT 1 FROM cases WHERE case_id=?",
                    (out["case_id"],)).fetchone():
                out.pop("case_id", None)
    except Exception:
        pass
    return out


def clear_project_session(project_path: str) -> None:
    try:
        from database import db
        with db(project_path) as conn:
            conn.execute("DELETE FROM settings WHERE key LIKE 'sess_%'")
    except Exception as e:
        logger.warning("project session clear failed: %s", e)
