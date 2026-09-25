"""Быстрый выбор причины после статуса «Плохо» (ТЗ §23): категория -> подкатегория."""
from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QGridLayout
from PySide6.QtCore import Qt
from taxonomy_service import SEVERITY_NAMES, list_categories
from ui_compat import FComboBox, FPrimaryButton, FPushButton


class ErrorCauseDialog(QDialog):
    """result = (category_id, subcategory_id|None, severity) или None (пропустить)."""

    def __init__(self, project_path: str, parent=None, case_id: int | None = None):
        super().__init__(parent)
        self.project_path = project_path
        self.case_id = case_id
        self.setWindowTitle("Причина ошибки")
        self.setMinimumWidth(480)
        self.result = None
        self._cat_id = None
        self._categories = []
        self._cat_buttons = {}
        self._init_ui()
        self._load()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(10)
        title = QLabel("Причина — шаг 1: категория")
        title.setStyleSheet("font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        hint = QLabel("Причина сохранится отдельным полем и дополнит твой комментарий, "
                      "а не заменит его.")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        self.suggest_row = QHBoxLayout()
        self.suggest_label = QLabel("")
        self.suggest_label.setWordWrap(True)
        self.suggest_btn = FPushButton("Применить")
        self.suggest_btn.setMaximumWidth(110)
        self.suggest_btn.clicked.connect(self._apply_suggestion)
        self.suggest_row.addWidget(self.suggest_label, 3)
        self.suggest_row.addWidget(self.suggest_btn)
        layout.addLayout(self.suggest_row)

        self.cats_layout = QGridLayout()
        self.cats_layout.setSpacing(6)
        layout.addLayout(self.cats_layout)

        self.sub_title = QLabel("Шаг 2: подкатегория")
        self.sub_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(self.sub_title)
        self.sub_combo = FComboBox()
        self.sub_combo.setMinimumHeight(32)
        layout.addWidget(self.sub_combo)

        sev_layout = QHBoxLayout()
        sev_layout.addWidget(QLabel("Критичность:"))
        self.sev_combo = FComboBox()
        for code in ("low", "medium", "high", "critical"):
            self.sev_combo.addItem(SEVERITY_NAMES[code], code)
        self.sev_combo.setCurrentIndex(1)
        sev_layout.addWidget(self.sev_combo)
        layout.addLayout(sev_layout)

        btns = QHBoxLayout()
        ok = FPrimaryButton("✅ Готово")
        ok.setMinimumHeight(40)
        ok.clicked.connect(self._on_ok)
        skip = FPushButton("Пропустить")
        skip.setMinimumHeight(40)
        skip.clicked.connect(self.reject)
        btns.addWidget(ok)
        btns.addWidget(skip)
        layout.addLayout(btns)
        self.setLayout(layout)

    def _load(self):
        try:
            self._categories = list_categories(self.project_path)
        except Exception:
            self._categories = []
        row = col = 0
        for cat in self._categories:
            btn = FPushButton(cat["name"])
            btn.setCheckable(True)
            btn.setChecked(False)
            btn.setMinimumHeight(36)
            self._style_cat_btn(btn, False)
            btn.clicked.connect(lambda _c, cid=cat["category_id"]: self._select_cat(cid))
            self.cats_layout.addWidget(btn, row, col)
            self._cat_buttons[cat["category_id"]] = btn
            col += 1
            if col >= 3:
                col = 0
                row += 1
        if self._categories:
            self._select_cat(self._categories[0]["category_id"])
        self._load_suggestion()

    def _load_suggestion(self):
        """Предложено backend'ом (§18) — применяется вручную кнопкой."""
        self._suggested = None
        self.suggest_label.setText("")
        self.suggest_btn.setVisible(False)
        if not self.case_id:
            return
        try:
            import category_suggestion_service as sug
            res = sug.suggest_annotations(self.project_path, self.case_id)
            cat = (res or {}).get("category")
        except Exception:
            cat = None
        if not cat or not cat.get("category_id"):
            return
        self._suggested = cat
        self.suggest_label.setText(
            f"💡 Предложено: {cat.get('category_name', '')} → "
            f"{cat.get('subcategory_name', '')} "
            f"({cat.get('support', 0)} похожих)")
        self.suggest_btn.setVisible(True)

    def _apply_suggestion(self):
        cat = getattr(self, "_suggested", None) or {}
        if not cat.get("category_id"):
            return
        self._select_cat(cat["category_id"])
        if cat.get("subcategory_id"):
            for i in range(self.sub_combo.count()):
                if self.sub_combo.itemData(i) == cat["subcategory_id"]:
                    self.sub_combo.setCurrentIndex(i)
                    break

    @staticmethod
    def _style_cat_btn(btn, selected: bool) -> None:
        # Выбранная категория видна сразу, без ухода в подкатегории.
        from styles import COLORS as _CC
        if selected:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: {_CC['green_bright']};
                    color: {_CC['bg_dark']};
                    border: 2px solid {_CC['green_bright']};
                    border-radius: 6px;
                    font-weight: bold;
                    padding: 6px;
                }}
            """)
        else:
            btn.setStyleSheet("")

    def _select_cat(self, category_id: int):
        self._cat_id = category_id
        for cid, btn in self._cat_buttons.items():
            selected = (cid == category_id)
            if btn.isChecked() != selected:
                btn.setChecked(selected)
            self._style_cat_btn(btn, selected)
        cat = next((c for c in self._categories if c["category_id"] == category_id), None)
        self.sub_title.setText(f"Шаг 2: подкатегория [категория: {(cat or {}).get('name', '')}]")
        self.sub_combo.clear()
        self.sub_combo.addItem("— без подкатегории —", None)
        for sub in (cat or {}).get("subs", []):
            self.sub_combo.addItem(sub["name"], sub["category_id"])

    def _on_ok(self):
        if self._cat_id is None:
            self.reject()
            return
        self.result = (self._cat_id, self.sub_combo.currentData(),
                       self.sev_combo.currentData() or "medium")
        self.accept()
