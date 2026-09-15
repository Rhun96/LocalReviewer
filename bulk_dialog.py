"""Диалог массовой операции: подтверждает count + операцию, запускает в фоне."""
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout
from ui_compat import FComboBox, FPrimaryButton, FPushButton, FTextEdit


class BulkDialog(QDialog):
    """Возвращает (op_type, params) через .result_op. Не выполняет сам — выполняет вызывающий."""

    def __init__(self, count: int, parent=None, project_path: str | None = None):
        super().__init__(parent)
        self.setWindowTitle("Массовая операция")
        self.setMinimumWidth(420)
        self.count = count
        self.project_path = project_path or getattr(parent, "project_path", None)
        self.result_op = None
        self._tags: list = []
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        info = QLabel(
            f"Вы собираетесь изменить <b>{self.count}</b> кейсов.<br>"
            "Операция будет записана в историю, её можно отменить."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        layout.addWidget(QLabel("Операция:"))
        self.op_combo = FComboBox()
        self.op_combo.addItem("Статус → Хорошо", ("status", "good"))
        self.op_combo.addItem("Статус → Плохо", ("status", "bad"))
        self.op_combo.addItem("Статус → Сомневаюсь", ("status", "uncertain"))
        self.op_combo.addItem("Статус → Дубль", ("status", "duplicate"))
        self.op_combo.addItem("Статус → Пропустить", ("status", "skip"))
        self.op_combo.addItem("Статус → Сбросить (непроверено)", ("status", "unreviewed"))
        self.op_combo.addItem("Комментарий → установить", ("comment_replace", ""))
        self.op_combo.addItem("Комментарий → добавить", ("comment_append", ""))
        self.op_combo.addItem("Комментарий → очистить", ("comment_clear", ""))
        self.op_combo.addItem("Тег → добавить", ("add_tag", ""))
        self.op_combo.currentIndexChanged.connect(self._on_op_changed)
        layout.addWidget(self.op_combo)

        self.tag_combo = FComboBox()
        self.tag_combo.setMinimumHeight(30)
        self._load_tags()
        layout.addWidget(self.tag_combo)

        self.text_edit = FTextEdit()
        self.text_edit.setPlaceholderText("Текст комментария (для операций с комментарием)")
        self.text_edit.setMaximumHeight(80)
        layout.addWidget(self.text_edit)

        btns = QHBoxLayout()
        ok = FPrimaryButton("▶ Применить")
        ok.clicked.connect(self._on_ok)
        cancel = FPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)
        self._on_op_changed()

    def _on_op_changed(self):
        op = self.op_combo.currentData()[0]
        self.text_edit.setEnabled(op.startswith("comment"))
        try:
            self.tag_combo.setEnabled(op == "add_tag")
        except Exception:
            pass

    def _load_tags(self):
        try:
            if not self.project_path:
                return
            from database import db
            with db(self.project_path) as conn:
                rows = conn.cursor().execute(
                    "SELECT tag_id, tag_name FROM tags ORDER BY tag_name").fetchall()
            for r in rows:
                self.tag_combo.addItem(r["tag_name"], r["tag_id"])
                self._tags.append(dict(r))
        except Exception:
            pass

    def _on_ok(self):
        op, val = self.op_combo.currentData()
        if op.startswith("comment") and op != "comment_clear":
            if not self.text_edit.toPlainText().strip():
                return
            self.result_op = (op, self.text_edit.toPlainText().strip())
        elif op == "add_tag":
            tag_id = self.tag_combo.currentData()
            if tag_id is None:
                return
            self.result_op = (op, tag_id)
        else:
            self.result_op = (op, val)
        self.accept()
