"""Экран «Баги» (ТЗ V2 §21): таблица, фильтры, поиск, создание/правка."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
)
from PySide6.QtCore import Qt
from database import db
from ui_base import BaseScreen
from ui_compat import (FComboBox, FLineEdit, FPushButton, FPrimaryButton,
                       clear_in_fluent, confirm, notify, polish_table)
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
            self.status_combo.addItem(bugs.BUG_STATUS_NAMES.get(s, s), s)
        filt.addWidget(self.status_combo)
        filt.addWidget(QLabel("Критичность:"))
        self.sev_combo = FComboBox()
        self.sev_combo.addItem("Все", None)
        for s in bugs.SEVERITIES:
            self.sev_combo.addItem(bugs.BUG_SEVERITY_NAMES.get(s, s), s)
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
            "Поиск: заголовок, описание, ID кейса, external ID… (Enter)")
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
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass

        btns = QHBoxLayout()
        btn_new = FPrimaryButton("＋ Баг")
        btn_new.setToolTip("Пустой баг (кейсы привяжешь внутри)")
        btn_new.clicked.connect(self._new_bug)
        btn_open = FPushButton("📝 Открыть")
        btn_open.clicked.connect(self._open_bug)
        btn_copy = FPushButton("📋 Копировать")
        btn_copy.setToolTip("Скопировать выбранный баг без открытия карточки "
                            "(Jira/Markdown/Plain, контекст подтянется сам)")
        btn_copy.clicked.connect(self._copy_menu)
        btn_del = FPushButton("🗑 Удалить")
        btn_del.clicked.connect(self._delete_bug)
        btns.addWidget(btn_new)
        btns.addWidget(btn_open)
        btns.addWidget(btn_copy)
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
            ["ID", "Заголовок", "Статус", "Критичность", "Категория", "Кейсы",
             "External", "Обновлён"])
        # Цвет статуса и критичности (только foreground — делегат библиотеки).
        try:
            from PySide6.QtGui import QColor as _QC
            from styles import SEMANTIC as _SEM, COLORS as _CC
            _ST_FG = {"New": _QC(_SEM["info"]),
                      "Confirmed": _QC(_SEM["warning"]),
                      "In Progress": _QC(_CC["blue"]),
                      "Fixed": _QC(_SEM["success"]),
                      "Rejected": _QC(_CC["gray"]),
                      "Duplicate": _QC(_CC["gray"])}
            _SEV_FG = {"Critical": _QC(_SEM["danger"]),
                       "High": _QC(_SEM["danger"]),
                       "Medium": _QC(_SEM["warning"]),
                       "Low": _QC(_CC["gray"])}
        except Exception:
            _ST_FG = {}
            _SEV_FG = {}
        for i, r in enumerate(rows):
            cat = cats.get(r["category_id"], "") if r["category_id"] else ""
            st = bugs.BUG_STATUS_NAMES.get(r["status"] or "", r["status"] or "")
            sv = bugs.BUG_SEVERITY_NAMES.get(r["severity"] or "", r["severity"] or "")
            self.table.setItem(i, 0, QTableWidgetItem(str(r["bug_id"])))
            self.table.setItem(i, 1, QTableWidgetItem((r["title"] or "")[:80]))
            _st_item = QTableWidgetItem(st)
            try:
                _fg = _ST_FG.get(r["status"] or "")
                if _fg is not None:
                    _st_item.setForeground(_fg)
            except Exception:
                pass
            self.table.setItem(i, 2, _st_item)
            _sev_item = QTableWidgetItem(sv)
            try:
                _fg = _SEV_FG.get(r["severity"] or "")
                if _fg is not None:
                    _sev_item.setForeground(_fg)
            except Exception:
                pass
            self.table.setItem(i, 3, _sev_item)
            self.table.setItem(i, 4, QTableWidgetItem(cat))
            self.table.setItem(i, 5, QTableWidgetItem(str(r["cases"])))
            self.table.setItem(i, 6, QTableWidgetItem(r["external_id"] or "—"))
            from ui_compat import format_dt as _fdt
            self.table.setItem(i, 7, QTableWidgetItem(_fdt(r["updated_at"])))
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
        cid = getattr(dlg, "result_case_id", None)
        if cid:
            try:
                mw = getattr(getattr(self, "parent_window", None),
                             "main_window", None)
                if mw is not None and hasattr(mw, "show_screen"):
                    mw.show_screen("review")
                    scr = mw.project_window.screens.get("review")
                    if scr is not None and cid in (scr.case_ids or []):
                        scr.load_case(scr.case_ids.index(cid))
            except Exception:
                pass

    def _copy_menu(self):
        """V2.2 §16: копия бага из списка без открытия карточки."""
        bid = self._selected_id()
        if bid is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for fmt, label in (("jira", "Copy for Jira"),
                           ("markdown", "Copy Markdown"),
                           ("plain", "Copy Plain Text")):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _c, f=fmt, name=label: self._do_copy(bid, f, name))
        anchor = self.sender()
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _do_copy(self, bug_id: int, fmt: str, label: str):
        import bug_export_service as bex
        try:
            text = bex.render(self.project_path, bug_id, fmt)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            import clipboard_service as _clip
            _clip.safe_copy(text)
            _after = _clip.get_clear_after()
            suffix = (f" Буфер будет очищен через {_clip.timeout_label(_after)}."
                      if _after else "")
        except Exception:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
            suffix = ""
        notify(self, "success", "Скопировано", f"Баг #{bug_id} ({label}) — в буфере.{suffix}")

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
