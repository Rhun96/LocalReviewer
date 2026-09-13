import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QStackedWidget, QFileDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from pathlib import Path
from database import init_database
from styles import APP_STYLE
from ui_compat import (
    FLUENT, FPrimaryButton, FPushButton, FSubtitleLabel, FTitleLabel,
    apply_theme, confirm, get_theme_mode, notify,
)


class StartScreen(QWidget):
    """Стартовый экран (без сайдбара)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.main_window = parent
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(20)

        title = FTitleLabel("LOCAL REVIEWER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = FSubtitleLabel("Локальная разметка датасетов")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(30)

        btn_create = FPrimaryButton("📁 Создать проект")
        btn_create.setMinimumWidth(280)
        btn_create.setMinimumHeight(50)
        btn_create.clicked.connect(self.on_create_project)

        btn_open = FPushButton("📂 Открыть проект")
        btn_open.setMinimumWidth(280)
        btn_open.setMinimumHeight(50)
        btn_open.clicked.connect(self.on_open_project)

        btn_exit = FPushButton("🚪 Выход")
        if not FLUENT:
            btn_exit.setObjectName("danger")
        btn_exit.setMinimumWidth(280)
        btn_exit.setMinimumHeight(50)
        btn_exit.clicked.connect(self.on_exit)

        layout.addWidget(btn_create, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(btn_open, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(btn_exit, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)

    def on_create_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку для нового проекта", "")
        if folder:
            try:
                init_database(folder)
                self.main_window.open_project(folder)
                notify(self.main_window, "success", "Проект создан",
                       f"База инициализирована:\n{folder}")
            except Exception as e:
                notify(self, "error", "Ошибка", f"Не удалось создать проект:\n{str(e)}")

    def on_open_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку существующего проекта", "")
        if folder:
            db_path = Path(folder) / "project.sqlite"
            if not db_path.exists():
                notify(self, "warning", "Проект не найден", f"В папке {folder} не найдена база данных.")
                return
            self.main_window.open_project(folder)

    def on_exit(self):
        QApplication.quit()


class ProjectWindow(QWidget):
    """Проект: владеет экранами и общей логикой.

    Во Fluent-режиме навигация — нативная (FluentWindow), этот виджет остаётся
    скрытым владельцем экранов. В классическом режиме — сайдбар + свой стек.
    """

    def __init__(self, project_path: str, main_window):
        super().__init__()
        self.project_path = project_path
        self.main_window = main_window
        self.screens = {}
        self._stack = None
        self.sidebar = None
        self.init_ui()

    @property
    def stack(self):
        # Экраны обращаются к parent_window.stack (транзитные виджеты и т.п.)
        if FLUENT:
            return self.main_window.stackedWidget
        return self._stack

    def init_ui(self):
        # Создаём все экраны
        from project_screen import ProjectScreen
        from review_screen import ReviewScreen
        from reports_screen import ReportsScreen
        from history_screen import HistoryScreen
        from backup_screen import BackupScreen
        from settings_screen import SettingsScreen

        self.screens['project'] = ProjectScreen(self.project_path, self)
        self.screens['review'] = ReviewScreen(self.project_path, self, filters=None)
        self.screens['reports'] = ReportsScreen(self.project_path, self)
        self.screens['history'] = HistoryScreen(self.project_path, self)
        self.screens['backup'] = BackupScreen(self.project_path, self)
        self.screens['settings'] = SettingsScreen(self.project_path, self)

        if FLUENT:
            return

        from sidebar import Sidebar
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Сайдбар
        self.sidebar = Sidebar(self.project_path)
        self.sidebar.nav_changed.connect(self.on_nav)
        layout.addWidget(self.sidebar)

        # Стек экранов
        self._stack = QStackedWidget()
        for screen in self.screens.values():
            self._stack.addWidget(screen)

        self._stack.setCurrentWidget(self.screens['project'])
        self.sidebar.set_active('project')

        layout.addWidget(self._stack)
        self.setLayout(layout)

    def on_nav(self, key):
        if key == "home":
            self.main_window.go_home()
            return
        if key in self.screens:
            self.stack.setCurrentWidget(self.screens[key])
            # Обновляем данные экрана при переключении
            screen = self.screens[key]
            refresh = getattr(screen, 'refresh', None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass
            if self.sidebar is not None:
                self.sidebar.update_progress()

    def refresh_all(self):
        """Обновляет все экраны."""
        if self.sidebar is not None:
            self.sidebar.update_progress()
        for screen in self.screens.values():
            refresh = getattr(screen, 'refresh', None)
            if callable(refresh):
                try:
                    refresh()
                except Exception:
                    pass

    def go_home(self):
        """Возврат на стартовый экран (для цепочки parent_window из экранов)."""
        self.main_window.go_home()


if FLUENT:
    from qfluentwidgets import FluentWindow as _BaseWindow
else:
    _BaseWindow = QMainWindow


class MainWindow(_BaseWindow):
    """Главное окно приложения (классика + Fluent-навигация)."""

    NAV_ITEMS = [
        ("project", "FOLDER", "Проект"),
        ("review", "SEARCH", "Ревью"),
        ("reports", "DOCUMENT", "Отчёты"),
        ("history", "HISTORY", "История"),
        ("backup", "SAVE", "Бэкапы"),
        ("settings", "SETTING", "Настройки"),
    ]

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local Reviewer")
        self.setMinimumSize(1000, 700)
        self.resize(1280, 800)

        if FLUENT:
            from qfluentwidgets import FluentIcon as FIF
            self._FIF = FIF
            # Нативный стек FluentWindow — алиас для совместимости экранов
            self.stack = self.stackedWidget
            self.start_screen = StartScreen(self)
            self.start_screen.setObjectName("start")
            self.addSubInterface(self.start_screen, FIF.HOME, "Главная")
            self.stackedWidget.currentChanged.connect(self._on_page_changed)
        else:
            self.stack = QStackedWidget()
            self.setCentralWidget(self.stack)
            self.start_screen = StartScreen(self)
            self.stack.addWidget(self.start_screen)
            self.stack.setCurrentWidget(self.start_screen)

        self.project_window = None

    def _nav_icon(self, name: str):
        return getattr(self._FIF, name)

    def open_project(self, folder):
        """Открывает проект (старый выгружается, чтобы не было утечек)."""
        try:
            # Миграции должны выполняться и при ОТКРЫТИИ, а не только при создании:
            # иначе старые проекты не получат новые таблицы (bulk_operations, saved_filters...).
            init_database(folder)
        except Exception as e:
            notify(self, "error", "Ошибка",
                   "Не удалось мигрировать базу проекта.\n\n"
                   f"Причина: {e}\n\n"
                   "Ваши данные НЕ изменены (миграция откачена).\n"
                   "Перед миграцией создан бэкап в папке backups/.\n"
                   "Подробности — в logs/localreviewer.log.")
            return
        self._close_project()
        self.project_window = ProjectWindow(folder, self)
        if FLUENT:
            for key, icon_name, text in self.NAV_ITEMS:
                screen = self.project_window.screens[key]
                screen.setObjectName(f"screen_{key}")
                self.addSubInterface(screen, self._nav_icon(icon_name), text)
            self.switchTo(self.project_window.screens["project"])
        else:
            self.stack.addWidget(self.project_window)
            self.stack.setCurrentWidget(self.project_window)

    def _close_project(self):
        if not self.project_window:
            return
        if FLUENT:
            for key, _icon_name, _text in self.NAV_ITEMS:
                screen = self.project_window.screens.get(key)
                if screen is None:
                    continue
                try:
                    self.navigationInterface.removeWidget(f"screen_{key}")
                except Exception:
                    pass
                self.stackedWidget.removeWidget(screen)
                screen.deleteLater()
        else:
            self.stack.removeWidget(self.project_window)
            self.project_window.deleteLater()
        self.project_window = None

    def go_home(self):
        """Возврат на стартовый экран."""
        self._close_project()
        if FLUENT:
            self.switchTo(self.start_screen)
        else:
            self.stack.setCurrentWidget(self.start_screen)

    def show_screen(self, key, filters=None):
        """Показать экран проекта; для ревью можно передать фильтры.

        Единая точка навигации: подсветка в меню всегда соответствует контенту.
        """
        pw = self.project_window
        if not pw or key not in pw.screens:
            return
        screen = pw.screens[key]
        if filters is not None and hasattr(screen, "filters"):
            screen.filters = filters
        if hasattr(screen, "current_page"):
            screen.current_page = 0
        if hasattr(screen, "current_index"):
            screen.current_index = 0
        if hasattr(screen, "bulk_selected"):
            try:
                screen.bulk_selected.clear()
            except Exception:
                pass
        if hasattr(screen, "load_case_ids"):
            try:
                screen.load_case_ids()
            except Exception:
                pass
        if FLUENT:
            if self.stackedWidget.currentWidget() is not screen:
                self.switchTo(screen)
            else:
                self._refresh_widget(screen)
        else:
            pw.stack.setCurrentWidget(screen)
            self._refresh_widget(screen)

    def _refresh_widget(self, widget):
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _on_page_changed(self, _index: int):
        self._refresh_widget(self.stackedWidget.currentWidget())


def main():
    from app_logging import setup_logging
    setup_logging()
    app = QApplication(sys.argv)
    if FLUENT:
        # Fluent рисует сам: глобальный APP_STYLE его бы ломал
        apply_theme(get_theme_mode())
    else:
        app.setStyle("Fusion")
        app.setStyleSheet(APP_STYLE)
    for family in ("Cascadia Code", "Consolas", "Courier New"):
        font = QFont(family, 10)
        if font.exactMatch() or family != "Cascadia Code":
            font.setStyleHint(QFont.StyleHint.Monospace)
            app.setFont(font)
            break
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()