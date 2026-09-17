"""Экран «Баги» (ТЗ V2 §21): таблица, фильтры, поиск, создание/правка."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
)
from PySide6.QtCore import Qt
from database import db
from ui_base import BaseScreen
from ui_compat import (FComboBox, FLineEdit, FPushButton, FPrimaryButton,
                       clear_in_fluent, confirm, notify)
import bug_report_service as bugs


class BugReportsScreen(BaseScreen):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("🐞 БАГИ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Статус:"))
        self.status_combo = FComboBox()
        self.status_combo.addItem("Все", None)
        for s in bugs.STATUSES:
            self.status_combo.addItem(s, s)
        filt.addWidget(self.status_combo)
        filt.addWidget(QLabel("Severity:"))
        self.sev_combo = FComboBox()
        self.sev_combo.addItem("Все", None)
        for s in bugs.SEVERITIES:
            self.sev_combo.addItem(s, s)
        filt.addWidget(self.sev_combo)
        filt.addWidget(QLabel("Трекер:"))
        self.tracker_combo = FComboBox()
        self.tracker_combo.addItem("Все", None)
        self.tracker_combo.addItem("С external ID", "__has__")
        self.tracker_combo.addItem("Без external ID", "__none__")
        filt.addWidget(self.tracker_combo)
        layout.addLayout(filt)

        search_row = QHBoxLayout()
        self.search_edit = FLineEdit()
        self.search_edit.setPlaceholderText(
            "Поиск: title, описание, ID кейса, external ID… (Enter)")
        self.search_edit.returnPressed.connect(self.refresh)
        search_row.addWidget(self.search_edit, 3)
        btn_find = FPushButton("🔍 Найти")
        btn_find.clicked.connect(self.refresh)
        search_row.addWidget(btn_find)
        layout.addLayout(search_row)

        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
        except Exception:
            pass

        btns = QHBoxLayout()
        btn_new = FPrimaryButton("＋ Баг")
        btn_new.setToolTip("Пустой баг (кейсы привяжешь внутри)")
        btn_new.clicked.connect(self._new_bug)
        btn_open = FPushButton("📝 Открыть")
        btn_open.clicked.connect(self._open_bug)
        btn_del = FPushButton("🗑 Удалить")
        btn_del.clicked.connect(self._delete_bug)
        btns.addWidget(btn_new)
        btns.addWidget(btn_open)
        btns.addWidget(btn_del)
        btns.addStretch()
        layout.addLayout(btns)
        self.setLayout(layout)
        self.table.itemDoubleClicked.connect(lambda _i: self._open_bug())

    def refresh(self):
        has_ext = None
        tracker = self.tracker_combo.currentData()
        if tracker == "__has__":
            has_ext, tracker = True, None
        elif tracker == "__none__":
            has_ext, tracker = False, None
        try:
            rows = bugs.list_bugs(
                self.project_path,
                status=self.status_combo.currentData(),
                severity=self.sev_combo.currentData(),
                tracker=tracker, has_external=has_ext,
                search=self.search_edit.text())
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            rows = []
        self._rows = rows
        try:
            with db(self.project_path) as conn:
                cats = {r["category_id"]: r["name"] for r in conn.cursor().execute(
                    "SELECT category_id, name FROM error_categories").fetchall()}
        except Exception:
            cats = {}
        self.table.clear()
        self.table.setColumnCount(8)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["ID", "Title", "Status", "Severity", "Категория", "Кейсы",
             "External", "Обновлён"])
        for i, r in enumerate(rows):
            cat = cats.get(r["category_id"], "") if r["category_id"] else ""
            self.table.setItem(i, 0, QTableWidgetItem(str(r["bug_id"])))
            self.table.setItem(i, 1, QTableWidgetItem((r["title"] or "")[:80]))
            self.table.setItem(i, 2, QTableWidgetItem(r["status"]))
            self.table.setItem(i, 3, QTableWidgetItem(r["severity"]))
            self.table.setItem(i, 4, QTableWidgetItem(cat))
            self.table.setItem(i, 5, QTableWidgetItem(str(r["cases"])))
            self.table.setItem(i, 6, QTableWidgetItem(r["external_id"] or "—"))
            self.table.setItem(i, 7, QTableWidgetItem((r["updated_at"] or "")[:19]))
            self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, r["bug_id"])
        self.table.resizeColumnsToContents()

    def _selected_id(self) -> int | None:
        item = self.table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери баг в таблице")
            return None
        row_item = self.table.item(item.row(), 0)
        return row_item.data(Qt.ItemDataRole.UserRole) if row_item else None

    def _new_bug(self):
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, None, None, self)
        dlg.exec()
        self.refresh()

    def _open_bug(self):
        bid = self._selected_id()
        if bid is None:
            return
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, None, bid, self)
        dlg.exec()
        self.refresh()

    def _delete_bug(self):
        bid = self._selected_id()
        if bid is None:
            return
        if not confirm(self, "Подтверждение", f"Удалить баг #{bid}?"):
            return
        try:
            bugs.delete_bug(self.project_path, bid)
            self.refresh()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
