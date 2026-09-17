"""JSONL-экспорт: схема, scope, доп. поля, UTF-8, валидность строк."""
import json
import os
import tempfile

import pytest
from database import db, init_database
from importer import import_file
from bulk_operation_service import bulk_add_tag, bulk_set_comment, bulk_set_status
from filter_service import get_filtered_case_ids
from export_service import JSONL_BASE, export_results_jsonl


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text", "i": "source_id",
                 "g": "group_name"},
                [{"q": "вопрос раз?", "a": "ответ раз", "i": "k1", "g": "grp"},
                 {"q": "вопрос два?", "a": "ответ два", "i": "k2", "g": "grp"}])
    return tmp


def _read_lines(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def test_jsonl_schema_and_scope():
    from database import db
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    bulk_set_comment(p, [ids[0]], "коммент ✓", mode="replace")
    from taxonomy_service import list_categories, set_case_error
    cats = list_categories(p)
    set_case_error(p, ids[0], cats[0]["category_id"],
                   cats[0]["subs"][0]["category_id"], "high")
    tid = None
    with db(p) as conn:
        tid = conn.execute("SELECT tag_id FROM tags WHERE tag_code='facts'"
                           ).fetchone()["tag_id"]
    bulk_add_tag(p, ids, tid)
    out = os.path.join(p, "r.jsonl")
    assert export_results_jsonl(p, out) == 2
    rows = _read_lines(out)
    assert len(rows) == 2
    for r in rows:
        assert list(r.keys()) == list(JSONL_BASE)  # стабильный порядок
    first = next(r for r in rows if r["id"] == "k1")
    assert first["query"] == "вопрос раз?"
    assert first["status"] == "bad" and first["comment"] == "коммент ✓"
    assert first["category"] == cats[0]["name"]
    assert first["severity"] == "high"
    # scope по файлу
    with db(p) as conn:
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    out2 = os.path.join(p, "r2.jsonl")
    assert export_results_jsonl(p, out2, file_id=fid) == 2
    assert len(_read_lines(out2)) == 2


def test_jsonl_extra_fields_and_fallback_id():
    p = _proj()
    out = os.path.join(p, "r.jsonl")
    export_results_jsonl(p, out, extra_fields=["tags", "group", "file",
                                               "source_id", "reviewed_at",
                                               "nope"])
    rows = _read_lines(out)
    assert rows[0]["tags"] == ["facts"] or isinstance(rows[0]["tags"], list)
    assert rows[0]["group"] == "grp" and rows[0]["file"] == "f.xlsx"
    assert rows[0]["source_id"] == "k1"
    assert "nope" not in rows[0]
    # кейс без source_id → id = case_id строкой
    tmp2 = tempfile.mkdtemp()
    init_database(tmp2)
    import_file(tmp2, "g.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "без айди"}])
    out3 = os.path.join(tmp2, "r.jsonl")
    export_results_jsonl(tmp2, out3)
    rows3 = _read_lines(out3)
    from filter_service import get_filtered_case_ids as _ids
    assert rows3[0]["id"] == str(_ids(tmp2, {})[0])


def _ann_proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "раз?", "i": "k1"}, {"q": "два?", "i": "k2"}])
    return tmp


def test_annotations_export_preview_merge_update():
    import annotation_io_service as aio
    from taxonomy_service import list_categories
    p = _ann_proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    bulk_set_status(p, [ids[1]], "good")
    bulk_set_comment(p, [ids[0]], "плохо", mode="replace")
    cats = list_categories(p)
    from taxonomy_service import set_case_error
    set_case_error(p, ids[0], cats[0]["category_id"],
                   cats[0]["subs"][0]["category_id"], "high")
    out = os.path.join(p, "ann.jsonl")
    assert aio.export_annotations(p, out) == 2
    rows, errors = aio.read_annotation_file(out)
    assert len(rows) == 2 and not errors
    assert rows[0]["category"] == cats[0]["code"]
    # второй проект: один кейс размечен иначе, второго кейса нет
    q = _ann_proj()
    qids = get_filtered_case_ids(q, {})
    bulk_set_status(q, [qids[0]], "good")
    prev = aio.preview_import(q, rows)
    assert prev["total"] == 2
    assert len(prev["conflicts"]) == 1  # good vs bad
    assert len(prev["new"]) == 1  # k2 чистый
    assert prev["conflicts"][0]["conflict_fields"] == ["status"]
    # merge: конфликт не трогаем, новое забираем
    res = aio.apply_import(q, prev, "merge")
    assert res["applied"] == 1
    with db(q) as conn:
        st = conn.execute("SELECT status FROM annotations WHERE case_id=?",
                          (qids[0],)).fetchone()["status"]
    assert st == "good"
    # update: конфликт перезаписывается
    res2 = aio.apply_import(q, prev, "update")
    assert res2["applied"] == 2
    with db(q) as conn:
        st = conn.execute("SELECT status FROM annotations WHERE case_id=?",
                          (qids[0],)).fetchone()["status"]
    assert st == "bad"
    # битые строки и неизвестные категории
    bad_rows = [{"id": "k1", "status": "bad!!"},
                {"id": "zzz"},
                {"id": "k1", "status": "good", "category": "nope"},
                {"noid": 1},
                "строка"]
    prev2 = aio.preview_import(q, bad_rows)
    assert len(prev2["errors"]) == 3  # статус, категория, не-объект
    assert len(prev2["not_found"]) == 2  # zzz + без id
    with pytest.raises(ValueError):
        aio.apply_import(q, prev2, "replace")
