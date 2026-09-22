"""Компактный Ctrl+P диалог (ТЗ V2.2 §13): без отдельного экрана.

Enter: одно совпадение — сразу открыть; несколько — выбрать из списка.
Живой поиск по мере ввода не делаем (лишний шум в БД) — только по Enter.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import FLineEdit, FPushButton, FPrimaryButton, clear_in_fluent
import global_search_service as gs


class GlobalSearchDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.result_case_id = None
        self.setWindowTitle("Найти кейс (Ctrl+P)")
        self.setMinimumSize(520, 380)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        hint = QLabel("ID кейса, source ID (точно/частично) или текст вопроса. Enter — найти.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.edit = FLineEdit()
        self.edit.setPlaceholderText("например: 1234, Номер обращения, часть вопроса…")
        self.edit.returnPressed.connect(self._search)
        layout.addWidget(self.edit)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._pick())
        layout.addWidget(self.list, 2)
        btns = QHBoxLayout()
        go = FPrimaryButton("Найти")
        go.clicked.connect(self._search)
        open_btn = FPushButton("Открыть")
        open_btn.clicked.connect(self._pick)
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addWidget(go)
        btns.addWidget(open_btn)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
        try:
            clear_in_fluent(self.list)
            clear_in_fluent(self)
        except Exception:
            pass
        self.edit.setFocus()

    def _search(self):
        q = self.edit.text()
        try:
            rows = gs.search_cases(self.project_path, q)
        except Exception:
            rows = []
        self.list.clear()
        if len(rows) == 1:
            # Одно совпадение — сразу открываем, без лишнего клика.
            self.result_case_id = rows[0]["case_id"]
            self.accept()
            return
        for r in rows:
            label = f"#{r['case_id']} [{r['source_id'] or '—'}] {r['snippet'][:100]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.list.addItem(item)
        if not rows:
            item = QListWidgetItem("Ничего не найдено")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(item)

    def _pick(self):
        item = self.list.currentItem()
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid:
            self.result_case_id = int(cid)
            self.accept()
