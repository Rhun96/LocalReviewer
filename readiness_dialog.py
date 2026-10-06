"""Проверка готовности набора (W1): агрегатор + вердикт + drill.

Тяжёлое считается в фоне с прогрессом и отменой (как дубли).
Drill ставит фильтры ревью и закрывает диалог.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FPushButton, FSpinBox,
                       clear_in_fluent, notify)
import dataset_readiness_service as readiness


_LEVEL_MARK = {"critical": "🛑", "warning": "⚠️", "info": "ℹ️"}


class ReadinessDialog(QDialog):
    def __init__(self, project_path: str, file_id: int | None = None,
                 parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.file_id = file_id
        self._rows: list = []
        self.setWindowTitle("Проверка готовности")
        self.setMinimumSize(640, 520)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        hint = QLabel("Готовность к заморозке/релизу: собирает существующие "
                      "проверки, ничего нового не считает. Двойной клик — "
                      "кейсы проблемы в ревью.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        row = QHBoxLayout()
        row.addWidget(QLabel("Где:"))
        self.scope_combo = FComboBox()
        self.scope_combo.addItem("Весь проект", None)
        try:
            from report_service import get_files_list
            for f in get_files_list(self.project_path):
                self.scope_combo.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        if self.file_id is not None:
            for i in range(self.scope_combo.count()):
                if self.scope_combo.itemData(i) == self.file_id:
                    self.scope_combo.setCurrentIndex(i)
                    break
        row.addWidget(self.scope_combo, 2)
        row.addWidget(QLabel("Дубли от:"))
        self.dup_spin = FSpinBox()
        self.dup_spin.setRange(50, 100)
        self.dup_spin.setValue(90)
        self.dup_spin.setSuffix(" %")
        self.dup_spin.setMaximumWidth(110)
        row.addWidget(self.dup_spin)
        btn = FPushButton("✅ Проверить")
        btn.clicked.connect(self._search)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        self.verdict = QLabel("")
        self.verdict.setWordWrap(True)
        layout.addWidget(self.verdict)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._on_open)
        layout.addWidget(self.results, 2)
        try:
            clear_in_fluent(self.results)
        except Exception:
            pass
        btns = QHBoxLayout()
        btn_open = FPushButton("➡️ Кейсы проблемы")
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
        progress = QProgressDialog("Проверка готовности…", "Отмена", 0, 100,
                                   self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)
        file_id = self.scope_combo.currentData()
        thr = self.dup_spin.value() / 100

        def _work_outer():
            from workers import run_in_background as _run
            holder: dict = {}

            def _progress(done, total):
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(
                        int(done / total * 100) if total else 0)

            worker = _run(readiness.check_readiness, self.project_path,
                          file_id, thr, 0.4, _progress, cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(res):
            try:
                progress.close()
            except Exception:
                pass
            self._show(res)

        def _fail(msg):
            try:
                progress.close()
            except Exception:
                pass
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Проверка", str(msg))
            elif "Слишком много" in (msg or ""):
                notify(self, "warning", "Проверка", str(msg))
            else:
                notify(self, "error", "Ошибка", str(msg))

        QTimer.singleShot(0, _work_outer)

    def _show(self, res):
        self._rows = res.get("checks", [])
        verdict = res.get("verdict_text", "")
        total = res.get("total", 0)
        try:
            self.verdict.setText(f"{verdict} (кейсов: {total}). "
                                 "Повторный запуск — кнопкой.")
        except Exception:
            pass
        self.results.clear()
        for c in self._rows:
            mark = _LEVEL_MARK.get(c["level"], "")
            if c["count"]:
                item = QListWidgetItem(f"{mark} {c['title']}: {c['count']}")
            else:
                item = QListWidgetItem(f"{mark} {c['title']} — чисто")
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            item.setData(Qt.ItemDataRole.UserRole, c["code"])
            self.results.addItem(item)

    def _on_open(self):
        item = self.results.currentItem()
        if item is None:
            return
        code = item.data(Qt.ItemDataRole.UserRole)
        hit = next((c for c in self._rows if c["code"] == code), None)
        if not hit or not hit.get("count"):
            return
        flt = dict(hit.get("filters") or {})
        if not flt:
            return
        try:
            rev = self.parent()
            if rev is not None and hasattr(rev, "filters"):
                rev.filters = flt
                rev.current_page = 0
                try:
                    rev.load_case_ids()
                except Exception:
                    pass
                try:
                    rev.load_table_data()
                except Exception:
                    pass
                try:
                    rev.update_filter_indicator()
                    rev.update_queue_indicator()
                except Exception:
                    pass
                self.accept()
                return
        except Exception:
            pass
        notify(self, "warning", "Проверка",
               "Некуда приземлить: открой ревью и повтори.")
