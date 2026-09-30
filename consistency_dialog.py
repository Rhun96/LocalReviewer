"""Контроль качества: противоречия себе + QC-выборка (только чтение и переходы)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTabWidget, QWidget, QLineEdit,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FPushButton, FSpinBox, clear_in_fluent,
                       notify)
import consistency_service as qc


class ConsistencyDialog(QDialog):
    """result_case_id — кейс для перехода (двойной клик / Открыть)."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.result_case_id = None
        self.setWindowTitle("Контроль качества")
        self.setMinimumSize(720, 560)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._conflicts_tab(), "⚖️ Противоречия")
        self.tabs.addTab(self._sample_tab(), "🎲 QC-выборка")
        layout = QVBoxLayout()
        layout.addWidget(self.tabs)
        btns = QHBoxLayout()
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.reject)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)

    # ---- Противоречия ----
    def _conflicts_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Похожие кейсы с противоположными вердиктами "
                                "(Хорошо vs Плохо). Разберись и переразметь."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Область:"))
        self.cf_scope = FComboBox()
        self.cf_scope.addItem("Весь проект", None)
        try:
            from report_service import get_files_list
            for f in get_files_list(self.project_path):
                self.cf_scope.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        row.addWidget(self.cf_scope)
        row.addWidget(QLabel("Порог:"))
        self.cf_thr = FComboBox()
        for pct in (30, 40, 50, 60, 75, 90):
            self.cf_thr.addItem(f"{pct} %", pct / 100)
        self.cf_thr.setCurrentIndex(1)
        row.addWidget(self.cf_thr)
        btn = FPushButton("🔍 Найти")
        btn.clicked.connect(self._find_conflicts)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        self.cf_info = QLabel("")
        self.cf_info.setWordWrap(True)
        layout.addWidget(self.cf_info)
        self.cf_list = QListWidget()
        self.cf_list.itemDoubleClicked.connect(self._open_selected)
        self.cf_list.currentItemChanged.connect(
            lambda *_a: self._show_conflict_pair())
        self.cf_list.setMinimumHeight(140)
        layout.addWidget(self.cf_list, 2)
        try:
            clear_in_fluent(self.cf_list)
        except Exception:
            pass
        from PySide6.QtWidgets import QSplitter, QTextBrowser
        cf_pair = QSplitter(Qt.Orientation.Horizontal)
        self.cf_pair_a = QTextBrowser()
        self.cf_pair_a.setReadOnly(True)
        self.cf_pair_a.setMinimumHeight(120)
        self.cf_pair_b = QTextBrowser()
        self.cf_pair_b.setReadOnly(True)
        self.cf_pair_b.setMinimumHeight(120)
        cf_pair.addWidget(self.cf_pair_a)
        cf_pair.addWidget(self.cf_pair_b)
        try:
            clear_in_fluent(self.cf_pair_a, self.cf_pair_b)
        except Exception:
            pass
        layout.addWidget(cf_pair, 1)
        pair_row = QHBoxLayout()
        self.btn_pair_a = FPushButton("➡️ Кейс 1")
        self.btn_pair_a.setToolTip("Открыть первый кейс пары")
        self.btn_pair_a.clicked.connect(lambda: self._open_pair_case(0))
        self.btn_pair_b = FPushButton("➡️ Кейс 2")
        self.btn_pair_b.setToolTip("Открыть второй кейс пары")
        self.btn_pair_b.clicked.connect(lambda: self._open_pair_case(1))
        pair_row.addWidget(self.btn_pair_a)
        pair_row.addWidget(self.btn_pair_b)
        pair_row.addStretch()
        layout.addLayout(pair_row)
        orow = QHBoxLayout()
        btn_open = FPushButton("➡️ Открыть выбранный")
        btn_open.clicked.connect(self._open_selected)
        orow.addWidget(btn_open)
        orow.addStretch()
        layout.addLayout(orow)
        w.setLayout(layout)
        return w

    def _find_conflicts(self):
        try:
            res = qc.find_conflicts(
                self.project_path, file_id=self.cf_scope.currentData(),
                threshold=self.cf_thr.currentData() or 0.4)
        except ValueError as e:
            notify(self, "warning", "Поиск", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.cf_list.clear()
        if not res["pairs"]:
            self.cf_info.setText("Противоречий нет. Если ожидал — снизь порог.")
            return
        tail = " (показаны первые)" if res.get("truncated") else ""
        self.cf_info.setText(f"Найдено пар: {res['total']}{tail}. "
                             "Двойной клик — открыть первый кейс пары.")
        for p in res["pairs"]:
            pct = int(round(p["score"] * 100))
            item = QListWidgetItem(
                f"{pct}% {p['status_a']} vs {p['status_b']} | "
                f"{p['source_a']} ↔ {p['source_b']}")
            item.setData(Qt.ItemDataRole.UserRole,
                         (p["case_a"], p["case_b"]))
            self.cf_list.addItem(item)
        try:
            if self.cf_list.count():
                self.cf_list.setCurrentRow(0)
        except Exception:
            pass
        self._show_conflict_pair()

    def _show_conflict_pair(self):
        """Превью выбранной пары: оба текста рядом, ходить не надо."""
        try:
            from similar_dialog import pair_preview
            item = self.cf_list.currentItem()
            if item is None:
                return
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, (list, tuple)) or len(data) != 2:
                return
            ta, tb = pair_preview(self.project_path, int(data[0]),
                                  int(data[1]))
            self.cf_pair_a.setPlainText(ta)
            self.cf_pair_b.setPlainText(tb)
            self._pair_ids = (int(data[0]), int(data[1]))
        except Exception:
            pass

    def _open_pair_case(self, side: int):
        """Переход к кейсу 1/2 пары из превью."""
        try:
            ids = getattr(self, "_pair_ids", None)
            if not ids or side not in (0, 1):
                return
            self.result_case_id = int(ids[side])
        except Exception:
            return
        self.accept()

    # ---- QC-выборка ----
    def _sample_tab(self):
        w = QWidget()
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Случайные размеченные кейсы на перепроверку. "
                                "Seed — повторимость выборки."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Область:"))
        self.qc_scope = FComboBox()
        self.qc_scope.addItem("Весь проект", None)
        try:
            from report_service import get_files_list
            for f in get_files_list(self.project_path):
                self.qc_scope.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        row.addWidget(self.qc_scope)
        row.addWidget(QLabel("Штук:"))
        self.qc_n = FSpinBox()
        self.qc_n.setRange(1, 200)
        self.qc_n.setValue(20)
        self.qc_n.setMaximumWidth(110)
        row.addWidget(self.qc_n)
        row.addWidget(QLabel("Seed:"))
        self.qc_seed = QLineEdit()
        self.qc_seed.setPlaceholderText("пусто — случайно")
        self.qc_seed.setMaximumWidth(130)
        row.addWidget(self.qc_seed)
        btn = FPushButton("🎲 Выбрать")
        btn.clicked.connect(self._pick_sample)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        self.qc_info = QLabel("")
        self.qc_info.setWordWrap(True)
        layout.addWidget(self.qc_info)
        self.qc_list = QListWidget()
        self.qc_list.itemDoubleClicked.connect(self._open_selected)
        layout.addWidget(self.qc_list, 2)
        try:
            clear_in_fluent(self.qc_list)
        except Exception:
            pass
        w.setLayout(layout)
        return w

    def _pick_sample(self):
        raw = (self.qc_seed.text() or "").strip()
        try:
            seed = int(raw) if raw else None
        except ValueError:
            notify(self, "warning", "Выборка", "Seed — целое число или пусто")
            return
        try:
            res = qc.qc_sample(self.project_path,
                               file_id=self.qc_scope.currentData(),
                               n=self.qc_n.value(), seed=seed)
        except ValueError as e:
            notify(self, "warning", "Выборка", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.qc_list.clear()
        if not res["sample"]:
            self.qc_info.setText("Нет размеченных кейсов в области.")
            return
        self.qc_info.setText(
            f"Выборка {len(res['sample'])} из {res['total_reviewed']} "
            f"(seed {res['seed']}). Двойной клик — открыть кейс.")
        for r in res["sample"]:
            label = r["source_id"] or f"case:{r['case_id']}"
            item = QListWidgetItem(f"{r['status']} | {label}")
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.qc_list.addItem(item)

    def _open_selected(self):
        lst = self.cf_list if self.tabs.currentIndex() == 0 else self.qc_list
        item = lst.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        try:
            # пары противоречий несут оба кейса — открываем первый
            if isinstance(data, (list, tuple)):
                data = data[0] if data else None
            self.result_case_id = int(data) if data else None
        except Exception:
            return
        if self.result_case_id:
            self.accept()
