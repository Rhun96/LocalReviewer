"""Круговая таблица прогонов: каждый с каждым + места.

Ячейка «победы A : победы B (ничьи, неразмечено)», двойной клик —
пара рядом в CompareDialog. Места — очки Копленда из предпочтений.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, clear_in_fluent, polish_table
import model_run_service as m


class RoundRobinDialog(QDialog):
    def __init__(self, project_path: str, run_ids: list, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.run_ids = list(run_ids)
        self._pairs: dict = {}
        self.setWindowTitle("Круговая таблица прогонов")
        self.setMinimumSize(720, 520)
        layout = QVBoxLayout()
        self.standings_label = QLabel("")
        self.standings_label.setWordWrap(True)
        layout.addWidget(self.standings_label)
        self.table = QTableWidget()
        self.table.setToolTip("Двойной клик по ячейке — пара рядом")
        self.table.itemDoubleClicked.connect(self._open_pair)
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass
        btns = QHBoxLayout()
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._reload()

    def _reload(self):
        try:
            res = m.roundrobin_matrix(self.project_path, self.run_ids)
        except Exception as e:
            self.standings_label.setText(f"Не удалось посчитать: {e}")
            return
        runs = res["runs"]
        self._pairs = {(p["a"], p["b"]): p for p in res["pairs"]}
        medals = ["🥇", "🥈", "🥉"]
        lines = []
        for i, s in enumerate(res["standings"]):
            lines.append(f"{medals[i] if i < 3 else f'{i + 1}.'} "
                         f"{s['name']}: {s['score']} "
                         f"(побед в парах: {s['wins']})")
        self.standings_label.setText("Места: " + " · ".join(lines))
        n = len(runs)
        self.table.clear()
        self.table.setColumnCount(n)
        self.table.setRowCount(n)
        self.table.setHorizontalHeaderLabels([r["name"] for r in runs])
        self.table.setVerticalHeaderLabels([r["name"] for r in runs])
        for x in range(n):
            for y in range(n):
                if x == y:
                    it = QTableWidgetItem("—")
                else:
                    a, b = runs[x]["run_id"], runs[y]["run_id"]
                    p = self._pairs.get((a, b)) or self._pairs.get((b, a))
                    if p is None:
                        it = QTableWidgetItem("—")
                    else:
                        wa, wb = p["wins_a"], p["wins_b"]
                        if p["a"] != a:
                            wa, wb = wb, wa
                        txt = f"{wa}:{wb}"
                        extra = []
                        if p["ties"]:
                            extra.append(f"ничьи {p['ties']}")
                        if p["unjudged"]:
                            extra.append(f"без вердикта {p['unjudged']}")
                        if extra:
                            txt += f" ({', '.join(extra)})"
                        it = QTableWidgetItem(txt)
                        it.setData(Qt.ItemDataRole.UserRole, (p["a"], p["b"]))
                it.setFlags(it.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self.table.setItem(x, y, it)
        self.table.resizeColumnsToContents()

    def _open_pair(self, item):
        try:
            from PySide6.QtCore import Qt as _Q
            pair = item.data(_Q.ItemDataRole.UserRole)
        except Exception:
            pair = None
        if not pair:
            return
        try:
            from compare_dialog import CompareDialog
            CompareDialog(self.project_path, pair[0], pair[1],
                          self).exec()
        except Exception:
            return
        try:
            self._reload()
        except Exception:
            pass
