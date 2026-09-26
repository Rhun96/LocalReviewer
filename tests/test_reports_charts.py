"""Графики как в референсе: компактная сетка 2×N, донат, сетка осей."""
import tempfile

import pytest
from PySide6.QtWidgets import QApplication, QLabel

from bulk_operation_service import bulk_set_status
from database import db, init_database
from importer import import_file
from reports_screen import ReportsScreen

pytest.importorskip("matplotlib")


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
    return p


def _win(p):
    QApplication.instance() or QApplication([])
    return ReportsScreen(p, None)


def _chart_labels(w):
    out = []
    lay = w.charts_layout
    for i in range(lay.count()):
        item = lay.itemAt(i)
        wd = item.widget() if item is not None else None
        if isinstance(wd, QLabel) and wd.pixmap() is not None:
            pos = lay.getItemPosition(i)
            out.append((pos[0], pos[1], wd.pixmap().isNull()))
    return out


def test_charts_grid_compact():
    w = _win(_proj())
    try:
        w.show()
        w.refresh_charts()
        got = _chart_labels(w)
        assert len(got) >= 2, got
        assert all(not null for _, _, null in got)
        pos = sorted((r, c) for r, c, _ in got)
        assert pos[0] == (0, 0) and pos[1] == (0, 1)
        assert all(c in (0, 1) for _, c in pos)
    finally:
        w.close()


def test_donut_pie_renders():
    from report_service import get_overall_report
    w = _win(_proj())
    try:
        w.show()
        rep = get_overall_report(w.project_path)
        w._create_pie_chart(rep)
        got = _chart_labels(w)
        assert len(got) == 1 and not got[0][2]
    finally:
        w.close()
