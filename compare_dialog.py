"""Сравнение ответов двух прогонов рядом (ТЗ §45-48).

Absolute quality — статус кейса (annotations), здесь только показываем.
Предпочтение A vs B (вердикт + ранги 1–3 + комментарий) — сохраняем отдельно.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QTextBrowser, QSplitter,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FLineEdit, FPrimaryButton, FPushButton,
                       clear_in_fluent, notify)
import model_run_service as runs
from model_run_service import VERDICT_NAMES
from diff_service import word_diff_html as _diff_html  # noqa: F401 (совместимость)

_SEV_RU = {"high": "высокая", "medium": "средняя", "low": "низкая",
           "critical": "критическая", "высокая": "высокая",
           "средняя": "средняя", "низкая": "низкая",
           "критическая": "критическая"}
_SEV_HIGH = {"high", "critical", "высокая", "критическая"}
_SIDE_EMOJI = {"good": "✅", "bad": "❌", "uncertain": "❓",
               "duplicate": "🔄", "skip": "⏭️", "unreviewed": "⬜"}


def _side_severity(comment: str, case_severity: str) -> str:
    """Тяжесть стороны: префикс комментария, иначе тяжесть кейса."""
    try:
        from run_marks_io_service import split_comment as _split
        sev, _body = _split(comment or "")
        if sev:
            return sev
    except Exception:
        pass
    raw = (case_severity or "").strip()
    if not raw:
        return ""
    return _SEV_RU.get(raw, _SEV_RU.get(raw.lower(), raw))


def _side_is_bad(project_path: str, status: str) -> bool:
    try:
        from review_profile_service import code_to_base
        base = code_to_base(project_path).get(status, status)
    except Exception:
        base = status
    return base == "bad"


def _side_is_high(severity: str) -> bool:
    s = (severity or "").strip().lower()
    return s in _SEV_HIGH or _SEV_RU.get(s, "") in _SEV_HIGH


class CompareDialog(QDialog):
    def __init__(self, project_path: str, run_a: int, run_b: int, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.run_a = run_a
        self.run_b = run_b
        self._rows = []
        self._idx = 0
        self._names = {}
        self.setWindowTitle("Сравнение прогонов")
        self.setMinimumSize(900, 640)
        self._init_ui()
        self._reload()

    def _init_ui(self):
        layout = QVBoxLayout()
        self.title = QLabel("")
        self.title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.title)
        self.stats = QLabel("")
        self.stats.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.stats.setWordWrap(True)
        layout.addWidget(self.stats)

        mid = QHBoxLayout()
        self.keys_list = QListWidget()
        self.keys_list.setMaximumWidth(280)
        self.keys_list.currentRowChanged.connect(self._on_key_selected)
        mid.addWidget(self.keys_list)

        right = QVBoxLayout()
        self.prompt_label = QLabel("")
        self.prompt_label.setWordWrap(True)
        right.addWidget(self.prompt_label)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.pane_a = QTextBrowser()
        self.pane_b = QTextBrowser()
        splitter.addWidget(self.pane_a)
        splitter.addWidget(self.pane_b)
        splitter.setSizes([450, 450])
        right.addWidget(splitter, 2)
        legend = QLabel("🔴 есть только в A · 🟢 есть только в B — "
                        "это diff текстов, а не оценка (оценка — кнопки вердикта ниже)")
        legend.setWordWrap(True)
        right.addWidget(legend)
        self.abs_label = QLabel("")
        right.addWidget(self.abs_label)

        verdict_row = QHBoxLayout()
        self.verdict_btns = {}
        for code in ("a_better", "b_better", "tie", "unknown"):
            btn = FPushButton(VERDICT_NAMES[code])
            btn.setCheckable(True)
            btn.setMinimumHeight(34)
            btn.clicked.connect(lambda _c, v=code: self._set_verdict(v))
            verdict_row.addWidget(btn)
            self.verdict_btns[code] = btn
        right.addLayout(verdict_row)

        rank_row = QHBoxLayout()
        rank_row.addWidget(QLabel("Ранг A (1–3):"))
        self.rank_a = FComboBox()
        self.rank_a.addItem("—", None)
        for i in (1, 2, 3):
            self.rank_a.addItem(str(i), i)
        self.rank_a.currentIndexChanged.connect(self._save_marks)
        rank_row.addWidget(self.rank_a)
        rank_row.addWidget(QLabel("Ранг B (1–3):"))
        self.rank_b = FComboBox()
        self.rank_b.addItem("—", None)
        for i in (1, 2, 3):
            self.rank_b.addItem(str(i), i)
        self.rank_b.currentIndexChanged.connect(self._save_marks)
        rank_row.addWidget(self.rank_b)
        rank_row.addWidget(QLabel("Комментарий:"))
        self.comment_edit = FLineEdit()
        rank_row.addWidget(self.comment_edit, 2)
        btn_save_comment = FPushButton("💾")
        btn_save_comment.setMaximumWidth(44)
        btn_save_comment.setToolTip("Сохранить ранги и комментарий")
        btn_save_comment.clicked.connect(lambda: self._save_marks(notify_ok=True))
        rank_row.addWidget(btn_save_comment)
        right.addLayout(rank_row)
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
        try:
            clear_in_fluent(self.pane_a, self.pane_b, self.keys_list)
        except Exception:
            pass

    def _reload(self):
        try:
            ra = runs.get_run(self.project_path, self.run_a)
            rb = runs.get_run(self.project_path, self.run_b)
            self._names = {self.run_a: ra["name"], self.run_b: rb["name"]}
            data = runs.compare_runs(self.project_path, self.run_a, self.run_b)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            self._rows = []
            return
        self._rows = data["rows"]
        c = data["counts"]
        self.title.setText(f"⚖️ {ra['name']}  vs  {rb['name']}")
        self.stats.setText(self._stats_text(c))
        self.keys_list.clear()
        for row in self._rows:
            mark = {"a_better": "◀", "b_better": "▶", "tie": "＝"}.get(
                row["verdict"] if row["has_verdict"] else "", "·")
            label = row["source_id"] or row["stable_key"]
            if len(label) > 32:
                label = label[:32] + "…"
            item = QListWidgetItem(f"{mark} {label}")
            self.keys_list.addItem(item)
        if self._rows:
            self._idx = min(self._idx, len(self._rows) - 1)
            self.keys_list.setCurrentRow(self._idx)
            self._show_row()
        else:
            self.prompt_label.setText("Нет общих и раздельных ключей.")

    def _side_summary(self) -> str:
        """Итоги по тяжести сторон: плохих и тяжёлых у A и B."""
        try:
            bad_a = bad_b = high_a = high_b = 0
            for r in self._rows:
                sa = _side_severity(r.get("comment_a") or "",
                                    r.get("case_severity") or "")
                sb = _side_severity(r.get("comment_b") or "",
                                    r.get("case_severity") or "")
                if _side_is_bad(self.project_path,
                                r.get("status_a") or "unreviewed"):
                    bad_a += 1
                    if _side_is_high(sa):
                        high_a += 1
                if _side_is_bad(self.project_path,
                                r.get("status_b") or "unreviewed"):
                    bad_b += 1
                    if _side_is_high(sb):
                        high_b += 1
            if not (bad_a or bad_b):
                return ""
            return (f" | Плохих A: {bad_a} (тяжёлых: {high_a}), "
                    f"B: {bad_b} (тяжёлых: {high_b})")
        except Exception:
            return ""

    def _stats_text(self, c: dict) -> str:
        total = len(self._rows)
        judged = total - c["no_verdict"]
        return (
            f"Кейсов: {total} (оба: {c['both']}, только A: {c['only_a']}, "
            f"только B: {c['only_b']}) | Оценено: {judged} | "
            f"A лучше: {c['a_better']}, B лучше: {c['b_better']}, "
            f"одинаково: {c['tie']}{self._side_summary()}")

    def _current(self) -> dict | None:
        if 0 <= self._idx < len(self._rows):
            return self._rows[self._idx]
        return None

    def _on_key_selected(self):
        self._idx = self.keys_list.currentRow()
        self._show_row()

    def _show_row(self):
        row = self._current()
        if not row:
            return
        name_a = self._names.get(self.run_a, "A")
        name_b = self._names.get(self.run_b, "B")
        prompt = (row.get("primary_text") or row.get("prompt_a")
                  or row.get("prompt_b") or "")
        pa = (row.get("product_a") or "").strip()
        pb = (row.get("product_b") or "").strip()
        if pa and pa == pb:
            prod = pa
        else:
            parts = []
            if pa:
                parts.append(f"A: {pa}")
            if pb:
                parts.append(f"B: {pb}")
            prod = " / ".join(parts) or (row.get("product_case") or "").strip()
        self.prompt_label.setText(
            f"📌 {prompt[:400]}{'…' if len(prompt) > 400 else ''}"
            f"\n🆔 {row.get('source_id') or row['stable_key']}"
            + (f"\n🏷️ {prod}" if prod else ""))
        html_a, html_b = _diff_html(row["answer_a"], row["answer_b"])
        try:
            from review_profile_service import status_display_name as _sdn
            _na = _sdn(self.project_path, row.get("status_a") or "unreviewed")
            _nb = _sdn(self.project_path, row.get("status_b") or "unreviewed")
        except Exception:
            _na = row.get("status_a") or "unreviewed"
            _nb = row.get("status_b") or "unreviewed"
        _sa = _side_severity(row.get("comment_a") or "",
                             row.get("case_severity") or "")
        _sb = _side_severity(row.get("comment_b") or "",
                             row.get("case_severity") or "")
        _la = f"{_SIDE_EMOJI.get(row.get('status_a') or 'unreviewed', '')} {_na}"
        if _sa:
            _la += f" · Критичность: {_sa}"
        _lb = f"{_SIDE_EMOJI.get(row.get('status_b') or 'unreviewed', '')} {_nb}"
        if _sb:
            _lb += f" · Критичность: {_sb}"
        self.pane_a.setHtml(f"<b>[{name_a}]</b> {_la}<br><br>{html_a}")
        self.pane_b.setHtml(f"<b>[{name_b}]</b> {_lb}<br><br>{html_b}")
        st = row.get("case_status") or "unreviewed"
        try:
            from review_profile_service import status_display_name
            st_name = status_display_name(self.project_path, st)
        except Exception:
            st_name = st
        self.abs_label.setText(f"Absolute (разметка кейса): {st_name}")
        for code, btn in self.verdict_btns.items():
            btn.blockSignals(True)
            btn.setChecked(row.get("verdict") == code and row.get("has_verdict"))
            btn.blockSignals(False)
        for combo, key in ((self.rank_a, "rank_a"), (self.rank_b, "rank_b")):
            combo.blockSignals(True)
            combo.setCurrentIndex(0)
            val = row.get(key)
            if val:
                for i in range(combo.count()):
                    if combo.itemData(i) == val:
                        combo.setCurrentIndex(i)
                        break
            combo.blockSignals(False)
        self.comment_edit.blockSignals(True)
        self.comment_edit.setText(row.get("comment") or "")
        self.comment_edit.blockSignals(False)

    def _set_verdict(self, verdict: str):
        row = self._current()
        if not row:
            return
        try:
            runs.set_preference(self.project_path, self.run_a, self.run_b,
                                row["stable_key"], verdict,
                                self.rank_a.currentData(), self.rank_b.currentData(),
                                self.comment_edit.text().strip() or None)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._refresh_row_state(verdict)

    def _save_marks(self, notify_ok: bool = False):
        row = self._current()
        if not row:
            return
        verdict = row["verdict"] if row.get("has_verdict") else "unknown"
        try:
            runs.set_preference(self.project_path, self.run_a, self.run_b,
                                row["stable_key"], verdict,
                                self.rank_a.currentData(), self.rank_b.currentData(),
                                self.comment_edit.text().strip() or None)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        if notify_ok:
            notify(self, "success", "Сохранено", "Ранги и комментарий записаны")

    def _refresh_row_state(self, verdict: str):
        # Обновляем кэш строки и метку в списке без полного пересчёта.
        for r in self._rows:
            if r["stable_key"] == (self._current() or {}).get("stable_key"):
                r["verdict"] = verdict
                r["has_verdict"] = True
                r["rank_a"] = self.rank_a.currentData()
                r["rank_b"] = self.rank_b.currentData()
                r["comment"] = self.comment_edit.text().strip() or None
                break
        item = self.keys_list.item(self._idx)
        if item:
            mark = {"a_better": "◀", "b_better": "▶", "tie": "＝"}.get(verdict, "·")
            item.setText(f"{mark} " + item.text()[2:])
        for code, btn in self.verdict_btns.items():
            btn.blockSignals(True)
            btn.setChecked(code == verdict)
            btn.blockSignals(False)
        try:
            data = runs.compare_runs(self.project_path, self.run_a, self.run_b)
            c = data["counts"]
            self.stats.setText(self._stats_text(c))
        except Exception:
            pass

    def _prev(self):
        if self._idx > 0:
            self.keys_list.setCurrentRow(self._idx - 1)

    def _next(self):
        if self._idx < len(self._rows) - 1:
            self.keys_list.setCurrentRow(self._idx + 1)
