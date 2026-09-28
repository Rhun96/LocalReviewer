"""Ручной период: пресеты и даты с/по в отчётах и на главной."""
import tempfile

from PySide6.QtCore import QDate
from PySide6.QtWidgets import QApplication

from database import init_database
from importer import import_file


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "q1"}, {"q": "q2"}])
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_period_dates_helper():
    from ui_compat import period_dates as _pd
    assert _pd("") == ("", "")
    assert _pd("nope") == ("", "")
    f, t = _pd("today")
    assert f == t and len(f) == 10
    f, t = _pd("7d")
    assert f < t and len(f) == 10
    assert _pd("manual", QDate(2026, 9, 1),
               QDate(2026, 9, 28)) == ("2026-09-01", "2026-09-28")
    # перепутанные меняются местами
    assert _pd("manual", QDate(2026, 9, 28),
               QDate(2026, 9, 1)) == ("2026-09-01", "2026-09-28")
    # мусор — пусто, а не взрыв
    assert _pd("manual", "мусор", "") == ("", "")


def test_reports_manual_scope():
    _app()
    from reports_screen import ReportsScreen
    p = _proj()
    w = ReportsScreen(p, None)
    try:
        w.show()
        assert not w.date_from.isVisible()
        for i in range(w.period_combo.count()):
            if w.period_combo.itemData(i) == "manual":
                w.period_combo.setCurrentIndex(i)
                break
        assert w.date_from.isVisible() and w.date_to.isVisible()
        assert w.date_from_label.isVisible()
        w.date_from.setDate(QDate(2026, 9, 1))
        w.date_to.setDate(QDate(2026, 9, 28))
        sc = w._analytics_scope()
        assert sc["reviewed_from"] == "2026-09-01"
        assert sc["reviewed_to"] == "2026-09-28"
    finally:
        w.close()


def test_dashboard_manual_smoke():
    _app()
    from dashboard_screen import DashboardScreen
    p = _proj()
    w = DashboardScreen(p, None)
    try:
        w.show()
        for i in range(w.period_combo.count()):
            if w.period_combo.itemData(i) == "manual":
                w.period_combo.setCurrentIndex(i)
                break
        w.date_from.setDate(QDate(2026, 9, 1))
        w.date_to.setDate(QDate(2026, 9, 28))
        w.refresh()
        assert w.date_from.isVisible()
    finally:
        w.close()
