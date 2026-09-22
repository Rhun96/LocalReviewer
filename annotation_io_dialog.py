"""Обмен разметкой: экспорт (scope) + импорт (Preview → Merge/Update)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog,
)
from ui_compat import (FComboBox, FPrimaryButton, FPushButton,
                       clear_in_fluent, notify)
import annotation_io_service as aio
import logging

logger = logging.getLogger(__name__)


class ExportAnnotationsDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Экспорт разметки")
        self.setMinimumWidth(380)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Только разметка: id, status, category, "
                                "subcategory, severity, comment (JSONL)."))
        layout.addWidget(QLabel("Охват:"))
        self.file_combo = FComboBox()
        self.file_combo.addItem("Весь проект", None)
        try:
            from report_service import get_files_list
            for f in get_files_list(self.project_path):
                self.file_combo.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        layout.addWidget(self.file_combo)
        btns = QHBoxLayout()
        ok = FPrimaryButton("Экспортировать")
        ok.clicked.connect(self._export)
        cancel = FPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _export(self):
        from datetime import datetime
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить разметку",
            f"annotations_{datetime.now().strftime('%Y%m%d_%H%M%S')}.jsonl",
            "JSONL (*.jsonl)")
        if not path:
            return
        try:
            n = aio.export_annotations(self.project_path, path,
                                       file_id=self.file_combo.currentData())
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Экспорт", f"Строк: {n}\n{path}")
        self.accept()


class ImportAnnotationsDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Импорт разметки")
        self.setMinimumSize(620, 520)
        self._rows = []
        self._preview_data = None
        self.result_case_id = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        file_row = QHBoxLayout()
        self.file_label = QLabel("Файл не выбран")
        btn = FPushButton("📂 Выбрать файл")
        btn.clicked.connect(self._select)
        file_row.addWidget(self.file_label)
        file_row.addWidget(btn)
        layout.addLayout(file_row)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Режим:"))
        self.mode_combo = FComboBox()
        self.mode_combo.addItem("Preview (только отчёт)", "preview")
        self.mode_combo.addItem("Merge (только пустые поля)", "merge")
        self.mode_combo.addItem("Update (перезапись различий)", "update")
        mode_row.addWidget(self.mode_combo)
        btn_preview = FPushButton("👁 Preview")
        btn_preview.clicked.connect(self._preview)
        mode_row.addWidget(btn_preview)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        self.summary = QLabel("Выбери файл и нажми Preview: увидишь новые, "
                              "обновляемые, конфликты — до записи.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            from ui_compat import polish_table as _polish
            clear_in_fluent(self.table)
            _polish(self.table, stretch_last=True)
        except Exception:
            pass
        btns = QHBoxLayout()
        ok = FPrimaryButton("▶ Применить")
        ok.clicked.connect(self._apply)
        self.btn_goto = FPushButton("➡️ В ревью")
        self.btn_goto.setToolTip("Открыть первый затронутый кейс в ревью")
        self.btn_goto.setEnabled(False)
        self.btn_goto.clicked.connect(self._goto_review)
        cancel = FPushButton("Закрыть")
        cancel.clicked.connect(self.accept)
        btns.addWidget(ok)
        btns.addWidget(self.btn_goto)
        btns.addStretch()
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _select(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл разметки", "",
            "Разметка (JSONL *.jsonl *.xlsx *.csv *.ods);;Все файлы (*.*)")
        if not path:
            return
        try:
            from pathlib import Path as _Path
            if _Path(path).suffix.lower() in (".xlsx", ".csv", ".ods"):
                rows, errors = aio.read_annotation_table(path)
            else:
                rows, errors = aio.read_annotation_file(path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self._rows = rows
        self._preview_data = None
        self.file_label.setText(f"{path} ({len(rows)} строк, битых: {len(errors)})")
        if errors:
            notify(self, "warning", "Файл",
                   f"Битых строк: {len(errors)} (пропущены).")
        # Выбрал файл — превью сразу, без лишнего клика.
        if rows:
            self._preview()

    def _preview(self):
        if not self._rows:
            notify(self, "warning", "Внимание", "Сначала выбери файл")
            return
        try:
            from annotation_io_service import preview_import
            self._preview_data = preview_import(self.project_path, self._rows)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        p = self._preview_data
        self.summary.setText(
            f"Всего: {p['total']} | новых: {len(p['new'])} | "
            f"обновляемых: {len(p['updating'])} | без изменений: "
            f"{len(p['unchanged'])} | не найдено: {len(p['not_found'])} | "
            f"конфликтов: {len(p['conflicts'])} | ошибок: {len(p['errors'])}")
        shown = []
        for bucket, tag in (("conflicts", "⚠ конфликт"), ("not_found", "❓ нет"),
                            ("errors", "⛔ ошибка"), ("updating", "✏ обновление"),
                            ("new", "＋ новый")):
            for e in p[bucket][:60]:
                shown.append((tag, str(e.get("id", "")),
                              str(e.get("conflict_fields") or e.get("error", ""))))
        self.table.clear()
        self.table.setColumnCount(3)
        self.table.setRowCount(len(shown))
        self.table.setHorizontalHeaderLabels(["Что", "ID", "Детали"])
        for i, (tag, ident, detail) in enumerate(shown):
            self.table.setItem(i, 0, QTableWidgetItem(tag))
            self.table.setItem(i, 1, QTableWidgetItem(ident))
            self.table.setItem(i, 2, QTableWidgetItem(detail[:120]))
        self.table.resizeColumnsToContents()
        # Прыжок доступен сразу после превью: превью уже знает кейсы,
        # ждать «Применить» не нужно.
        try:
            got = ((p.get("new") or []) + (p.get("updating") or [])
                   + (p.get("conflicts") or []))
            self.result_case_id = got[0]["case_id"] if got else None
            self.btn_goto.setEnabled(bool(self.result_case_id))
        except Exception:
            pass

    def _apply(self):
        if not self._preview_data:
            notify(self, "warning", "Внимание", "Сначала нажми Preview")
            return
        mode = self.mode_combo.currentData() or "preview"
        if mode == "preview":
            notify(self, "warning", "Preview",
                   "Режим Preview ничего не пишет — выбери Merge или Update.")
            return
        if self._preview_data["conflicts"] and mode == "merge":
            notify(self, "success", "Merge",
                   "Конфликты пропускаются (не перезаписываются молча).")
        try:
            res = aio.apply_import(self.project_path, self._preview_data, mode)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        except Exception as e:
            logger.exception("annotation apply failed")
            notify(self, "error", "Ошибка", f"Не удалось применить:\n{e}")
            return
        # Первый затронутый кейс — для прыжка в ревью (посмотреть, а не верить).
        try:
            got = ((self._preview_data.get("new") or [])
                   + (self._preview_data.get("updating") or [])
                   + (self._preview_data.get("conflicts") or []))
            self.result_case_id = got[0]["case_id"] if got else None
        except Exception:
            self.result_case_id = None
        goto = ""
        if self.result_case_id:
            goto = " Кнопка «➡️ В ревью» покажет первый затронутый кейс."
        notify(self, "success", "Импорт",
               f"Применено: {res['applied']}, пропущено: {res['skipped']}, "
               f"не найдено: {res['not_found']}, ошибок: {res['errors']}.{goto}")
        self._preview()
        try:
            self.btn_goto.setEnabled(bool(self.result_case_id))
        except Exception:
            pass

    def _goto_review(self):
        """Закрыть диалог и открыть первый затронутый кейс в ревью."""
        if not self.result_case_id:
            return
        self.accept()
