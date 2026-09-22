"""Прогоны модели: список, создание, импорт ответов, сравнение A vs B."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QFileDialog, QFormLayout, QWidget,
    QScrollArea,
)
from PySide6.QtCore import Qt
from pathlib import Path
from file_reader import FileReader
from ui_base import BaseScreen
from ui_compat import (FComboBox, FLineEdit, FPrimaryButton, FPushButton,
                       clear_in_fluent, confirm, notify)
import model_run_service as runs


RUN_ROLES = [
    ("ignore", "Не импортировать"),
    ("answer", "Ответ модели"),
    ("source_id", "Идентификатор"),
    ("prompt", "Промпт / запрос"),
    ("product", "Продукт"),
]


def _guess_roles(headers: list) -> dict:
    """Совместимость: подбор ролей живёт в sheet_align_service."""
    from sheet_align_service import guess_roles
    return guess_roles(headers)


class RunMetaDialog(QDialog):
    """Метаданные нового прогона (ТЗ §51)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Новый прогон")
        self.setMinimumWidth(420)
        self.result_meta = None
        layout = QFormLayout()
        self.edits = {}
        for key, label in (("name", "Название *"), ("model_name", "Модель *"),
                           ("model_version", "Версия модели"),
                           ("prompt_version", "Версия промпта"),
                           ("description", "Описание")):
            ed = FLineEdit()
            self.edits[key] = ed
            layout.addRow(label, ed)
        btns = QHBoxLayout()
        ok = FPrimaryButton("Создать")
        ok.clicked.connect(self._on_ok)
        cancel = FPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addRow(btns)
        self.setLayout(layout)

    def _on_ok(self):
        meta = {k: e.text().strip() for k, e in self.edits.items()}
        if not meta["name"] or not meta["model_name"]:
            notify(self, "warning", "Ошибка", "Название и модель обязательны")
            return
        self.result_meta = meta
        self.accept()


def collect_run_metadata(row: dict, custom_map: dict) -> dict:
    """Метаданные ответа из custom-колонок: {колонка: категория} -> {категория: текст}.

    Несколько колонок одной категории склеиваются, как в импорте кейсов.
    """
    grouped: dict = {}
    for header, name in (custom_map or {}).items():
        v = row.get(header, "")
        if str(v or "").strip():
            grouped.setdefault(name, []).append(str(v).strip())
    return {k: "\n\n".join(v) for k, v in grouped.items()}


class RunImportDialog(QDialog):
    """Импорт ответов прогона из файла: файл + маппинг колонок."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Импорт ответов прогона")
        self.setMinimumSize(560, 480)
        self.reader = FileReader()
        self.file_path = None
        self.file_type = None
        self.sheet_name = None
        self.preview = None
        self.combos = {}
        self.result_rows = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout()
        file_row = QHBoxLayout()
        self.file_label = QLabel("Файл не выбран")
        btn = FPushButton("📂 Выбрать файл")
        btn.clicked.connect(self._select_file)
        file_row.addWidget(self.file_label)
        file_row.addWidget(btn)
        layout.addLayout(file_row)
        self.sheet_row = QHBoxLayout()
        self.sheet_row.addWidget(QLabel("Лист:"))
        self.sheet_combo = FComboBox()
        self.sheet_combo.currentIndexChanged.connect(self._reload_preview)
        self.sheet_row.addWidget(self.sheet_combo)
        layout.addLayout(self.sheet_row)
        hint = QLabel("Назначь роли колонкам: «Ответ модели» — не более "
                      "одной колонки (можно без неё — тогда размечаются сами "
                      "вопросы), «Идентификатор» и «Промпт» — для "
                      "сопоставления с кейсами, «Продукт» — подпись в сравнении. "
                      "Кнопка «+ Своя категория…» создаёт именованную категорию — "
                      "значение уйдёт в метаданные ответа под этим именем. "
                      "Роли подставляются сами "
                      "по названиям — проверь и жми «Импортировать».")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        custom_row = QHBoxLayout()
        btn_custom = FPushButton("+ Своя категория…")
        btn_custom.setToolTip("Именованная категория: значение уйдёт в метаданные ответа")
        btn_custom.clicked.connect(self.on_add_custom_role)
        custom_row.addWidget(btn_custom)
        btn_del_custom = FPushButton("－ Категория")
        btn_del_custom.setToolTip("Удалить свою категорию маппинга")
        btn_del_custom.clicked.connect(self.on_remove_custom_role)
        custom_row.addWidget(btn_del_custom)
        custom_row.addStretch()
        layout.addLayout(custom_row)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.map_host = QWidget()
        self.map_layout = QFormLayout()
        self.map_host.setLayout(self.map_layout)
        scroll.setWidget(self.map_host)
        clear_in_fluent(scroll)
        layout.addWidget(scroll)
        btns = QHBoxLayout()
        ok = FPrimaryButton("🚀 Импортировать")
        ok.clicked.connect(self._on_import)
        cancel = FPushButton("Отмена")
        cancel.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        cmp_row = QHBoxLayout()
        btn_cmp = FPushButton("⇄ Сравнить листы / упорядочить")
        btn_cmp.setToolTip("Структура листов относительно друг друга + выгрузка")
        btn_cmp.clicked.connect(self._open_sheet_compare)
        cmp_row.addWidget(btn_cmp)
        cmp_row.addStretch()
        layout.addLayout(cmp_row)
        self.setLayout(layout)

    def _select_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Файл с ответами", "",
            "Таблицы (*.xlsx *.ods *.csv *.json *.jsonl);;Все файлы (*.*)")
        if not path:
            return
        try:
            ftype = self.reader.detect_file_type(path)
        except ValueError as e:
            notify(self, "warning", "Формат", str(e))
            return
        self.file_path = path
        self.file_type = ftype
        self.file_label.setText(Path(path).name)
        try:
            if ftype in ("excel", "ods"):
                if ftype == "excel":
                    sheets = self.reader.read_excel_sheets(path)
                else:
                    sheets = self.reader.read_ods_sheets(path)
                self.sheet_combo.clear()
                self.sheet_combo.addItems(sheets)
                self.sheet_name = sheets[0] if sheets else None
            self._reload_preview()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _reload_preview(self):
        if not self.file_path:
            return
        try:
            if self.file_type in ("excel", "ods"):
                self.sheet_name = self.sheet_combo.currentText() or None
                if self.file_type == "excel":
                    self.preview = self.reader.read_excel_preview(
                        self.file_path, self.sheet_name, max_rows=50)
                else:
                    self.preview = self.reader.read_ods_preview(
                        self.file_path, self.sheet_name, max_rows=50)
            elif self.file_type == "csv":
                self.preview = self.reader.read_csv_preview(
                    self.file_path, max_rows=50)
            elif self.file_type == "json":
                self.preview = self.reader.read_json_preview(
                    self.file_path, max_rows=50)
            elif self.file_type == "jsonl":
                self.preview = self.reader.read_jsonl_preview(
                    self.file_path, max_rows=50)
            self._build_mapping()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _build_mapping(self):
        from mapping_custom import custom_roles, reapply_mapping
        saved = {h: c.currentData() for h, c in self.combos.items()}
        while self.map_layout.count():
            item = self.map_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.combos.clear()
        headers = (self.preview or {}).get("headers", [])
        rows = (self.preview or {}).get("rows", []) or []
        roles = list(RUN_ROLES) + custom_roles(self.project_path)
        restored = reapply_mapping(headers, roles, saved)
        guessed = _guess_roles(headers)
        for idx, header in enumerate(headers):
            samples = []
            for r in rows:
                try:
                    v = str(r[idx] if idx < len(r) else "").strip()
                except Exception:
                    v = ""
                if v and v not in samples:
                    samples.append(v[:60])
                if len(samples) >= 2:
                    break
            from ui_compat import mapping_label
            left = QLabel(mapping_label(header, samples))
            # Длинные названия/примеры разъезжают диалог шире экрана —
            # переносим и ограничиваем ширину метки.
            left.setWordWrap(True)
            left.setMaximumWidth(420)
            try:
                from PySide6.QtCore import Qt as _Qt
                left.setTextFormat(_Qt.TextFormat.RichText)
            except Exception:
                pass
            combo = FComboBox()
            for code, name in roles:
                combo.addItem(name, code)
            want = restored.get(header) or guessed.get(header)
            if want:
                for i in range(combo.count()):
                    if combo.itemData(i) == want:
                        combo.setCurrentIndex(i)
                        break
            self.map_layout.addRow(left, combo)
            self.combos[header] = combo

    def on_add_custom_role(self):
        from PySide6.QtWidgets import QInputDialog
        from mapping_custom import add_custom_category
        name, ok = QInputDialog.getText(
            self, "Своя категория",
            "Название категории (попадёт в метаданные ответа):")
        if not ok:
            return
        try:
            add_custom_category(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._build_mapping()
        notify(self, "success", "Категория",
               f"Категория «{str(name).strip()}» добавлена — выбери её в нужных колонках")

    def on_remove_custom_role(self):
        from PySide6.QtWidgets import QInputDialog
        from mapping_custom import load_custom_categories, remove_custom_category
        names = load_custom_categories(self.project_path)
        if not names:
            notify(self, "warning", "Внимание", "Своих категорий пока нет")
            return
        name, ok = QInputDialog.getItem(
            self, "Удалить категорию", "Категория:", names, 0, False)
        if not ok or not name:
            return
        try:
            remove_custom_category(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._build_mapping()
        notify(self, "success", "Категория", f"«{name}» удалена")

    def _mapping(self) -> dict:
        return {h: c.currentData() for h, c in self.combos.items()}

    def _open_sheet_compare(self):
        if not self.file_path:
            notify(self, "warning", "Внимание", "Сначала выбери файл")
            return
        from sheet_compare_dialog import SheetCompareDialog
        SheetCompareDialog(self.file_path, self).exec()
        # После упорядочивания превью могло устареть — обновляем.
        try:
            self._reload_preview()
        except Exception:
            pass

    def _on_import(self):
        if not self.file_path or not self.preview:
            notify(self, "warning", "Внимание", "Сначала выбери файл")
            return
        mapping = self._mapping()
        answers = [h for h, r in mapping.items() if r == "answer"]
        if len(answers) > 1:
            notify(self, "warning", "Маппинг",
                   "Роль «Ответ модели» должна быть только у одной колонки "
                   f"(сейчас: {len(answers)}). Лишние переключи на «Не импортировать».")
            return
        try:
            if self.file_type == "excel":
                data = self.reader.read_excel_data(
                    self.file_path, self.sheet_name, header_row=0)
            elif self.file_type == "ods":
                data = self.reader.read_ods_data(
                    self.file_path, self.sheet_name, header_row=0)
            elif self.file_type == "csv":
                data = self.reader.read_csv_data(self.file_path)
            elif self.file_type == "json":
                data, _err = self.reader.read_json_data(self.file_path)
            elif self.file_type == "jsonl":
                data, _err = self.reader.read_jsonl_data(self.file_path)
            else:
                return
        except Exception as e:
            notify(self, "error", "Ошибка чтения", str(e))
            return
        cols = {}
        if answers:
            cols["answer"] = answers[0]
        for h, r in mapping.items():
            if r in ("source_id", "prompt", "product") and r not in cols:
                cols[r] = h
        custom_map = {}
        for h, r in mapping.items():
            if isinstance(r, str) and r.startswith("custom:"):
                custom_map[h] = r.split(":", 1)[1].strip()
        rows = []
        for row in data:
            if not isinstance(row, dict):
                continue
            rows.append({
                "answer": row.get(cols["answer"], "") if "answer" in cols else "",
                "source_id": row.get(cols["source_id"], "") if "source_id" in cols else "",
                "prompt": row.get(cols["prompt"], "") if "prompt" in cols else "",
                "product": row.get(cols["product"], "") if "product" in cols else "",
                "metadata": collect_run_metadata(row, custom_map),
            })
        if not rows:
            notify(self, "warning", "Внимание", "Нет строк для импорта")
            return
        self.result_rows = rows
        self.accept()


class ModelRunsScreen(BaseScreen):
    """Экран прогонов модели (ТЗ §45-53)."""

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._run_id = None
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("🏃 ПРОГОНЫ МОДЕЛИ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Прогон = ответы одной версии модели (/оператора/эталона). "
                      "Импортируй ответы → сопоставление с кейсами идёт по ID, "
                      "иначе по тексту промпта. Сравнение — кнопкой «⇄ Сравнить».")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.runs_list = QListWidget()
        from PySide6.QtWidgets import QAbstractItemView as _AIV
        self.runs_list.setSelectionMode(
            _AIV.SelectionMode.ExtendedSelection)
        self.runs_list.setToolTip("Множественный выбор: Ctrl+клик, Shift+клик")
        self.runs_list.currentRowChanged.connect(self._on_run_selected)
        layout.addWidget(self.runs_list, 2)
        row = QHBoxLayout()
        btn_new = FPrimaryButton("＋ Прогон")
        btn_new.clicked.connect(self._new_run)
        btn_import = FPushButton("📥 Импортировать ответы")
        btn_import.clicked.connect(self._import_answers)
        btn_review = FPushButton("📝 Разметить ответы")
        btn_review.clicked.connect(self._review_answers)
        btn_del = FPushButton("🗑 Удалить")
        btn_del.clicked.connect(self._delete_run)
        row.addWidget(btn_new)
        row.addWidget(btn_import)
        row.addWidget(btn_review)
        row.addWidget(btn_del)
        layout.addLayout(row)
        self.detail = QLabel("Выбери прогон")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        cmp_row = QHBoxLayout()
        cmp_row.addWidget(QLabel("Сравнить с:"))
        self.combo_b = FComboBox()
        cmp_row.addWidget(self.combo_b)
        btn_cmp = FPushButton("⇄ Сравнить")
        btn_cmp.clicked.connect(self._compare)
        cmp_row.addWidget(btn_cmp)
        btn_sheets = FPushButton("⇄ Листы файла")
        btn_sheets.setToolTip("Структура листов xlsx/ods: сравнить, упорядочить, выгрузить")
        btn_sheets.clicked.connect(self._compare_sheets)
        cmp_row.addWidget(btn_sheets)
        btn_reg = FPushButton("🧪 Регрессия")
        btn_reg.setToolTip("Baseline vs кандидат: матрица, gate PASS/FAIL, экспорт")
        btn_reg.clicked.connect(self._regression)
        cmp_row.addWidget(btn_reg)
        layout.addLayout(cmp_row)
        sheet_row = QHBoxLayout()
        btn_sheets = FPushButton("⇄ Листы файла: сравнить / упорядочить")
        btn_sheets.setToolTip("Структура листов xlsx/ods относительно друг друга")
        btn_sheets.clicked.connect(self._sheet_compare)
        sheet_row.addWidget(btn_sheets)
        sheet_row.addStretch()
        layout.addLayout(sheet_row)
        self.setLayout(layout)

    def refresh(self):
        try:
            items = runs.list_runs(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            items = []
        self._items = {r["run_id"]: r for r in items}
        cur = self._run_id
        self.runs_list.clear()
        for r in items:
            item = QListWidgetItem(
                f"{r['name']} — {r['model_name']} {r['model_version'] or ''} "
                f"({r['answers']} отв.)")
            item.setData(Qt.ItemDataRole.UserRole, r["run_id"])
            self.runs_list.addItem(item)
        self.combo_b.clear()
        for r in items:
            self.combo_b.addItem(f"{r['name']} ({r['model_name']})", r["run_id"])
        if cur in self._items:
            for i in range(self.runs_list.count()):
                if self.runs_list.item(i).data(Qt.ItemDataRole.UserRole) == cur:
                    self.runs_list.setCurrentRow(i)
                    break
        elif self.runs_list.count():
            self.runs_list.setCurrentRow(0)
        else:
            self._run_id = None
            self.detail.setText("Прогонов пока нет — нажми «＋ Прогон».")

    def _on_run_selected(self):
        item = self.runs_list.currentItem()
        self._run_id = item.data(Qt.ItemDataRole.UserRole) if item else None
        if self._run_id is None:
            return
        try:
            answers = runs.list_answers(self.project_path, self._run_id)
        except Exception as e:
            self.detail.setText(f"Ошибка: {e}")
            return
        matched = sum(1 for a in answers if a["case_id"])
        self.detail.setText(
            f"Ответов: {len(answers)}, сопоставлено с кейсами: {matched}, "
            f"новых: {len(answers) - matched}.")

    def _new_run(self):
        dlg = RunMetaDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_meta:
            return
        m = dlg.result_meta
        try:
            rid = runs.create_run(self.project_path, m["name"], m["model_name"],
                                  model_version=m.get("model_version", ""),
                                  prompt_version=m.get("prompt_version", ""),
                                  description=m.get("description", ""))
            self._run_id = rid
            self.refresh()
            notify(self, "success", "Прогон", "Прогон создан — импортируй ответы")
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _import_answers(self):
        if self._run_id is None:
            notify(self, "warning", "Внимание", "Сначала выбери прогон")
            return
        dlg = RunImportDialog(self.project_path, self)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_rows:
            return
        try:
            prev = (runs.get_run(self.project_path, self._run_id) or {}).get(
                "source_file") or ""
            if prev and prev == (dlg.file_path or ""):
                if not confirm(self, "Повторный импорт",
                               "Этот файл уже импортировался в данный прогон. "
                               "Повтор перезапишет совпавшие ответы.\n\nПродолжить?",
                               ok_text="Импортировать", cancel_text="Остановить"):
                    return
        except Exception:
            pass
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Импорт ответов…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)
        rows = dlg.result_rows
        run_id = self._run_id

        def _work_outer():
            from workers import run_in_background as _run
            holder: dict = {}

            def _progress(done, total):
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(
                        int(done / total * 100) if total else 0)

            worker = _run(runs.import_run_rows, self.project_path, run_id, rows,
                          progress_callback=_progress, cancel_event=cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_import_done)
            worker.signals.error.connect(_import_error)

        def _import_done(res):
            try:
                progress.close()
            except Exception:
                pass
            msg = (f"Всего: {res['total']}, сопоставлено: {res['matched']}, "
                   f"новых: {res['new']}")
            if res["dups"]:
                msg += f"\n⚠ Дублей ключа в файле: {res['dups']} (взят первый)."
            if res["no_key"]:
                msg += (f"\n⚠ Без ID и промпта: {res['no_key']} — сопоставить "
                        "нельзя (ТЗ §53).")
            notify(self, "success", "Импорт ответов", msg)
            try:
                runs_list = runs.get_run(self.project_path, run_id)
                if runs_list:
                    from database import db as _db
                    with _db(self.project_path) as conn:
                        conn.cursor().execute(
                            "UPDATE model_runs SET source_file=? WHERE run_id=?",
                            (dlg.file_path or "", run_id))
            except Exception:
                pass
            self.refresh()

        def _import_error(msg):
            try:
                progress.close()
            except Exception:
                pass
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Импорт", str(msg))
                self.refresh()
            else:
                notify(self, "error", "Ошибка импорта", str(msg))

        QTimer.singleShot(0, _work_outer)

    def _delete_run(self):
        """Удаляет выделенные прогоны (или текущий, если выделения нет)."""
        from PySide6.QtCore import Qt as _Qt
        ids = []
        try:
            for it in self.runs_list.selectedItems():
                rid = it.data(_Qt.ItemDataRole.UserRole)
                if rid and rid not in ids:
                    ids.append(rid)
        except Exception:
            ids = []
        if not ids:
            if self._run_id is None:
                return
            ids = [self._run_id]
        if not confirm(self, "Подтверждение",
                       f"Удалить прогонов: {len(ids)} "
                       "(вместе с ответами/разметкой)?"):
            return
        errs = 0
        for rid in ids:
            try:
                runs.delete_run(self.project_path, rid)
            except ValueError:
                errs += 1
        self._run_id = None
        self.refresh()
        if errs:
            notify(self, "warning", "Удаление",
                   f"Не удалено: {errs} (уже нет?).")

    def _compare(self):
        if self._run_id is None:
            notify(self, "warning", "Внимание", "Выбери прогон A слева")
            return
        run_b = self.combo_b.currentData()
        if not run_b or run_b == self._run_id:
            notify(self, "warning", "Внимание", "Выбери другой прогон B")
            return
        from compare_dialog import CompareDialog
        CompareDialog(self.project_path, self._run_id, run_b, self).exec()

    def _compare_sheets(self):
        """Сравнение листов прямо с экрана: Прогоны → «⇄ Листы файла»."""
        from PySide6.QtWidgets import QFileDialog as _FD
        path, _ = _FD.getOpenFileName(
            self, "Файл с листами", "",
            "Таблицы (*.xlsx *.ods);;Все файлы (*.*)")
        if not path:
            return
        from sheet_compare_dialog import SheetCompareDialog
        SheetCompareDialog(path, self).exec()

    def _review_answers(self):
        if self._run_id is None:
            notify(self, "warning", "Внимание", "Сначала выбери прогон")
            return
        from run_review_dialog import RunReviewDialog
        RunReviewDialog(self.project_path, self._run_id, self).exec()
        self._on_run_selected()

    def _regression(self):
        from regression_dialog import RegressionDialog
        RegressionDialog(self.project_path, self).exec()

    def _sheet_compare(self):
        from PySide6.QtWidgets import QFileDialog as _QFD
        path, _ = _QFD.getOpenFileName(
            self, "Файл с листами", "",
            "Таблицы (*.xlsx *.ods);;Все файлы (*.*)")
        if not path:
            return
        from sheet_compare_dialog import SheetCompareDialog
        SheetCompareDialog(path, self).exec()
