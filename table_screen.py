from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QMessageBox, QComboBox,
    QHeaderView
)
from PySide6.QtCore import Qt, Signal
from database import get_db_connection


class TableScreen(QWidget):
    """Экран табличного просмотра кейсов."""
    
    table_closed = Signal()
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        
        self.init_ui()
        self.load_cases()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 20, 40, 20)
        
        # Заголовок
        title = QLabel("ТАБЛИЧНЫЙ РЕЖИМ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Фильтр по статусу
        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Фильтр по статусу:"))
        
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все статусы", None)
        self.status_filter.addItem("Не проверено", "unreviewed")
        self.status_filter.addItem("Хорошо", "good")
        self.status_filter.addItem("Плохо", "bad")
        self.status_filter.addItem("Сомневаюсь", "uncertain")
        self.status_filter.addItem("Дубль", "duplicate")
        self.status_filter.addItem("Пропустить", "skip")
        self.status_filter.currentIndexChanged.connect(self.load_cases)
        filter_layout.addWidget(self.status_filter)
        filter_layout.addStretch()
        layout.addLayout(filter_layout)
        
        # Таблица
        self.table = QTableWidget()
        self.table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 2px solid #00FF41;
                color: #00FF41;
                font-size: 12px;
                gridline-color: #003315;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #003315;
            }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        btn_refresh = QPushButton("Обновить")
        btn_refresh.setMinimumHeight(50)
        btn_refresh.clicked.connect(self.load_cases)
        
        btn_back = QPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(50)
        btn_back.clicked.connect(self.on_back)
        
        buttons_layout.addWidget(btn_refresh)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def load_cases(self):
        """Загружает кейсы в таблицу."""
        status_filter = self.status_filter.currentData()
        
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            
            query = """
                SELECT 
                    c.case_id,
                    c.row_index + 1 as row_num,
                    f.file_name,
                    SUBSTR(c.primary_text, 1, 100) as primary_text,
                    COALESCE(a.status, 'unreviewed') as status,
                    a.comment,
                    a.updated_at
                FROM cases c
                JOIN files f ON c.file_id = f.file_id
                LEFT JOIN annotations a ON c.case_id = a.case_id
            """
            
            params = []
            if status_filter:
                query += " WHERE COALESCE(a.status, 'unreviewed') = ?"
                params.append(status_filter)
            
            query += " ORDER BY f.imported_at, c.row_index LIMIT 500"
            
            cursor.execute(query, params)
            cases = cursor.fetchall()
            conn.close()
            
            self.table.clear()
            self.table.setColumnCount(7)
            self.table.setRowCount(len(cases))
            self.table.setHorizontalHeaderLabels([
                "ID", "Строка", "Файл", "Основной текст", "Статус", "Комментарий", "Обновлён"
            ])
            
            status_names = {
                'unreviewed': 'Не проверено',
                'good': 'Хорошо',
                'bad': 'Плохо',
                'uncertain': 'Сомневаюсь',
                'duplicate': 'Дубль',
                'skip': 'Пропустить'
            }
            
            for row, case in enumerate(cases):
                self.table.setItem(row, 0, QTableWidgetItem(str(case['case_id'])))
                self.table.setItem(row, 1, QTableWidgetItem(str(case['row_num'])))
                self.table.setItem(row, 2, QTableWidgetItem(case['file_name']))
                self.table.setItem(row, 3, QTableWidgetItem(case['primary_text'] or ''))
                self.table.setItem(row, 4, QTableWidgetItem(status_names.get(case['status'], case['status'])))
                self.table.setItem(row, 5, QTableWidgetItem(case['comment'] or ''))
                self.table.setItem(row, 6, QTableWidgetItem(case['updated_at'][:19] if case['updated_at'] else ''))
            
            self.table.resizeColumnsToContents()
            
            # Устанавливаем ширину колонки с текстом
            self.table.setColumnWidth(3, 400)
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить кейсы: {str(e)}")
    
    def on_back(self):
        """Возврат к проекту."""
        self.table_closed.emit()