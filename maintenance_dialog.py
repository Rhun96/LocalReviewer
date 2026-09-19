"""Целостность БД: отчёт о сиротах + чистка (с подтверждением)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, confirm, notify
import maintenance_service as maint


class IntegrityDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Целостность базы")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout()
        hint = QLabel("Сироты — кейсы удалённых файлов: невидимы в ревью, "
                      "но врут в сырых счётчиках. Снимки версий не трогаем.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.info = QLabel("")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        self.details = QListWidget()
        layout.addWidget(self.details, 2)
        try:
            from ui_compat import clear_in_fluent
            clear_in_fluent(self.details)
        except Exception:
            pass
        btns = QHBoxLayout()
        self.btn_purge = FPushButton("🧹 Очистить")
        self.btn_purge.clicked.connect(self._purge)
        btns.addWidget(self.btn_purge)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._refresh()

    def _refresh(self):
        try:
            rep = maint.integrity_report(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        n = rep["orphan_cases"]
        if not n:
            self.info.setText(
                f"Файлов: {rep['files']}, кейсов: {rep['cases']}. "
                "Сирот нет — чистить нечего.")
        else:
            self.info.setText(
                f"Файлов: {rep['files']}, кейсов: {rep['cases']}, "
                f"сирот: {n}.")
        self.details.clear()
        for t, c in (rep.get("children") or {}).items():
            item = QListWidgetItem(f"{t}: {c}")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.details.addItem(item)
        self.btn_purge.setEnabled(bool(n))

    def _purge(self):
        try:
            rep = maint.integrity_report(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        n = rep["orphan_cases"]
        if not n:
            return
        if not confirm(self, "Очистить сирот",
                       f"Удалить {n} кейсов удалённых файлов и их хвосты?\n"
                       "Снимки версий не пострадают.\n"
                       "Действие необратимо (сделай бэкап!)",
                       ok_text="Очистить", cancel_text="Отмена"):
            return
        try:
            done = maint.purge_orphans(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Готово",
               f"Удалено кейсов-сирот: {done.get('orphan_cases', 0)}")
        self._refresh()
