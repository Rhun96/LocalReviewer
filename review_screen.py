from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QGroupBox, QFrame,
    QGridLayout, QSizePolicy, QMenu, QInputDialog, QStackedWidget,
    QTableWidget, QTableWidgetItem, QComboBox, QDialog, QAbstractItemView,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication
from constants import COLUMN_TO_SQL, STATUS_NAMES, TABLE_SYSTEM_COLUMNS
from database import db
from datetime import datetime, UTC
from filter_dialog import FilterDialog
from filter_service import get_filtered_case_ids, get_all_case_ids
from autocheck_service import check_case, get_check_settings
from templates_service import (
    add_comment_template, delete_comment_template, get_comment_templates,
    get_user_templates,
)
from styles import STATUS_STYLES
from ui_base import BaseScreen
from ui_compat import (
    FLUENT, FCheckBox, FComboBox, FPushButton, FTable, clear_in_fluent,
    confirm, notify,
)
import json
import logging

logger = logging.getLogger(__name__)


class ReviewScreen(BaseScreen):
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
        # Массовые операции (ТЗ §5): выбранные кейсы
        self.bulk_selected: set = set()
        # Умная очередь (ТЗ §8): normal | unreviewed | problematic
        self.queue_mode = "normal"
        self.load_case_ids()
        self.load_available_columns()
        self.init_ui()
        self.init_shortcuts()
        self._pending_empty_warning = not bool(self.case_ids)
        if self.case_ids:
            self.load_case(0)

    def showEvent(self, event):
        super().showEvent(event)
        if getattr(self, "_pending_empty_warning", False):
            self._pending_empty_warning = False
            notify(self, "warning", "Внимание", "Нет кейсов, соответствующих фильтрам")

    def refresh(self):
        """Перезагрузка при возврате на экран (требуется сайдбару)."""
        self.settings = self.load_review_settings()
        self.load_case_ids()
        self.load_available_columns()
        self.update_column_filter_combo()
        if self.case_ids:
            self.current_index = min(self.current_index, len(self.case_ids) - 1)
            self.load_case(self.current_index)
        self.update_filter_indicator()
        self.update_queue_indicator()

    def load_review_settings(self) -> dict:
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM settings")
                settings = {row['key']: row['value'] for row in cursor.fetchall()}
            return {
                'auto_next_case': settings.get('auto_next_case', 'true') == 'true',
                'require_comment_for_bad': settings.get('require_comment_for_bad', 'warn'),
            }
        except Exception as e:
            logger.warning("review settings fallback: %s", e)
            return {
                'auto_next_case': True,
                'require_comment_for_bad': 'warn',
            }

    def load_case_ids(self):
        if self.queue_mode and self.queue_mode != "normal":
            try:
                from review_queue_service import build_queue
                self.case_ids, _reasons = build_queue(
                    self.project_path, mode=self.queue_mode, filters=self.filters or None)
                return
            except Exception as e:
                logger.warning("queue fallback to plain filter: %s", e)
        if self.filters:
            self.case_ids = get_filtered_case_ids(self.project_path, self.filters)
        else:
            self.case_ids = get_all_case_ids(self.project_path)

    def load_available_columns(self):
        """Загружает доступные столбцы из метаданных."""
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT metadata_json FROM cases "
                               "WHERE metadata_json IS NOT NULL LIMIT 100")
                rows = cursor.fetchall()
            metadata_keys = set()
            for row in rows:
                if row['metadata_json']:
                    try:
                        metadata = json.loads(row['metadata_json'])
                        metadata_keys.update(metadata.keys())
                    except (ValueError, TypeError):
                        continue
            self.available_columns = TABLE_SYSTEM_COLUMNS + sorted(metadata_keys)
        except Exception as e:
            logger.warning("available columns fallback: %s", e)
            self.available_columns = list(TABLE_SYSTEM_COLUMNS)

    def load_file_mapping(self, file_id):
        """Загружает маппинг файла."""
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT mapping_json FROM files WHERE file_id = ?", (file_id,))
                row = cursor.fetchone()
            if row and row['mapping_json']:
                return json.loads(row['mapping_json'])
            return {}
        except Exception as e:
            logger.warning("file mapping fallback: %s", e)
            return {}

    def _shortcuts_allowed(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is None:
            return True
        # Не перехватываем цифры/стрелки при вводе текста или выборе в комбо
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QSpinBox
        return not isinstance(focus, (QLineEdit, QTextEdit, QComboBox, QSpinBox))

    def init_shortcuts(self):
        def guarded(fn):
            return lambda: fn() if self._shortcuts_allowed() else None
        for key, status in (("1", "good"), ("2", "bad"), ("3", "uncertain"),
                            ("4", "duplicate"), ("5", "skip")):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(guarded(lambda s=status: self.set_status(s)))
        for key, fn in (("Right", self.next_case), ("Left", self.prev_case)):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(guarded(fn))

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
        self.btn_toggle_view = FPushButton("📋 Таблица")
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
        clear_in_fluent(scroll)
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
        clear_in_fluent(text_scroll)
        case_group.setLayout(case_group_layout)
        layout.addWidget(case_group)

        # === 2. Навигация (сразу после текста) ===
        nav_group = QGroupBox("🧭 Навигация")
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(6)
        btn_prev = FPushButton("⬅️ Пред.")
        btn_prev.setMinimumHeight(30)
        btn_prev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_prev.clicked.connect(self.prev_case)
        btn_filters = FPushButton("🎛️ Фильтры")
        btn_filters.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        btn_filters.setMinimumHeight(30)
        btn_filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_filters.clicked.connect(self.open_filters)
        btn_next = FPushButton("➡️ След.")
        btn_next.setMinimumHeight(30)
        btn_next.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_next.clicked.connect(self.next_case)
        btn_back = FPushButton("🚪 Назад")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(30)
        btn_back.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_back.clicked.connect(self.on_back)
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_filters)
        nav_layout.addWidget(btn_next)
        nav_layout.addWidget(btn_back)
        for _i in range(4):
            nav_layout.setStretch(_i, 1)
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
        self.btn_good = FPushButton("✅ Хорошо [1]")
        self.btn_good.setStyleSheet(STATUS_STYLES['good'])
        self.btn_good.setMinimumHeight(30)
        self.btn_good.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_good.clicked.connect(lambda: self.set_status('good'))
        self.btn_bad = FPushButton("❌ Плохо [2]")
        self.btn_bad.setStyleSheet(STATUS_STYLES['bad'])
        self.btn_bad.setMinimumHeight(30)
        self.btn_bad.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_bad.clicked.connect(lambda: self.set_status('bad'))
        self.btn_uncertain = FPushButton("❓ Сомневаюсь [3]")
        self.btn_uncertain.setStyleSheet(STATUS_STYLES['uncertain'])
        self.btn_uncertain.setMinimumHeight(30)
        self.btn_uncertain.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_uncertain.clicked.connect(lambda: self.set_status('uncertain'))
        self.btn_duplicate = FPushButton("🔄 Дубль [4]")
        self.btn_duplicate.setStyleSheet(STATUS_STYLES['duplicate'])
        self.btn_duplicate.setMinimumHeight(30)
        self.btn_duplicate.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_duplicate.clicked.connect(lambda: self.set_status('duplicate'))
        self.btn_skip = FPushButton("⏭️ Пропустить [5]")
        self.btn_skip.setStyleSheet(STATUS_STYLES['skip'])
        self.btn_skip.setMinimumHeight(30)
        self.btn_skip.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_skip.clicked.connect(lambda: self.set_status('skip'))
        status_layout.addWidget(self.btn_good, 0, 0)
        status_layout.addWidget(self.btn_bad, 0, 1)
        status_layout.addWidget(self.btn_uncertain, 0, 2)
        status_layout.addWidget(self.btn_duplicate, 1, 0)
        status_layout.addWidget(self.btn_skip, 1, 1)
        # Равномерные колонки: в узком окне кнопки сжимаются одинаково,
        # текст остаётся по центру и не «съезжает»
        for _c in range(3):
            status_layout.setColumnStretch(_c, 1)
        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # === 5. Комментарий ===
        comment_group = QGroupBox("💬 Комментарий")
        comment_layout = QVBoxLayout()
        comment_layout.setSpacing(6)
        templates_layout = QHBoxLayout()
        btn_templates = FPushButton("📋 Шаблоны")
        self.btn_templates = btn_templates
        btn_templates.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_templates.setMinimumHeight(28)
        btn_templates.clicked.connect(self.show_templates_menu)
        btn_add_template = FPushButton("➕ Новый")
        btn_add_template.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_add_template.setMinimumHeight(28)
        btn_add_template.clicked.connect(self.add_new_template)
        btn_del_template = FPushButton("🗑️ Удалить")
        btn_del_template.setStyleSheet("""
            QPushButton { border-color: #FF3B3B; color: #FF3B3B; }
            QPushButton:hover { background-color: #330000; }
        """)
        btn_del_template.setMinimumHeight(28)
        btn_del_template.clicked.connect(self.delete_template)
        btn_save_comment = FPushButton("💾 Сохранить")
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
        self.btn_toggle_tags = FPushButton("🏷️ Теги (нажмите для раскрытия)")
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
        self.btn_select_columns = FPushButton("📊 Столбцы")
        self.btn_select_columns.setMinimumHeight(30)
        self.btn_select_columns.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        self.btn_select_columns.clicked.connect(self.open_column_selector)
        self.column_filter_combo = FComboBox()
        self.column_filter_combo.addItem("Фильтр по столбцу...", None)
        self.column_filter_combo.setMinimumHeight(30)
        self.column_filter_combo.currentIndexChanged.connect(self.on_column_filter_changed)
        self.value_filter_combo = FComboBox()
        self.value_filter_combo.addItem("Все значения", None)
        self.value_filter_combo.setMinimumHeight(30)
        self.value_filter_combo.currentIndexChanged.connect(self.on_value_filter_changed)
        self.btn_table_filters = FPushButton("🎛️ Фильтры")
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

        # Панель массовых операций (ТЗ §5-7)
        bulk_layout = QHBoxLayout()
        self.bulk_label = QLabel("Выбрано: 0")
        self.bulk_label.setStyleSheet("font-size: 12px; font-weight: bold;")
        btn_bulk_all = FPushButton("☑ Выбрать все по фильтру")
        btn_bulk_all.setMinimumHeight(30)
        btn_bulk_all.clicked.connect(self.on_bulk_select_all)
        btn_bulk_clear = FPushButton("☐ Снять выбор")
        btn_bulk_clear.setMinimumHeight(30)
        btn_bulk_clear.clicked.connect(self.on_bulk_clear)
        btn_bulk_run = FPushButton("⚡ Массовое действие…")
        btn_bulk_run.setMinimumHeight(30)
        btn_bulk_run.clicked.connect(self.on_bulk_run)
        btn_bulk_undo = FPushButton("↩ Отменить последнюю")
        btn_bulk_undo.setMinimumHeight(30)
        btn_bulk_undo.clicked.connect(self.on_bulk_undo)
        btn_recheck = FPushButton("🔄 Пересчитать проверки")
        btn_recheck.setMinimumHeight(30)
        btn_recheck.setToolTip("Записать автопроверки в БД: нужно для фильтров "
                               "по проверкам и проблемной очереди")
        btn_recheck.clicked.connect(self.on_recheck_all)
        self.queue_combo = FComboBox()
        self.queue_combo.addItem("Очередь: обычная", "normal")
        self.queue_combo.addItem("Очередь: непроверенные", "unreviewed")
        self.queue_combo.addItem("Очередь: проблемные", "problematic")
        self.queue_combo.currentIndexChanged.connect(self.on_queue_changed)
        bulk_layout.addWidget(self.bulk_label)
        bulk_layout.addWidget(btn_bulk_all)
        bulk_layout.addWidget(btn_bulk_clear)
        bulk_layout.addWidget(btn_bulk_run)
        bulk_layout.addWidget(btn_bulk_undo)
        bulk_layout.addWidget(btn_recheck)
        bulk_layout.addWidget(self.queue_combo)
        bulk_layout.addStretch()
        layout.addLayout(bulk_layout)

        # Таблица
        self.cases_table = FTable()
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
        # Горизонтальный ползунок всегда виден: в узком окне колонки
        # Статус/⚠ не пропадают, а уходят вправо за скролл
        self.cases_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self.cases_table.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.cases_table.doubleClicked.connect(self.on_table_double_click)
        layout.addWidget(self.cases_table)
        clear_in_fluent(self.cases_table)

        # Пагинация
        page_layout = QHBoxLayout()
        self.btn_prev_page = FPushButton("◀️ Пред.")
        self.btn_prev_page.setMinimumHeight(30)
        self.btn_prev_page.clicked.connect(self.prev_page)
        self.page_label = QLabel("Страница 1 / 1")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.btn_next_page = FPushButton("➡️ След.")
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
        from column_select_dialog import ColumnSelectDialog
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
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                if column in TABLE_SYSTEM_COLUMNS:
                    col_sql = COLUMN_TO_SQL[column]
                    query = f"""
                        SELECT DISTINCT {col_sql} as value
                        FROM cases c
                        JOIN files f ON c.file_id = f.file_id
                        LEFT JOIN annotations a ON c.case_id = a.case_id
                        WHERE {col_sql} IS NOT NULL
                        ORDER BY value
                        LIMIT 100
                    """
                    cursor.execute(query)
                    values = [row['value'] for row in cursor.fetchall()]
                else:
                    cursor.execute("SELECT metadata_json FROM cases "
                                   "WHERE metadata_json IS NOT NULL LIMIT 2000")
                    rows = cursor.fetchall()
                    values = set()
                    for row in rows:
                        try:
                            metadata = json.loads(row['metadata_json'])
                            if column in metadata and metadata[column]:
                                values.add(str(metadata[column]))
                        except (ValueError, TypeError):
                            continue
                    values = sorted(values)[:100]
            for value in values:
                self.value_filter_combo.addItem(str(value), str(value))
        except Exception as e:
            logger.warning("column filter values failed: %s", e)
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
            from filter_service import filter_from, BASE_FROM
            _joins, conditions, params = filter_from(self.filters)
            params = list(params)
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                count_query = "SELECT COUNT(DISTINCT c.case_id) as total " + BASE_FROM
                if self.column_filter and self.value_filter:
                    if self.column_filter in TABLE_SYSTEM_COLUMNS:
                        conditions = list(conditions) + [
                            f"CAST({COLUMN_TO_SQL[self.column_filter]} AS TEXT) = ?"]
                        params = params + [self.value_filter]
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
                """ + BASE_FROM
                if conditions:
                    data_query += " WHERE " + " AND ".join(conditions)
                data_query += (" ORDER BY f.imported_at, c.row_index "
                                 f"LIMIT {self.page_size} OFFSET {offset}")
                cursor.execute(data_query, params)
                cases = cursor.fetchall()
            if (self.column_filter and self.value_filter
                    and self.column_filter not in TABLE_SYSTEM_COLUMNS):
                filtered_cases = []
                for case in cases:
                    if case['metadata_json']:
                        try:
                            metadata = json.loads(case['metadata_json'])
                            if str(metadata.get(self.column_filter, '')) == self.value_filter:
                                filtered_cases.append(case)
                        except (ValueError, TypeError):
                            continue
                cases = filtered_cases
                cases = filtered_cases
            # Сводка проверок для строк страницы (видна и в таблице, и в ревью)
            checks_map: dict = {}
            if cases:
                try:
                    with db(self.project_path) as conn2:
                        cur2 = conn2.cursor()
                        page_ids = [c['case_id'] for c in cases]
                        for i in range(0, len(page_ids), 500):
                            chunk = page_ids[i:i + 500]
                            ph = ",".join(["?"] * len(chunk))
                            for r in cur2.execute(f"""
                                SELECT case_id, severity, COUNT(*) AS n
                                FROM case_checks
                                WHERE case_id IN ({ph})
                                GROUP BY case_id, severity
                            """, chunk).fetchall():
                                sev = r["severity"] or "warning"
                                checks_map.setdefault(r["case_id"], {})[sev] = r["n"]
                except Exception as e:
                    logger.warning("checks summary failed: %s", e)
            self.cases_table.blockSignals(True)
            self.cases_table.clear()
            self.cases_table.setColumnCount(len(self.selected_columns) + 2)
            self.cases_table.setRowCount(len(cases))
            self.cases_table.setHorizontalHeaderLabels(["✓"] + self.selected_columns + ["⚠"])
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
                    except (ValueError, TypeError):
                        pass
                # Чекбокс — настоящим виджетом по центру ячейки: рисованный
                # индикатор item'а fluent-стиль ужимает и сдвигает в угол
                check_item = QTableWidgetItem()
                check_item.setData(Qt.ItemDataRole.UserRole, case['case_id'])
                check_item.setFlags(check_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.cases_table.setItem(row, 0, check_item)
                check_wrap = QWidget()
                check_layout = QHBoxLayout(check_wrap)
                check_layout.setContentsMargins(0, 0, 0, 0)
                check_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
                check_box = FCheckBox()
                check_box.setChecked(case['case_id'] in self.bulk_selected)
                check_box.toggled.connect(
                    lambda checked, cid=case['case_id']: self._on_bulk_toggled(cid, checked))
                check_layout.addWidget(check_box)
                self.cases_table.setCellWidget(row, 0, check_wrap)
                for col_idx, col_name in enumerate(self.selected_columns, start=1):
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
                    item = QTableWidgetItem(value)
                    # case_id дублируем и в первую дата-колонку для совместимости
                    if col_idx == 1:
                        item.setData(Qt.ItemDataRole.UserRole, case['case_id'])
                    item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                    self.cases_table.setItem(row, col_idx, item)
                sev = checks_map.get(case['case_id'], {})
                if sev:
                    parts = []
                    if sev.get('critical'):
                        parts.append(f"🔴{sev['critical']}")
                    if sev.get('error'):
                        parts.append(f"🔴{sev['error']}")
                    if sev.get('warning'):
                        parts.append(f"🟡{sev['warning']}")
                    if sev.get('info'):
                        parts.append(f"🔵{sev['info']}")
                    checks_text = " ".join(parts)
                    tip = "; ".join(f"{k}: {v}" for k, v in sorted(sev.items()))
                else:
                    checks_text, tip = "—", "Нет срабатываний в БД (нажми «Пересчитать проверки»)"
                checks_item = QTableWidgetItem(checks_text)
                checks_item.setToolTip(tip)
                checks_item.setFlags(checks_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.cases_table.setItem(row, len(self.selected_columns) + 1, checks_item)
            self.cases_table.blockSignals(False)
            self.cases_table.resizeColumnsToContents()
            # Колонка галочки — фиксированная узкая, как раньше: бокс ровно
            # напротив номера строки, без люфта
            self.cases_table.setColumnWidth(0, 30)
            # Широкие текстовые колонки укорачиваем, но не душим (440),
            # иначе Статус и ⚠ выдавливаются за край даже со скроллом
            for _c in range(1, self.cases_table.columnCount()):
                if self.cases_table.columnWidth(_c) > 440:
                    self.cases_table.setColumnWidth(_c, 440)
            self.page_label.setText(
                f"Страница {self.current_page + 1} / {self.total_pages} "
                f"(всего: {total})")
            self._update_bulk_label()
        except Exception as e:
            self.show_error("Не удалось загрузить таблицу", e)

    def _on_bulk_toggled(self, case_id: int, checked: bool):
        """Чекбокс-виджет массовых операций."""
        try:
            case_id = int(case_id)
        except (TypeError, ValueError):
            return
        if checked:
            self.bulk_selected.add(case_id)
        else:
            self.bulk_selected.discard(case_id)
        self._update_bulk_label()

    def _update_bulk_label(self):
        if hasattr(self, "bulk_label"):
            self.bulk_label.setText(f"Выбрано: {len(self.bulk_selected)}")

    def _bulk_target_ids(self) -> list:
        if self.bulk_selected:
            return sorted(self.bulk_selected)
        # ТЗ §7: пустой ручной выбор = вся текущая выборка фильтра
        return list(self.case_ids)

    def on_bulk_select_all(self):
        # «Выбрать все по фильтру» — вся выборка (может быть большой, подтверждаем)
        if len(self.case_ids) > 5000:
            if not confirm(
                self, "Подтверждение",
                f"Выбрать все {len(self.case_ids)} кейсов по текущему фильтру?\nПродолжить?",
            ):
                return
        self.bulk_selected = set(self.case_ids)
        self._update_bulk_label()
        self.load_table_data()

    def on_bulk_clear(self):
        self.bulk_selected.clear()
        self._update_bulk_label()
        self.load_table_data()

    def on_queue_changed(self):
        self.queue_mode = self.queue_combo.currentData() or "normal"
        self.load_case_ids()
        self.current_index = 0
        if self.case_ids:
            self.load_case(0)
        self.update_filter_indicator()
        self.update_queue_indicator()

    def update_queue_indicator(self):
        if not hasattr(self, "filter_indicator"):
            return
        try:
            from review_queue_service import queue_stats
            fid = (self.filters or {}).get("file_id")
            stats = queue_stats(self.project_path, file_id=fid)
            scope = "файл" if fid else "проект"
            base = getattr(self, "_filter_base", self.filter_indicator.text())
            self.filter_indicator.setText(
                f"{base}  |  {scope}: 🔴 {stats['problematic']} проблемных, "
                f"🟢 {stats['reviewed']}/{stats['total']} обработан")
        except Exception:
            pass

    def on_bulk_run(self):
        ids = self._bulk_target_ids()
        if not ids:
            notify(self, "warning", "Внимание", "Нет кейсов для массовой операции")
            return
        from bulk_dialog import BulkDialog
        dlg = BulkDialog(len(ids), self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_op:
            return
        op, val = dlg.result_op
        if not confirm(
            self, "Подтверждение",
            f"Вы собираетесь изменить {len(ids)} кейсов.\nОперация: {op} → {val}.\nПродолжить?",
        ):
            return
        sender_btn = self.sender()
        if sender_btn is not None:
            sender_btn.setEnabled(False)
            sender_btn.setText("⏳ Выполняется…")

        def _work():
            from bulk_operation_service import bulk_set_comment, bulk_set_status
            if op == "status":
                return bulk_set_status(self.project_path, ids, val)
            if op == "comment_replace":
                return bulk_set_comment(self.project_path, ids, val, mode="replace")
            if op == "comment_append":
                return bulk_set_comment(self.project_path, ids, val, mode="append")
            if op == "comment_clear":
                return bulk_set_comment(self.project_path, ids, "", mode="clear")
            raise ValueError(op)

        def _done(done):
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            self.bulk_selected.clear()
            self.load_case_ids()
            self.load_table_data()
            if self.case_ids:
                self.load_case(min(self.current_index, len(self.case_ids) - 1))
            notify(self, "success", "Готово", f"{done} кейсов обработано")

        def _fail(msg):
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            notify(self, "error", "Ошибка", f"Массовая операция не удалась:\n{msg}")

        from workers import run_in_background
        run_in_background(_work, on_finished=_done, on_error=_fail)

    def on_recheck_all(self):
        """Пересчёт автопроверок в БД (фон) — питает фильтры по проверкам и очередь."""
        import threading
        from PySide6.QtWidgets import QProgressDialog
        cancel_event = threading.Event()
        progress = QProgressDialog("Пересчёт автопроверок…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)

        sender_btn = self.sender()
        if sender_btn is not None:
            sender_btn.setEnabled(False)

        def _work():
            from autocheck_service import run_autochecks
            from workers import run_in_background as _run
            fid = (self.filters or {}).get("file_id")
            holder = {}

            def _progress(done, total):
                pct = int(done / total * 100) if total else 0
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(pct)

            worker = _run(run_autochecks, self.project_path,
                          file_id=fid, progress_callback=_progress, cancel_event=cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(res):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
            try:
                self.load_case_ids()
                self.load_table_data()
                self.update_queue_indicator()
            except Exception:
                pass
            fid = (self.filters or {}).get("file_id")
            scope = "по файлу" if fid else "по проекту"
            cancelled = isinstance(res, dict) and res.get("cancelled")
            notify(
                self, "success", "Автопроверки",
                f"Пересчёт {scope}: проверено кейсов: {res.get('total_checked', 0)}\n"
                f"Срабатываний: {res.get('flags_found', 0)}"
                + ("\n⚠️ Прервано пользователем — запустите снова для полного пересчёта."
                   if cancelled else ""))

        def _fail(msg):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
            if "Прервано пользователем" in msg:
                try:
                    self.load_case_ids()
                    self.load_table_data()
                    self.update_queue_indicator()
                except Exception:
                    pass
                notify(
                    self, "warning", "Автопроверки",
                    f"{msg}\nЧастичные результаты сохранены — "
                    "запустите снова для полного пересчёта.")
            else:
                notify(self, "error", "Ошибка",
                       f"Не удалось пересчитать проверки:\n{msg}")

        # _work создаёт воркер и цепляет сигналы: запуск через очередь событий,
        # чтобы progress успел отрисоваться до старта тяжёлой задачи
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _work)

    def on_bulk_undo(self):
        from database import db as _db
        try:
            with _db(self.project_path) as conn:
                row = conn.execute(
                    "SELECT operation_id FROM bulk_operations "
                    "WHERE undone=0 ORDER BY operation_id DESC LIMIT 1"
                ).fetchone()
            if not row:
                notify(self, "success", "Отмена", "Нет операций для отмены")
                return
            op_id = row["operation_id"]
        except Exception as e:
            self.show_error("Не удалось найти операцию", e)
            return
        if not confirm(self, "Подтверждение", f"Отменить массовую операцию #{op_id}?"):
            return
        try:
            from bulk_operation_service import undo_bulk_operation
            done = undo_bulk_operation(self.project_path, op_id)
            self.load_case_ids()
            self.load_table_data()
            notify(self, "success", "Готово", f"Отменено изменений: {done}")
        except Exception as e:
            self.show_error("Не удалось отменить", e)

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
        item = self.cases_table.item(row, 0)
        if not item:
            return
        case_id = item.data(Qt.ItemDataRole.UserRole)
        try:
            case_id = int(case_id)
        except (TypeError, ValueError):
            return
        if case_id in self.case_ids:
            idx = self.case_ids.index(case_id)
            self.view_stack.setCurrentIndex(0)
            self.btn_toggle_view.setText("📋 Таблица")
            self.load_case(idx)

    def open_table_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            self.filters = new_filters
            self.current_page = 0
            self.bulk_selected.clear()
            try:
                self.load_case_ids()
            except Exception as e:
                self.show_error("Не удалось применить фильтры", e)
                return
            self.load_table_data()
            self.update_filter_indicator()
            self.update_queue_indicator()
            notify(self, "success", "Фильтры", f"Найдено кейсов: {len(self.case_ids)}")

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
            from autocheck_service import rule_severity
            sev_icon = {"critical": "🔴", "error": "🔴", "warning": "🟡", "info": "🔵"}
            lines = [f"{sev_icon.get(rule_severity(c[0]), '⚠️')} {c[1]}: {c[2]}" for c in checks]
            self.checks_label.setText("\n".join(lines))
            self.checks_label.setStyleSheet("color: #FFAA00; font-size: 11px;")

    def show_templates_menu(self):
        templates = get_comment_templates(self.project_path)
        if not templates:
            notify(self, "success", "Шаблоны", "Нет доступных шаблонов")
            return
        menu = QMenu(self)
        for template in templates:
            action = menu.addAction(template['text'])
            action.triggered.connect(
                lambda checked, t=template['text']: self.insert_template(t)
            )
        anchor = getattr(self, "btn_templates", None) or self.btn_good
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

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
            try:
                added = add_comment_template(self.project_path, text.strip())
            except ValueError as e:
                notify(self, "warning", "Ошибка", str(e))
                return
            if added:
                notify(self, "success", "Шаблон добавлен", f"✅ Шаблон «{text.strip()}» добавлен")
            else:
                notify(self, "warning", "Ошибка", "Такой шаблон уже есть")

    def delete_template(self):
        """Удаляет пользовательский шаблон."""
        user_templates = get_user_templates(self.project_path)
        if not user_templates:
            notify(self, "success", "Удаление", "Нет пользовательских шаблонов для удаления")
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
                    notify(self, "success", "Удаление", f"✅ Шаблон «{text}» удалён")
                else:
                    notify(self, "warning", "Ошибка", "Не удалось удалить шаблон")

    def update_filter_indicator(self):
        base = ""
        if not self.filters:
            base = "Фильтры не применены"
        else:
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
            base = ("⚠️ Фильтры: " + " | ".join(parts)) if parts else "Фильтры не применены"
        # Всегда показываем размер выборки — видно, что фильтр сработал
        self._filter_base = f"{base}  |  Найдено: {len(self.case_ids)}"
        self.filter_indicator.setText(self._filter_base)

    def open_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            try:
                filtered_ids = get_filtered_case_ids(self.project_path, new_filters)
            except Exception as e:
                self.show_error("Не удалось применить фильтры", e)
                return
            if not filtered_ids:
                notify(
                    self,
                    "warning",
                    "Внимание",
                    "Нет кейсов, соответствующих выбранным фильтрам.\nФильтры не будут применены."
                )
                return
            self.filters = new_filters
            self.case_ids = filtered_ids
            self.current_index = 0
            self.bulk_selected.clear()
            self.update_filter_indicator()
            self.update_queue_indicator()
            notify(self, "success", "Фильтры", f"Найдено кейсов: {len(filtered_ids)}")
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
            with db(self.project_path) as conn:
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
                file_id = row['file_id']
                cursor.execute("SELECT mapping_json FROM files WHERE file_id = ?", (file_id,))
                mrow = cursor.fetchone()
                if mrow and mrow['mapping_json']:
                    try:
                        self.current_file_mapping = json.loads(mrow['mapping_json'])
                    except (ValueError, TypeError):
                        self.current_file_mapping = {}
                else:
                    self.current_file_mapping = {}

                cursor.execute("""
                    SELECT t.tag_id, t.tag_name, t.tag_code
                    FROM tags t
                    JOIN case_tags ct ON t.tag_id = ct.tag_id
                    WHERE ct.case_id = ?
                """, (self.current_case_id,))
                case_tags = {r['tag_id'] for r in cursor.fetchall()}
            self.update_case_display()
            self.update_tags_display(case_tags)
            self.update_info_label()
            self.run_autochecks_for_case()
            self.comment_edit.setPlainText(self.current_case.get('comment') or '')
            self.save_indicator.setText("")
        except Exception as e:
            self.show_error("Не удалось загрузить кейс", e)

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
            except (ValueError, TypeError):
                pass

        # Находим колонки по ролям из маппинга
        mapping = self.current_file_mapping
        primary_cols = [col for col, role in mapping.items() if role == 'primary_text']
        response_cols = [col for col, role in mapping.items() if role == 'response_text']

        # Отображаем запрос с реальными названиями колонок
        if primary_cols:
            for col_name in primary_cols:
                label = QLabel(f"📌 {col_name}:")
                if not FLUENT:
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
            if not FLUENT:
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
                if not FLUENT:
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
                if not FLUENT:
                    label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
                self.case_layout.addWidget(label)
                text_label = QLabel(response)
                text_label.setWordWrap(True)
                text_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
                text_label.setStyleSheet("font-size: 14px; padding: 6px;")
                self.case_layout.addWidget(text_label)

        # Источник (ссылка на БЗ) и свои категории из метаданных
        try:
            metadata = json.loads(self.current_case.get('metadata_json') or '{}')
        except (ValueError, TypeError):
            metadata = {}
        source = (metadata.get('source') or '').strip() if isinstance(metadata, dict) else ''
        if source:
            src_label = QLabel("🔗 Источник:")
            if not FLUENT:
                src_label.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
            self.case_layout.addWidget(src_label)
            src_text = QLabel(source)
            src_text.setWordWrap(True)
            src_text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
            src_text.setOpenExternalLinks(False)
            src_text.setStyleSheet("font-size: 13px; padding: 6px; color: #00AAFF;")
            self.case_layout.addWidget(src_text)

        self.case_layout.addStretch()

    def update_info_label(self):
        if not self.current_case:
            return
        status_map = {
            'unreviewed': '⬜ Не проверено',
            'good': f"✅ {STATUS_NAMES['good']}",
            'bad': f"❌ {STATUS_NAMES['bad']}",
            'uncertain': f"❓ {STATUS_NAMES['uncertain']}",
            'duplicate': f"🔄 {STATUS_NAMES['duplicate']}",
            'skip': f"⏭️ {STATUS_NAMES['skip']}",
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
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tag_id, tag_name, tag_code FROM tags ORDER BY tag_name")
                all_tags = cursor.fetchall()
            columns = 5
            row, col = 0, 0
            for tag in all_tags:
                tag_id = tag['tag_id']
                is_selected = tag_id in selected_tag_ids
                btn = FPushButton(tag['tag_name'])
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
        except Exception as e:
            logger.warning("tags display failed: %s", e)

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
            now = datetime.now(UTC).isoformat()
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("DELETE FROM case_tags WHERE case_id = ?", (self.current_case_id,))
                for tag_id in self.selected_tags:
                    cursor.execute("""
                        INSERT INTO case_tags (case_id, tag_id, created_at)
                        VALUES (?, ?, ?)
                    """, (self.current_case_id, tag_id, now))
        except Exception as e:
            logger.warning("save_tags failed: %s", e)

    def _comment_changed(self) -> bool:
        saved = (self.current_case or {}).get('comment') or ''
        return self.comment_edit.toPlainText().strip() != saved.strip()

    def save_comment(self, silent=False):
        if not self.current_case_id:
            return
        if silent and not self._comment_changed():
            return
        try:
            comment = self.comment_edit.toPlainText().strip()
            now = datetime.now(UTC).isoformat()
            with db(self.project_path) as conn:
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
            if self.current_case is not None:
                self.current_case['comment'] = comment or None
            if not silent:
                self.save_indicator.setText(f"💾 Комментарий сохранён ({now[:19]})")
        except Exception as e:
            if not silent:
                self.show_error("Не удалось сохранить комментарий", e)
            else:
                logger.warning("save_comment silent failed: %s", e)

    def set_status(self, status: str):
        if not self.current_case_id:
            return
        comment = self.comment_edit.toPlainText().strip()
        if status == 'bad':
            comment_mode = self.settings.get('require_comment_for_bad', 'warn')
            if comment_mode == 'required' and not comment:
                notify(
                    self,
                    "warning",
                    "Требуется комментарий",
                    "Для статуса «Плохо» необходимо добавить комментарий."
                )
                return
            elif comment_mode == 'warn' and not comment:
                if not confirm(
                    self,
                    "Рекомендация",
                    "Для статуса «Плохо» рекомендуется добавить комментарий.\n\n"
                    "Продолжить без комментария?",
                ):
                    return
        try:
            now = datetime.now(UTC).isoformat()
            with db(self.project_path) as conn:
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
                        INSERT INTO history
                            (case_id, event_type, field_name, old_value, new_value, created_at)
                        VALUES (?, 'status_changed', 'status', ?, ?, ?)
                    """, (self.current_case_id, old_status, status, now))
            self.current_case['status'] = status
            self.current_case['comment'] = comment or None
            self.update_info_label()
            self.save_indicator.setText(f"💾 Статус сохранён: {status}")
            if self.settings.get('auto_next_case', True):
                self.next_case()
        except Exception as e:
            self.show_error("Не удалось сохранить статус", e)

    def next_case(self):
        if self.current_index < len(self.case_ids) - 1:
            self.load_case(self.current_index + 1)
        else:
            notify(self, "success", "Конец", "🎉 Это последний кейс в выборке")

    def prev_case(self):
        if self.current_index > 0:
            self.load_case(self.current_index - 1)
        else:
            notify(self, "success", "Начало", "📍 Это первый кейс в выборке")

    def on_back(self):
        if self.current_case_id:
            self.save_comment(silent=True)
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.review_closed.emit()
