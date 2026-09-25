"""Миграции: цепочка v10 -> текущая без потери данных."""
import sqlite3
import tempfile
from pathlib import Path

from database import SCHEMA_VERSION, init_database
from importer import import_file
from bulk_operation_service import bulk_set_status
from filter_service import get_filtered_case_ids


def test_upgrade_chain_v10_to_current():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "раз"}, {"q": "два"}])
    ids = get_filtered_case_ids(tmp, {})
    assert bulk_set_status(tmp, ids[:1], "good") == 1

    # Эмулируем старую БД: сносим таблицы v11+, колонку viewed, версию -> 10.
    con = sqlite3.connect(str(Path(tmp) / "project.sqlite"))
    for t in ("case_check_verdicts", "model_runs", "run_answers",
              "run_preferences", "output_reviews", "regression_runs",
              "regression_results"):
        con.execute(f"DROP TABLE IF EXISTS {t}")
    cols = [r[1] for r in con.execute("PRAGMA table_info(annotations)").fetchall()]
    if "viewed" in cols:
        con.execute("ALTER TABLE annotations DROP COLUMN viewed")
    con.execute("PRAGMA user_version=10")
    con.commit()
    con.close()

    init_database(tmp)  # должна дойти до текущей версии без потерь
    con = sqlite3.connect(str(Path(tmp) / "project.sqlite"))
    try:
        assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert con.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 2
        assert con.execute("SELECT status FROM annotations WHERE case_id=?",
                           (ids[0],)).fetchone()[0] == "good"
        cols = [r[1] for r in con.execute("PRAGMA table_info(annotations)").fetchall()]
        assert "viewed" in cols
        sql = con.execute("SELECT sql FROM sqlite_master WHERE name='annotations'"
                          ).fetchone()[0].upper()
        assert "CHECK" not in sql  # свои статусы разрешены
        for t in ("case_check_verdicts", "model_runs", "run_answers",
                  "run_preferences", "output_reviews", "regression_runs",
                  "regression_results"):
            assert con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (t,)).fetchone(), t
    finally:
        con.close()
    # Свои коды пишутся после миграции.
    assert bulk_set_status(tmp, ids[1:], "custom_code") == 1
    assert len(get_filtered_case_ids(tmp, {"statuses": ["custom_code"]})) == 1


def test_delete_version_and_file_lookup():
    import os
    from dataset_service import (create_dataset, create_version, delete_version,
                                 freeze_version, list_versions)
    from importer import find_file_by_name
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    src = os.path.join(tmp, "f.txt")
    with open(src, "w", encoding="utf-8") as f:
        f.write("x")
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "раз"}])
    # хэш считается от реального файла; здесь — поиск по имени
    found = find_file_by_name(tmp, "f.xlsx")
    assert found and found["row_count"] == 1
    assert find_file_by_name(tmp, "nope.xlsx") is None
    ds = create_dataset(tmp, "D")
    v1 = create_version(tmp, ds)
    v2 = create_version(tmp, ds)
    assert len(list_versions(tmp, ds)) == 2
    delete_version(tmp, v1)
    rest = list_versions(tmp, ds)
    assert len(rest) == 1 and rest[0]["version_id"] == v2
    freeze_version(tmp, v2)
    delete_version(tmp, v2)  # frozen тоже удаляется явно
    assert list_versions(tmp, ds) == []
    import pytest as _pytest
    with _pytest.raises(ValueError):
        delete_version(tmp, v2)


def test_delete_dataset_cleans_versions_and_keeps_marks():
    import tempfile
    from database import init_database, db
    from dataset_service import (create_dataset, create_version,
                                 delete_dataset, list_datasets,
                                 set_dataset_locked)
    from importer import import_file
    import pytest as _pytest
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "раз"}])
    ds = create_dataset(tmp, "D")
    v1 = create_version(tmp, ds)
    v2 = create_version(tmp, ds)
    assert len(list_datasets(tmp)) == 1
    done = delete_dataset(tmp, ds)
    assert done["versions"] == 2
    assert list_datasets(tmp) == []
    with db(tmp) as conn:
        assert conn.execute("SELECT COUNT(*) FROM dataset_versions").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM dataset_cases").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0] == 1
    # запертый — только через отпирание
    ds2 = create_dataset(tmp, "L")
    create_version(tmp, ds2)
    set_dataset_locked(tmp, ds2, True)
    with _pytest.raises(ValueError):
        delete_dataset(tmp, ds2)
    set_dataset_locked(tmp, ds2, False)
    delete_dataset(tmp, ds2)
    assert list_datasets(tmp) == []
    _ = v1, v2


def test_tag_create_delete_rules():
    from tag_service import create_tag, delete_tag, list_tags, usage_count
    import pytest as _pytest
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    tid = create_tag(tmp, "Мой тег")
    assert any(t["tag_id"] == tid for t in list_tags(tmp))
    with _pytest.raises(ValueError):
        create_tag(tmp, "Мой тег")  # дубль
    with _pytest.raises(ValueError):
        create_tag(tmp, "")
    delete_tag(tmp, tid)  # неиспользуемый удаляется
    assert all(t["tag_id"] != tid for t in list_tags(tmp))
    tid2 = create_tag(tmp, "Рабочий")
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "раз"}])
    from bulk_operation_service import bulk_add_tag
    from filter_service import get_filtered_case_ids
    ids = get_filtered_case_ids(tmp, {})
    bulk_add_tag(tmp, ids, tid2)
    assert usage_count(tmp, tid2) == 1
    with _pytest.raises(ValueError):
        delete_tag(tmp, tid2)  # используемый — блок с числом
    with _pytest.raises(ValueError):
        delete_tag(tmp, 999999)
