"""Датасеты: список, версии, freeze, сравнение A vs B."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QInputDialog,
)
from PySide6.QtCore import Qt
from dataset_service import (
    compare_versions, create_dataset, create_version, delete_version,
    freeze_version, list_datasets, list_versions, set_dataset_locked,
)
from ui_compat import FComboBox, FPrimaryButton, FPushButton, clear_in_fluent, notify


class DatasetsDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Датасеты")
        self.setMinimumSize(680, 520)
        self._init_ui()
        self.reload_datasets()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("Датасеты и версии")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        how = QLabel(
            "Как это работает: 1) разметь кейсы в «Ревью» → "
            "2) «＋ Версия» снимает слепок статусов → "
            "3) «❄ Freeze» фиксирует эталон → "
            "4) размечай дальше и жми «⇄ Сравнить», чтобы увидеть, что изменилось.")
        how.setWordWrap(True)
        layout.addWidget(how)

        top = QHBoxLayout()
        left = QVBoxLayout()
        left.addWidget(QLabel("Датасеты:"))
        self.ds_list = QListWidget()
        self.ds_list.currentRowChanged.connect(self._on_dataset_selected)
        left.addWidget(self.ds_list)
        row_ds = QHBoxLayout()
        btn_new_ds = FPrimaryButton("＋ Датасет")
        btn_new_ds.clicked.connect(self._new_dataset)
        row_ds.addWidget(btn_new_ds)
        btn_lock = FPushButton("🔒")
        btn_lock.setMaximumWidth(44)
        btn_lock.setToolTip("Запереть/отпереть датасет: запертый не даёт "
                            "создавать и удалять версии")
        btn_lock.clicked.connect(self._toggle_lock)
        row_ds.addWidget(btn_lock)
        left.addLayout(row_ds)
        top.addLayout(left, 2)

        right = QVBoxLayout()
        right.addWidget(QLabel("Версии (снимок статусов):"))
        self.ver_list = QListWidget()
        right.addWidget(self.ver_list)
        row_ver = QHBoxLayout()
        self.file_combo = FComboBox()
        self.file_combo.setToolTip("Чей слепок снимать: весь проект или один файл")
        btn_new_ver = FPushButton("＋ Версия")
        btn_new_ver.setToolTip("Снимок текущих статусов выбранного состава")
        btn_new_ver.clicked.connect(self._new_version)
        btn_freeze = FPushButton("❄ Freeze")
        btn_freeze.clicked.connect(self._freeze)
        btn_del_ver = FPushButton("🗑")
        btn_del_ver.setMaximumWidth(44)
        btn_del_ver.setToolTip("Удалить выбранную версию (снимок)")
        btn_del_ver.clicked.connect(self._delete_version)
        row_ver.addWidget(self.file_combo)
        row_ver.addWidget(btn_new_ver)
        row_ver.addWidget(btn_freeze)
        row_ver.addWidget(btn_del_ver)
        right.addLayout(row_ver)

        cmp_row = QHBoxLayout()
        self.combo_a = FComboBox()
        self.combo_b = FComboBox()
        btn_cmp = FPushButton("⇄ Сравнить")
        btn_cmp.clicked.connect(self._compare)
        cmp_row.addWidget(QLabel("A:"))
        cmp_row.addWidget(self.combo_a)
        cmp_row.addWidget(QLabel("B:"))
        cmp_row.addWidget(self.combo_b)
        cmp_row.addWidget(btn_cmp)
        right.addLayout(cmp_row)
        top.addLayout(right, 3)
        layout.addLayout(top)

        self.cmp_result = QLabel("Выбери две версии и нажми «Сравнить».")
        self.cmp_result.setWordWrap(True)
        layout.addWidget(self.cmp_result)
        self.cmp_details = QListWidget()
        self.cmp_details.setMaximumHeight(140)
        layout.addWidget(self.cmp_details)
        clear_in_fluent(self.cmp_details)

        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        self.setLayout(layout)

    def _current_ds(self) -> int | None:
        item = self.ds_list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def reload_datasets(self):
        try:
            datasets = list_datasets(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось загрузить датасеты:\n{e}")
            datasets = []
        self.ds_list.clear()
        for ds in datasets:
            mark = " 🔒" if ds.get("locked") else ""
            item = QListWidgetItem(f"{ds['name']} [{ds['dataset_type']}] "
                                   f"({ds['versions']} верс.){mark}")
            item.setData(Qt.ItemDataRole.UserRole, ds["dataset_id"])
            self.ds_list.addItem(item)
        if self.ds_list.count():
            self.ds_list.setCurrentRow(0)
        else:
            self.ver_list.clear()
            self.cmp_result.setText("Датасетов пока нет — нажми «＋ Датасет».")

    def _on_dataset_selected(self):
        ds_id = self._current_ds()
        if ds_id is None:
            return
        try:
            versions = list_versions(self.project_path, ds_id)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            versions = []
        self._reload_files()
        self.ver_list.clear()
        self.combo_a.clear()
        self.combo_b.clear()
        for v in versions:
            st = v["status"]
            from dataset_service import VERSION_STATUS_NAMES
            text = (f"v{v['version_number']} "
                    f"[{VERSION_STATUS_NAMES.get(st, st)}] ({v['case_count']})")
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, v["version_id"])
            self.ver_list.addItem(item)
            self.combo_a.addItem(text, v["version_id"])
            self.combo_b.addItem(text, v["version_id"])
        if self.combo_b.count() > 1:
            self.combo_b.setCurrentIndex(1)
        if not versions:
            self.cmp_result.setText("Версий пока нет — разметь кейсы в «Ревью» "
                                    "и нажми «＋ Версия».")

    def _new_dataset(self):
        name, ok = QInputDialog.getText(self, "Новый датасет", "Название:")
        if not ok or not (name or "").strip():
            return
        dtype, ok2 = QInputDialog.getItem(
            self, "Тип", "Тип датасета:",
            ["working", "golden", "test", "safety", "archive"], 0, False)
        if not ok2:
            return
        try:
            create_dataset(self.project_path, name.strip(), "", dtype)
            self.reload_datasets()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _toggle_lock(self):
        ds_id = self._current_ds()
        if ds_id is None:
            notify(self, "warning", "Внимание", "Сначала выбери датасет слева")
            return
        try:
            cur = next(d for d in list_datasets(self.project_path)
                       if d["dataset_id"] == ds_id)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        locked = bool(cur.get("locked"))
        from ui_compat import confirm
        action = "Отпереть" if locked else "Запереть"
        if not confirm(self, f"{action} датасет",
                       f"{action} «{cur['name']}»? Запертый датасет не даёт "
                       "создавать и удалять версии (freeze разрешён).",
                       ok_text=action, cancel_text="Отмена"):
            return
        try:
            set_dataset_locked(self.project_path, ds_id, not locked)
            notify(self, "success", "Датасет",
                   f"«{cur['name']}» {'заперт' if not locked else 'отперт'}")
            self.reload_datasets()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _reload_files(self):
        from database import db as _db
        try:
            with _db(self.project_path) as conn:
                files = conn.cursor().execute(
                    "SELECT file_id, file_name FROM files ORDER BY imported_at").fetchall()
        except Exception:
            files = []
        self.file_combo.blockSignals(True)
        self.file_combo.clear()
        self.file_combo.addItem("Весь проект", None)
        for f in files:
            self.file_combo.addItem(f["file_name"], f["file_id"])
        self.file_combo.blockSignals(False)

    def _new_version(self):
        ds_id = self._current_ds()
        if ds_id is None:
            notify(self, "warning", "Внимание", "Сначала выбери датасет слева")
            return
        file_id = self.file_combo.currentData()
        scope = "весь проект" if file_id is None else f"файл «{self.file_combo.currentText()}»"
        from database import db as _db
        try:
            with _db(self.project_path) as conn:
                if file_id is None:
                    total = conn.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
                else:
                    total = conn.execute("SELECT COUNT(*) AS c FROM cases WHERE file_id=?",
                                         (file_id,)).fetchone()["c"]
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        if total == 0:
            notify(self, "warning", "Внимание",
                   "Кейсов нет — сначала импортируй файл")
            return
        from ui_compat import confirm
        if not confirm(self, "Новая версия",
                       f"Снять слепок текущих статусов ({total}, {scope})?"):
            return
        desc, ok = QInputDialog.getText(self, "Новая версия", "Описание (необязательно):")
        if not ok:
            return
        try:
            vid = create_version(self.project_path, ds_id, None, desc or "",
                                 file_id=file_id)
            versions = list_versions(self.project_path, ds_id)
            num = next(v["version_number"] for v in versions if v["version_id"] == vid)
            notify(self, "success", "Версия", f"Снимок v{num} создан")
            self._on_dataset_selected()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _freeze(self):
        item = self.ver_list.currentItem()
        if not item:
            notify(self, "warning", "Внимание", "Выбери версию")
            return
        from ui_compat import confirm
        if not confirm(self, "Freeze",
                       "Заморозить версию? Это необратимо: правки пойдут "
                       "только в новую версию.\nСтраховой бэкап проекта "
                       "создастся автоматически.",
                       ok_text="Заморозить", cancel_text="Отмена"):
            return
        try:
            freeze_version(self.project_path, item.data(Qt.ItemDataRole.UserRole))
            notify(self, "success", "Freeze", "Версия заморожена (неизменяема)")
            self._on_dataset_selected()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _delete_version(self):
        item = self.ver_list.currentItem()
        if not item:
            notify(self, "warning", "Внимание", "Выбери версию")
            return
        from ui_compat import confirm
        if not confirm(self, "Удалить версию",
                       "Удалить снимок версии? Датасет останется, разметка "
                       "кейсов не пострадает (удаляется только снимок).",
                       ok_text="Удалить", cancel_text="Отмена"):
            return
        try:
            delete_version(self.project_path, item.data(Qt.ItemDataRole.UserRole))
            notify(self, "success", "Версия", "Снимок удалён")
            self._on_dataset_selected()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _compare(self):
        va, vb = self.combo_a.currentData(), self.combo_b.currentData()
        if not va or not vb:
            return
        try:
            res = compare_versions(self.project_path, va, vb)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        c = res["counts"]
        from dataset_service import version_agreement
        try:
            agr = version_agreement(self.project_path, res)
            agree_line = (f"\n🤝 Согласие разметки: {agr['pct']:.0%} "
                          f"({agr['agreed']}/{agr['matched']}, "
                          f"в т.ч. со сменой вердикта: {agr['verdict_changed']})"
                          if agr["pct"] is not None else
                          "\n🤝 Согласие разметки: нет общих ключей")
        except Exception:
            agree_line = ""
        self.cmp_result.setText(
            f"A vs B (по source_id/хэшу): добавлено {c['added']}, "
            f"удалено {c['removed']}, изменено {c['changed']}, "
            f"без изменений {c['unchanged']}, конфликтов {c['conflicted']}."
            f"{agree_line}")
        self.cmp_details.clear()
        for d in res["details"][:200]:
            ch = ",".join(d.get("changes", []) or [])
            extra = f" [{ch}]" if ch else ""
            self.cmp_details.addItem(
                f"кейс {d['case_id']}: {d['before']} → {d['after']}{extra}")
        for cf in res.get("conflicted", [])[:50]:
            self.cmp_details.addItem(
                f"⚠ ключ {cf['key']}: дубли в A{cf['a_cases']} / B{cf['b_cases']}")
        rest = len(res["details"]) - 200
        if rest > 0:
            self.cmp_details.addItem(f"… и ещё {rest}")
