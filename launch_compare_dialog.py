"""Сравнение двух запусков: что изменилось (без автовывода)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem,
)
from ui_compat import (FComboBox, FPushButton, clear_in_fluent, notify,
                       polish_table)
import regression_service as rg


class LaunchCompareDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self._fixed_ids: list = []
        self._broken_ids: list = []
        self.setWindowTitle("Сравнение запусков")
        self.setMinimumSize(720, 520)
        layout = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("A:"))
        self.combo_a = FComboBox()
        row.addWidget(self.combo_a, 2)
        row.addWidget(QLabel("B:"))
        self.combo_b = FComboBox()
        row.addWidget(self.combo_b, 2)
        btn = FPushButton("⇄ Сравнить")
        btn.clicked.connect(self._compare)
        row.addWidget(btn)
        layout.addLayout(row)
        self.summary = QLabel("Выбери два запуска.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass
        drow = QHBoxLayout()
        self.btn_fixed = FPushButton("✅ Исправленные → ревью")
        self.btn_fixed.clicked.connect(lambda: self._drill(True))
        self.btn_broken = FPushButton("❌ Новые регрессии → ревью")
        self.btn_broken.clicked.connect(lambda: self._drill(False))
        drow.addWidget(self.btn_fixed)
        drow.addWidget(self.btn_broken)
        drow.addStretch()
        layout.addLayout(drow)
        btns = QHBoxLayout()
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._reload_lists()

    def _reload_lists(self):
        try:
            rows = rg.list_regressions(self.project_path)
        except Exception:
            rows = []
        for combo, idx in ((self.combo_a, 1), (self.combo_b, 0)):
            try:
                combo.blockSignals(True)
                combo.clear()
                for r in rows:
                    combo.addItem(
                        f"#{r['regression_id']} {r.get('name') or ''} "
                        f"({r.get('gate_result') or '?'})",
                        r["regression_id"])
                if combo.count() > idx:
                    combo.setCurrentIndex(idx)
            except Exception:
                pass
            finally:
                try:
                    combo.blockSignals(False)
                except Exception:
                    pass

    def _compare(self):
        try:
            res = rg.compare_launches(
                self.project_path, self.combo_a.currentData(),
                self.combo_b.currentData())
        except ValueError as e:
            notify(self, "warning", "Сравнение", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        a, b = res["a"], res["b"]
        self.summary.setText(
            f"A #{a['regression_id']} {a.get('name') or ''} "
            f"[{a.get('gate_result') or '?'}] → "
            f"B #{b['regression_id']} {b.get('name') or ''} "
            f"[{b.get('gate_result') or '?'}]: "
            f"исправлено {len(res['fixed'])}, "
            f"новых регрессий {len(res['broken'])}"
            + (" (показаны первые)" if res.get("truncated") else ""))
        self._fixed_ids = list(res.get("fixed_ids") or [])
        self._broken_ids = list(res.get("broken_ids") or [])
        rows = res.get("rows", [])
        self.table.clear()
        self.table.setColumnCount(4)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["Ключ", "Кейс", "A → B", "Итог"])
        kinds = {"fixed": "✅ исправлена", "broken": "❌ регрессия",
                 "same": "без изменений", "only_a": "только в A",
                 "only_b": "только в B"}
        for i, r in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(r["stable_key"] or ""))
            self.table.setItem(
                i, 1, QTableWidgetItem(str(r["case_id"] or "—")))
            self.table.setItem(
                i, 2, QTableWidgetItem(
                    f"{r['res_a'] or '?'} → {r['res_b'] or '?'}"))
            self.table.setItem(
                i, 3, QTableWidgetItem(kinds.get(r["kind"], r["kind"])))
        self.table.resizeColumnsToContents()

    def _drill(self, fixed: bool):
        ids = list(self._fixed_ids if fixed else self._broken_ids)
        if not ids:
            notify(self, "warning", "Сравнение", "Кейсов нет")
            return
        try:
            scr = self.parent()
            mw = getattr(getattr(scr, "parent_window", None),
                         "main_window", None)
            if mw is None or not hasattr(mw, "show_screen"):
                raise ValueError("review")
            mw.show_screen("review", {"case_ids": ids})
            try:
                rev = mw.project_window.screens.get("review")
                if rev is not None:
                    rev.current_page = 0
                    rev.load_table_data()
            except Exception:
                pass
            self.accept()
        except Exception:
            notify(self, "warning", "Сравнение",
                   "Некуда приземлить: открой ревью и повтори.")
