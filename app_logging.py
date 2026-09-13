"""Настройка логирования: консоль + файл logs/localreviewer.log, без содержимого кейсов."""
import logging
import sys
from pathlib import Path


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    root = logging.getLogger()
    if root.handlers:
        return root
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    console = logging.StreamHandler(sys.stderr)
    console.setFormatter(fmt)
    root.addHandler(console)

    try:
        log_dir = Path("logs")
        log_dir.mkdir(exist_ok=True)
        file_handler = logging.FileHandler(log_dir / "localreviewer.log", encoding="utf-8")
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError:
        pass
    return root
