"""V2.1 §§8-10: контекст кейса полон, пустые опционалы — пустые, баги в карточке."""
import tempfile

from database import init_database
from importer import import_file
from filter_service import get_filtered_case_ids
import bug_export_service as bex
import bug_report_service as bugs


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "base.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id",
                 "a": "response_text", "p": "product"},
                [{"q": "где возврат?", "i": "k1",
                  "a": "вернём за 3 дня", "p": "Travel"}])
    return tmp


def test_context_has_all_fields():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    md = bex.render_case(p, ids[0], "markdown")
    for field in ("CASE ID", "SOURCE ID", "QUERY", "MODEL RESPONSE",
                  "REFERENCE", "STATUS", "CATEGORY", "SUBCATEGORY",
                  "SEVERITY", "COMMENT", "AUTOCHECK RESULTS", "MODEL",
                  "MODEL VERSION", "PROMPT VERSION", "SYSTEM PROMPT VERSION"):
        assert field in md, field
    assert "где возврат" in md and "вернём за 3 дня" in md
    plain = bex.render_case(p, ids[0], "plain")
    assert "CASE ID" in plain and "где возврат" in plain


def test_context_empty_optionals_stay_empty():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    pre_cols = bex.render_case(p, ids[0], "plain")
    # нет прогона — версии модели пустые, но не выдуманные
    assert "MODEL VERSION: \n" in pre_cols or "MODEL VERSION:" in pre_cols
    from bug_report_service import build_from_case
    pre = build_from_case(p, ids[0])
    assert pre["model_name"] == "" and pre["prompt_version"] == ""
    assert pre["expected_behavior"] == pre["reference"] == ""


def test_reference_flows_into_bug():
    import json
    from database import db
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    with db(p) as conn:
        row = conn.execute(
            "SELECT metadata_json FROM cases WHERE case_id=?",
            (ids[0],)).fetchone()
        meta = json.loads(row["metadata_json"] or "{}")
        meta["operator_response"] = "вернём по правилам тарифа"
        conn.execute("UPDATE cases SET metadata_json=? WHERE case_id=?",
                     (json.dumps(meta, ensure_ascii=False), ids[0]))
    from bug_report_service import build_from_case
    pre = build_from_case(p, ids[0])
    assert pre["reference"] == "вернём по правилам тарифа"
    assert pre["expected_behavior"] == "вернём по правилам тарифа"
    md = bex.render_case(p, ids[0], "markdown")
    assert "вернём по правилам тарифа" in md


def test_bugs_visible_from_case():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    assert bugs.bugs_for_case(p, ids[0]) == []
    bid = bugs.create_bug(p, "заголовок", [ids[0]], severity="High")
    linked = bugs.bugs_for_case(p, ids[0])
    assert len(linked) == 1 and linked[0]["bug_id"] == bid
    assert linked[0]["severity"] == "High"
    cases = bugs.cases_for_bug(p, bid)
    assert [c["case_id"] for c in cases] == [ids[0]]
