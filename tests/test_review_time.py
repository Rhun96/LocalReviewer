"""Время ревью: схема v22, замеры, статистика."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

from database import db, init_database


def _proj(rows):
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": q} for q in rows])
    return p


def test_schema_v22_columns_and_version():
    p = _proj(["q1"])
    with db(p) as conn:
        ver = conn.execute("PRAGMA user_version").fetchone()[0]
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(annotations)").fetchall()]
    assert ver == 22
    assert "review_started_at" in cols
    assert "review_duration_s" in cols
    # повторный open — идемпотентно, версия та же
    init_database(p)
    with db(p) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 22


def test_duration_helper():
    from analytics_service import review_duration_seconds as _d
    assert _d("2026-09-28T10:00:00+00:00",
              "2026-09-28T10:01:30.500000+00:00") == 90.5
    assert _d("2026-09-28T10:00:00", "2026-09-28T10:00:00") == 0.0
    assert _d("мусор", "2026-09-28T10:00:00") is None
    assert _d(None, None) is None
    assert _d("2026-09-28T10:01:00", "2026-09-28T10:00:00") is None
    assert _d("2026-09-28T10:00:00", "2026-09-28T15:00:01") is None


def test_fmt_duration():
    from analytics_service import fmt_duration as _f
    assert _f(None) == "—"
    assert _f("мусор") == "—"
    assert _f(45) == "45 с"
    assert _f(80) == "1 мин 20 с"
    assert _f(60) == "1 мин"
    assert _f(3900) == "1 ч 05 мин"


def test_stats_empty_and_helpers():
    import analytics_service as an
    p = _proj(["q1", "q2"])
    res = an.review_time_stats(p, None)
    assert res["count"] == 0 and res["avg_s"] is None
    assert res["by_day"] == [] and res["slowest"] == []


def test_stats_counts_only_honest_measurements():
    from datetime import datetime, UTC
    import analytics_service as an
    p = _proj(["q1", "q2", "q3"])
    day = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
        conn.execute("UPDATE annotations SET status='good', "
                     "review_duration_s=60.0, updated_at=? WHERE case_id=?",
                     (day, ids[0]))
        conn.execute("UPDATE annotations SET status='bad', "
                     "review_duration_s=120.0, updated_at=? WHERE case_id=?",
                     (day, ids[1]))
        # третий — без замера (bulk/до v22): в статистику не входит
    res = an.review_time_stats(p, None)
    assert res["count"] == 2
    assert res["avg_s"] == 90.0
    assert res["median_s"] == 90.0
    assert res["total_s"] == 180.0
    assert res["by_day"][0]["n"] == 2
    assert res["slowest"][0]["duration_s"] == 120.0
    assert an.fmt_duration(res["avg_s"]) == "1 мин 30 с"


def test_hooks_stamp_and_measure():
    """load_case ставит старт, set_status пишет длительность."""
    from datetime import datetime, timedelta, UTC
    from PySide6.QtWidgets import QApplication
    from review_screen import ReviewScreen
    QApplication.instance() or QApplication([])
    p = _proj(["вопрос один", "вопрос два"])
    w = ReviewScreen(p)
    try:
        w.load_case(0)
        cid = w.current_case_id
        with db(p) as conn:
            row = conn.execute("SELECT review_started_at, "
                               "review_duration_s FROM annotations "
                               "WHERE case_id=?", (cid,)).fetchone()
            assert row["review_started_at"]
            assert row["review_duration_s"] is None
            back = (datetime.now(UTC) - timedelta(seconds=90)).isoformat()
            conn.execute("UPDATE annotations SET review_started_at=? "
                         "WHERE case_id=?", (back, cid))
        w.set_status("good")
        with db(p) as conn:
            dur = conn.execute("SELECT review_duration_s FROM annotations "
                               "WHERE case_id=?", (cid,)).fetchone()[0]
        assert dur is not None and 85 <= dur <= 95
    finally:
        w.close()
