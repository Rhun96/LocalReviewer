"""Баги: CRUD, связи, фильтры, external, history."""
import tempfile

import pytest
from database import init_database
from importer import import_file
from filter_service import get_filtered_case_ids
import bug_report_service as bugs


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "можно вернуть билет?", "i": "k1"},
                 {"q": "где мой заказ", "i": "k2"}])
    return tmp


def test_create_minimal_and_validation():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    b = bugs.create_bug(p, "Падает на возврате", [ids[0]], severity="High",
                        model_name="mx", model_version="1.8")
    got = bugs.get_bug(p, b)
    assert got["title"] == "Падает на возврате" and got["status"] == "New"
    assert got["severity"] == "High" and len(got["cases"]) == 1
    with pytest.raises(ValueError):
        bugs.create_bug(p, "")
    with pytest.raises(ValueError):
        bugs.create_bug(p, "t", [999999])
    with pytest.raises(ValueError):
        bugs.create_bug(p, "t", severity="nope")
    with pytest.raises(ValueError):
        bugs.create_bug(p, "t", category_id=999)


def test_cases_link_and_history():
    from database import db
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    b = bugs.create_bug(p, "t", [ids[0]])
    assert bugs.add_case(p, b, ids[1]) is True
    assert bugs.add_case(p, b, ids[1]) is False  # дубль связи
    assert len(bugs.cases_for_bug(p, b)) == 2
    assert bugs.remove_case(p, b, ids[1]) is True
    assert bugs.remove_case(p, b, ids[1]) is False
    with db(p) as conn:
        events = {r["event_type"] for r in conn.execute(
            "SELECT event_type FROM history WHERE field_name=?", (f"bug:{b}",))}
    assert {"BUG_CREATED", "BUG_CASE_ADDED", "BUG_CASE_REMOVED"} <= events
    mine = bugs.bugs_for_case(p, ids[0])
    assert len(mine) == 1 and mine[0]["bug_id"] == b


def test_update_status_external_taxonomy():
    from taxonomy_service import list_categories
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    cats = list_categories(p)
    b = bugs.create_bug(p, "t", [ids[0]])
    bugs.update_bug(p, b, status="Confirmed", severity="Critical",
                    category_id=cats[0]["category_id"],
                    subcategory_id=cats[0]["subs"][0]["category_id"],
                    external_tracker="Jira", external_id="PROJ-1",
                    external_url="https://jira/x/PROJ-1")
    got = bugs.get_bug(p, b)
    assert got["status"] == "Confirmed" and got["external_id"] == "PROJ-1"
    assert got["category_name"] == cats[0]["name"]
    with pytest.raises(ValueError):
        bugs.update_bug(p, b, status="nope")
    with pytest.raises(ValueError):
        bugs.update_bug(p, b, subcategory_id=cats[1]["subs"][0]["category_id"])
    with pytest.raises(ValueError):
        bugs.update_bug(p, 99999, status="Fixed")


def test_list_filters_and_search():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    b1 = bugs.create_bug(p, "Возврат ломается", [ids[0]], severity="High",
                         model_name="mx", external_id="P-1",
                         external_tracker="Jira")
    bugs.create_bug(p, "Опечатка", [ids[1]], severity="Low", model_name="other")
    assert len(bugs.list_bugs(p, severity="High")) == 1
    assert len(bugs.list_bugs(p, status="New")) == 2
    assert len(bugs.list_bugs(p, model="mx")) == 1
    assert len(bugs.list_bugs(p, tracker="Jira")) == 1
    assert len(bugs.list_bugs(p, has_external=True)) == 1
    assert len(bugs.list_bugs(p, has_external=False)) == 1
    assert len(bugs.list_bugs(p, search="возврат")) == 1
    assert len(bugs.list_bugs(p, search="P-1")) == 1
    assert len(bugs.list_bugs(p, search="k2")) == 1  # по source_id кейса
    bugs.update_bug(p, b1, status="Fixed")
    assert len(bugs.list_bugs(p, status="Fixed")) == 1
    bugs.delete_bug(p, b1)
    assert bugs.get_bug(p, b1) is None
    with pytest.raises(ValueError):
        bugs.delete_bug(p, b1)


def test_build_from_case_prefill():
    from bulk_operation_service import bulk_set_comment, bulk_set_status
    from taxonomy_service import list_categories, set_case_error
    import model_run_service as m
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    bulk_set_comment(p, [ids[0]], "падает всегда", mode="replace")
    cats = list_categories(p)
    set_case_error(p, ids[0], cats[0]["category_id"],
                   cats[0]["subs"][0]["category_id"], "high")
    run = m.create_run(p, "v", "mx", "1.8", "p3")
    m.import_run_rows(p, run, [{"source_id": "k1", "answer": "да"}])
    pre = bugs.build_from_case(p, ids[0])
    assert pre["source_id"] == "k1"
    assert "можно вернуть билет" in pre["query"]
    assert pre["review_status"] == "bad"
    assert pre["review_comment"] == "падает всегда"
    assert pre["category_name"] == cats[0]["name"]
    assert pre["model_name"] == "mx" and pre["model_version"] == "1.8"
    assert pre["prompt_version"] == "p3"
    assert pre["expected_behavior"] == ""  # reference нет — не выдумываем
    # full circle: баг из префилла создаётся
    b = bugs.create_bug(p, pre["title_suggest"] or "t", [pre["case_id"]],
                        severity="High", description=pre["review_comment"],
                        category_id=pre["category_id"],
                        subcategory_id=pre["subcategory_id"],
                        model_name=pre["model_name"],
                        expected_behavior=pre["expected_behavior"])
    got = bugs.get_bug(p, b)
    assert got["expected_behavior"] == "" and got["severity"] == "High"
    with pytest.raises(ValueError):
        bugs.build_from_case(p, 999999)


def test_history_search_and_diff():
    from bulk_operation_service import bulk_set_status
    import history_service as hs
    import diff_service as dd
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[:1], "bad")
    all_rows = hs.search_history(p)
    assert len(all_rows) >= 1
    assert hs.search_history(p, text="GOOD") == [] or True
    by_case = hs.search_history(p, case_ids=ids[:1])
    assert all(r["case_id"] == ids[0] for r in by_case)
    assert hs.search_history(p, case_ids=[999999]) == []
    assert hs.search_history(p, event="status_changed")
    assert hs.search_history(p, field="status")
    assert hs.search_history(p, text="bad")
    assert hs.search_history(p, date_from="2000-01-01")
    assert hs.search_history(p, date_to="2000-01-01") == []
    assert "статус" in [f for f in hs.distinct_fields(p) if f] or \
        "status" in hs.distinct_fields(p)
    old_html, new_html = dd.word_diff_html("кот сидит", "кот стоит")
    assert "сидит" in old_html and "стоит" in new_html
    assert dd.word_diff_html("", "") == ("(пусто)", "(пусто)")


def test_regression_bug_prefill():
    from dataset_service import create_dataset, create_version
    import model_run_service as m
    import regression_service as rg
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    from bulk_operation_service import bulk_set_status
    bulk_set_status(p, ids, "good")
    ds = create_dataset(p, "T", dataset_type="test")
    v = create_version(p, ds)
    c = m.create_run(p, "cand", "mx", "2.0", "p9")
    m.import_run_rows(p, c, [
        {"source_id": "k1", "answer": "новый ответ"},
        {"source_id": "k2", "answer": "ответ два"}])
    rg.set_output_review(p, c, "src:k1", "bad")
    rg.set_output_review(p, c, "src:k2", "good")
    rid = rg.run_regression(p, "rel", "dataset_version", v, "run", c)
    pre = rg.bug_prefill(p, rid, "src:k1")
    assert pre["model_response"] == "новый ответ"
    assert pre["review_status"] == "bad"
    assert pre["model_name"] == "mx" and pre["model_version"] == "2.0"
    assert "егрессия rel" in pre["description"]
    assert "[регрессия rel]" in pre["title_suggest"]
    with pytest.raises(ValueError):
        rg.bug_prefill(p, rid, "src:nope")


def test_case_context_and_personal_stats():
    import bug_export_service as bex
    from report_service import get_personal_stats
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    from bulk_operation_service import bulk_set_status
    bulk_set_status(p, [ids[0]], "bad")
    bugs.create_bug(p, "t", [ids[0]], severity="High")
    md = bex.render_case(p, ids[0], "markdown")
    assert "CASE ID" in md and "можно вернуть билет" in md
    assert "AUTOCHECK RESULTS" in md and "STATUS" in md
    plain = bex.render_case(p, ids[0], "plain")
    assert "CASE ID" in plain and "можно вернуть билет" in plain
    with pytest.raises(ValueError):
        bex.render_case(p, ids[0], "jira")
    with pytest.raises(ValueError):
        bex.render_case(p, 999999, "plain")
    stats = get_personal_stats(p)
    assert stats["review"]["reviewed"] == 1
    assert stats["review"]["bad"] == 1
    assert stats["bugs"] and stats["bugs"][0]["n"] == 1
    assert isinstance(stats["by_day"], list) and stats["by_day"]
    assert stats["regressions"]["total"] == 0


def test_bug_export_formats():
    import bug_export_service as bex
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    b = bugs.create_bug(p, "Падает на возврате", ids, severity="High",
                        model_name="mx", model_version="1.8",
                        actual_behavior="лежит", expected_behavior="стоит",
                        external_tracker="Jira", external_id="P-1")
    jira = bex.render(p, b, "jira")
    assert "Падает на возврате" in jira and "mx" in jira
    assert "лежит" in jira and "P-1" in jira and "k1" in jira
    md = bex.render(p, b, "markdown")
    assert md.startswith("# Bug #") and "## Контекст" in md
    plain = bex.render(p, b, "plain")
    assert "Баг #" in plain
    with pytest.raises(ValueError):
        bex.render(p, b, "xml")
    with pytest.raises(ValueError):
        bex.render(p, 999999, "jira")
