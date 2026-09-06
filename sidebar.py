from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QPushButton, QLabel,
    QSizePolicy, QProgressBar, QSpacerItem
)
from PySide6.QtCore import Qt, Signal
from database import get_db_connection


class Sidebar(QWidget):
    """Боковая панель навигации."""
    nav_changed = Signal(str)  # Сигнал смены экрана

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.collapsed = False
        self.buttons = {}
        self.init_ui()
        self.update_progress()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setSpacing(4)
        self.layout.setContentsMargins(8, 12, 8, 12)
        self.setFixedWidth(200)
        self.setStyleSheet("background-color: #0A0F0A; border-right: 1px solid #00441A;")

        # Логотип
        self.logo = QLabel("LOCAL\nREVIEWER")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.logo.setStyleSheet("""
            color: #00FF41;
            font-size: 14px;
            font-weight: 900;
            letter-spacing: 2px;
            padding: 8px 0px;
        """)
        self.layout.addWidget(self.logo)

        # Разделитель
        line = self._make_line()
        self.layout.addWidget(line)
        self.layout.addSpacing(8)

        # Кнопки навигации
        nav_items = [
            ("project",   "📁 Проект"),
            ("review",    "🔍 Ревью"),
            ("reports",   "📈 Отчёты"),
            ("history",   "🕐 История"),
            ("backup",    "💾 Бэкапы"),
            ("settings",  "⚙️ Настройки"),
        ]

        for key, label in nav_items:
            btn = QPushButton(label)
            btn.setMinimumHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setStyleSheet(self._nav_style(False))
            btn.clicked.connect(lambda checked, k=key: self._on_nav(k))
            self.layout.addWidget(btn)
            self.buttons[key] = btn

        self.layout.addStretch()

        # Прогресс проекта
        self.progress_label = QLabel("Прогресс: 0%")
        self.progress_label.setStyleSheet("color: #00AA2A; font-size: 11px; padding: 4px;")
        self.layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(12)
        self.progress_bar.setStyleSheet("""
            QProgressBar {
                background-color: #0D150D;
                border: 1px solid #00441A;
                border-radius: 6px;
                text-align: center;
                color: transparent;
            }
            QProgressBar::chunk {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #00AA2A, stop:1 #00FF41
                );
                border-radius: 5px;
            }
        """)
        self.layout.addWidget(self.progress_bar)

        self.layout.addSpacing(8)

        # Кнопка на главную
        self.btn_home = QPushButton("🏠 На главную")
        self.btn_home.setMinimumHeight(36)
        self.btn_home.setStyleSheet("""
            QPushButton {
                background-color: transparent;
                color: #FF6666;
                border: 1px solid #662222;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
            }
            QPushButton:hover { background-color: #330000; }
        """)
        self.btn_home.clicked.connect(self._on_home)
        self.layout.addWidget(self.btn_home)

        self.setLayout(self.layout)

    def _make_line(self):
        line = QLabel()
        line.setFixedHeight(1)
        line.setStyleSheet("background-color: #00441A;")
        return line

    def _nav_style(self, active=False):
        if active:
            return """
                QPushButton {
                    background-color: #1A3A1A;
                    color: #00FF41;
                    border: 1px solid #00FF41;
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: bold;
                    text-align: left;
                }
            """
        return """
            QPushButton {
                background-color: transparent;
                color: #00DD38;
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                text-align: left;
            }
            QPushButton:hover {
                background-color: #0F2010;
                border-color: #007722;
            }
        """

    def _on_nav(self, key):
        self.set_active(key)
        self.nav_changed.emit(key)

    def _on_home(self):
        self.nav_changed.emit("home")

    def set_active(self, key):
        for k, btn in self.buttons.items():
            btn.setStyleSheet(self._nav_style(k == key))

    def update_progress(self):
        """Обновляет прогресс-бар проекта."""
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) as total FROM cases")
            total = cursor.fetchone()['total']
            cursor.execute("""
                SELECT COUNT(*) as reviewed FROM annotations
                WHERE status != 'unreviewed'
            """)
            reviewed = cursor.fetchone()['reviewed']
            conn.close()
            pct = int(reviewed / total * 100) if total > 0 else 0
            self.progress_bar.setValue(pct)
            self.progress_label.setText(f"Проверено: {reviewed}/{total} ({pct}%)")
        except Exception:
            self.progress_bar.setValue(0)
            self.progress_label.setText("Нет данных")