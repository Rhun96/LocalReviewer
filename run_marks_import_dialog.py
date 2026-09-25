"""Импорт оценок ответов прогона из Excel (Preview → Merge/Update).

Маппинг колонок задаётся пользователем и запоминается в проекте:
ID (ключ) / Статус (1/0/текст) / Комментарий / Тяжесть (необязательно).
Тяжесть идёт префиксом комментария (у output_reviews нет поля тяжести).
Комментарий без статуса применяется как «Сомневаюсь», иначе замечание
потерялось бы в статистике (там считаются только статусы).
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QFormLayout,
)
from ui_compat import (FComboBox, FPrimaryButton, FPushButton,
                       clear_in_fluent, notify, polish_table)
import run_marks_io_service as mio


class ImportRunMarksDialog(QDialog):
    def __init__(self, project_path: str, run_id: int, run_name: str = "",
                 parent=None, initial_file: str = ""):
        super().__init__(parent)
        self.project_path = project_path
        self.run_id = run_id
        self.setWindowTitle(f"Импорт оценок: {run_name or run_id}")
        self.setMinimumSize(640, 560)
        self._headers: list = []
        self._rows: list = []
        self._preview_data = None
        self._saved_vals: dict = {}
        self._init_ui()
        if initial_file:
            try:
                from pathlib import Path as _P
                if _P(initial_file).exists():
                    self._load_file(initial_file)
            except Exception:
                pass
        try:
            saved = mio.load_mapping(project_path)
            if saved:
                self._apply_mapping(saved)
        except Exception:
            pass

    def _init_ui(self):
        layout = QVBoxLayout()
        file_row = QHBoxLayout()
        self.file_label = QLabel("Файл не выбран (xlsx/csv/ods)")
        btn = FPushButton("📂 Выбрать файл")
        btn.clicked.connect(self._select)
        file_row.addWidget(self.file_label)
        file_row.addWidget(btn)
        layout.addLayout(file_row)
        sheet_row = QHBoxLayout()
        sheet_row.addWidget(QLabel("Лист:"))
        self.sheet_combo = FComboBox()
        self.sheet_combo.setToolTip("У многостраничных файлов бери нужный лист")
        self.sheet_combo.currentIndexChanged.connect(
            lambda _i: self._reload_sheet())
        sheet_row.addWidget(self.sheet_combo, 2)
        layout.addLayout(sheet_row)
        # Маппинг колонок: один раз вбить — дальше помнится.
        form = QFormLayout()
        self.map_combos: dict = {}
        for key, label in (("id", "ID (ключ) *"),
                           ("status", "Статус *"),
                           ("comment", "Комментарий"),
                           ("severity", "Тяжесть (необязательно)")):
            cb = FComboBox()
            cb.addItem("—", "")
            self.map_combos[key] = cb
            form.addRow(label, cb)
        layout.addLayout(form)
        # Маппинг ЗНАЧЕНИЙ: все уникальные из выбранных колонок.
        vals_row = QHBoxLayout()
        self.status_vals = QTableWidget()
        self.status_vals.setColumnCount(2)
        self.status_vals.setHorizontalHeaderLabels(["Статус в файле", "→"])
        self.status_vals.horizontalHeader().setStretchLastSection(True)
        vals_row.addWidget(self.status_vals)
        self.sev_vals = QTableWidget()
        self.sev_vals.setColumnCount(2)
        self.sev_vals.setHorizontalHeaderLabels(["Тяжесть в файле", "→"])
        self.sev_vals.horizontalHeader().setStretchLastSection(True)
        vals_row.addWidget(self.sev_vals)
        layout.addLayout(vals_row)
        try:
            clear_in_fluent(self.status_vals, self.sev_vals)
        except Exception:
            pass
        self.map_combos["status"].currentIndexChanged.connect(
            lambda _i: self._rebuild_value_tables())
        self.map_combos["severity"].currentIndexChanged.connect(
            lambda _i: self._rebuild_value_tables())
        hint = QLabel("Значения маппятся вручную (дефолт подставляется сам). "
                      "Тяжесть — префиксом комментария. Комментарий без "
                      "статуса → «Сомневаюсь». Всё сохраняется в проекте.")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        mode_row = QHBoxLayout()
        mode_row.addWidget(QLabel("Режим:"))
        self.mode_combo = FComboBox()
        self.mode_combo.addItem("Merge (только пустые)", "merge")
        self.mode_combo.addItem("Update (перезапись различий)", "update")
        mode_row.addWidget(self.mode_combo)
        btn_preview = FPushButton("👁 Preview")
        btn_preview.clicked.connect(self._preview)
        mode_row.addWidget(btn_preview)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        self.summary = QLabel("Выбери файл, расставь колонки, нажми Preview.")
        self.summary.setWordWrap(True)
        layout.addWidget(self.summary)
        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass
        btns = QHBoxLayout()
        ok = FPrimaryButton("▶ Применить")
        ok.clicked.connect(self._apply)
        self.btn_review = FPushButton("📝 В разметку")
        self.btn_review.setToolTip("Открыть разметку этого прогона")
        self.btn_review.setEnabled(False)
        self.btn_review.clicked.connect(self._goto_review)
        cancel = FPushButton("Закрыть")
        cancel.clicked.connect(self.accept)
        btns.addWidget(ok)
        btns.addWidget(self.btn_review)
        btns.addStretch()
        btns.addWidget(cancel)
        layout.addLayout(btns)
        self.setLayout(layout)

    _STATUS_TARGETS = (("Хорошо", "good"), ("Плохо", "bad"),
                         ("Сомневаюсь", "uncertain"), ("Дубль", "duplicate"),
                         ("Пропуск", "skip"), ("— пропустить", ""))
    _SEV_TARGETS = (("— нет", "none"), ("низкая", "низкая"),
                    ("средняя", "средняя"), ("высокая", "высокая"),
                    ("как есть", "as_is"))

    def _mapping(self) -> dict:
        out = {k: cb.currentData() or "" for k, cb in self.map_combos.items()}
        out["sheet"] = self.sheet_combo.currentData() or ""
        out["status_values"] = self._harvest_value_table(
            self.status_vals, 1) or {}
        out["severity_values"] = self._harvest_value_table(
            self.sev_vals, 1) or {}
        return out

    @staticmethod
    def _harvest_value_table(table, col: int = 1) -> dict:
        out = {}
        try:
            for r in range(table.rowCount()):
                key_item = table.item(r, 0)
                cell = table.cellWidget(r, col)
                if key_item is None or cell is None:
                    continue
                try:
                    out[key_item.text()] = cell.currentData()
                except Exception:
                    continue
        except Exception:
            pass
        return out

    def _default_status_target(self, raw: str) -> str:
        try:
            return mio.parse_status(raw) or ""
        except ValueError:
            return ""

    @staticmethod
    def _default_sev_target(raw: str) -> str:
        low = (raw or "").strip().lower()
        if not low or low in mio.SEVERITY_NONE:
            return "none"
        if low in mio.SEVERITY_MAP:
            return mio.SEVERITY_MAP[low]
        return "as_is"

    def _rebuild_value_tables(self) -> None:
        """Таблицы значений: правки > сохранённое > дефолт."""
        if not self._rows:
            return
        saved = getattr(self, "_saved_vals", {}) or {}
        keep_st = self._harvest_value_table(self.status_vals, 1)
        keep_sv = self._harvest_value_table(self.sev_vals, 1)
        self._fill_value_table(
            self.status_vals, self.map_combos["status"].currentData() or "",
            self._STATUS_TARGETS,
            {**{k: self._default_status_target(k) for k in
                mio.distinct_values(self._rows, self.map_combos["status"].currentData() or "")},
             **(saved.get("status_values") or {}), **keep_st})
        self._fill_value_table(
            self.sev_vals, self.map_combos["severity"].currentData() or "",
            self._SEV_TARGETS,
            {**{k: self._default_sev_target(k) for k in
                mio.distinct_values(self._rows, self.map_combos["severity"].currentData() or "")},
             **(saved.get("severity_values") or {}), **keep_sv})

    def _fill_value_table(self, table, header: str, targets: tuple,
                          prefer: dict) -> None:
        from ui_compat import add_elided_item as _addc
        vals = mio.distinct_values(self._rows, header) if header else []
        table.clear()
        table.setColumnCount(2)
        table.setHorizontalHeaderLabels(["Значение", "→"])
        table.setRowCount(len(vals))
        for i, raw in enumerate(vals):
            table.setItem(i, 0, QTableWidgetItem(raw))
            cb = FComboBox()
            for label, data in targets:
                _addc(cb, label, data)
            want = prefer.get(raw, "")
            for j in range(cb.count()):
                if cb.itemData(j) == want:
                    cb.setCurrentIndex(j)
                    break
            table.setCellWidget(i, 1, cb)
        table.resizeColumnsToContents()

    def _apply_mapping(self, mapping: dict) -> None:
        for k, cb in self.map_combos.items():
            want = (mapping or {}).get(k, "")
            for i in range(cb.count()):
                if cb.itemData(i) == want and want:
                    cb.setCurrentIndex(i)
                    break

    def _select(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Оценки прогона", "", "Таблицы (*.xlsx *.csv *.ods)")
        if not path:
            return
        self._load_file(path)

    def _load_file(self, path: str) -> None:
        self._file_path = path
        try:
            sheets = mio.list_sheets(path)
        except Exception:
            sheets = []
        self.sheet_combo.blockSignals(True)
        self.sheet_combo.clear()
        if sheets:
            for s in sheets:
                self.sheet_combo.addItem(s, s)
        else:
            self.sheet_combo.addItem("—", "")
        try:
            want = (mio.load_mapping(self.project_path) or {}).get("sheet", "")
        except Exception:
            want = ""
        if want:
            for i in range(self.sheet_combo.count()):
                if self.sheet_combo.itemData(i) == want:
                    self.sheet_combo.setCurrentIndex(i)
                    break
        self.sheet_combo.blockSignals(False)
        self._reload_sheet()

    def _reload_sheet(self) -> None:
        path = getattr(self, "_file_path", "")
        if not path:
            return
        sheet = self.sheet_combo.currentData() or None
        try:
            headers, rows, errors = mio.read_marks_table(path, sheet)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._headers, self._rows = headers, rows
        from ui_compat import add_elided_item as _addc
        for cb in self.map_combos.values():
            cb.blockSignals(True)
            cb.clear()
            cb.addItem("—", "")
            for h in headers:
                _addc(cb, h, h)
            cb.blockSignals(False)
        # сначала сохранённый маппинг (только целые колонки), иначе угадайка;
        # таблицы значений перестраиваются из него же
        try:
            saved = mio.load_mapping(self.project_path)
        except Exception:
            saved = {}
        cols = {k: saved.get(k, "") for k in
                ("id", "status", "comment", "severity")}
        if any(cols.values()) and all((not v) or (v in headers)
                                      for v in cols.values()):
            self._saved_vals = saved
            self._apply_mapping(cols)
        else:
            self._saved_vals = {}
            self._apply_mapping(mio.guess_mapping(headers))
        self._rebuild_value_tables()
        tail = f", строк с ошибками: {len(errors)}" if errors else ""
        shown = f"{path} [{sheet or '—'}]" if self.sheet_combo.count() > 1 \
            else path
        self.file_label.setText(f"{shown} (строк: {len(rows)}{tail})")
        self.summary.setText("Проверь маппинг и нажми Preview.")
        self._preview_data = None

    def _preview(self):
        if not self._rows:
            notify(self, "warning", "Внимание", "Сначала выбери файл")
            return
        mapping = self._mapping()
        if not mapping["id"] or not mapping["status"]:
            notify(self, "warning", "Внимание",
                   "Нужны колонки ID и статуса")
            return
        try:
            rep = mio.preview_marks(self.project_path, self.run_id,
                                    self._rows, mapping)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        mio.save_mapping(self.project_path, mapping)
        self._preview_data = rep
        text = (
            f"Всего: {rep['total']} | новые: {len(rep['new'])} | "
            f"дозаполнение: {len(rep['updating'])} | "
            f"конфликты: {len(rep['conflicts'])} | "
            f"без изменений: {len(rep['unchanged'])} | "
            f"не найдено: {len(rep['not_found'])} | "
            f"ошибки: {len(rep['errors'])}")
        if rep["not_found"]:
            try:
                import model_run_service as _m
                _ans = _m.list_answers(self.project_path, self.run_id)
                _matched = sum(1 for a in _ans if a["case_id"])
            except Exception:
                _ans, _matched = [], 0
            text += (f"\n⚠️ ID нет среди ответов прогона (ответов: {len(_ans)}, "
                     f"привязано: {_matched}). Порядок: 1) импортируй вопросы "
                     "с этими ID; 2) импортируй ответы — привязка встанет сама; "
                     "3) вернись сюда.")
        self.summary.setText(text)
        rows = (rep["new"] + rep["updating"] + rep["conflicts"]
                + rep["not_found"] + rep["errors"])[:200]
        if rep["total"] > 200:
            text += (f"\nВ таблице — первые 200 строк из {rep['total']}, "
                     "счётчики выше — по всем.")
            self.summary.setText(text)
        self.table.clear()
        self.table.setColumnCount(4)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["ID", "Что будет", "Входящее", "Текущее"])
        for i, r in enumerate(rows):
            if "error" in r:
                kind, inc, cur = "❌ ошибка", r["error"], ""
            elif "stable_key" not in r:
                kind, inc, cur = "🔍 не найден", "", ""
            elif r in rep["conflicts"]:
                kind = "⚠️ конфликт"
                inc = (f"{r['incoming']['status']}; "
                       f"{r['incoming']['comment'][:60]}")
                cur = (f"{r['current']['status']}; "
                       f"{r['current']['comment'][:60]}")
            elif r in rep["new"]:
                kind = "＋ новое"
                inc = (f"{r['incoming']['status']}; "
                       f"{r['incoming']['comment'][:60]}")
                cur = "—"
            else:
                kind = "↻ дозаполнение"
                inc = (f"{r['incoming']['status']}; "
                       f"{r['incoming']['comment'][:60]}")
                cur = (f"{r['current']['status']}; "
                       f"{r['current']['comment'][:60]}")
            self.table.setItem(i, 0, QTableWidgetItem(str(r.get("id", ""))))
            self.table.setItem(i, 1, QTableWidgetItem(kind))
            self.table.setItem(i, 2, QTableWidgetItem(inc))
            self.table.setItem(i, 3, QTableWidgetItem(cur))
        self.table.resizeColumnsToContents()

    def _apply(self):
        if not self._preview_data:
            notify(self, "warning", "Внимание", "Сначала Preview")
            return
        mode = self.mode_combo.currentData() or "merge"
        try:
            done = mio.apply_marks(self.project_path, self.run_id,
                                   self._preview_data, mode)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        notify(self, "success", "Готово",
               f"Применено: {done['applied']}, пропущено: {done['skipped']}, "
               f"не найдено: {done['not_found']}, ошибки: {done['errors']}")
        self.btn_review.setEnabled(done["applied"] > 0)
        self._preview_data = None

    def _goto_review(self):
        try:
            from run_review_dialog import RunReviewDialog
            RunReviewDialog(self.project_path, self.run_id, self).exec()
        except Exception:
            pass
