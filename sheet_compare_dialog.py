"""Сравнение структуры листов и упорядочивание по эталону."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QFileDialog,
)
from ui_compat import (FCheckBox, FComboBox, FPrimaryButton, FPushButton,
                       clear_in_fluent, notify)
import sheet_align_service as align
from file_reader import FileReader


class SheetCompareDialog(QDialog):
    """Эталонный лист A vs целевой B: расхождения + «Упорядочить» + выгрузка."""

    def __init__(self, file_path: str, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.reader = FileReader()
        try:
            self.file_type = self.reader.detect_file_type(file_path)
        except ValueError as e:
            self.file_type = "unknown"
            self._init_error = str(e)
        else:
            self._init_error = None
        self._ordered = None  # (headers, rows) после упорядочивания
        self.setWindowTitle("Сравнение листов")
        self.setMinimumSize(640, 560)
        self._init_ui()
        if self._init_error:
            notify(self, "warning", "Формат", self._init_error)
        else:
            self._reload_sheets()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Файл: {self.file_path}"))
        row = QHBoxLayout()
        row.addWidget(QLabel("Эталон A:"))
        self.combo_a = FComboBox()
        row.addWidget(self.combo_a)
        row.addWidget(QLabel("Цель B:"))
        self.combo_b = FComboBox()
        row.addWidget(self.combo_b)
        btn_cmp = FPrimaryButton("⇄ Сравнить")
        btn_cmp.clicked.connect(self._compare)
        row.addWidget(btn_cmp)
        layout.addLayout(row)
        filt_a = QHBoxLayout()
        filt_a.addWidget(QLabel("Фильтр A:"))
        self.cond_box_a = QVBoxLayout()
        filt_a.addLayout(self.cond_box_a, 3)
        btn_add_a = FPushButton("＋ условие")
        btn_add_a.setMaximumWidth(120)
        btn_add_a.clicked.connect(lambda: self._add_cond_row("a"))
        filt_a.addWidget(btn_add_a)
        layout.addLayout(filt_a)
        filt_b = QHBoxLayout()
        filt_b.addWidget(QLabel("Фильтр B:"))
        self.cond_box_b = QVBoxLayout()
        filt_b.addLayout(self.cond_box_b, 3)
        btn_add_b = FPushButton("＋ условие")
        btn_add_b.setMaximumWidth(120)
        btn_add_b.clicked.connect(lambda: self._add_cond_row("b"))
        filt_b.addWidget(btn_add_b)
        btn_apply_filter = FPushButton("Применить")
        btn_apply_filter.clicked.connect(self._compare)
        filt_b.addWidget(btn_apply_filter)
        btn_reset_filter = FPushButton("Сбросить")
        btn_reset_filter.clicked.connect(self._reset_filter)
        filt_b.addWidget(btn_reset_filter)
        layout.addLayout(filt_b)
        # Совместимость: старые имена указывают на первое условие B.
        self._cond_rows = {"a": [], "b": []}
        self._add_cond_row("a")
        self._add_cond_row("b")
        self.filter_stats = QLabel("")
        self.filter_stats.setWordWrap(True)
        layout.addWidget(self.filter_stats)
        self.result = QListWidget()
        layout.addWidget(self.result, 2)
        try:
            clear_in_fluent(self.result)
        except Exception:
            pass
        opt_row = QHBoxLayout()
        self.keep_extra = FCheckBox("Лишние колонки — в конец (иначе отбросить)")
        self.keep_extra.setChecked(True)
        opt_row.addWidget(self.keep_extra)
        self.export_filtered = FCheckBox("Выгружать с учётом фильтра")
        self.export_filtered.setToolTip("Иначе выгружается весь лист целиком")
        opt_row.addWidget(self.export_filtered)
        btn_order = FPushButton("🧹 Упорядочить B по A")
        btn_order.clicked.connect(self._order)
        opt_row.addWidget(btn_order)
        layout.addLayout(opt_row)
        exp_row = QHBoxLayout()
        btn_sheet = FPushButton("📤 Выгрузить упорядоченный лист")
        btn_sheet.clicked.connect(lambda: self._export(whole=False))
        btn_file = FPushButton("📤 Выгрузить файл целиком")
        btn_file.clicked.connect(lambda: self._export(whole=True))
        exp_row.addWidget(btn_sheet)
        exp_row.addWidget(btn_file)
        layout.addLayout(exp_row)
        self.info = QLabel("Нормализация — только .xlsx (запись); сравнение — xlsx/ods. "
                           "Значения не меняются, форматирование ячеек не сохраняется.")
        self.info.setWordWrap(True)
        layout.addWidget(self.info)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        self.setLayout(layout)

    def _reload_sheets(self):
        try:
            if self.file_type == "excel":
                sheets = self.reader.read_excel_sheets(self.file_path)
            elif self.file_type == "ods":
                sheets = self.reader.read_ods_sheets(self.file_path)
            else:
                notify(self, "warning", "Формат",
                       "Сравнение структуры — для xlsx/ods")
                return
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.combo_a.clear()
        self.combo_b.clear()
        from ui_compat import add_elided_item as _add
        for s in sheets:
            _add(self.combo_a, s, s)
            _add(self.combo_b, s, s)
        if len(sheets) > 1:
            self.combo_b.setCurrentIndex(1)
        from ui_compat import bound_combo_popup as _bound
        _bound(self.combo_a)
        _bound(self.combo_b)
        # Списки условий всегда соответствуют текущим листам:
        # при смене A/B перезаполняем колонки (иначе висят чужие).
        try:
            self.combo_a.currentIndexChanged.connect(
                lambda _i: self._reload_filter_columns())
            self.combo_b.currentIndexChanged.connect(
                lambda _i: self._reload_filter_columns())
        except Exception:
            pass
        self._reload_filter_columns()

    def _sheets(self):
        a, b = self.combo_a.currentData(), self.combo_b.currentData()
        if not a or not b:
            notify(self, "warning", "Внимание", "Выбери оба листа")
            return None, None
        if a == b:
            notify(self, "warning", "Внимание", "Листы совпадают — сравнивать нечего")
            return None, None
        return a, b

    def _side_sheets(self) -> dict:
        return {"a": self.combo_a.currentData(), "b": self.combo_b.currentData()}

    def _side_headers(self, side: str) -> list:
        sheet = self._side_sheets()[side]
        if not sheet:
            return []
        try:
            return [h for h in
                    align.sheet_headers(self.file_path, self.file_type, sheet) if h]
        except Exception:
            return []

    def _add_cond_row(self, side: str):
        """Строка условия (колонка + значение + ✕). Максимум 5 на сторону."""
        box = self.cond_box_a if side == "a" else self.cond_box_b
        if len(self._cond_rows[side]) >= 5:
            notify(self, "warning", "Фильтр", "Хватит и пяти условий на сторону")
            return
        row = QHBoxLayout()
        col_box = FComboBox()
        col_box.addItem("— колонка —", None)
        col_box.setMaximumWidth(280)
        from ui_compat import add_elided_item as _add2, bound_combo_popup as _bound2
        for h in self._side_headers(side):
            _add2(col_box, h, h)
        val_box = FComboBox()
        val_box.addItem("— значение —", None)
        val_box.setMaximumWidth(280)
        _bound2(col_box)
        _bound2(val_box)
        col_box.currentIndexChanged.connect(
            lambda _i, s=side, r=row: self._reload_row_values(s, r))
        btn_del = FPushButton("✕")
        btn_del.setMaximumWidth(40)
        btn_del.clicked.connect(lambda _c, s=side, r=row: self._del_cond_row(s, r))
        row.addWidget(col_box, 2)
        row.addWidget(val_box, 2)
        row.addWidget(btn_del)
        box.addLayout(row)
        self._cond_rows[side].append({"layout": row, "col": col_box, "val": val_box})

    def _del_cond_row(self, side: str, row):
        rows = self._cond_rows[side]
        for i, entry in enumerate(rows):
            if entry["layout"] is row:
                while row.count():
                    item = row.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                box = self.cond_box_a if side == "a" else self.cond_box_b
                try:
                    box.removeItem(row)
                except Exception:
                    pass
                rows.pop(i)
                break
        if not rows:
            self._add_cond_row(side)

    def _reload_row_values(self, side: str, row):
        entry = next((e for e in self._cond_rows[side] if e["layout"] is row), None)
        if not entry:
            return
        col_box, val_box = entry["col"], entry["val"]
        keep = val_box.currentData()
        val_box.blockSignals(True)
        val_box.clear()
        val_box.addItem("— значение —", None)
        col = col_box.currentData()
        sheet = self._side_sheets()[side]
        if col and sheet:
            try:
                vals, truncated = align.column_values(
                    self.file_path, self.file_type, sheet, col)
            except Exception as e:
                notify(self, "warning", "Ошибка", str(e))
                vals, truncated = [], False
            from ui_compat import add_elided_item as _add3
            for x in sorted(set(vals))[:500]:
                _add3(val_box, x, x)
            if truncated:
                val_box.addItem("… (слишком много, сузь фильтр)", None)
        if keep:
            for i in range(val_box.count()):
                if val_box.itemData(i) == keep:
                    val_box.setCurrentIndex(i)
                    break
        val_box.blockSignals(False)

    def _current_filter(self):
        conds = self._filters().get("b") or []
        if conds:
            return conds[0]
        return None, None

    def _filters(self) -> dict:
        """Условия сторон: {'a': [(col, val)], 'b': [...]} (только заполненные)."""
        out = {}
        for side in ("a", "b"):
            conds = []
            for e in self._cond_rows[side]:
                col, val = e["col"].currentData(), e["val"].currentData()
                if col and val is not None:
                    conds.append((col, val))
            out[side] = conds
        return out

    def _reload_filter_columns(self):
        """Обновить списки колонок во всех строках (при смене листов)."""
        for side in ("a", "b"):
            headers = self._side_headers(side)
            for e in self._cond_rows[side]:
                keep_col, keep_val = e["col"].currentData(), e["val"].currentData()
                e["col"].blockSignals(True)
                e["col"].clear()
                e["col"].addItem("— колонка —", None)
                from ui_compat import add_elided_item as _add4
                for h in headers:
                    _add4(e["col"], h, h)
                for i in range(e["col"].count()):
                    if e["col"].itemData(i) == keep_col:
                        e["col"].setCurrentIndex(i)
                        break
                e["col"].blockSignals(False)
                self._reload_row_values(side, e["layout"])
                if keep_val:
                    for i in range(e["val"].count()):
                        if e["val"].itemData(i) == keep_val:
                            e["val"].setCurrentIndex(i)
                            break

    def _reset_filter(self):
        for side in ("a", "b"):
            box = self.cond_box_a if side == "a" else self.cond_box_b
            for e in list(self._cond_rows[side]):
                lay = e["layout"]
                while lay.count():
                    item = lay.takeAt(0)
                    if item.widget():
                        item.widget().deleteLater()
                try:
                    box.removeItem(lay)
                except Exception:
                    pass
            self._cond_rows[side] = []
            self._add_cond_row(side)
        self.filter_stats.setText("")
        self._compare()

    def _compare(self):
        a, b = self._sheets()
        if not a:
            return
        try:
            d = align.compare_sheets(self.file_path, self.file_type, a, b)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self._reload_filter_columns()
        filters = self._filters()
        try:
            sa = align.sheet_stats(self.file_path, self.file_type, a,
                                   filters["a"] or None)
            sb = align.sheet_stats(self.file_path, self.file_type, b,
                                   filters["b"] or None)
        except Exception as e:
            notify(self, "warning", "Статистика", str(e))
            sa = sb = None
        if sa and sb:
            self.filter_stats.setText(
                f"A «{a}»: {sa['filtered']}/{sa['total']} строк"
                f"{self._flt_txt(filters['a'])}{self._id_txt(sa)}  |  "
                f"B «{b}»: {sb['filtered']}/{sb['total']} строк"
                f"{self._flt_txt(filters['b'])}{self._id_txt(sb)}")
        else:
            self.filter_stats.setText("")
        self.result.clear()
        if d["same_order"]:
            self.result.addItem(QListWidgetItem("✅ Структура совпадает полностью"))
            return
        for h in d["missing_in_target"]:
            self.result.addItem(QListWidgetItem(f"➖ Нет в B: «{h}» (добавится пустой)"))
        for h in d["extra_in_target"]:
            self.result.addItem(QListWidgetItem(f"➕ Лишняя в B: «{h}»"))
        for m in d["moved"]:
            self.result.addItem(QListWidgetItem(
                f"↔ «{m['header']}»: в A позиция {m['ref_index'] + 1}, "
                f"в B позиция {m['target_index'] + 1}"))
        for n in d["role_notes"]:
            self.result.addItem(QListWidgetItem(
                f"🏷 Роль {n['role']}: A={n['ref'] or '—'}, B={n['target'] or '—'}"))

    @staticmethod
    def _id_txt(stats: dict) -> str:
        cov = stats.get("id_coverage") or {}
        if not cov:
            return ""
        return f", ID {cov['column']}: {cov['filled']}/{cov['total']}"

    @staticmethod
    def _flt_txt(conds) -> str:
        if not conds:
            return ""
        return " [фильтр " + ", ".join(f"{c}={v}" for c, v in conds) + "]"

    def _order(self):
        a, b = self._sheets()
        if not a:
            return
        if self.file_type != "excel":
            notify(self, "warning", "Внимание",
                   "Упорядочить можно только .xlsx (нужна запись)")
            return
        try:
            headers, rows = align.normalize_sheet(
                self.file_path, a, b, keep_extra=self.keep_extra.isChecked())
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self._ordered = (b, headers, rows)
        self.info.setText(f"Готово: лист B упорядочен ({len(rows)} строк, "
                          f"{len(headers)} колонок). Выгрузи лист или файл.")
        notify(self, "success", "Готово", "Порядок колонок — как в A")

    def _export(self, whole: bool):
        if not self._ordered:
            notify(self, "warning", "Внимание", "Сначала нажми «Упорядочить»")
            return
        if self.file_type != "excel":
            notify(self, "warning", "Внимание", "Выгрузка — только .xlsx")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить", f"ordered_{'file' if whole else 'sheet'}.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        sheet, headers, rows = self._ordered
        conds = (self._filters().get("b") or [])
        if self.export_filtered.isChecked() and conds:
            missing = [c for c, _ in conds if c not in headers]
            if missing:
                notify(self, "warning", "Фильтр",
                       f"Колонок {missing} нет в упорядоченном листе — выгружаю всё.")
            else:
                rows = align.filter_rows(headers, rows, conds)
        try:
            if whole:
                out = align.write_file_xlsx(self.file_path, path, sheet, headers, rows)
            else:
                out = align.write_sheet_xlsx(path, sheet, headers, rows)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        n = (f" ({len(rows)} строк)"
             if self.export_filtered.isChecked() and conds else "")
        notify(self, "success", "Сохранено", f"{out}{n}")
