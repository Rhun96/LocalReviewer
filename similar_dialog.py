"""Похожие кейсы (ТЗ §64-70): боковая панель контекста, без автопростановки."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import (FCheckBox, FComboBox, FPushButton, FSpinBox,
                       clear_in_fluent, notify)
import similarity_service as sim


class SimilarDialog(QDialog):
    """result_case_id — выбранный похожий кейс (переход по двойному клику)."""

    def __init__(self, project_path: str, case_id: int, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.case_id = case_id
        self.result_case_id = None
        self.setWindowTitle("Похожие кейсы")
        self.setMinimumSize(620, 520)
        self._init_ui()
        self._search()

    def _init_ui(self):
        layout = QVBoxLayout()
        hint = QLabel("Похожие размеченные кейсы — только контекст для решения, "
                      "статус по ним не ставится.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("Где искать:"))
        self.scope_combo = FComboBox()
        self.scope_combo.addItem("В текущем файле", "file")
        self.scope_combo.addItem("В проекте", "project")
        self.scope_combo.addItem("В Golden", "golden")
        self.scope_combo.addItem("В архивных", "archive")
        row.addWidget(self.scope_combo)
        row.addWidget(QLabel("Мин. схожесть:"))
        self.min_spin = FSpinBox()
        self.min_spin.setRange(50, 100)
        self.min_spin.setValue(75)
        self.min_spin.setSuffix(" %")
        self.min_spin.setMaximumWidth(120)
        row.addWidget(self.min_spin)
        layout.addLayout(row)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("По полям:"))
        self.field_boxes = {}
        for code, name in (("primary_text", "Запрос"), ("response_text", "Ответ"),
                           ("group_name", "Группа"), ("product", "Продукт")):
            cb = FCheckBox(name)
            cb.setChecked(code == "primary_text")
            self.field_boxes[code] = cb
            frow.addWidget(cb)
        frow.addStretch()
        layout.addLayout(frow)
        btn_row = QHBoxLayout()
        btn_find = FPushButton("🔍 Найти")
        btn_find.clicked.connect(self._search)
        btn_row.addWidget(btn_find)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.info = QLabel("")
        layout.addWidget(self.info)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.results, 2)
        try:
            clear_in_fluent(self.results)
        except Exception:
            pass
        btns = QHBoxLayout()
        btn_open = FPushButton("➡️ Открыть выбранный")
        btn_open.clicked.connect(self._on_open)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_open)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _params(self):
        fields = tuple(c for c, cb in self.field_boxes.items() if cb.isChecked())
        return {"min_score": self.min_spin.value() / 100,
                "scope": self.scope_combo.currentData() or "file",
                "fields": fields or ("primary_text",)}

    def _search(self):
        try:
            res = sim.find_similar(self.project_path, self.case_id, **self._params())
        except ValueError as e:
            notify(self, "warning", "Поиск", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.results.clear()
        if not res["results"]:
            self.info.setText("Ничего похожего не нашлось — попробуй снизить порог "
                              "или расширить область.")
            return
        labeled = sum(1 for r in res["results"] if r["reviewed"])
        self.info.setText(f"Найдено: {res['total']}, из них размеченных: {labeled}. "
                          "Двойной клик — открыть кейс.")
        for r in res["results"]:
            pct = int(round(r["score"] * 100))
            mark = "✅" if r["reviewed"] else "⬜"
            label = r["source_id"] or f"case:{r['case_id']}"
            item = QListWidgetItem(f"{pct}% {mark} {r['status']} | {label} | "
                                   f"{r['snippet'][:100]}")
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.results.addItem(item)

    def _on_open(self):
        item = self.results.currentItem()
        if not item:
            return
        self.result_case_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()


class DuplicatesDialog(QDialog):
    """Потенциальные дубли в файле/проекте (попарный TF-IDF, порог)."""

    def __init__(self, project_path: str, file_id: int | None = None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.file_id = file_id
        self.result_case_id = None
        self.setWindowTitle("Потенциальные дубли")
        self.setMinimumSize(560, 440)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        scope = ("текущем файле" if self.file_id else "проекте")
        layout.addWidget(QLabel(f"Попарное сравнение в {scope} "
                                "(запрос+ответ). Дубли не ставятся автоматически."))
        row = QHBoxLayout()
        row.addWidget(QLabel("Порог:"))
        self.thr_spin = FSpinBox()
        self.thr_spin.setRange(50, 100)
        self.thr_spin.setValue(90)
        self.thr_spin.setSuffix(" %")
        self.thr_spin.setMaximumWidth(120)
        row.addWidget(self.thr_spin)
        btn = FPushButton("🔍 Найти дубли")
        btn.clicked.connect(self._search)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        self.info = QLabel("")
        layout.addWidget(self.info)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.results, 2)
        try:
            clear_in_fluent(self.results)
        except Exception:
            pass
        btns = QHBoxLayout()
        btn_open = FPushButton("➡️ Открыть первый из пары")
        btn_open.clicked.connect(self._on_open)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_open)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _search(self):
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Поиск дублей…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)
        thr = self.thr_spin.value() / 100
        file_id = self.file_id

        def _work_outer():
            from workers import run_in_background as _run
            holder: dict = {}

            def _progress(done, total):
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(
                        int(done / total * 100) if total else 0)

            worker = _run(sim.find_duplicates, self.project_path, file_id, thr,
                          200, _progress, cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(res):
            try:
                progress.close()
            except Exception:
                pass
            self.results.clear()
            if not res["pairs"]:
                self.info.setText("Дублей выше порога нет.")
                return
            extra = f" (показаны первые {len(res['pairs'])})" if res["truncated"] else ""
            self.info.setText(f"Пар: {res['total']}{extra}. Двойной клик — открыть.")
            for p in res["pairs"]:
                pct = int(round(p["score"] * 100))
                item = QListWidgetItem(
                    f"{pct}%  case:{p['case_a']}  ⇄  case:{p['case_b']}")
                item.setData(Qt.ItemDataRole.UserRole, p["case_a"])
                self.results.addItem(item)

        def _fail(msg):
            try:
                progress.close()
            except Exception:
                pass
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Поиск", str(msg))
            elif "Слишком много" in (msg or ""):
                notify(self, "warning", "Поиск", str(msg))
            else:
                notify(self, "error", "Ошибка", str(msg))

        QTimer.singleShot(0, _work_outer)

    def _on_open(self):
        item = self.results.currentItem()
        if not item:
            return
        self.result_case_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
