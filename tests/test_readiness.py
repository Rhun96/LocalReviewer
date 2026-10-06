"""Готовность набора: вердикт, проверки, drill-фильтры, повтор."""
import tempfile

from PySide6.QtWidgets import QApplication

from bulk_operation_service import bulk_set_status
from database import init_database
from filter_service import count_filtered_cases, get_filtered_case_ids
from importer import import_file
import dataset_readiness_service as readiness


def _proj(rows):
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"}, rows)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def _by_code(res):
    return {c["code"]: c for c in res["checks"]}


def test_clean_project_is_ready():
    p = _proj([{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    res = readiness.check_readiness(p)
    assert res["verdict"] == "ready"
    assert res["verdict_text"] == "Готов"
    assert _by_code(res)["unreviewed"]["count"] == 0
    # повтор стабилен
    again = readiness.check_readiness(p)
    assert again["verdict"] == "ready"
    assert [c["code"] for c in again["checks"]] == [
        c["code"] for c in res["checks"]]


def test_bad_without_cause_is_critical():
    p = _proj([{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    bulk_set_status(p, [ids[1]], "good")
    res = readiness.check_readiness(p)
    assert res["verdict"] == "issues"
    bad = _by_code(res)["bad_no_cause"]
    assert bad["level"] == "critical" and bad["count"] == 1
    # drill ведёт ровно к тем же кейсам
    assert count_filtered_cases(p, bad["filters"]) == 1


def test_ids_and_unreviewed():
    p = _proj([{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k1"},
               {"q": "q3", "i": ""}])
    res = readiness.check_readiness(p)
    assert res["verdict"] == "issues"  # 3 неразмеченных — критично
    assert _by_code(res)["unreviewed"]["count"] == 3
    assert _by_code(res)["dup_id"]["count"] == 2
    assert _by_code(res)["empty_id"]["count"] == 1
    assert _by_code(res)["duplicates"]["level"] == "warning"


def test_dialog_builds_and_preselects_file():
    _app()
    from database import db
    from readiness_dialog import ReadinessDialog
    p = _proj([{"q": "q1", "i": "k1"}])
    with db(p) as conn:
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    d = ReadinessDialog(p, fid, None)
    try:
        d.show()
        assert d.scope_combo.currentData() == fid
        assert d.dup_spin.value() == 90
    finally:
        d.close()
