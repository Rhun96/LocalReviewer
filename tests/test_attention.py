"""Центр внимания: детекторы, уровни, переходы."""
import tempfile

from PySide6.QtWidgets import QApplication

from bulk_operation_service import bulk_set_status
from database import db, init_database
from filter_service import get_filtered_case_ids
from importer import import_file
import attention_service as att
import bug_report_service as bugs


def _proj(rows):
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"}, rows)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_clean_project_is_quiet():
    p = _proj([{"q": "q1", "i": "k1"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    assert att.fast_snapshot(p) == []


def test_unreviewed_and_bad_no_cause():
    p = _proj([{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    rows = {r["code"]: r for r in att.fast_snapshot(p)}
    assert rows["unreviewed"]["level"] == "warning"
    assert rows["unreviewed"]["count"] == 1
    assert rows["bad_no_cause"]["level"] == "critical"
    assert rows["bad_no_cause"]["count"] == 1
    assert rows["bad_no_cause"]["action"]["screen"] == "review"
    assert rows["bad_no_cause"]["action"]["filters"]["case_ids"] == [ids[0]]
    # с причиной — пункт уходит
    from taxonomy_service import set_case_error
    with db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness'").fetchone()
        sub = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness.hallucination'").fetchone()
    set_case_error(p, ids[0], cat["category_id"], sub["category_id"], "high")
    rows = {r["code"]: r for r in att.fast_snapshot(p)}
    assert "bad_no_cause" not in rows


def test_bugs_and_launches():
    p = _proj([{"q": "q1", "i": "k1"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    bugs.create_bug(p, "один", [ids[0]])
    bugs.create_bug(p, "без кейса")
    with db(p) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO model_runs (name, created_at) "
                    "VALUES ('m1', 't')")
        rid = cur.lastrowid
        cur.execute(
            """INSERT INTO regression_runs
                (name, baseline_type, baseline_id, candidate_type,
                 candidate_run_id, gate_max_critical, gate_max_rate,
                 gate_result, total, regressions, improvements, unchanged,
                 created_at)
               VALUES ('hang', 'run', ?, 'run', ?, 0, 0.02,
                       NULL, 10, 0, 0, 10, datetime('now'))""",
            (rid, rid))
        cur.execute(
            """INSERT INTO regression_runs
                (name, baseline_type, baseline_id, candidate_type,
                 candidate_run_id, gate_max_critical, gate_max_rate,
                 gate_result, total, regressions, improvements, unchanged,
                 created_at)
               VALUES ('fail1', 'run', ?, 'run', ?, 0, 0.02,
                       'FAIL', 10, 3, 1, 6, datetime('now'))""",
            (rid, rid))
    rows = {r["code"]: r for r in att.fast_snapshot(p)}
    assert rows["bugs_open"]["count"] == 2
    assert rows["bugs_lonely"]["count"] == 1
    assert rows["bugs_open"]["action"] == {"screen": "bugs"}
    assert rows["runs_hanging"]["count"] == 1
    assert rows["regressions"]["level"] == "critical"
    assert rows["regressions"]["count"] == 3


def test_heavy_conflicts():
    p = _proj([{"q": "как обменять билет на поезд на другую дату"},
               {"q": "как обменять билет на поезд на другую дату!"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    bulk_set_status(p, [ids[1]], "bad")
    rows = {r["code"]: r for r in att.heavy_counts(p)}
    assert rows["conflicts"]["count"] == 2
    assert rows["conflicts"]["action"] == {"screen": "consistency"}


def test_dashboard_block_dispatch():
    _app()
    from dashboard_screen import DashboardScreen
    p = _proj([{"q": "q1", "i": "k1"}])
    calls = []

    class _MW:
        def show_screen(self, key, filters=None):
            calls.append((key, dict(filters or {})))

    class _PW:
        main_window = _MW()

    w = DashboardScreen(p, None)
    try:
        w.parent_window = _PW()
        w.show()
        w.refresh()
        assert w.attention_list.count() >= 1
        w.attention_list.setCurrentRow(0)
        w._open_attention(w.attention_list.item(0))
        assert calls and calls[0][0] == "review"
        assert calls[0][1].get("statuses") == ["unreviewed"]
    finally:
        w.close()


def test_anomaly_flows_into_attention():
    """V2 §7: аналитика нашла отклонение -> внимание показывает -> кейсы."""
    from datetime import datetime as _dt, timedelta as _td, UTC as _UTC
    now = _dt.now(_UTC)
    recent = now.isoformat()
    base_day = (now - _td(days=10)).isoformat()
    p = _proj([{"q": f"q{i}", "i": f"k{i}"} for i in range(24)])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[:11], "good")
    bulk_set_status(p, ids[11:12], "bad")
    bulk_set_status(p, ids[12:18], "good")
    bulk_set_status(p, ids[18:24], "bad")
    with db(p) as conn:
        for cid in ids[:12]:
            conn.execute("UPDATE annotations SET updated_at=? "
                         "WHERE case_id=?", (base_day, cid))
        for cid in ids[12:]:
            conn.execute("UPDATE annotations SET updated_at=? "
                         "WHERE case_id=?", (recent, cid))
    rows = {r["code"]: r for r in att.fast_snapshot(p)}
    assert "anom_bad_spike" in rows
    hit = rows["anom_bad_spike"]
    assert hit["action"]["screen"] == "review"
    assert hit["count"] == len(hit["action"]["filters"]["case_ids"])
    assert set(get_filtered_case_ids(
        p, hit["action"]["filters"])) == \
        set(hit["action"]["filters"]["case_ids"])
