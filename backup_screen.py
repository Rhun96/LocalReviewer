from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QFileDialog
)
from PySide6.QtCore import Qt, Signal
from backup_service import create_backup, get_backups_list, restore_backup, delete_backup
from ui_base import BaseScreen
from ui_compat import FPrimaryButton, FPushButton, clear_in_fluent, confirm, notify
from workers import run_in_background


class BackupScreen(BaseScreen):
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
        
        btn_create = FPrimaryButton("Создать резервную копию")
        btn_create.setMinimumHeight(50)
        btn_create.clicked.connect(self.on_create_backup)
        
        btn_refresh = FPushButton("Обновить список")
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
        clear_in_fluent(self.backups_list)
        
        # Кнопки для выбранной копии
        actions_layout = QHBoxLayout()
        
        btn_restore = FPushButton("Восстановить выбранную копию")
        btn_restore.setMinimumHeight(50)
        btn_restore.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        btn_restore.clicked.connect(self.on_restore_backup)
        
        btn_delete = FPushButton("Удалить выбранную копию")
        btn_delete.setMinimumHeight(50)
        btn_delete.setObjectName("danger")
        btn_delete.clicked.connect(self.on_delete_backup)
        
        actions_layout.addWidget(btn_restore)
        actions_layout.addWidget(btn_delete)
        layout.addLayout(actions_layout)
        
        # Кнопка назад
        btn_back = FPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(50)
        btn_back.clicked.connect(self.on_back)
        layout.addWidget(btn_back)
        
        self.setLayout(layout)
    
    def load_backups(self):
        """Загружает список резервных копий."""
        try:
            backups = get_backups_list(self.project_path)
        except Exception as e:
            self.show_error("Не удалось получить список копий", e)
            return

        self.backups_list.clear()

        if not backups:
            item = QListWidgetItem("Резервных копий нет")
            item.setData(Qt.ItemDataRole.UserRole, None)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.backups_list.addItem(item)
            return
        
        for backup in backups:
            size_mb = backup['size'] / (1024 * 1024)
            text = f"{backup['name']} ({size_mb:.2f} МБ, {backup['created'][:19]})"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, backup['path'])
            self.backups_list.addItem(item)
    
    def on_create_backup(self):
        """Создаёт резервную копию (в фоне, чтобы не морозить UI)."""
        self.set_buttons_enabled(False)

        def _done(path):
            self.set_buttons_enabled(True)
            notify(self, "success", "Резервная копия создана", f"Копия сохранена:\n{path}")
            self.load_backups()
            if self.parent_window and hasattr(self.parent_window, "refresh_all"):
                try:
                    self.parent_window.refresh_all()
                except Exception:
                    pass

        def _fail(msg):
            self.set_buttons_enabled(True)
            notify(self, "error", "Ошибка", f"Не удалось создать резервную копию:\n{msg}")

        run_in_background(create_backup, self.project_path, on_finished=_done, on_error=_fail)

    def set_buttons_enabled(self, enabled: bool):
        for w in self.findChildren(QWidget):
            if isinstance(w, QPushButton):
                w.setEnabled(enabled)

    def refresh(self):
        self.load_backups()
    
    def on_restore_backup(self):
        """Восстанавливает выбранную резервную копию."""
        current_item = self.backups_list.currentItem()

        if not current_item:
            notify(self, "warning", "Внимание", "Выберите резервную копию")
            return

        backup_path = current_item.data(Qt.ItemDataRole.UserRole)

        if not backup_path:
            return

        if not confirm(
            self,
            "Подтверждение",
            "Восстановить базу данных из этой резервной копии?\n\nТекущие данные будут заменены.",
        ):
            return
        try:
            restore_backup(self.project_path, backup_path)
            notify(
                self,
                "success",
                "Восстановление завершено",
                "База данных восстановлена из резервной копии.\nТекущая база была сохранена как резервная копия."
            )
            self.load_backups()
            if self.parent_window and hasattr(self.parent_window, "refresh_all"):
                try:
                    self.parent_window.refresh_all()
                except Exception:
                    pass
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось восстановить: {str(e)}")
    
    def on_delete_backup(self):
        """Удаляет выбранную резервную копию."""
        current_item = self.backups_list.currentItem()

        if not current_item:
            notify(self, "warning", "Внимание", "Выберите резервную копию")
            return

        backup_path = current_item.data(Qt.ItemDataRole.UserRole)

        if not backup_path:
            return

        if not confirm(self, "Подтверждение", "Удалить эту резервную копию?"):
            return
        if delete_backup(self.project_path, backup_path):
            self.load_backups()
        else:
            notify(self, "error", "Ошибка", "Не удалось удалить резервную копию")
    
    def on_back(self):
        """Возврат к проекту."""
        self.backup_closed.emit()