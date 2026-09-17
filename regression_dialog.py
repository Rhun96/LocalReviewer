"""Регрессионное тестирование: baseline vs candidate, gate PASS/FAIL, экспорт."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QFormLayout,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FLineEdit, FPrimaryButton, FPushButton,
                       FSpinBox, clear_in_fluent, confirm, notify)
import regression_service as rg
import model_run_service as mruns


class RegressionDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Регрессионное тестирование")
        self.setMinimumSize(920, 660)
        self._reg_id = None
        self._init_ui()
        self._reload_lists()

    def _init_ui(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = FLineEdit()
        self.name_edit.setPlaceholderText("Название запуска, например rel-1.8")
        form.addRow("Название:", self.name_edit)
        self.base_combo = FComboBox()
        form.addRow("Baseline (эталон):", self.base_combo)
        self.cand_combo = FComboBox()
        form.addRow("Кандидат (прогон):", self.cand_combo)
        gate_row = QHBoxLayout()
        self.gate_crit = FSpinBox()
        self.gate_crit.setRange(0, 100000)
        self.gate_crit.setValue(0)
        gate_row.addWidget(QLabel("Макс. критических:"))
        gate_row.addWidget(self.gate_crit)
        self.gate_rate = FSpinBox()
        self.gate_rate.setRange(0, 100)
        self.gate_rate.setValue(2)
        self.gate_rate.setSuffix(" %")
        gate_row.addWidget(QLabel("Макс. regression rate:"))
        gate_row.addWidget(self.gate_rate)
        gate_row.addStretch()
        form.addRow("Gate:", gate_row)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_run = FPrimaryButton("▶ Запустить сравнение")
        btn_run.clicked.connect(self._run)
        btn_row.addWidget(btn_run)
        btn_row.addWidget(QLabel("Прошлые:"))
        self.past_combo = FComboBox()
        btn_row.addWidget(self.past_combo, 2)
        btn_load = FPushButton("Открыть")
        btn_load.clicked.connect(self._load_past)
        btn_row.addWidget(btn_load)
        btn_del = FPushButton("🗑")
        btn_del.setMaximumWidth(44)
        btn_del.clicked.connect(self._delete_past)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        self.summary = QLabel("Выбери baseline и кандидата, нажми «Запустить».")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Итог:"))
        self.result_combo = FComboBox()
        self.result_combo.addItem("Все", None)
        for code in ("REGRESSION", "IMPROVED", "UNCHANGED", "NEW", "REMOVED",
                     "UNRESOLVED"):
            self.result_combo.addItem(code, code)
        filt.addWidget(self.result_combo)
        filt.addWidget(QLabel("Severity:"))
        self.sev_combo = FComboBox()
        self.sev_combo.addItem("Все", None)
        for code in ("critical", "warning", "info"):
            self.sev_combo.addItem(code, code)
        filt.addWidget(self.sev_combo)
        btn_apply = FPushButton("Применить")
        btn_apply.clicked.connect(self._load_results)
        filt.addWidget(btn_apply)
        btn_export = FPushButton("📤 Экспорт регрессий")
        btn_export.clicked.connect(self._export)
        filt.addWidget(btn_export)
        btn_bug = FPushButton("🐞 Создать баг")
        btn_bug.setToolTip("Баг из выбранной строки — контекст подставится сам")
        btn_bug.clicked.connect(self._create_bug)
        filt.addWidget(btn_bug)
        layout.addLayout(filt)

        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
        except Exception:
            pass
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        self.setLayout(layout)

    def _reload_lists(self):
        try:
            bases = rg.list_baseline_candidates(self.project_path)
            runs = mruns.list_runs(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.base_combo.clear()
        for b in bases:
            mark = "" if b.get("frozen", True) else " ⚠ не заморожен"
            self.base_combo.addItem(b["label"] + mark, (b["type"], b["id"]))
        self.cand_combo.clear()
        for r in runs:
            self.cand_combo.addItem(f"{r['name']} ({r['model_name']})", r["run_id"])
        self._reload_past()

    def _reload_past(self):
        try:
            past = rg.list_regressions(self.project_path)
        except Exception:
            past = []
        self.past_combo.clear()
        for p in past:
            self.past_combo.addItem(
                f"{p['name']} [{p['gate_result']}] "
                f"регр:{p['regressions']}/{p['total']}", p["regression_id"])

    def _run(self):
        name = self.name_edit.text().strip()
        base = self.base_combo.currentData()
        cand = self.cand_combo.currentData()
        if not name:
            notify(self, "warning", "Внимание", "Введи название запуска")
            return
        if not base or not cand:
            notify(self, "warning", "Внимание", "Выбери baseline и кандидата")
            return
        try:
            rid = rg.run_regression(
                self.project_path, name, base[0], base[1], cand,
                gate_max_critical=self.gate_crit.value(),
                gate_max_rate=self.gate_rate.value() / 100)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._reg_id = rid
        self._reload_past()
        self._show_summary()
        self._load_results()

    def _load_past(self):
        rid = self.past_combo.currentData()
        if not rid:
            return
        self._reg_id = rid
        self._show_summary()
        self._load_results()

    def _delete_past(self):
        rid = self.past_combo.currentData()
        if not rid:
            return
        if not confirm(self, "Подтверждение", "Удалить запуск регрессии?"):
            return
        try:
            rg.delete_regression(self.project_path, rid)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        if self._reg_id == rid:
            self._reg_id = None
        self._reload_past()

    def _show_summary(self):
        reg = rg.get_regression(self.project_path, self._reg_id)
        if not reg:
            return
        gate = reg["gate_result"] or "?"
        self.summary.setText(
            f"{'✅ PASS' if gate == 'PASS' else '❌ FAIL'} {reg['name']}: "
            f"всего {reg['total']}, регрессий {reg['regressions']} "
            f"(rate {reg['regression_rate']:.1%}), улучшений {reg['improvements']}, "
            f"без изменений {reg['unchanged']}.")

    def _load_results(self):
        if not self._reg_id:
            return
        try:
            rows = rg.list_regression_results(
                self.project_path, self._reg_id,
                result=self.result_combo.currentData(),
                severity=self.sev_combo.currentData())
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.table.clear()
        self.table.setColumnCount(6)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["Ключ", "Было", "Стало", "Итог", "Severity", "Запрос"])
        for i, r in enumerate(rows):
            key = r["source_id"] or r["stable_key"]
            self.table.setItem(i, 0, QTableWidgetItem(str(key)[:40]))
            self.table.setItem(i, 1, QTableWidgetItem(r["baseline_status"] or "—"))
            self.table.setItem(i, 2, QTableWidgetItem(r["candidate_status"] or "—"))
            self.table.setItem(i, 3, QTableWidgetItem(r["result"]))
            self.table.setItem(i, 4, QTableWidgetItem(r["severity"]))
            self.table.setItem(i, 5, QTableWidgetItem((r["primary_text"] or "")[:80]))
        self.table.resizeColumnsToContents()

    def _export(self):
        if not self._reg_id:
            notify(self, "warning", "Внимание", "Сначала запусти сравнение")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт регрессий", "regressions.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        try:
            out = rg.export_regressions_xlsx(self.project_path, self._reg_id, path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Экспорт", f"Сохранено:\n{out}")

    def _create_bug(self):
        """Баг из выбранной строки регрессии — без ручного копирования (§34)."""
        if not self._reg_id:
            notify(self, "warning", "Внимание", "Сначала запусти сравнение")
            return
        item = self.table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери строку в таблице")
            return
        # Строка таблицы 1-в-1 соответствует выдаче с текущими фильтрами.
        try:
            rows = rg.list_regression_results(
                self.project_path, self._reg_id,
                result=self.result_combo.currentData(),
                severity=self.sev_combo.currentData())
            row = rows[item.row()] if 0 <= item.row() < len(rows) else None
        except Exception as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        if not row:
            return
        try:
            prefill = rg.bug_prefill(self.project_path, self._reg_id,
                                     row["stable_key"])
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, prefill, None, self)
        dlg.exec()
