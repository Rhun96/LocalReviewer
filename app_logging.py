"""Настройка логирования: консоль + файл, без содержимого кейсов.

Файл — <проект>/logs/localreviewer.log, если проект известен,
иначе logs/ рядом с CWD (fallback для стартового экрана).
Ротация 1 МБ × 3, чтобы exe не растил лог бесконечно.
"""
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_configured_files: set = set()


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
