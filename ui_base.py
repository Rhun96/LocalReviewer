"""Базовый класс экранов: единый refresh() и показ ошибок."""
import logging
from PySide6.QtWidgets import QWidget
from ui_compat import FLUENT, notify

logger = logging.getLogger(__name__)


class BaseScreen(QWidget):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Фон экрана — заливкой из палитры, а не QSS-правилом
        # QWidget[screen=...]: Qt кэширует совпадения dynamic property,
        # и при живом переключении темы фон залипал на старой теме
        # (смесь светлого и тёмного). Палитра обновляется сразу.
        # objectName для этого не годится — затирает Fluent
        # (addSubInterface ставит routeKey).
        if FLUENT:
            self.setAutoFillBackground(True)

    def refresh(self) -> None:
        pass

    def show_error(self, title: str, e: Exception) -> None:
        logger.exception("%s: %s", title, e)
        notify(self, "error", "Ошибка", f"{title}:\n{e}")
