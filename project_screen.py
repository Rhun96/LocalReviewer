from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem,
    QGridLayout, QSizePolicy, QGroupBox
)
from PySide6.QtCore import Qt
from database import db
from styles import COLORS, apply_shadow
from ui_base import BaseScreen
from ui_compat import (FPrimaryButton, FPushButton, accent_button_style,
                        confirm, notify)


class ProjectScreen(BaseScreen):
    """Экран проекта после создания/открытия."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._transient = []  # виджеты, добавленные в стек (wizard/review/...), чтобы удалять их
        self.setAcceptDrops(True)
        self.init_ui()
        self.load_project_info()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 15, 30, 15)

        # Заголовок
        title = QLabel("📁 ПРОЕКТ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Информация о проекте
        self.info_label = QLabel()
        self.info_label.setObjectName("subtitle")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)
        layout.addSpacing(5)

        # Карточка со списком файлов
        files_group = QGroupBox("📄 Файлы в проекте (можно перетащить файл сюда)")
        files_layout = QVBoxLayout()
        self.files_list = QListWidget()
        self.files_list.setMinimumHeight(120)
        self.files_list.setAcceptDrops(True)
        files_layout.addWidget(self.files_list)

        # Кнопки управления файлами
        file_buttons = QHBoxLayout()
        btn_add_file = FPushButton("📥 Добавить файл")
        btn_add_file.setMinimumHeight(45)
        btn_add_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_add_file.clicked.connect(self.on_add_file)
        apply_shadow(btn_add_file)

        btn_delete_file = FPushButton("🗑️ Удалить файл")
        btn_delete_file.setObjectName("danger")
        btn_delete_file.setMinimumHeight(45)
        btn_delete_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_delete_file.clicked.connect(self.on_delete_file)
        apply_shadow(btn_delete_file, color=COLORS['red'])

        file_buttons.addWidget(btn_add_file)
        file_buttons.addWidget(btn_delete_file)
        btn_health = FPushButton("🧹 Целостность")
        btn_health.setMinimumHeight(45)
        btn_health.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_health.setToolTip("Сироты удалённых файлов: проверка и чистка")
        btn_health.clicked.connect(self.on_integrity)
        apply_shadow(btn_health, color=COLORS['amber'])
        file_buttons.addWidget(btn_health)
        files_layout.addLayout(file_buttons)
        files_group.setLayout(files_layout)
        apply_shadow(files_group)
        layout.addWidget(files_group)
        layout.addSpacing(5)

        # Обмен разметкой между проектами
        io_group = QGroupBox("🔄 Обмен разметкой")
        io_layout = QHBoxLayout()
        btn_import_ann = FPushButton("📥 Импорт разметки")
        btn_import_ann.setMinimumHeight(40)
        btn_import_ann.setSizePolicy(QSizePolicy.Policy.Expanding,
                                     QSizePolicy.Policy.Fixed)
        btn_import_ann.setToolTip("Preview → Merge/Update из JSONL")
        btn_import_ann.clicked.connect(self.on_import_annotations)
        io_layout.addWidget(btn_import_ann)
        io_group.setLayout(io_layout)
        layout.addWidget(io_group)
        layout.addSpacing(5)

        # Карточка с кнопками
        actions_group = QGroupBox("⚡ Действия")
        buttons_grid = QGridLayout()
        buttons_grid.setSpacing(10)

        # Ряд 1
        btn_start_review = FPrimaryButton("▶️ Начать ревью")
        btn_start_review.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_start_review.setMinimumHeight(45)
        btn_start_review.clicked.connect(self.on_start_review)
        apply_shadow(btn_start_review)

        btn_reports = FPushButton("📈 Отчёты")
        btn_reports.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_reports.setMinimumHeight(45)
        btn_reports.clicked.connect(self.on_reports)
        apply_shadow(btn_reports)

        btn_history = FPushButton("🕐 История")
        btn_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_history.setMinimumHeight(45)
        btn_history.clicked.connect(self.on_history)
        apply_shadow(btn_history)

        btn_backup = FPushButton("💾 Резервные копии")
        btn_backup.setStyleSheet(accent_button_style())
        btn_backup.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_backup.setMinimumHeight(45)
        btn_backup.clicked.connect(self.on_backup)
        apply_shadow(btn_backup, color=COLORS['blue'])

        buttons_grid.addWidget(btn_start_review, 0, 0)
        buttons_grid.addWidget(btn_reports, 0, 1)
        buttons_grid.addWidget(btn_history, 0, 2)
        buttons_grid.addWidget(btn_backup, 0, 3)

        # Ряд 2 (рескин: Датасеты и Прогоны живут в сайдбаре —
        # дублей точек входа больше нет).
        btn_settings = FPushButton("⚙️ Настройки")
        btn_settings.setStyleSheet(accent_button_style())
        btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_settings.setMinimumHeight(45)
        btn_settings.clicked.connect(self.on_settings)
        apply_shadow(btn_settings, color=COLORS['blue'])

        btn_back = FPushButton("🚪 Назад")
        btn_back.setObjectName("danger")
        btn_back.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_back.setMinimumHeight(45)
        btn_back.clicked.connect(self.on_back)
        apply_shadow(btn_back, color=COLORS['red'])

        buttons_grid.addWidget(btn_settings, 1, 0, 1, 2)
        buttons_grid.addWidget(btn_back, 1, 2, 1, 2)
        actions_group.setLayout(buttons_grid)
        apply_shadow(actions_group)
        layout.addWidget(actions_group)

        self.setLayout(layout)

    def load_project_info(self):
        """Загружает информацию о проекте."""
        self.info_label.setText(f"📂 {self.project_path}")
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_id, file_name, row_count FROM files "
                               "ORDER BY imported_at DESC")
                files = cursor.fetchall()
                cursor.execute("SELECT COUNT(*) AS total FROM cases c "
                               "JOIN files f ON f.file_id = c.file_id")
                total = cursor.fetchone()["total"]
                cursor.execute("SELECT COUNT(*) AS reviewed FROM annotations a "
                               "JOIN cases c ON c.case_id = a.case_id "
                               "JOIN files f ON f.file_id = c.file_id "
                               "WHERE a.status != 'unreviewed'")
                reviewed = cursor.fetchone()["reviewed"]
            pct = int(reviewed / total * 100) if total else 0
            self.info_label.setText(
                f"📂 {self.project_path}\nПроверено: {reviewed}/{total} ({pct}%)")
            self.files_list.clear()
            if files:
                for file in files:
                    item = QListWidgetItem(f"📄 {file['file_name']} ({file['row_count']} кейсов)")
                    item.setData(Qt.ItemDataRole.UserRole, file['file_id'])
                    self.files_list.addItem(item)
            else:
                item = QListWidgetItem("📭 Файлы ещё не добавлены")
                item.setData(Qt.ItemDataRole.UserRole, None)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.files_list.addItem(item)
        except Exception as e:
            self.files_list.clear()
            item = QListWidgetItem(f"❌ Ошибка загрузки: {str(e)}")
            self.files_list.addItem(item)

    def refresh(self):
        self.load_project_info()

    def _show_transient(self, widget):
        self._transient.append(widget)
        self.parent_window.stack.addWidget(widget)
        self.parent_window.stack.setCurrentWidget(widget)

    def on_add_file(self):
        """Добавление нового файла (мастер — поверх, пункта меню у него нет)."""
        self.open_wizard()

    def open_wizard(self, file_path: str | None = None):
        """Мастер импорта; file_path — пресет (drag-n-drop)."""
        from import_wizard import ImportWizard
        wizard = ImportWizard(self.project_path, self.parent_window)
        wizard.import_finished.connect(lambda: self._close_wizard(wizard))
        wizard.import_cancelled.connect(lambda: self._close_wizard(wizard))
        self._show_transient(wizard)
        if file_path:
            wizard.load_path(file_path)

    def dragEnterEvent(self, event):
        try:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return
        except Exception:
            pass
        super().dragEnterEvent(event)

    def dropEvent(self, event):
        try:
            urls = event.mimeData().urls()
            paths = [u.toLocalFile() for u in urls or []]
            paths = [p for p in paths if p]
            if paths:
                event.acceptProposedAction()
                self.open_wizard(paths[0])
                if len(paths) > 1:
                    notify(self, "warning", "Импорт",
                           "Перетащено несколько файлов — открыт первый. "
                           "Остальные добавь по одному.")
                return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
        super().dropEvent(event)

    def _close_wizard(self, wizard):
        stack = self.parent_window.stack
        stack.removeWidget(wizard)
        wizard.deleteLater()
        if wizard in self._transient:
            self._transient.remove(wizard)
        self.parent_window.main_window.show_screen("project")

    def on_delete_file(self):
        """Удаление выбранного файла."""
        current_item = self.files_list.currentItem()
        if not current_item:
            notify(self, "warning", "Внимание", "Выберите файл для удаления")
            return
        file_id = current_item.data(Qt.ItemDataRole.UserRole)
        if not file_id:
            notify(self, "warning", "Внимание", "Выберите файл для удаления")
            return
        file_name = current_item.text()
        if not confirm(
            self,
            "Подтверждение",
            f"Удалить файл и все связанные кейсы?\n\n{file_name}\n\n"
            "⚠️ Это действие нельзя отменить.",
        ):
            return
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                # Кейсы — явно до файла: safety net на случай выключенного FK,
                # иначе остаются сироты (невидимы в ревью, но портят счётчики).
                cursor.execute("DELETE FROM cases WHERE file_id = ?", (file_id,))
                cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                if cursor.rowcount == 0:
                    raise RuntimeError("Файл уже удалён")
            self.load_project_info()
            notify(self, "success", "Удаление", "✅ Файл удалён из проекта")
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось удалить файл: {str(e)}")

    def on_integrity(self):
        """Целостность БД: отчёт о сиротах + чистка."""
        from maintenance_dialog import IntegrityDialog
        IntegrityDialog(self.project_path, self).exec()
        self.load_project_info()

    def on_start_review(self):
        """Ревью с выбором датасета — через главный экран (подсветка лупы)."""
        from dataset_select_dialog import DatasetSelectDialog
        dialog = DatasetSelectDialog(self.project_path, self)
        if dialog.exec() == DatasetSelectDialog.Accepted:
            filters = {}
            if dialog.selected_file_id is not None:
                filters['file_id'] = dialog.selected_file_id
            self.parent_window.main_window.show_screen("review", filters=filters)

    def on_reports(self):
        """Переход к отчётам."""
        self.parent_window.main_window.show_screen("reports")

    def on_history(self):
        """Переход к истории."""
        self.parent_window.main_window.show_screen("history")

    def on_backup(self):
        """Переход к резервному копированию."""
        self.parent_window.main_window.show_screen("backup")

    def on_settings(self):
        """Переход к настройкам."""
        self.parent_window.main_window.show_screen("settings")

    def on_import_annotations(self):
        """Импорт разметки: Preview → Merge/Update → прыжок в ревью."""
        from annotation_io_dialog import ImportAnnotationsDialog
        dlg = ImportAnnotationsDialog(self.project_path, self)
        dlg.exec()
        self.load_project_info()
        cid = getattr(dlg, "result_case_id", None)
        if cid:
            try:
                mw = self.parent_window.main_window
                mw.show_screen("review")
                scr = mw.project_window.screens.get("review")
                if scr is not None and not scr.ensure_visible_case(cid):
                    notify(self, "warning", "Внимание",
                           "Кейс не найден в проекте.")
            except Exception:
                pass

    def on_back(self):
        """Возврат на стартовый экран."""
        main = self.parent_window
        while main is not None and not hasattr(main, "go_home"):
            main = main.parent()
        if main is not None:
            main.go_home()
