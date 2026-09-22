"""Review screen: table, filters, queue, bulk selection (mixin)."""


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QDialog, QAbstractItemView,
)
from PySide6.QtCore import Qt
from constants import COLUMN_TO_SQL, TABLE_SYSTEM_COLUMNS
from database import db
from filter_dialog import FilterDialog
from filter_service import get_filtered_case_ids, get_all_case_ids
from ui_compat import (
    FCheckBox, FComboBox, FPushButton, FTable, clear_in_fluent,
    confirm, notify, polish_table,
)
import json
import logging


logger = logging.getLogger(__name__)


class TableMixin:
    """Table view, pagination, filters, queue, bulk selection."""

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

    def update_column_filter_combo(self):
        """Обновляет список столбцов для фильтра."""
        if not hasattr(self, 'column_filter_combo'):
            return
        self.column_filter_combo.blockSignals(True)
        self.column_filter_combo.clear()
        self.column_filter_combo.addItem("Фильтр по столбцу...", None)
        from ui_compat import add_elided_item as _addc, bound_combo_popup as _boundc
        from constants import metadata_column_label as _label
        for col in self.available_columns:
            _addc(self.column_filter_combo, _label(col), col)
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
                color: #e8e8e8;
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
                color: #e8e8e8;
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
        # Без stretch: у таблицы всегда горизонтальный скролл, колонки шире
        # вида — тянуть последнюю некуда.
        polish_table(self.cases_table)

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
            from constants import metadata_column_label as _label
            self.cases_table.setHorizontalHeaderLabels(
                ["✓"] + [_label(c) for c in self.selected_columns] + ["⚠"])
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
