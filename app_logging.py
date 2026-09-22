"""Настройка логирования: консоль + файл, без содержимого кейсов.

Файл — <проект>/logs/localreviewer.log, если проект известен,
иначе logs/ рядом с CWD (fallback для стартового экрана).
Ротация 1 МБ × 3, чтобы exe не растил лог бесконечно.
"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured_files: set = set()

_DEBUG_KEY = "privacy/debug_content"


def is_content_debug_enabled() -> bool:
    """Диагностический режим с контентом кейсов: только явное включение.

    По умолчанию False: в обычные логи пишутся только ID/счётчики/ошибки
    (ТЗ V2.2 §2). Включается env LOCALREVIEWER_DEBUG_CONTENT=1 или флагом
    в QSettings (экран настроек). Проверяй этот флаг перед каждым логом,
    куда хочешь положить текст запроса/ответа/бага.
    """
    try:
        if os.environ.get("LOCALREVIEWER_DEBUG_CONTENT", "").strip() == "1":
            return True
        from PySide6.QtCore import QSettings
        v = QSettings("LocalReviewer", "LocalReviewer").value(_DEBUG_KEY, False)
        if isinstance(v, str):
            return v.lower() in ("1", "true", "yes", "on")
        return bool(v)
    except Exception:
        return False


def set_content_debug_enabled(on: bool) -> None:
    try:
        from PySide6.QtCore import QSettings
        QSettings("LocalReviewer", "LocalReviewer").setValue(
            _DEBUG_KEY, bool(on))
    except Exception:
        pass


def _add_file_handler(log_dir: Path) -> None:
    key = str(log_dir.resolve()) if log_dir.exists() else str(log_dir.absolute())
    if key in _configured_files:
        return
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(log_dir / "localreviewer.log", maxBytes=1_000_000,
                                 backupCount=3, encoding="utf-8")
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
        logging.getLogger().addHandler(fh)
        _configured_files.add(key)
    except OSError:
        pass


def setup_logging(level: int = logging.INFO,
                  project_path: str | None = None) -> logging.Logger:
    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(level)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        console = logging.StreamHandler(sys.stderr)
        console.setFormatter(fmt)
        root.addHandler(console)
    else:
        root.setLevel(min(root.level, level))
    if project_path:
        _add_file_handler(Path(project_path) / "logs")
    else:
        _add_file_handler(Path("logs"))
    return root
