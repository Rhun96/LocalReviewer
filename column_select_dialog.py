"""Диалог выбора столбцов таблицы (вынесен из review_screen для модульности)."""
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget,
)
from ui_compat import FCheckBox, FPrimaryButton, FPushButton, clear_in_fluent


class ColumnSelectDialog(QDialog):
    def __init__(self, columns, selected_columns, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Выбор столбцов")
        self.setMinimumWidth(400)
        self.columns = columns
        self.selected_columns = selected_columns
        self.checkboxes = {}
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout()
        for col in self.columns:
            cb = FCheckBox(col)
            cb.setChecked(col in self.selected_columns)
            self.checkboxes[col] = cb
            content_layout.addWidget(cb)
        content.setLayout(content_layout)
        scroll.setWidget(content)
        layout.addWidget(scroll)
        clear_in_fluent(scroll)
        buttons = QHBoxLayout()
        btn_ok = FPrimaryButton("✅ Применить")
        btn_ok.setMinimumHeight(35)
        btn_ok.clicked.connect(self.accept)
        btn_cancel = FPushButton("❌ Отмена")
        btn_cancel.setMinimumHeight(35)
        btn_cancel.clicked.connect(self.reject)
        buttons.addWidget(btn_ok)
        buttons.addWidget(btn_cancel)
        layout.addLayout(buttons)
        self.setLayout(layout)

    def get_selected_columns(self):
        return [col for col, cb in self.checkboxes.items() if cb.isChecked()]
