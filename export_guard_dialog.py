"""Диалог-подтверждение экспорта (ТЗ V2.2 §4–§6): компактно, без блокировок.

Показывает:
- «В экспорт попадут N кейсов и M комментариев»;
- найденные Privacy Scan шаблоны («возможные», без утверждений);
- три исхода: as_is / anonymized / cancel (None).

Фокус по умолчанию — «как есть» (основной сценарий тренера в один Enter).
Обезличивание применяется вызывающим кодом только к копии в файле.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
)
from ui_compat import FPushButton, FPrimaryButton, clear_in_fluent


class ExportGuardDialog(QDialog):
    def __init__(self, summary: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Экспорт — подтверждение")
        self.setMinimumWidth(440)
        self.result_mode = None
        layout = QVBoxLayout()
        layout.setSpacing(10)

        cases = summary.get("cases", 0)
        comments = summary.get("comments", 0)
        head = QLabel(f"В экспорт попадут {cases} кейсов и {comments} комментариев.")
        head.setWordWrap(True)
        layout.addWidget(head)

        import privacy_scan_service as _scan
        lines = _scan.summary_lines(summary)
        if lines:
            warn = QLabel("Перед экспортом обнаружено:\n• " + "\n• ".join(lines)
                          + "\n\nЭто шаблоны («возможные»), не точные секреты.")
            warn.setWordWrap(True)
            warn.setObjectName("warning")
            layout.addWidget(warn)
        else:
            ok = QLabel("Чувствительных шаблонов не найдено.")
            ok.setWordWrap(True)
            layout.addWidget(ok)

        hint = QLabel("«Как есть» — для проверки номеров/почт и полного контекста.\n"
                      "«Обезличенный» — пишет копию с <EMAIL_1>/<PHONE_1>/..., база не меняется.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btns = QHBoxLayout()
        self.btn_as_is = FPrimaryButton("Экспорт как есть")
        self.btn_as_is.clicked.connect(self._as_is)
        self.btn_anon = FPushButton("Обезличенный")
        self.btn_anon.clicked.connect(self._anon)
        btn_cancel = FPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_as_is)
        btns.addWidget(self.btn_anon)
        btns.addWidget(btn_cancel)
        layout.addLayout(btns)
        self.setLayout(layout)
        try:
            clear_in_fluent(self)
        except Exception:
            pass
        self.btn_as_is.setFocus()
        self.btn_as_is.setDefault(True)

    def _as_is(self):
        self.result_mode = "as_is"
        self.accept()

    def _anon(self):
        self.result_mode = "anonymized"
        self.accept()


def confirm_export(parent, summary: dict) -> str | None:
    """Возвращает 'as_is' / 'anonymized' / None (отмена)."""
    dlg = ExportGuardDialog(summary, parent)
    if dlg.exec() != QDialog.DialogCode.Accepted:
        return None
    return dlg.result_mode
