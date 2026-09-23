"""Целостность БД (V2.2 §9–§10): полный отчёт + безопасный ремонт сирот."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, confirm, notify
import integrity_check_service as check


class IntegrityDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Целостность базы")
        self.setMinimumSize(520, 420)
        layout = QVBoxLayout()
        hint = QLabel("Проверка связей SQLite: сироты, висячие линки, версии, "
                      "баги, подсветки. Чиним только безопасное (сироты и "
                      "висячие линки) — разметка, баги и снимки не трогаем. "
                      "Перед ремонтом — автоматический бэкап.")
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
            rep = check.check_project(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        issues = rep.get("issues", [])
        self.details.clear()
        if rep.get("ok"):
            self.info.setText("✅ Проект исправен.")
            # Здоровый проект — показываем ЧТО проверено (как в референсе),
            # а не пустой список: спокойствие должно быть видно.
            for scope in ("database", "cases", "annotations", "tags",
                          "datasets", "runs", "regression", "bugs",
                          "highlights"):
                item = QListWidgetItem(f"✅ {scope} — чисто")
                item.setData(Qt.ItemDataRole.UserRole, None)
                self.details.addItem(item)
        else:
            self.info.setText(f"Найдено проблем: {len(issues)}.")
            for it in issues:
                mark = "🛠" if it.get("fixable") else "👁"
                item = QListWidgetItem(
                    f"{mark} [{it.get('scope')}] {it.get('detail')}")
                item.setData(Qt.ItemDataRole.UserRole, None)
                self.details.addItem(item)
        # Кнопка чистки активна только если есть чинимое.
        self.btn_purge.setEnabled(any(i.get("fixable") for i in issues))
        self.btn_purge.setText("🛠 Исправить безопасное")

    def _purge(self):
        try:
            rep = check.check_project(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        fixable = [i for i in rep.get("issues", []) if i.get("fixable")]
        if not fixable:
            return
        if not confirm(self, "Безопасный ремонт",
                       "Исправить только безопасное:\n• "
                       + "\n• ".join(i.get("detail", "") for i in fixable[:10])
                       + "\n\nРазметка, баги, снимки версий не пострадают.\n"
                         "Сначала сделаем бэкап.",
                       ok_text="Исправить", cancel_text="Отмена"):
            return
        try:
            import backup_service as _bak
            _bak.create_backup(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка",
                   f"Бэкап не создан — ремонт отменён:\n{e}")
            return
        try:
            done = check.repair_safe(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Готово", f"Исправлено: {done}")
        self._refresh()
