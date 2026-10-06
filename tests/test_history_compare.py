"""Сравнение состояний кейса, включая «событие → сейчас»."""
import tempfile

import pytest
from PySide6.QtWidgets import QApplication

from bulk_operation_service import bulk_set_status
from database import init_database
from filter_service import get_filtered_case_ids
from importer import import_file
import history_service as hs


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "q1"}, {"q": "q2"}])
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_compare_two_events_still_works():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    bulk_set_status(p, [ids[0]], "bad")
    evts = hs.search_history(p, case_ids=[ids[0]])
    assert len(evts) == 2
    res = hs.compare_states(p, ids[0], evts[0]["history_id"],
                            evts[1]["history_id"])
    row = {r["field"]: r for r in res["rows"]}
    assert row["status"]["changed"] is True
    with pytest.raises(ValueError):
        hs.compare_states(p, ids[0], evts[0]["history_id"],
                          evts[0]["history_id"])


def test_compare_event_with_now():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    evts = hs.search_history(p, case_ids=[ids[0]])
    res = hs.compare_states(p, ids[0], evts[0]["history_id"], None)
    assert res["b_id"] is None and res["b_at"] is None
    row = {r["field"]: r for r in res["rows"]}
    assert row["status"]["b"] == "good"
    # после смены вердикта «сейчас» едет следом
    bulk_set_status(p, [ids[0]], "bad")
    res2 = hs.compare_states(p, ids[0], evts[0]["history_id"], None)
    row2 = {r["field"]: r for r in res2["rows"]}
    assert row2["status"]["b"] == "bad"
    assert row2["status"]["changed"] is True


def test_compare_now_dialog_button():
    _app()
    from history_screen import HistoryScreen, StateCompareDialog
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    w = HistoryScreen(p, None)
    try:
        w.show()
        w.case_filter.setText(str(ids[0]))
        w.load_history()
        assert w.history_table.rowCount() >= 1
        w.history_table.setCurrentCell(0, 0)
        sel = w._selected_event_ids()
        assert len(sel) == 1
        res = hs.compare_states(p, ids[0], sel[0]["history_id"], None)
        d = StateCompareDialog(res, None)
        try:
            d.show()
            from PySide6.QtWidgets import QLabel as _QL
            texts = [x.text() for x in d.findChildren(_QL)]
            assert any("текущее" in t for t in texts)
        finally:
            d.close()
    finally:
        w.close()
