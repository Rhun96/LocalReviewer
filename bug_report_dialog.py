"""Диалог Bug Report: полный режим и быстрый (только title)."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QFormLayout, QInputDialog, QScrollArea, QWidget,
)
from PySide6.QtCore import Qt, Signal
from ui_compat import (FComboBox, FLineEdit, FPrimaryButton, FPushButton,
                       FTextEdit, clear_in_fluent, notify)
import bug_report_service as bugs


class BugReportWidget(QWidget):
    """Тело карточки бага (панель списка и диалог делят один код).

    В отличие от диалога никуда не закрывается: saved/goto_case —
    сигналы хозяину. После создания bug_id подхватывается, чтобы
    повторный «Сохранить» правил, а не дублировал.
    """

    saved = Signal(int)
    goto_case = Signal(int)

    def __init__(self, project_path: str, prefill: dict | None = None,
                 bug_id: int | None = None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.prefill = dict(prefill or {})
        self.bug_id = bug_id
        self.result_id = None
        self.result_case_id = None
        self._linked: list = []
        self._init_ui()
        self._load()

    def _init_ui(self):
        outer = QVBoxLayout()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        host = QWidget()
        layout = QVBoxLayout()
        form = QFormLayout()
        self.title_edit = FLineEdit()
        form.addRow("Заголовок *:", self.title_edit)
        self.sev_combo = FComboBox()
        for s in bugs.SEVERITIES:
            self.sev_combo.addItem(bugs.BUG_SEVERITY_NAMES.get(s, s), s)
        self.sev_combo.setCurrentIndex(1)
        form.addRow("Критичность:", self.sev_combo)
        self.status_combo = FComboBox()
        for s in bugs.STATUSES:
            self.status_combo.addItem(bugs.BUG_STATUS_NAMES.get(s, s), s)
        form.addRow("Статус:", self.status_combo)
        self.cat_combo = FComboBox()
        self.cat_combo.addItem("— нет —", None)
        self.sub_combo = FComboBox()
        self.sub_combo.addItem("— нет —", None)
        form.addRow("Категория:", self.cat_combo)
        form.addRow("Подкатегория:", self.sub_combo)
        layout.addLayout(form)
        self.desc_edit = FTextEdit()
        self.desc_edit.setMaximumHeight(80)
        layout.addWidget(QLabel("Описание:"))
        layout.addWidget(self.desc_edit)
        self.actual_edit = FTextEdit()
        self.actual_edit.setMaximumHeight(70)
        layout.addWidget(QLabel("Фактическое поведение:"))
        layout.addWidget(self.actual_edit)
        self.expected_edit = FTextEdit()
        self.expected_edit.setMaximumHeight(70)
        layout.addWidget(QLabel("Ожидаемое поведение:"))
        layout.addWidget(self.expected_edit)
        layout.addWidget(QLabel("Контекст (из кейса, можно править):"))
        self.ctx_label = QLabel("")
        self.ctx_label.setWordWrap(True)
        self.ctx_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.ctx_label)
        model_row = QHBoxLayout()
        self.model_edits = {}
        for key, label in (("model_name", "Модель"), ("model_version", "Версия"),
                           ("prompt_version", "Промпт"), ("system_prompt_version", "Сист.")):
            self.model_edits[key] = FLineEdit()
            model_row.addWidget(QLabel(label))
            model_row.addWidget(self.model_edits[key])
        layout.addLayout(model_row)
        ext_row = QHBoxLayout()
        self.ext_tracker = FLineEdit()
        self.ext_tracker.setPlaceholderText("трекер")
        self.ext_id = FLineEdit()
        self.ext_id.setPlaceholderText("ID")
        self.ext_url = FLineEdit()
        self.ext_url.setPlaceholderText("URL")
        ext_row.addWidget(QLabel("Трекер:"))
        ext_row.addWidget(self.ext_tracker)
        ext_row.addWidget(self.ext_id)
        ext_row.addWidget(self.ext_url)
        layout.addLayout(ext_row)
        self.internal_edit = FLineEdit()
        self.internal_edit.setPlaceholderText("Внутренний комментарий (не для разработчиков)")
        layout.addWidget(self.internal_edit)
        layout.addWidget(QLabel("Связанные кейсы (двойной клик — открыть):"))
        self.cases_list = QListWidget()
        self.cases_list.setMaximumHeight(110)
        self.cases_list.itemDoubleClicked.connect(
            lambda _i: self._open_linked_case())
        layout.addWidget(self.cases_list)
        link_row = QHBoxLayout()
        btn_add = FPushButton("＋ Кейс по ID")
        btn_add.clicked.connect(self._add_case)
        btn_del = FPushButton("－ Убрать")
        btn_del.clicked.connect(self._del_case)
        btn_goto = FPushButton("➡️ Открыть кейс")
        btn_goto.setToolTip("Сохранить баг и перейти к кейсу в ревью")
        btn_goto.clicked.connect(self._open_linked_case)
        link_row.addWidget(btn_add)
        link_row.addWidget(btn_del)
        link_row.addWidget(btn_goto)
        link_row.addStretch()
        layout.addLayout(link_row)
        host.setLayout(layout)
        scroll.setWidget(host)
        try:
            clear_in_fluent(scroll)
        except Exception:
            pass
        outer.addWidget(scroll)
        btns = QHBoxLayout()
        ok = FPrimaryButton("💾 Сохранить баг")
        ok.clicked.connect(self._save)
        btn_copy = FPushButton("📋 Копировать")
        btn_copy.setToolTip("Jira / Markdown / Plain Text в буфер обмена")
        btn_copy.clicked.connect(self._copy_menu)
        btns.addWidget(ok)
        btns.addWidget(btn_copy)
        btns.addStretch()
        outer.addLayout(btns)
        self.setLayout(outer)
        self.cat_combo.currentIndexChanged.connect(self._reload_subs)

    def _load_taxonomy(self):
        try:
            from taxonomy_service import list_categories
            cats = list_categories(self.project_path)
        except Exception:
            cats = []
        self._cats = {c["category_id"]: c for c in cats}
        for c in cats:
            self.cat_combo.addItem(c["name"], c["category_id"])

    def _reload_subs(self):
        cid = self.cat_combo.currentData()
        self.sub_combo.clear()
        self.sub_combo.addItem("— нет —", None)
        cat = (self._cats or {}).get(cid, {})
        for s in cat.get("subs", []):
            self.sub_combo.addItem(s["name"], s["category_id"])

    def _select_combo(self, combo, value):
        for i in range(combo.count()):
            if combo.itemData(i) == value:
                combo.setCurrentIndex(i)
                return

    def _load(self):
        self._load_taxonomy()
        if self.bug_id is not None:
            data = bugs.get_bug(self.project_path, self.bug_id)
            if not data:
                notify(self, "error", "Ошибка", "Баг не найден")
                return
            self.title_edit.setText(data["title"] or "")
            self._select_combo(self.sev_combo, data["severity"])
            self._select_combo(self.status_combo, data["status"])
            self._select_combo(self.cat_combo, data.get("category_id"))
            self._reload_subs()
            self._select_combo(self.sub_combo, data.get("subcategory_id"))
            self.desc_edit.setPlainText(data["description"] or "")
            self.actual_edit.setPlainText(data["actual_behavior"] or "")
            self.expected_edit.setPlainText(data["expected_behavior"] or "")
            for k, ed in self.model_edits.items():
                ed.setText(data.get(k) or "")
            self.ext_tracker.setText(data.get("external_tracker") or "")
            self.ext_id.setText(data.get("external_id") or "")
            self.ext_url.setText(data.get("external_url") or "")
            self.internal_edit.setText(data.get("internal_comment") or "")
            self._linked = [c["case_id"] for c in data.get("cases", [])]
            ctx_lines = [f"ID: {c.get('source_id') or c['case_id']}"
                         for c in data.get("cases", [])]
            self.ctx_label.setText("Кейсы: " + (", ".join(ctx_lines) or "—"))
        else:
            p = self.prefill
            self.title_edit.setText(p.get("title_suggest", ""))
            if p.get("severity"):
                self._select_combo(self.sev_combo, p["severity"])
            self._select_combo(self.cat_combo, p.get("category_id"))
            self._reload_subs()
            self._select_combo(self.sub_combo, p.get("subcategory_id"))
            self.desc_edit.setPlainText(
                p.get("description") or p.get("review_comment", ""))
            self.expected_edit.setPlainText(p.get("expected_behavior", ""))
            for k, ed in self.model_edits.items():
                ed.setText(p.get(k) or "")
            if p.get("case_id"):
                self._linked = [p["case_id"]]
            q = (p.get("query") or "")[:200]
            self.ctx_label.setText(
                f"Кейс {p.get('source_id') or p.get('case_id')} "
                f"[{p.get('review_status', '')}]: {q}")
        self._refresh_cases()
        self._snapshot = self._snap()

    def _snap(self):
        return (self._collect(), list(self._linked))

    def is_dirty(self) -> bool:
        """Есть несохранённые правки (сравнение со снимком загрузки)."""
        try:
            return self._snap() != self._snapshot
        except Exception:
            return False

    def _has_title(self) -> bool:
        try:
            return bool(self.title_edit.text().strip())
        except Exception:
            return False

    def autosave(self) -> bool:
        """Тихое сохранение для панели: True — можно уходить с карточки."""
        try:
            if not self.is_dirty():
                return True
            if not self._has_title():
                notify(self, "warning", "Несохранённые правки",
                       "Введи заголовок — иначе правки потеряются")
                return False
            self._save()
            return not self.is_dirty()
        except Exception:
            return True

    def _refresh_cases(self):
        self.cases_list.clear()
        if not self._linked:
            return
        try:
            from database import db as _db
            with _db(self.project_path) as conn:
                for cid in self._linked:
                    row = conn.execute(
                        "SELECT source_id FROM cases WHERE case_id=?",
                        (cid,)).fetchone()
                    label = (row["source_id"] if row and row["source_id"]
                             else f"case:{cid}")
                    self.cases_list.addItem(QListWidgetItem(label))
        except Exception:
            for cid in self._linked:
                self.cases_list.addItem(QListWidgetItem(f"case:{cid}"))

    def _add_case(self):
        text, ok = QInputDialog.getText(self, "Кейс", "ID из маппинга или номер:")
        if not ok or not (text or "").strip():
            return
        text = text.strip()
        try:
            from database import db as _db
            with _db(self.project_path) as conn:
                row = conn.execute("SELECT case_id FROM cases WHERE source_id=? "
                                   "OR CAST(case_id AS TEXT)=?",
                                   (text, text)).fetchone()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        if not row:
            notify(self, "warning", "Внимание", f"Кейс «{text}» не найден")
            return
        if row["case_id"] in self._linked:
            notify(self, "warning", "Внимание", "Кейс уже привязан")
            return
        if self.bug_id is not None:
            try:
                bugs.add_case(self.project_path, self.bug_id, row["case_id"])
            except ValueError as e:
                notify(self, "warning", "Ошибка", str(e))
                return
        self._linked.append(row["case_id"])
        self._refresh_cases()

    def _del_case(self):
        item = self.cases_list.currentItem()
        if not item:
            return
        idx = self.cases_list.currentRow()
        cid = self._linked.pop(idx)
        if self.bug_id is not None:
            try:
                bugs.remove_case(self.project_path, self.bug_id, cid)
            except Exception:
                pass
        self._refresh_cases()

    def _collect(self) -> dict:
        return {
            "title": self.title_edit.text().strip(),
            "severity": self.sev_combo.currentData() or "Medium",
            "status": self.status_combo.currentData() or "New",
            "category_id": self.cat_combo.currentData(),
            "subcategory_id": self.sub_combo.currentData(),
            "description": self.desc_edit.toPlainText().strip(),
            "actual_behavior": self.actual_edit.toPlainText().strip(),
            "expected_behavior": self.expected_edit.toPlainText().strip(),
            "model_name": self.model_edits["model_name"].text().strip(),
            "model_version": self.model_edits["model_version"].text().strip(),
            "prompt_version": self.model_edits["prompt_version"].text().strip(),
            "system_prompt_version":
                self.model_edits["system_prompt_version"].text().strip(),
            "external_tracker": self.ext_tracker.text().strip(),
            "external_id": self.ext_id.text().strip(),
            "external_url": self.ext_url.text().strip(),
            "internal_comment": self.internal_edit.text().strip(),
        }

    def _copy_menu(self):
        from PySide6.QtWidgets import QMenu
        if self.bug_id is None:
            notify(self, "warning", "Внимание",
                   "Сначала сохрани баг — копирование работает с сохранённым")
            return
        menu = QMenu(self)
        for fmt, label in (("jira", "Copy for Jira"),
                           ("markdown", "Copy Markdown"),
                           ("plain", "Copy Plain Text")):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _c, f=fmt, name=label: self._do_copy(f, name))
        anchor = self.sender()
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _do_copy(self, fmt: str, label: str):
        import bug_export_service as bex
        try:
            text = bex.render(self.project_path, self.bug_id, fmt)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            import clipboard_service as _clip
            _clip.safe_copy(text)
            _after = _clip.get_clear_after()
            suffix = (f" Буфер будет очищен через {_clip.timeout_label(_after)}."
                      if _after else "")
        except Exception:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
            suffix = ""
        notify(self, "success", "Скопировано", f"{label} — в буфере обмена.{suffix}")

    def _open_linked_case(self):
        """V2.1 §10: сохранить баг и перейти к кейсу (не теряя правки)."""
        item = self.cases_list.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери кейс в списке")
            return
        cid = self._linked[self.cases_list.currentRow()] \
            if 0 <= self.cases_list.currentRow() < len(self._linked) else None
        if not cid:
            return
        data = self._collect()
        if not data["title"]:
            notify(self, "warning", "Ошибка",
                   "Заголовок обязателен — без него баг не сохранить")
            return
        try:
            if self.bug_id is None:
                self.result_id = bugs.create_bug(
                    self.project_path, data.pop("title"), self._linked, **data)
                self.bug_id = self.result_id
            else:
                data.pop("title", None)
                bugs.update_bug(self.project_path, self.bug_id, title=
                                self.title_edit.text().strip(), **data)
                self.result_id = self.bug_id
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.result_case_id = cid
        self.goto_case.emit(cid)

    def _save(self):
        data = self._collect()
        if not data["title"]:
            notify(self, "warning", "Ошибка", "Заголовок обязателен")
            return
        try:
            if self.bug_id is None:
                self.result_id = bugs.create_bug(
                    self.project_path, data.pop("title"), self._linked, **data)
                # Подхват id: повторный «Сохранить» правит, а не дублирует.
                self.bug_id = self.result_id
            else:
                data.pop("title", None)
                bugs.update_bug(self.project_path, self.bug_id, title=
                                self.title_edit.text().strip(), **data)
                # связи в режиме редактирования пишутся сразу (add/del выше)
                self.result_id = self.bug_id
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        notify(self, "success", "Баг", f"Сохранён #{self.result_id}")
        try:
            self._snapshot = self._snap()
        except Exception:
            pass
        self.saved.emit(self.result_id)


class QuickBugDialog(QDialog):
    """Быстрый баг: только заголовок (+severity), остальное — из кейса."""

    def __init__(self, project_path: str, prefill: dict, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.prefill = prefill
        self.result_id = None
        self.setWindowTitle("Быстрый баг")
        self.setMinimumWidth(420)
        layout = QVBoxLayout()
        q = (prefill.get("query") or "")[:160]
        hint = QLabel(f"Кейс {prefill.get('source_id') or prefill.get('case_id')}: {q}")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addWidget(QLabel("Заголовок * (остальное подтянется из кейса):"))
        self.title_edit = FLineEdit()
        self.title_edit.setText(prefill.get("title_suggest", ""))
        layout.addWidget(self.title_edit)
        layout.addWidget(QLabel("Критичность:"))
        self.sev_combo = FComboBox()
        for s in bugs.SEVERITIES:
            self.sev_combo.addItem(bugs.BUG_SEVERITY_NAMES.get(s, s), s)
        # V2.1 §9: severity по умолчанию — из тяжести кейса, а не Medium.
        _sev_map = {"low": "Low", "medium": "Medium",
                    "high": "High", "critical": "Critical"}
        _default = "Medium"
        try:
            from database import db as _db
            _cid = (prefill or {}).get("case_id")
            if _cid:
                with _db(project_path) as _conn:
                    _row = _conn.execute(
                        "SELECT severity FROM case_errors WHERE case_id=?",
                        (_cid,)).fetchone()
                    if _row and _row["severity"]:
                        _default = _sev_map.get(str(_row["severity"]).lower(),
                                                "Medium")
        except Exception:
            pass
        try:
            self.sev_combo.setCurrentIndex(list(bugs.SEVERITIES).index(_default))
        except ValueError:
            self.sev_combo.setCurrentIndex(1)
        layout.addWidget(self.sev_combo)
        btns = QHBoxLayout()
        ok = FPrimaryButton("🐞 Создать")
        ok.clicked.connect(self._save)
        cancel = FPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _save(self):
        title = self.title_edit.text().strip()
        if not title:
            notify(self, "warning", "Ошибка", "Заголовок обязателен")
            return
        p = self.prefill
        try:
            self.result_id = bugs.create_bug(
                self.project_path, title,
                [p["case_id"]] if p.get("case_id") else [],
                severity=self.sev_combo.currentData() or "Medium",
                description=p.get("review_comment", ""),
                category_id=p.get("category_id"),
                subcategory_id=p.get("subcategory_id"),
                model_name=p.get("model_name", ""),
                model_version=p.get("model_version", ""),
                prompt_version=p.get("prompt_version", ""),
                system_prompt_version=p.get("system_prompt_version", ""),
                expected_behavior=p.get("expected_behavior", ""))
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.accept()


class BugReportDialog(QDialog):
    """Тонкая модалка поверх BugReportWidget (старые вызовы целы)."""

    def __init__(self, project_path: str, prefill: dict | None = None,
                 bug_id: int | None = None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Bug Report" if bug_id is None else f"Баг #{bug_id}")
        self.setMinimumSize(640, 620)
        layout = QVBoxLayout()
        self.body = BugReportWidget(project_path, prefill, bug_id, self)
        self.body.saved.connect(self._on_saved)
        self.body.goto_case.connect(self._on_goto)
        layout.addWidget(self.body, 1)
        btn_close = FPushButton("Отмена")
        btn_close.clicked.connect(self.reject)
        layout.addWidget(btn_close)
        self.setLayout(layout)
        self.result_id = None
        self.result_case_id = None

    def _on_saved(self, rid: int):
        self.result_id = rid
        self.accept()

    def _on_goto(self, cid: int):
        self.result_case_id = cid
        self.accept()
