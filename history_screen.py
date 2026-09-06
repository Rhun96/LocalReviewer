from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, Signal
from database import get_db_connection


class HistoryScreen(QWidget):
    """Экран истории изменений."""
    
    history_closed = Signal()
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        
        self.init_ui()
        self.load_history()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 20, 40, 20)
        
        # Заголовок
        title = QLabel("ИСТОРИЯ ИЗМЕНЕНИЙ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Фильтр по типу события
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Тип события:"))
        
        self.event_filter = QComboBox()
        self.event_filter.addItem("Все события", None)
        self.event_filter.addItem("Изменение статуса", "status_changed")
        self.event_filter.addItem("Изменение комментария", "comment_changed")
        self.event_filter.addItem("Добавление тега", "tag_added")
        self.event_filter.addItem("Удаление тега", "tag_removed")
        self.event_filter.currentIndexChanged.connect(self.load_history)
        filter_layout.addWidget(self.event_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Таблица истории
        self.history_table = QTableWidget()
        self.history_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 2px solid #00FF41;
                color: #00FF41;
                font-size: 13px;
                gridline-color: #003315;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.history_table)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        btn_refresh = QPushButton("Обновить")
        btn_refresh.clicked.connect(self.load_history)
        
        btn_back = QPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.clicked.connect(self.on_back)
        
        buttons_layout.addWidget(btn_refresh)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def load_history(self):
        """Загружает историю изменений."""
        event_type = self.event_filter.currentData()
        
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    h.history_id,
                    h.event_type,
                    h.field_name,
                    h.old_value,
                    h.new_value,
                    h.created_at,
                    c.case_id,
                    f.file_name
                FROM history h
                JOIN cases c ON h.case_id = c.case_id
                JOIN files f ON c.file_id = f.file_id
            """
            
            params = []
            if event_type:
                query += " WHERE h.event_type = ?"
                params.append(event_type)
            
            query += " ORDER BY h.created_at DESC LIMIT 500"
            
            cursor.execute(query, params)
            events = cursor.fetchall()
            conn.close()
            
            self.history_table.clear()
            self.history_table.setColumnCount(7)
            self.history_table.setRowCount(len(events))
            self.history_table.setHorizontalHeaderLabels([
                "Дата", "Кейс", "Файл", "Событие", "Поле", "Было", "Стало"
            ])
            
            event_names = {
                'status_changed': 'Изменение статуса',
                'comment_changed': 'Изменение комментария',
                'tag_added': 'Добавление тега',
                'tag_removed': 'Удаление тега',
            }
            
            for row, event in enumerate(events):
                self.history_table.setItem(row, 0, QTableWidgetItem(event['created_at'][:19]))
                self.history_table.setItem(row, 1, QTableWidgetItem(str(event['case_id'])))
                self.history_table.setItem(row, 2, QTableWidgetItem(event['file_name']))
                self.history_table.setItem(row, 3, QTableWidgetItem(event_names.get(event['event_type'], event['event_type'])))
                self.history_table.setItem(row, 4, QTableWidgetItem(event['field_name'] or ''))
                self.history_table.setItem(row, 5, QTableWidgetItem(event['old_value'] or ''))
                self.history_table.setItem(row, 6, QTableWidgetItem(event['new_value'] or ''))
            
            self.history_table.resizeColumnsToContents()
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить историю: {str(e)}")
    
    def on_back(self):
        """Возврат к проекту."""
        self.history_closed.emit()