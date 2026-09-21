"""V2.1 §14: подсказка 'нет Bug Report' — только Bad+причина+high/critical."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from database import init_database
from importer import import_file
from filter_service import get_filtered_case_ids
from bulk_operation_service import bulk_set_status
from taxonomy_service import list_categories, set_case_error
import bug_report_service as bugs
from saved_filter_service import (
    ensure_preset_views, list_saved_filters, delete_saved_filter)


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text"},
                [{"q": "q1", "a": "a1"}])
    return tmp


def _cause_ids(p):
    for c in list_categories(p):
        subs = c.get("subs") or []
        if subs:
            return c["category_id"], subs[0]["category_id"]
    raise AssertionError("no taxonomy seeded")


def _window(p):
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from review_screen import ReviewScreen
    w = ReviewScreen(p)
    w.show()
    QApplication.instance().processEvents()
    return w


def _hint_visible(w) -> bool:
    return bool(w.nobug_widget.isVisible())


def test_hint_shows_for_bad_high_without_bug():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "bad")
    cat, sub = _cause_ids(p)
    set_case_error(p, ids[0], cat, sub, "high")
    w = _window(p)
    try:
        assert _hint_visible(w), "Bad+high без бага: хинт должен быть виден"
    finally:
        w.close()


def test_hint_hidden_with_bug_or_good_or_low():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    cat, sub = _cause_ids(p)

    bulk_set_status(p, ids, "bad")
    set_case_error(p, ids[0], cat, sub, "critical")
    bugs.create_bug(p, "t", ids, severity="High")
    w = _window(p)
    try:
        assert not _hint_visible(w), "есть баг: хинта быть не должно"
    finally:
        w.close()

    bulk_set_status(p, ids, "good")
    w2 = _window(p)
    try:
        assert not _hint_visible(w2), "Good: хинта быть не должно"
    finally:
        w2.close()

    bulk_set_status(p, ids, "bad")
    set_case_error(p, ids[0], cat, sub, "low")
    for b in bugs.bugs_for_case(p, ids[0]):
        bugs.delete_bug(p, b["bug_id"])
    w3 = _window(p)
    try:
        assert not _hint_visible(w3), "low severity: хинта быть не должно"
    finally:
        w3.close()


def test_presets_seeded_once_and_not_resurrected():
    p = _proj()
    assert ensure_preset_views(p) == 3
    assert ensure_preset_views(p) == 0
    names = [f["name"] for f in list_saved_filters(p)]
    assert "Обычное ревью" in names and "Баги" in names
    victim = next(f for f in list_saved_filters(p) if f["name"] == "Баги")
    assert delete_saved_filter(p, victim["filter_id"])
    assert ensure_preset_views(p) == 0
    assert "Баги" not in [f["name"] for f in list_saved_filters(p)]
