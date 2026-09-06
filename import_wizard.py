from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QFileDialog,
    QMessageBox, QSpinBox, QGroupBox, QScrollArea,
    QFormLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from file_reader import FileReader
from pathlib import Path

MAPPING_ROLES = [
    ("ignore", "Не импортировать"),
    ("primary_text", "Запрос"),
    ("response_text", "Ответ модели"),
    ("ticket_number", "Номер обращения"),
    ("product", "Продукт"),
    ("operator_response", "Ответ оператора"),
    ("group_name", "Группа / категория"),
    ("source_id", "Идентификатор"),
    ("comment_source", "Комментарий из источника"),
    ("metadata", "Дополнительное поле"),
]


class ImportWizard(QWidget):
    import_finished = Signal()

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
        btn_select = QPushButton("📂 Выбрать файл")
        btn_select.setMinimumHeight(35)
        btn_select.clicked.connect(self.on_select_file)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(btn_select)
        layout.addLayout(file_layout)

        self.sheet_group = QGroupBox("📑 Лист Excel")
        sheet_layout = QHBoxLayout()
        self.sheet_combo = QComboBox()
        self.sheet_combo.setMinimumHeight(30)
        self.sheet_combo.currentIndexChanged.connect(self.on_sheet_changed)
        sheet_layout.addWidget(QLabel("Лист:"))
        sheet_layout.addWidget(self.sheet_combo)
        self.sheet_group.setLayout(sheet_layout)
        self.sheet_group.setVisible(False)
        layout.addWidget(self.sheet_group)

        header_layout = QHBoxLayout()
        self.header_spin = QSpinBox()
        self.header_spin.setMinimum(0)
        self.header_spin.setMaximum(100)
        self.header_spin.setValue(0)
        self.header_spin.setMinimumHeight(30)
        self.header_spin.valueChanged.connect(self.on_header_changed)
        header_layout.addWidget(QLabel("Строка заголовка (0 = первая):"))
        header_layout.addWidget(self.header_spin)
        header_layout.addStretch()
        layout.addLayout(header_layout)

        preview_label = QLabel("📋 Превью данных:")
        preview_label.setStyleSheet("font-size: 14px; font-weight: bold;")
        layout.addWidget(preview_label)

        self.preview_table = QTableWidget()
        self.preview_table.setMinimumHeight(150)
        self.preview_table.setStyleSheet("""
            QTableWidget {
                background-color: #0D150D;
                border: 2px solid #00441A;
                border-radius: 8px;
                color: #00FF41;
                font-size: 11px;
                gridline-color: #00441A;
            }
            QTableWidget::item { padding: 5px; }
            QHeaderView::section {
                background-color: #1A3A1A;
                color: #00FF41;
                border: 1px solid #007722;
                padding: 6px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.preview_table)

        buttons_layout = QHBoxLayout()
        btn_next = QPushButton("➡️ Далее: маппинг колонок")
        btn_next.setMinimumHeight(40)
        btn_next.clicked.connect(self.on_next_step)
        btn_cancel = QPushButton("❌ Отмена")
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
            "Исключение: «Идентификатор» — только одна колонка."
        )
        hint.setStyleSheet("color: #00AA2A; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumHeight(250)
        scroll.setStyleSheet("""
            QScrollArea {
                border: 2px solid #00441A;
                border-radius: 8px;
                background-color: #0A0F0A;
            }
        """)
        self.mapping_container = QWidget()
        self.mapping_layout = QFormLayout()
        self.mapping_layout.setSpacing(8)
        self.mapping_layout.setContentsMargins(10, 10, 10, 10)
        self.mapping_container.setLayout(self.mapping_layout)
        scroll.setWidget(self.mapping_container)
        layout.addWidget(scroll)

        buttons_layout = QHBoxLayout()
        btn_back = QPushButton("⬅️ Назад")
        btn_back.setMinimumHeight(40)
        btn_back.clicked.connect(self.on_back_step)
        btn_import = QPushButton("🚀 Начать импорт")
        btn_import.setMinimumHeight(40)
        btn_import.setStyleSheet("""
            QPushButton { border-color: #00FF41; color: #00FF41; font-weight: bold; }
            QPushButton:hover { background-color: #003315; }
        """)
        btn_import.clicked.connect(self.on_import)
        btn_cancel = QPushButton("❌ Отмена")
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
            "Таблицы (*.xlsx *.xls *.csv);;Excel (*.xlsx *.xls);;CSV (*.csv);;"
            "JSON (*.json *.jsonl);;Все файлы (*.*)"
        )
        if not file_path:
            return
        self.file_path = file_path
        self.file_label.setText(Path(file_path).name)
        self.file_type = self.file_reader.detect_file_type(file_path)

        if self.file_type == 'excel':
            try:
                sheets = self.file_reader.read_excel_sheets(file_path)
                self.sheet_combo.clear()
                self.sheet_combo.addItems(sheets)
                self.sheet_group.setVisible(True)
                self.sheet_name = sheets[0] if sheets else None
                self.load_preview()
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", str(e))
        elif self.file_type == 'csv':
            self.sheet_group.setVisible(False)
            self.load_preview()
        elif self.file_type in ['json', 'jsonl']:
            self.sheet_group.setVisible(False)
            self.load_preview()
        else:
            QMessageBox.warning(self, "Неподдерживаемый формат",
                "Пока поддерживаются: .xlsx, .csv, .json, .jsonl")

    def on_sheet_changed(self):
        self.sheet_name = self.sheet_combo.currentText()
        self.load_preview()

    def on_header_changed(self):
        self.load_preview()

    def load_preview(self):
        if not self.file_path:
            return
        try:
            if self.file_type == 'excel':
                self.preview_data = self.file_reader.read_excel_preview(
                    self.file_path, self.sheet_name, max_rows=100)
            elif self.file_type == 'csv':
                self.preview_data = self.file_reader.read_csv_preview(
                    self.file_path, encoding='utf-8', delimiter=',', max_rows=100)
            elif self.file_type == 'json':
                self.preview_data = self.file_reader.read_json_preview(
                    self.file_path, max_rows=100)
            elif self.file_type == 'jsonl':
                self.preview_data = self.file_reader.read_jsonl_preview(
                    self.file_path, max_rows=100)
            self.update_preview_table()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", str(e))

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
            QMessageBox.warning(self, "Внимание", "Сначала выберите файл")
            return
        if not self.preview_data or not self.preview_data['headers']:
            QMessageBox.warning(self, "Внимание", "Нет данных для маппинга")
            return
        self.build_mapping_ui()
        self.step1_widget.setVisible(False)
        self.step2_widget.setVisible(True)
        self.title.setText("🔧 МАППИНГ КОЛОНОК")

    def build_mapping_ui(self):
        while self.mapping_layout.count():
            item = self.mapping_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.mapping_combos.clear()

        headers = self.preview_data['headers']
        for header in headers:
            combo = QComboBox()
            combo.setMinimumHeight(30)
            for role_code, role_name in MAPPING_ROLES:
                combo.addItem(role_name, role_code)
            if header == headers[0]:
                combo.setCurrentIndex(1)  # primary_text
            self.mapping_layout.addRow(QLabel(str(header)), combo)
            self.mapping_combos[header] = combo

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
            QMessageBox.warning(self, "Ошибка маппинга", error)
            return

        try:
            if self.file_type == 'excel':
                data = self.file_reader.read_excel_data(
                    self.file_path, self.sheet_name,
                    header_row=self.header_spin.value())
            elif self.file_type == 'csv':
                data = self.file_reader.read_csv_data(
                    self.file_path, encoding='utf-8', delimiter=',',
                    header_row=self.header_spin.value())
            elif self.file_type == 'json':
                data = self.file_reader.read_json_data(self.file_path)
            elif self.file_type == 'jsonl':
                data = self.file_reader.read_jsonl_data(self.file_path)
            else:
                QMessageBox.warning(self, "Ошибка", "Неподдерживаемый формат")
                return

            if not data:
                QMessageBox.warning(self, "Внимание", "Файл не содержит данных")
                return

            from importer import import_file
            file_id, cases_count = import_file(
                project_path=self.project_path,
                file_path=self.file_path,
                file_type=self.file_type,
                sheet_name=self.sheet_name,
                header_row=self.header_spin.value(),
                mapping=mapping,
                data=data
            )
            QMessageBox.information(self, "Импорт завершён",
                f"✅ Успешно импортировано {cases_count} кейсов.")
            self.import_finished.emit()
        except Exception as e:
            QMessageBox.critical(self, "Ошибка импорта", str(e))

    def on_cancel(self):
        self.import_finished.emit()