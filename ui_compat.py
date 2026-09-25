"""Совместимый слой Fluent UI.

Если установлен PySide6-Fluent-Widgets — используются настоящие fluent-виджеты
и темы (светлая/тёмная/системная). Если нет — тихий fallback на обычные
Qt-виджеты, приложение продолжает работать в классическом виде.
"""
import logging

logger = logging.getLogger(__name__)

try:
    from qfluentwidgets import (
        BodyLabel as _BodyLabel,
        CaptionLabel as _CaptionLabel,
        CardWidget as _CardWidget,
        CheckBox as _CheckBox,
        ComboBox as _ComboBox,
        InfoBar as _InfoBar,
        InfoBarPosition as _InfoBarPosition,
        LineEdit as _LineEdit,
        MessageBox as _MessageBox,
        PrimaryPushButton as _PrimaryPushButton,
        PushButton as _PushButton,
        SpinBox as _SpinBox,
        SubtitleLabel as _SubtitleLabel,
        SwitchButton as _SwitchButton,
        TableWidget as _TableWidget,
        TextEdit as _TextEdit,
        Theme as _Theme,
        TitleLabel as _TitleLabel,
        setTheme as _setTheme,
        setThemeColor as _setThemeColor,
    )
    FLUENT = True
except ImportError:
    FLUENT = False
    _InfoBarPosition = None
    _Theme = None

if FLUENT:
    FPushButton = _PushButton
    FPrimaryButton = _PrimaryPushButton
    FTitleLabel = _TitleLabel
    FSubtitleLabel = _SubtitleLabel
    FBodyLabel = _BodyLabel
    FCaptionLabel = _CaptionLabel
    FCard = _CardWidget
    FLineEdit = _LineEdit
    FTextEdit = _TextEdit

    class FComboBox(_ComboBox):
        """Qt-совместимый addItem(text, userData): у fluent вторым идёт icon."""

        def addItem(self, text, userData=None):  # noqa: N802 (совместимость с Qt)
            super().addItem(text, None, userData)
    FCheckBox = _CheckBox
    FSwitch = _SwitchButton
    FSpinBox = _SpinBox
    FTable = _TableWidget
    InfoBarPosition = _InfoBarPosition
    Theme = _Theme
else:
    from PySide6.QtWidgets import (
        QCheckBox,
        QComboBox,
        QGroupBox,
        QLabel,
        QLineEdit,
        QPushButton,
        QSpinBox,
        QTableWidget,
        QTextEdit,
    )

    class _FallbackButton(QPushButton):
        pass

    FPushButton = _FallbackButton
    FPrimaryButton = _FallbackButton
    FTitleLabel = QLabel
    FSubtitleLabel = QLabel
    FBodyLabel = QLabel
    FCaptionLabel = QLabel
    FCard = QGroupBox
    FLineEdit = QLineEdit
    FTextEdit = QTextEdit
    FComboBox = QComboBox
    FCheckBox = QCheckBox
    FSwitch = QCheckBox  # fallback: обычный чекбокс вместо свитча
    FSpinBox = QSpinBox
    FTable = QTableWidget
    InfoBarPosition = None
    Theme = None


def clear_in_fluent(*widgets) -> None:
    """Сброс декоративного QSS в Fluent-режиме (вид задаёт тема).

    Используется для больших тёмных поверхностей (таблицы/списки/скроллы)
    и неонового текста — иначе в светлой теме чёрные плашки и невидимые буквы.
    """
    if FLUENT:
        for w in widgets:
            try:
                w.setStyleSheet("")
            except Exception:
                pass


def polish_table(table, stretch_last: bool = False) -> None:
    """Единый приличный вид таблицы: без номерного столбца слева, зебра,
    последний столбец тянется на пустое место (иначе справа тёмная пустота).

    Только оформление: данные, сортировки и скроллы не трогает. Номер строки
    и так есть колонкой («Строка»/«ID») там, где нужен.
    """
    try:
        vh = table.verticalHeader()
        vh.setVisible(False)
    except Exception:
        pass
    try:
        table.setAlternatingRowColors(True)
    except Exception:
        pass
    try:
        table.horizontalHeader().setStretchLastSection(bool(stretch_last))
    except Exception:
        pass


def maybe_style(widget, qss: str) -> None:
    """Декоративный тёмный QSS — только в классическом режиме.

    Во Fluent-режиме вид задают тема + базовый QSS, иначе inevitable каша
    (неоновый текст на светлом фоне и наоборот).
    Семантические цвета (статусы, severity) через эту функцию не проводить.
    """
    if not FLUENT:
        widget.setStyleSheet(qss)


def classic_table_style() -> str:
    """Единый QSS классических таблиц отчётов (тёмно-зелёный).

    1-в-1 как было в 4 местах reports_screen (проверено диффом строк):
    те же цвета через токены, та же разметка. Отдельные экраны больше
    не держат копии этого блока.
    """
    from styles import COLORS as _C
    return f"""
        QTableWidget {{
            background-color: {_C['bg_input']};
            border: 1px solid {_C['green_bright']};
            color: {_C['text_bright']};
            font-size: 14px;
            gridline-color: {_C['green_deep']};
        }}
        QTableWidget::item {{ padding: 8px; }}
        QHeaderView::section {{
            background-color: {_C['green_deep']};
            color: {_C['text_bright']};
            border: 1px solid {_C['green_bright']};
            padding: 8px;
            font-weight: bold;
        }}
    """


def accent_button_style(extra: str = "") -> str:
    """Синяя акцентная кнопка (была в 8 местах пятью файлами, 1-в-1).

    extra — добавка внутрь правила QPushButton (например padding).
    """
    return _colored_button("blue", "accent_hover", extra)


def _colored_button(color_key: str, hover_key: str, extra: str = "") -> str:
    from styles import COLORS as _C
    inner = f"border-color: {_C[color_key]}; color: {_C[color_key]};"
    if extra.strip():
        inner += f" {extra.strip()}"
    return (
        f"QPushButton {{ {inner} }} "
        f"QPushButton:hover {{ background-color: {_C[hover_key]}; }}"
    )


def warning_button_style(extra: str = "") -> str:
    """Янтарная кнопка (была в 3 местах, 1-в-1)."""
    return _colored_button("amber", "amber_hover", extra)


def danger_button_style(extra: str = "") -> str:
    """Красная кнопка (1-в-1)."""
    return _colored_button("red", "danger_hover", extra)


def notify(parent, kind: str, title: str, text: str) -> None:
    """Ненавязчивое уведомление: InfoBar во Fluent, QMessageBox в fallback."""
    if FLUENT:
        try:
            from PySide6.QtCore import Qt

            pos = _InfoBarPosition.TOP_RIGHT
            orient = Qt.Orientation.Vertical
            if kind == "success":
                _InfoBar.success(title, text, parent=parent, position=pos,
                                 orient=orient, duration=5000)
            elif kind == "warning":
                _InfoBar.warning(title, text, parent=parent, position=pos,
                                 orient=orient, duration=5000)
            else:
                _InfoBar.error(title, text, parent=parent, position=pos,
                               orient=orient, duration=5000)
            return
        except Exception as e:
            logger.warning("InfoBar failed, fallback to QMessageBox: %s", e)
    from PySide6.QtWidgets import QMessageBox

    if kind == "success":
        QMessageBox.information(parent, title, text)
    elif kind == "warning":
        QMessageBox.warning(parent, title, text)
    else:
        QMessageBox.critical(parent, title, text)


def confirm(parent, title: str, text: str,
            ok_text: str = "Да", cancel_text: str = "Отмена") -> bool:
    """Блокирующий вопрос. Подтверждения нельзя заменить InfoBar (нужен ответ),
    поэтому здесь красивый fluent MessageBox, в fallback — обычный вопрос."""
    if FLUENT:
        try:
            box = _MessageBox(title, text, parent)
            try:
                box.yesButton.setText(ok_text)
                box.cancelButton.setText(cancel_text)
            except Exception:
                pass
            return bool(box.exec())
        except Exception as e:
            logger.warning("MessageBox failed, fallback to QMessageBox: %s", e)
    from PySide6.QtWidgets import QMessageBox
    return QMessageBox.question(
        parent, title, text,
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.No,
    ) == QMessageBox.StandardButton.Yes


ACCENT_GREEN = "#00DD38"
THEME_MODES = ("system", "light", "dark")
THEME_NAMES = {"system": "Системная", "light": "Светлая", "dark": "Тёмная"}


def get_theme_mode() -> str:
    """Тема оформления из настроек приложения (QSettings, не зависит от проекта)."""
    try:
        from PySide6.QtCore import QSettings
        mode = QSettings("LocalReviewer", "LocalReviewer").value("ui/theme", "system")
        return mode if mode in THEME_MODES else "system"
    except Exception:
        return "system"


def set_theme_mode(mode: str) -> str:
    try:
        from PySide6.QtCore import QSettings
        if mode not in THEME_MODES:
            mode = "system"
        QSettings("LocalReviewer", "LocalReviewer").setValue("ui/theme", mode)
        return mode
    except Exception:
        return "system"


def _resolve_effective(mode: str) -> str:
    """system -> light/dark по ОС (через darkdetect из зависимостей Fluent)."""
    if mode in ("light", "dark"):
        return mode
    try:
        import darkdetect
        return "dark" if darkdetect.theme() == "Dark" else "light"
    except Exception:
        return "light"


def effective_theme() -> str:
    """Фактическая тема с учётом системной ('light' или 'dark')."""
    return _resolve_effective(get_theme_mode())


def apply_theme(mode: str = "system") -> str:
    """Применяет тему Fluent + базовый QSS для обычных виджетов.

    Fluent красит только свои виджеты, поэтому фон обычных QWidget/QTableWidget
    и цвет текста задаём сами — иначе окно остаётся светлым, а буквы не видно.
    Палитру приложения синхронизируем с темой: всё, что рисуется через палитру
    (фолбэки, части композитных виджетов), иначе остаётся белым при тёмной теме.
    Возвращает фактический режим.
    """
    if mode not in THEME_MODES:
        mode = "system"
    if not FLUENT:
        return mode
    try:
        theme = {"system": _Theme.AUTO, "light": _Theme.LIGHT, "dark": _Theme.DARK}[mode]
        _setTheme(theme)
        _setThemeColor(ACCENT_GREEN)
        from PySide6.QtWidgets import QApplication
        from styles import FLUENT_BASE_DARK, FLUENT_BASE_LIGHT
        app = QApplication.instance()
        dark = _resolve_effective(mode) == "dark"
        if app is not None:
            # Порядок важен: сначала тема Fluent, затем палитра и QSS.
            # Без принудительных unpolish/polish: на Fluent-окнах они валят
            # приложение при переключении темы (проверено падением).
            # setStyleSheet сам перечитывает стили и перекрашивает окна.
            app.setStyleSheet(FLUENT_BASE_DARK if dark else FLUENT_BASE_LIGHT)
            _push_palette(app, _apply_palette(app, dark))
    except Exception as e:
        logger.warning("apply_theme failed: %s", e)
    return mode


def _apply_palette(app, dark: bool) -> None:
    """Тёмная/светлая палитра приложения под текущую тему."""
    from PySide6.QtGui import QPalette, QColor
    pal = QPalette()
    if dark:
        window, base, text = QColor("#202020"), QColor("#2b2b2b"), QColor("#ffffff")
        dim, accent = QColor("#a0a0a0"), QColor("#4ade80")
        highlight, hl_text = QColor("#2ea043"), QColor("#ffffff")
    else:
        window, base, text = QColor("#f3f3f3"), QColor("#ffffff"), QColor("#1b1b1b")
        dim, accent = QColor("#616161"), QColor("#0b7a34")
        highlight, hl_text = QColor("#0b7a34"), QColor("#ffffff")
    pal.setColor(QPalette.ColorRole.Window, window)
    pal.setColor(QPalette.ColorRole.WindowText, text)
    pal.setColor(QPalette.ColorRole.Base, base)
    pal.setColor(QPalette.ColorRole.AlternateBase, window)
    pal.setColor(QPalette.ColorRole.Text, text)
    pal.setColor(QPalette.ColorRole.Button, base)
    pal.setColor(QPalette.ColorRole.ButtonText, text)
    pal.setColor(QPalette.ColorRole.BrightText, accent)
    pal.setColor(QPalette.ColorRole.Highlight, highlight)
    pal.setColor(QPalette.ColorRole.HighlightedText, hl_text)
    pal.setColor(QPalette.ColorRole.ToolTipBase, base)
    pal.setColor(QPalette.ColorRole.ToolTipText, text)
    try:
        pal.setColor(QPalette.ColorRole.PlaceholderText, dim)
    except Exception:
        pass
    app.setPalette(pal)
    return pal


def _push_palette(app, pal) -> None:
    """Copy the app palette into every widget (fixes live theme switch).

    Plain widgets cache their palette at creation: after app.setPalette()
    they keep painting with the previous theme (dark slabs in light theme
    and vice versa). QSS rules still win where they match, and fresh
    windows inherit exactly these values, so converging to them is safe.
    """
    try:
        widgets = list(app.allWidgets())
    except Exception:
        return
    for w in widgets:
        try:
            w.setPalette(pal)
        except Exception:
            continue


def elide_middle(text: str, limit: int = 45) -> str:
    """Укорачивает длинные строки для комбо-списков (полный текст — в userData)."""
    text = str(text or "")
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def add_elided_item(combo, text: str, user_data=None, limit: int = 45) -> None:
    """addItem с обрезанным отображением. Логика — только по userData/currentData.

    Иначе всплывающий список комбо разъезжается на весь экран на длинных
    названиях колонок (и в оконном режиме тоже).
    """
    combo.addItem(elide_middle(text, limit),
                  text if user_data is None else user_data)


def bound_combo_popup(combo, max_width: int = 560, max_rows: int = 12) -> None:
    """Всплывающий список в пределах экрана: ширина + число видимых строк.

    У Fluent-комбо нет .view() (свой попап) — там работает только
    setMaxVisibleItems; у классического QComboBox — оба механизма.
    """
    try:
        if hasattr(combo, "setMaxVisibleItems"):
            combo.setMaxVisibleItems(max_rows)
    except Exception:
        pass
    try:
        from PySide6.QtCore import Qt as _Qt
        view = combo.view()
        view.setHorizontalScrollBarPolicy(_Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        win = view.window()
        if win is not None and max_width:
            win.setMaximumWidth(max_width)
    except Exception:
        pass


def mapping_label(header, samples: list) -> str:
    """Rich-text подпись колонки в маппинге: жирное имя + серые примеры.

    Имя и примеры визуально разделены — не сливаются и не путаются.
    """
    import html as _html
    name = _html.escape(str(header))
    if not samples:
        return f"<b>{name}</b>"
    shown = "<br>".join("↳ " + _html.escape(str(s)[:60]) for s in samples[:2])
    return (f"<b>{name}</b>"
            f'<br><span style="color:#888888; font-size:11px;">{shown}</span>')
