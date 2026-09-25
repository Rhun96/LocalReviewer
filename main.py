import logging
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
    apply_theme, get_theme_mode, notify,
)

logger = logging.getLogger(__name__)


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

        # V2.1 P0 §18: последние проекты (не искать папку каждый раз).
        from PySide6.QtWidgets import QLabel as _QL
        self.recent_label = _QL("")
        self.recent_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_label.setWordWrap(True)
        layout.addWidget(self.recent_label)
        self.recent_box = QWidget()
        self.recent_layout = QVBoxLayout()
        self.recent_layout.setSpacing(6)
        self.recent_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.recent_box.setLayout(self.recent_layout)
        layout.addWidget(self.recent_box, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setLayout(layout)
        self.refresh_recent()

    def refresh_recent(self):
        try:
            from session_service import get_recent_projects
            items = get_recent_projects()
        except Exception:
            items = []
        # чистим старые кнопки
        while self.recent_layout.count():
            it = self.recent_layout.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        if not items:
            self.recent_label.setText("")
            return
        self.recent_label.setText("Недавние проекты:")
        for it in items[:5]:
            path, ok = it["path"], it["available"]
            name = Path(path).name or path
            btn = FPushButton(f"{name}" + ("" if ok else " (папка недоступна)"))
            btn.setMinimumWidth(280)
            btn.setToolTip(path)
            btn.setEnabled(ok)
            btn.clicked.connect(lambda _c, p=path: self._open_recent(p))
            self.recent_layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _open_recent(self, path):
        from pathlib import Path as _P
        if not (_P(path) / "project.sqlite").exists():
            notify(self, "warning", "Папка недоступна",
                   f"В папке нет базы:\n{path}\nЗапись оставлена в списке.")
            self.refresh_recent()
            return
        self.main_window.open_project(path)

    def showEvent(self, event):
        try:
            self.refresh_recent()
        except Exception:
            pass
        super().showEvent(event)

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
                notify(self, "warning", "Проект не найден",
                       f"В папке {folder} не найдена база данных.")
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
        from runs_screen import ModelRunsScreen
        from bug_reports_screen import BugReportsScreen
        from launches_screen import LaunchesScreen
        from datasets_screen import DatasetsScreen
        from reports_screen import ReportsScreen
        from history_screen import HistoryScreen
        from backup_screen import BackupScreen
        from settings_screen import SettingsScreen

        self.screens['project'] = ProjectScreen(self.project_path, self)
        self.screens['review'] = ReviewScreen(self.project_path, self, filters=None)
        self.screens['runs'] = ModelRunsScreen(self.project_path, self)
        self.screens['bugs'] = BugReportsScreen(self.project_path, self)
        self.screens['launches'] = LaunchesScreen(self.project_path, self)
        self.screens['datasets'] = DatasetsScreen(self.project_path, self)
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
        ("runs", "SYNC", "Прогоны"),
        ("bugs", "FLAG", "Баги"),
        ("launches", "SEND", "Запуски"),
        ("datasets", "LIBRARY", "Датасеты"),
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
        self.current_project_path = None

    def _nav_icon(self, name: str):
        return getattr(self._FIF, name)

    def open_project(self, folder):
        """Открывает проект (старый выгружается, чтобы не было утечек)."""
        try:
            # Логи — в папку проекта (ТЗ: logs/ проекта, а не CWD exe).
            try:
                from app_logging import setup_logging as _setup
                _setup(project_path=folder)
            except Exception:
                pass
            # Миграции должны выполняться и при ОТКРЫТИИ, а не только при создании:
            # иначе старые проекты не получат новые таблицы (bulk_operations, saved_filters...).
            # Замер: 10k кейсов открываются за ~0с; курсор-часы — страховка
            # на случай тяжёлой дедупликации очень грязных БД.
            from PySide6.QtWidgets import QApplication as _QA
            try:
                _QA.setOverrideCursor(Qt.CursorShape.WaitCursor)
            except Exception:
                pass
            try:
                init_database(folder)
            finally:
                try:
                    _QA.restoreOverrideCursor()
                except Exception:
                    pass
        except Exception as e:
            notify(self, "error", "Ошибка",
                   "Не удалось мигрировать базу проекта.\n\n"
                   f"Причина: {e}\n\n"
                   "Ваши данные НЕ изменены (миграция откачена).\n"
                   "Перед миграцией создан бэкап в папке backups/.\n"
                   "Подробности — в logs/localreviewer.log.")
            return
        self._save_session(silent=True)
        self._close_project()
        self.project_window = ProjectWindow(folder, self)
        self.current_project_path = str(folder)
        try:
            from session_service import add_recent_project
            add_recent_project(str(folder))
        except Exception:
            pass
        try:
            from saved_filter_service import ensure_preset_views
            ensure_preset_views(str(folder))
        except Exception:
            pass
        if FLUENT:
            for key, icon_name, text in self.NAV_ITEMS:
                screen = self.project_window.screens[key]
                screen.setObjectName(f"screen_{key}")
                self.addSubInterface(screen, self._nav_icon(icon_name), text)
            self.switchTo(self.project_window.screens["project"])
        else:
            self.stack.addWidget(self.project_window)
            self.stack.setCurrentWidget(self.project_window)
        self._restore_session()

    def _close_project(self):
        if not self.project_window:
            self.current_project_path = None
            return
        try:
            self._save_session(silent=True)
        except Exception:
            pass
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
        self.current_project_path = None

    def go_home(self):
        """Возврат на стартовый экран."""
        self._close_project()
        if FLUENT:
            self.switchTo(self.start_screen)
        else:
            self.stack.setCurrentWidget(self.start_screen)

    def show_screen(self, key, filters=None, fresh=True):
        """Показать экран проекта; для ревью можно передать фильтры.

        Единая точка навигации: подсветка в меню всегда соответствует контенту.
        Строгий режим «Плохо» блокирует уход с недозаполненного кейса.
        fresh=False — без сброса вида (для восстановления сессии: состояние
        накатит restore_session одним проходом вместо тройной загрузки).
        """
        pw = self.project_window
        if not pw or key not in pw.screens:
            return
        # Не даём тихо сбросить pending переходом через меню/назад.
        try:
            cur = None
            if FLUENT:
                cur = self.stackedWidget.currentWidget()
            else:
                cur = pw.stack.currentWidget()
            if cur is not None and cur is not pw.screens.get(key):
                can_leave = getattr(cur, "_bad_can_leave", None)
                if callable(can_leave) and not can_leave():
                    # Подсветка меню останется на текущем экране после возврата.
                    try:
                        if FLUENT:
                            self.switchTo(cur)
                    except Exception:
                        pass
                    return
        except Exception:
            pass
        screen = pw.screens[key]
        if filters is not None and hasattr(screen, "filters"):
            screen.filters = filters
        if fresh:
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
        # Экраны только что построены со свежими данными; при restore
        # (fresh=False) повторный refresh — лишняя загрузка, пропускаем
        # (включая refresh из currentChanged-сигнала).
        if not fresh:
            self._skip_refresh_once = True
        if FLUENT:
            if self.stackedWidget.currentWidget() is not screen:
                self.switchTo(screen)
                if fresh:
                    self._refresh_widget(screen)
            elif fresh:
                self._refresh_widget(screen)
        else:
            pw.stack.setCurrentWidget(screen)
            if fresh:
                self._refresh_widget(screen)

    def _refresh_widget(self, widget):
        refresh = getattr(widget, "refresh", None)
        if callable(refresh):
            try:
                refresh()
            except Exception:
                pass

    def _save_session(self, silent=True):
        """V2.1 P0 §5: снапшот рабочего места (черновик + sess_*-ключи)."""
        try:
            pw = self.project_window
            if pw is None or not self.current_project_path:
                return
            from session_service import is_restore_enabled, save_project_session
            if not is_restore_enabled():
                return
            rev = pw.screens.get("review")
            if rev is not None and getattr(rev, "current_case_id", None):
                try:
                    rev.save_comment(silent=True)
                except Exception:
                    pass
                try:
                    save_project_session(self.current_project_path,
                                         rev.snapshot_session())
                except Exception:
                    pass
            # активный экран запоминаем отдельно (review уже внутри snapshot)
            try:
                cur = None
                if FLUENT:
                    cur = self.stackedWidget.currentWidget()
                else:
                    cur = pw.stack.currentWidget()
                for key, scr in pw.screens.items():
                    if scr is cur and key != "review":
                        save_project_session(self.current_project_path,
                                             {"screen": key})
                        break
            except Exception:
                pass
        except Exception:
            if not silent:
                raise

    def _restore_session(self):
        """Восстановить последнее место одним проходом; битое — молча пропуск."""
        try:
            from session_service import is_restore_enabled, load_project_session
            if not is_restore_enabled():
                return
            pw = self.project_window
            if pw is None or not self.current_project_path:
                return
            state = load_project_session(self.current_project_path)
            if not state:
                return
            screen = state.get("screen", "project")
            if screen not in pw.screens or screen == "project":
                return
            try:
                if screen == "review":
                    # fresh=False: без сброса и предзагрузки, restore сам
                    # один раз загрузит очередь + кейс + таблицу.
                    self.show_screen(screen, fresh=False)
                    pw.screens["review"].restore_session(state)
                else:
                    self.show_screen(screen)
            except Exception:
                pass
        except Exception:
            pass

    def closeEvent(self, event):
        """При закрытии: черновик + снапшот сессии (данные не трогаем)."""
        try:
            self._save_session(silent=True)
        except Exception:
            pass
        super().closeEvent(event)

    def _on_page_changed(self, _index: int):
        if getattr(self, "_skip_refresh_once", False):
            self._skip_refresh_once = False
            return
        self._refresh_widget(self.stackedWidget.currentWidget())


def main():
    from app_logging import setup_logging
    setup_logging()
    try:
        import qfluentwidgets as _qw
        _qw_ver = getattr(_qw, "__version__", "?")
    except Exception:
        _qw_ver = None
    # Режим в лог при каждом старте: иначе «почему не тот вид» гадается.
    logger.info("startup: FLUENT=%s qfluentwidgets=%s", FLUENT, _qw_ver)
    app = QApplication(sys.argv)
    try:
        # V2.2 §3: монитор буфера (любая копия из программы взводит таймер).
        from clipboard_service import install_monitor as _mon
        _mon()
    except Exception:
        pass
    try:
        # V2.2 §13: Ctrl+P фильтром приложения (обход мёртвого QShortcutMap).
        from app_shortcuts import install_global_keys as _keys
        _keys(app)
    except Exception:
        pass
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
    # V2.1 P0 §5.3: быстрый возврат туда, где остановился. Отложенно —
    # окно сначала отрисовывается, тяжёлое открытие не держит старт.
    try:
        from PySide6.QtCore import QTimer as _QT

        def _auto_open():
            try:
                from session_service import get_last_project, is_restore_enabled
                if is_restore_enabled():
                    last = get_last_project()
                    if last:
                        window.open_project(last)
            except Exception:
                pass
        _QT.singleShot(0, _auto_open)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
