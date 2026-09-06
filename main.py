import sys
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QStackedWidget, QFileDialog, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from pathlib import Path
from database import init_database
from sidebar import Sidebar
from styles import APP_STYLE


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

        title = QLabel("LOCAL REVIEWER")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Локальная разметка датасетов")
        subtitle.setObjectName("subtitle")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        layout.addSpacing(30)

        btn_create = QPushButton("📁 Создать проект")
        btn_create.setMinimumWidth(280)
        btn_create.setMinimumHeight(50)
        btn_create.clicked.connect(self.on_create_project)

        btn_open = QPushButton("📂 Открыть проект")
        btn_open.setMinimumWidth(280)
        btn_open.setMinimumHeight(50)
        btn_open.clicked.connect(self.on_open_project)

        btn_exit = QPushButton("🚪 Выход")
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
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось создать проект:\n{str(e)}")

    def on_open_project(self):
        folder = QFileDialog.getExistingDirectory(
            self, "Выберите папку существующего проекта", "")
        if folder:
            db_path = Path(folder) / "project.sqlite"
            if not db_path.exists():
                QMessageBox.warning(self, "Проект не найден",
                    f"В папке {folder} не найдена база данных.")
                return
            self.main_window.open_project(folder)

    def on_exit(self):
        QApplication.quit()


class ProjectWindow(QWidget):
    """Окно проекта: сайдбар + стек экранов."""

    def __init__(self, project_path: str, main_window):
        super().__init__()
        self.project_path = project_path
        self.main_window = main_window
        self.screens = {}
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Сайдбар
        self.sidebar = Sidebar(self.project_path)
        self.sidebar.nav_changed.connect(self.on_nav)
        layout.addWidget(self.sidebar)

        # Стек экранов
        self.stack = QStackedWidget()

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

        for screen in self.screens.values():
            self.stack.addWidget(screen)

        self.stack.setCurrentWidget(self.screens['project'])
        self.sidebar.set_active('project')

        layout.addWidget(self.stack)
        self.setLayout(layout)

    def on_nav(self, key):
        if key == "home":
            self.main_window.go_home()
            return
        if key in self.screens:
            self.stack.setCurrentWidget(self.screens[key])
            # Обновляем данные экрана при переключении
            screen = self.screens[key]
            if hasattr(screen, 'refresh'):
                screen.refresh()

    def refresh_all(self):
        """Обновляет все экраны."""
        self.sidebar.update_progress()
        for screen in self.screens.values():
            if hasattr(screen, 'refresh'):
                screen.refresh()


class MainWindow(QMainWindow):
    """Главное окно приложения."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local Reviewer")
        self.setMinimumSize(1000, 700)
        self.resize(1280, 800)

        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        self.start_screen = StartScreen(self)
        self.stack.addWidget(self.start_screen)
        self.stack.setCurrentWidget(self.start_screen)

        self.project_window = None

    def open_project(self, folder):
        """Открывает проект."""
        self.project_window = ProjectWindow(folder, self)
        self.stack.addWidget(self.project_window)
        self.stack.setCurrentWidget(self.project_window)

    def go_home(self):
        """Возврат на стартовый экран."""
        if self.project_window:
            self.stack.removeWidget(self.project_window)
            self.project_window.deleteLater()
            self.project_window = None
        self.stack.setCurrentWidget(self.start_screen)


def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(APP_STYLE)
    font = QFont("Cascadia Code", 10)
    font.setStyleHint(QFont.StyleHint.Monospace)
    app.setFont(font)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()