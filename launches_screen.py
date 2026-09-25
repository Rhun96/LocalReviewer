"""Экран «Запуски» (рескин по референсу): история регрессионных запусков."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
)
from PySide6.QtCore import Qt
from ui_base import BaseScreen
from ui_compat import (FComboBox, FLineEdit, FPushButton, FPrimaryButton,
                       clear_in_fluent, confirm, notify, polish_table)
import regression_service as rg


class LaunchesScreen(BaseScreen):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._rows = []
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("🚀 ЗАПУСКИ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        subtitle = QLabel("Замеры: baseline vs кандидат, вердикт gate "
                          "(сырые ответы модели — в «Прогонах»)")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        try:
            from styles import COLORS as _CC
            subtitle.setStyleSheet(
                f"font-size: 11px; color: {_CC['gray']};")
        except Exception:
            pass
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Gate:"))
        self.gate_combo = FComboBox()
        self.gate_combo.addItem("Все", None)
        self.gate_combo.addItem("✅ PASS", "PASS")
        self.gate_combo.addItem("❌ FAIL", "FAIL")
        self.gate_combo.currentIndexChanged.connect(self.refresh)
        filt.addWidget(self.gate_combo)
        filt.addWidget(QLabel("Поиск:"))
        self.search_edit = FLineEdit()
        self.search_edit.setPlaceholderText("Название, кандидат… (Enter)")
        self.search_edit.returnPressed.connect(self.refresh)
        filt.addWidget(self.search_edit, 3)
        btn_find = FPushButton("🔍 Найти")
        btn_find.clicked.connect(self.refresh)
        filt.addWidget(btn_find)
        layout.addLayout(filt)

        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass

        btns = QHBoxLayout()
        btn_run = FPrimaryButton("▶ Запустить")
        btn_run.setToolTip("Новый регрессионный запуск (baseline vs кандидат)")
        btn_run.clicked.connect(self._run_new)
        btn_open = FPushButton("📝 Открыть")
        btn_open.clicked.connect(self._open_run)
        btn_del = FPushButton("🗑 Удалить")
        btn_del.clicked.connect(self._delete_run)
        btns.addWidget(btn_run)
        btns.addWidget(btn_open)
        btns.addWidget(btn_del)
        btns.addStretch()
        layout.addLayout(btns)
        self.setLayout(layout)
        self.table.itemDoubleClicked.connect(lambda _i: self._open_run())

    def refresh(self):
        gate = self.gate_combo.currentData()
        q = (self.search_edit.text() or "").strip().lower()
        try:
            rows = rg.list_regressions(self.project_path)
        except Exception as e:
            self.show_error("Не удалось загрузить запуски", e)
            rows = []
        shown = []
        for r in rows:
            if gate and (r.get("gate_result") or "") != gate:
                continue
            if q:
                cand = rg.candidate_label(self.project_path, r).lower()
                if q not in (r.get("name") or "").lower() and q not in cand:
                    continue
            shown.append(r)
        self._rows = shown
        try:
            from PySide6.QtGui import QColor as _QC
            from styles import SEMANTIC as _SEM
            _GATE_FG = {"PASS": _QC(_SEM["success"]),
                        "FAIL": _QC(_SEM["danger"])}
        except Exception:
            _GATE_FG = {}
        self.table.clear()
        self.table.setColumnCount(7)
        self.table.setRowCount(len(shown))
        self.table.setHorizontalHeaderLabels(
            ["ID", "Дата", "Название", "Кандидат", "Gate",
             "Регрессии", "Улучшения"])
        for i, r in enumerate(shown):
            self.table.setItem(i, 0, QTableWidgetItem(str(r["regression_id"])))
            from ui_compat import format_dt as _fdt
            self.table.setItem(
                i, 1, QTableWidgetItem(_fdt(r.get("created_at"))))
            self.table.setItem(i, 2, QTableWidgetItem(r.get("name") or ""))
            self.table.setItem(
                i, 3, QTableWidgetItem(
                    rg.candidate_label(self.project_path, r)))
            gate_txt = "✅ PASS" if r.get("gate_result") == "PASS" else "❌ FAIL"
            _gate_item = QTableWidgetItem(gate_txt)
            try:
                _fg = _GATE_FG.get(r.get("gate_result") or "")
                if _fg is not None:
                    _gate_item.setForeground(_fg)
            except Exception:
                pass
            self.table.setItem(i, 4, _gate_item)
            total = int(r.get("total") or 0)
            n_reg = int(r.get("regressions") or 0)
            _reg_item = QTableWidgetItem(f"{n_reg}/{total}")
            try:
                if n_reg > 0:
                    _reg_item.setForeground(_QC(_SEM["danger"]))
            except Exception:
                pass
            self.table.setItem(i, 5, _reg_item)
            n_imp = int(r.get("improvements") or 0)
            _imp_item = QTableWidgetItem(f"+{n_imp}")
            try:
                if n_imp > 0:
                    _imp_item.setForeground(_QC(_SEM["success"]))
            except Exception:
                pass
            self.table.setItem(i, 6, _imp_item)
            self.table.item(i, 0).setData(
                Qt.ItemDataRole.UserRole, r["regression_id"])
        self.table.resizeColumnsToContents()

    def _selected_id(self) -> int | None:
        item = self.table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери запуск в таблице")
            return None
        row_item = self.table.item(item.row(), 0)
        return row_item.data(Qt.ItemDataRole.UserRole) if row_item else None

    def _run_new(self):
        from regression_dialog import RegressionDialog
        dlg = RegressionDialog(self.project_path, self)
        dlg.exec()
        self.refresh()

    def _open_run(self):
        rid = self._selected_id()
        if rid is None:
            return
        from regression_dialog import RegressionDialog
        dlg = RegressionDialog(self.project_path, self, regression_id=rid)
        dlg.exec()
        self.refresh()

    def _delete_run(self):
        rid = self._selected_id()
        if rid is None:
            return
        if not confirm(self, "Подтверждение", "Удалить запуск регрессии?"):
            return
        try:
            rg.delete_regression(self.project_path, rid)
        except Exception as e:
            self.show_error("Не удалось удалить запуск", e)
            return
        self.refresh()
