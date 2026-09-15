"""Редактор профилей ревью: схема статусов, хоткеи, обязательные поля."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QTableWidget, QInputDialog, QHeaderView,
)
from PySide6.QtCore import Qt
from review_profile_service import (
    create_profile, delete_profile, get_profile, list_profiles,
    update_profile, validate_config,
)
from ui_compat import FCheckBox, FComboBox, FLineEdit, FPrimaryButton, FPushButton, notify


class ProfileDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Профили ревью")
        self.setMinimumSize(640, 520)
        self._current_id = None
        self._status_rows = []  # [{code, name_edit, hot_edit, check}]
        self._init_ui()
        self.reload_profiles()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("Профили ревью")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        top = QHBoxLayout()
        self.profiles_list = QListWidget()
        self.profiles_list.setMaximumWidth(220)
        self.profiles_list.currentRowChanged.connect(self._on_profile_selected)
        top.addWidget(self.profiles_list)

        right = QVBoxLayout()
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Название:"))
        self.name_edit = FLineEdit()
        name_row.addWidget(self.name_edit)
        right.addLayout(name_row)
        right.addWidget(QLabel("Статусы (вкл, имя, хоткей):"))
        self.status_table = QTableWidget()
        self.status_table.setColumnCount(3)
        self.status_table.setHorizontalHeaderLabels(["Вкл", "Название", "Клавиша"])
        self.status_table.setColumnWidth(0, 60)
        self.status_table.setColumnWidth(2, 90)
        self.status_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        # Строки выше редакторов: текст не вылезает и не съезжает
        self.status_table.verticalHeader().setDefaultSectionSize(40)
        right.addWidget(self.status_table)

        self.req_cat = FCheckBox("Причина обязательна для «Плохо»")
        right.addWidget(self.req_cat)
        comment_row = QHBoxLayout()
        comment_row.addWidget(QLabel("Комментарий для «Плохо»:"))
        self.req_comment = FComboBox()
        self.req_comment.addItem("Из настроек проекта", None)
        self.req_comment.addItem("Не обязателен", "none")
        self.req_comment.addItem("Мягкое предупреждение", "warn")
        self.req_comment.addItem("Обязателен", "required")
        comment_row.addWidget(self.req_comment)
        right.addLayout(comment_row)
        top.addLayout(right)
        layout.addLayout(top)

        row1 = QHBoxLayout()
        btn_new = FPrimaryButton("＋ Новый")
        btn_new.clicked.connect(self._create)
        btn_save = FPushButton("💾 Сохранить")
        btn_save.clicked.connect(self._save)
        btn_delete = FPushButton("🗑 Удалить")
        btn_delete.clicked.connect(self._delete)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        row1.addWidget(btn_new)
        row1.addWidget(btn_save)
        row1.addWidget(btn_delete)
        row1.addStretch()
        row1.addWidget(btn_close)
        layout.addLayout(row1)
        self.setLayout(layout)

    def reload_profiles(self):
        try:
            profiles = list_profiles(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось загрузить профили:\n{e}")
            profiles = []
        self.profiles_list.clear()
        for p in profiles:
            label = f"{'⭐ ' if p['is_default'] else ''}{p['name']}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, p["profile_id"])
            self.profiles_list.addItem(item)
        if self.profiles_list.count():
            self.profiles_list.setCurrentRow(0)

    def _on_profile_selected(self):
        item = self.profiles_list.currentItem()
        if not item:
            return
        pid = item.data(Qt.ItemDataRole.UserRole)
        try:
            prof = get_profile(self.project_path, pid)
        except Exception:
            prof = None
        if not prof:
            return
        self._current_id = pid
        self.name_edit.setText(prof["name"])
        cfg = prof["config"]
        self._status_rows = []
        self.status_table.setRowCount(len(cfg.get("statuses", [])))
        for row, s in enumerate(cfg.get("statuses", [])):
            check = FCheckBox()
            check.setChecked(bool(s.get("enabled", True)))
            self.status_table.setCellWidget(row, 0, self._centered(check))
            name_edit = FLineEdit()
            name_edit.setText(s.get("name", ""))
            self.status_table.setCellWidget(row, 1, name_edit)
            hot_edit = FLineEdit()
            hot_edit.setText(s.get("hotkey", ""))
            hot_edit.setMaxLength(1)
            self.status_table.setCellWidget(row, 2, hot_edit)
            self._status_rows.append({"code": s["code"], "check": check,
                                      "name": name_edit, "hot": hot_edit})
        self.req_cat.setChecked(bool(cfg.get("require_category_for_bad", False)))
        mode = cfg.get("require_comment_for_bad", None)
        for i in range(self.req_comment.count()):
            if self.req_comment.itemData(i) == mode:
                self.req_comment.setCurrentIndex(i)
                break

    @staticmethod
    def _centered(widget):
        from PySide6.QtWidgets import QWidget, QHBoxLayout
        wrap = QWidget()
        lay = QHBoxLayout(wrap)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(widget)
        return wrap

    def _collect_config(self) -> dict:
        statuses = []
        for r in self._status_rows:
            statuses.append({"code": r["code"], "name": r["name"].text(),
                             "hotkey": r["hot"].text(),
                             "enabled": r["check"].isChecked()})
        return {"statuses": statuses,
                "require_category_for_bad": self.req_cat.isChecked(),
                "require_comment_for_bad": self.req_comment.currentData()}

    def _create(self):
        name, ok = QInputDialog.getText(self, "Новый профиль", "Название:")
        if not ok or not (name or "").strip():
            return
        try:
            create_profile(self.project_path, name.strip())
            self.reload_profiles()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _save(self):
        if self._current_id is None:
            return
        try:
            cfg = validate_config(self._collect_config())
            update_profile(self.project_path, self._current_id,
                           self.name_edit.text(), cfg)
            notify(self, "success", "Профиль", "Сохранено")
            self.reload_profiles()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _delete(self):
        if self._current_id is None:
            return
        from ui_compat import confirm
        if not confirm(self, "Подтверждение", "Удалить профиль?"):
            return
        try:
            delete_profile(self.project_path, self._current_id)
            self._current_id = None
            self.reload_profiles()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
