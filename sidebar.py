from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QProgressBar
)
from PySide6.QtCore import Qt, Signal
from database import db
from ui_compat import FLUENT, FPushButton


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
        from styles import COLORS as _CC
        if not FLUENT:
            self.setStyleSheet(
                f"background-color: {_CC['bg_panel']}; "
                f"border-right: 1px solid {_CC['border_dim']};")

        # Логотип
        self.logo = QLabel("LOCAL\nREVIEWER")
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if not FLUENT:
            self.logo.setStyleSheet(f"""
                color: {_CC['text_bright']};
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
            ("runs",      "🏃 Прогоны"),
            ("bugs",      "🐞 Баги"),
            ("launches",  "🚀 Запуски"),
            ("reports",   "📈 Отчёты"),
            ("history",   "🕐 История"),
            ("backup",    "💾 Бэкапы"),
            ("settings",  "⚙️ Настройки"),
        ]

        for key, label in nav_items:
            btn = FPushButton(label)
            btn.setMinimumHeight(36)
            btn.setCursor(Qt.PointingHandCursor)
            if FLUENT:
                btn.setCheckable(True)
            else:
                btn.setStyleSheet(self._nav_style(False))
            btn.clicked.connect(lambda checked, k=key: self._on_nav(k))
            self.layout.addWidget(btn)
            self.buttons[key] = btn

        self.layout.addStretch()

        # Прогресс проекта
        self.progress_label = QLabel("Прогресс: 0%")
        if not FLUENT:
            self.progress_label.setStyleSheet(
                f"color: {_CC['green_dark']}; font-size: 11px; padding: 4px;")
        self.layout.addWidget(self.progress_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setMaximumHeight(12)
        if not FLUENT:
            self.progress_bar.setStyleSheet(f"""
                QProgressBar {{
                    background-color: {_CC['bg_card']};
                    border: 1px solid {_CC['border_dim']};
                    border-radius: 6px;
                    text-align: center;
                    color: transparent;
                }}
                QProgressBar::chunk {{
                    background: qlineargradient(
                        x1:0, y1:0, x2:1, y2:0,
                        stop:0 {_CC['green_dark']}, stop:1 {_CC['green_bright']}
                    );
                    border-radius: 5px;
                }}
            """)
        self.layout.addWidget(self.progress_bar)

        self.layout.addSpacing(8)

        # Кнопка на главную
        self.btn_home = FPushButton("🏠 На главную")
        self.btn_home.setMinimumHeight(36)
        if not FLUENT:
            from styles import COLORS as _CC
            self.btn_home.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    color: {_CC['red_light']};
                    border: 1px solid {_CC['red_border']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 12px;
                }}
                QPushButton:hover {{ background-color: {_CC['danger_hover']}; }}
            """)
        self.btn_home.clicked.connect(self._on_home)
        self.layout.addWidget(self.btn_home)

        self.setLayout(self.layout)

    def _make_line(self):
        line = QLabel()
        line.setFixedHeight(1)
        if not FLUENT:
            from styles import COLORS as _CC2
            line.setStyleSheet(f"background-color: {_CC2['border_dim']};")
        return line

    def _nav_style(self, active=False):
        from styles import COLORS as _CC3
        if active:
            return f"""
                QPushButton {{
                    background-color: {_CC3['bg_active']};
                    color: {_CC3['text_bright']};
                    border: 1px solid {_CC3['green_bright']};
                    border-radius: 6px;
                    padding: 6px 12px;
                    font-size: 12px;
                    font-weight: bold;
                    text-align: left;
                }}
            """
        return f"""
            QPushButton {{
                background-color: transparent;
                color: {_CC3['green_main']};
                border: 1px solid transparent;
                border-radius: 6px;
                padding: 6px 12px;
                font-size: 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                background-color: {_CC3['bg_hover']};
                border-color: {_CC3['green_dim']};
            }}
        """

    def _on_nav(self, key):
        self.set_active(key)
        self.nav_changed.emit(key)

    def _on_home(self):
        self.nav_changed.emit("home")

    def set_active(self, key):
        for k, btn in self.buttons.items():
            if FLUENT:
                btn.setChecked(k == key)
            else:
                btn.setStyleSheet(self._nav_style(k == key))

    def update_progress(self):
        """Обновляет прогресс-бар проекта (проверено = base != unreviewed)."""
        try:
            try:
                from review_profile_service import code_to_base
                mapping = code_to_base(self.project_path)
                unrev = ["unreviewed"] + [
                    c for c, b in mapping.items()
                    if b == "unreviewed" and c != "unreviewed"]
            except Exception:
                unrev = ["unreviewed"]
            ph = ",".join(["?"] * len(unrev))
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as total FROM cases c "
                               "JOIN files f ON f.file_id = c.file_id")
                total = cursor.fetchone()['total']
                cursor.execute(f"""
                    SELECT COUNT(*) as reviewed FROM annotations a
                    JOIN cases c ON c.case_id = a.case_id
                    JOIN files f ON f.file_id = c.file_id
                    WHERE COALESCE(a.status, 'unreviewed') NOT IN ({ph})
                """, unrev)
                reviewed = cursor.fetchone()['reviewed']
            pct = int(reviewed / total * 100) if total > 0 else 0
            self.progress_bar.setValue(pct)
            self.progress_label.setText(f"Проверено: {reviewed}/{total} ({pct}%)")
        except Exception:
            self.progress_bar.setValue(0)
            self.progress_label.setText("Нет данных")

    def refresh(self):
        self.update_progress()
