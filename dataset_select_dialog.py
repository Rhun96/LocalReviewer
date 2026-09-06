from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QListWidget, QListWidgetItem, QMessageBox
)
from PySide6.QtCore import Qt
from database import get_db_connection


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

        title = QLabel("📄 Выберите датасет для ревью")
        title.setStyleSheet("font-size: 18px; font-weight: bold; color: #00FF41;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Выберите конкретный файл или все файлы:")
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

        self.load_files()

        # Кнопки
        buttons = QHBoxLayout()
        btn_all = QPushButton("📋 Все файлы")
        btn_all.setMinimumHeight(45)
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

        btn_ok = QPushButton("✅ Начать ревью")
        btn_ok.setMinimumHeight(45)
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

        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setMinimumHeight(45)
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
            conn = get_db_connection(self.project_path)
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
            conn.close()

            self.files_list.clear()
            for f in files:
                text = f"📄 {f['file_name']}  ({f['row_count']} кейсов, проверено: {f['reviewed']})"
                item = QListWidgetItem(text)
                item.setData(Qt.ItemDataRole.UserRole, f['file_id'])
                self.files_list.addItem(item)

            if self.files_list.count() > 0:
                self.files_list.setCurrentRow(0)
        except Exception:
            pass

    def on_accept(self):
        current = self.files_list.currentItem()
        if current:
            self.selected_file_id = current.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def on_all_files(self):
        self.selected_file_id = None
        self.accept()