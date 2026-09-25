"""Экран «Датасеты» (рескин по референсу): то же тело, что в диалоге."""
from PySide6.QtWidgets import QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from ui_base import BaseScreen
from datasets_dialog import DatasetsWidget


class DatasetsScreen(BaseScreen):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("🗂 ДАТАСЕТЫ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        self.body = DatasetsWidget(project_path, self)
        layout.addWidget(self.body, 1)
        self.setLayout(layout)

    def refresh(self):
        try:
            self.body.reload_datasets()
        except Exception:
            pass
