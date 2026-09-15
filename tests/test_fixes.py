"""Фиксы критического ревью: freeze, compare, undo, импорт, очередь, шаблоны."""
import tempfile

import pytest
from database import db, init_database
from importer import import_file


def _proj(n=4):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": f"вопрос {i}"} for i in range(n)])
    return tmp


def test_import_returns_triplet_and_rowcount_is_total():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    fid, imp, skipped = import_file(
        tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
        [{"q": "a"}, {"q": "a"}])  # внутрифайловый дубль по хэшу
    assert imp == 1 and skipped == 1
    with db(tmp) as conn:
        rc = conn.execute("SELECT row_count FROM files WHERE file_id=?",
                          (fid,)).fetchone()["row_count"]
    assert rc == 2  # исходное число строк, а не imported


def test_freeze_is_immutable():
    from dataset_service import (create_dataset, create_version, freeze_version,
                                 set_version_status)
    p = _proj(2)
    ds = create_dataset(p, "D")
    v = create_version(p, ds)
    freeze_version(p, v)
    with pytest.raises(ValueError):
        set_version_status(p, v, "draft")
    with pytest.raises(ValueError):
        set_version_status(p, v, "review")
    # frozen -> archived разрешён
    set_version_status(p, v, "archived")


def test_compare_catches_comment_error_tags_text():
    from dataset_service import (compare_versions, create_dataset, create_version)
    from filter_service import get_filtered_case_ids
    from bulk_operation_service import bulk_set_comment
    from taxonomy_service import list_categories, set_case_error
    p = _proj(3)
    ds = create_dataset(p, "D")
    v1 = create_version(p, ds)
    ids = get_filtered_case_ids(p, {})
    bulk_set_comment(p, [ids[0]], "новый комментарий", mode="replace")
    cats = list_categories(p)
    set_case_error(p, ids[1], cats[0]["category_id"],
                   cats[0]["subs"][0]["category_id"], "high")
    v2 = create_version(p, ds)
    res = compare_versions(p, v1, v2)
    by_id = {d["case_id"]: d for d in res["details"]}
    assert by_id[ids[0]]["changes"] == ["comment"]
    assert "error" in by_id[ids[1]]["changes"]
    assert res["counts"]["unchanged"] == 1


def test_undo_does_not_clobber_manual_edit():
    from bulk_operation_service import bulk_set_status, undo_bulk_operation
    from filter_service import get_filtered_case_ids
    from database import db as _db
    p = _proj(2)
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    # Ручная правка после bulk
    bulk_set_status(p, [ids[0]], "bad")
    with _db(p) as conn:
        op = conn.execute("SELECT operation_id FROM bulk_operations "
                          "WHERE undone=0 ORDER BY operation_id DESC LIMIT 1"
                          ).fetchone()["operation_id"]
        first_op = conn.execute("SELECT operation_id FROM bulk_operations "
                                "ORDER BY operation_id ASC LIMIT 1").fetchone()["operation_id"]
    done = undo_bulk_operation(p, first_op)
    # ids[0] вручную ушёл в bad — его откат пропускается
    assert done == 1
    with _db(p) as conn:
        st = {r["case_id"]: r["status"] for r in conn.execute(
            "SELECT case_id, status FROM annotations")}
    assert st[ids[0]] == "bad"
    assert st[ids[1]] == "unreviewed"
    _ = op


def test_queue_uses_max_severity():
    from review_queue_service import build_queue
    from autocheck_service import run_autochecks
    p = _proj(3)
    run_autochecks(p)
    ids, _ = build_queue(p, mode="problematic")
    assert len(ids) == 3


def test_duplicate_across_batches_found():
    from autocheck_service import run_autochecks
    from database import db as _db
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    # Одинаковый primary/response, но разный raw (extra-колонка):
    # импортёр сохраняет все 5 (content_hash разный), autocheck видит дубли.
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "same text here!!", "extra": i} for i in range(5)])
    res = run_autochecks(tmp)
    assert res["total_checked"] == 5
    with _db(tmp) as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM case_checks "
                         "WHERE check_code='duplicate'").fetchone()["c"]
    assert n == 5, "дубль должен найтись по всей выборке, а не внутри батча"


def test_templates_render_vars():
    from templates_service import render_template, template_vars
    t = "В ответе отсутствует {missing_part} для {product} (кейс {case_id})."
    assert set(template_vars(t)) == {"missing_part", "product", "case_id"}
    out = render_template(t, {"missing_part": "тариф", "product": "Авиа",
                              "case_id": 7})
    assert out == "В ответе отсутствует тариф для Авиа (кейс 7)."
    # Неизвестные остаются как есть — не придумываем
    assert render_template("Нужно {expected}", {}) == "Нужно {expected}"


def test_filter_new_keys_do_not_break_old():
    from filter_service import count_filtered_cases
    p = _proj(2)
    assert count_filtered_cases(p, {"checks": ["too_short"]}) >= 0
    assert count_filtered_cases(p, {"check_severities": ["warning"]}) >= 0
    assert count_filtered_cases(p, {"error_severities": ["high"]}) == 0
