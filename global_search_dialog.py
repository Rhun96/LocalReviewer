"""Компактный Ctrl+P диалог (ТЗ V2.2 §13): без отдельного экрана.

Enter: одно совпадение — сразу открыть; несколько — выбрать из списка.
Живой поиск по мере ввода не делаем (лишний шум в БД) — только по Enter.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QButtonGroup,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FLineEdit, FPushButton, FPrimaryButton,
                        clear_in_fluent)
import global_search_service as gs


class GlobalSearchDialog(QDialog):
    def __init__(self, project_path: str, parent=None, file_id=None):
        super().__init__(parent)
        self.project_path = project_path
        self.file_id = file_id
        self.result_case_id = None
        self.setWindowTitle("Найти кейс (Ctrl+P)")
        self.setMinimumSize(520, 380)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        hint = QLabel("ID кейса, source ID (точно/частично) или текст вопроса. Enter — найти.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.hint = hint
        self.edit = FLineEdit()
        self.edit.setPlaceholderText("например: 1234, Номер обращения, часть вопроса…")
        self.edit.returnPressed.connect(self._search)
        layout.addWidget(self.edit)
        mode_row = QHBoxLayout()
        self.btn_mode_exact = FPushButton("Точный")
        self.btn_mode_exact.setCheckable(True)
        self.btn_mode_exact.setChecked(True)
        self.btn_mode_exact.setToolTip("ID кейса, source ID, подстрока текста")
        self.btn_mode_semantic = FPushButton("По смыслу")
        self.btn_mode_semantic.setCheckable(True)
        self.btn_mode_semantic.setToolTip("Перефразировки тоже находятся "
                                          "(эмбеддинги, иначе TF-IDF)")
        self._mode_group = QButtonGroup(self)
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_mode_exact)
        self._mode_group.addButton(self.btn_mode_semantic)
        self.btn_mode_exact.toggled.connect(self._on_mode_changed)
        mode_row.addWidget(self.btn_mode_exact)
        mode_row.addWidget(self.btn_mode_semantic)
        mode_row.addWidget(QLabel("Где:"))
        self.scope_combo = FComboBox()
        self.scope_combo.addItem("В проекте", "project")
        self.scope_combo.addItem("В текущем файле", "file")
        self.scope_combo.setEnabled(False)
        mode_row.addWidget(self.scope_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        self.engine_info = QLabel("")
        self.engine_info.setWordWrap(True)
        layout.addWidget(self.engine_info)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _i: self._pick())
        layout.addWidget(self.list, 2)
        btns = QHBoxLayout()
        go = FPrimaryButton("Найти")
        go.clicked.connect(self._search)
        open_btn = FPushButton("Открыть")
        open_btn.clicked.connect(self._pick)
        close = FPushButton("Закрыть")
        close.clicked.connect(self.reject)
        btns.addWidget(go)
        btns.addWidget(open_btn)
        btns.addStretch()
        btns.addWidget(close)
        layout.addLayout(btns)
        self.setLayout(layout)
        try:
            clear_in_fluent(self.list)
            clear_in_fluent(self)
        except Exception:
            pass
        self.edit.setFocus()

    def _mode(self) -> str:
        return ("semantic" if self.btn_mode_semantic.isChecked()
                else "exact")

    def _on_mode_changed(self, *_a):
        semantic = self._mode() == "semantic"
        self.scope_combo.setEnabled(bool(semantic and self.file_id is not None))
        hint = ("Смысл: перефразировки тоже находятся "
                "(эмбеддинги, иначе TF-IDF)."
                if semantic else
                "ID кейса, source ID (точно/частично) или текст вопроса. Enter — найти.")
        try:
            self.hint.setText(hint)
        except Exception:
            pass

    def _search(self):
        if self._mode() == "semantic":
            self._search_semantic()
            return
        q = self.edit.text()
        try:
            rows = gs.search_cases(self.project_path, q)
        except Exception:
            rows = []
        self.list.clear()
        if len(rows) == 1:
            # Одно совпадение — сразу открываем, без лишнего клика.
            self.result_case_id = rows[0]["case_id"]
            self.accept()
            return
        for r in rows:
            label = f"#{r['case_id']} [{r['source_id'] or '—'}] {r['snippet'][:100]}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.list.addItem(item)
        if not rows:
            item = QListWidgetItem("Ничего не найдено")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(item)

    def _search_semantic(self):
        q = self.edit.text()
        scope = self.scope_combo.currentData() or "project"
        if scope == "file" and self.file_id is None:
            scope = "project"
        try:
            res = gs.search_semantic(self.project_path, q, scope=scope,
                                     file_id=self.file_id)
        except ValueError as e:
            from ui_compat import notify as _notify
            _notify(self, "warning", "Поиск", str(e))
            return
        except Exception as e:
            from ui_compat import notify as _notify
            _notify(self, "error", "Ошибка", str(e))
            return
        engine = (f" [движок: {res['backend']}"
                  f"{(' — ' + res['note']) if res['note'] else ''}]")
        self.engine_info.setText("Поиск по смыслу." + engine)
        self.list.clear()
        rows = res.get("results", [])
        if len(rows) == 1:
            self.result_case_id = rows[0]["case_id"]
            self.accept()
            return
        for r in rows:
            pct = int(round(float(r.get("score", 0.0)) * 100))
            mark = "✅" if r.get("reviewed") else "⬜"
            label = (f"{pct}% {mark} #{r['case_id']} "
                     f"[{r['source_id'] or '—'}] {r['snippet'][:100]}")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.list.addItem(item)
        if not rows:
            item = QListWidgetItem("Ничего похожего — попробуй переформулировать")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self.list.addItem(item)
        else:
            missing = res.get("missing") or []
            if res.get("backend") == "embedding" and missing:
                try:
                    from ui_compat import get_embed_auto as _auto
                    if _auto():
                        from workers import run_in_background as _run
                        import embedding_service as _emb
                        _run(_emb.ensure_indexed, self.project_path,
                             list(missing))
                except Exception:
                    pass

    def _pick(self):
        item = self.list.currentItem()
        if item is None:
            return
        cid = item.data(Qt.ItemDataRole.UserRole)
        if cid:
            self.result_case_id = int(cid)
            self.accept()
