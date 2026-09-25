from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
     QGroupBox, QGridLayout,
    QScrollArea, QWidget, QInputDialog
)
from PySide6.QtCore import Qt
from constants import CHECK_OPTIONS, CHECK_SEVERITIES
from database import db
from ui_compat import (
    FCheckBox, FComboBox, FLineEdit, FPrimaryButton, FPushButton,
    clear_in_fluent, notify,
)


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
            'check_severities': [],
            'error_category_id': None,
            'error_severities': [],
            'reviewed_from': '',
            'reviewed_to': '',
        }

        self.status_checkboxes = {}
        self.tag_checkboxes = {}
        self.check_checkboxes = {}
        self.sev_checkboxes = {}
        self.err_sev_checkboxes = {}
        # Вид таблицы, связанный с фильтром (ТЗ §29): колонки/сортировка/очередь.
        # Хранится рядом с условиями, применяется экраном ревью.
        self.view = None

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
        from styles import COLORS as _CC
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: none;
                background-color: {_CC['bg_dark']};
            }}
        """)

        content_widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(10, 10, 10, 10)

        # Сохранённые фильтры (ТЗ §28-30)
        saved_group = QGroupBox("⭐ Сохранённые фильтры")
        saved_layout = QHBoxLayout()
        self.saved_combo = FComboBox()
        self.saved_combo.setMinimumHeight(30)
        btn_saved_apply = FPushButton("Применить")
        btn_saved_apply.clicked.connect(self.on_saved_apply)
        btn_saved_save = FPushButton("💾 Сохранить текущий")
        btn_saved_save.clicked.connect(self.on_saved_save)
        btn_saved_del = FPushButton("🗑")
        btn_saved_del.setMaximumWidth(40)
        btn_saved_del.clicked.connect(self.on_saved_delete)
        saved_layout.addWidget(self.saved_combo)
        saved_layout.addWidget(btn_saved_apply)
        saved_layout.addWidget(btn_saved_save)
        saved_layout.addWidget(btn_saved_del)
        saved_group.setLayout(saved_layout)
        layout.addWidget(saved_group)
        self.reload_saved_filters()

        # Статусы — из активного профиля (свои коды поддерживаются)
        status_group = QGroupBox("Статус")
        status_layout = QGridLayout()

        try:
            from review_profile_service import status_options
            status_opts = status_options(self.project_path)
        except Exception:
            status_opts = []
        if not status_opts:
            from constants import STATUS_OPTIONS as _FALLBACK
            status_opts = list(_FALLBACK)
        for i, (code, name) in enumerate(status_opts):
            cb = FCheckBox(name)
            self.status_checkboxes[code] = cb
            status_layout.addWidget(cb, i // 3, i % 3)

        status_group.setLayout(status_layout)
        layout.addWidget(status_group)

        # Файл
        file_group = QGroupBox("Файл")
        file_layout = QHBoxLayout()

        self.file_combo = FComboBox()
        self.file_combo.addItem("Все файлы", None)
        self.load_files()

        file_layout.addWidget(QLabel("Файл:"))
        file_layout.addWidget(self.file_combo)
        file_group.setLayout(file_layout)
        layout.addWidget(file_group)

        # Комментарий
        comment_group = QGroupBox("Комментарий")
        comment_layout = QHBoxLayout()

        self.comment_combo = FComboBox()
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
            cb = FCheckBox(name)
            self.check_checkboxes[code] = cb
            self.checks_layout.addWidget(cb, i // 3, i % 3)

        checks_group.setLayout(self.checks_layout)
        layout.addWidget(checks_group)

        # Severity автопроверок
        sev_group = QGroupBox("Severity автопроверок")
        sev_layout = QHBoxLayout()
        for code, name in CHECK_SEVERITIES:
            cb = FCheckBox(name)
            self.sev_checkboxes[code] = cb
            sev_layout.addWidget(cb)
        sev_group.setLayout(sev_layout)
        layout.addWidget(sev_group)

        # Таксономия ошибок
        err_group = QGroupBox("Причина ошибки (таксономия)")
        err_layout = QVBoxLayout()
        err_row = QHBoxLayout()
        self.error_category_combo = FComboBox()
        self.error_category_combo.addItem("Любая причина", None)
        self._load_error_categories()
        err_row.addWidget(QLabel("Категория:"))
        err_row.addWidget(self.error_category_combo)
        err_layout.addLayout(err_row)
        err_sev_row = QHBoxLayout()
        for code, name in (("low", "Низкая"), ("medium", "Средняя"),
                           ("high", "Высокая"), ("critical", "Критическая")):
            cb = FCheckBox(name)
            self.err_sev_checkboxes[code] = cb
            err_sev_row.addWidget(cb)
        err_layout.addLayout(err_sev_row)
        err_group.setLayout(err_layout)
        layout.addWidget(err_group)

        # Текстовый поиск
        search_group = QGroupBox("Поиск по тексту")
        search_layout = QHBoxLayout()

        self.search_input = FLineEdit()
        self.search_input.setPlaceholderText("Введите текст для поиска...")

        search_layout.addWidget(self.search_input)
        search_group.setLayout(search_layout)
        layout.addWidget(search_group)

        # Период проверки (аналитика): даты разметки, не импорта.
        period_group = QGroupBox("Период проверки")
        period_layout = QHBoxLayout()
        from PySide6.QtWidgets import QDateEdit as _QDE
        from PySide6.QtCore import QDate as _QD
        self.period_preset = FComboBox()
        self.period_preset.addItem("Всё время", "")
        self.period_preset.addItem("Сегодня", "today")
        self.period_preset.addItem("7 дней", "7d")
        self.period_preset.addItem("14 дней", "14d")
        self.period_preset.addItem("30 дней", "30d")
        self.period_preset.addItem("Вручную", "manual")
        self.period_preset.currentIndexChanged.connect(
            self._on_period_preset)
        period_layout.addWidget(self.period_preset)
        self.date_from = _QDE()
        self.date_from.setDisplayFormat("dd-MM-yyyy")
        self.date_from.setCalendarPopup(True)
        self.date_from.setDate(_QD.currentDate().addDays(-7))
        self.date_from.dateChanged.connect(
            lambda _d: self._on_period_manual())
        period_layout.addWidget(QLabel("с:"))
        period_layout.addWidget(self.date_from)
        self.date_to = _QDE()
        self.date_to.setDisplayFormat("dd-MM-yyyy")
        self.date_to.setCalendarPopup(True)
        self.date_to.setDate(_QD.currentDate())
        self.date_to.dateChanged.connect(
            lambda _d: self._on_period_manual())
        period_layout.addWidget(QLabel("по:"))
        period_layout.addWidget(self.date_to)
        period_group.setLayout(period_layout)
        layout.addWidget(period_group)

        content_widget.setLayout(layout)
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)
        clear_in_fluent(scroll)

        # Кнопки
        buttons_layout = QHBoxLayout()

        btn_apply = FPrimaryButton("✅ Применить фильтры")
        btn_apply.setMinimumHeight(45)
        btn_apply.clicked.connect(self.on_apply)

        btn_reset = FPushButton("🔄 Сбросить")
        btn_reset.setMinimumHeight(45)
        btn_reset.clicked.connect(self.on_reset)

        btn_cancel = FPushButton("❌ Отмена")
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
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT file_id, file_name FROM files ORDER BY imported_at")
                files = cursor.fetchall()

            for file in files:
                self.file_combo.addItem(file['file_name'], file['file_id'])
        except Exception:
            pass

    def load_tags(self):
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tag_id, tag_name FROM tags ORDER BY tag_name")
                tags = cursor.fetchall()

            row, col = 0, 0
            for tag in tags:
                cb = FCheckBox(tag['tag_name'])
                self.tag_checkboxes[tag['tag_id']] = cb
                self.tags_layout.addWidget(cb, row, col)
                col += 1
                if col >= 3:
                    col = 0
                    row += 1
        except Exception:
            pass

    def _load_error_categories(self):
        try:
            from taxonomy_service import list_categories
            cats = list_categories(self.project_path)
        except Exception:
            cats = []
        for cat in cats:
            self.error_category_combo.addItem(
                cat["name"], cat["category_id"])
            for sub in cat.get("subs", []):
                self.error_category_combo.addItem(
                    f"  └ {sub['name']}", sub["category_id"])

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
        self.filters['check_severities'] = [
            code for code, cb in self.sev_checkboxes.items() if cb.isChecked()
        ]
        self.filters['error_category_id'] = self.error_category_combo.currentData()
        self.filters['error_severities'] = [
            code for code, cb in self.err_sev_checkboxes.items() if cb.isChecked()
        ]

        self.filters['search_text'] = self.search_input.text().strip()
        _preset, _pf, _pt = self._period_dates()
        _ = _preset
        self.filters['reviewed_from'] = _pf
        self.filters['reviewed_to'] = _pt

        self.accept()

    @staticmethod
    def _iso_today() -> str:
        from datetime import date as _d
        return _d.today().isoformat()

    @staticmethod
    def _iso_days_ago(n: int) -> str:
        from datetime import date as _d, timedelta as _td
        return (_d.today() - _td(days=n)).isoformat()

    def _on_period_preset(self):
        """Пресет ставит даты; ручная правка дат переключает на «Вручную»."""
        mode = self.period_preset.currentData() or ""
        if not mode or mode == "manual":
            return
        from PySide6.QtCore import QDate as _QD
        today = _QD.currentDate()
        if mode == "today":
            self.date_from.setDate(today)
            self.date_to.setDate(today)
        elif mode in ("7d", "14d", "30d"):
            self.date_from.setDate(today.addDays(-int(mode[:-1])))
            self.date_to.setDate(today)

    def _on_period_manual(self):
        for i in range(self.period_preset.count()):
            if self.period_preset.itemData(i) == "manual":
                self.period_preset.blockSignals(True)
                self.period_preset.setCurrentIndex(i)
                self.period_preset.blockSignals(False)
                break

    def _period_dates(self) -> tuple:
        """(preset, from, to): '' = без ограничения."""
        mode = self.period_preset.currentData() or ""
        if not mode:
            return "", "", ""
        if mode == "today":
            t = self._iso_today()
            return mode, t, t
        if mode in ("7d", "14d", "30d"):
            return mode, self._iso_days_ago(int(mode[:-1])), self._iso_today()
        f = self.date_from.date().toString("yyyy-MM-dd")
        t = self.date_to.date().toString("yyyy-MM-dd")
        if f > t:
            f, t = t, f
        return mode, f, t

    def on_reset(self):
        for cb in self.status_checkboxes.values():
            cb.setChecked(False)

        self.file_combo.setCurrentIndex(0)
        self.comment_combo.setCurrentIndex(0)

        for cb in self.tag_checkboxes.values():
            cb.setChecked(False)

        for cb in self.check_checkboxes.values():
            cb.setChecked(False)
        for cb in self.sev_checkboxes.values():
            cb.setChecked(False)
        for cb in self.err_sev_checkboxes.values():
            cb.setChecked(False)
        try:
            self.error_category_combo.setCurrentIndex(0)
        except Exception:
            pass

        self.search_input.clear()
        self.period_preset.setCurrentIndex(0)

    def get_filters(self):
        import copy
        return copy.deepcopy(self.filters)

    def set_view(self, view: dict | None) -> None:
        """Текущий вид таблицы (колонки/сортировка/очередь) для сохранения рядом."""
        self.view = dict(view) if view else None

    def get_view(self) -> dict | None:
        import copy
        return copy.deepcopy(self.view) if self.view else None

    def reload_saved_filters(self):
        try:
            from saved_filter_service import list_saved_filters
            items = list_saved_filters(self.project_path)
        except Exception:
            items = []
        self.saved_combo.blockSignals(True)
        self.saved_combo.clear()
        self.saved_combo.addItem("— выбрать —", None)
        for it in items:
            self.saved_combo.addItem(it["name"], it["filters"])
        self.saved_combo.blockSignals(False)

    def _collect_ui_filters(self) -> dict:
        return {
            "statuses": [c for c, cb in self.status_checkboxes.items() if cb.isChecked()],
            "file_id": self.file_combo.currentData(),
            "has_comment": self.comment_combo.currentData(),
            "tags": [t for t, cb in self.tag_checkboxes.items() if cb.isChecked()],
            "checks": [c for c, cb in self.check_checkboxes.items() if cb.isChecked()],
            "check_severities": [c for c, cb in self.sev_checkboxes.items()
                                 if cb.isChecked()],
            "error_category_id": self.error_category_combo.currentData(),
            "error_severities": [c for c, cb in self.err_sev_checkboxes.items()
                                 if cb.isChecked()],
            "search_text": self.search_input.text().strip(),
            "reviewed_from": self._period_dates()[1],
            "reviewed_to": self._period_dates()[2],
        }

    def on_saved_apply(self):
        data = self.saved_combo.currentData()
        if data:
            self.set_filters(data)

    def on_saved_save(self):
        from saved_filter_service import save_filter
        current = self._collect_ui_filters()
        name, ok = QInputDialog.getText(self, "Сохранить фильтр", "Название:")
        if ok and (name or "").strip():
            try:
                payload: dict = {"filters": current}
                view_bits = []
                if self.view:
                    for k in ("columns", "queue_mode", "sort"):
                        if self.view.get(k) is not None:
                            payload[k] = self.view[k]
                    if payload.get("columns"):
                        view_bits.append(f"колонки: {len(payload['columns'])}")
                    if payload.get("sort"):
                        view_bits.append(f"сортировка: {payload['sort']}")
                    if payload.get("queue_mode"):
                        view_bits.append(f"очередь: {payload['queue_mode']}")
                from ui_compat import confirm
                detail = ("условия" + (f" + вид ({', '.join(view_bits)})"
                                       if view_bits else " (без вида таблицы)"))
                if not confirm(self, "Сохранить фильтр",
                               f"«{name.strip()}»: {detail}.\nПродолжить?",
                               ok_text="Сохранить", cancel_text="Отмена"):
                    return
                save_filter(self.project_path, name.strip(), payload)
                self.reload_saved_filters()
                notify(self, "success", "Фильтр", "Фильтр сохранён")
            except Exception as e:
                notify(self, "warning", "Ошибка", str(e))

    def on_saved_delete(self):
        from saved_filter_service import list_saved_filters, delete_saved_filter
        idx = self.saved_combo.currentIndex()
        if idx <= 0:
            return
        name = self.saved_combo.currentText()
        try:
            items = list_saved_filters(self.project_path)
            match = next((i for i in items if i["name"] == name), None)
            if match and delete_saved_filter(self.project_path, match["filter_id"]):
                self.reload_saved_filters()
        except Exception as e:
            notify(self, "warning", "Ошибка", str(e))

    def set_filters(self, payload):
        # Совместимость: старые сохранения — плоский dict условий;
        # новые — {"filters": {...}, "columns": [...], "queue_mode": ..., "sort": ...}.
        if isinstance(payload, dict) and "filters" in payload and isinstance(
                payload["filters"], dict):
            filters = payload["filters"]
            self.view = {k: payload[k] for k in ("columns", "queue_mode", "sort")
                         if k in payload}
        else:
            filters = payload or {}
            self.view = None
        if not filters:
            self.on_reset()
            return

        for code, cb in self.status_checkboxes.items():
            cb.setChecked(code in filters.get('statuses', []))

        file_id = filters.get('file_id')
        self.file_combo.setCurrentIndex(0)
        if file_id:
            for i in range(self.file_combo.count()):
                if self.file_combo.itemData(i) == file_id:
                    self.file_combo.setCurrentIndex(i)
                    break

        has_comment = filters.get('has_comment')
        self.comment_combo.setCurrentIndex(0)
        if has_comment is not None:
            for i in range(self.comment_combo.count()):
                if self.comment_combo.itemData(i) == has_comment:
                    self.comment_combo.setCurrentIndex(i)
                    break

        for tag_id, cb in self.tag_checkboxes.items():
            cb.setChecked(tag_id in filters.get('tags', []))

        for code, cb in self.check_checkboxes.items():
            cb.setChecked(code in filters.get('checks', []))
        for code, cb in self.sev_checkboxes.items():
            cb.setChecked(code in filters.get('check_severities', []))
        for code, cb in self.err_sev_checkboxes.items():
            cb.setChecked(code in filters.get('error_severities', []))
        try:
            ecid = filters.get('error_category_id')
            self.error_category_combo.setCurrentIndex(0)
            if ecid:
                for i in range(self.error_category_combo.count()):
                    if self.error_category_combo.itemData(i) == ecid:
                        self.error_category_combo.setCurrentIndex(i)
                        break
        except Exception:
            pass

        self.search_input.setText(filters.get('search_text', ''))
        try:
            from PySide6.QtCore import QDate as _QD
            pf = (filters.get('reviewed_from') or '').strip()
            pt = (filters.get('reviewed_to') or '').strip()
            if pf or pt:
                if pf:
                    self.date_from.setDate(_QD.fromString(pf, "yyyy-MM-dd"))
                if pt:
                    self.date_to.setDate(_QD.fromString(pt, "yyyy-MM-dd"))
                for i in range(self.period_preset.count()):
                    if self.period_preset.itemData(i) == "manual":
                        self.period_preset.blockSignals(True)
                        self.period_preset.setCurrentIndex(i)
                        self.period_preset.blockSignals(False)
                        break
            else:
                self.period_preset.blockSignals(True)
                self.period_preset.setCurrentIndex(0)
                self.period_preset.blockSignals(False)
        except Exception:
            pass
