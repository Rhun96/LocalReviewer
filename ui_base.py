"""Базовый класс экранов: единый refresh() и показ ошибок."""
import logging
from PySide6.QtWidgets import QWidget
from ui_compat import notify

logger = logging.getLogger(__name__)


class BaseScreen(QWidget):
    def refresh(self) -> None:
        pass

    def show_error(self, title: str, e: Exception) -> None:
        logger.exception("%s: %s", title, e)
        notify(self, "error", "Ошибка", f"{title}:\n{e}")
