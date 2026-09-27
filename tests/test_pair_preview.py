"""Превью пар: тексты рядом без прыжков по кейсам."""
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QListWidgetItem

from database import init_database
from importer import import_file
from similar_dialog import DuplicatesDialog, SimilarDialog, pair_preview


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text"},
                [{"q": "как вернуть билет", "a": "оформи возврат"},
                 {"q": "хочу сдать билет", "a": "возврат за 5 дней"}])
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_pair_preview_texts():
    _app()
    from database import db
    p = _proj()
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    ta, tb = pair_preview(p, ids[0], ids[1])
    assert "вернуть билет" in ta and "оформи возврат" in ta
    assert "сдать билет" in tb
    assert pair_preview(p, 999999, ids[1])[0] != ""


def test_duplicates_preview_fills():
    _app()
    p = _proj()
    from database import db
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    d = DuplicatesDialog(p, None, None)
    try:
        d.show()
        item = QListWidgetItem("99%")
        item.setData(Qt.ItemDataRole.UserRole, (ids[0], ids[1]))
        d.results.addItem(item)
        d.results.setCurrentRow(0)
        assert "вернуть билет" in d.pair_a.toPlainText()
        assert "сдать билет" in d.pair_b.toPlainText()
    finally:
        d.close()


def test_similar_preview_fills():
    _app()
    p = _proj()
    from database import db
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    d = SimilarDialog(p, ids[0], None)
    try:
        d.show()
        item = QListWidgetItem("80%")
        item.setData(Qt.ItemDataRole.UserRole, ids[1])
        d.results.addItem(item)
        d.results.setCurrentRow(0)
        assert "вернуть билет" in d.preview_a.toPlainText()
        assert "сдать билет" in d.preview_b.toPlainText()
    finally:
        d.close()
