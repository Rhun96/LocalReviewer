from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QCheckBox, QLineEdit, QComboBox, QGroupBox, QGridLayout,
    QScrollArea, QWidget
)
from PySide6.QtCore import Qt
from database import get_db_connection


STATUS_OPTIONS = [
    ('unreviewed', 'Не проверено'),
    ('good', 'Хорошо'),
    ('bad', 'Плохо'),
    ('uncertain', 'Сомневаюсь'),
    ('duplicate', 'Дубль'),
    ('skip', 'Пропустить'),
]

CHECK_OPTIONS = [
    ('empty_text', 'Пустой текст'),
    ('too_short', 'Слишком короткий'),
    ('too_long', 'Слишком длинный'),
    ('has_url', 'Содержит URL'),
    ('has_email', 'Содержит email'),
    ('has_phone', 'Содержит телефон'),
    ('many_spaces', 'Много пробелов'),
    ('many_caps', 'Много заглавных'),
    ('duplicate', 'Дубль'),
]


class FilterDialog(QDialog):
    """Диалог выбора фильтров."""
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        
        self.setWindowTitle("Фильтры")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        self.filters = {
            'statuses': [],
            'file_id': None,
            'has_comment': None,
            'tags': [],
            'search_text': '',
            'checks': [],
        }
        
        self.status_checkboxes = {}
        self.tag_checkboxes = {}
        self.check_checkboxes = {}
        
        self.init_ui()
    
    def init_ui(self):
        # Основной лейаут диалога
        main_layout = QVBoxLayout()
        main_layout.setSpacing(10)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        title = QLabel("🎛️ ФИЛЬТРЫ")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(title)
        
        # Прокручиваемая область для контента
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("""
            QScrollArea {
                border: none;
                background-color: #000000;
            }
        """)
        
        content_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Статусы
        status_group = QGroupBox("Статус")
        status_layout = QGridLayout()
        
        for i, (code, name) in enumerate(STATUS_OPTIONS):
            cb = QCheckBox(name)
            self.status_checkboxes[code] = cb
            status_layout.addWidget(cb, i // 3, i % 3)
        
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)
        
        # Файл
        file_group = QGroupBox("Файл")
        file_layout = QHBoxLayout()
        
        self.file_combo = QComboBox()
        self.file_combo.addItem("Все файлы", None)
        self.load_files()
        
        file_layout.addWidget(QLabel("Файл:"))
        file_layout.addWidget(self.file_combo)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)
        
        # Комментарий
        comment_group = QGroupBox("Комментарий")
        comment_layout = QHBoxLayout()
        
        self.comment_combo = QComboBox()
        self.comment_combo.addItem("Не важно", None)
        self.comment_combo.addItem("С комментарием", True)
        self.comment_combo.addItem("Без комментария", False)
        
        comment_layout.addWidget(QLabel("Наличие комментария:"))
        comment_layout.addWidget(self.comment_combo)
        comment_group.setLayout(comment_layout)
        layout.addWidget(comment_group)
        
        # Теги
        tags_group = QGroupBox("Теги")
        self.tags_layout = QGridLayout()
        self.load_tags()
        tags_group.setLayout(self.tags_layout)
        layout.addWidget(tags_group)
        
        # Автопроверки
        checks_group = QGroupBox("Автопроверки")
        self.checks_layout = QGridLayout()
        
        for i, (code, name) in enumerate(CHECK_OPTIONS):
            cb = QCheckBox(name)
            self.check_checkboxes[code] = cb
            self.checks_layout.addWidget(cb, i // 3, i % 3)
        
        checks_group.setLayout(self.checks_layout)
        layout.addWidget(checks_group)
        
        # Текстовый поиск
        search_group = QGroupBox("Поиск по тексту")
        search_layout = QHBoxLayout()
        
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")
        
        search_layout.addWidget(self.search_input)
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)
        
        content_widget.setLayout(layout)
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        btn_apply = QPushButton("✅ Применить фильтры")
        btn_apply.setMinimumHeight(45)
        btn_apply.clicked.connect(self.on_apply)
        
        btn_reset = QPushButton("🔄 Сбросить")
        btn_reset.setMinimumHeight(45)
        btn_reset.clicked.connect(self.on_reset)
        
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setObjectName("danger")
        btn_cancel.setMinimumHeight(45)
        btn_cancel.clicked.connect(self.reject)
        
        buttons_layout.addWidget(btn_apply)
        buttons_layout.addWidget(btn_reset)
        buttons_layout.addWidget(btn_cancel)
        main_layout.addLayout(buttons_layout)
        
        self.setLayout(main_layout)
    
    def load_files(self):
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT file_id, file_name FROM files ORDER BY imported_at")
            files = cursor.fetchall()
            conn.close()
            
            for file in files:
                self.file_combo.addItem(file['file_name'], file['file_id'])
        except:
            pass
    
    def load_tags(self):
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT tag_id, tag_name FROM tags ORDER BY tag_name")
            tags = cursor.fetchall()
            conn.close()
            
            row, col = 0, 0
            for tag in tags:
                cb = QCheckBox(tag['tag_name'])
                self.tag_checkboxes[tag['tag_id']] = cb
                self.tags_layout.addWidget(cb, row, col)
                col += 1
                if col >= 3:
                    col = 0
                    row += 1
        except:
            pass
    
    def on_apply(self):
        self.filters['statuses'] = [
            code for code, cb in self.status_checkboxes.items() if cb.isChecked()
        ]
        
        self.filters['file_id'] = self.file_combo.currentData()
        self.filters['has_comment'] = self.comment_combo.currentData()
        
        self.filters['tags'] = [
            tag_id for tag_id, cb in self.tag_checkboxes.items() if cb.isChecked()
        ]
        
        self.filters['checks'] = [
            code for code, cb in self.check_checkboxes.items() if cb.isChecked()
        ]
        
        self.filters['search_text'] = self.search_input.text().strip()
        
        self.accept()
    
    def on_reset(self):
        for cb in self.status_checkboxes.values():
            cb.setChecked(False)
        
        self.file_combo.setCurrentIndex(0)
        self.comment_combo.setCurrentIndex(0)
        
        for cb in self.tag_checkboxes.values():
            cb.setChecked(False)
        
        for cb in self.check_checkboxes.values():
            cb.setChecked(False)
        
        self.search_input.clear()
    
    def get_filters(self):
        return self.filters
    
    def set_filters(self, filters):
        if not filters:
            return
        
        for code, cb in self.status_checkboxes.items():
            cb.setChecked(code in filters.get('statuses', []))
        
        file_id = filters.get('file_id')
        if file_id:
            for i in range(self.file_combo.count()):
                if self.file_combo.itemData(i) == file_id:
                    self.file_combo.setCurrentIndex(i)
                    break
        
        has_comment = filters.get('has_comment')
        if has_comment is not None:
            for i in range(self.comment_combo.count()):
                if self.comment_combo.itemData(i) == has_comment:
                    self.comment_combo.setCurrentIndex(i)
                    break
        
        for tag_id, cb in self.tag_checkboxes.items():
            cb.setChecked(tag_id in filters.get('tags', []))
        
        for code, cb in self.check_checkboxes.items():
            cb.setChecked(code in filters.get('checks', []))
        
        self.search_input.setText(filters.get('search_text', ''))