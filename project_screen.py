from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QMessageBox, QListWidget, QListWidgetItem,
    QGridLayout, QSizePolicy, QGroupBox
)
from PySide6.QtCore import Qt
from database import get_db_connection
from styles import apply_shadow


class ProjectScreen(QWidget):
    """Экран проекта после создания/открытия."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
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
        files_group = QGroupBox("📄 Файлы в проекте")
        files_layout = QVBoxLayout()
        self.files_list = QListWidget()
        self.files_list.setMinimumHeight(120)
        files_layout.addWidget(self.files_list)

        # Кнопки управления файлами
        file_buttons = QHBoxLayout()
        btn_add_file = QPushButton("📥 Добавить файл")
        btn_add_file.setMinimumHeight(45)
        btn_add_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_add_file.clicked.connect(self.on_add_file)
        apply_shadow(btn_add_file)

        btn_delete_file = QPushButton("🗑️ Удалить файл")
        btn_delete_file.setObjectName("danger")
        btn_delete_file.setMinimumHeight(45)
        btn_delete_file.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_delete_file.clicked.connect(self.on_delete_file)
        apply_shadow(btn_delete_file, color='#FF3B3B')

        file_buttons.addWidget(btn_add_file)
        file_buttons.addWidget(btn_delete_file)
        files_layout.addLayout(file_buttons)
        files_group.setLayout(files_layout)
        apply_shadow(files_group)
        layout.addWidget(files_group)
        layout.addSpacing(5)

        # Карточка с кнопками
        actions_group = QGroupBox("⚡ Действия")
        buttons_grid = QGridLayout()
        buttons_grid.setSpacing(10)

        # Ряд 1
        btn_start_review = QPushButton("▶️ Начать ревью")
        btn_start_review.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_start_review.setMinimumHeight(45)
        btn_start_review.clicked.connect(self.on_start_review)
        apply_shadow(btn_start_review)

        btn_reports = QPushButton("📈 Отчёты")
        btn_reports.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_reports.setMinimumHeight(45)
        btn_reports.clicked.connect(self.on_reports)
        apply_shadow(btn_reports)

        btn_history = QPushButton("🕐 История")
        btn_history.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_history.setMinimumHeight(45)
        btn_history.clicked.connect(self.on_history)
        apply_shadow(btn_history)

        btn_backup = QPushButton("💾 Резервные копии")
        btn_backup.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_backup.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_backup.setMinimumHeight(45)
        btn_backup.clicked.connect(self.on_backup)
        apply_shadow(btn_backup, color='#00AAFF')

        buttons_grid.addWidget(btn_start_review, 0, 0)
        buttons_grid.addWidget(btn_reports, 0, 1)
        buttons_grid.addWidget(btn_history, 0, 2)
        buttons_grid.addWidget(btn_backup, 0, 3)

        # Ряд 2
        btn_settings = QPushButton("⚙️ Настройки")
        btn_settings.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_settings.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_settings.setMinimumHeight(45)
        btn_settings.clicked.connect(self.on_settings)
        apply_shadow(btn_settings, color='#00AAFF')

        btn_back = QPushButton("🚪 Назад")
        btn_back.setObjectName("danger")
        btn_back.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_back.setMinimumHeight(45)
        btn_back.clicked.connect(self.on_back)
        apply_shadow(btn_back, color='#FF3B3B')

        buttons_grid.addWidget(btn_settings, 1, 0)
        buttons_grid.addWidget(btn_back, 1, 1, 1, 3)
        actions_group.setLayout(buttons_grid)
        apply_shadow(actions_group)
        layout.addWidget(actions_group)

        self.setLayout(layout)

    def load_project_info(self):
        """Загружает информацию о проекте."""
        self.info_label.setText(f"📂 {self.project_path}")
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT file_id, file_name, row_count FROM files ORDER BY imported_at DESC")
            files = cursor.fetchall()
            conn.close()
            self.files_list.clear()
            if files:
                for file in files:
                    item = QListWidgetItem(f"📄 {file['file_name']} ({file['row_count']} кейсов)")
                    item.setData(Qt.ItemDataRole.UserRole, file['file_id'])
                    self.files_list.addItem(item)
            else:
                item = QListWidgetItem("📭 Файлы ещё не добавлены")
                self.files_list.addItem(item)
        except Exception as e:
            self.files_list.clear()
            item = QListWidgetItem(f"❌ Ошибка загрузки: {str(e)}")
            self.files_list.addItem(item)

    def refresh(self):
        self.load_project_info()

    def on_add_file(self):
        """Добавление нового файла."""
        from import_wizard import ImportWizard
        wizard = ImportWizard(self.project_path, self.parent_window)
        wizard.import_finished.connect(self.on_import_finished)
        self.parent_window.stack.addWidget(wizard)
        self.parent_window.stack.setCurrentWidget(wizard)

    def on_import_finished(self):
        """Завершение импорта."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_delete_file(self):
        """Удаление выбранного файла."""
        current_item = self.files_list.currentItem()
        if not current_item:
            QMessageBox.warning(self, "Внимание", "Выберите файл для удаления")
            return
        file_id = current_item.data(Qt.ItemDataRole.UserRole)
        if not file_id:
            QMessageBox.warning(self, "Внимание", "Выберите файл для удаления")
            return
        file_name = current_item.text()
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            f"Удалить файл и все связанные кейсы?\n\n{file_name}\n\n⚠️ Это действие нельзя отменить.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            try:
                conn = get_db_connection(self.project_path)
                cursor = conn.cursor()
                cursor.execute("DELETE FROM files WHERE file_id = ?", (file_id,))
                conn.commit()
                conn.close()
                self.load_project_info()
                QMessageBox.information(self, "Удаление", "✅ Файл удалён из проекта")
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось удалить файл: {str(e)}")

    def on_start_review(self):
        """Ревью с выбором датасета."""
        from dataset_select_dialog import DatasetSelectDialog
        dialog = DatasetSelectDialog(self.project_path, self)
        if dialog.exec() == DatasetSelectDialog.Accepted:
            filters = {}
            if dialog.selected_file_id is not None:
                filters['file_id'] = dialog.selected_file_id

            from review_screen import ReviewScreen
            review = ReviewScreen(self.project_path, self.parent_window, filters=filters)
            review.review_closed.connect(self.on_review_closed)
            self.parent_window.stack.addWidget(review)
            self.parent_window.stack.setCurrentWidget(review)

    def on_review_closed(self):
        """Возврат из ревью."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_reports(self):
        """Переход к отчётам."""
        from reports_screen import ReportsScreen
        reports = ReportsScreen(self.project_path, self.parent_window)
        reports.reports_closed.connect(self.on_reports_closed)
        self.parent_window.stack.addWidget(reports)
        self.parent_window.stack.setCurrentWidget(reports)

    def on_reports_closed(self):
        """Возврат из отчётов."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_history(self):
        """Переход к истории."""
        from history_screen import HistoryScreen
        history = HistoryScreen(self.project_path, self.parent_window)
        history.history_closed.connect(self.on_history_closed)
        self.parent_window.stack.addWidget(history)
        self.parent_window.stack.setCurrentWidget(history)

    def on_history_closed(self):
        """Возврат из истории."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_backup(self):
        """Переход к резервному копированию."""
        from backup_screen import BackupScreen
        backup = BackupScreen(self.project_path, self.parent_window)
        backup.backup_closed.connect(self.on_backup_closed)
        self.parent_window.stack.addWidget(backup)
        self.parent_window.stack.setCurrentWidget(backup)

    def on_backup_closed(self):
        """Возврат из резервного копирования."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_settings(self):
        """Переход к настройкам."""
        from settings_screen import SettingsScreen
        settings = SettingsScreen(self.project_path, self.parent_window)
        settings.settings_closed.connect(self.on_settings_closed)
        self.parent_window.stack.addWidget(settings)
        self.parent_window.stack.setCurrentWidget(settings)

    def on_settings_closed(self):
        """Возврат из настроек."""
        self.load_project_info()
        self.parent_window.stack.setCurrentWidget(self)

    def on_back(self):
        """Возврат на стартовый экран."""
        self.parent_window.stack.setCurrentWidget(self.parent_window.start_screen)