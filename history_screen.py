from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QTextBrowser
)
from PySide6.QtCore import Qt, Signal
from database import db
from ui_base import BaseScreen
from ui_compat import (FComboBox, FPushButton, clear_in_fluent, notify,
                        polish_table)
import history_service as hs


class HistoryScreen(BaseScreen):
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

        self.event_filter = FComboBox()
        self.event_filter.addItem("Все события", None)
        self.event_filter.addItem("Изменение статуса", "status_changed")
        self.event_filter.addItem("Изменение комментария", "comment_changed")
        self.event_filter.addItem("Добавление тега", "tag_added")
        self.event_filter.addItem("Удаление тега", "tag_removed")
        self.event_filter.addItem("Причина ошибки", "category_changed")
        self.event_filter.addItem("Вердикт проверки", "check_verdict")
        self.event_filter.addItem("Просмотрено", "viewed_changed")
        self.event_filter.addItem("Массовая операция", "bulk_undone")
        self.event_filter.addItem("Баг создан", "BUG_CREATED")
        self.event_filter.addItem("Баг: статус", "BUG_STATUS_CHANGED")
        self.event_filter.addItem("Баг: кейсы", "BUG_CASES")
        self.event_filter.currentIndexChanged.connect(self.load_history)
        filter_layout.addWidget(self.event_filter)
        filter_layout.addWidget(QLabel("Кейс (ID/№):"))
        from ui_compat import FLineEdit
        self.case_filter = FLineEdit()
        self.case_filter.setPlaceholderText("ID из маппинга или №")
        self.case_filter.setMaximumWidth(160)
        self.case_filter.returnPressed.connect(self.load_history)
        filter_layout.addWidget(self.case_filter)
        btn_apply_case = FPushButton("Найти")
        btn_apply_case.clicked.connect(self.load_history)
        filter_layout.addWidget(btn_apply_case)
        layout.addLayout(filter_layout)

        # Поиск по тексту + даты + поле
        search_layout = QHBoxLayout()
        search_layout.addWidget(QLabel("Текст:"))
        self.text_filter = FLineEdit()
        self.text_filter.setPlaceholderText("событие, поле, было, стало, комментарий…")
        self.text_filter.returnPressed.connect(self.load_history)
        search_layout.addWidget(self.text_filter, 3)
        search_layout.addWidget(QLabel("Поле:"))
        self.field_combo = FComboBox()
        self.field_combo.addItem("Все поля", None)
        search_layout.addWidget(self.field_combo)
        search_layout.addWidget(QLabel("С:"))
        self.date_from = FLineEdit()
        self.date_from.setPlaceholderText("ГГГГ-ММ-ДД")
        self.date_from.setMaximumWidth(120)
        search_layout.addWidget(self.date_from)
        search_layout.addWidget(QLabel("По:"))
        self.date_to = FLineEdit()
        self.date_to.setPlaceholderText("ГГГГ-ММ-ДД")
        self.date_to.setMaximumWidth(120)
        search_layout.addWidget(self.date_to)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # Таблица истории
        self.history_table = QTableWidget()
        from styles import COLORS as _CC
        self.history_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {_CC['bg_input']};
                border: 2px solid {_CC['green_bright']};
                color: {_CC['text_bright']};
                font-size: 13px;
                gridline-color: {_CC['green_deep']};
            }}
            QTableWidget::item {{
                padding: 6px;
            }}
            QHeaderView::section {{
                background-color: {_CC['green_deep']};
                color: {_CC['text_bright']};
                border: 1px solid {_CC['green_bright']};
                padding: 8px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.history_table)
        clear_in_fluent(self.history_table)
        polish_table(self.history_table, stretch_last=True)

        # Кнопки
        buttons_layout = QHBoxLayout()

        btn_refresh = FPushButton("Обновить")
        btn_refresh.clicked.connect(self.load_history)

        btn_open = FPushButton("➡️ Открыть кейс")
        btn_open.setToolTip("Открыть выбранную запись в ревью")
        btn_open.clicked.connect(self.open_case)

        btn_back = FPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.clicked.connect(self.on_back)

        buttons_layout.addWidget(btn_refresh)
        buttons_layout.addWidget(btn_open)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)

        self.detail = QTextBrowser()
        self.detail.setMaximumHeight(120)
        self.detail.setPlaceholderText("Выбери запись — здесь было/стало с подсветкой diff.")
        layout.addWidget(self.detail)
        try:
            clear_in_fluent(self.detail)
        except Exception:
            pass

        self.setLayout(layout)

    def load_history(self):
        """Загружает историю: фильтры + текстовый поиск (сервис)."""
        event_type = self.event_filter.currentData()
        if event_type == "BUG_CASES":
            event_filter_value = None
            bug_cases_only = True
        else:
            event_filter_value, bug_cases_only = event_type, False
        case_text = ""
        try:
            case_text = self.case_filter.text().strip()
        except Exception:
            pass
        case_ids: list | None = None
        if case_text:
            # ID = идентификатор из маппинга (source_id, любой текст)
            # или внутренний номер кейса.
            try:
                with db(self.project_path) as conn:
                    rows = conn.cursor().execute(
                        "SELECT case_id FROM cases WHERE source_id = ? "
                        "OR CAST(case_id AS TEXT) = ?",
                        (case_text, case_text)).fetchall()
                case_ids = [r["case_id"] for r in rows]
            except Exception as e:
                notify(self, "error", "Ошибка", str(e))
                return
            if not case_ids:
                notify(self, "warning", "Фильтр",
                       f"Кейс «{case_text}» не найден")
                return
        try:
            self._reload_field_combo()
            events = hs.search_history(
                self.project_path,
                text=self.text_filter.text() if hasattr(self, "text_filter") else "",
                event=event_filter_value,
                case_ids=case_ids,
                field=self.field_combo.currentData()
                if hasattr(self, "field_combo") else None,
                date_from=(self.date_from.text().strip() or None)
                if hasattr(self, "date_from") else None,
                date_to=(self.date_to.text().strip() or None)
                if hasattr(self, "date_to") else None)
            if bug_cases_only:
                events = [e for e in events if e["event_type"] in (
                    "BUG_CASE_ADDED", "BUG_CASE_REMOVED")]
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось загрузить историю: {str(e)}")
            return
        self._events = events
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
            'category_changed': 'Причина ошибки',
            'check_confirmed': 'Проверка подтверждена',
            'check_rejected': 'Проверка отклонена',
            'check_verdict_cleared': 'Вердикт снят',
            'viewed_changed': 'Просмотрено',
            'bulk_undone': 'Отмена bulk',
            'BUG_CREATED': 'Баг создан',
            'BUG_UPDATED': 'Баг обновлён',
            'BUG_STATUS_CHANGED': 'Баг: статус',
            'BUG_CASE_ADDED': 'Баг: +кейс',
            'BUG_CASE_REMOVED': 'Баг: −кейс',
            'BUG_EXTERNAL_LINKED': 'Баг: трекер',
        }
        for row, event in enumerate(events):
            created = (event['created_at'] or '')[:19]
            self.history_table.setItem(row, 0, QTableWidgetItem(created))
            self.history_table.setItem(
                row, 1, QTableWidgetItem(str(event['case_id'] or '')))
            self.history_table.setItem(
                row, 2, QTableWidgetItem(event['file_name'] or '(удалён)'))
            self.history_table.setItem(
                row, 3, QTableWidgetItem(
                    event_names.get(event['event_type'], event['event_type'])))
            self.history_table.setItem(row, 4, QTableWidgetItem(event['field_name'] or ''))
            self.history_table.setItem(row, 5, QTableWidgetItem(
                (event['old_value'] or '')[:80]))
            self.history_table.setItem(row, 6, QTableWidgetItem(
                (event['new_value'] or '')[:80]))
            self.history_table.item(row, 0).setData(
                Qt.ItemDataRole.UserRole, row)
        self.history_table.resizeColumnsToContents()
        try:
            self.history_table.itemSelectionChanged.disconnect()
        except Exception:
            pass
        self.history_table.itemSelectionChanged.connect(self._show_detail)

    def _reload_field_combo(self):
        try:
            current = self.field_combo.currentData()
        except Exception:
            return
        try:
            fields = hs.distinct_fields(self.project_path)
        except Exception:
            fields = []
        self.field_combo.blockSignals(True)
        self.field_combo.clear()
        self.field_combo.addItem("Все поля", None)
        for f in fields:
            self.field_combo.addItem(f, f)
        for i in range(self.field_combo.count()):
            if self.field_combo.itemData(i) == current:
                self.field_combo.setCurrentIndex(i)
                break
        self.field_combo.blockSignals(False)

    def _show_detail(self):
        """Было/стало выбранной записи с визуальным diff."""
        item = self.history_table.currentItem()
        if item is None:
            return
        ref = self.history_table.item(item.row(), 0)
        idx = ref.data(Qt.ItemDataRole.UserRole) if ref else None
        if idx is None or idx >= len(getattr(self, "_events", [])):
            return
        ev = self._events[idx]
        try:
            from diff_service import word_diff_html
            old_html, new_html = word_diff_html(ev.get("old_value"),
                                               ev.get("new_value"))
        except Exception:
            old_html, new_html = (ev.get("old_value") or ""), (ev.get("new_value") or "")
        self.detail.setHtml(
            f"<b>{ev.get('event_type')}</b> · кейс {ev.get('case_id')} · "
            f"{(ev.get('created_at') or '')[:19]}<br>"
            f"<b>Было:</b> {old_html}<br><b>Стало:</b> {new_html}")

    def open_case(self):
        """Открыть кейс выбранной записи в ревью."""
        item = self.history_table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери запись в таблице")
            return
        ref = self.history_table.item(item.row(), 0)
        idx = ref.data(Qt.ItemDataRole.UserRole) if ref else None
        events = getattr(self, "_events", [])
        if idx is None or idx >= len(events):
            return
        case_id = events[idx].get("case_id")
        if not case_id:
            notify(self, "warning", "Внимание", "У записи нет кейса")
            return
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is None or not hasattr(mw, "show_screen"):
            return
        mw.show_screen("review")
        try:
            screen = mw.project_window.screens.get("review")
            if screen is not None and case_id in (screen.case_ids or []):
                screen.load_case(screen.case_ids.index(case_id))
            else:
                notify(self, "warning", "Внимание",
                       "Кейса нет в текущей выборке ревью — сбрось фильтры там.")
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def refresh(self):
        self.load_history()

    def on_back(self):
        """Возврат к проекту."""
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.history_closed.emit()
