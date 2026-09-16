"""Базовый класс экранов: единый refresh() и показ ошибок."""
import logging
from PySide6.QtWidgets import QWidget
from ui_compat import notify

logger = logging.getLogger(__name__)


class BaseScreen(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Фон точечно по dynamic property: objectName затирает Fluent
        # (addSubInterface ставит routeKey), а blanket-правило QWidget ломало
        # внутренности Fluent-виджетов. См. styles._fluent_base.
        self.setProperty("screen", True)

    def refresh(self) -> None:
        pass

    def show_error(self, title: str, e: Exception) -> None:
        logger.exception("%s: %s", title, e)
        notify(self, "error", "Ошибка", f"{title}:\n{e}")
