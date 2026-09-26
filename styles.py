"""
Продвинутая чёрно-зелёная тема для Local Reviewer.
Версия 3: боковая панель, компактные кнопки.
Плюс FLUENT_BASE_* — нейтральные базовые темы для Fluent-режима
(Fluent красит только свои виджеты, обычные QWidget красим сами под тему).
"""

from PySide6.QtWidgets import QGraphicsDropShadowEffect
from PySide6.QtGui import QColor

# Основная палитра
COLORS = {
    'bg_dark': '#000000',
    'bg_panel': '#0A0F0A',
    'bg_card': '#0D150D',
    'bg_card_hover': '#122012',
    'bg_input': '#001A0A',
    'bg_hover': '#0F2010',
    'bg_active': '#1A3A1A',
    'bg_sidebar': '#050A05',
    'green_bright': '#00FF41',
    # Белый текст классики (0.6.1): зелёным остаются только рамки,
    # подсветки и семантика (статусы/severity). Один токен — смена в 1 месте.
    'text_bright': '#e8e8e8',
    'green_main': '#00DD38',
    'green_dark': '#00AA2A',
    'green_dim': '#007722',
    'red': '#FF3B3B',
    'red_dark': '#CC2222',
    # Ховеры кнопок (жили россыпью по экранам, значения 1-в-1).
    'danger_hover': '#330000',
    'amber_hover': '#332200',
    # Светлый красный сайдбара (единственное место, оттенок свой).
    'red_light': '#FF6666',
    'red_border': '#662222',
    # Кирпичный gate-карточек и подсветки (темнее danger, оттенок свой).
    'gate_red': '#C0392B',
    # Мягкая рамка (таблицы/карточки, где border_dim слишком зелёный).
    'border_soft': '#3A3A3A',
    # Жёлтый подсветки фрагментов (свой оттенок).
    'highlight_yellow': '#E3B008',
    'pure_white': '#FFFFFF',
    'pure_black': '#000000',
    'yellow': '#FFD700',
    'orange': '#FF9900',
    # Янтарь предупреждений (#FFAA00 живёт в ~10 местах по экранам).
    'amber': '#FFAA00',
    'blue': '#00AAFF',
    # Ховер синей кнопки (жил в 8 местах пятью файлами).
    'accent_hover': '#002233',
    'gray': '#888888',
    'border': '#00FF41',
    'border_dim': '#00441A',
    # Глубокий зелёный шапок таблиц (жил в 4+ местах reports_screen).
    'green_deep': '#003315',
}

# Семантика reskin-ветки: один смысл — один цвет. Нейтральные значения
# читаются на тёмной И светлой темах (в отличие от неоновых из COLORS).
SEMANTIC = {
    'success': '#2ea043',
    'danger': '#da3633',
    'warning': '#bf8700',
    'info': '#1f6feb',
}

# Цвета diff-подсветки ответов (тёмные пары фон/текст, оттенки свои).
DIFF = {
    'del_bg': '#5a1a1a',
    'del_text': '#ffb3b3',
    'add_bg': '#1a4a22',
    'add_text': '#b3ffbf',
}

# Серии круговых диаграмм (фиксированные, вне тем — как было).
CHART_SERIES = {
    'unreviewed': '#555555',
    'good': '#00CC44',
    'bad': '#CC3333',
    'uncertain': '#CCAA00',
    'duplicate': '#CC7700',
    'skip': '#888888',
}

# Приглушённая серия для светлой темы (добой §3: неон на белом резал глаз).
# Только токены styles.py (hex-гард вне styles не трогаем).
CHART_SERIES_LIGHT = {
    'unreviewed': '#888888',
    'good': '#2ea043',
    'bad': '#da3633',
    'uncertain': '#bf8700',
    'duplicate': '#b26a00',
    'skip': '#888888',
}

# Палитры Fluent-тем (reskin batch 4): единый источник для QSS-базы
# (_fluent_base) и QPalette (_apply_palette в ui_compat). Значения 1-в-1
# как были россыпью, ключи совпадают с аргументами _fluent_base.
FLUENT_DARK = {
    'bg': '#202020',
    'bg_card': '#2b2b2b',
    'bg_input': '#2b2b2b',
    'text': '#ffffff',
    'text_dim': '#a0a0a0',
    'border': '#3a3a3a',
    'accent': '#4ade80',
    'accent_soft': '#1d3a28',
    'header_bg': '#2d2d2d',
    'sel_bg': '#2ea043',
    'sel_text': '#ffffff',
}

FLUENT_LIGHT = {
    'bg': '#f3f3f3',
    'bg_card': '#ffffff',
    'bg_input': '#ffffff',
    'text': '#1b1b1b',
    'text_dim': '#616161',
    'border': '#e0e0e0',
    'accent': '#0b7a34',
    'accent_soft': '#d3e9dc',
    'header_bg': '#ececec',
    'sel_bg': '#0b7a34',
    'sel_text': '#ffffff',
}

# Палитры графиков matplotlib (reskin batch 4): единый источник для
# _chart_palette в reports_screen. Значения 1-в-1 как были.
CHART_DARK = {
    'style': 'dark_background',
    'bg': '#0A0F0A',
    'fg': '#e8e8e8',
    'spine': '#3a3a3a',
    'bar_total': '#1d5c33',
    'bar_done': '#00CC66',
    'pct_stroke': '#000000',
}

CHART_LIGHT = {
    'style': 'default',
    'bg': '#ffffff',
    'fg': '#1b1b1b',
    'spine': '#cccccc',
    'bar_total': '#bcd8c6',
    'bar_done': '#0b7a34',
    'pct_stroke': '#ffffff',
}

def apply_shadow(widget, color='#00FF41', blur=25, offset=4, alpha=50):
    """Добавляет тень к виджету. Хранит ссылку на виджете, чтобы GC не съел эффект."""
    if not isinstance(color, str) or len(color) != 7 or not color.startswith('#'):
        raise ValueError(f"Bad color: {color!r}, expected '#RRGGBB'")
    try:
        r, g, b = int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)
    except ValueError:
        raise ValueError(f"Bad color: {color!r}, expected '#RRGGBB'") from None
    shadow = QGraphicsDropShadowEffect(widget)
    shadow.setBlurRadius(blur)
    shadow.setColor(QColor(r, g, b, alpha))
    shadow.setOffset(0, offset)
    widget.setGraphicsEffect(shadow)
    # Удерживаем ссылку: без этого PySide может собрать эффект и тени пропадут/упадёт
    widget.setProperty("_shadow", shadow)
    if not hasattr(widget, "_shadows"):
        widget._shadows = []
    widget._shadows.append(shadow)
    return shadow

# === Дизайн-токены 0.6.0: один смысл — один размер ===
# Ритм отступов 4/8/16/24, три кегля, два радиуса. Новые стили — только
# через токены, захардкоженных px по коду не разбрасываем.
UI_TOKENS = {
    "space_xs": 4,
    "space_s": 8,
    "space_m": 16,
    "space_l": 24,
    "font_title": 15,
    "font_body": 13,
    "font_small": 11,
    "radius_s": 6,
    "radius_m": 8,
}

# === Референс-палитра (старый визуал ChatGPT, hex — лучшее чтение
# со скрина, править построчно при сверке; кегли НЕ трогаем:
# веб-масштаб 20/24 ломает десктопные шапки) ===
REF_COLORS = {
    'bg_dark': '#0d1117',
    'bg_panel': '#12181d',
    'bg_card': '#1a2129',
    'bg_card_hover': '#212a33',
    'bg_input': '#161d24',
    'bg_hover': '#1f2933',
    'bg_active': '#28323d',
    'bg_sidebar': '#0b0f14',
    'green_bright': '#00ff41',
    'text_bright': '#e6edf3',
    'green_main': '#00ff41',
    'green_dark': '#00cc33',
    'green_dim': '#0a5c2a',
    'red': '#ff4d4f',
    'red_dark': '#b32b2b',
    'danger_hover': '#2a0d0d',
    'amber_hover': '#332a00',
    'red_light': '#ff8080',
    'red_border': '#5a2a2a',
    'gate_red': '#C0392B',
    'border_soft': '#30363d',
    'highlight_yellow': '#E3B008',
    'pure_white': '#FFFFFF',
    'pure_black': '#000000',
    'yellow': '#f5c518',
    'orange': '#FF9900',
    'amber': '#f5c518',
    'blue': '#4da3ff',
    'accent_hover': '#0f1e2e',
    'gray': '#8b949e',
    'border': '#00ff41',
    'border_dim': '#24313a',
    'green_deep': '#0f2e1c',
}

REF_FLUENT_DARK = {
    'bg': '#12181d',
    'bg_card': '#1a2129',
    'bg_input': '#161d24',
    'text': '#e6edf3',
    'text_dim': '#8b949e',
    'border': '#30363d',
    'accent': '#00ff41',
    'accent_soft': '#0f2e1c',
    'header_bg': '#161d24',
    'sel_bg': '#00cc33',
    'sel_text': '#ffffff',
}

REF_CHART_DARK = {
    'style': 'dark_background',
    'bg': '#12181d',
    'fg': '#e6edf3',
    'spine': '#30363d',
    'bar_total': '#1d4a30',
    'bar_done': '#00cc33',
    'pct_stroke': '#000000',
}


def _palette_variant() -> str:
    """classic | ref: env LR_PALETTE важнее QSettings ui/palette."""
    try:
        import os as _os
        v = (_os.environ.get("LR_PALETTE") or "").strip().lower()
        if v in ("classic", "ref"):
            return v
    except Exception:
        pass
    try:
        from PySide6.QtCore import QSettings as _QS
        v = str(_QS("LocalReviewer", "LocalReviewer").value(
            "ui/palette", "classic") or "classic")
        return "ref" if v.strip().lower() == "ref" else "classic"
    except Exception:
        return "classic"


# Переключатель, НЕ замена: литералы выше целы (гард токенов парсит
# их как есть), мутация in-place — все потребители видят один объект.
# Светлая тема и SEMANTIC/DIFF/серии — общие для обоих вариантов.
if _palette_variant() == "ref":
    COLORS.update(REF_COLORS)
    FLUENT_DARK.update(REF_FLUENT_DARK)
    CHART_DARK.update(REF_CHART_DARK)
    UI_TOKENS.update({"radius_s": 8, "radius_m": 12})

# Глобальный стиль приложения
APP_STYLE = f"""
/* === ОБЩИЕ НАСТРОЙКИ === */
QMainWindow {{
    background-color: {COLORS['bg_dark']};
}}
QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['text_bright']};
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}}

/* === ЗАГОЛОВКИ === */
QLabel {{
    color: {COLORS['text_bright']};
    font-size: 13px;
    background: transparent;
}}
QLabel#title {{
    font-size: 32px;
    font-weight: 900;
    color: {COLORS['text_bright']};
    padding: 15px;
    letter-spacing: 3px;
}}
QLabel#subtitle {{
    font-size: 14px;
    color: {COLORS['green_dark']};
    padding: 8px;
    letter-spacing: 1px;
}}

/* === КНОПКИ === */
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLORS['bg_hover']},
        stop:1 {COLORS['bg_card']}
    );
    color: {COLORS['text_bright']};
    border: 2px solid {COLORS['green_dark']};
    border-radius: 8px;
    padding: 8px 10px;
    font-size: 13px;
    font-weight: bold;
    text-align: center;
    min-width: 60px;
    min-height: 35px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLORS['bg_active']},
        stop:1 {COLORS['bg_hover']}
    );
    border-color: {COLORS['green_bright']};
    color: {COLORS['text_bright']};
}}
QPushButton:pressed {{
    background-color: {COLORS['green_bright']};
    color: {COLORS['bg_dark']};
    border-color: {COLORS['green_bright']};
}}
QPushButton:disabled {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['green_dim']};
    border-color: {COLORS['border_dim']};
}}

/* Кнопка "Опасность" */
QPushButton#danger {{
    border-color: {COLORS['red']};
    color: {COLORS['red']};
}}
QPushButton#danger:hover {{
    background-color: #330000;
    border-color: #FF6666;
    color: #FF6666;
}}

/* === КАРТОЧКИ === */
QGroupBox {{
    background-color: {COLORS['bg_card']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 10px;
    margin-top: 15px;
    padding: 20px 15px 15px 15px;
    font-weight: bold;
    font-size: 13px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 6px 15px;
    background-color: {COLORS['bg_active']};
    border: 2px solid {COLORS['green_dark']};
    border-radius: 6px;
    color: {COLORS['text_bright']};
    left: 15px;
    font-size: 13px;
}}

/* === ПОЛЯ ВВОДА === */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 6px;
    color: {COLORS['text_bright']};
    padding: 10px;
    font-size: 13px;
    selection-background-color: {COLORS['green_dark']};
    selection-color: {COLORS['bg_dark']};
}}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {COLORS['green_bright']};
}}
QLineEdit::placeholder {{
    color: {COLORS['green_dim']};
}}

/* === ВЫПАДАЮЩИЕ СПИСКИ === */
QComboBox {{
    background-color: {COLORS['bg_input']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 6px;
    color: {COLORS['text_bright']};
    padding: 8px 12px;
    font-size: 12px;
}}
QComboBox:hover {{
    border-color: {COLORS['green_bright']};
}}
QComboBox::drop-down {{
    border: none;
    width: 30px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 7px solid {COLORS['green_bright']};
    margin-right: 12px;
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_card']};
    border: 2px solid {COLORS['green_bright']};
    border-radius: 6px;
    color: {COLORS['text_bright']};
    selection-background-color: {COLORS['bg_active']};
}}

/* === ЧЕКБОКСЫ === */
QCheckBox {{
    spacing: 10px;
    color: {COLORS['text_bright']};
    font-size: 12px;
}}
QCheckBox::indicator {{
    width: 20px;
    height: 20px;
    border: 2px solid {COLORS['green_dim']};
    border-radius: 4px;
    background-color: {COLORS['bg_input']};
}}
QCheckBox::indicator:hover {{
    border-color: {COLORS['green_bright']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['green_bright']};
    border-color: {COLORS['green_bright']};
}}

/* === ТАБЛИЦЫ === */
QTableWidget {{
    background-color: {COLORS['bg_card']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 8px;
    color: {COLORS['text_bright']};
    font-size: 12px;
    gridline-color: {COLORS['border_dim']};
    alternate-background-color: {COLORS['bg_panel']};
}}
QTableWidget::item {{
    padding: 8px;
    border: none;
}}
QTableWidget::item:selected {{
    background-color: {COLORS['bg_active']};
    color: {COLORS['text_bright']};
}}
QTableWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
}}
QHeaderView::section {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLORS['bg_active']},
        stop:1 {COLORS['bg_card']}
    );
    color: {COLORS['text_bright']};
    border: 1px solid {COLORS['green_dim']};
    padding: 10px;
    font-weight: bold;
    font-size: 12px;
}}

/* === СПИСКИ === */
QListWidget {{
    background-color: {COLORS['bg_card']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 8px;
    color: {COLORS['text_bright']};
    font-size: 12px;
    outline: none;
}}
QListWidget::item {{
    padding: 12px;
    border: none;
    border-bottom: 1px solid {COLORS['border_dim']};
}}
QListWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
}}
QListWidget::item:selected {{
    background-color: {COLORS['bg_active']};
    color: {COLORS['text_bright']};
}}

/* === ВКЛАДКИ === */
QTabWidget::pane {{
    border: 2px solid {COLORS['green_dim']};
    border-radius: 8px;
    background-color: {COLORS['bg_card']};
}}
QTabBar::tab {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['green_dark']};
    border: 2px solid {COLORS['green_dim']};
    border-bottom: none;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    padding: 12px 24px;
    font-size: 13px;
    margin-right: 4px;
}}
QTabBar::tab:selected {{
    background-color: {COLORS['bg_active']};
    color: {COLORS['text_bright']};
    border-color: {COLORS['green_bright']};
    font-weight: bold;
}}
QTabBar::tab:hover:!selected {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['green_main']};
}}

/* === СКРОЛЛБАРЫ === */
QScrollBar:vertical {{
    background-color: {COLORS['bg_dark']};
    width: 14px;
    margin: 0;
    border-radius: 7px;
}}
QScrollBar::handle:vertical {{
    background-color: {COLORS['green_dim']};
    min-height: 40px;
    border-radius: 7px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background-color: {COLORS['green_dark']};
}}
QScrollBar::handle:vertical:pressed {{
    background-color: {COLORS['green_bright']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    background: none;
}}
QScrollBar:horizontal {{
    background-color: {COLORS['bg_dark']};
    height: 14px;
    margin: 0;
    border-radius: 7px;
}}
QScrollBar::handle:horizontal {{
    background-color: {COLORS['green_dim']};
    min-width: 40px;
    border-radius: 7px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background-color: {COLORS['green_dark']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0px;
}}
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    background: none;
}}

/* === ОБЛАСТИ ПРОКРУТКИ === */
QScrollArea {{
    border: 2px solid {COLORS['green_dim']};
    border-radius: 8px;
    background-color: {COLORS['bg_card']};
}}

/* === МЕНЮ === */
QMenu {{
    background-color: {COLORS['bg_card']};
    color: {COLORS['text_bright']};
    border: 2px solid {COLORS['green_bright']};
    border-radius: 8px;
    padding: 8px;
}}
QMenu::item {{
    padding: 10px 25px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background-color: {COLORS['bg_active']};
}}

/* === СПИНБОКСЫ === */
QSpinBox {{
    background-color: {COLORS['bg_input']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 6px;
    color: {COLORS['text_bright']};
    padding: 8px;
    font-size: 12px;
}}
QSpinBox:focus {{
    border-color: {COLORS['green_bright']};
}}
QSpinBox::up-button, QSpinBox::down-button {{
    background-color: {COLORS['bg_card']};
    border: none;
    width: 24px;
}}
QSpinBox::up-arrow {{
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-bottom: 6px solid {COLORS['green_bright']};
}}
QSpinBox::down-arrow {{
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {COLORS['green_bright']};
}}

/* === ПРОГРЕСС-БАР === */
QProgressBar {{
    background-color: {COLORS['bg_card']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 8px;
    text-align: center;
    color: {COLORS['text_bright']};
    font-weight: bold;
}}
QProgressBar::chunk {{
    background: qlineargradient(
        x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLORS['green_dark']},
        stop:1 {COLORS['green_bright']}
    );
    border-radius: 6px;
}}

/* === РАЗДЕЛИТЕЛИ === */
QFrame[frameShape="4"] {{
    color: {COLORS['green_dim']};
    max-height: 2px;
}}

/* === ДИАЛОГИ === */
QMessageBox {{
    background-color: {COLORS['bg_dark']};
}}
QMessageBox QLabel {{
    color: {COLORS['text_bright']};
    font-size: 13px;
}}
"""

# Дополнительные стили для статусных кнопок с эмодзи
STATUS_STYLES = {
    'good': """
QPushButton {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #003300, stop:1 #002200
    );
    border-color: #00FF00;
    color: #00FF00;
    font-size: 14px;
}
QPushButton:hover {
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #005500, stop:1 #003300
    );
    border-color: #66FF66;
}
""",
    'bad': f"""
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #330000, stop:1 #220000
    );
    border-color: {COLORS['red']};
    color: {COLORS['red']};
    font-size: 14px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #550000, stop:1 #330000
    );
    border-color: #FF6666;
}}
""",
    'uncertain': f"""
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #333300, stop:1 #222200
    );
    border-color: {COLORS['yellow']};
    color: {COLORS['yellow']};
    font-size: 14px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #555500, stop:1 #333300
    );
    border-color: #FFEE66;
}}
""",
    'duplicate': f"""
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #331A00, stop:1 #221100
    );
    border-color: {COLORS['orange']};
    color: {COLORS['orange']};
    font-size: 14px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #553300, stop:1 #331A00
    );
    border-color: #FFBB44;
}}
""",
    'skip': f"""
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #1A1A1A, stop:1 #111111
    );
    border-color: {COLORS['gray']};
    color: {COLORS['gray']};
    font-size: 14px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #333333, stop:1 #1A1A1A
    );
    border-color: #AAAAAA;
}}
""",
}


# === Базовые темы для Fluent-режима ===
# Красим ЯВНО все используемые поверхности цветами текущей темы — и обычные
# Qt-виджеты, и Fluent-классы (селекторы без Q-префикса: PushButton, ComboBox
# и т.д.; Qt их просто не матчит, если класса нет — безопасно).
# Причина: часть поверхностей Fluent рисует через палитру/по-своему, и без
# явных цветов получается каша (белые кнопки с белым текстом на тёмной теме).
# Пер-виджетные inline-QSS приоритетнее app-level и продолжают работать.
def _fluent_base(bg, bg_card, bg_input, text, text_dim, border, accent, accent_soft, header_bg,
                 sel_bg, sel_text):
    return f"""
QDialog {{
    background-color: {bg};
    color: {text};
}}
QLabel {{
    color: {text};
    background: transparent;
}}
QPushButton, PushButton, PrimaryPushButton {{
    background-color: {bg_card};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 6px 12px;
}}
QPushButton:hover, PushButton:hover, PrimaryPushButton:hover {{
    border-color: {accent};
}}
QPushButton:disabled, PushButton:disabled, PrimaryPushButton:disabled {{
    color: {text_dim};
}}
QPushButton:checked, PushButton:checked {{
    background-color: {accent_soft};
    border-color: {accent};
}}
QCheckBox, CheckBox {{
    background: transparent;
    color: {text};
    spacing: 8px;
}}
QGroupBox {{
    background-color: {bg_card};
    border: 1px solid {border};
    border-radius: {UI_TOKENS['radius_m']}px;
    margin-top: {UI_TOKENS['space_m']}px;
    padding: {UI_TOKENS['space_m']}px 12px 12px 12px;
    font-weight: bold;
    font-size: {UI_TOKENS['font_body']}px;
    color: {text};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 10px;
    padding: 0 4px;
    color: {text};
}}
QTableWidget, TableWidget {{
    background-color: {bg_card};
    alternate-background-color: {bg};
    color: {text};
    gridline-color: {border};
    selection-background-color: {accent_soft};
    selection-color: {text};
    border: 1px solid {border};
    border-radius: {UI_TOKENS['radius_m']}px;
}}
QTableWidget::item, TableWidget::item {{
    padding: 2px 6px;
}}
QTableWidget::indicator, TableWidget::indicator {{
    width: 18px;
    height: 18px;
}}
QTableWidget::indicator:unchecked, TableWidget::indicator:unchecked {{
    border: 1px solid {text_dim};
    border-radius: 4px;
    background-color: transparent;
}}
QTableWidget::indicator:checked, TableWidget::indicator:checked {{
    border: 1px solid {accent};
    border-radius: 4px;
    background-color: {accent};
}}
QTableWidget::indicator:unchecked:hover, TableWidget::indicator:unchecked:hover {{
    border: 1px solid {accent};
}}
QTableWidget::item:hover, TableWidget::item:hover {{
    background-color: {header_bg};
}}
QHeaderView {{
    background-color: {header_bg};
}}
QHeaderView::section {{
    background-color: {header_bg};
    color: {text};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 2px solid {accent};
    padding: 6px 8px;
    font-weight: bold;
    font-size: 12px;
}}
/* Квадрат-заглушка в углу таблицы (между номерами строк и заголовками):
   без этого в тёмной теме там белое пятно. */
QTableCornerButton::section {{
    background-color: {header_bg};
    border: none;
    border-right: 1px solid {border};
    border-bottom: 1px solid {border};
}}
QListWidget, ListWidget {{
    background-color: {bg_card};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
}}
QListWidget::item:selected, ListWidget::item:selected {{
    background-color: {accent_soft};
    color: {text};
}}
QLineEdit, QTextEdit, QPlainTextEdit, LineEdit, TextEdit {{
    background-color: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {sel_bg};
    selection-color: {sel_text};
}}
QSpinBox, SpinBox, QComboBox, ComboBox, QDateEdit, QTimeEdit, QDateTimeEdit {{
    background-color: {bg_input};
    color: {text};
    border: 1px solid {border};
    border-radius: 6px;
    padding: 4px 8px;
    selection-background-color: {sel_bg};
    selection-color: {sel_text};
}}
QComboBox QAbstractItemView, ComboBox QAbstractItemView {{
    background-color: {bg_card};
    color: {text};
    selection-background-color: {accent_soft};
}}
QScrollArea {{
    background: transparent;
}}
QTabWidget::pane {{
    border: 1px solid {border};
    border-radius: 6px;
    background-color: {bg};
}}
QTabBar::tab {{
    background-color: {bg_card};
    color: {text_dim};
    border: 1px solid {border};
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
}}
QTabBar::tab:selected {{
    color: {text};
    border-color: {accent};
    background-color: {bg};
}}
QToolTip {{
    background-color: {bg_card};
    color: {text};
    border: 1px solid {border};
}}
QMenu {{
    background-color: {bg_card};
    color: {text};
    border: 1px solid {border};
}}
QMenu::item:selected {{
    background-color: {accent_soft};
}}
QProgressBar {{
    background-color: {bg_card};
    border: 1px solid {border};
    border-radius: 4px;
    text-align: center;
    color: {text};
}}
QProgressBar::chunk {{
    background-color: {accent};
    border-radius: 3px;
}}
"""

FLUENT_BASE_LIGHT = _fluent_base(**FLUENT_LIGHT)

FLUENT_BASE_DARK = _fluent_base(**FLUENT_DARK)
