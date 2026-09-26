"""Экран Датасеты: тело из диалога, навигация, чистка Проекта."""
import tempfile

from PySide6.QtWidgets import QApplication, QPushButton

from database import init_database
from dataset_service import create_dataset
from datasets_screen import DatasetsScreen


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    create_dataset(p, "ds1", "", "working")
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_screen_lists_datasets():
    _app()
    w = DatasetsScreen(_proj(), None)
    try:
        w.show()
        assert w.body.ds_list.count() == 1
        assert "ds1" in w.body.ds_list.item(0).text()
        w.refresh()
        assert w.body.ds_list.count() == 1
    finally:
        w.close()


def test_dialog_wrapper_compat():
    _app()
    from datasets_dialog import DatasetsDialog, DatasetsWidget
    p = _proj()
    d = DatasetsDialog(p, None)
    try:
        d.show()
        assert isinstance(d.body, DatasetsWidget)
        assert d.body.ds_list.count() == 1
        d.reload_datasets()
        assert d.body.ds_list.count() == 1
    finally:
        d.close()


def test_project_has_no_dup_entries():
    _app()
    from project_screen import ProjectScreen
    p = tempfile.mkdtemp()
    init_database(p)
    w = ProjectScreen(p, None)
    try:
        w.show()
        labels = [b.text() for b in w.findChildren(QPushButton)]
        assert not any("Датасеты" in t for t in labels), labels
        assert not any("Прогоны" in t for t in labels), labels
        assert any("Начать ревью" in t for t in labels), labels
    finally:
        w.close()


def test_totals_footer():
    _app()
    w = DatasetsScreen(_proj(), None)
    try:
        w.show()
        assert "Всего датасетов: 1" in w.body.totals_label.text()
    finally:
        w.close()
