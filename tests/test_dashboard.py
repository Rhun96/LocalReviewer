"""Дашборд Главная: карточки, график, последние действия, навигация."""
import tempfile

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from bulk_operation_service import bulk_set_status
from database import db, init_database
from dashboard_screen import DashboardScreen
from importer import import_file
import bug_report_service as bugs


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(p, "f.xlsx", "excel", "S", 0, mapping,
                [{"q": f"q{i}", "a": f"a{i}"} for i in range(4)])
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    bulk_set_status(p, ids[:2], "good")
    bulk_set_status(p, ids[2:3], "bad")
    bugs.create_bug(p, "падает", severity="High")
    return p


def _win(p):
    QApplication.instance() or QApplication([])
    return DashboardScreen(p, None)


def _text(w, key):
    return w._cards[key][0].text(), w._cards[key][1].text()


def test_cards_values():
    w = _win(_proj())
    try:
        w.show()
        v, s = _text(w, "reviewed")
        assert v == "3" and "4" in s, (v, s)
        v, s = _text(w, "complete")
        assert v == "75.0%", (v, s)
        v, s = _text(w, "bad")
        assert v == "33.3%" and "1" in s, (v, s)
        v, s = _text(w, "bugs")
        assert v == "1", (v, s)
    finally:
        w.close()


def test_chart_and_recent():
    pytest.importorskip("matplotlib")
    w = _win(_proj())
    try:
        w.show()
        pix = w.chart_label.pixmap()
        assert pix is not None and not pix.isNull()
        assert w.recent_list.count() >= 3
        assert w.recent_list.item(0).data(Qt.ItemDataRole.UserRole) is not None
    finally:
        w.close()


def test_nav_first():
    _ = QApplication.instance() or QApplication([])
    from database import init_database as _init
    from sidebar import Sidebar
    from session_service import SCREENS
    from main import MainWindow
    p = tempfile.mkdtemp()
    _init(p)
    s = Sidebar(p)
    assert list(s.buttons)[0] == "dashboard"
    assert MainWindow.NAV_ITEMS[0][0] == "dashboard"
    assert "dashboard" in SCREENS
