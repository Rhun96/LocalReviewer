"""Клавиши уровня приложения — обход мёртвого QShortcutMap.

Контекст (проверено): на рабочей машине пользователя молчит ВЕСЬ QShortcut
(Ctrl+Z/H/A/P — тишина), хотя кнопки, нативный Ctrl+C и остальное живы, а
offscreen-пробы показывают корректную регистрацию и доставку. Внешнюю
причину (раскладка/перехватчик) из кода не чиним — ловим сырой KeyPress
фильтром приложения: он идёт до shortcutmap и не зависит от контекстов,
override и фокуса в полях (у Ctrl+P нет нативного текстового биндинга).

Фильтр ест ТОЛЬКО точное совпадение и возвращает True — дальше событие не
идёт, поэтому двойных срабатываний нет даже там, где QShortcut жив.
Модалка открыта — не лезем поверх. Вне ревью — молчим.
"""
import logging

from PySide6.QtCore import QObject, QEvent, Qt

logger = logging.getLogger(__name__)


def _review_ancestor(w):
    """Ближайший ReviewScreen вверх по родителям (или None)."""
    p = w
    seen = 0
    while p is not None and seen < 64:
        try:
            if p.__class__.__name__ == "ReviewScreen":
                return p
            p = p.parentWidget()
        except Exception:
            return None
        seen += 1
    return None


class ReviewKeysFilter(QObject):
    """Ctrl+P -> глобальный поиск кейса (диалог, не хоткей статуса)."""

    def eventFilter(self, obj, ev):
        try:
            if ev.type() != QEvent.Type.KeyPress:
                return False
            # Модификаторы — по маске, а не ==: NumLock/Caps добавляют свои
            # флаги, со строгим сравнением хоткей молча умирал бы у всех.
            _wanted = Qt.KeyboardModifier.ControlModifier
            _ban = (Qt.KeyboardModifier.ShiftModifier
                    | Qt.KeyboardModifier.AltModifier
                    | Qt.KeyboardModifier.MetaModifier)
            if not (ev.modifiers() & _wanted) or (ev.modifiers() & _ban):
                return False
            if ev.key() != Qt.Key.Key_P:
                return False
            from PySide6.QtWidgets import QApplication
            if QApplication.activeModalWidget() is not None:
                return False
            rev = _review_ancestor(QApplication.focusWidget())
            if rev is None:
                return False
            try:
                rev.open_global_search()
            except Exception as e:
                logger.warning("global keys Ctrl+P failed: %s", e)
            return True
        except Exception:
            return False


def install_global_keys(app) -> bool:
    """Вешает фильтр на приложение (идемпотентно, живёт пока жив app)."""
    try:
        if getattr(app, "_lr_keys_installed", False):
            return True
        app.installEventFilter(ReviewKeysFilter(app))
        app._lr_keys_installed = True
        return True
    except Exception as e:
        logger.warning("global keys install failed: %s", e)
        return False
