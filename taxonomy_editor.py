"""Редактор таксономии ошибок: дерево, свои категории, архив, удаление."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTreeWidget,
    QTreeWidgetItem, QInputDialog,
)
from PySide6.QtCore import Qt
from taxonomy_service import (
    archive_category, create_category, delete_category, list_categories,
    rename_category, set_category_active,
)
from ui_compat import FPrimaryButton, FPushButton, clear_in_fluent, confirm, notify


class TaxonomyDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Таксономия ошибок")
        self.setMinimumSize(560, 480)
        self._init_ui()
        self.reload()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("Категории и подкатегории ошибок")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        hint = QLabel("Архив прячет категорию из выбора, но сохраняет старую разметку.")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Название", "Кейсов", "Состояние"])
        self.tree.setColumnWidth(0, 300)
        layout.addWidget(self.tree)
        clear_in_fluent(self.tree)

        row1 = QHBoxLayout()
        btn_add_cat = FPrimaryButton("＋ Категория")
        btn_add_cat.clicked.connect(self._add_category)
        btn_add_sub = FPushButton("＋ Подкатегория")
        btn_add_sub.clicked.connect(self._add_subcategory)
        btn_rename = FPushButton("✏ Переименовать")
        btn_rename.clicked.connect(self._rename)
        row1.addWidget(btn_add_cat)
        row1.addWidget(btn_add_sub)
        row1.addWidget(btn_rename)
        layout.addLayout(row1)

        row2 = QHBoxLayout()
        btn_toggle = FPushButton("📦 Архив / вернуть")
        btn_toggle.clicked.connect(self._toggle_archive)
        btn_delete = FPushButton("🗑 Удалить")
        btn_delete.clicked.connect(self._delete)
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        row2.addWidget(btn_toggle)
        row2.addWidget(btn_delete)
        row2.addStretch()
        row2.addWidget(btn_close)
        layout.addLayout(row2)
        self.setLayout(layout)

    def reload(self):
        try:
            cats = list_categories(self.project_path, include_archived=True)
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось загрузить таксономию:\n{e}")
            cats = []
        self.tree.clear()
        try:
            from taxonomy_service import usage_count as _usage
        except Exception:
            _usage = None
        for cat in cats:
            n = _usage(self.project_path, cat["category_id"]) if _usage else 0
            top = QTreeWidgetItem([cat["name"], str(n),
                                   "" if cat["is_active"] else "архив"])
            top.setData(0, Qt.ItemDataRole.UserRole, cat["category_id"])
            if not cat["is_active"]:
                top.setDisabled(True)
            for sub in cat.get("subs", []):
                m = _usage(self.project_path, sub["category_id"]) if _usage else 0
                child = QTreeWidgetItem([sub["name"], str(m),
                                         "" if sub["is_active"] else "архив"])
                child.setData(0, Qt.ItemDataRole.UserRole, sub["category_id"])
                if not sub["is_active"]:
                    child.setDisabled(True)
                top.addChild(child)
            self.tree.addTopLevelItem(top)
        self.tree.expandAll()

    def _selected_id(self) -> int | None:
        item = self.tree.currentItem()
        if not item:
            notify(self, "warning", "Внимание", "Выбери категорию в дереве")
            return None
        return item.data(0, Qt.ItemDataRole.UserRole)

    def _ask_name(self, title: str) -> str | None:
        name, ok = QInputDialog.getText(self, title, "Название:")
        name = (name or "").strip()
        if not ok or not name:
            return None
        if len(name) > 64:
            notify(self, "warning", "Ошибка", "Название до 64 символов")
            return None
        return name

    def _add_category(self):
        name = self._ask_name("Новая категория")
        if not name:
            return
        try:
            create_category(self.project_path, name)
            self.reload()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _add_subcategory(self):
        parent_id = self._selected_id()
        if parent_id is None:
            return
        name = self._ask_name("Новая подкатегория")
        if not name:
            return
        try:
            create_category(self.project_path, name, parent_id=parent_id)
            self.reload()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _rename(self):
        cid = self._selected_id()
        if cid is None:
            return
        name = self._ask_name("Переименовать")
        if not name:
            return
        try:
            rename_category(self.project_path, cid, name)
            self.reload()
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))

    def _toggle_archive(self):
        cid = self._selected_id()
        if cid is None:
            return
        try:
            cats = list_categories(self.project_path, include_archived=True)
            flat = [c for c in cats] + [s for c in cats for s in c.get("subs", [])]
            cur = next((c for c in flat if c["category_id"] == cid), None)
            active = not (cur and cur["is_active"])
            if active:
                set_category_active(self.project_path, cid, True)
            else:
                archive_category(self.project_path, cid)
            self.reload()
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def _delete(self):
        cid = self._selected_id()
        if cid is None:
            return
        if not confirm(self, "Подтверждение",
                       "Удалить категорию? Получится, только если она нигде не использована."):
            return
        try:
            delete_category(self.project_path, cid)
            self.reload()
        except ValueError as e:
            notify(self, "warning", "Удаление невозможно", str(e))
