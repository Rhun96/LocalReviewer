"""Похожие баги (формулировки, TF-IDF): группы + слияние в один."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, FPrimaryButton, clear_in_fluent, confirm, notify
import bug_report_service as bugs


class BugSimilarDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Похожие баги")
        self.setMinimumSize(640, 420)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        hint = QLabel("Группы открытых багов с похожими заголовками "
                      "(TF-IDF, без LLM). Слияние переносит кейсы в цель, "
                      "остальные становятся дубликатами.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.groups_list = QListWidget()
        self.groups_list.itemDoubleClicked.connect(
            lambda _i: self._merge_current())
        layout.addWidget(self.groups_list, 2)
        try:
            clear_in_fluent(self.groups_list)
        except Exception:
            pass
        btns = QHBoxLayout()
        go = FPrimaryButton("Объединить группу")
        go.clicked.connect(self._merge_current)
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addWidget(go)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._reload()

    def _reload(self):
        from report_service import bug_semantic_groups
        try:
            self._groups = bug_semantic_groups(self.project_path) or []
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            self._groups = []
        self.groups_list.clear()
        if not self._groups:
            item = QListWidgetItem("Похожих открытых багов нет")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.groups_list.addItem(item)
            return
        for g in self._groups:
            titles = "; ".join(f"#{b} {t[:60]}" for b, t in zip(
                g["bug_ids"], g["titles"], strict=True))
            item = QListWidgetItem(f"{g['size']} похожих: {titles[:220]}")
            item.setData(Qt.ItemDataRole.UserRole, list(g["bug_ids"]))
            self.groups_list.addItem(item)

    def _merge_current(self):
        item = self.groups_list.currentItem()
        if item is None:
            return
        ids = item.data(Qt.ItemDataRole.UserRole)
        if not ids or len(ids) < 2:
            return
        ids = [int(c) for c in ids]
        target = min(ids)
        srcs = [c for c in ids if c != target]
        if not confirm(self, "Подтверждение",
                       f"Слить {len(srcs)} в баг #{target}? Кейсы переедут, "
                       "источники станут дубликатами."):
            return
        try:
            res = bugs.merge_bugs(self.project_path, target, srcs)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        notify(self, "success", "Баги",
               f"В #{res['target']} влито {len(res['merged'])}.")
        self._reload()
