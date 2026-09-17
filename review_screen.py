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
from filter_dialog import FilterDialog
from filter_service import get_filtered_case_ids, get_all_case_ids
from autocheck_service import check_case, get_check_settings
from templates_service import (
    add_comment_template, delete_comment_template,
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

    def load_profile(self) -> dict:
        """Активный профиль ревью; fallback — дефолтная схема."""
        try:
            from review_profile_service import get_active_profile
            self.profile = get_active_profile(self.project_path)
        except Exception as e:
            logger.warning("profile fallback: %s", e)
            from migrations import DEFAULT_PROFILE_CONFIG
            import copy
            self.profile = {"profile_id": 0, "name": "Default",
                            "config": copy.deepcopy(DEFAULT_PROFILE_CONFIG)}
        return self.profile

    # Эмодзи по base-семантике (свои коды профилей тоже покрыты).
    BASE_EMOJI = {"unreviewed": "⬜", "good": "✅", "bad": "❌",
                  "uncertain": "❓", "duplicate": "🔄", "skip": "⏭️"}

    def profile_statuses(self) -> list:
        cfg = (getattr(self, "profile", None) or {}).get("config", {})
        return [s for s in cfg.get("statuses", []) if s.get("enabled")]

    def _status_base(self, code: str) -> str:
        for s in (getattr(self, "profile", None) or {}).get("config", {}).get(
                "statuses", []):
            if s.get("code") == code:
                base = s.get("base") or code
                return base if base in ("unreviewed", "good", "bad",
                                        "uncertain", "duplicate", "skip") else code
        if code in ("unreviewed", "good", "bad", "uncertain", "duplicate", "skip"):
            return code
        return code

    def _status_display(self, code: str) -> str:
        for s in (getattr(self, "profile", None) or {}).get("config", {}).get(
                "statuses", []):
            if s.get("code") == code:
                return s.get("name") or code
        return STATUS_NAMES.get(code, code)

    def apply_profile(self):
        """Кнопки и хоткеи из активного профиля (коды — произвольные)."""
        if getattr(self, "profile", None) is None:
            self.load_profile()
        layout = getattr(self, "status_layout", None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.status_buttons = {}
            specs = self.profile_statuses()
            cols = 3
            for i, spec in enumerate(specs):
                code = spec["code"]
                base = spec.get("base") or code
                btn = FPushButton()
                btn.setMinimumHeight(30)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
                try:
                    btn.setStyleSheet(STATUS_STYLES.get(base, ""))
                except Exception:
                    pass
                hotkey = (spec.get("hotkey") or "").strip()
                suffix = f" [{hotkey}]" if hotkey else ""
                btn.setText(f"{self.BASE_EMOJI.get(base, '')} "
                            f"{spec.get('name', code)}{suffix}")
                btn.clicked.connect(lambda _c, s=code: self.set_status(s))
                layout.addWidget(btn, i // cols, i % cols)
                self.status_buttons[code] = btn
            for _c in range(cols):
                try:
                    layout.setColumnStretch(_c, 1)
                except Exception:
                    pass
        self.rebuild_shortcuts()

    def load_review_settings(self) -> dict:
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM settings")
                settings = {row['key']: row['value'] for row in cursor.fetchall()}
            return {
                'auto_next_case': settings.get('auto_next_case', 'true') == 'true',
                'require_comment_for_bad': settings.get('require_comment_for_bad', 'warn'),
                'skip_reviewed': settings.get('skip_reviewed', 'false') == 'true',
                'checks_first': settings.get('checks_first', 'false') == 'true',
                'no_return_good': settings.get('no_return_good', 'false') == 'true',
            }
        except Exception as e:
            logger.warning("review settings fallback: %s", e)
            return {
                'auto_next_case': True,
                'require_comment_for_bad': 'warn',
                'skip_reviewed': False,
                'checks_first': False,
                'no_return_good': False,
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
        # Не перехватываем цифры/стрелки при вводе текста или выборе в комбо.
        # Во Fluent-режиме FLineEdit/FTextEdit/FComboBox — НЕ наследники
        # QLineEdit/QTextEdit/QComboBox, поэтому проверяем и их явно,
        # иначе цифры 1–5 меняют статус прямо во время набора комментария.
        from PySide6.QtWidgets import QLineEdit, QTextEdit, QSpinBox
        from ui_compat import FComboBox as _FC, FLineEdit as _FL, FTextEdit as _FT
        try:
            fluent_types = tuple(t for t in (_FL, _FT, _FC) if isinstance(t, type))
        except Exception:
            fluent_types = ()
        return not isinstance(
            focus, (QLineEdit, QTextEdit, QComboBox, QSpinBox, *fluent_types))

    def init_shortcuts(self):
        self._shortcuts = []
        self.rebuild_shortcuts()

    def rebuild_shortcuts(self):
        """Хоткеи из профиля (+ стрелки всегда). Старые удаляем."""
        for sc in getattr(self, "_shortcuts", []):
            try:
                sc.setParent(None)
                sc.deleteLater()
            except Exception:
                pass
        self._shortcuts = []

        def guarded(fn):
            return lambda: fn() if self._shortcuts_allowed() else None

        def _add(key, fn):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(guarded(fn))
            self._shortcuts.append(sc)

        try:
            statuses = self.profile_statuses()
        except Exception:
            statuses = []
        if not statuses:
            statuses = [{"code": c, "hotkey": k} for c, k in
                        (("good", "1"), ("bad", "2"), ("uncertain", "3"),
                         ("duplicate", "4"), ("skip", "5"))]
        for spec in statuses:
            hotkey = (spec.get("hotkey") or "").strip()
            code = spec.get("code")
            if hotkey and code:
                _add(hotkey, lambda s=code: self.set_status(s))
        _add("Right", self.next_case)
        _add("Left", self.prev_case)
        # Ctrl+Z — отмена одиночного действия; в полях ввода работает
        # нативный undo текста (guarded пропускает), вне полей — наш.
        _add("Ctrl+Z", self.undo_single)
        # §26: рабочие хоткеи, если не заняты статусами профиля.
        used = {(s.get("hotkey") or "").strip().upper() for s in statuses}
        if "B" not in used:
            _add("B", self.open_bug_report)
        if "H" not in used:
            _add("H", self.open_history)
        if "S" not in used:
            _add("S", self.open_similar)
        _add("Ctrl+A", self.on_bulk_select_all)
        _add("Ctrl+Shift+A", self.on_bulk_clear)
        sc_save = QShortcut(QKeySequence("Ctrl+Return"), self)
        sc_save.setContext(Qt.ShortcutContext.WindowShortcut)
        sc_save.activated.connect(self.save_marks_hotkey)
        self._shortcuts.append(sc_save)

    def save_marks_hotkey(self):
        """Ctrl+Enter: сохранить разметку (черновик комментария). Везде."""
        if not self.current_case_id:
            return
        self.save_comment(silent=True)
        try:
            self.save_indicator.setText("💾 Сохранено (Ctrl+Enter)")
        except Exception:
            pass

    def open_history(self):
        """Переход к истории (H)."""
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("history")

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

        # === 1. Текст кейса (плоский контейнер: вложенные группы
        # криво рисуют заголовки, проверено на скринах) ===
        case_wrap = QWidget()
        case_wrap_layout = QVBoxLayout()
        case_wrap_layout.setSpacing(8)
        case_wrap_layout.setContentsMargins(0, 0, 0, 0)
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
        case_wrap_layout.addWidget(text_scroll)
        clear_in_fluent(text_scroll)
        case_wrap.setLayout(case_wrap_layout)
        layout.addWidget(case_wrap)

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
        self.btn_finish = FPushButton("🏁 Завершить ревью")
        self.btn_finish.setMinimumHeight(30)
        self.btn_finish.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_finish.setToolTip("Сохранить версию датасета (снимок всех оценок)")
        self.btn_finish.clicked.connect(self.on_finish_review)
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_filters)
        nav_layout.addWidget(btn_next)
        nav_layout.addWidget(btn_back)
        nav_layout.addWidget(self.btn_finish)
        for _i in range(5):
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
        self.verdicts_widget = QWidget()
        self.verdicts_layout = QGridLayout()
        self.verdicts_layout.setSpacing(4)
        self.verdicts_layout.setContentsMargins(0, 4, 0, 0)
        self.verdicts_widget.setLayout(self.verdicts_layout)
        checks_layout.addWidget(self.verdicts_widget)
        self.checks_group.setLayout(checks_layout)
        layout.addWidget(self.checks_group)

        # === 4. Статус (кнопки строятся из профиля — коды произвольные) ===
        status_group = QGroupBox("🎯 Статус")
        self.status_layout = QGridLayout()
        self.status_layout.setSpacing(6)
        self.status_buttons = {}
        # Равномерные колонки: в узком окне кнопки сжимаются одинаково,
        # текст остаётся по центру и не «съезжает»
        for _c in range(3):
            self.status_layout.setColumnStretch(_c, 1)
        status_group.setLayout(self.status_layout)
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
        btn_save_comment.clicked.connect(self.save_comment_manual)
        btn_undo_single = FPushButton("↩")
        btn_undo_single.setMaximumWidth(44)
        btn_undo_single.setToolTip("Отменить последнее действие (Ctrl+Z)")
        btn_undo_single.clicked.connect(self.undo_single)
        templates_layout.addWidget(btn_templates)
        templates_layout.addWidget(btn_add_template)
        templates_layout.addWidget(btn_del_template)
        templates_layout.addWidget(btn_save_comment)
        templates_layout.addWidget(btn_undo_single)
        templates_layout.addStretch()
        comment_layout.addLayout(templates_layout)
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(60)
        # Выделение мышью видно в любой теме: яркий фон + тёмный текст.
        self.comment_edit.setStyleSheet("""
            QTextEdit {
                selection-background-color: #00AAFF;
                selection-color: #000000;
            }
        """)
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
        tags_row = QHBoxLayout()
        tags_row.addWidget(self.btn_toggle_tags)
        self.btn_taxonomy = FPushButton("⚠ Таксономия…")
        self.btn_taxonomy.setMinimumHeight(30)
        self.btn_taxonomy.setToolTip("Редактор категорий и подкатегорий ошибок")
        self.btn_taxonomy.clicked.connect(self.open_taxonomy_editor)
        tags_row.addWidget(self.btn_taxonomy)
        self.btn_new_tag = FPushButton("＋ Тег")
        self.btn_new_tag.setMinimumHeight(30)
        self.btn_new_tag.setToolTip("Создать свой тег")
        self.btn_new_tag.clicked.connect(self.on_create_tag)
        tags_row.addWidget(self.btn_new_tag)
        self.btn_del_tag = FPushButton("－ Тег")
        self.btn_del_tag.setMinimumHeight(30)
        self.btn_del_tag.setToolTip("Удалить неиспользуемый тег")
        self.btn_del_tag.clicked.connect(self.on_delete_tag)
        tags_row.addWidget(self.btn_del_tag)
        self.btn_similar = FPushButton("🔍 Похожие")
        self.btn_similar.setMinimumHeight(30)
        self.btn_similar.setToolTip("Похожие кейсы (TF-IDF) — только контекст")
        self.btn_similar.clicked.connect(self.open_similar)
        tags_row.addWidget(self.btn_similar)
        self.btn_bug = FPushButton("🐞 Баг")
        self.btn_bug.setMinimumHeight(30)
        self.btn_bug.setToolTip("Создать Bug Report из кейса")
        self.btn_bug.clicked.connect(self.open_bug_report)
        tags_row.addWidget(self.btn_bug)
        self.btn_quick_bug = FPushButton("⚡ Быстрый баг")
        self.btn_quick_bug.setMinimumHeight(30)
        self.btn_quick_bug.setToolTip("Быстрый баг: только заголовок")
        self.btn_quick_bug.clicked.connect(self.open_quick_bug)
        tags_row.addWidget(self.btn_quick_bug)
        self.btn_case_bugs = FPushButton("🐞 Баги (0)")
        self.btn_case_bugs.setMinimumHeight(30)
        self.btn_case_bugs.setToolTip("Баги текущего кейса — клик открывает")
        self.btn_case_bugs.clicked.connect(self.open_case_bugs)
        tags_row.addWidget(self.btn_case_bugs)
        self.btn_context = FPushButton("📤 Контекст")
        self.btn_context.setMinimumHeight(30)
        self.btn_context.setToolTip("Контекст кейса в буфер (Markdown/Plain)")
        self.btn_context.clicked.connect(self.copy_case_context)
        tags_row.addWidget(self.btn_context)
        layout.addLayout(tags_row)
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
        self.btn_duplicates = FPushButton("👯 Дубли")
        self.btn_duplicates.setMinimumHeight(30)
        self.btn_duplicates.setToolTip("Потенциальные дубли (TF-IDF по запросу+ответу)")
        self.btn_duplicates.clicked.connect(self.open_duplicates)
        controls_layout.addWidget(self.btn_duplicates)
        self.sort_combo = FComboBox()
        self.sort_combo.addItem("Порядок импорта", "import")
        self.sort_combo.addItem("Сначала непроверенные", "unreviewed_first")
        self.sort_combo.addItem("Сначала проблемные", "problematic_first")
        self.sort_combo.setMinimumHeight(30)
        self.sort_combo.setToolTip("Сортировка таблицы (сохраняется в фильтр)")
        self.sort_combo.currentIndexChanged.connect(self.on_sort_changed)
        controls_layout.addWidget(self.sort_combo)
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

    def open_taxonomy_editor(self):
        """Редактор таксономии прямо из ревью — всё под рукой."""
        try:
            from taxonomy_editor import TaxonomyDialog
            TaxonomyDialog(self.project_path, self).exec()
        except Exception as e:
            self.show_error("Не удалось открыть таксономию", e)

    def update_column_filter_combo(self):
        """Обновляет список столбцов для фильтра."""
        if not hasattr(self, 'column_filter_combo'):
            return
        self.column_filter_combo.blockSignals(True)
        self.column_filter_combo.clear()
        self.column_filter_combo.addItem("Фильтр по столбцу...", None)
        from ui_compat import add_elided_item as _addc, bound_combo_popup as _boundc
        for col in self.available_columns:
            _addc(self.column_filter_combo, col, col)
        _boundc(self.column_filter_combo)
        _boundc(self.value_filter_combo)
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
                if column == "ID":
                    # ID = столбец-идентификатор из маппинга (source_id).
                    # Пустые показывают номер строки — их в списке нет,
                    # иначе UUID смешиваются с номерами и «всё наперекосяк».
                    try:
                        cursor.execute("""
                            SELECT DISTINCT c.source_id as value
                            FROM cases c
                            WHERE c.source_id IS NOT NULL AND c.source_id != ''
                            ORDER BY value
                            LIMIT 100
                        """)
                        values = [row['value'] for row in cursor.fetchall()]
                    except Exception:
                        # Фолбэк: старое выражение (source_id или номер).
                        col_sql = COLUMN_TO_SQL[column]
                        cursor.execute(f"""
                            SELECT DISTINCT {col_sql} as value
                            FROM cases c
                            JOIN files f ON c.file_id = f.file_id
                            LEFT JOIN annotations a ON c.case_id = a.case_id
                            WHERE {col_sql} IS NOT NULL
                            ORDER BY value
                            LIMIT 100
                        """)
                        values = [row['value'] for row in cursor.fetchall()]
                elif column in TABLE_SYSTEM_COLUMNS:
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
                    # Metadata-значения — одним SQL через json_extract,
                    # а не перебором 2000 JSON в GUI-потоке.
                    try:
                        cursor.execute("""
                            SELECT DISTINCT json_extract(c.metadata_json, '$.' || ?) AS value
                            FROM cases c
                            WHERE c.metadata_json IS NOT NULL
                              AND json_extract(c.metadata_json, '$.' || ?) IS NOT NULL
                            ORDER BY value LIMIT 100
                        """, (column, column))
                        values = [r["value"] for r in cursor.fetchall()
                                  if r["value"] not in (None, "")]
                        values = [str(v) for v in values]
                    except Exception:
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
            from ui_compat import add_elided_item as _addv
            for value in values:
                _addv(self.value_filter_combo, str(value), str(value))
        except Exception as e:
            logger.warning("column filter values failed: %s", e)
            notify(self, "warning", "Фильтр по столбцу",
                   f"Не удалось загрузить значения колонки «{self.column_filter}»:\n{e}\n"
                   "Подробности — в logs/localreviewer.log.")
        self.value_filter_combo.blockSignals(False)

    def on_sort_changed(self):
        if not hasattr(self, 'sort_combo'):
            return
        self.table_sort = self.sort_combo.currentData() or "import"
        self.current_page = 0
        self.load_table_data()

    def on_value_filter_changed(self):
        """При изменении значения фильтра перезагружаем таблицу."""
        if not hasattr(self, 'value_filter_combo'):
            return
        self.value_filter = self.value_filter_combo.currentData()
        self.current_page = 0
        self.load_table_data()

    def toggle_view(self):
        """Переключает между видом кейса и таблицей.

        Строгий режим «Плохо» блокирует только СМЕНУ кейса, а не просмотр:
        в таблицу и фильтры ходить можно, выбрать другой кейс — нет.
        """
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
            eff_filters = dict(self.filters or {})
            # Таблица уважает режим очереди: unreviewed — это фильтр, а не только порядок.
            if getattr(self, "queue_mode", "normal") == "unreviewed":
                eff_filters = dict(eff_filters)
                eff_filters["statuses"] = ["unreviewed"]
            _joins, conditions, params = filter_from(eff_filters)
            params = list(params)
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                count_query = "SELECT COUNT(DISTINCT c.case_id) as total " + BASE_FROM
                data_conditions = list(conditions)
                data_params = list(params)
                if self.column_filter and self.value_filter:
                    if self.column_filter in TABLE_SYSTEM_COLUMNS:
                        data_conditions = data_conditions + [
                            f"CAST({COLUMN_TO_SQL[self.column_filter]} AS TEXT) = ?"]
                        data_params = data_params + [self.value_filter]
                    else:
                        # Metadata-фильтр в SQL (иначе total врёт, страница полупустая).
                        data_conditions = data_conditions + [
                            "json_extract(c.metadata_json, '$.' || ?) = ?"]
                        data_params = data_params + [self.column_filter, self.value_filter]
                if data_conditions:
                    count_query += " WHERE " + " AND ".join(data_conditions)
                cursor.execute(count_query, data_params)
                total = cursor.fetchone()['total']
                self.total_pages = max(1, (total + self.page_size - 1) // self.page_size)
                self.current_page = min(self.current_page, self.total_pages - 1)
                offset = self.current_page * self.page_size
                data_query = """
                    SELECT c.case_id, c.source_id, c.row_index + 1 as row_num, f.file_name,
                           c.primary_text, c.response_text,
                           COALESCE(a.status, 'unreviewed') as status,
                           a.comment, c.metadata_json
                """ + BASE_FROM
                if self.table_sort == "problematic_first":
                    # JOIN строго до WHERE, иначе near "LEFT": syntax error.
                    data_query += (" LEFT JOIN (SELECT case_id, COUNT(*) AS n FROM case_checks "
                                   "GROUP BY case_id) cc ON cc.case_id = c.case_id")
                if data_conditions:
                    data_query += " WHERE " + " AND ".join(data_conditions)
                if self.table_sort == "problematic_first":
                    data_query += (" ORDER BY COALESCE(cc.n, 0) DESC, "
                                   "f.imported_at, c.row_index ")
                elif self.table_sort == "unreviewed_first":
                    data_query += (" ORDER BY (COALESCE(a.status, 'unreviewed') "
                                   "!= 'unreviewed'), f.imported_at, c.row_index ")
                else:
                    data_query += (" ORDER BY f.imported_at, c.row_index ")
                data_query += "LIMIT ? OFFSET ?"
                cursor.execute(data_query, (*data_params, self.page_size, offset))
                cases = cursor.fetchall()
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
            _name_cache: dict = {}

            def _status_label(code: str) -> str:
                if code not in _name_cache:
                    base = self._status_base(code or "unreviewed")
                    _name_cache[code] = (
                        f"{self.BASE_EMOJI.get(base, '')} "
                        f"{self._status_display(code or 'unreviewed')}").strip()
                return _name_cache[code]
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
                        # Идентификатор из маппинга (001, 1kij…), иначе внутренний номер
                        value = case['source_id'] or str(case['case_id'])
                    elif col_name == 'Строка':
                        value = str(case['row_num'])
                    elif col_name == 'Файл':
                        value = case['file_name']
                    elif col_name == 'Запрос':
                        value = (case['primary_text'] or '')[:100]
                    elif col_name == 'Ответ':
                        value = (case['response_text'] or '')[:100]
                    elif col_name == 'Статус':
                        value = _status_label(case['status'])
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
            bad_part = f", ❌ {stats['bad']} плохих" if stats.get("bad") else ""
            self.filter_indicator.setText(
                f"{base}  |  {scope}: 🔴 {stats['problematic']} проблемных{bad_part}, "
                f"🟢 {stats['reviewed']}/{stats['total']} обработан")
        except Exception:
            pass

    def on_bulk_run(self):
        ids = self._bulk_target_ids()
        if not ids:
            notify(self, "warning", "Внимание", "Нет кейсов для массовой операции")
            return
        # Защита от неявного «вся выборка»: пустой ручной выбор подсвечиваем отдельно.
        if not self.bulk_selected:
            if not confirm(
                self, "Подтверждение",
                f"Ручной выбор пуст — операция применится ко ВСЕЙ текущей выборке "
                f"({len(ids)} кейсов).\nПродолжить?",
            ):
                return
        from bulk_dialog import BulkDialog
        dlg = BulkDialog(len(ids), self, project_path=self.project_path)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_op:
            return
        op, val = dlg.result_op
        if op == "add_tag":
            op_label = f"добавить тег (id={val})"
        elif op == "remove_tag":
            op_label = f"убрать тег (id={val})"
        elif op == "replace_tags":
            op_label = f"заменить набор тегов ({len(val)} шт.)"
        elif op == "mark_viewed":
            op_label = "отметить просмотренными"
        elif op == "unmark_viewed":
            op_label = "снять «просмотрено»"
        elif op in ("recheck", "reset_checks"):
            op_label = {"recheck": "пересчитать проверки",
                        "reset_checks": "сбросить проверки"}[op]
        else:
            op_label = f"{op} → {val}"
        if not confirm(
            self, "Подтверждение",
            f"Вы собираетесь изменить {len(ids)} кейсов.\nОперация: {op_label}.\nПродолжить?",
        ):
            return
        sender_btn = self.sender()
        if sender_btn is not None:
            sender_btn.setEnabled(False)
            sender_btn.setText("⏳ Выполняется…")
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Массовая операция…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)

        def _work_outer():
            from workers import run_in_background as _run

            def _make_work():
                from bulk_operation_service import (
                    bulk_add_tag, bulk_remove_tag, bulk_set_comment,
                    bulk_set_status, bulk_set_tags, bulk_set_viewed)
                from autocheck_service import run_autochecks, reset_checks

                def _call(fn, *a):
                    return fn(*a, progress_callback=_progress,
                              cancel_event=cancel_event)

                if op == "status":
                    return _call(bulk_set_status, self.project_path, ids, val)
                if op == "comment_replace":
                    return _call(bulk_set_comment, self.project_path, ids, val,
                                 mode="replace")
                if op == "comment_append":
                    return _call(bulk_set_comment, self.project_path, ids, val,
                                 mode="append")
                if op == "comment_clear":
                    return _call(bulk_set_comment, self.project_path, ids, "",
                                 mode="clear")
                if op == "add_tag":
                    return _call(bulk_add_tag, self.project_path, ids, int(val))
                if op == "remove_tag":
                    return _call(bulk_remove_tag, self.project_path, ids, int(val))
                if op == "replace_tags":
                    return _call(bulk_set_tags, self.project_path, ids,
                                 [int(t) for t in val])
                if op == "mark_viewed":
                    return _call(bulk_set_viewed, self.project_path, ids, True)
                if op == "unmark_viewed":
                    return _call(bulk_set_viewed, self.project_path, ids, False)
                if op == "recheck":
                    return run_autochecks(self.project_path, case_ids=ids,
                                          progress_callback=_progress,
                                          cancel_event=cancel_event)["flags_found"]
                if op == "reset_checks":
                    # Мгновенный DELETE без прогресса — отмена не нужна.
                    return reset_checks(self.project_path, case_ids=ids)
                raise ValueError(op)

            holder: dict = {}

            def _progress(done, total):
                pct = int(done / total * 100) if total else 0
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(pct)

            worker = _run(_make_work)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(done):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            self.bulk_selected.clear()
            self.load_case_ids()
            self.load_table_data()
            if self.case_ids:
                self.load_case(min(self.current_index, len(self.case_ids) - 1))
            # Bulk мог сменить статус текущего кейса — pending пересчитываем.
            if (self.current_case or {}).get('status') != 'bad':
                self._bad_reset()
            if op == "recheck":
                text = f"Проверки пересчитаны для {len(ids)} кейсов, срабатываний: {done}"
            elif op == "reset_checks":
                text = f"Сброшено срабатываний: {done} (кейсов: {len(ids)})"
            else:
                text = f"{done} кейсов обработано"
            notify(self, "success", "Готово", text)

        def _fail(msg):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Операция прервана",
                       f"{msg}\nИзменения откачены — можно запустить снова.")
            else:
                notify(self, "error", "Ошибка", f"Массовая операция не удалась:\n{msg}")

        # Запуск через очередь событий, чтобы прогресс успел отрисоваться.
        QTimer.singleShot(0, _work_outer)

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
                notify(self, "warning", "Отмена", "Нет операций для отмены")
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
        if not self._bad_can_leave():
            self.view_stack.setCurrentIndex(0)
            self.btn_toggle_view.setText("📋 Таблица")
            return
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

    def _current_view(self) -> dict:
        """Вид таблицы для сохранения рядом с фильтром (ТЗ §29)."""
        return {"columns": list(self.selected_columns),
                "queue_mode": self.queue_mode,
                "sort": self.table_sort}

    def _apply_view(self, view: dict | None) -> None:
        """Применяет вид из сохранённого фильтра (с проверкой значений)."""
        if not view:
            return
        cols = view.get("columns")
        if cols:
            valid = [c for c in cols if c in (self.available_columns or [])]
            if valid:
                self.selected_columns = valid
        qm = view.get("queue_mode")
        if qm in ("normal", "unreviewed", "problematic"):
            self.queue_mode = qm
            try:
                for i in range(self.queue_combo.count()):
                    if self.queue_combo.itemData(i) == qm:
                        self.queue_combo.blockSignals(True)
                        self.queue_combo.setCurrentIndex(i)
                        self.queue_combo.blockSignals(False)
                        break
            except Exception:
                pass
        s = view.get("sort")
        if s in ("import", "unreviewed_first", "problematic_first"):
            self.table_sort = s
            try:
                for i in range(self.sort_combo.count()):
                    if self.sort_combo.itemData(i) == s:
                        self.sort_combo.blockSignals(True)
                        self.sort_combo.setCurrentIndex(i)
                        self.sort_combo.blockSignals(False)
                        break
            except Exception:
                pass

    def open_table_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        dialog.set_view(self._current_view())
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            self.filters = new_filters
            self._apply_view(dialog.get_view())
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
        self._refresh_verdicts()

    def _refresh_verdicts(self):
        """Кнопки вердиктов по срабатываниям из БД (ТЗ §75): ✓ / ✗."""
        while self.verdicts_layout.count():
            item = self.verdicts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.current_case_id:
            self.verdicts_widget.setVisible(False)
            return
        try:
            from autocheck_service import get_case_checks, get_check_verdicts
            stored = get_case_checks(self.project_path, self.current_case_id)
            verdicts = get_check_verdicts(self.project_path, self.current_case_id)
        except Exception as e:
            logger.warning("verdicts load failed: %s", e)
            self.verdicts_widget.setVisible(False)
            return
        if not stored:
            self.verdicts_widget.setVisible(False)
            return
        for row, chk in enumerate(stored):
            code = chk.get("check_code", "")
            name = chk.get("check_name", code)
            cur = verdicts.get(code)
            lbl = QLabel(f"{'✅' if cur == 'confirmed' else '❌' if cur else '⚪'} {name}")
            lbl.setStyleSheet("font-size: 11px;")
            btn_ok = FPushButton("✓")
            btn_ok.setMaximumWidth(36)
            btn_ok.setToolTip("Подтвердить: правило сработало верно")
            btn_ok.setCheckable(True)
            btn_ok.setChecked(cur == "confirmed")
            self._style_tag_btn(btn_ok, cur == "confirmed")
            btn_ok.clicked.connect(
                lambda _c, c=code, v=cur: self._set_verdict(
                    c, None if v == "confirmed" else "confirmed"))
            btn_no = FPushButton("✗")
            btn_no.setMaximumWidth(36)
            btn_no.setToolTip("Ложное: правило сработало зря")
            btn_no.setCheckable(True)
            btn_no.setChecked(cur == "false_positive")
            self._style_tag_btn(btn_no, cur == "false_positive")
            btn_no.clicked.connect(
                lambda _c, c=code, v=cur: self._set_verdict(
                    c, None if v == "false_positive" else "false_positive"))
            self.verdicts_layout.addWidget(lbl, row, 0)
            self.verdicts_layout.addWidget(btn_ok, row, 1)
            self.verdicts_layout.addWidget(btn_no, row, 2)
        self.verdicts_widget.setVisible(True)

    def _set_verdict(self, check_code: str, verdict: str | None):
        if not self.current_case_id:
            return
        try:
            from autocheck_service import set_check_verdict
            set_check_verdict(self.project_path, self.current_case_id,
                              check_code, verdict)
        except Exception as e:
            self.show_error("Не удалось сохранить вердикт", e)
            return
        self._refresh_verdicts()

    def show_templates_menu(self):
        from templates_service import ordered_templates
        err = getattr(self, "current_error", None) or {}
        templates = ordered_templates(
            self.project_path, err.get("category_id"), err.get("subcategory_id"))
        if not templates:
            notify(self, "warning", "Шаблоны", "Нет доступных шаблонов")
            return
        menu = QMenu(self)
        for template in templates:
            label = template['text']
            if (err.get("category_id") and
                    template.get("category_id") == err.get("category_id")):
                if template.get("subcategory_id") == err.get("subcategory_id"):
                    label = "★ " + label
                else:
                    label = "☆ " + label
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked, t=template['text']: self.insert_template(t)
            )
        anchor = getattr(self, "btn_templates", None)
        if anchor is None:
            btns = getattr(self, "status_buttons", {}) or {}
            anchor = next(iter(btns.values()), None) or self
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def insert_template(self, text: str):
        from templates_service import (TEMPLATE_VARS, build_template_context,
                                       render_template, template_vars)
        ctx = build_template_context(
            self.project_path, self.current_case_id or 0,
            getattr(self, "current_case", None),
            getattr(self, "current_error", None))
        rendered = render_template(text, ctx)
        # Неизвестные переменные — спрашиваем у человека (не придумываем).
        for var in template_vars(rendered):
            if var not in TEMPLATE_VARS:
                continue
            val, ok = QInputDialog.getText(
                self, "Шаблон", f"Значение для {{{var}}}:")
            if not ok:
                return
            ctx[var] = (val or "").strip()
        rendered = render_template(text, ctx)
        current = self.comment_edit.toPlainText()
        if current:
            self.comment_edit.setPlainText(current + "\n" + rendered)
        else:
            self.comment_edit.setPlainText(rendered)

    def add_new_template(self):
        text, ok = QInputDialog.getText(
            self,
            "Новый шаблон",
            "Введите текст шаблона комментария:"
        )
        if ok and text.strip():
            text = text.strip()
            # Привязка к причине текущего кейса (ТЗ §25): подходящие шаблоны
            # показываются первыми (★) при такой же причине.
            cat_id, sub_id = None, None
            err = getattr(self, "current_error", None) or {}
            if err.get("category_id"):
                label = err.get("category_name", "")
                if err.get("subcategory_name"):
                    label += f" → {err['subcategory_name']}"
                if confirm(self, "Привязка к причине",
                           f"Привязать шаблон к причине «{label}»?\n"
                           "Привязанные показываются первыми при такой же причине.\n"
                           "«Нет» — общий шаблон для всех."):
                    cat_id, sub_id = err.get("category_id"), err.get("subcategory_id")
            try:
                added = add_comment_template(self.project_path, text, cat_id, sub_id)
            except ValueError as e:
                notify(self, "warning", "Ошибка", str(e))
                return
            if added:
                notify(self, "success", "Шаблон добавлен", f"✅ Шаблон «{text}» добавлен")
            else:
                notify(self, "warning", "Ошибка", "Такой шаблон уже есть")

    def delete_template(self):
        """Удаляет пользовательский шаблон."""
        user_templates = get_user_templates(self.project_path)
        if not user_templates:
            notify(self, "warning", "Удаление", "Нет пользовательских шаблонов для удаления")
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
            if self.filters.get('check_severities'):
                parts.append(f"severity: {','.join(self.filters['check_severities'])}")
            if self.filters.get('error_category_id'):
                parts.append("по причине ✓")
            if self.filters.get('error_severities'):
                parts.append(f"крит.: {','.join(self.filters['error_severities'])}")
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
        dialog.set_view(self._current_view())
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            try:
                filtered_ids = get_filtered_case_ids(self.project_path, new_filters)
            except Exception as e:
                self.show_error("Не удалось применить фильтры", e)
                return
            # Пустой результат — тоже валиден: показываем пустую выборку,
            # а не молча оставляем старые фильтры (иначе таблица и кейс-вид расходятся).
            if not filtered_ids:
                notify(
                    self,
                    "warning",
                    "Внимание",
                    "Нет кейсов, соответствующих выбранным фильтрам.\n"
                    "Показана пустая выборка."
                )
            self.filters = new_filters
            self._apply_view(dialog.get_view())
            # Выборку пересчитываем через очередь (вид мог сменить queue_mode).
            try:
                self.load_case_ids()
            except Exception:
                self.case_ids = filtered_ids
            self.current_index = 0
            self.bulk_selected.clear()
            self.update_filter_indicator()
            self.update_queue_indicator()
            notify(self, "success", "Фильтры", f"Найдено кейсов: {len(filtered_ids)}")
            if self.case_ids:
                self.load_case(0)
            else:
                self.current_case = None
                self.current_case_id = None

    def load_case(self, index: int):
        if index < 0 or index >= len(self.case_ids):
            return
        # Строгий режим: не даём тихо сменить кейс и сбросить pending.
        # load_case вызывается только после _bad_can_leave, но bulk/_done и
        # программные переходы могли прийти в обход — проверяем здесь тоже.
        try:
            new_id = self.case_ids[index]
        except Exception:
            return
        if new_id != self.current_case_id:
            # Смена кейса в строгом режиме запрещена (жульничество через таблицу
            # тоже закрыто: двойной клик идёт через _bad_can_leave).
            if (self._bad_pending and self.current_case_id is not None
                    and not self._bad_can_leave()):
                return
            if self.current_case_id:
                self.save_comment(silent=True)
            self._bad_reset()  # новый кейс — чистый лист
        elif self.current_case_id:
            # Перезагрузка того же кейса (после bulk/фильтров): черновик
            # сохраняем, pending сохраняем.
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
            try:
                from taxonomy_service import get_case_error
                self.current_error = get_case_error(self.project_path, self.current_case_id)
            except Exception:
                self.current_error = None
            self.update_case_display()
            self.update_tags_display(case_tags)
            self.update_info_label()
            self.run_autochecks_for_case()
            self.comment_edit.setPlainText(self.current_case.get('comment') or '')
            self.save_indicator.setText("")
        except Exception as e:
            self.show_error("Не удалось загрузить кейс", e)

    def update_case_display(self):
        """Три окна: Тема / Текст / Ответ (Ответ шире, меньше скролла)."""
        if not self.current_case:
            return

        # Очищаем старый контент
        while self.case_layout.count():
            item = self.case_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def _text_widget(text: str):
            w = QLabel(str(text) if text else "(пусто)")
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            w.setStyleSheet("font-size: 14px; padding: 6px;")
            return w

        def _header(text: str):
            h = QLabel(text)
            if not FLUENT:
                h.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
            return h

        def _box(title: str):
            # Панель + обычный заголовок вместо вложенного QGroupBox:
            # вложенные группы криво рисуют заголовки.
            panel = QFrame()
            panel.setObjectName("caseBox")
            panel.setStyleSheet(
                "#caseBox { border: 1px solid #3a3a3a; border-radius: 8px; }")
            lay = QVBoxLayout()
            lay.setSpacing(6)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.addWidget(_header(title))
            panel.setLayout(lay)
            return panel, lay

        # Парсим сырые данные и метаданные
        raw_data = {}
        if self.current_case.get('raw_json'):
            try:
                raw_data = json.loads(self.current_case['raw_json'])
            except (ValueError, TypeError):
                pass
        try:
            metadata = json.loads(self.current_case.get('metadata_json') or '{}')
        except (ValueError, TypeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        mapping = self.current_file_mapping
        primary_cols = [col for col, role in mapping.items() if role == 'primary_text']
        response_cols = [col for col, role in mapping.items() if role == 'response_text']
        topic = (metadata.get('topic') or '').strip()
        topic_title = "📌 Тема"
        text_cols = list(primary_cols)
        if not topic and len(primary_cols) >= 2:
            # Тема и Текст — одна категория «Запрос»: ищем колонку,
            # похожую на тему по имени, иначе берём первую.
            # Работает и на старых импортах без роли Темы.
            # Одна колонка — делить нечего, Темы нет.
            import re as _re
            named = [c for c in primary_cols
                     if _re.search(r"тем|subj|title|topic", c, _re.IGNORECASE)]
            tcol = named[0] if named else primary_cols[0]
            topic = str(raw_data.get(tcol, '') or '').strip()
            if topic:
                topic_title = f"📌 Тема ({tcol})"
                text_cols = [c for c in primary_cols if c != tcol]

        # 1. Тема (явная роль — или первая колонка Запроса)
        if topic:
            box, lay = _box(topic_title)
            lay.addWidget(_text_widget(topic))
            self.case_layout.addWidget(box, 1)

        # 2. Текст (запрос): подпись колонки — только если их несколько.
        box, lay = _box("📝 Текст")
        if text_cols:
            for col_name in text_cols:
                if len(text_cols) > 1:
                    lay.addWidget(_header(f"📌 {col_name}:"))
                lay.addWidget(_text_widget(raw_data.get(col_name, '')))
        else:
            # Одна колонка Запроса без Темы — показываем как есть.
            lay.addWidget(_header("📌 Запрос:"))
            lay.addWidget(_text_widget(self.current_case.get('primary_text')))
        source = (metadata.get('source') or '').strip()
        if source and not topic:
            # Источник — сюда, только если нет окна Темы.
            lay.addWidget(_header("🔗 Источник:"))
            src_text = QLabel(source)
            src_text.setWordWrap(True)
            src_text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            src_text.setOpenExternalLinks(False)
            src_text.setStyleSheet("font-size: 13px; padding: 6px; color: #00AAFF;")
            lay.addWidget(src_text)
        self.case_layout.addWidget(box, 2)

        # 3. Ответ (шире остальных, чтобы меньше скроллить)
        box, lay = _box("💬 Ответ")
        if response_cols:
            for col_name in response_cols:
                if len(response_cols) > 1:
                    lay.addWidget(_header(f"💬 {col_name}:"))
                lay.addWidget(_text_widget(raw_data.get(col_name, '')))
        else:
            lay.addWidget(_text_widget(self.current_case.get('response_text')))
        self.case_layout.addWidget(box, 4)

        self.case_layout.addStretch(0)

    def update_info_label(self):
        if not self.current_case:
            return
        code = self.current_case.get('status') or 'unreviewed'
        base = self._status_base(code)
        status = f"{self.BASE_EMOJI.get(base, '')} {self._status_display(code)}".strip()
        sid = (self.current_case.get('source_id') or "").strip()
        sid_part = f" | 🆔 {sid}" if sid else f" | 🆔 case:{self.current_case.get('case_id')}"
        text = (
            f"📋 Кейс {self.current_index + 1} / {len(self.case_ids)} | "
            f"📄 {self.current_case.get('file_name')}{sid_part} | "
            f"{status}"
        )
        err = getattr(self, "current_error", None)
        if err and err.get("category_name"):
            from taxonomy_service import SEVERITY_NAMES
            sub = f" → {err['subcategory_name']}" if err.get("subcategory_name") else ""
            sev = SEVERITY_NAMES.get(err.get("severity", ""), "")
            text += f" | ⚠ {err['category_name']}{sub} [{sev}]"
        self.info_label.setText(text)
        self.update_finish_button()
        try:
            from bug_report_service import bugs_for_case
            n = len(bugs_for_case(self.project_path, self.current_case_id))
            self.btn_case_bugs.setText(f"🐞 Баги ({n})")
        except Exception:
            pass

    def _review_scope(self):
        """Скоуп ревью: файл из фильтров или весь проект.

        Считаем только то, что проверяется: условный «Ревью 1» — кейсы
        файла «Ревью 1»; все файлы — только если фильтр по файлу не задан.
        """
        return (self.filters or {}).get("file_id")

    def _scope_stats(self) -> dict:
        from review_queue_service import queue_stats
        return queue_stats(self.project_path, file_id=self._review_scope())

    def _scope_name(self) -> str:
        fid = self._review_scope()
        if fid is None:
            return "проект"
        try:
            with db(self.project_path) as conn:
                row = conn.cursor().execute(
                    "SELECT file_name FROM files WHERE file_id=?", (fid,)).fetchone()
                if row:
                    return f"файл «{row['file_name']}»"
        except Exception:
            pass
        return "файл"

    def update_finish_button(self):
        """Кнопка «Завершить ревью» активна только при 100% в текущем скоупе."""
        btn = getattr(self, "btn_finish", None)
        if btn is None:
            return
        try:
            stats = self._scope_stats()
            total, remaining = stats["total"], stats["remaining"]
        except Exception:
            btn.setEnabled(False)
            return
        if total and remaining == 0:
            btn.setEnabled(True)
            btn.setToolTip(f"Всё размечено ({self._scope_name()}) — "
                           "сохранить версию датасета (снимок всех оценок)")
        else:
            btn.setEnabled(False)
            if total:
                btn.setToolTip(f"Осталось разметить: {remaining} ({self._scope_name()})")
            else:
                btn.setToolTip("Нет кейсов")

    def on_finish_review(self):
        """Итог по текущему скоупу + переход к сохранению версии датасета."""
        if not self._bad_can_leave():
            return
        from report_service import get_overall_report
        try:
            rep = get_overall_report(self.project_path, file_id=self._review_scope())
        except Exception as e:
            self.show_error("Не удалось посчитать итог", e)
            return
        scope = self._scope_name()
        logger.info("finish review pressed: scope=%s total=%s reviewed=%s",
                    scope, rep["total"], rep["reviewed"])
        if not rep["total"] or rep["reviewed"] < rep["total"]:
            notify(self, "warning", "Ещё не всё",
                   f"Осталось разметить: {rep['total'] - rep['reviewed']} ({scope})")
            return
        summary = (f"{scope.capitalize()}: проверено {rep['reviewed']} из {rep['total']}\n"
                   f"✅ Хорошо: {rep['good']}\n"
                   f"❌ Плохо: {rep['bad']}\n"
                   f"❓ Сомневаюсь: {rep['uncertain']}\n"
                   f"🔄 Дубль: {rep['duplicate']}\n"
                   f"⏭️ Пропущено: {rep['skip']}")
        if confirm(self, "Завершить ревью",
                   summary + "\n\nСохранить версию датасета?"):
            from datasets_dialog import DatasetsDialog
            DatasetsDialog(self.project_path, self).exec()

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

    @staticmethod
    def _style_tag_btn(btn, selected: bool) -> None:
        if selected:
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

    def toggle_tag(self, tag_id: int):
        added = tag_id not in self.selected_tags
        if tag_id in self.selected_tags:
            self.selected_tags.remove(tag_id)
        else:
            self.selected_tags.add(tag_id)
        self.save_tags()
        self._last_single = {"kind": "tag", "case_id": self.current_case_id,
                             "tag_id": tag_id, "added": added}
        if tag_id in self.tag_buttons:
            self._style_tag_btn(self.tag_buttons[tag_id],
                                tag_id in self.selected_tags)

    def save_comment_manual(self):
        """Явное «Сохранить» — запоминаем для одиночной отмены (Ctrl+Z)."""
        if not self.current_case_id:
            return
        prev = (self.current_case or {}).get("comment") or ""
        self.save_comment(silent=False)
        new = self.comment_edit.toPlainText().strip()
        if new != prev.strip():
            self._last_single = {"kind": "comment", "case_id": self.current_case_id,
                                 "old": prev, "new": new}

    def undo_single(self):
        """Отмена последнего одиночного действия (статус/тег/комментарий)."""
        act = getattr(self, "_last_single", None)
        if not act:
            notify(self, "warning", "Отмена", "Нечего отменять")
            return
        try:
            from database import utcnow as _utcnow
            now = _utcnow()
            with db(self.project_path) as conn:
                cur = conn.cursor()
                cid = act["case_id"]
                if act["kind"] == "status":
                    cur.execute("""
                        INSERT INTO annotations (case_id, status, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                    """, (cid, act["old"], now, act["old"], now))
                    cur.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'status_changed', 'status', ?, ?, ?)
                    """, (cid, act["new"], act["old"], now))
                elif act["kind"] == "comment":
                    cur.execute("""
                        INSERT INTO annotations (case_id, comment, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                    """, (cid, act["old"] or None, now, act["old"] or None, now))
                    cur.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'comment_changed', 'comment', ?, ?, ?)
                    """, (cid, act["new"], act["old"], now))
                elif act["kind"] == "tag":
                    if act["added"]:
                        cur.execute("DELETE FROM case_tags WHERE case_id=? AND tag_id=?",
                                    (cid, act["tag_id"]))
                        cur.execute("""
                            INSERT INTO history (case_id, event_type, field_name,
                                                 old_value, new_value, created_at)
                            VALUES (?, 'tag_removed', 'tag', ?, NULL, ?)
                        """, (cid, str(act["tag_id"]), now))
                    else:
                        cur.execute("INSERT OR IGNORE INTO case_tags "
                                    "(case_id, tag_id, created_at) VALUES (?, ?, ?)",
                                    (cid, act["tag_id"], now))
                        cur.execute("""
                            INSERT INTO history (case_id, event_type, field_name,
                                                 old_value, new_value, created_at)
                            VALUES (?, 'tag_added', 'tag', NULL, ?, ?)
                        """, (cid, str(act["tag_id"]), now))
                else:
                    return
        except Exception as e:
            self.show_error("Не удалось отменить", e)
            return
        self._last_single = None
        notify(self, "success", "Отмена", "Действие отменено")
        if self.case_ids and cid in self.case_ids:
            self.load_case(self.case_ids.index(cid))

    def open_similar(self):
        """Похожие на текущий кейс (только контекст, статус не ставится)."""
        if not self.current_case_id:
            return
        from similar_dialog import SimilarDialog
        dlg = SimilarDialog(self.project_path, self.current_case_id, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_case_id:
            self._jump_to_case(dlg.result_case_id)

    def open_bug_report(self):
        """Полный Bug Report из текущего кейса (контекст подставляется)."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import build_from_case
            prefill = build_from_case(self.project_path, self.current_case_id)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, prefill, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_id:
            notify(self, "success", "Баг", f"Создан баг #{dlg.result_id}")

    def open_quick_bug(self):
        """Быстрый баг: только заголовок, остальное — из кейса."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import build_from_case
            prefill = build_from_case(self.project_path, self.current_case_id)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import QuickBugDialog
        dlg = QuickBugDialog(self.project_path, prefill, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_id:
            notify(self, "success", "Баг", f"Создан баг #{dlg.result_id}")
            self.update_info_label()

    def open_case_bugs(self):
        """Баги кейса (ID/status/severity/title) — клик открывает баг."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import bugs_for_case
            items = bugs_for_case(self.project_path, self.current_case_id)
        except Exception as e:
            self.show_error("Не удалось загрузить баги", e)
            return
        if not items:
            notify(self, "warning", "Баги", "У кейса пока нет багов — создай 🐞")
            return
        menu = QMenu(self)
        for b in items:
            action = menu.addAction(
                f"#{b['bug_id']} [{b['status']}/{b['severity']}] {b['title'][:60]}")
            action.triggered.connect(
                lambda _c, bid=b["bug_id"]: self._open_bug_dialog(bid))
        anchor = getattr(self, "btn_case_bugs", None) or self
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _open_bug_dialog(self, bug_id: int):
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, None, bug_id, self)
        dlg.exec()
        self.update_info_label()

    def copy_case_context(self):
        """Контекст кейса в буфер без создания бага (§22)."""
        if not self.current_case_id:
            return
        menu = QMenu(self)
        for fmt, label in (("markdown", "Markdown"), ("plain", "Plain Text")):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _c, f=fmt, name=label: self._do_copy_context(f, name))
        anchor = getattr(self, "btn_context", None) or self
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _do_copy_context(self, fmt: str, label: str):
        from PySide6.QtGui import QGuiApplication
        import bug_export_service as bex
        try:
            text = bex.render_case(self.project_path, self.current_case_id, fmt)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        QGuiApplication.clipboard().setText(text)
        notify(self, "success", "Скопировано", f"Контекст ({label}) — в буфере")

    def open_duplicates(self):
        """Потенциальные дубли в области текущего фильтра/файла."""
        from similar_dialog import DuplicatesDialog
        fid = (self.filters or {}).get("file_id")
        dlg = DuplicatesDialog(self.project_path, fid, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_case_id:
            self._jump_to_case(dlg.result_case_id)

    def _jump_to_case(self, case_id: int):
        """Переход из похожих/дублей: строгий режим «Плохо» соблюдаем."""
        if not self._bad_can_leave():
            self.view_stack.setCurrentIndex(0)
            try:
                self.btn_toggle_view.setText("📋 Таблица")
            except Exception:
                pass
            return
        try:
            case_id = int(case_id)
        except (TypeError, ValueError):
            return
        if case_id in self.case_ids:
            self.view_stack.setCurrentIndex(0)
            try:
                self.btn_toggle_view.setText("📋 Таблица")
            except Exception:
                pass
            self.load_case(self.case_ids.index(case_id))
        else:
            notify(self, "warning", "Внимание",
                   "Кейс вне текущей выборки — сбрось фильтры, чтобы открыть его.")

    def on_create_tag(self):
        """Создать свой тег (ТЗ: пользовательские теги)."""
        text, ok = QInputDialog.getText(self, "Новый тег", "Название тега:")
        if not ok or not (text or "").strip():
            return
        name = text.strip()
        try:
            from tag_service import create_tag
            create_tag(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            self.update_tags_display(set(self.selected_tags))
        except Exception:
            pass
        notify(self, "success", "Тег", f"Тег «{name}» создан")

    def on_delete_tag(self):
        """Удалить неиспользуемый тег."""
        try:
            from tag_service import delete_tag, list_tags, usage_count
            tags = list_tags(self.project_path)
        except Exception as e:
            self.show_error("Не удалось загрузить теги", e)
            return
        if not tags:
            notify(self, "warning", "Теги", "Тегов нет")
            return
        names = []
        by_name = {}
        for t in tags:
            n = usage_count(self.project_path, t["tag_id"])
            label = f"{t['tag_name']} ({n} кейсов)"
            names.append(label)
            by_name[label] = t
        text, ok = QInputDialog.getItem(
            self, "Удалить тег", "Тег (удалить можно только неиспользуемый):",
            names, 0, False)
        if not ok or not text:
            return
        tag = by_name[text]
        if not confirm(self, "Удалить тег",
                       f"Удалить тег «{tag['tag_name']}»?",
                       ok_text="Удалить", cancel_text="Отмена"):
            return
        try:
            delete_tag(self.project_path, tag["tag_id"])
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.selected_tags.discard(tag["tag_id"])
        try:
            self.update_tags_display(set(self.selected_tags))
        except Exception:
            pass
        notify(self, "success", "Тег", f"Тег «{tag['tag_name']}» удалён")

    def save_tags(self):
        if not self.current_case_id:
            return
        try:
            from database import utcnow as _utcnow
            now = _utcnow()
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                old_rows = cursor.execute(
                    "SELECT tag_id FROM case_tags WHERE case_id=?",
                    (self.current_case_id,)).fetchall()
                old_ids = {r["tag_id"] for r in old_rows}
                new_ids = set(self.selected_tags)
                cursor.execute("DELETE FROM case_tags WHERE case_id = ?", (self.current_case_id,))
                for tag_id in new_ids:
                    cursor.execute("""
                        INSERT INTO case_tags (case_id, tag_id, created_at)
                        VALUES (?, ?, ?)
                    """, (self.current_case_id, tag_id, now))
                for tid in sorted(new_ids - old_ids):
                    cursor.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'tag_added', 'tag', NULL, ?, ?)
                    """, (self.current_case_id, str(tid), now))
                for tid in sorted(old_ids - new_ids):
                    cursor.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'tag_removed', 'tag', ?, NULL, ?)
                    """, (self.current_case_id, str(tid), now))
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
            from database import utcnow as _utcnow
            now = _utcnow()
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

    def _bad_reset(self) -> None:
        self._bad_pending = False
        self._bad_agreed = False
        self._bad_cause_done = False

    def _bad_can_leave(self) -> bool:
        """Можно ли уйти с кейса в строгом режиме (всегда True вне pending).

        Задумка: «Плохо» → комментарий → причина. Без комментария (если не
        согласился в мягком режиме) и без причины с кейса не уйти — смотреть
        таблицу и фильтры можно, перейти на другой кейс нельзя.
        """
        if not self._bad_pending:
            return True
        if not self._bad_agreed:
            comment = self.comment_edit.toPlainText().strip()
            if not comment:
                notify(self, "warning", "Заполните комментарий",
                       "Чтобы уйти с кейса: напиши комментарий, нажми «Плохо» "
                       "и укажи причину. Или выбери другой статус.")
                self.comment_edit.setFocus()
                return False
        if not self._bad_cause_done:
            notify(self, "warning", "Укажите причину",
                   "Нажми «Плохо» и выбери причину — "
                   "или выбери другой статус.")
            self.comment_edit.setFocus()
            return False
        return True

    def set_status(self, status: str):
        if not self.current_case_id:
            return
        # Настройки — свежие из БД, а не кэшированные: режимы
        # «мягкое/обязательное» должны работать сразу после смены в настройках
        try:
            self.settings = self.load_review_settings()
        except Exception as e:
            logger.warning("settings reload failed: %s", e)
        try:
            self.load_profile()
        except Exception as e:
            logger.warning("profile reload failed: %s", e)
        # Выход из строгого режима — выбором любого не-«плохого» статуса
        # (base-семантика: свои коды с base 'bad' — тоже «плохие»).
        is_bad = self._status_base(status) == "bad"
        if not is_bad:
            self._bad_reset()
        comment = self.comment_edit.toPlainText().strip()
        profile_cfg = (getattr(self, "profile", None) or {}).get("config", {})
        comment_mode = profile_cfg.get("require_comment_for_bad", None)
        if comment_mode is None:
            comment_mode = self.settings.get('require_comment_for_bad', 'warn')
        if is_bad:
            if not comment:
                if comment_mode == 'required':
                    notify(
                        self,
                        "warning",
                        "Требуется комментарий",
                        "Для статуса «Плохо» необходимо добавить комментарий. "
                        "Переход заблокирован: напиши комментарий, нажми «Плохо» "
                        "и укажи причину. Или выбери другой статус."
                    )
                    self._bad_pending = True
                    self._bad_agreed = False
                    self._bad_cause_done = False
                    self.save_indicator.setText(
                        "✏️ Напиши комментарий и снова нажми «Плохо»")
                    self.comment_edit.setFocus()
                    return
                # warn: «Да» = согласие идти без комментария (единственное
                # исключение), «Нет» = строгий режим до комментария + причины.
                if not confirm(
                    self,
                    "Рекомендация",
                    "Для статуса «Плохо» рекомендуется добавить комментарий.\n\n"
                    "Продолжить без комментария?",
                    ok_text="Да",
                    cancel_text="Нет",
                ):
                    self._bad_pending = True
                    self._bad_agreed = False
                    self._bad_cause_done = False
                    self.save_indicator.setText(
                        "✏️ Напиши комментарий и снова нажми «Плохо»")
                    notify(self, "warning", "Заполните комментарий",
                           "Переход заблокирован: напиши комментарий, нажми "
                           "«Плохо» и укажи причину. Или выбери другой статус.")
                    self.comment_edit.setFocus()
                    return
                self._bad_pending = True
                self._bad_agreed = True
                self._bad_cause_done = False
        try:
            from database import utcnow as _utcnow2
            now = _utcnow2()
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
            if old_status != status:
                self._last_single = {"kind": "status",
                                     "case_id": self.current_case_id,
                                     "old": old_status, "new": status}
            if is_bad:
                # Причина обязательна в строгом режиме и по профилю
                # («Профили → Причина обязательна для Плохо»).
                # Пропуск разрешён только вне pending при выключенном флаге.
                pending = self._bad_pending
                required_by_profile = bool(profile_cfg.get(
                    "require_category_for_bad", False))
                if pending or required_by_profile:
                    completed = self._ask_error_cause()
                    if not completed:
                        self._bad_pending = True
                        notify(self, "warning", "Укажите причину",
                               "Без причины с кейса не уйти. "
                               "Нажми «Плохо» и выбери причину — "
                               "или выбери другой статус.")
                        self.update_info_label()
                        return
                    self._bad_cause_done = True
                    self._bad_pending = False
                elif comment and not self._bad_cause_done:
                    # Разовый вопрос без блокировки.
                    if self._ask_error_cause():
                        self._bad_cause_done = True
            self.update_info_label()
            self.save_indicator.setText(f"💾 Статус сохранён: {status}")
            if self.settings.get('auto_next_case', True):
                self.next_case()
        except Exception as e:
            self.show_error("Не удалось сохранить статус", e)

    def _ask_error_cause(self) -> bool:
        """Быстрый выбор причины после «Плохо» (ТЗ §23).

        Возвращает True, если причина выбрана и сохранена.
        При сломанной таксономии/диалоге возвращает False, чтобы обязательный
        режим не пропускался молча, — выйти можно другим статусом.
        """
        try:
            from taxonomy_dialog import ErrorCauseDialog
            from taxonomy_service import set_case_error
        except Exception as e:
            logger.warning("taxonomy unavailable: %s", e)
            notify(self, "error", "Таксономия",
                   "Не удалось открыть выбор причины. Выбери другой статус "
                   "или исправь таксономию в настройках.")
            return False
        try:
            dlg = ErrorCauseDialog(self.project_path, self,
                                   case_id=self.current_case_id)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result:
                cat_id, sub_id, sev = dlg.result
                set_case_error(self.project_path, self.current_case_id,
                               cat_id, sub_id, sev)
                # подтянем имена для шапки
                from taxonomy_service import get_case_error
                self.current_error = get_case_error(
                    self.project_path, self.current_case_id)
                return True
            return False
        except Exception as e:
            logger.warning("error cause dialog failed: %s", e)
            notify(self, "error", "Таксономия",
                   f"Не удалось сохранить причину: {e}")
            return False

    def _next_index(self) -> int | None:
        """Следующий индекс с учётом настроек перехода (ТЗ §11).

        skip_reviewed — пропускать размеченные; no_return_good — пропускать
        «Хорошо»; checks_first — сначала кейсы с автопроверками.
        Возвращает None, если подходящих впереди нет.
        """
        nxt = self.current_index + 1
        if nxt >= len(self.case_ids):
            return None
        if not (self.settings.get('skip_reviewed') or self.settings.get('checks_first')
                or self.settings.get('no_return_good')):
            return nxt
        remaining = self.case_ids[nxt:]
        try:
            with db(self.project_path) as conn:
                cur = conn.cursor()
                statuses: dict = {}
                flagged: set = set()
                for i in range(0, len(remaining), 500):
                    chunk = remaining[i:i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    for r in cur.execute(
                            f"SELECT case_id, status FROM annotations "
                            f"WHERE case_id IN ({ph})", chunk).fetchall():
                        statuses[r["case_id"]] = r["status"]
                    for r in cur.execute(
                            f"SELECT DISTINCT case_id FROM case_checks "
                            f"WHERE case_id IN ({ph})", chunk).fetchall():
                        flagged.add(r["case_id"])
        except Exception as e:
            logger.warning("next-index fallback: %s", e)
            return nxt
        order = list(remaining)
        if self.settings.get('checks_first'):
            order.sort(key=lambda cid: (cid not in flagged))
        for cid in order:
            st = statuses.get(cid, "unreviewed")
            base = self._status_base(st)
            if self.settings.get('skip_reviewed') and base != "unreviewed":
                continue
            if self.settings.get('no_return_good') and base == "good":
                continue
            return self.case_ids.index(cid)
        return None

    def next_case(self):
        if not self._bad_can_leave():
            return
        nxt = self._next_index()
        if nxt is not None:
            self.load_case(nxt)
            return
        # Последний кейс выборки: если текущий скоуп готов — тихая подсказка
        # про версию датасета (без модалок и без флагов «один раз»).
        try:
            stats = self._scope_stats()
            complete = stats["total"] > 0 and stats["remaining"] == 0
        except Exception:
            complete = False
        logger.info("last case reached: scope=%s complete=%s",
                    self._scope_name(), complete)
        if complete:
            notify(self, "success", "Ревью завершено",
                   f"Всё размечено ({self._scope_name()}). Сохрани версию датасета "
                   "кнопкой «🏁 Завершить ревью».")
        else:
            notify(self, "success", "Конец", "🎉 Это последний кейс в выборке")

    def prev_case(self):
        if not self._bad_can_leave():
            return
        if self.current_index > 0:
            self.load_case(self.current_index - 1)
        else:
            notify(self, "success", "Начало", "📍 Это первый кейс в выборке")

    def on_back(self):
        if not self._bad_can_leave():
            return
        if self.current_case_id:
            self.save_comment(silent=True)
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.review_closed.emit()
