"""
Продвинутая чёрно-зелёная тема для Local Reviewer.
Версия 3: боковая панель, компактные кнопки.
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
    'green_main': '#00DD38',
    'green_dark': '#00AA2A',
    'green_dim': '#007722',
    'red': '#FF3B3B',
    'red_dark': '#CC2222',
    'yellow': '#FFD700',
    'orange': '#FF9900',
    'blue': '#00AAFF',
    'gray': '#888888',
    'border': '#00FF41',
    'border_dim': '#00441A',
}

def apply_shadow(widget, color='#00FF41', blur=25, offset=4, alpha=50):
    """Добавляет тень к виджету."""
    shadow = QGraphicsDropShadowEffect()
    shadow.setBlurRadius(blur)
    r = int(color[1:3], 16)
    g = int(color[3:5], 16)
    b = int(color[5:7], 16)
    shadow.setColor(QColor(r, g, b, alpha))
    shadow.setOffset(0, offset)
    widget.setGraphicsEffect(shadow)
    return shadow

# Глобальный стиль приложения
APP_STYLE = f"""
/* === ОБЩИЕ НАСТРОЙКИ === */
QMainWindow {{
    background-color: {COLORS['bg_dark']};
}}
QWidget {{
    background-color: {COLORS['bg_dark']};
    color: {COLORS['green_bright']};
    font-family: 'Cascadia Code', 'Consolas', 'Courier New', monospace;
    font-size: 13px;
}}

/* === ЗАГОЛОВКИ === */
QLabel {{
    color: {COLORS['green_bright']};
    font-size: 13px;
    background: transparent;
}}
QLabel#title {{
    font-size: 32px;
    font-weight: 900;
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
    border: 2px solid {COLORS['green_dark']};
    border-radius: 8px;
    padding: 10px 20px;
    font-size: 13px;
    font-weight: bold;
    min-width: 100px;
    min-height: 35px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 {COLORS['bg_active']},
        stop:1 {COLORS['bg_hover']}
    );
    border-color: {COLORS['green_bright']};
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
    left: 15px;
    font-size: 13px;
}}

/* === ПОЛЯ ВВОДА === */
QLineEdit, QTextEdit, QPlainTextEdit {{
    background-color: {COLORS['bg_input']};
    border: 2px solid {COLORS['green_dim']};
    border-radius: 6px;
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
    selection-background-color: {COLORS['bg_active']};
}}

/* === ЧЕКБОКСЫ === */
QCheckBox {{
    spacing: 10px;
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
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
    color: {COLORS['green_bright']};
    font-size: 13px;
}}
"""

# Дополнительные стили для статусных кнопок с эмодзи
STATUS_STYLES = {
    'good': f"""
QPushButton {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #003300, stop:1 #002200
    );
    border-color: #00FF00;
    color: #00FF00;
    font-size: 14px;
}}
QPushButton:hover {{
    background: qlineargradient(
        x1:0, y1:0, x2:0, y2:1,
        stop:0 #005500, stop:1 #003300
    );
    border-color: #66FF66;
}}
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