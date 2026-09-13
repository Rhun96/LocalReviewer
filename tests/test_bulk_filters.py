"""Тесты 0.2: миграции, bulk-операции, сохранённые фильтры."""
import tempfile
from database import init_database
from bulk_operation_service import bulk_set_status, bulk_set_comment, undo_bulk_operation
from filter_service import get_filtered_case_ids
from importer import import_file
from saved_filter_service import save_filter, list_saved_filters, delete_saved_filter


def _proj(n=30):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    data = [{"q": f"вопрос {i}", "a": f"ответ {i}"} for i in range(n)]
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text"}, data)
    return tmp


def test_migration_v3_tables():
    import sqlite3
    from pathlib import Path
    p = _proj(5)
    conn = sqlite3.connect(str(Path(p) / "project.sqlite"))
    try:
        tables = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        assert "bulk_operations" in tables
        assert "saved_filters" in tables
        cols = [r[1] for r in conn.execute("PRAGMA table_info(history)").fetchall()]
        assert "operation_id" in cols
        assert conn.execute("PRAGMA user_version").fetchone()[0] >= 4
    finally:
        conn.close()


def test_bulk_status_and_undo():
    p = _proj(100)
    ids = get_filtered_case_ids(p, {})
    assert len(ids) == 100
    done = bulk_set_status(p, ids[:50], "bad")
    assert done == 50
    bad = get_filtered_case_ids(p, {"statuses": ["bad"]})
    assert len(bad) == 50
    # undo последней операции (50 кейсов)
    import sqlite3
    from pathlib import Path
    conn = sqlite3.connect(str(Path(p) / "project.sqlite"))
    try:
        op = conn.execute("SELECT operation_id FROM bulk_operations ORDER BY operation_id DESC LIMIT 1").fetchone()[0]
    finally:
        conn.close()
    undone = undo_bulk_operation(p, op)
    assert undone == 50
    assert len(get_filtered_case_ids(p, {"statuses": ["bad"]})) == 0


def test_bulk_comment_modes():
    p = _proj(3)
    ids = get_filtered_case_ids(p, {})
    assert bulk_set_comment(p, ids, "hello", mode="replace") == 3
    assert bulk_set_comment(p, ids, "hello", mode="replace") == 0  # без изменений
    assert bulk_set_comment(p, ids, "more", mode="append") == 3
    assert bulk_set_comment(p, ids, "x", mode="clear") == 3


def test_saved_filters():
    p = _proj(3)
    fid = save_filter(p, "bad only", {"statuses": ["bad"]})
    assert fid > 0
    items = list_saved_filters(p)
    assert any(i["name"] == "bad only" for i in items)
    assert delete_saved_filter(p, fid) is True
