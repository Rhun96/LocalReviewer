from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QScrollArea, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal
from ui_base import BaseScreen
from ui_compat import (
    FPushButton, clear_in_fluent,
    notify,
)
import logging

from review_bulk import BulkMixin
from review_case import CaseMixin
from review_profile import ProfileMixin
from review_table import TableMixin
from review_verdicts import VerdictsMixin


logger = logging.getLogger(__name__)


class ReviewScreen(BaseScreen, ProfileMixin, CaseMixin, TableMixin, BulkMixin, VerdictsMixin):
    """Экран ревью с переключением между кейсом и таблицей."""

    review_closed = Signal()

    # Эмодзи по base-семантике (свои коды профилей тоже покрыты).
    BASE_EMOJI = {"unreviewed": "⬜", "good": "✅", "bad": "❌",
                  "uncertain": "❓", "duplicate": "🔄", "skip": "⏭️"}

    def __init__(self, project_path: str, parent=None, filters=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self.filters = filters or {}
        self.settings = self.load_review_settings()
        self.current_case = None
        self.current_case_id = None
        self.current_error = None
        # Строгий режим «Плохо»: комментарий → причина.
        # _bad_agreed — согласие идти без комментария (мягкий режим, «Да»).
        # _bad_cause_done — причина уже выбрана для текущего кейса.
        self._bad_pending = False
        self._bad_agreed = False
        self._bad_cause_done = False
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
        # Сортировка таблицы: import | unreviewed_first | problematic_first
        self.table_sort = "import"
        # Фильтр по значениям столбца
        self.column_filter = None
        self.value_filter = None
        # Теги раскрыты или нет
        self.tags_expanded = False
        # Массовые операции (ТЗ §5): выбранные кейсы
        self.bulk_selected: set = set()
        # Последнее одиночное действие для Ctrl+Z
        self._last_single = None
        # Умная очередь (ТЗ §8): normal | unreviewed | problematic
        self.queue_mode = "normal"
        self.load_case_ids()
        self.load_available_columns()
        self.init_ui()
        self.load_profile()
        self.apply_profile()
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
        self.load_profile()
        self.apply_profile()
        self.load_case_ids()
        self.load_available_columns()
        self.update_column_filter_combo()
        if self.case_ids:
            self.current_index = min(self.current_index, len(self.case_ids) - 1)
            self.load_case(self.current_index)
        self.update_filter_indicator()
        self.update_queue_indicator()

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
