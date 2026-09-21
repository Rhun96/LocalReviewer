"""V2.1 P0 §5: сохранение/восстановление рабочего состояния, сброс."""
import tempfile

from database import init_database
from importer import import_file
import session_service as ss


def _proj(n=2):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text"},
                [{"q": f"q{i}", "a": f"a{i}"} for i in range(n)])
    return tmp


def test_save_and_restore_roundtrip():
    p = _proj()
    ss.save_project_session(p, {"screen": "review", "queue": "unreviewed",
                                "filters": {"statuses": ["unreviewed"]},
                                "columns": ["ID", "Запрос"], "sort": "import",
                                "page": 0, "view": 1, "case_id": 1})
    st = ss.load_project_session(p)
    assert st["screen"] == "review"
    assert st["queue"] == "unreviewed"
    assert st["filters"] == {"statuses": ["unreviewed"]}
    assert st["columns"] == ["ID", "Запрос"]
    assert st["view"] == 1
    assert st["case_id"] == 1


def test_missing_case_dropped_not_fatal():
    p = _proj()
    ss.save_project_session(p, {"screen": "review", "case_id": 999999})
    st = ss.load_project_session(p)
    assert st.get("case_id") is None
    assert st.get("screen") == "review"  # живое сохранилось


def test_corrupt_filter_not_restored():
    from database import db
    p = _proj()
    with db(p) as conn:
        conn.execute("INSERT INTO settings (key, value, updated_at)"
                     " VALUES ('sess_filters', 'not-json{{{', 'x')")
    st = ss.load_project_session(p)
    assert "filters" not in st


def test_clear_project_session():
    p = _proj()
    ss.save_project_session(p, {"screen": "review", "queue": "normal"})
    ss.clear_project_session(p)
    assert ss.load_project_session(p) == {}


def test_unknown_project_returns_empty():
    assert ss.load_project_session("Z:/no/such/project") == {}
    assert ss.get_last_project() is None or isinstance(
        ss.get_last_project(), str)
