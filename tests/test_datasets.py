"""Датасеты: создание, версии, freeze, сравнение."""
import tempfile
from database import init_database
from bulk_operation_service import bulk_set_status
from dataset_service import (
    compare_versions, create_dataset, create_version, freeze_version,
    list_datasets, list_versions,
)
from filter_service import get_filtered_case_ids
from importer import import_file


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": f"вопрос {i}"} for i in range(6)])
    return tmp


def test_versions_and_freeze():
    p = _proj()
    ds = create_dataset(p, "Golden — Авиа", dataset_type="golden")
    assert len(list_datasets(p)) == 1
    v1 = create_version(p, ds, None, "первый снимок")
    versions = list_versions(p, ds)
    assert len(versions) == 1 and versions[0]["status"] == "draft"
    assert versions[0]["case_count"] == 6
    freeze_version(p, v1)
    assert list_versions(p, ds)[0]["status"] == "frozen"
    assert list_versions(p, ds)[0]["frozen_at"]
    try:
        create_dataset(p, "Golden — Авиа")
        raise AssertionError("should raise")
    except ValueError:
        pass


def test_compare():
    p = _proj()
    ds = create_dataset(p, "D")
    v1 = create_version(p, ds)
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[:2], "bad")
    bulk_set_status(p, ids[2:4], "good")
    v2 = create_version(p, ds)
    res = compare_versions(p, v1, v2)
    assert res["counts"]["changed"] == 4, res["counts"]
    assert res["counts"]["unchanged"] == 2
    assert res["counts"]["added"] == 0 and res["counts"]["removed"] == 0
    assert res["counts"]["conflicted"] == 0
    assert all(d["before"] == "unreviewed" for d in res["details"])
    # снимок неизменяем: позднейшие правки v2 не трогают
    bulk_set_status(p, ids[4:], "bad")
    res2 = compare_versions(p, v1, v2)
    assert res2["counts"] == res["counts"]


def test_key_match_across_files():
    """Два файла с общими source_id: сравнение идёт по ключам, а не case_id."""
    import tempfile
    from database import init_database
    from importer import import_file

    tmp = tempfile.mkdtemp()
    init_database(tmp)
    m = {"sid": "source_id", "q": "primary_text"}
    import_file(tmp, "a.xlsx", "excel", "S", 0, m,
                [{"sid": "k1", "q": "q1"}, {"sid": "k2", "q": "q2"}])
    ds = create_dataset(tmp, "D")
    v1 = create_version(tmp, ds)
    import_file(tmp, "b.xlsx", "excel", "S", 0, m,
                [{"sid": "k1", "q": "q1 new"}, {"sid": "k3", "q": "q3"}])
    from database import db
    with db(tmp) as conn:
        fid_b = conn.execute("SELECT file_id FROM files WHERE file_name='b.xlsx'"
                             ).fetchone()["file_id"]
    v2 = create_version(tmp, ds, file_id=fid_b)
    res = compare_versions(tmp, v1, v2)
    assert res["counts"]["added"] == 1, res["counts"]  # k3
    assert res["counts"]["removed"] == 1  # k2
    # k1: текст изменился (q1 -> q1 new) — считается changed (сравнение по
    # статусу+комментарию+ошибке+тегам+тексту), а не unchanged.
    assert res["counts"]["changed"] == 1, res["counts"]
    assert res["counts"]["unchanged"] == 0
    assert res["details"][0]["changes"] == ["text"] or "text" in res["details"][0]["changes"]
    # слепок только из файла B
    versions = list_versions(tmp, ds)
    assert next(v for v in versions if v["version_id"] == v2)["case_count"] == 2


def test_conflicts():
    """Задвоенный source_id: ключ встречается дважды — конфликт, а не молчание."""
    import tempfile
    from database import init_database
    from importer import import_file

    tmp = tempfile.mkdtemp()
    init_database(tmp)
    m = {"sid": "source_id", "q": "primary_text"}
    import_file(tmp, "a.xlsx", "excel", "S", 0, m,
                [{"sid": "k1", "q": "one"}, {"sid": "k2", "q": "two"}])
    ds = create_dataset(tmp, "D")
    v1 = create_version(tmp, ds)
    import_file(tmp, "b.xlsx", "excel", "S", 0, m,
                [{"sid": "k1", "q": "uno"}, {"sid": "k1", "q": "dos"}])
    from database import db
    with db(tmp) as conn:
        fid_b = conn.execute("SELECT file_id FROM files WHERE file_name='b.xlsx'"
                             ).fetchone()["file_id"]
    v2 = create_version(tmp, ds, file_id=fid_b)
    res = compare_versions(tmp, v1, v2)
    assert res["counts"]["conflicted"] == 1, res["counts"]
    assert res["counts"]["removed"] == 1  # k2
    cf = res["conflicted"][0]
    assert len(cf["b_cases"]) == 2
