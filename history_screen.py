from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QTextBrowser, QDialog,
)
from PySide6.QtCore import Qt, Signal
from database import db
from ui_base import BaseScreen
from ui_compat import (FComboBox, FPushButton, clear_in_fluent, notify,
                        polish_table, format_dt as _fdt,
                        parse_date_input as _pdi)
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
        self.date_from.setPlaceholderText("ДД-ММ-ГГГГ")
        self.date_from.setMaximumWidth(120)
        search_layout.addWidget(self.date_from)
        search_layout.addWidget(QLabel("По:"))
        self.date_to = FLineEdit()
        self.date_to.setPlaceholderText("ДД-ММ-ГГГГ")
        self.date_to.setMaximumWidth(120)
        search_layout.addWidget(self.date_to)
        search_layout.addStretch()
        layout.addLayout(search_layout)

        # Таблица истории
        self.history_table = QTableWidget()
        try:
            from PySide6.QtWidgets import QAbstractItemView as _AIV
            self.history_table.setSelectionBehavior(
                _AIV.SelectionBehavior.SelectRows)
            self.history_table.setSelectionMode(
                _AIV.SelectionMode.ExtendedSelection)
        except Exception:
            pass
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

        btn_compare = FPushButton("⇄ Сравнить 2 записи")
        btn_compare.setToolTip("Выдели ровно 2 записи одного кейса: "
                               "что было / что стало")
        btn_compare.clicked.connect(self.compare_selected)
        self.btn_compare = btn_compare

        btn_now = FPushButton("⇄ С текущим")
        btn_now.setToolTip("Выдели 1 запись: сравнить её с нынешним "
                           "состоянием кейса")
        btn_now.clicked.connect(self.compare_with_now)
        buttons_layout.addWidget(btn_now)

        btn_back = FPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.clicked.connect(self.on_back)

        buttons_layout.addWidget(btn_refresh)
        buttons_layout.addWidget(btn_open)
        buttons_layout.addWidget(btn_compare)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)

        self.lifecycle_label = QLabel("")
        self.lifecycle_label.setWordWrap(True)
        layout.addWidget(self.lifecycle_label)

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
                date_from=(_pdi(self.date_from.text()) or None)
                if hasattr(self, "date_from") else None,
                date_to=(_pdi(self.date_to.text()) or None)
                if hasattr(self, "date_to") else None)
            if bug_cases_only:
                events = [e for e in events if e["event_type"] in (
                    "BUG_CASE_ADDED", "BUG_CASE_REMOVED")]
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось загрузить историю: {str(e)}")
            return
        self._events = events
        self._refresh_lifecycle(case_ids)
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
            created = _fdt(event['created_at'])
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
            f"{_fdt(ev.get('created_at'))}<br>"
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

    def _refresh_lifecycle(self, case_ids: list | None) -> None:
        """Одна строка жизненного цикла, если в игре ровно один кейс."""
        try:
            self.lifecycle_label.setText("")
        except Exception:
            pass
        ids = list(dict.fromkeys(case_ids or []))
        if len(ids) != 1:
            return
        try:
            life = hs.case_lifecycle(self.project_path, ids[0])
        except Exception:
            return
        if not (life.get("total") or 0):
            return
        parts = [f"событий: {life['total']}"]
        if life.get("status_changes"):
            parts.append(f"вердиктов: {life['status_changes']}")
        if life.get("comments"):
            parts.append(f"комментариев: {life['comments']}")
        if life.get("categories"):
            parts.append(f"причин: {life['categories']}")
        if life.get("tags_added") or life.get("tags_removed"):
            parts.append(f"теги: +{life.get('tags_added', 0)}/"
                         f"−{life.get('tags_removed', 0)}")
        if life.get("bugs"):
            parts.append(f"баги: {life['bugs']}")
        try:
            self.lifecycle_label.setText(
                f"Жизненный цикл кейса {life['case_id']}: "
                + "; ".join(parts))
        except Exception:
            pass

    def _selected_event_ids(self) -> list:
        """history_id ровно 2 выбранных записей (иначе [])."""
        out = []
        try:
            sm = self.history_table.selectionModel()
            rows = sorted({i.row() for i in sm.selectedRows()})
            events = getattr(self, "_events", []) or []
            for r in rows:
                ref = self.history_table.item(r, 0)
                idx = ref.data(Qt.ItemDataRole.UserRole) if ref else None
                if idx is not None and 0 <= idx < len(events):
                    out.append(events[idx])
        except Exception:
            pass
        return out

    def compare_selected(self):
        """Сравнение двух записей: что было / что стало."""
        sel = self._selected_event_ids()
        if len(sel) != 2:
            notify(self, "warning", "Сравнение",
                   "Выдели ровно 2 записи (Ctrl+клик).")
            return
        cids = {e.get("case_id") for e in sel}
        if len(cids) != 1 or None in cids:
            notify(self, "warning", "Сравнение",
                   "Записи должны быть одного кейса.")
            return
        try:
            res = hs.compare_states(
                self.project_path, sel[0]["case_id"],
                sel[0]["history_id"], sel[1]["history_id"])
        except ValueError as e:
            notify(self, "warning", "Сравнение", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        dlg = StateCompareDialog(res, self)
        dlg.exec()

    def compare_with_now(self):
        """Одна запись → сравнить с нынешним состоянием кейса."""
        sel = self._selected_event_ids()
        if len(sel) != 1:
            notify(self, "warning", "Сравнение",
                   "Выдели ровно 1 запись (текущее подставится само).")
            return
        try:
            res = hs.compare_states(
                self.project_path, sel[0]["case_id"],
                sel[0]["history_id"], None)
        except ValueError as e:
            notify(self, "warning", "Сравнение", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        dlg = StateCompareDialog(res, self)
        dlg.exec()


class StateCompareDialog(QDialog):
    """Было/стало между двумя записями истории (только чтение)."""

    def __init__(self, res: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Сравнение состояний кейса")
        self.setMinimumSize(560, 380)
        layout = QVBoxLayout()
        try:
            from ui_compat import format_dt as _fdt
            _b = _fdt(res.get("b_at")) if res.get("b_at") else "текущее"
            head = QLabel(f"Кейс {res.get('case_id')}: "
                          f"{_fdt(res.get('a_at'))} → {_b}")
        except Exception:
            head = QLabel(f"Кейс {res.get('case_id')}")
        head.setWordWrap(True)
        layout.addWidget(head)
        table = QTableWidget()
        rows = res.get("rows", [])
        table.setColumnCount(3)
        table.setRowCount(len(rows))
        table.setHorizontalHeaderLabels(["Поле", "Было", "Стало"])
        for i, r in enumerate(rows):
            table.setItem(i, 0, QTableWidgetItem(r["label"]))
            table.setItem(i, 1, QTableWidgetItem(r["a"]))
            table.setItem(i, 2, QTableWidgetItem(r["b"]))
            if r.get("changed"):
                try:
                    from PySide6.QtGui import QColor as _QC
                    from styles import SEMANTIC as _SEM
                    for c in range(3):
                        table.item(i, c).setForeground(_QC(_SEM["success"]))
                except Exception:
                    pass
        table.resizeColumnsToContents()
        try:
            clear_in_fluent(table)
        except Exception:
            pass
        layout.addWidget(table)
        btns = QHBoxLayout()
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
