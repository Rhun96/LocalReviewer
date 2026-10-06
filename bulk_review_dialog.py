"""Массовая разметка прогонов: кейс + все ответы рядом.

Выборка — отмеченные прогоны (1+). Слева ключи, сверху вопрос кейса,
ниже — ответы каждого прогона колонками. Клик по колонке выбирает
ответ, кнопки статусов размечают его (absolute на прогон) и идут
дальше. «Всем ответам кейса» — тот же вердикт сразу всем колонкам.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextBrowser, QSplitter, QGridLayout, QSizePolicy,
    QTextEdit,
)
from PySide6.QtCore import Qt
from ui_compat import FPushButton, FPrimaryButton, notify
import model_run_service as m
import regression_service as rg


class BulkReviewDialog(QDialog):
    EMOJI = {"unreviewed": "⬜", "good": "✅", "bad": "❌",
             "uncertain": "❓", "duplicate": "🔄", "skip": "⏭️"}

    def __init__(self, project_path: str, run_ids: list, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        try:
            self.run_ids = list(dict.fromkeys(int(r) for r in (run_ids or [])))
        except (TypeError, ValueError):
            self.run_ids = []
        self._keys: list = []
        self._idx = 0
        self._active = 0
        self._last_shown = None
        self._data: dict = {}
        self._names: dict = {}
        self.setWindowTitle("Массовая разметка прогонов")
        self.setMinimumSize(1000, 640)
        self._init_ui()
        self._reload()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        mid = QHBoxLayout()
        self.keys_list = QListWidget()
        self.keys_list.setMaximumWidth(220)
        self.keys_list.currentRowChanged.connect(self._on_key)
        mid.addWidget(self.keys_list)
        right = QVBoxLayout()
        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        right.addWidget(self.prompt_label)
        self.panes_row = QHBoxLayout()
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.panes_row.addWidget(self.splitter)
        right.addLayout(self.panes_row, 3)
        self.status_layout = QGridLayout()
        right.addLayout(self.status_layout)
        brow = QHBoxLayout()
        brow.addWidget(QLabel("Комментарий:"))
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(52)
        brow.addWidget(self.comment_edit, 2)
        self.btn_all = FPushButton("Тот же вердикт всем ответам кейса")
        self.btn_all.setToolTip("Повторить текущий вердикт активной колонки "
                                "на все ответы этого кейса")
        self.btn_all.clicked.connect(self._apply_to_all)
        brow.addWidget(self.btn_all)
        right.addLayout(brow)
        mid.addLayout(right, 4)
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
            runs = m.list_runs(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            runs = []
        by_id = {r["run_id"]: r for r in runs}
        self.run_ids = [r for r in self.run_ids if r in by_id]
        if not self.run_ids:
            notify(self, "warning", "Внимание", "Нет прогонов для разметки")
            self._keys, self._data = [], {}
            return
        self._names = {r: by_id[r]["name"] for r in self.run_ids}
        self.setWindowTitle("Массово: " + ", ".join(
            self._names[r] for r in self.run_ids)[:120])
        self._data = {}
        keyset: set = set()
        for r in self.run_ids:
            rows = {x["stable_key"]: dict(x) for x in
                    rg.list_output_reviews(self.project_path, r)}
            self._data[r] = rows
            keyset |= set(rows)
        self._keys = sorted(keyset)
        specs = self._statuses()
        while self.status_layout.count():
            item = self.status_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.status_buttons = {}
        for i, spec in enumerate(specs):
            btn = FPushButton(spec.get("name", spec["code"]))
            btn.setMinimumHeight(32)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                              QSizePolicy.Policy.Fixed)
            btn.clicked.connect(
                lambda _c, s=spec["code"]: self._set_status(s))
            self.status_buttons[spec["code"]] = btn
            self.status_layout.addWidget(btn, i // 4, i % 4)
        while self.splitter.count():
            w = self.splitter.widget(0)
            w.setParent(None)
        self.panes = []
        self.pane_labels = []
        for r in self.run_ids:
            cell = QVBoxLayout()
            lab = QLabel(self._names[r])
            lab.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lab.setStyleSheet("font-weight: bold;")
            cell.addWidget(lab)
            pane = QTextBrowser()
            pane.setReadOnly(True)
            pane.setOpenLinks(False)
            _orig_press = pane.mousePressEvent

            def _click(event, _r=r, _o=_orig_press):
                try:
                    _o(event)
                except Exception:
                    pass
                self._select_run(_r)

            pane.mousePressEvent = _click
            cell.addWidget(pane, 2)
            box = QLabel()
            box.setLayout(cell)
            self.splitter.addWidget(box)
            self.panes.append(pane)
            self.pane_labels.append(lab)
        self._rebuild_keys()
        if self._keys:
            self.keys_list.setCurrentRow(0)
            self._show()

    def _rebuild_keys(self):
        self.keys_list.blockSignals(True)
        try:
            self.keys_list.clear()
            for k in self._keys:
                n = sum(1 for r in self.run_ids
                        if ((self._data.get(r) or {}).get(k, {}).get(
                            "review_status") or "unreviewed") != "unreviewed")
                mark = f"{n}/{len(self.run_ids)}"
                row0 = next((self._data[r][k] for r in self.run_ids
                             if k in (self._data.get(r) or {})), {})
                label = row0.get("source_id") or k
                if len(label) > 24:
                    label = label[:24] + "…"
                self.keys_list.addItem(QListWidgetItem(f"{mark} {label}"))
        finally:
            self.keys_list.blockSignals(False)

    def _reselect_key(self, key):
        try:
            self._idx = self._keys.index(key)
        except ValueError:
            self._idx = min(self._idx, len(self._keys) - 1)
        if self._keys:
            self.keys_list.setCurrentRow(max(0, self._idx))

    def _update_title(self):
        total = len(self._keys) * len(self.run_ids)
        done = sum(
            1 for k in self._keys for r in self.run_ids
            if ((self._data.get(r) or {}).get(k, {}).get("review_status")
                or "unreviewed") != "unreviewed")
        self.title.setText(f"Размечено ответов: {done}/{total}")

    def _on_key(self):
        self._stash_comment()
        self._idx = self.keys_list.currentRow()
        self._show()

    def _select_run(self, run_id: int):
        self._stash_comment()
        try:
            self._active = self.run_ids.index(run_id)
        except ValueError:
            self._active = 0
        self._show()

    def _stash_comment(self):
        """Коммент сохраняется, даже если статус не жали (как в ревью).

        Пишем только за показанную ячейку (_last_shown): иначе первое
        открытие затирало бы комменты пустотой. Статус не трогаем.
        """
        try:
            if not self._last_shown:
                return
            key, rid = self._last_shown
            cell = (self._data.get(rid) or {}).get(key)
            if cell is None:
                return
            text = self.comment_edit.toPlainText().strip() or None
            if (cell.get("review_comment") or None) == text:
                return
            rg.set_output_review(self.project_path, rid, key,
                                 cell.get("review_status") or "unreviewed",
                                 text)
            cell["review_comment"] = text
        except Exception as e:
            import logging as _lg
            _lg.getLogger(__name__).warning("stash comment failed: %s", e)

    def _current_key(self):
        if 0 <= self._idx < len(self._keys):
            return self._keys[self._idx]
        return None

    def _case_topic(self, case_id) -> str:
        if not case_id:
            return ""
        try:
            import json as _json
            from database import db as _db
            from constants import topic_from_metadata as _tof
            with _db(self.project_path) as _conn:
                _m = _conn.execute(
                    "SELECT metadata_json FROM cases WHERE case_id=?",
                    (case_id,)).fetchone()
            if _m and _m["metadata_json"]:
                return _tof(_json.loads(_m["metadata_json"] or "{}"))
        except Exception:
            pass
        return ""

    def _show(self):
        key = self._current_key()
        if not key:
            return
        if not 0 <= self._active < len(self.run_ids):
            self._active = 0
        prompt = ""
        for r in self.run_ids:
            row = (self._data.get(r) or {}).get(key) or {}
            prompt = row.get("primary_text") or row.get("prompt_text") or ""
            if prompt:
                break
        sid = next(((self._data.get(r) or {}).get(key, {}).get("source_id")
                    for r in self.run_ids
                    if (self._data.get(r) or {}).get(key)), key)
        topic = ""
        for r in self.run_ids:
            cid = ((self._data.get(r) or {}).get(key) or {}).get("case_id")
            if cid:
                topic = self._case_topic(cid)
                if topic:
                    break
        self.prompt_label.setText(
            f"📌 {prompt[:400]}{'…' if len(prompt) > 400 else ''}\n🆔 {sid}"
            + (f"\n📰 Тема: {topic[:120]}" if topic else ""))
        for i, r in enumerate(self.run_ids):
            row = (self._data.get(r) or {}).get(key) or {}
            pane = self.panes[i]
            pane.setPlainText(row.get("answer_text") or "(пусто)")
            st = row.get("review_status") or "unreviewed"
            mark = self.EMOJI.get(st, "")
            base = f"{mark} {self._names[r]}".strip()
            self.pane_labels[i].setText(
                f"▶ {base}" if i == self._active else base)
        cur = ((self._data.get(self.run_ids[self._active]) or {}).get(key)
               or {})
        self.comment_edit.setPlainText(cur.get("review_comment") or "")
        self._last_shown = (key, self.run_ids[self._active])
        self._update_title()

    def _set_status(self, status: str):
        key = self._current_key()
        if not key or not self.run_ids:
            return
        rid = self.run_ids[self._active]
        comment = self.comment_edit.toPlainText().strip() or None
        try:
            rg.set_output_review(self.project_path, rid, key, status, comment)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        cell = (self._data.get(rid) or {}).get(key)
        if cell is not None:
            cell["review_status"] = status
            cell["review_comment"] = comment
        self._rebuild_keys()
        self._reselect_key(key)
        self._show()
        self._next_key_or_run()

    def _next_key_or_run(self):
        if self._active + 1 < len(self.run_ids):
            self._active += 1
            self._show()
        else:
            self._active = 0
            self._next()

    def _apply_to_all(self):
        key = self._current_key()
        if not key or not self.run_ids:
            return
        src = ((self._data.get(self.run_ids[self._active]) or {}).get(key)
               or {})
        status = src.get("review_status") or "unreviewed"
        if status == "unreviewed":
            notify(self, "warning", "Внимание",
                   "Сначала поставь вердикт активной колонке")
            return
        comment = self.comment_edit.toPlainText().strip() or None
        bad = []
        for r in self.run_ids:
            if r == self.run_ids[self._active]:
                continue
            try:
                rg.set_output_review(self.project_path, r, key, status,
                                     comment)
                cell = (self._data.get(r) or {}).get(key)
                if cell is not None:
                    cell["review_status"] = status
                    cell["review_comment"] = comment
            except ValueError as e:
                bad.append(f"{self._names.get(r, r)}: {e}")
        if bad:
            notify(self, "warning", "Частично", "\n".join(bad)[:500])
        self._rebuild_keys()
        self._reselect_key(key)
        self._show()

    def _prev(self):
        if self._idx > 0:
            self.keys_list.setCurrentRow(self._idx - 1)

    def _next(self):
        if self._idx < len(self._keys) - 1:
            self.keys_list.setCurrentRow(self._idx + 1)

    def accept(self):
        self._stash_comment()
        super().accept()

    def reject(self):
        self._stash_comment()
        super().reject()
