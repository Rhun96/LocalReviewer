from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem
)
from PySide6.QtCore import Qt
from database import db
from ui_compat import FLUENT, FPrimaryButton, FPushButton, FTitleLabel, clear_in_fluent, notify


class DatasetSelectDialog(QDialog):
    """Диалог выбора датасета для ревью."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Выбор датасета")
        self.setMinimumWidth(500)
        self.setMinimumHeight(400)
        self.selected_file_id = None
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        title = FTitleLabel("📄 Выберите датасет для ревью")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Выберите конкретный файл или все файлы:")
        if not FLUENT:
            hint.setStyleSheet("color: #00AA2A; font-size: 13px;")
        layout.addWidget(hint)

        # Список файлов
        self.files_list = QListWidget()
        self.files_list.setStyleSheet("""
            QListWidget {
                background-color: #0D150D;
                border: 2px solid #00441A;
                border-radius: 8px;
                color: #00FF41;
                font-size: 14px;
            }
            QListWidget::item {
                padding: 12px;
                border-bottom: 1px solid #00441A;
            }
            QListWidget::item:selected {
                background-color: #1A3A1A;
            }
            QListWidget::item:hover {
                background-color: #0F2010;
            }
        """)
        layout.addWidget(self.files_list)
        clear_in_fluent(self.files_list)
        self.files_list.itemDoubleClicked.connect(lambda _item: self.on_accept())

        self.load_files()

        # Кнопки
        buttons = QHBoxLayout()
        btn_all = FPushButton("📋 Все файлы")
        btn_all.setMinimumHeight(45)
        if not FLUENT:
            btn_all.setStyleSheet("""
                QPushButton {
                    background-color: #0D150D;
                    color: #00AAFF;
                    border: 2px solid #00AAFF;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #002233;
                }
            """)
        btn_all.clicked.connect(self.on_all_files)

        btn_ok = FPrimaryButton("✅ Начать ревью")
        btn_ok.setMinimumHeight(45)
        if not FLUENT:
            btn_ok.setStyleSheet("""
                QPushButton {
                    background-color: #0D150D;
                    color: #00FF41;
                    border: 2px solid #00FF41;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #003315;
                }
            """)
        btn_ok.clicked.connect(self.on_accept)

        btn_cancel = FPushButton("❌ Отмена")
        btn_cancel.setMinimumHeight(45)
        if not FLUENT:
            btn_cancel.setStyleSheet("""
                QPushButton {
                    background-color: #0D150D;
                    color: #FF3B3B;
                    border: 2px solid #FF3B3B;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-size: 14px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #330000;
                }
            """)
        btn_cancel.clicked.connect(self.reject)

        buttons.addWidget(btn_all)
        buttons.addWidget(btn_ok)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)

        self.setLayout(layout)

    def load_files(self):
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT f.file_id, f.file_name, f.row_count,
                           COUNT(DISTINCT CASE WHEN COALESCE(a.status,'unreviewed') != 'unreviewed'
                                 THEN c.case_id END) as reviewed
                    FROM files f
                    LEFT JOIN cases c ON f.file_id = c.file_id
                    LEFT JOIN annotations a ON c.case_id = a.case_id
                    GROUP BY f.file_id
                    ORDER BY f.imported_at DESC
                """)
                files = cursor.fetchall()

            self.files_list.clear()
            for f in files:
                text = f"📄 {f['file_name']}  ({f['row_count']} кейсов, проверено: {f['reviewed']})"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, f['file_id'])
                self.files_list.addItem(item)

            if self.files_list.count() > 0:
                self.files_list.setCurrentRow(0)
            else:
                item = QListWidgetItem("📭 Файлы ещё не добавлены")
                item.setData(Qt.ItemDataRole.UserRole, None)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                self.files_list.addItem(item)
        except Exception as e:
            notify(self, "warning", "Ошибка", f"Не удалось загрузить файлы:\n{e}")

    def on_accept(self):
        current = self.files_list.currentItem()
        if current:
            file_id = current.data(Qt.ItemDataRole.UserRole)
            if file_id is None and self.files_list.count() == 1:
                # Плейсхолдер «нет файлов» — явный отказ вместо молчаливого «все файлы»
                notify(self, "warning", "Внимание", "В проекте пока нет файлов для ревью")
                return
            self.selected_file_id = file_id
        self.accept()

    def on_all_files(self):
        self.selected_file_id = None
        self.accept()
