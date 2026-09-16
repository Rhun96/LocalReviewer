"""Разметка ответов прогона: absolute-статус на каждый ответ (свой на run)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextBrowser, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, FPrimaryButton, notify
import regression_service as rg
from PySide6.QtWidgets import QTextEdit


class RunReviewDialog(QDialog):
    """Листалка ответов: промпт + ответ, статусы из профиля, комментарий."""

    EMOJI = {"unreviewed": "⬜", "good": "✅", "bad": "❌",
             "uncertain": "❓", "duplicate": "🔄", "skip": "⏭️"}

    def __init__(self, project_path: str, run_id: int, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.run_id = run_id
        self._rows = []
        self._idx = 0
        self.setWindowTitle("Разметка прогона")
        self.setMinimumSize(860, 600)
        self._init_ui()
        self._reload()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        mid = QHBoxLayout()
        self.keys_list = QListWidget()
        self.keys_list.setMaximumWidth(240)
        self.keys_list.currentRowChanged.connect(self._on_key)
        mid.addWidget(self.keys_list)
        right = QVBoxLayout()
        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        right.addWidget(self.prompt_label)
        self.answer_pane = QTextBrowser()
        right.addWidget(self.answer_pane, 2)
        self.status_layout = QGridLayout()
        right.addLayout(self.status_layout)
        comment_row = QHBoxLayout()
        comment_row.addWidget(QLabel("Комментарий:"))
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(60)
        comment_row.addWidget(self.comment_edit, 2)
        right.addLayout(comment_row)
        mid.addLayout(right, 3)
        layout.addLayout(mid)
        nav = QHBoxLayout()
        btn_prev = FPushButton("⬅️ Пред.")
        btn_prev.clicked.connect(self._prev)
        btn_next = FPrimaryButton("След. ➡️")
        btn_next.clicked.connect(self._next)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        nav.addWidget(btn_prev)
        nav.addWidget(btn_next)
        nav.addStretch()
        nav.addWidget(btn_close)
        layout.addLayout(nav)
        self.setLayout(layout)

    def _statuses(self) -> list:
        try:
            from review_profile_service import get_active_profile, enabled_statuses
            prof = get_active_profile(self.project_path)
            return enabled_statuses(prof.get("config", {}))
        except Exception:
            return [{"code": c, "name": c, "hotkey": "", "base": c}
                    for c in ("good", "bad", "uncertain", "duplicate", "skip")]

    def _reload(self):
        try:
            import model_run_service as m
            run = m.get_run(self.project_path, self.run_id)
            self.setWindowTitle(f"Разметка: {run['name']}")
            self._rows = rg.list_output_reviews(self.project_path, self.run_id)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            self._rows = []
        specs = self._statuses()
        while self.status_layout.count():
            item = self.status_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        for i, spec in enumerate(specs):
            btn = FPushButton(spec.get("name", spec["code"]))
            btn.setMinimumHeight(32)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            btn.clicked.connect(lambda _c, s=spec["code"]: self._set_status(s))
            self.status_layout.addWidget(btn, i // 3, i % 3)
        self.keys_list.clear()
        for row in self._rows:
            st = row.get("review_status") or "unreviewed"
            mark = "✅" if st != "unreviewed" else "·"
            label = row.get("source_id") or row["stable_key"]
            if len(label) > 28:
                label = label[:28] + "…"
            self.keys_list.addItem(QListWidgetItem(f"{mark} {label}"))
        self._update_title()
        if self._rows:
            self.keys_list.setCurrentRow(min(self._idx, len(self._rows) - 1))
            self._show()

    def _update_title(self):
        total = len(self._rows)
        done = sum(1 for r in self._rows if (r.get("review_status") or "unreviewed")
                   != "unreviewed")
        self.title.setText(f"Размечено: {done}/{total}")

    def _current(self):
        if 0 <= self._idx < len(self._rows):
            return self._rows[self._idx]
        return None

    def _on_key(self):
        self._idx = self.keys_list.currentRow()
        self._show()

    def _show(self):
        row = self._current()
        if not row:
            return
        prompt = row.get("primary_text") or ""
        self.prompt_label.setText(
            f"📌 {prompt[:400]}{'…' if len(prompt) > 400 else ''}"
            f"\n🆔 {row.get('source_id') or row['stable_key']}")
        self.answer_pane.setPlainText(row.get("answer_text") or "(пусто)")
        self.comment_edit.setPlainText(row.get("review_comment") or "")

    def _set_status(self, status: str):
        row = self._current()
        if not row:
            return
        comment = self.comment_edit.toPlainText().strip() or None
        try:
            rg.set_output_review(self.project_path, self.run_id,
                                 row["stable_key"], status, comment)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        row["review_status"] = status
        row["review_comment"] = comment
        item = self.keys_list.item(self._idx)
        if item:
            item.setText("✅ " + item.text()[2:])
        self._update_title()
        self._next()

    def _prev(self):
        if self._idx > 0:
            self.keys_list.setCurrentRow(self._idx - 1)

    def _next(self):
        if self._idx < len(self._rows) - 1:
            self.keys_list.setCurrentRow(self._idx + 1)
