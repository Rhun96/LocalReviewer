"""V2.1 §15: assertions PASS/FAIL/SKIPPED, пачка, кривой regex, отмена."""
import tempfile

import pytest
from database import init_database
from importer import import_file
import model_run_service as m
import regression_assertion_service as ra
from workers import Cancelled


def _proj_with_run():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "base.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    rid = m.create_run(tmp, "v1", "mx")
    m.import_run_rows(tmp, rid, [
        {"source_id": "k1", "answer": "TICKET-1 ready https://x.y"},
        {"source_id": "k2", "answer": ""},
    ])
    return tmp, rid


def test_crud_validation():
    import regression_assertion_service as a
    import tempfile as _t
    from database import init_database as _init
    p = _t.mkdtemp()
    _init(p)
    aid = a.create_assertion(p, "NE", "not_empty")
    assert aid > 0
    with pytest.raises(ValueError):
        a.create_assertion(p, "X", "nope")
    with pytest.raises(ValueError):
        a.create_assertion(p, "", "not_empty")
    with pytest.raises(ValueError):
        a.create_assertion(p, "X", "not_empty", severity="blocker")
    a.update_assertion(p, aid, enabled=False)
    assert a.list_assertions(p, enabled_only=True) == []
    assert len(a.list_assertions(p)) == 1
    a.delete_assertion(p, aid)
    with pytest.raises(ValueError):
        a.delete_assertion(p, aid)


def test_evaluate_matrix():
    E = ra.evaluate
    assert E({"atype": "not_empty"}, "x")[0] == "PASS"
    assert E({"atype": "not_empty"}, "   ")[0] == "FAIL"
    assert E({"atype": "not_empty"}, None)[0] == "FAIL"
    assert E({"atype": "min_length", "params": {"n": 3}}, "abcd")[0] == "PASS"
    assert E({"atype": "min_length", "params": {"n": 5}}, "abcd")[0] == "FAIL"
    assert E({"atype": "min_length", "params": {}}, "abcd")[0] == "SKIPPED"
    assert E({"atype": "max_length", "params": {"n": 2}}, "abcd")[0] == "FAIL"
    assert E({"atype": "contains", "params": {"text": "T"}}, "T-1")[0] == "PASS"
    assert E({"atype": "contains", "params": {"text": "Z"}}, "T-1")[0] == "FAIL"
    assert E({"atype": "contains", "params": {"text": ""}}, "T-1")[0] == "SKIPPED"
    assert E({"atype": "not_contains", "params": {"text": "Z"}}, "T")[0] == "PASS"
    assert E({"atype": "regex", "params": {"pattern": r"T-\d+"}}, "T-1")[0] == "PASS"
    assert E({"atype": "regex", "params": {"pattern": "([a-z"}}, "abc")[0] == "SKIPPED"
    assert E({"atype": "exact_match", "params": {"text": "a"}}, "a")[0] == "PASS"
    assert E({"atype": "exact_match", "params": {"text": "a"}}, "b")[0] == "FAIL"
    assert E({"atype": "contains_url"}, "see https://x.y")[0] == "PASS"
    assert E({"atype": "contains_url"}, "no link")[0] == "FAIL"
    assert E({"atype": "contains_email"}, "a@b.cc")[0] == "PASS"
    assert E({"atype": "contains_phone"}, "+7 900 123-45-67")[0] == "PASS"
    assert E({"atype": "contains_keyword", "params": {"keywords": ["vip", "ticket"]}},
             "VIP client")[0] == "PASS"
    assert E({"atype": "contains_keyword", "params": {}}, "x")[0] == "SKIPPED"
    assert E({"atype": "no_service_text"}, "normal answer")[0] == "PASS"
    assert E({"atype": "no_service_text"}, "SYSTEM: do")[0] == "FAIL"
    assert E({"atype": "mystery"}, "x")[0] == "SKIPPED"


def test_run_batch_and_summary():
    p, rid = _proj_with_run()
    ra.create_assertion(p, "NE", "not_empty")
    ra.create_assertion(p, "T", "contains", {"text": "TICKET"},
                        severity="critical")
    res = ra.run_assertions(p, rid)
    assert set(res) == {"src:k1", "src:k2"}
    assert res["src:k1"]["failed"] == 0 and res["src:k1"]["passed"] == 2
    assert res["src:k2"]["failed"] == 2  # пустой ответ валит обе
    s = ra.summarize(res)
    assert s == {"checked": 2, "failed": 1, "failed_critical": 1}


def test_run_cancelled():
    p, rid = _proj_with_run()
    ra.create_assertion(p, "NE", "not_empty")
    with pytest.raises(Cancelled):
        ra.run_assertions(p, rid, cancel_flag=lambda: True)


def test_disabled_not_run():
    p, rid = _proj_with_run()
    aid = ra.create_assertion(p, "NE", "not_empty", enabled=False)
    res = ra.run_assertions(p, rid)
    assert all(v["passed"] == 0 and v["failed"] == 0 for v in res.values())
    ra.update_assertion(p, aid, enabled=True)
    res2 = ra.run_assertions(p, rid)
    assert res2["src:k1"]["passed"] == 1
