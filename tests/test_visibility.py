"""Скрытие строк: сервис, отсечения выборок/счётчиков/слепков/экспорта, UI."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from database import SCHEMA_VERSION, init_database
from importer import import_file
import visibility_service as vis


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text", "i": "source_id"},
                [{"q": f"q{i}", "a": f"a{i}", "i": f"k{i}"} for i in range(4)])
    return tmp


def test_schema_v19():
    assert SCHEMA_VERSION == 20


def test_hide_unhide_roundtrip():
    p = _proj()
    assert vis.hide_cases(p, [1, 2, 2]) == 2
    assert vis.hide_cases(p, [1]) == 0  # уже скрыт
    assert vis.hidden_count(p) == 2
    assert vis.unhide_cases(p, [1, 9]) == 1  # 9 нет
    assert vis.hidden_count(p) == 1
    from database import db
    with db(p) as conn:
        evts = [r["event_type"] for r in conn.execute(
            "SELECT event_type FROM history ORDER BY history_id").fetchall()]
    assert "case_hidden" in evts and "case_shown" in evts


def test_hidden_out_of_everywhere():
    from filter_service import (get_all_case_ids, get_filtered_case_ids,
                                count_filtered_cases)
    from review_queue_service import queue_stats, build_queue
    from report_service import get_overall_report
    p = _proj()
    vis.hide_cases(p, [1])
    assert 1 not in get_all_case_ids(p)
    assert len(get_all_case_ids(p)) == 3
    assert 1 not in get_filtered_case_ids(p, {"search_text": "q"})
    assert count_filtered_cases(p, {}) == 3
    qids, _ = build_queue(p, "normal", None)
    assert 1 not in qids
    st = queue_stats(p)
    assert (st["total"], st["remaining"]) == (3, 3)
    rep = get_overall_report(p)
    assert (rep["total"], rep["reviewed"]) == (3, 0)
    # а с флагом — видно
    assert 1 in get_filtered_case_ids(p, {"include_hidden": True})


def test_hidden_out_of_snapshot_and_export(tmp_path=None):
    import dataset_service as ds
    from export_service import export_results_to_xlsx
    p = _proj()
    vis.hide_cases(p, [1])
    did = ds.create_dataset(p, "d")
    ver = ds.create_version(p, did)
    info = [v for v in ds.list_versions(p, did) if v["version_id"] == ver][0]
    assert info["case_count"] == 3
    out = os.path.join(tempfile.mkdtemp(), "exp.xlsx")
    n = export_results_to_xlsx(p, out)
    assert n == 3


def test_ui_toggle_and_bulk():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from review_screen import ReviewScreen
    p = _proj()
    w = ReviewScreen(p)
    try:
        w.show()
        assert len(w.case_ids) == 4
        w.toggle_hide_current()  # скрыть текущий
        assert len(w.case_ids) == 3
        assert "Скрыто" in w.filter_indicator.text()
        # тумблер показывает серых
        w.btn_show_hidden.setChecked(True)
        assert "Скрытые (1)" in w.btn_show_hidden.text()
        # bulk-показ возвращает
        from database import db
        with db(p) as conn:
            hid = [r["case_id"] for r in conn.execute(
                "SELECT case_id FROM cases WHERE hidden = 1").fetchall()]
        w.bulk_selected = set(hid)
        w.on_bulk_unhide()
        assert len(w.case_ids) == 4
    finally:
        w.close()


def test_hide_undo_in_case_mode():
    """Скрыл в кейсе — Ctrl+Z вернул без похода в таблицу."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from review_screen import ReviewScreen
    p = _proj()
    w = ReviewScreen(p)
    try:
        w.show()
        cid = w.current_case_id
        assert len(w.case_ids) == 4
        w.toggle_hide_current()
        assert len(w.case_ids) == 3
        assert vis.hidden_count(p) == 1
        assert w._last_single is not None and w._last_single["kind"] == "hide"
        w.undo_single()
        assert vis.hidden_count(p) == 0
        assert len(w.case_ids) == 4
        assert cid in w.case_ids
    finally:
        w.close()
