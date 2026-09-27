"""Похожие кейсы (ТЗ §64-70): боковая панель контекста, без автопростановки."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem,
)
from PySide6.QtCore import Qt
from ui_compat import (FCheckBox, FComboBox, FPushButton, FSpinBox,
                       clear_in_fluent, notify)
import similarity_service as sim


class SimilarDialog(QDialog):
    """result_case_id — выбранный похожий кейс (переход по двойному клику)."""

    def __init__(self, project_path: str, case_id: int, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.case_id = case_id
        self.result_case_id = None
        self.setWindowTitle("Похожие кейсы")
        self.setMinimumSize(620, 520)
        self._init_ui()
        self._search()

    def _init_ui(self):
        layout = QVBoxLayout()
        hint = QLabel("Похожие размеченные кейсы — только контекст для решения, "
                      "статус по ним не ставится.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.suggest_label = QLabel("")
        self.suggest_label.setWordWrap(True)
        layout.addWidget(self.suggest_label)
        sug_row = QHBoxLayout()
        self.btn_apply_status = FPushButton("✅ Применить статус")
        self.btn_apply_status.setToolTip("Поставить предложенный статус текущему кейсу")
        self.btn_apply_status.clicked.connect(lambda: self._apply("status"))
        self.btn_apply_cause = FPushButton("⚠ Применить причину")
        self.btn_apply_cause.setToolTip("Поставить предложенную причину текущему кейсу")
        self.btn_apply_cause.clicked.connect(lambda: self._apply("cause"))
        sug_row.addWidget(self.btn_apply_status)
        sug_row.addWidget(self.btn_apply_cause)
        sug_row.addStretch()
        layout.addLayout(sug_row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Где искать:"))
        self.scope_combo = FComboBox()
        self.scope_combo.addItem("В текущем файле", "file")
        self.scope_combo.addItem("В проекте", "project")
        self.scope_combo.addItem("В Golden", "golden")
        self.scope_combo.addItem("В архивных", "archive")
        row.addWidget(self.scope_combo)
        row.addWidget(QLabel("Мин. схожесть:"))
        self.min_spin = FSpinBox()
        self.min_spin.setRange(50, 100)
        self.min_spin.setValue(75)
        self.min_spin.setSuffix(" %")
        self.min_spin.setMaximumWidth(120)
        row.addWidget(self.min_spin)
        layout.addLayout(row)
        frow = QHBoxLayout()
        frow.addWidget(QLabel("По полям:"))
        self.field_boxes = {}
        for code, name in (("primary_text", "Запрос"), ("response_text", "Ответ"),
                           ("group_name", "Группа"), ("product", "Продукт")):
            cb = FCheckBox(name)
            cb.setChecked(code == "primary_text")
            self.field_boxes[code] = cb
            frow.addWidget(cb)
        frow.addStretch()
        layout.addLayout(frow)
        btn_row = QHBoxLayout()
        btn_find = FPushButton("🔍 Найти")
        btn_find.clicked.connect(self._search)
        btn_row.addWidget(btn_find)
        btn_row.addStretch()
        layout.addLayout(btn_row)
        self.info = QLabel("")
        layout.addWidget(self.info)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._on_open)
        self.results.currentItemChanged.connect(lambda *_a: self._show_preview())
        layout.addWidget(self.results, 2)
        try:
            clear_in_fluent(self.results)
        except Exception:
            pass
        from PySide6.QtWidgets import QSplitter, QTextBrowser
        preview = QSplitter(Qt.Orientation.Horizontal)
        self.preview_a = QTextBrowser()
        self.preview_a.setReadOnly(True)
        self.preview_a.setMaximumHeight(150)
        self.preview_b = QTextBrowser()
        self.preview_b.setReadOnly(True)
        self.preview_b.setMaximumHeight(150)
        preview.addWidget(self.preview_a)
        preview.addWidget(self.preview_b)
        try:
            clear_in_fluent(self.preview_a, self.preview_b)
        except Exception:
            pass
        layout.addWidget(preview)
        btns = QHBoxLayout()
        btn_open = FPushButton("➡️ Открыть выбранный")
        btn_open.clicked.connect(self._on_open)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_open)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _params(self):
        fields = tuple(c for c, cb in self.field_boxes.items() if cb.isChecked())
        return {"min_score": self.min_spin.value() / 100,
                "scope": self.scope_combo.currentData() or "file",
                "fields": fields or ("primary_text",)}

    def _search(self):
        try:
            be, note = sim.resolve_backend()
            res = be.find_similar(self.project_path, self.case_id, **self._params())
        except ValueError as e:
            notify(self, "warning", "Поиск", str(e))
            return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        engine = f" [движок: {be.name}{(' — ' + note) if note else ''}]"
        self.results.clear()
        if not res["results"]:
            self.info.setText("Ничего похожего не нашлось — попробуй снизить порог "
                              "или расширить область." + engine)
            self._refresh_suggestion()
            return
        labeled = sum(1 for r in res["results"] if r["reviewed"])
        self.info.setText(f"Найдено: {res['total']}, из них размеченных: {labeled}. "
                          "Двойной клик — открыть кейс." + engine)
        try:
            # Авто-индексация недостающего — в фон, без фриза.
            from ui_compat import get_embed_auto as _auto
            missing = res.get("missing") or []
            if be.name == "embedding" and _auto() and missing:
                from workers import run_in_background as _run
                import embedding_service as _emb
                _run(_emb.ensure_indexed, self.project_path, list(missing))
        except Exception:
            pass
        for r in res["results"]:
            pct = int(round(r["score"] * 100))
            mark = "✅" if r["reviewed"] else "⬜"
            label = r["source_id"] or f"case:{r['case_id']}"
            item = QListWidgetItem(f"{pct}% {mark} {r['status']} | {label} | "
                                   f"{r['snippet'][:100]}")
            item.setData(Qt.ItemDataRole.UserRole, r["case_id"])
            self.results.addItem(item)
        self._refresh_suggestion()

    def _on_open(self):
        item = self.results.currentItem()
        if not item:
            return
        self.result_case_id = item.data(Qt.ItemDataRole.UserRole)
        self.accept()

    def _show_preview(self):
        """Превью пары: текущий кейс vs выбранный похожий."""
        try:
            item = self.results.currentItem()
            if item is None:
                return
            cid = item.data(Qt.ItemDataRole.UserRole)
            ta, tb = pair_preview(self.project_path, self.case_id, int(cid))
            self.preview_a.setPlainText(ta)
            self.preview_b.setPlainText(tb)
        except Exception:
            pass

    def _refresh_suggestion(self):
        """Предложение по одинаково размеченным похожим (§33): вручную."""
        self._suggestion = {"status": None, "category": None}
        try:
            import category_suggestion_service as sug
            self._suggestion = sug.suggest_annotations(
                self.project_path, self.case_id)
        except Exception:
            pass
        parts = []
        st = (self._suggestion or {}).get("status")
        if st:
            parts.append(f"статус «{st['status']}» "
                         f"({st['support']} кейса, score {st['score']})")
        else:
            parts.append("статуса нет (похожие размечены по-разному)")
        cat = (self._suggestion or {}).get("category")
        if cat:
            parts.append(f"причина «{cat.get('category_name', '')} → "
                         f"{cat.get('subcategory_name', '')}» "
                         f"({cat['support']} кейса)")
        self.suggest_label.setText("💡 Предложено: " + "; ".join(parts))
        self.btn_apply_status.setEnabled(bool(st))
        self.btn_apply_cause.setEnabled(bool(cat))

    def _apply(self, what: str):
        from database import db as _db, utcnow as _utcnow
        sug = getattr(self, "_suggestion", {}) or {}
        try:
            if what == "status":
                st = (sug.get("status") or {}).get("status")
                if not st:
                    return
                now = _utcnow()
                with _db(self.project_path) as conn:
                    cur = conn.cursor()
                    old = cur.execute("SELECT status FROM annotations WHERE case_id=?",
                                      (self.case_id,)).fetchone()
                    old_st = old["status"] if old else "unreviewed"
                    cur.execute("""
                        INSERT INTO annotations (case_id, status, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                    """, (self.case_id, st, now, st, now))
                    if old_st != st:
                        cur.execute("""
                            INSERT INTO history (case_id, event_type, field_name,
                                                 old_value, new_value, created_at)
                            VALUES (?, 'status_changed', 'status', ?, ?, ?)
                        """, (self.case_id, old_st, st, now))
            else:
                cat = sug.get("category") or {}
                if not cat.get("category_id"):
                    return
                from taxonomy_service import set_case_error
                set_case_error(self.project_path, self.case_id,
                               cat["category_id"], cat.get("subcategory_id"),
                               "medium")
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Применено",
               "Разметка поставлена вручную по предложению")
        self._refresh_suggestion()


def pair_preview(project_path: str, case_a: int, case_b: int,
                 limit: int = 500) -> tuple:
    """Тексты пары для превью (Вопрос + Ответ, обрезка)."""
    out = []
    try:
        from database import db as _db
        with _db(project_path) as conn:
            for cid in (case_a, case_b):
                row = conn.execute(
                    "SELECT primary_text, response_text FROM cases WHERE case_id=?",
                    (cid,)).fetchone()
                if row is None:
                    out.append("— кейс не найден —")
                    continue
                q = (row["primary_text"] or "").strip()
                a = (row["response_text"] or "").strip()
                text = f"Вопрос: {q}\nОтвет: {a}".strip()
                if len(text) > limit:
                    text = text[:limit] + "…"
                out.append(text or "— пусто —")
    except Exception:
        out = ["— ошибка —", "— ошибка —"]
    return (out + ["—", "—"])[:2]


class DuplicatesDialog(QDialog):
    """Потенциальные дубли в файле/проекте (попарный TF-IDF, порог)."""

    def __init__(self, project_path: str, file_id: int | None = None, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.file_id = file_id
        self.result_case_id = None
        self.setWindowTitle("Потенциальные дубли")
        self.setMinimumSize(760, 560)
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        scope = ("текущем файле" if self.file_id else "проекте")
        self.hint_label = QLabel(
            f"Попарное сравнение в {scope} (запрос+ответ). "
            "Дубли не ставятся автоматически. "
            "Перефразировки лови порогом ниже (70–80%).")
        self.hint_label.setWordWrap(True)
        layout.addWidget(self.hint_label)
        row = QHBoxLayout()
        row.addWidget(QLabel("Порог:"))
        self.thr_spin = FSpinBox()
        self.thr_spin.setRange(50, 100)
        self.thr_spin.setValue(90)
        self.thr_spin.setSuffix(" %")
        self.thr_spin.setMaximumWidth(120)
        row.addWidget(self.thr_spin)
        btn = FPushButton("🔍 Найти дубли")
        btn.clicked.connect(self._search)
        row.addWidget(btn)
        row.addStretch()
        layout.addLayout(row)
        try:
            # Эмбеддинги жмут скоры вверх: дефолт и подсказка свои.
            be, _note = sim.resolve_backend()
            if be.name == "embedding":
                self.thr_spin.setValue(95)
                self.hint_label.setText(
                    f"Попарное сравнение эмбеддингами в {scope}. "
                    "Дубли не ставятся автоматически. "
                    "Эмбеддинги жмут скоры вверх: дубли лови порогом 93–98%.")
        except Exception:
            pass
        self.info = QLabel("")
        layout.addWidget(self.info)
        self.results = QListWidget()
        self.results.itemDoubleClicked.connect(self._on_open)
        self.results.currentItemChanged.connect(lambda *_a: self._show_pair())
        self.results.setMinimumHeight(140)
        layout.addWidget(self.results, 2)
        try:
            clear_in_fluent(self.results)
        except Exception:
            pass
        from PySide6.QtWidgets import QSplitter, QTextBrowser
        pair_split = QSplitter(Qt.Orientation.Horizontal)
        self.pair_a = QTextBrowser()
        self.pair_a.setReadOnly(True)
        self.pair_a.setMinimumHeight(120)
        self.pair_b = QTextBrowser()
        self.pair_b.setReadOnly(True)
        self.pair_b.setMinimumHeight(120)
        pair_split.addWidget(self.pair_a)
        pair_split.addWidget(self.pair_b)
        try:
            clear_in_fluent(self.pair_a)
            clear_in_fluent(self.pair_b)
        except Exception:
            pass
        layout.addWidget(pair_split, 1)
        btns = QHBoxLayout()
        btn_open = FPushButton("➡️ Открыть первый из пары")
        btn_open.clicked.connect(self._on_open)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.reject)
        btns.addWidget(btn_open)
        btns.addStretch()
        btns.addWidget(btn_close)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _search(self):
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Поиск дублей…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)
        thr = self.thr_spin.value() / 100
        file_id = self.file_id

        def _work_outer():
            from workers import run_in_background as _run
            holder: dict = {}

            def _progress(done, total):
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(
                        int(done / total * 100) if total else 0)

            be, _note = sim.resolve_backend()
            worker = _run(be.find_duplicates, self.project_path, file_id, thr,
                          200, _progress, cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(res):
            try:
                progress.close()
            except Exception:
                pass
            self.results.clear()
            if not res["pairs"]:
                self.info.setText("Дублей выше порога нет.")
                return
            extra = f" (показаны первые {len(res['pairs'])})" if res["truncated"] else ""
            self.info.setText(f"Пар: {res['total']}{extra}. Двойной клик — открыть.")
            for p in res["pairs"]:
                pct = int(round(p["score"] * 100))
                item = QListWidgetItem(
                    f"{pct}%  case:{p['case_a']}  ⇄  case:{p['case_b']}")
                item.setData(Qt.ItemDataRole.UserRole,
                             (p["case_a"], p["case_b"]))
                self.results.addItem(item)
            try:
                if self.results.count():
                    self.results.setCurrentRow(0)
            except Exception:
                pass
            self._show_pair()

        def _fail(msg):
            try:
                progress.close()
            except Exception:
                pass
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Поиск", str(msg))
            elif "Слишком много" in (msg or ""):
                notify(self, "warning", "Поиск", str(msg))
            else:
                notify(self, "error", "Ошибка", str(msg))

        QTimer.singleShot(0, _work_outer)

    def _show_pair(self):
        """Превью выбранной пары: оба текста рядом, ходить никуда не надо."""
        try:
            item = self.results.currentItem()
            if item is None:
                return
            data = item.data(Qt.ItemDataRole.UserRole)
            if not isinstance(data, (list, tuple)) or len(data) != 2:
                return
            ta, tb = pair_preview(self.project_path, int(data[0]), int(data[1]))
            self.pair_a.setPlainText(ta)
            self.pair_b.setPlainText(tb)
        except Exception:
            pass

    def _on_open(self):
        item = self.results.currentItem()
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        try:
            self.result_case_id = int(data[0]) if isinstance(
                data, (list, tuple)) else int(data)
        except Exception:
            return
        self.accept()
