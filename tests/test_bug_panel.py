"""Панель карточки бага: виджет, обёртка диалога, сплит в списке."""
import tempfile

from PySide6.QtWidgets import QApplication

from bug_report_dialog import BugReportDialog, BugReportWidget
from bug_reports_screen import BugReportsScreen
from database import db, init_database
import bug_report_service as bugs


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_widget_save_no_duplicate():
    _app()
    p = _proj()
    w = BugReportWidget(p, None, None)
    try:
        w.show()
        got = []
        w.saved.connect(got.append)
        w.title_edit.setText("падает тут")
        w._save()
        assert got and isinstance(got[0], int)
        assert w.bug_id == got[0]
        w.title_edit.setText("падает тут же")
        w._save()
        with db(p) as conn:
            n = conn.execute("SELECT COUNT(*) c FROM bug_reports").fetchone()["c"]
        assert n == 1
        assert len(got) == 2 and got[0] == got[1]
    finally:
        w.close()


def test_dialog_wrapper_compat():
    _app()
    p = _proj()
    bid = bugs.create_bug(p, "сломан", severity="High")
    d = BugReportDialog(p, None, bid, None)
    try:
        d.show()
        assert d.body.title_edit.text() == "сломан"
        d._on_saved(bid)
        assert d.result_id == bid
        d._on_goto(7)
        assert d.result_case_id == 7
    finally:
        d.close()
    d2 = BugReportDialog(p, {"title_suggest": "черновик"}, None, None)
    try:
        d2.show()
        assert d2.body.title_edit.text() == "черновик"
    finally:
        d2.close()


def test_panel_selection_and_new():
    _app()
    p = _proj()
    bid = bugs.create_bug(p, "первый", severity="Low")
    w = BugReportsScreen(p, None)
    try:
        w.show()
        assert w.table.rowCount() == 1
        assert w.card_id is None
        w.table.setCurrentCell(0, 0)
        assert w.card_id == bid
        assert w.card_title.text() == f"Баг #{bid}"
        assert w.card_widget.title_edit.text() == "первый"
        w._new_bug()
        assert w.card_id is None
        assert w.card_title.text() == "Новый баг"
        w.card_widget.title_edit.setText("второй")
        w.card_widget._save()
        assert w.table.rowCount() == 2
        assert w.card_id != bid
    finally:
        w.close()
