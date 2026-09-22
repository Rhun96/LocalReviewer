"""Безопасный clipboard (ТЗ V2.2 §3): автоочистка только своего содержимого.

Поведение:
- настройка «Автоматически очищать буфер обмена»: Выкл / 30с / 60с / 5 мин
  (глобально, QSettings — не зависит от проекта);
- после Copy запоминаем fingerprint (sha256) скопированного текста;
- через заданное время очищаем clipboard ТОЛЬКО если там всё ещё наше
  содержимое (пользователь ничего не скопировал поверх);
- чужой текст никогда не трогаем.

Архитектура: UI -> clipboard_service -> QClipboard. Никакой бизнес-логики
в UI-файлах: UI только вызывает safe_copy() и показывает текст уведомления.
"""
import hashlib
import logging

logger = logging.getLogger(__name__)

ORG = "LocalReviewer"
APP = "LocalReviewer"
_K_CLEAR_AFTER = "privacy/clipboard_clear_after"

OFF = 0
TIMEOUT_30 = 30
TIMEOUT_60 = 60
TIMEOUT_300 = 300
ALLOWED = (OFF, TIMEOUT_30, TIMEOUT_60, TIMEOUT_300)
DEFAULT_TIMEOUT = TIMEOUT_60

# Последний наш fingerprint: {"hash": str} или None. Нужен таймеру очистки,
# чтобы не снести чужой текст, скопированный поверх нашего.
_PENDING: dict = {"hash": None}
# Дедлайн автоочистки (time.monotonic) или None (выкл/уже очищено).
_DEADLINE: dict = {"at": None}


def fingerprint(text: str) -> str:
    """Стабильный отпечаток содержимого (sha256 hex)."""
    if not isinstance(text, str):
        text = str(text)
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()


def should_clear(stored_hash: str | None, current_text: str | None) -> bool:
    """Решение для тестов и таймера: чистить только своё.

    - stored_hash None -> False (мы ничего не копировали);
    - current_text пустой/None -> False (уже пусто, нечего делать);
    - иначе True только при совпадении fingerprint.
    """
    if not stored_hash:
        return False
    if not current_text:
        return False
    try:
        return fingerprint(current_text) == stored_hash
    except Exception:
        return False


def _qs():
    from PySide6.QtCore import QSettings
    return QSettings(ORG, APP)


def get_clear_after() -> int:
    """Таймаут автоочистки в секундах (0 = выкл)."""
    try:
        v = _qs().value(_K_CLEAR_AFTER, DEFAULT_TIMEOUT)
        v = int(v)
        return v if v in ALLOWED else DEFAULT_TIMEOUT
    except Exception:
        return DEFAULT_TIMEOUT


def set_clear_after(seconds: int) -> None:
    """Сохранить таймаут (только из ALLOWED, иначе игнор)."""
    if seconds not in ALLOWED:
        return
    try:
        _qs().setValue(_K_CLEAR_AFTER, int(seconds))
    except Exception as e:
        logger.warning("clipboard timeout save failed: %s", e)


def timeout_label(seconds: int) -> str:
    return {0: "Выкл.", 30: "30 секунд",
            60: "60 секунд", 300: "5 минут"}.get(seconds, str(seconds))


def safe_copy(text: str) -> str:
    """Положить текст в системный clipboard и взвести автоочистку.

    Возвращает fingerprint (для тестов/диагностики). Никогда не бросает
    исключение наружу: копирование не должно ронять ревью.
    """
    fp = fingerprint(text)
    try:
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is not None:
            cb.setText(text)
    except Exception as e:
        logger.warning("clipboard copy failed: %s", e)
        return fp
    _PENDING["hash"] = fp
    timeout = get_clear_after()
    try:
        import time
        _DEADLINE["at"] = (time.monotonic() + timeout) if timeout > 0 else None
    except Exception:
        _DEADLINE["at"] = None
    if timeout > 0:
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(timeout * 1000,
                              lambda: _maybe_clear(fp))
        except Exception as e:
            logger.warning("clipboard timer failed: %s", e)
    return fp


def _maybe_clear(wanted_hash: str) -> None:
    """Слот таймера: чистим только если fingerprint совпал и актуален."""
    try:
        if _PENDING.get("hash") != wanted_hash:
            return  # уже было новое копирование — старый таймер молча гаснет
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is None:
            return
        current = cb.text()
        if should_clear(wanted_hash, current):
            cb.clear()
            _PENDING["hash"] = None
            _DEADLINE["at"] = None
    except Exception as e:
        logger.warning("clipboard clear failed: %s", e)


def pending_hash() -> str | None:
    """Текущий ожидающий fingerprint (для тестов/дiagnostics, без Qt)."""
    return _PENDING.get("hash")


def reset_pending() -> None:
    _PENDING["hash"] = None
    _DEADLINE["at"] = None


_MONITORED: dict = {"on": False}


def _on_clipboard_changed():
    """Монитор (ТЗ V2.2 §3): любая копия ИЗ программы взводит таймер.

    Нативные Ctrl+C/Copy по выделению идут мимо safe_copy — ловим их здесь.
    Чужое отличаем по активному окну: копируешь в Jira/браузере — наше окно
    неактивно, игнорим (не трогаем и не показываем). Своё повторное —
    уже взведено, второй таймер не нужен.
    """
    try:
        from PySide6.QtWidgets import QApplication
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is None:
            return
        text = cb.text()
        if not text:
            return  # пусто (в т.ч. наша же очистка) — нечего охранять
        fp = fingerprint(text)
        if fp == _PENDING.get("hash"):
            return  # наше через safe_copy — уже взведено
        if QApplication.activeWindow() is None:
            return  # окно чужое — не трогаем
        timeout = get_clear_after()
        if timeout <= 0:
            return  # автоочистка выкл — не следим
        import time
        _PENDING["hash"] = fp
        _DEADLINE["at"] = time.monotonic() + timeout
        try:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(timeout * 1000,
                              lambda: _maybe_clear(fp))
        except Exception as e:
            logger.warning("clipboard monitor timer failed: %s", e)
    except Exception as e:
        logger.warning("clipboard monitor failed: %s", e)


def install_monitor() -> bool:
    """Подключить монитор к системному clipboard (идемпотентно)."""
    if _MONITORED.get("on"):
        return True
    try:
        from PySide6.QtGui import QGuiApplication
        cb = QGuiApplication.clipboard()
        if cb is None:
            return False
        cb.dataChanged.connect(_on_clipboard_changed)
        _MONITORED["on"] = True
        return True
    except Exception as e:
        logger.warning("clipboard monitor install failed: %s", e)
        return False


def countdown_state() -> int | None:
    """Остаток секунд до автоочистки для пилюли в шапке ревью.

    None — пилюлю прячем: таймаут выкл, время вышло, буфер уже пуст или
    пользователь скопировал что-то своё поверх (чужое не трогаем и не
    показываем). Только чтение, исключений наружу нет.
    """
    try:
        import math
        import time
        at = _DEADLINE.get("at")
        fp = _PENDING.get("hash")
        if not at or not fp:
            return None
        left = math.ceil(at - time.monotonic())
        if left <= 0:
            return None
        try:
            from PySide6.QtGui import QGuiApplication
            cb = QGuiApplication.clipboard()
            current = cb.text() if cb is not None else ""
        except Exception:
            return None
        if not should_clear(fp, current):
            return None
        return left
    except Exception:
        return None
