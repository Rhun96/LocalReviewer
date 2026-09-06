from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QMessageBox, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from backup_service import create_backup, get_backups_list, restore_backup, delete_backup


class BackupScreen(QWidget):
    """Экран резервного копирования."""
    
    backup_closed = Signal()
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        
        self.init_ui()
        self.load_backups()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 20, 40, 20)
        
        # Заголовок
        title = QLabel("РЕЗЕРВНОЕ КОПИРОВАНИЕ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Кнопки действий
        buttons_layout = QHBoxLayout()
        
        btn_create = QPushButton("Создать резервную копию")
        btn_create.setMinimumHeight(50)
        btn_create.clicked.connect(self.on_create_backup)
        
        btn_refresh = QPushButton("Обновить список")
        btn_refresh.setMinimumHeight(50)
        btn_refresh.clicked.connect(self.load_backups)
        
        buttons_layout.addWidget(btn_create)
        buttons_layout.addWidget(btn_refresh)
        layout.addLayout(buttons_layout)
        
        # Список резервных копий
        list_label = QLabel("Резервные копии:")
        list_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        layout.addWidget(list_label)
        
        self.backups_list = QListWidget()
        self.backups_list.setStyleSheet("""
            QListWidget {
                background-color: #001A0A;
                border: 2px solid #00FF41;
                border-radius: 4px;
                color: #00FF41;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 10px;
            }
            QListWidget::item:selected {
                background-color: #003315;
            }
        """)
        layout.addWidget(self.backups_list)
        
        # Кнопки для выбранной копии
        actions_layout = QHBoxLayout()
        
        btn_restore = QPushButton("Восстановить выбранную копию")
        btn_restore.setMinimumHeight(50)
        btn_restore.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        btn_restore.clicked.connect(self.on_restore_backup)
        
        btn_delete = QPushButton("Удалить выбранную копию")
        btn_delete.setMinimumHeight(50)
        btn_delete.setObjectName("danger")
        btn_delete.clicked.connect(self.on_delete_backup)
        
        actions_layout.addWidget(btn_restore)
        actions_layout.addWidget(btn_delete)
        layout.addLayout(actions_layout)
        
        # Кнопка назад
        btn_back = QPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(50)
        btn_back.clicked.connect(self.on_back)
        layout.addWidget(btn_back)
        
        self.setLayout(layout)
    
    def load_backups(self):
        """Загружает список резервных копий."""
        backups = get_backups_list(self.project_path)
        
        self.backups_list.clear()
        
        if not backups:
            item = QListWidgetItem("Резервных копий нет")
            self.backups_list.addItem(item)
            return
        
        for backup in backups:
            size_mb = backup['size'] / (1024 * 1024)
            text = f"{backup['name']} ({size_mb:.2f} МБ, {backup['created'][:19]})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, backup['path'])
            self.backups_list.addItem(item)
    
    def on_create_backup(self):
        """Создаёт резервную копию."""
        try:
            backup_path = create_backup(self.project_path)
            QMessageBox.information(
                self,
                "Резервная копия создана",
                f"Копия сохранена:\n{backup_path}"
            )
            self.load_backups()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось создать резервную копию: {str(e)}")
    
    def on_restore_backup(self):
        """Восстанавливает выбранную резервную копию."""
        current_item = self.backups_list.currentItem()
        
        if not current_item:
            QMessageBox.warning(self, "Внимание", "Выберите резервную копию")
            return
        
        backup_path = current_item.data(Qt.ItemDataRole.UserRole)
        
        if not backup_path:
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Восстановить базу данных из этой резервной копии?\n\nТекущие данные будут заменены.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            try:
                restore_backup(self.project_path, backup_path)
                QMessageBox.information(
                    self,
                    "Восстановление завершено",
                    "База данных восстановлена из резервной копии.\nТекущая база была сохранена как резервная копия."
                )
                self.load_backups()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось восстановить: {str(e)}")
    
    def on_delete_backup(self):
        """Удаляет выбранную резервную копию."""
        current_item = self.backups_list.currentItem()
        
        if not current_item:
            QMessageBox.warning(self, "Внимание", "Выберите резервную копию")
            return
        
        backup_path = current_item.data(Qt.ItemDataRole.UserRole)
        
        if not backup_path:
            return
        
        reply = QMessageBox.question(
            self,
            "Подтверждение",
            "Удалить эту резервную копию?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            if delete_backup(backup_path):
                self.load_backups()
            else:
                QMessageBox.critical(self, "Ошибка", "Не удалось удалить резервную копию")
    
    def on_back(self):
        """Возврат к проекту."""
        self.backup_closed.emit()