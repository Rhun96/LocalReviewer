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
    import time as _t
    pytest.importorskip("matplotlib")
    w = _win(_proj())
    try:
        w.show()
        for _ in range(100):
            app = QApplication.instance()
            app.processEvents()
            pix = w.chart_label.pixmap()
            if pix is not None and not pix.isNull():
                break
            _t.sleep(0.05)
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


def _proj2files():
    from database import db
    p = tempfile.mkdtemp()
    init_database(p)
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(p, "a.xlsx", "excel", "S", 0, mapping,
                [{"q": f"a{i}", "a": f"a{i}"} for i in range(3)])
    import_file(p, "b.xlsx", "excel", "S", 0, mapping,
                [{"q": "b0", "a": "b0"}])
    with db(p) as conn:
        fids = {r["file_name"]: r["file_id"] for r in conn.execute(
            "SELECT file_id, file_name FROM files").fetchall()}
        aids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases WHERE file_id=?",
            (fids["a.xlsx"],)).fetchall()]
    bulk_set_status(p, aids[:2], "good")
    bugs.create_bug(p, "в файле а", severity="High", case_ids=aids[:1])
    return p, fids


def test_scope_combo_and_file_cards():
    import analytics_service as an
    p, fids = _proj2files()
    w = _win(p)
    try:
        w.show()
        assert w.scope_combo.count() == 3
        for i in range(w.scope_combo.count()):
            if w.scope_combo.itemData(i) == fids["b.xlsx"]:
                w.scope_combo.setCurrentIndex(i)
                break
        w.refresh()
        v, s = _text(w, "reviewed")
        assert v == "0", (v, s)
        assert "из 1" in s, (v, s)
        v, _s = _text(w, "bugs")
        assert v == "0", (v, _s)
        scoped = an.bugs_stats(p, {"file_id": fids["a.xlsx"]})
        assert scoped["open"] == 1 and scoped["created"] == 1
        scoped_b = an.bugs_stats(p, {"file_id": fids["b.xlsx"]})
        assert scoped_b["open"] == 0 and scoped_b["created"] == 0
    finally:
        w.close()


def test_review_cards_follow_file_filter():
    _ = QApplication.instance() or QApplication([])
    from review_screen import ReviewScreen
    p, fids = _proj2files()
    w = ReviewScreen(p)
    try:
        w.show()
        w.refresh()
        assert w._stat_cards["total"][0].text() == "4"
        assert w._stat_cards["total"][1].text() == "в проекте"
        w.filters = {"file_id": fids["b.xlsx"]}
        w.load_case_ids()
        w.update_stat_cards()
        assert w._stat_cards["total"][0].text() == "1"
        assert w._stat_cards["total"][1].text() == "в файле"
    finally:
        w.close()


def test_period_combo_filters():
    w = _win(_proj())
    try:
        w.show()
        for i in range(w.period_combo.count()):
            if w.period_combo.itemData(i) == "7d":
                w.period_combo.setCurrentIndex(i)
                break
        w.refresh()
        v, _s = _text(w, "reviewed")
        assert v == "3"
    finally:
        w.close()


def test_chart_lazy_renders_on_show():
    """График не рендерится в refresh (старт!), только после показа."""
    import time as _t

    import pytest
    pytest.importorskip("matplotlib")
    w = _win(_proj())
    try:
        assert w._chart_dirty
        pix0 = w.chart_label.pixmap()
        assert pix0 is None or pix0.isNull()
        w.show()
        for _ in range(100):
            app = QApplication.instance()
            app.processEvents()
            if not w._chart_dirty and w.chart_label.pixmap() is not None:
                break
            _t.sleep(0.05)
        assert not w._chart_dirty
        assert w.chart_label.pixmap() is not None
        assert not w.chart_label.pixmap().isNull()
    finally:
        w.close()
