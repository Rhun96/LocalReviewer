"""Гигиена: сироты (отчёт + чистка) и locked-флаг датасетов."""
import tempfile

import pytest

from bulk_operation_service import bulk_add_tag, bulk_set_status
from database import init_database
from filter_service import get_filtered_case_ids
from importer import find_file_by_name, import_file
from tag_service import create_tag


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    m = {"q": "primary_text"}
    import_file(tmp, "live.xlsx", "excel", "S", 0, m,
                [{"q": "qa1"}, {"q": "qa2"}])
    import_file(tmp, "dead.xlsx", "excel", "S", 0, m,
                [{"q": "позвоните +7 (900) 111-22-33"},
                 {"q": "qd2"}, {"q": "qd3"}])
    return tmp


def _kill_file(proj, name):
    from database import db as _db
    with _db(proj) as conn:
        fid = find_file_by_name(proj, name)["file_id"]
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("DELETE FROM files WHERE file_id=?", (fid,))


def test_orphan_report_and_purge():
    import maintenance_service as maint
    from autocheck_service import run_autochecks
    from review_queue_service import queue_stats
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    tid = create_tag(p, "T1")
    bulk_add_tag(p, ids, tid)
    run_autochecks(p)
    _kill_file(p, "dead.xlsx")
    rep = maint.integrity_report(p)
    assert (rep["files"], rep["cases"], rep["orphan_cases"]) == (1, 5, 3), rep
    assert rep["children"].get("annotations", 0) >= 3
    assert rep["children"].get("case_checks", 0) >= 1
    assert not rep["healthy"]
    assert queue_stats(p)["total"] == 2  # счётчики сирот уже не видят (JOIN files)
    done = maint.purge_orphans(p)
    assert done["orphan_cases"] == 3, done
    rep2 = maint.integrity_report(p)
    assert rep2["healthy"] and rep2["cases"] == 2
    assert queue_stats(p)["total"] == 2
    assert maint.purge_orphans(p)["orphan_cases"] == 0


def test_dataset_lock_guards():
    from dataset_service import (create_dataset, create_version,
                                 delete_version, freeze_version,
                                 set_dataset_locked)
    p = _proj()
    ds = create_dataset(p, "G", description="", dataset_type="golden")
    v1 = create_version(p, ds)
    set_dataset_locked(p, ds, True)
    with pytest.raises(ValueError):
        create_version(p, ds)
    with pytest.raises(ValueError):
        delete_version(p, v1)
    freeze_version(p, v1)  # freeze на запертом разрешён
    set_dataset_locked(p, ds, False)
    v2 = create_version(p, ds)
    assert v2 != v1
    with pytest.raises(ValueError):
        set_dataset_locked(p, 999999, True)
