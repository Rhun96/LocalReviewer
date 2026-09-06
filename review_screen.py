from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTextEdit, QScrollArea, QGroupBox, QMessageBox, QFrame,
    QGridLayout, QSizePolicy, QMenu, QInputDialog, QStackedWidget,
    QTableWidget, QTableWidgetItem, QComboBox, QDialog, QCheckBox
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from database import get_db_connection
from datetime import datetime
from filter_dialog import FilterDialog
from filter_service import get_filtered_case_ids, get_all_case_ids
from autocheck_service import check_case, get_check_settings
from templates_service import get_comment_templates, add_comment_template, delete_comment_template, get_user_templates
from styles import STATUS_STYLES, apply_shadow
import json


class ColumnSelectDialog(QDialog):
    """Диалог выбора столбцов для таблицы."""
    def __init__(self, columns, selected_columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор столбцов")
        self.setMinimumWidth(400)
        self.columns = columns
        self.selected_columns = selected_columns
        self.checkboxes = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout()
        for col in self.columns:
            cb = QCheckBox(col)
            cb.setChecked(col in self.selected_columns)
            self.checkboxes[col] = cb
            content_layout.addWidget(cb)
        content.setLayout(content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        buttons = QHBoxLayout()
        btn_ok = QPushButton("✅ Применить")
        btn_ok.setMinimumHeight(35)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("❌ Отмена")
        btn_cancel.setObjectName("danger")
        btn_cancel.setMinimumHeight(35)
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_ok)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def get_selected_columns(self):
        return [col for col, cb in self.checkboxes.items() if cb.isChecked()]


class ReviewScreen(QWidget):
    """Экран ревью с переключением между кейсом и таблицей."""
    review_closed = Signal()

    def __init__(self, project_path: str, parent=None, filters=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self.filters = filters or {}
        self.settings = self.load_review_settings()
        self.current_case = None
        self.current_case_id = None
        self.current_file_mapping = {}  # Маппинг текущего файла
        self.case_ids = []
        self.current_index = 0
        self.selected_tags = set()
        self.tag_buttons = {}
        # Пагинация таблицы
        self.page_size = 50
        self.current_page = 0
        self.total_pages = 1
        # Выбранные столбцы для таблицы
        self.available_columns = []
        self.selected_columns = ['ID', 'Строка', 'Файл', 'Запрос', 'Статус']
        # Фильтр по значениям столбца
        self.column_filter = None
        self.value_filter = None
        # Теги раскрыты или нет
        self.tags_expanded = False
        self.load_case_ids()
        self.load_available_columns()
        self.init_ui()
        self.init_shortcuts()
        if self.case_ids:
            self.load_case(0)
        else:
            QMessageBox.warning(self, "Внимание", "Нет кейсов, соответствующих фильтрам")

    def load_review_settings(self) -> dict:
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            settings = {row['key']: row['value'] for row in cursor.fetchall()}
            conn.close()
            return {
                'auto_next_case': settings.get('auto_next_case', 'true') == 'true',
                'require_comment_for_bad': settings.get('require_comment_for_bad', 'warn'),
            }
        except:
            return {
                'auto_next_case': True,
                'require_comment_for_bad': 'warn',
            }

    def load_case_ids(self):
        if self.filters:
            self.case_ids = get_filtered_case_ids(self.project_path, self.filters)
        else:
            self.case_ids = get_all_case_ids(self.project_path)

    def load_available_columns(self):
        """Загружает доступные столбцы из метаданных."""
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT metadata_json FROM cases WHERE metadata_json IS NOT NULL LIMIT 100")
            rows = cursor.fetchall()
            conn.close()
            metadata_keys = set()
            for row in rows:
                if row['metadata_json']:
                    try:
                        metadata = json.loads(row['metadata_json'])
                        metadata_keys.update(metadata.keys())
                    except:
                        pass
            self.available_columns = [
                'ID', 'Строка', 'Файл', 'Запрос', 'Ответ', 'Статус', 'Комментарий'
            ] + sorted(list(metadata_keys))
        except:
            self.available_columns = ['ID', 'Строка', 'Файл', 'Запрос', 'Ответ', 'Статус', 'Комментарий']

    def load_file_mapping(self, file_id):
        """Загружает маппинг файла."""
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT mapping_json FROM files WHERE file_id = ?", (file_id,))
            row = cursor.fetchone()
            conn.close()
            if row and row['mapping_json']:
                return json.loads(row['mapping_json'])
            return {}
        except:
            return {}

    def init_shortcuts(self):
        QShortcut(QKeySequence("1"), self, activated=lambda: self.set_status('good'))
        QShortcut(QKeySequence("2"), self, activated=lambda: self.set_status('bad'))
        QShortcut(QKeySequence("3"), self, activated=lambda: self.set_status('uncertain'))
        QShortcut(QKeySequence("4"), self, activated=lambda: self.set_status('duplicate'))
        QShortcut(QKeySequence("5"), self, activated=lambda: self.set_status('skip'))
        QShortcut(QKeySequence("Right"), self, activated=self.next_case)
        QShortcut(QKeySequence("Left"), self, activated=self.prev_case)

    def init_ui(self):
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
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
        layout.setSpacing(8)
        layout.setContentsMargins(20, 10, 20, 10)

        # Заголовок
        self.header_label = QLabel("🔍 РЕЖИМ РЕВЬЮ")
        self.header_label.setObjectName("title")
        self.header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.header_label)

        # Информация о кейсе
        self.info_label = QLabel()
        self.info_label.setStyleSheet("font-size: 13px; color: #00AA2A; font-weight: bold;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Индикатор фильтров
        self.filter_indicator = QLabel()
        self.filter_indicator.setStyleSheet("font-size: 11px; color: #FFAA00;")
        self.filter_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.filter_indicator.setWordWrap(True)
        layout.addWidget(self.filter_indicator)
        self.update_filter_indicator()

        # Кнопка переключения вида
        self.btn_toggle_view = QPushButton("📋 Таблица")
        self.btn_toggle_view.setMinimumHeight(30)
        self.btn_toggle_view.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; padding: 6px 12px; }
            QPushButton:hover { background-color: #002233; }
        """)
        self.btn_toggle_view.clicked.connect(self.toggle_view)
        layout.addWidget(self.btn_toggle_view)

        # Стек видов
        self.view_stack = QStackedWidget()
        # Вид 1: Один кейс
        self.case_view = self.create_case_view()
        self.view_stack.addWidget(self.case_view)
        # Вид 2: Таблица
        self.table_view = self.create_table_view()
        self.view_stack.addWidget(self.table_view)
        layout.addWidget(self.view_stack)

        content_widget.setLayout(layout)
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        self.setLayout(main_layout)

    def create_case_view(self):
        """Создаёт вид одного кейса."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # === 1. Текст кейса ===
        case_group = QGroupBox("📝 Текст кейса")
        case_group_layout = QVBoxLayout()
        case_group_layout.setSpacing(8)
        text_scroll = QScrollArea()
        text_scroll.setWidgetResizable(True)
        text_scroll.setMinimumHeight(150)
        text_scroll.setStyleSheet("""
            QScrollArea {
                border: 2px solid #00441A;
                border-radius: 8px;
                background-color: #0A0F0A;
            }
        """)
        self.case_content = QWidget()
        self.case_layout = QVBoxLayout()
        self.case_layout.setSpacing(10)
        self.case_layout.setContentsMargins(12, 12, 12, 12)
        # Контент будет заполняться динамически в update_case_display
        self.case_layout.addStretch()
        self.case_content.setLayout(self.case_layout)
        text_scroll.setWidget(self.case_content)
        case_group_layout.addWidget(text_scroll)
        case_group.setLayout(case_group_layout)
        layout.addWidget(case_group)

        # === 2. Навигация (сразу после текста) ===
        nav_group = QGroupBox("🧭 Навигация")
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(6)
        btn_prev = QPushButton("⬅️ Пред.")
        btn_prev.setMinimumHeight(30)
        btn_prev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_prev.clicked.connect(self.prev_case)
        btn_filters = QPushButton("🎛️ Фильтры")
        btn_filters.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        btn_filters.setMinimumHeight(30)
        btn_filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_filters.clicked.connect(self.open_filters)
        btn_next = QPushButton("➡️ След.")
        btn_next.setMinimumHeight(30)
        btn_next.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_next.clicked.connect(self.next_case)
        btn_back = QPushButton("🚪 Назад")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(30)
        btn_back.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_back.clicked.connect(self.on_back)
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_filters)
        nav_layout.addWidget(btn_next)
        nav_layout.addWidget(btn_back)
        nav_group.setLayout(nav_layout)
        layout.addWidget(nav_group)

        # === 3. Автопроверки ===
        self.checks_group = QGroupBox("⚠️ Автопроверки")
        self.checks_label = QLabel("✅ Нет предупреждений")
        self.checks_label.setWordWrap(True)
        self.checks_label.setStyleSheet("color: #00AA2A; font-size: 11px;")
        checks_layout = QVBoxLayout()
        checks_layout.addWidget(self.checks_label)
        self.checks_group.setLayout(checks_layout)
        layout.addWidget(self.checks_group)

        # === 4. Статус ===
        status_group = QGroupBox("🎯 Статус")
        status_layout = QGridLayout()
        status_layout.setSpacing(6)
        self.btn_good = QPushButton("✅ Хорошо [1]")
        self.btn_good.setStyleSheet(STATUS_STYLES['good'])
        self.btn_good.setMinimumHeight(30)
        self.btn_good.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_good.clicked.connect(lambda: self.set_status('good'))
        self.btn_bad = QPushButton("❌ Плохо [2]")
        self.btn_bad.setStyleSheet(STATUS_STYLES['bad'])
        self.btn_bad.setMinimumHeight(30)
        self.btn_bad.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_bad.clicked.connect(lambda: self.set_status('bad'))
        self.btn_uncertain = QPushButton("❓ Сомневаюсь [3]")
        self.btn_uncertain.setStyleSheet(STATUS_STYLES['uncertain'])
        self.btn_uncertain.setMinimumHeight(30)
        self.btn_uncertain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_uncertain.clicked.connect(lambda: self.set_status('uncertain'))
        self.btn_duplicate = QPushButton("🔄 Дубль [4]")
        self.btn_duplicate.setStyleSheet(STATUS_STYLES['duplicate'])
        self.btn_duplicate.setMinimumHeight(30)
        self.btn_duplicate.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_duplicate.clicked.connect(lambda: self.set_status('duplicate'))
        self.btn_skip = QPushButton("⏭️ Пропустить [5]")
        self.btn_skip.setStyleSheet(STATUS_STYLES['skip'])
        self.btn_skip.setMinimumHeight(30)
        self.btn_skip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_skip.clicked.connect(lambda: self.set_status('skip'))
        status_layout.addWidget(self.btn_good, 0, 0)
        status_layout.addWidget(self.btn_bad, 0, 1)
        status_layout.addWidget(self.btn_uncertain, 0, 2)
        status_layout.addWidget(self.btn_duplicate, 1, 0)
        status_layout.addWidget(self.btn_skip, 1, 1)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # === 5. Комментарий ===
        comment_group = QGroupBox("💬 Комментарий")
        comment_layout = QVBoxLayout()
        comment_layout.setSpacing(6)
        templates_layout = QHBoxLayout()
        btn_templates = QPushButton("📋 Шаблоны")
        btn_templates.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_templates.setMinimumHeight(28)
        btn_templates.clicked.connect(self.show_templates_menu)
        btn_add_template = QPushButton("➕ Новый")
        btn_add_template.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_add_template.setMinimumHeight(28)
        btn_add_template.clicked.connect(self.add_new_template)
        btn_del_template = QPushButton("🗑️ Удалить")
        btn_del_template.setStyleSheet("""
            QPushButton { border-color: #FF3B3B; color: #FF3B3B; }
            QPushButton:hover { background-color: #330000; }
        """)
        btn_del_template.setMinimumHeight(28)
        btn_del_template.clicked.connect(self.delete_template)
        btn_save_comment = QPushButton("💾 Сохранить")
        btn_save_comment.setMinimumHeight(28)
        btn_save_comment.clicked.connect(self.save_comment)
        templates_layout.addWidget(btn_templates)
        templates_layout.addWidget(btn_add_template)
        templates_layout.addWidget(btn_del_template)
        templates_layout.addWidget(btn_save_comment)
        templates_layout.addStretch()
        comment_layout.addLayout(templates_layout)
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(60)
        comment_layout.addWidget(self.comment_edit)
        self.save_indicator = QLabel("")
        self.save_indicator.setStyleSheet("color: #00AA2A; font-size: 10px;")
        comment_layout.addWidget(self.save_indicator)
        comment_group.setLayout(comment_layout)
        layout.addWidget(comment_group)

        # === 6. Теги (раскрывающиеся) ===
        self.btn_toggle_tags = QPushButton("🏷️ Теги (нажмите для раскрытия)")
        self.btn_toggle_tags.setMinimumHeight(30)
        self.btn_toggle_tags.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        self.btn_toggle_tags.clicked.connect(self.toggle_tags)
        layout.addWidget(self.btn_toggle_tags)
        self.tags_group = QGroupBox("🏷️ Теги")
        self.tags_layout = QGridLayout()
        self.tags_layout.setSpacing(4)
        self.tags_group.setLayout(self.tags_layout)
        self.tags_group.setVisible(False)  # Скрыты по умолчанию
        layout.addWidget(self.tags_group)

        widget.setLayout(layout)
        return widget

    def create_table_view(self):
        """Создаёт табличный вид."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # Панель управления таблицей
        controls_layout = QHBoxLayout()
        self.btn_select_columns = QPushButton("📊 Столбцы")
        self.btn_select_columns.setMinimumHeight(30)
        self.btn_select_columns.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        self.btn_select_columns.clicked.connect(self.open_column_selector)
        self.column_filter_combo = QComboBox()
        self.column_filter_combo.addItem("Фильтр по столбцу...", None)
        self.column_filter_combo.setMinimumHeight(30)
        self.column_filter_combo.currentIndexChanged.connect(self.on_column_filter_changed)
        self.value_filter_combo = QComboBox()
        self.value_filter_combo.addItem("Все значения", None)
        self.value_filter_combo.setMinimumHeight(30)
        self.value_filter_combo.currentIndexChanged.connect(self.on_value_filter_changed)
        self.btn_table_filters = QPushButton("🎛️ Фильтры")
        self.btn_table_filters.setMinimumHeight(30)
        self.btn_table_filters.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        self.btn_table_filters.clicked.connect(self.open_table_filters)
        controls_layout.addWidget(self.btn_select_columns)
        controls_layout.addWidget(self.column_filter_combo)
        controls_layout.addWidget(self.value_filter_combo)
        controls_layout.addWidget(self.btn_table_filters)
        controls_layout.addStretch()
        layout.addLayout(controls_layout)
        self.update_column_filter_combo()

        # Таблица
        self.cases_table = QTableWidget()
        self.cases_table.setStyleSheet("""
            QTableWidget {
                background-color: #0D150D;
                border: 2px solid #00441A;
                border-radius: 8px;
                color: #00FF41;
                font-size: 11px;
                gridline-color: #00441A;
            }
            QTableWidget::item {
                padding: 6px;
            }
            QTableWidget::item:selected {
                background-color: #1A3A1A;
            }
            QHeaderView::section {
                background-color: #1A3A1A;
                color: #00FF41;
                border: 1px solid #007722;
                padding: 8px;
                font-weight: bold;
            }
        """)
        self.cases_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cases_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cases_table.doubleClicked.connect(self.on_table_double_click)
        layout.addWidget(self.cases_table)

        # Пагинация
        page_layout = QHBoxLayout()
        self.btn_prev_page = QPushButton("◀️ Пред.")
        self.btn_prev_page.setMinimumHeight(30)
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.page_label = QLabel("Страница 1 / 1")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next_page = QPushButton("➡️ След.")
        self.btn_next_page.setMinimumHeight(30)
        self.btn_next_page.clicked.connect(self.next_page)
        page_layout.addWidget(self.btn_prev_page)
        page_layout.addWidget(self.page_label)
        page_layout.addWidget(self.btn_next_page)
        layout.addLayout(page_layout)

        widget.setLayout(layout)
        return widget

    def toggle_tags(self):
        """Переключает видимость тегов."""
        self.tags_expanded = not self.tags_expanded
        if self.tags_expanded:
            self.tags_group.setVisible(True)
            self.btn_toggle_tags.setText("🏷️ Теги (нажмите для скрытия)")
        else:
            self.tags_group.setVisible(False)
            self.btn_toggle_tags.setText("🏷️ Теги (нажмите для раскрытия)")

    def update_column_filter_combo(self):
        """Обновляет список столбцов для фильтра."""
        if not hasattr(self, 'column_filter_combo'):
            return
        self.column_filter_combo.blockSignals(True)
        self.column_filter_combo.clear()
        self.column_filter_combo.addItem("Фильтр по столбцу...", None)
        for col in self.available_columns:
            self.column_filter_combo.addItem(col, col)
        self.column_filter_combo.blockSignals(False)

    def open_column_selector(self):
        """Открывает диалог выбора столбцов."""
        dialog = ColumnSelectDialog(self.available_columns, self.selected_columns, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.selected_columns = dialog.get_selected_columns()
            if not self.selected_columns:
                self.selected_columns = ['ID', 'Запрос', 'Статус']
            self.load_table_data()

    def on_column_filter_changed(self):
        """При изменении столбца для фильтра загружаем уникальные значения."""
        if not hasattr(self, 'value_filter_combo'):
            return
        column = self.column_filter_combo.currentData()
        self.value_filter_combo.blockSignals(True)
        self.value_filter_combo.clear()
        self.value_filter_combo.addItem("Все значения", None)
        if not column:
            self.column_filter = None
            self.value_filter = None
            self.value_filter_combo.blockSignals(False)
            return
        self.column_filter = column
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            if column in ['ID', 'Строка', 'Файл', 'Запрос', 'Ответ', 'Статус', 'Комментарий']:
                column_map = {
                    'ID': 'c.case_id',
                    'Строка': 'c.row_index + 1',
                    'Файл': 'f.file_name',
                    'Запрос': 'c.primary_text',
                    'Ответ': 'c.response_text',
                    'Статус': "COALESCE(a.status, 'unreviewed')",
                    'Комментарий': 'a.comment'
                }
                query = f"""
                    SELECT DISTINCT {column_map[column]} as value
                    FROM cases c
                    JOIN files f ON c.file_id = f.file_id
                    LEFT JOIN annotations a ON c.case_id = a.case_id
                    WHERE {column_map[column]} IS NOT NULL
                    ORDER BY value
                    LIMIT 100
                """
                cursor.execute(query)
                values = [row['value'] for row in cursor.fetchall()]
            else:
                cursor.execute("SELECT metadata_json FROM cases WHERE metadata_json IS NOT NULL")
                rows = cursor.fetchall()
                values = set()
                for row in rows:
                    try:
                        metadata = json.loads(row['metadata_json'])
                        if column in metadata and metadata[column]:
                            values.add(str(metadata[column]))
                    except:
                        pass
                values = sorted(list(values))[:100]
            conn.close()
            for value in values:
                self.value_filter_combo.addItem(str(value), str(value))
        except:
            pass
        self.value_filter_combo.blockSignals(False)

    def on_value_filter_changed(self):
        """При изменении значения фильтра перезагружаем таблицу."""
        if not hasattr(self, 'value_filter_combo'):
            return
        self.value_filter = self.value_filter_combo.currentData()
        self.current_page = 0
        self.load_table_data()

    def toggle_view(self):
        """Переключает между видом кейса и таблицей."""
        if self.view_stack.currentIndex() == 0:
            self.view_stack.setCurrentIndex(1)
            self.btn_toggle_view.setText("📝 Кейс")
            self.load_table_data()
        else:
            self.view_stack.setCurrentIndex(0)
            self.btn_toggle_view.setText("📋 Таблица")

    def load_table_data(self):
        """Загружает данные в таблицу."""
        if not hasattr(self, 'cases_table'):
            return
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            count_query = """
                SELECT COUNT(*) as total
                FROM cases c
                JOIN files f ON c.file_id = f.file_id
                LEFT JOIN annotations a ON c.case_id = a.case_id
            """
            conditions = []
            params = []
            if self.filters:
                statuses = self.filters.get('statuses', [])
                if statuses:
                    placeholders = ','.join(['?' for _ in statuses])
                    conditions.append(f"COALESCE(a.status, 'unreviewed') IN ({placeholders})")
                    params.extend(statuses)
                file_id = self.filters.get('file_id')
                if file_id:
                    conditions.append("c.file_id = ?")
                    params.append(file_id)
                search_text = self.filters.get('search_text', '')
                if search_text:
                    conditions.append("(c.primary_text LIKE ? OR c.response_text LIKE ?)")
                    search_param = f"%{search_text}%"
                    params.extend([search_param, search_param])
            if self.column_filter and self.value_filter:
                if self.column_filter in ['ID', 'Строка', 'Файл', 'Запрос', 'Ответ', 'Статус', 'Комментарий']:
                    column_map = {
                        'ID': 'c.case_id',
                        'Строка': 'c.row_index + 1',
                        'Файл': 'f.file_name',
                        'Запрос': 'c.primary_text',
                        'Ответ': 'c.response_text',
                        'Статус': "COALESCE(a.status, 'unreviewed')",
                        'Комментарий': 'a.comment'
                    }
                    conditions.append(f"CAST({column_map[self.column_filter]} AS TEXT) = ?")
                    params.append(self.value_filter)
            if conditions:
                count_query += " WHERE " + " AND ".join(conditions)
            cursor.execute(count_query, params)
            total = cursor.fetchone()['total']
            self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
            self.current_page = min(self.current_page, self.total_pages - 1)
            offset = self.current_page * self.page_size
            data_query = """
                SELECT c.case_id, c.row_index + 1 as row_num, f.file_name,
                       c.primary_text, c.response_text,
                       COALESCE(a.status, 'unreviewed') as status,
                       a.comment, c.metadata_json
                FROM cases c
                JOIN files f ON c.file_id = f.file_id
                LEFT JOIN annotations a ON c.case_id = a.case_id
            """
            if conditions:
                data_query += " WHERE " + " AND ".join(conditions)
            data_query += f" ORDER BY f.imported_at, c.row_index LIMIT {self.page_size} OFFSET {offset}"
            cursor.execute(data_query, params)
            cases = cursor.fetchall()
            conn.close()
            if self.column_filter and self.value_filter and self.column_filter not in ['ID', 'Строка', 'Файл', 'Запрос', 'Ответ', 'Статус', 'Комментарий']:
                filtered_cases = []
                for case in cases:
                    if case['metadata_json']:
                        try:
                            metadata = json.loads(case['metadata_json'])
                            if str(metadata.get(self.column_filter, '')) == self.value_filter:
                                filtered_cases.append(case)
                        except:
                            pass
                cases = filtered_cases
            self.cases_table.clear()
            self.cases_table.setColumnCount(len(self.selected_columns))
            self.cases_table.setRowCount(len(cases))
            self.cases_table.setHorizontalHeaderLabels(self.selected_columns)
            status_names = {
                'unreviewed': '⬜ Не проверено',
                'good': '✅ Хорошо',
                'bad': '❌ Плохо',
                'uncertain': '❓ Сомневаюсь',
                'duplicate': '🔄 Дубль',
                'skip': '⏭️ Пропустить'
            }
            for row, case in enumerate(cases):
                metadata = {}
                if case['metadata_json']:
                    try:
                        metadata = json.loads(case['metadata_json'])
                    except:
                        pass
                for col_idx, col_name in enumerate(self.selected_columns):
                    if col_name == 'ID':
                        value = str(case['case_id'])
                    elif col_name == 'Строка':
                        value = str(case['row_num'])
                    elif col_name == 'Файл':
                        value = case['file_name']
                    elif col_name == 'Запрос':
                        value = (case['primary_text'] or '')[:100]
                    elif col_name == 'Ответ':
                        value = (case['response_text'] or '')[:100]
                    elif col_name == 'Статус':
                        value = status_names.get(case['status'], case['status'])
                    elif col_name == 'Комментарий':
                        value = (case['comment'] or '')[:100]
                    else:
                        value = str(metadata.get(col_name, ''))[:100]
                    self.cases_table.setItem(row, col_idx, QTableWidgetItem(value))
            self.cases_table.resizeColumnsToContents()
            self.page_label.setText(f"Страница {self.current_page + 1} / {self.total_pages} (всего: {total})")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить таблицу: {str(e)}")

    def prev_page(self):
        if self.current_page > 0:
            self.current_page -= 1
            self.load_table_data()

    def next_page(self):
        if self.current_page < self.total_pages - 1:
            self.current_page += 1
            self.load_table_data()

    def on_table_double_click(self, index):
        row = index.row()
        case_id_item = self.cases_table.item(row, 0)
        if case_id_item:
            try:
                case_id = int(case_id_item.text())
                if case_id in self.case_ids:
                    idx = self.case_ids.index(case_id)
                    self.view_stack.setCurrentIndex(0)
                    self.btn_toggle_view.setText("📋 Таблица")
                    self.load_case(idx)
            except:
                pass

    def open_table_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            self.filters = new_filters
            self.current_page = 0
            self.load_table_data()
            self.update_filter_indicator()

    def run_autochecks_for_case(self):
        if not self.current_case:
            self.checks_label.setText("✅ Нет предупреждений")
            return
        settings = get_check_settings(self.project_path)
        checks = check_case(self.current_case, settings)
        if not checks:
            self.checks_label.setText("✅ Нет предупреждений")
            self.checks_label.setStyleSheet("color: #00AA2A; font-size: 11px;")
        else:
            lines = [f"⚠️ {c[1]}: {c[2]}" for c in checks]
            self.checks_label.setText("\n".join(lines))
            self.checks_label.setStyleSheet("color: #FFAA00; font-size: 11px;")

    def show_templates_menu(self):
        templates = get_comment_templates(self.project_path)
        if not templates:
            QMessageBox.information(self, "Шаблоны", "Нет доступных шаблонов")
            return
        menu = QMenu(self)
        for template in templates:
            action = menu.addAction(template['text'])
            action.triggered.connect(
                lambda checked, t=template['text']: self.insert_template(t)
            )
        menu.exec(self.mapToGlobal(self.btn_good.pos()))

    def insert_template(self, text: str):
        current = self.comment_edit.toPlainText()
        if current:
            self.comment_edit.setPlainText(current + "\n" + text)
        else:
            self.comment_edit.setPlainText(text)

    def add_new_template(self):
        text, ok = QInputDialog.getText(
            self,
            "Новый шаблон",
            "Введите текст шаблона комментария:"
        )
        if ok and text.strip():
            if add_comment_template(self.project_path, text.strip()):
                QMessageBox.information(self, "Шаблон добавлен", f"✅ Шаблон «{text.strip()}» добавлен")
            else:
                QMessageBox.warning(self, "Ошибка", "Не удалось добавить шаблон")

    def delete_template(self):
        """Удаляет пользовательский шаблон."""
        user_templates = get_user_templates(self.project_path)
        if not user_templates:
            QMessageBox.information(self, "Удаление", "Нет пользовательских шаблонов для удаления")
            return
        names = [t['text'] for t in user_templates]
        text, ok = QInputDialog.getItem(
            self,
            "Удалить шаблон",
            "Выберите шаблон для удаления:",
            names,
            0,
            False
        )
        if ok and text:
            tpl = next((t for t in user_templates if t['text'] == text), None)
            if tpl:
                if delete_comment_template(self.project_path, tpl['template_id']):
                    QMessageBox.information(self, "Удаление", f"✅ Шаблон «{text}» удалён")
                else:
                    QMessageBox.warning(self, "Ошибка", "Не удалось удалить шаблон")

    def update_filter_indicator(self):
        if not self.filters:
            self.filter_indicator.setText("Фильтры не применены")
            return
        parts = []
        if self.filters.get('statuses'):
            parts.append(f"статусы: {', '.join(self.filters['statuses'])}")
        if self.filters.get('file_id'):
            parts.append("фильтр по файлу")
        if self.filters.get('has_comment') is not None:
            parts.append("фильтр по комментарию")
        if self.filters.get('tags'):
            parts.append(f"тегов: {len(self.filters['tags'])}")
        if self.filters.get('checks'):
            parts.append(f"автопроверок: {len(self.filters['checks'])}")
        if self.filters.get('search_text'):
            parts.append(f"поиск: '{self.filters['search_text']}'")
        if parts:
            self.filter_indicator.setText("⚠️ Фильтры: " + " | ".join(parts))
        else:
            self.filter_indicator.setText("Фильтры не применены")

    def open_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            filtered_ids = get_filtered_case_ids(self.project_path, new_filters)
            if not filtered_ids:
                QMessageBox.warning(
                    self,
                    "Внимание",
                    "Нет кейсов, соответствующих выбранным фильтрам.\nФильтры не будут применены."
                )
                return
            self.filters = new_filters
            self.case_ids = filtered_ids
            self.current_index = 0
            self.update_filter_indicator()
            if self.case_ids:
                self.load_case(0)

    def load_case(self, index: int):
        if index < 0 or index >= len(self.case_ids):
            return
        if self.current_case_id:
            self.save_comment(silent=True)
        self.current_index = index
        self.current_case_id = self.case_ids[index]
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT c.*, f.file_name, f.file_id, a.status, a.comment
                FROM cases c
                JOIN files f ON c.file_id = f.file_id
                LEFT JOIN annotations a ON c.case_id = a.case_id
                WHERE c.case_id = ?
            """, (self.current_case_id,))
            row = cursor.fetchone()
            if not row:
                return
            self.current_case = dict(row)

            # Загружаем маппинг файла
            self.current_file_mapping = self.load_file_mapping(row['file_id'])

            cursor.execute("""
                SELECT t.tag_id, t.tag_name, t.tag_code
                FROM tags t
                JOIN case_tags ct ON t.tag_id = ct.tag_id
                WHERE ct.case_id = ?
            """, (self.current_case_id,))
            case_tags = {row['tag_id'] for row in cursor.fetchall()}
            conn.close()
            self.update_case_display()
            self.update_tags_display(case_tags)
            self.update_info_label()
            self.run_autochecks_for_case()
            self.comment_edit.setPlainText(self.current_case.get('comment') or '')
            self.save_indicator.setText("")
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось загрузить кейс: {str(e)}")

    def update_case_display(self):
        """Обновляет отображение текста кейса с реальными названиями колонок из маппинга."""
        if not self.current_case:
            return

        # Очищаем старый контент
        while self.case_layout.count():
            item = self.case_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # Парсим сырые данные
        raw_data = {}
        if self.current_case.get('raw_json'):
            try:
                raw_data = json.loads(self.current_case['raw_json'])
            except:
                pass

        # Находим колонки по ролям из маппинга
        mapping = self.current_file_mapping
        primary_cols = [col for col, role in mapping.items() if role == 'primary_text']
        response_cols = [col for col, role in mapping.items() if role == 'response_text']

        # Отображаем запрос с реальными названиями колонок
        if primary_cols:
            for col_name in primary_cols:
                label = QLabel(f"📌 {col_name}:")
                label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
                self.case_layout.addWidget(label)
                text = raw_data.get(col_name, '') or '(пусто)'
                text_label = QLabel(str(text))
                text_label.setWordWrap(True)
                text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                text_label.setStyleSheet("font-size: 14px; padding: 6px;")
                self.case_layout.addWidget(text_label)
        else:
            # Fallback: если маппинга нет, показываем стандартно
            label = QLabel("📌 Запрос:")
            label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
            self.case_layout.addWidget(label)
            text_label = QLabel(self.current_case.get('primary_text') or '(пусто)')
            text_label.setWordWrap(True)
            text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            text_label.setStyleSheet("font-size: 14px; padding: 6px;")
            self.case_layout.addWidget(text_label)

        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("color: #00441A; max-height: 2px;")
        self.case_layout.addWidget(line)

        # Отображаем ответ с реальными названиями колонок
        if response_cols:
            for col_name in response_cols:
                label = QLabel(f"💬 {col_name}:")
                label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
                self.case_layout.addWidget(label)
                text = raw_data.get(col_name, '') or '(пусто)'
                text_label = QLabel(str(text))
                text_label.setWordWrap(True)
                text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                text_label.setStyleSheet("font-size: 14px; padding: 6px;")
                self.case_layout.addWidget(text_label)
        else:
            # Fallback: если маппинга нет, показываем стандартно
            response = self.current_case.get('response_text')
            if response:
                label = QLabel("💬 Ответ:")
                label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
                self.case_layout.addWidget(label)
                text_label = QLabel(response)
                text_label.setWordWrap(True)
                text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                text_label.setStyleSheet("font-size: 14px; padding: 6px;")
                self.case_layout.addWidget(text_label)

        self.case_layout.addStretch()

    def update_info_label(self):
        if not self.current_case:
            return
        status_map = {
            'unreviewed': '⬜ Не проверено',
            'good': '✅ Хорошо',
            'bad': '❌ Плохо',
            'uncertain': '❓ Сомневаюсь',
            'duplicate': '🔄 Дубль',
            'skip': '⏭️ Пропустить'
        }
        status = status_map.get(self.current_case.get('status'), '⬜ Не проверено')
        self.info_label.setText(
            f"📋 Кейс {self.current_index + 1} / {len(self.case_ids)} | "
            f"📄 {self.current_case.get('file_name')} | "
            f"{status}"
        )

    def update_tags_display(self, selected_tag_ids: set):
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.selected_tags = selected_tag_ids.copy()
        self.tag_buttons.clear()
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT tag_id, tag_name, tag_code FROM tags ORDER BY tag_name")
            all_tags = cursor.fetchall()
            conn.close()
            columns = 5
            row, col = 0, 0
            for tag in all_tags:
                tag_id = tag['tag_id']
                is_selected = tag_id in selected_tag_ids
                btn = QPushButton(tag['tag_name'])
                btn.setCheckable(True)
                btn.setChecked(is_selected)
                btn.setMinimumHeight(25)
                if is_selected:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #00FF41;
                            color: #000000;
                            border-color: #00FF41;
                            padding: 4px 8px;
                            border-radius: 4px;
                            font-weight: bold;
                            font-size: 11px;
                        }
                    """)
                else:
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #0D150D;
                            color: #00FF41;
                            border-color: #007722;
                            padding: 4px 8px;
                            border-radius: 4px;
                            font-size: 11px;
                        }
                        QPushButton:hover {
                            background-color: #0F2010;
                            border-color: #00FF41;
                        }
                        QPushButton:checked {
                            background-color: #00FF41;
                            color: #000000;
                        }
                    """)
                btn.clicked.connect(lambda checked, tid=tag_id: self.toggle_tag(tid))
                self.tags_layout.addWidget(btn, row, col)
                self.tag_buttons[tag_id] = btn
                col += 1
                if col >= columns:
                    col = 0
                    row += 1
        except:
            pass

    def toggle_tag(self, tag_id: int):
        if tag_id in self.selected_tags:
            self.selected_tags.remove(tag_id)
        else:
            self.selected_tags.add(tag_id)
        self.save_tags()
        if tag_id in self.tag_buttons:
            btn = self.tag_buttons[tag_id]
            if tag_id in self.selected_tags:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #00FF41;
                        color: #000000;
                        border-color: #00FF41;
                        padding: 4px 8px;
                        border-radius: 4px;
                        font-weight: bold;
                        font-size: 11px;
                    }
                """)
            else:
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #0D150D;
                        color: #00FF41;
                        border-color: #007722;
                        padding: 4px 8px;
                        border-radius: 4px;
                        font-size: 11px;
                    }
                    QPushButton:hover {
                        background-color: #0F2010;
                        border-color: #00FF41;
                    }
                """)

    def save_tags(self):
        if not self.current_case_id:
            return
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("DELETE FROM case_tags WHERE case_id = ?", (self.current_case_id,))
            now = datetime.now().isoformat()
            for tag_id in self.selected_tags:
                cursor.execute("""
                    INSERT INTO case_tags (case_id, tag_id, created_at)
                    VALUES (?, ?, ?)
                """, (self.current_case_id, tag_id, now))
            conn.commit()
            conn.close()
        except:
            pass

    def save_comment(self, silent=False):
        if not self.current_case_id:
            return
        try:
            comment = self.comment_edit.toPlainText().strip()
            now = datetime.now().isoformat()
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO annotations (case_id, status, comment, updated_at)
                VALUES (?, 'unreviewed', ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    comment = ?,
                    updated_at = ?
            """, (
                self.current_case_id, comment or None, now,
                comment or None, now
            ))
            conn.commit()
            conn.close()
            if not silent:
                self.save_indicator.setText(f"💾 Комментарий сохранён ({now[:19]})")
        except Exception as e:
            if not silent:
                QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить комментарий: {str(e)}")

    def set_status(self, status: str):
        if not self.current_case_id:
            return
        comment = self.comment_edit.toPlainText().strip()
        if status == 'bad':
            comment_mode = self.settings.get('require_comment_for_bad', 'warn')
            if comment_mode == 'required' and not comment:
                QMessageBox.warning(
                    self,
                    "Требуется комментарий",
                    "Для статуса «Плохо» необходимо добавить комментарий."
                )
                return
            elif comment_mode == 'warn' and not comment:
                reply = QMessageBox.question(
                    self,
                    "Рекомендация",
                    "Для статуса «Плохо» рекомендуется добавить комментарий.\n\nПродолжить без комментария?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        try:
            now = datetime.now().isoformat()
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute(
                "SELECT status FROM annotations WHERE case_id = ?",
                (self.current_case_id,)
            )
            old_row = cursor.fetchone()
            old_status = old_row['status'] if old_row else 'unreviewed'
            cursor.execute("""
                INSERT INTO annotations (case_id, status, comment, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(case_id) DO UPDATE SET
                    status = ?,
                    comment = ?,
                    updated_at = ?
            """, (
                self.current_case_id, status, comment or None, now,
                status, comment or None, now
            ))
            if old_status != status:
                cursor.execute("""
                    INSERT INTO history (case_id, event_type, field_name, old_value, new_value, created_at)
                    VALUES (?, 'status_changed', 'status', ?, ?, ?)
                """, (self.current_case_id, old_status, status, now))
            conn.commit()
            conn.close()
            self.current_case['status'] = status
            self.current_case['comment'] = comment or None
            self.update_info_label()
            self.save_indicator.setText(f"💾 Статус сохранён: {status}")
            if self.settings.get('auto_next_case', True):
                self.next_case()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить статус: {str(e)}")

    def next_case(self):
        if self.current_index < len(self.case_ids) - 1:
            self.load_case(self.current_index + 1)
        else:
            QMessageBox.information(self, "Конец", "🎉 Это последний кейс в выборке")

    def prev_case(self):
        if self.current_index > 0:
            self.load_case(self.current_index - 1)
        else:
            QMessageBox.information(self, "Начало", "📍 Это первый кейс в выборке")

    def on_back(self):
        if self.current_case_id:
            self.save_comment(silent=True)
        self.review_closed.emit()