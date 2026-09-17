"""ReviewScreen собран из миксинов + offscreen smoke без модальных диалогов."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from review_screen import ReviewScreen


def test_mro_and_methods():
    names = [c.__name__ for c in ReviewScreen.__mro__]
    for base in ("BaseScreen", "ProfileMixin", "CaseMixin", "TableMixin",
                 "BulkMixin", "VerdictsMixin"):
        assert base in names, base
    for method in ("load_case", "set_status", "next_case", "prev_case",
                   "create_case_view", "create_table_view", "load_table_data",
                   "on_bulk_select_all", "on_bulk_run", "on_recheck_all",
                   "on_bulk_undo", "load_profile", "apply_profile",
                   "init_shortcuts", "_refresh_verdicts", "open_filters",
                   "update_filter_indicator", "review_closed"):
        assert hasattr(ReviewScreen, method), method


def _make_window():
    from PySide6.QtWidgets import QApplication

    from database import init_database
    from importer import import_file

    tmp = tempfile.mkdtemp()
    init_database(tmp)
    data = [{"q": "question one", "a": "answer one"},
            {"q": "question two", "a": "answer two"}]
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(tmp, "f.xlsx", "excel", "Sheet1", 0, mapping, data)
    QApplication.instance() or QApplication([])
    return ReviewScreen(tmp)


def test_offscreen_smoke():
    w = _make_window()
    try:
        assert len(w.case_ids) == 2
        w.next_case()
        assert w.current_index == 1
        w.prev_case()
        assert w.current_index == 0
        w.toggle_view()
        w.load_table_data()
        w.next_page()
        w.prev_page()
        w.on_bulk_select_all()
        assert len(w.bulk_selected) == 2
        w.on_bulk_clear()
        assert len(w.bulk_selected) == 0
        w.toggle_view()
        first = w.current_case_id
        w.set_status("good")
        w.load_case(w.case_ids.index(first))
        assert w.current_case.get("status") == "good"
    finally:
        w.close()


def test_counter_updates_after_single_mark():
    w = _make_window()
    try:
        w.refresh()
        assert "0/2" in w.filter_indicator.text()
        first = w.current_case_id
        w.set_status("good")
        assert "1/2" in w.filter_indicator.text()
        w.load_case(w.case_ids.index(first))
        assert w.current_case.get("status") == "good"
    finally:
        w.close()


def test_theme_switch_converges_palettes():
    from PySide6.QtWidgets import QApplication, QWidget

    from ui_compat import apply_theme

    w = _make_window()
    try:
        app = QApplication.instance()
        w.show()
        app.processEvents()
        role = app.palette().ColorRole.Window
        for mode, expect in (("dark", "#202020"), ("light", "#f3f3f3")):
            apply_theme(mode)
            app.processEvents()
            assert app.palette().color(role).name() == expect
            # Only visible widgets: hidden ones repolish on show.
            shown = [x for x in [w] + w.findChildren(QWidget) if x.isVisible()]
            assert shown, "window did not show offscreen"
            for child in shown:
                assert child.palette().color(role).name() == expect
    finally:
        w.close()


def test_indicator_ignores_orphan_cases():
    """Сироты удалённых файлов: невидимы в ревью — не входят и в счётчики."""
    import tempfile

    from PySide6.QtWidgets import QApplication

    from bulk_operation_service import bulk_set_status
    from database import db, init_database
    from importer import import_file
    from review_queue_service import queue_stats

    proj = tempfile.mkdtemp()
    init_database(proj)
    mapping = {"q": "primary_text", "a": "response_text"}
    live = [{"q": "q1", "a": "a1"}, {"q": "q2", "a": "a2"}, {"q": "q3", "a": "a3"}]
    dead = [{"q": "d1", "a": "a1"}, {"q": "d2", "a": "a2"}, {"q": "d3", "a": "a3"}]
    import_file(proj, "live.xlsx", "excel", "S", 0, mapping, live)
    dead_id, _, _ = import_file(proj, "dead.xlsx", "excel", "S", 0, mapping, dead)
    with db(proj) as conn:
        orphans = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases WHERE file_id = ?", (dead_id,))]
    assert len(orphans) == 3
    bulk_set_status(proj, orphans[:1], "good")
    with db(proj) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM files WHERE file_id = ?", (dead_id,))
    with db(proj) as conn:
        assert conn.execute("SELECT COUNT(*) c FROM cases").fetchone()["c"] == 6
    stats = queue_stats(proj)
    assert (stats["total"], stats["reviewed"], stats["remaining"]) == (3, 0, 3), stats
    QApplication.instance() or QApplication([])
    w = ReviewScreen(proj)
    try:
        w.refresh()
        assert "0/3" in w.filter_indicator.text(), w.filter_indicator.text()
    finally:
        w.close()
    from report_service import get_overall_report
    overall = get_overall_report(proj)
    assert (overall["total"], overall["reviewed"]) == (3, 0), overall
    from project_screen import ProjectScreen
    ps = ProjectScreen(proj)
    try:
        assert "0/3" in ps.info_label.text(), ps.info_label.text()
    finally:
        ps.close()
