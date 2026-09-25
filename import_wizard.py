from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidgetItem, QFileDialog,
    QGroupBox, QScrollArea,
    QFormLayout
)
from PySide6.QtCore import Qt, Signal
from file_reader import FileReader
from pathlib import Path
from ui_compat import (
    FComboBox, FPrimaryButton, FPushButton, FSpinBox, FTable,
    clear_in_fluent, notify,
)

from constants import MAPPING_ROLES


def precheck_stats(mapping: dict, data: list) -> dict:
    """Предимпортная проверка (ТЗ §80-81): покрытие ID/запроса и дубли ID."""
    sid_cols = [c for c, r in mapping.items() if r == "source_id"]
    pri_cols = [c for c, r in mapping.items() if r == "primary_text"]
    total = sum(1 for row in data if isinstance(row, dict))
    filled, empty, dups = 0, 0, 0
    seen: set = set()
    dup_examples: list = []
    pri_empty = 0
    if sid_cols:
        scol = sid_cols[0]
        for row in data:
            if not isinstance(row, dict):
                continue
            v = str(row.get(scol, "") or "").strip()
            if not v:
                empty += 1
                continue
            filled += 1
            if v in seen:
                dups += 1
                if len(dup_examples) < 5:
                    dup_examples.append(v)
            else:
                seen.add(v)
    if pri_cols:
        for row in data:
            if not isinstance(row, dict):
                continue
            if not any(str(row.get(c, "") or "").strip() for c in pri_cols):
                pri_empty += 1
    return {"total": total, "sid_mapped": bool(sid_cols),
            "sid_filled": filled, "sid_empty": empty,
            "sid_dups": dups, "dup_examples": dup_examples,
            "primary_empty": pri_empty}


class ImportWizard(QWidget):
    import_finished = Signal()
    import_cancelled = Signal()

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self.file_reader = FileReader()
        self.file_path = None
        self.file_type = None
        self.sheet_name = None
        self.preview_data = None
        self.mapping_combos = {}
        # Одобрение дубля: digest файла, по которому уже ответили «Импортировать».
        self._dup_approved = None
        self.init_ui()

    def init_ui(self):
        self.layout = QVBoxLayout()
        self.layout.setSpacing(15)
        self.layout.setContentsMargins(25, 10, 25, 10)

        self.title = QLabel("📥 ИМПОРТ ФАЙЛА")
        self.title.setObjectName("title")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.layout.addWidget(self.title)

        self.step1_widget = self.create_step1()
        self.layout.addWidget(self.step1_widget)

        self.step2_widget = self.create_step2()
        self.step2_widget.setVisible(False)
        self.layout.addWidget(self.step2_widget)

        self.setLayout(self.layout)

    def create_step1(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)

        file_layout = QHBoxLayout()
        self.file_label = QLabel("Файл не выбран")
        self.file_label.setStyleSheet("font-size: 13px;")
        btn_select = FPushButton("📂 Выбрать файл")
        btn_select.setMinimumHeight(35)
        btn_select.clicked.connect(self.on_select_file)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(btn_select)
        layout.addLayout(file_layout)

        self.sheet_group = QGroupBox("📑 Лист Excel")
        sheet_layout = QHBoxLayout()
        self.sheet_combo = FComboBox()
        self.sheet_combo.setMinimumHeight(30)
        self.sheet_combo.currentIndexChanged.connect(self.on_sheet_changed)
        sheet_layout.addWidget(QLabel("Лист:"))
        sheet_layout.addWidget(self.sheet_combo)
        self.sheet_group.setLayout(sheet_layout)
        self.sheet_group.setVisible(False)
        layout.addWidget(self.sheet_group)

        header_layout = QHBoxLayout()
        self.header_spin = FSpinBox()
        self.header_spin.setMinimum(0)
        self.header_spin.setMaximum(100)
        self.header_spin.setValue(0)
        self.header_spin.setMinimumHeight(30)
        self.header_spin.valueChanged.connect(self.on_header_changed)
        header_layout.addWidget(QLabel("Строка заголовка (0 = первая):"))
        header_layout.addWidget(self.header_spin)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        csv_layout = QHBoxLayout()
        self.encoding_combo = FComboBox()
        self.encoding_combo.addItem("UTF-8 (BOM тоже)", "utf-8-sig")
        self.encoding_combo.addItem("UTF-8", "utf-8")
        self.encoding_combo.addItem("CP1251 (рус. Excel)", "cp1251")
        self.encoding_combo.currentIndexChanged.connect(self.load_preview)
        self.delimiter_combo = FComboBox()
        self.delimiter_combo.addItem("Запятая (,)", ",")
        self.delimiter_combo.addItem("Точка с запятой (;)", ";")
        self.delimiter_combo.addItem("Табуляция", "\t")
        self.delimiter_combo.addItem("Пайп (|)", "|")
        self.delimiter_combo.currentIndexChanged.connect(self.load_preview)
        csv_layout.addWidget(QLabel("Кодировка CSV:"))
        csv_layout.addWidget(self.encoding_combo)
        csv_layout.addWidget(QLabel("Разделитель:"))
        csv_layout.addWidget(self.delimiter_combo)
        csv_layout.addStretch()
        layout.addLayout(csv_layout)

        preview_label = QLabel("📋 Превью данных:")
        preview_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(preview_label)

        self.preview_table = FTable()
        self.preview_table.setMinimumHeight(150)
        try:
            from PySide6.QtWidgets import QSizePolicy
            self.preview_table.setSizePolicy(
                QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        except Exception:
            pass
        # Плейсхолдер: пустая тёмная панель на весь экран выглядит как баг.
        self.preview_table.setColumnCount(1)
        self.preview_table.setRowCount(1)
        self.preview_table.setHorizontalHeaderLabels(["Превью"])
        try:
            from PySide6.QtWidgets import QTableWidgetItem as _TI
            self.preview_table.setItem(0, 0, _TI("📂 Выбери файл — здесь появится превью"))
        except Exception:
            pass
        from styles import COLORS as _CC
        self.preview_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {_CC['bg_card']};
                border: 2px solid {_CC['border_dim']};
                border-radius: 8px;
                color: {_CC['text_bright']};
                font-size: 11px;
                gridline-color: {_CC['border_dim']};
            }}
            QTableWidget::item {{ padding: 5px; }}
            QHeaderView::section {{
                background-color: {_CC['bg_active']};
                color: {_CC['text_bright']};
                border: 1px solid {_CC['green_dim']};
                padding: 6px;
                font-weight: bold;
            }}
        """)
        layout.addWidget(self.preview_table)
        clear_in_fluent(self.preview_table)

        buttons_layout = QHBoxLayout()
        btn_next = FPushButton("➡️ Далее: маппинг колонок")
        btn_next.setMinimumHeight(40)
        btn_next.clicked.connect(self.on_next_step)
        btn_cancel = FPushButton("❌ Отмена")
        btn_cancel.setObjectName("danger")
        btn_cancel.setMinimumHeight(40)
        btn_cancel.clicked.connect(self.on_cancel)
        buttons_layout.addWidget(btn_next)
        buttons_layout.addWidget(btn_cancel)
        layout.addLayout(buttons_layout)

        widget.setLayout(layout)
        return widget

    def create_step2(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(10)

        label = QLabel("🔧 Настройка маппинга колонок")
        label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(label)

        hint = QLabel(
            "Укажите роль для каждой колонки. "
            "Можно назначить одну роль нескольким колонкам — "
            "их содержимое будет объединено. "
            "Исключение: «Идентификатор» — только одна колонка. "
            "«Источник» — ссылка на статью БЗ (показывается в кейсе 🔗). "
            "Свои категории попадают в метаданные и становятся столбцами таблицы."
        )
        from styles import COLORS as _CC
        hint.setStyleSheet(
            f"color: {_CC['green_dark']}; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        custom_layout = QHBoxLayout()
        btn_custom = FPushButton("＋ Своя категория…")
        btn_custom.setMinimumHeight(32)
        btn_custom.setToolTip("Создать свою категорию маппинга — "
                              "значение попадёт в метаданные кейса")
        btn_custom.clicked.connect(self.on_add_custom_role)
        custom_layout.addWidget(btn_custom)
        btn_del_custom = FPushButton("－ Категория")
        btn_del_custom.setMinimumHeight(32)
        btn_del_custom.setToolTip("Удалить свою категорию маппинга")
        btn_del_custom.clicked.connect(self.on_remove_custom_role)
        custom_layout.addWidget(btn_del_custom)
        custom_layout.addStretch()
        layout.addLayout(custom_layout)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(250)
        scroll.setStyleSheet(f"""
            QScrollArea {{
                border: 2px solid {_CC['border_dim']};
                border-radius: 8px;
                background-color: {_CC['bg_panel']};
            }}
        """)
        self.mapping_container = QWidget()
        self.mapping_layout = QFormLayout()
        self.mapping_layout.setSpacing(8)
        self.mapping_layout.setContentsMargins(10, 10, 10, 10)
        self.mapping_container.setLayout(self.mapping_layout)
        scroll.setWidget(self.mapping_container)
        clear_in_fluent(scroll)
        layout.addWidget(scroll)

        buttons_layout = QHBoxLayout()
        btn_back = FPushButton("⬅️ Назад")
        btn_back.setMinimumHeight(40)
        btn_back.clicked.connect(self.on_back_step)
        btn_import = FPrimaryButton("🚀 Начать импорт")
        btn_import.setMinimumHeight(40)
        btn_import.setStyleSheet(f"""
            QPushButton {{ border-color: {_CC['green_bright']};
                color: {_CC['text_bright']}; font-weight: bold; }}
            QPushButton:hover {{ background-color: {_CC['green_deep']}; }}
        """)
        btn_import.clicked.connect(self.on_import)
        btn_cancel = FPushButton("❌ Отмена")
        btn_cancel.setObjectName("danger")
        btn_cancel.setMinimumHeight(40)
        btn_cancel.clicked.connect(self.on_cancel)
        buttons_layout.addWidget(btn_back)
        buttons_layout.addWidget(btn_import)
        buttons_layout.addWidget(btn_cancel)
        layout.addLayout(buttons_layout)

        widget.setLayout(layout)
        return widget

    def on_select_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выберите файл для импорта", "",
            "Таблицы (*.xlsx *.xls *.csv *.ods);;Excel (*.xlsx *.xls);;"
            "Calc (*.ods);;CSV (*.csv);;"
            "JSON (*.json *.jsonl);;Все файлы (*.*)"
        )
        if not file_path:
            return
        self.load_path(file_path)

    def load_path(self, file_path: str) -> None:
        """Пресет файла (drag-n-drop): та же настройка, что из диалога."""
        self.file_path = file_path
        self.file_label.setText(Path(file_path).name)
        self._dup_approved = None
        try:
            self.file_type = self.file_reader.detect_file_type(file_path)
        except ValueError as e:
            notify(self, "warning", "Неподдерживаемый формат", str(e))
            return
        # Дубль опознаём сразу при выборе файла (до маппинга): не тратить
        # время на маппинг повтора. Ответ запоминаем, при импорте не переспрашиваем.
        if not self._confirm_file_dup(early=True):
            self.file_path = None
            self.file_label.setText("Файл не выбран")
            return

        if self.file_type in ('excel', 'ods'):
            try:
                if self.file_type == 'excel':
                    sheets = self.file_reader.read_excel_sheets(file_path)
                else:
                    sheets = self.file_reader.read_ods_sheets(file_path)
                self.sheet_combo.clear()
                self.sheet_combo.addItems(sheets)
                self.sheet_group.setVisible(True)
                self.sheet_name = sheets[0] if sheets else None
                self.load_preview()
            except Exception as e:
                notify(self, "error", "Ошибка", str(e))
        elif self.file_type == 'csv':
            self.sheet_group.setVisible(False)
            self.load_preview()
        elif self.file_type in ['json', 'jsonl']:
            self.sheet_group.setVisible(False)
            self.load_preview()
        else:
            notify(self, "warning", "Неподдерживаемый формат",
                   "Пока поддерживаются: .xlsx, .ods, .csv, .json, .jsonl")

    def on_sheet_changed(self):
        self.sheet_name = self.sheet_combo.currentText()
        self.load_preview()

    def on_header_changed(self):
        self.load_preview()

    def _csv_options(self):
        return self.encoding_combo.currentData(), self.delimiter_combo.currentData()

    def load_preview(self):
        if not self.file_path:
            return
        try:
            if self.file_type == 'excel':
                self.preview_data = self.file_reader.read_excel_preview(
                    self.file_path, self.sheet_name, max_rows=100)
            elif self.file_type == 'ods':
                self.preview_data = self.file_reader.read_ods_preview(
                    self.file_path, self.sheet_name, max_rows=100)
            elif self.file_type == 'csv':
                enc, delim = self._csv_options()
                self.preview_data = self.file_reader.read_csv_preview(
                    self.file_path, encoding=enc, delimiter=delim, max_rows=100)
            elif self.file_type == 'json':
                self.preview_data = self.file_reader.read_json_preview(
                    self.file_path, max_rows=100)
            elif self.file_type == 'jsonl':
                self.preview_data = self.file_reader.read_jsonl_preview(
                    self.file_path, max_rows=100)
                errors = self.preview_data.get('errors')
                if errors:
                    notify(
                        self, "warning", "JSONL",
                        f"Битых строк в превью: {len(errors)} (показаны целые).")
            self.update_preview_table()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def update_preview_table(self):
        if not self.preview_data:
            return
        headers = self.preview_data['headers']
        rows = self.preview_data['rows']
        self.preview_table.clear()
        self.preview_table.setColumnCount(len(headers))
        self.preview_table.setRowCount(min(len(rows), 20))
        self.preview_table.setHorizontalHeaderLabels(headers)
        for row_idx, row in enumerate(rows[:20]):
            for col_idx, value in enumerate(row):
                item = QTableWidgetItem(str(value)[:100])
                self.preview_table.setItem(row_idx, col_idx, item)
        self.preview_table.resizeColumnsToContents()

    def on_next_step(self):
        if not self.file_path:
            notify(self, "warning", "Внимание", "Сначала выберите файл")
            return
        if not self.preview_data or not self.preview_data['headers']:
            notify(self, "warning", "Внимание", "Нет данных для маппинга")
            return
        self.build_mapping_ui()
        self.step1_widget.setVisible(False)
        self.step2_widget.setVisible(True)
        self.title.setText("🔧 МАППИНГ КОЛОНОК")

    def build_mapping_ui(self):
        from mapping_custom import custom_roles, reapply_mapping
        saved = {h: c.currentData() for h, c in self.mapping_combos.items()}
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.mapping_combos.clear()

        headers = self.preview_data['headers']
        rows = self.preview_data.get('rows', []) or []
        roles = list(MAPPING_ROLES) + custom_roles(self.project_path)
        restored = reapply_mapping(headers, roles, saved)
        for idx, header in enumerate(headers):
            # Примеры значений из превью: видно, что за данные в колонке,
            # и сразу заметно, где идентификаторы, а где пусто.
            samples = []
            for r in rows:
                try:
                    v = str(r[idx] if idx < len(r) else "").strip()
                except Exception:
                    v = ""
                if v and v not in samples:
                    samples.append(v)
                if len(samples) >= 2:
                    break
            from ui_compat import mapping_label
            left = QLabel(mapping_label(header, samples))
            # Иначе длинные названия разъезжают диалог шире экрана.
            left.setWordWrap(True)
            left.setMaximumWidth(420)
            left.setTextFormat(Qt.TextFormat.RichText)
            combo = FComboBox()
            combo.setMinimumHeight(30)
            for role_code, role_name in roles:
                combo.addItem(role_name, role_code)
            want = restored.get(header)
            if want:
                for i in range(combo.count()):
                    if combo.itemData(i) == want:
                        combo.setCurrentIndex(i)
                        break
            # Без пресетов: все колонки изначально «Не импортировать»,
            # включая первую, — пользователь назначает роли сам.
            self.mapping_layout.addRow(left, combo)
            self.mapping_combos[header] = combo

    def on_add_custom_role(self):
        from PySide6.QtWidgets import QInputDialog
        from mapping_custom import add_custom_category
        name, ok = QInputDialog.getText(
            self, "Своя категория", "Название категории (попадёт в метаданные):")
        if not ok:
            return
        try:
            add_custom_category(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.build_mapping_ui()
        notify(self, "success", "Категория",
               f"Категория «{str(name).strip()}» добавлена — выбери её в нужных колонках")

    def on_remove_custom_role(self):
        from PySide6.QtWidgets import QInputDialog
        from mapping_custom import load_custom_categories, remove_custom_category
        names = load_custom_categories(self.project_path)
        if not names:
            notify(self, "warning", "Внимание", "Своих категорий пока нет")
            return
        name, ok = QInputDialog.getItem(
            self, "Удалить категорию", "Категория:", names, 0, False)
        if not ok or not name:
            return
        try:
            remove_custom_category(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.build_mapping_ui()
        notify(self, "success", "Категория", f"«{name}» удалена")

    def on_back_step(self):
        self.step2_widget.setVisible(False)
        self.step1_widget.setVisible(True)
        self.title.setText("📥 ИМПОРТ ФАЙЛА")

    def get_mapping(self):
        mapping = {}
        for header, combo in self.mapping_combos.items():
            role_code = combo.currentData()
            if role_code != "ignore":
                mapping[header] = role_code
        return mapping

    def validate_mapping(self, mapping):
        """Проверяет корректность маппинга.
        Разрешает несколько столбцов в одной роли, кроме 'Идентификатор'."""
        has_primary = any(role == "primary_text" for role in mapping.values())
        if not has_primary:
            return False, "Не выбрана колонка с запросом"

        # Только Идентификатор не может повторяться
        source_id_count = sum(1 for role in mapping.values() if role == 'source_id')
        if source_id_count > 1:
            return False, "Роль «Идентификатор» можно назначить только одной колонке"

        return True, ""

    def on_import(self):
        mapping = self.get_mapping()
        valid, error = self.validate_mapping(mapping)
        if not valid:
            notify(self, "warning", "Ошибка маппинга", error)
            return

        try:
            errors = []
            read_stats: dict = {}
            if self.file_type == 'excel':
                data = self.file_reader.read_excel_data(
                    self.file_path, self.sheet_name,
                    header_row=self.header_spin.value(), stats=read_stats)
            elif self.file_type == 'ods':
                data = self.file_reader.read_ods_data(
                    self.file_path, self.sheet_name,
                    header_row=self.header_spin.value(), stats=read_stats)
            elif self.file_type == 'csv':
                enc, delim = self._csv_options()
                data = self.file_reader.read_csv_data(
                    self.file_path, encoding=enc, delimiter=delim,
                    header_row=self.header_spin.value())
            elif self.file_type == 'json':
                data, errors = self.file_reader.read_json_data(self.file_path)
            elif self.file_type == 'jsonl':
                data, errors = self.file_reader.read_jsonl_data(self.file_path)
            else:
                notify(self, "warning", "Ошибка", "Неподдерживаемый формат")
                return

            if not data:
                notify(self, "warning", "Внимание", "Файл не содержит данных")
                return

            # Предимпортная проверка (ТЗ §80-81): строки, покрытие ID,
            # дубли ID, пустые запросы. При проблемах — подтверждение.
            if not self._precheck_and_confirm(mapping, data, read_stats):
                return
            # Вопрос о дубле файла — на этапе попытки импорта, отдельно.
            if not self._confirm_file_dup():
                return
            self._run_import_in_background(mapping, data, errors)
        except Exception as e:
            notify(self, "error", "Ошибка импорта", str(e))

    def _confirm_file_dup(self, early: bool = False) -> bool:
        """Вопрос о дубле файла.

        early=True — при выборе файла (до маппинга): ответ запоминается,
        при импорте не переспрашиваем. early=False — при попытке импорта
        (для файлов, выбранных до этого обновления, и на всякий случай).
        """
        from ui_compat import confirm
        from pathlib import Path as _Path
        import logging as _logging
        log = _logging.getLogger(__name__)
        try:
            from importer import file_sha256
            digest = file_sha256(self.file_path)
        except Exception as e:
            log.warning("file dup check by hash failed: %s", e)
            digest = None
        fname = _Path(self.file_path).name
        if self._dup_approved and (digest, fname) == tuple(self._dup_approved):
            return True
        if digest:
            try:
                from importer import find_file_by_hash as _find
                dup = _find(self.project_path, digest)
            except Exception as e:
                log.warning("file dup lookup failed: %s", e)
                dup = None
            if dup:
                ok = confirm(
                    self, "Файл уже импортирован",
                    f"«{dup['file_name']}» ({dup['row_count']} строк) уже есть в проекте. "
                    "Повторный импорт создаст дубли кейсов.\n\nПродолжить?",
                    ok_text="Продолжить", cancel_text="Остановить")
                if ok:
                    self._dup_approved = (digest, fname)
                return ok
        try:
            from importer import find_file_by_name
            same = find_file_by_name(self.project_path, _Path(self.file_path).name)
        except Exception as e:
            log.warning("file dup check by name failed: %s", e)
            same = None
        if same:
            ok = confirm(
                self, "Похоже на повтор",
                f"Файл с именем «{same['file_name']}» уже импортирован "
                f"({same['row_count']} строк; хэш старого импорта неизвестен). "
                "Повтор создаст дубли кейсов.\n\nПродолжить?",
                ok_text="Продолжить", cancel_text="Остановить")
            if ok:
                self._dup_approved = (digest, fname)
            return ok
        if early:
            self._dup_approved = (digest, fname)
        return True

    def _precheck_stats(self, mapping: dict, data: list) -> dict:
        """Считает покрытие ID/запроса и дубли ID по данным и маппингу."""
        return precheck_stats(mapping, data)

    def _precheck_and_confirm(self, mapping: dict, data: list,
                                read_stats: dict | None = None) -> bool:
        """Возвращает False, если пользователь остановил импорт."""
        from ui_compat import confirm
        try:
            st = self._precheck_stats(mapping, data)
        except Exception:
            return True
        lines = [f"Строк: {st['total']}."]
        try:
            n_err = int((read_stats or {}).get("formula_errors", 0) or 0)
        except Exception:
            n_err = 0
        if n_err:
            lines.append(
                f"⚠ Ячеек с ошибками формул (#REF! и т.п.): {n_err} — "
                "втянутся пустыми. Почини файл, если там данные.")
        if st["sid_mapped"]:
            lines.append(f"ID заполнен: {st['sid_filled']} из {st['total']} "
                         f"(пустых: {st['sid_empty']}).")
        else:
            lines.append("⚠ Колонка «Идентификатор» не назначена: в таблице будут "
                         "внутренние номера 1,2,3 вместо ID из файла, а версии и "
                         "прогоны состыкуются по хэшу текста. Нужна именно роль "
                         "«Идентификатор» — «Номер обращения» уходит в метаданные "
                         "и ID не задаёт.")
        if st["sid_dups"]:
            lines.append(f"⚠ Повторяющихся ID: {st['sid_dups']} "
                         f"(например: {', '.join(st['dup_examples'])}). "
                         "В датасетах они попадут в «конфликты».")
        if st["primary_empty"]:
            lines.append(f"⚠ Пустых запросов: {st['primary_empty']}.")
        has_problem = (st["sid_dups"] > 0 or not st["sid_mapped"]
                       or st["primary_empty"] > 0
                       or (st["sid_mapped"] and st["sid_filled"] == 0)
                       or n_err > 0)
        if not has_problem:
            return True
        return confirm(
            self, "Проверка перед импортом",
            "\n".join(lines) + "\n\nПродолжить импорт?",
            ok_text="Продолжить", cancel_text="Остановить")

    def _run_import_in_background(self, mapping: dict, data: list, errors: list):
        """Импорт в фоне с прогрессом, чтобы UI не вис на больших файлах."""
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Импорт…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)

        def _work():
            from importer import import_file
            from workers import run_in_background as _run
            holder: dict = {}

            def _progress(done, total):
                pct = int(done / total * 100) if total else 0
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(pct)

            worker = _run(import_file, self.project_path, self.file_path,
                          self.file_type, self.sheet_name,
                          self.header_spin.value(), mapping, data,
                          progress_callback=_progress, cancel_event=cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(
                lambda res: self._on_import_done(res, errors, progress))
            worker.signals.error.connect(
                lambda msg: self._on_import_error(msg, progress))

        def _noop():
            pass
        _ = _noop
        QTimer.singleShot(0, _work)

    def _on_import_done(self, res, errors: list, progress):
        try:
            progress.close()
        except Exception:
            pass
        try:
            file_id, cases_count, skipped = res
        except (TypeError, ValueError):
            # Совместимость со старым 2-tuple (на всякий случай).
            file_id, cases_count = res
            skipped = 0
        msg = f"✅ Успешно импортировано {cases_count} кейсов."
        if skipped:
            msg += f"\n⏭ Пропущено дублей/битых: {skipped}."
        if errors:
            msg += f"\n⚠️ Битых строк в файле: {len(errors)}."
        # Залипший фильтр по старому файлу прятал бы новые кейсы под видом
        # «закэшированного» ревью — сбрасываем его явно.
        try:
            pw = getattr(self, "parent_window", None)
            rev = (pw.screens.get("review") if pw is not None
                   and hasattr(pw, "screens") else None)
            if rev is not None and isinstance(
                    getattr(rev, "filters", None), dict) \
                    and rev.filters.get("file_id"):
                rev.filters = {k: v for k, v in rev.filters.items()
                               if k != "file_id"}
                msg += ("\n🎛️ Фильтр по файлу сброшен, чтобы показать "
                        "новые кейсы.")
        except Exception:
            pass
        notify(self, "success", "Импорт завершён", msg)
        self.import_finished.emit()

    def _on_import_error(self, msg: str, progress):
        try:
            progress.close()
        except Exception:
            pass
        if "Прервано пользователем" in (msg or ""):
            notify(self, "warning", "Импорт",
                   f"{msg}\nЧастичные данные сохранены.")
            self.import_finished.emit()
        else:
            notify(self, "error", "Ошибка импорта", str(msg))

    def on_cancel(self):
        self.import_cancelled.emit()
