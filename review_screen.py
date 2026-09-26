from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QScrollArea, QStackedWidget,
)
from PySide6.QtCore import Qt, Signal, QTimer
from ui_base import BaseScreen
from ui_compat import (
    FPushButton, accent_button_style, clear_in_fluent,
    notify,
)
import logging

from review_bulk import BulkMixin
from review_case import CaseMixin
from review_profile import ProfileMixin
from review_table import TableMixin
from review_verdicts import VerdictsMixin


logger = logging.getLogger(__name__)


class _FitStack(QStackedWidget):
    """Стек высотой по текущей странице (рескин: иначе таблица тянется
    по длинной странице кейса и футер с номерами уезжает за скролл)."""

    def sizeHint(self):
        try:
            w = self.currentWidget()
            if w is not None:
                return w.sizeHint()
        except Exception:
            pass
        return super().sizeHint()

    def minimumSizeHint(self):
        try:
            w = self.currentWidget()
            if w is not None:
                return w.minimumSizeHint()
        except Exception:
            pass
        return super().minimumSizeHint()


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
        self.value_filter_like = False
        self.value_search_text = ""
        # Теги раскрыты или нет
        self.tags_expanded = False
        # Массовые операции (ТЗ §5): выбранные кейсы
        self.bulk_selected: set = set()
        # Последнее одиночное действие для Ctrl+Z
        self._last_single = None
        # «Завершить ревью» уже нажимали: кнопка гаснет до новой разметки
        self._review_finished = False
        # Умная очередь (ТЗ §8): normal | unreviewed | problematic
        self.queue_mode = "normal"
        # Показ скрытых в таблице (серыми); в кейсах их нет никогда.
        self.show_hidden = False
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

    def resizeEvent(self, event):
        """Форвардер рефита таблицы (виртуалки из миксинов Qt не вызывает)."""
        try:
            self._refit_on_resize()
        except Exception:
            pass
        try:
            super().resizeEvent(event)
        except Exception:
            pass

    def snapshot_session(self) -> dict:
        """V2.1 P0 §5: текущее место ревью (координация, без бизнес-логики)."""
        try:
            filt = None
            if isinstance(getattr(self, "filters", None), dict):
                import copy as _cp
                filt = _cp.deepcopy(self.filters)
            # file_id: из активного фильтра, иначе из текущего кейса
            fid = (filt or {}).get("file_id")
            if not fid and getattr(self, "current_case", None):
                try:
                    fid = self.current_case.get("file_id")
                except Exception:
                    fid = None
            return {
                "screen": "review",
                "file_id": fid if isinstance(fid, int) else None,
                "case_id": self.current_case_id,
                "queue": getattr(self, "queue_mode", "normal"),
                "filters": filt,
                "columns": list(getattr(self, "selected_columns", []) or []),
                "sort": getattr(self, "table_sort", "import"),
                "page": int(getattr(self, "current_page", 0) or 0),
                "view": int(getattr(self, "view_stack", None).currentIndex()
                            if getattr(self, "view_stack", None) is not None else 0),
            }
        except Exception:
            return {"screen": "review"}

    def restore_session(self, state: dict) -> None:
        """Применить снапшот; битые куски пропускаем, остаёмся на живом."""
        try:
            if not isinstance(state, dict):
                return
            if isinstance(state.get("columns"), list) and state["columns"]:
                self.selected_columns = [c for c in state["columns"]
                                         if isinstance(c, str)][:64]
            if state.get("sort") in ("import", "unreviewed_first",
                                     "problematic_first"):
                self.table_sort = state["sort"]
            if state.get("queue") in ("normal", "unreviewed", "problematic"):
                self.queue_mode = state["queue"]
            if isinstance(state.get("filters"), dict):
                self.filters = dict(state["filters"])
            elif state.get("file_id"):
                self.filters = {"file_id": state["file_id"]}
            try:
                self.current_page = max(0, int(state.get("page", 0)))
            except (TypeError, ValueError):
                self.current_page = 0
            self.load_case_ids()
            cid = state.get("case_id")
            if cid in (self.case_ids or []):
                self.load_case(self.case_ids.index(cid))
            elif self.case_ids:
                self.load_case(0)
            try:
                if state.get("view") in (0, 1) and hasattr(self, "view_stack"):
                    self.view_stack.setCurrentIndex(int(state["view"]))
            except Exception:
                pass
            self.update_filter_indicator()
            self.update_queue_indicator()
            try:
                self.load_table_data()
            except Exception:
                pass
        except Exception:
            pass

    def update_stat_cards(self):
        """Пересчёт карточек шапки (base-семантика, скрытые вне счёта).

        Правило охвата: при фильтре по файлу карточки показывают файл,
        иначе проект (индикатор фильтров сообщает о скоупе).
        """
        if not hasattr(self, "_stat_cards"):
            return
        try:
            fid = (self.filters or {}).get("file_id")
        except Exception:
            fid = None
        try:
            from report_service import get_overall_report
            rep = get_overall_report(self.project_path, fid)
        except Exception:
            return
        try:
            total = int(rep.get("total", 0) or 0)
            vals = {
                "total": (total, ""),
                "reviewed": (int(rep.get("reviewed", 0) or 0), "проверено"),
                "bad": (int(rep.get("bad", 0) or 0), "плохих"),
                "uncertain": (int(rep.get("uncertain", 0) or 0), "сомнений"),
                "duplicate": (int(rep.get("duplicate", 0) or 0), "дублей"),
            }
            for key, (val, _caption) in vals.items():
                slot = self._stat_cards.get(key)
                if not slot:
                    continue
                vlab, slab = slot
                vlab.setText(f"{val:,}".replace(",", " "))
                if key == "total":
                    slab.setText("в файле" if fid else "в проекте")
                else:
                    pct = (100.0 * val / total) if total else 0.0
                    slab.setText(f"{pct:.0f}%")
        except Exception:
            pass

    def _tick_clip_pill(self):
        """Пилюля буфера: остаток автоочистки или скрыть (чужое/пусто/выкл)."""
        try:
            import clipboard_service as _clip
            left = _clip.countdown_state()
        except Exception:
            left = None
        try:
            if left is None:
                if self.clip_pill.isVisible():
                    self.clip_pill.setVisible(False)
                return
            self.clip_pill.setText(f"⏳ До сброса буфера: {left} сек.")
            if not self.clip_pill.isVisible():
                self.clip_pill.setVisible(True)
        except Exception:
            pass

    def ensure_visible_case(self, case_id: int) -> bool:
        """Открыть кейс, даже если он вне текущей выборки.

        Прыжки (импорт разметки, баги, история) не должны упираться в чужой
        фильтр молча: вне выборки — сбрасываем фильтры и открываем.
        """
        try:
            if case_id in (self.case_ids or []):
                self.load_case(self.case_ids.index(case_id))
                return True
            self.filters = {}
            self.current_page = 0
            self.load_case_ids()
            self.update_filter_indicator()
            try:
                self.load_table_data()
            except Exception:
                pass
            if case_id in (self.case_ids or []):
                self.load_case(self.case_ids.index(case_id))
                try:
                    self.view_stack.setCurrentIndex(0)
                except Exception:
                    pass
                notify(self, "warning", "Фильтры",
                       "Кейс был вне выборки — фильтры сброшены.")
                return True
        except Exception:
            pass
        return False

    def focus_work_area(self):
        """V2.1 P0 §6.5: фокус остаётся в рабочей области, не на кнопке."""
        try:
            from PySide6.QtWidgets import QApplication as _QA
            fw = _QA.focusWidget()
            from PySide6.QtWidgets import QLineEdit, QTextEdit, QComboBox, QSpinBox
            if isinstance(fw, (QLineEdit, QTextEdit, QComboBox, QSpinBox)):
                return
            try:
                from ui_compat import FComboBox as _FC, FLineEdit as _FL
                from ui_compat import FTextEdit as _FT
                if isinstance(fw, tuple(t for t in (_FL, _FT, _FC)
                                        if isinstance(t, type))):
                    return
            except Exception:
                pass
            tgt = getattr(self, "view_stack", None) or self
            tgt.setFocus()
        except Exception:
            pass

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
        from styles import COLORS as _CC
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {_CC['bg_dark']};
            }}
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

        # Пилюля буфера (V2.2 §3): видна только пока тикает автоочистка.
        # Общая для кейса и таблицы (шапка вне view_stack).
        self.clip_pill = QLabel("")
        from styles import COLORS as _CC
        self.clip_pill.setStyleSheet(
            f"font-size: 12px; color: {_CC['blue']}; font-weight: bold;")
        self.clip_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.clip_pill.setVisible(False)
        layout.addWidget(self.clip_pill)
        self._clip_timer = QTimer(self)
        self._clip_timer.setInterval(1000)
        self._clip_timer.timeout.connect(self._tick_clip_pill)
        self._clip_timer.start()

        # Карточки статистики (референс: Всего / Проверено / С ошибками /
        # Сомневаюсь / Дубликаты). Только чтение, скоуп — проект.
        # Нейтральный полупрозрачный фон: видно на любой теме без знания
        # палитры; семантические цвета значений читаются и на тёмной,
        # и на светлой.
        from PySide6.QtWidgets import QHBoxLayout as _HB, QFrame as _FR
        from styles import SEMANTIC as _SEM
        cards_row = _HB()
        cards_row.setSpacing(8)
        self._stat_cards: dict = {}
        for _key, _title, _color in (
                ("total", "Всего кейсов", ""),
                ("reviewed", "Проверено", _SEM["success"]),
                ("bad", "С ошибками", _SEM["danger"]),
                ("uncertain", "Сомневаюсь", _SEM["warning"]),
                ("duplicate", "Дубликаты", _SEM["info"])):
            _frame = _FR()
            _frame.setStyleSheet(
                "QFrame { background: rgba(127, 127, 127, 0.08);"
                " border: 1px solid rgba(127, 127, 127, 0.25);"
                " border-radius: 8px; }")
            _box = QVBoxLayout()
            _box.setSpacing(0)
            _box.setContentsMargins(10, 6, 10, 6)
            _t = QLabel(_title)
            _t.setStyleSheet("font-size: 11px; border: none; background: transparent;")
            _t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _v = QLabel("—")
            _v.setStyleSheet(
                f"font-size: 18px; font-weight: bold; border: none;"
                f" background: transparent;{(' color: ' + _color + ';') if _color else ''}")
            _v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _s = QLabel("")
            _s.setStyleSheet("font-size: 10px; border: none; background: transparent;")
            _s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _box.addWidget(_t)
            _box.addWidget(_v)
            _box.addWidget(_s)
            _frame.setLayout(_box)
            cards_row.addWidget(_frame)
            self._stat_cards[_key] = (_v, _s)
        layout.addLayout(cards_row)
        self.update_stat_cards()

        # Информация о кейсе (пилот Review шаг 1: компактная шапка
        # как в референсе Проверка — влево, в одну строку, короткий ID).
        self.info_label = QLabel()
        from styles import COLORS as _CC2
        self.info_label.setStyleSheet(
            f"font-size: 13px; color: {_CC2['green_dark']}; font-weight: bold;")
        self.info_label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.info_label.setWordWrap(True)
        layout.addWidget(self.info_label)

        # Индикатор фильтров (пилот шаг 1: влево, компактно).
        self.filter_indicator = QLabel()
        from styles import COLORS as _CC3
        self.filter_indicator.setStyleSheet(
            f"font-size: 11px; color: {_CC3['amber']};")
        self.filter_indicator.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.filter_indicator.setWordWrap(True)
        layout.addWidget(self.filter_indicator)
        self.update_filter_indicator()

        # Кнопка переключения вида
        self.btn_toggle_view = FPushButton("📋 Таблица")
        self.btn_toggle_view.setMinimumHeight(30)
        self.btn_toggle_view.setStyleSheet(
            accent_button_style(" padding: 6px 12px;"))
        self.btn_toggle_view.clicked.connect(self.toggle_view)
        layout.addWidget(self.btn_toggle_view)

        # Стек видов (адаптивный: высота по текущей странице).
        self.view_stack = _FitStack()
        # Вид 1: Один кейс
        self.case_view = self.create_case_view()
        self.view_stack.addWidget(self.case_view)
        # Вид 2: Таблица
        self.table_view = self.create_table_view()
        self.view_stack.addWidget(self.table_view)
        layout.addWidget(self.view_stack, 1)
        try:
            self.view_stack.currentChanged.connect(
                lambda _i: self.view_stack.updateGeometry())
        except Exception:
            pass

        content_widget.setLayout(layout)
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        clear_in_fluent(scroll)
        self.setLayout(main_layout)
        # Якоря для вьюпорт-фита таблицы (рескин): table view ужимает
        # таблицу под высоту окна, чтобы футер с номерами был виден.
        self._review_scroll = scroll
        self._review_content = content_widget
