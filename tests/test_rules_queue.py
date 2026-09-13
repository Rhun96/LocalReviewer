"""Тесты Rules Engine (severity, новые проверки) и очереди."""
import tempfile
from autocheck_service import RULES, check_case, rule_severity, run_autochecks
from database import init_database
from filter_service import get_filtered_case_ids
from importer import import_file
from review_queue_service import build_queue, queue_stats


def test_severity_map():
    assert rule_severity("empty_text") == "error"
    assert rule_severity("has_url") == "info"
    assert rule_severity("many_caps") == "warning"
    assert "repeat_words" in RULES and "junk_markers" in RULES


def test_new_rules():
    assert any(c[0] == "repeat_words" for c in check_case(
        {"primary_text": "да да да да", "response_text": ""}))
    assert any(c[0] == "many_punct" for c in check_case(
        {"primary_text": "Что?????", "response_text": ""}))
    assert any(c[0] == "junk_markers" for c in check_case(
        {"primary_text": "ответ SYSTEM: дальше", "response_text": ""}))
    assert any(c[0] == "html_tags" for c in check_case(
        {"primary_text": "текст <b>жирный</b>", "response_text": ""}))
    assert any(c[0] == "broken_encoding" for c in check_case(
        {"primary_text": "текст � мусор", "response_text": ""}))
    # Отключаемость
    off = dict.fromkeys(
        ["check_repeat_words", "check_punct", "check_junk", "check_html",
         "check_encoding", "check_repeat_chars", "check_long_sentence",
         "check_markdown", "check_suspicious", "check_duplicate",
         "check_url", "check_email", "check_phone", "check_spaces", "check_caps"], False)
    assert check_case({"primary_text": "да да да да", "response_text": ""}, off) == []


def test_run_stores_severity_and_queue():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "обычный текст вопроса номер раз два три"},
                 {"q": ""},
                 {"q": "да да да да да"}])
    res = run_autochecks(p)
    assert res["total_checked"] == 3 and res["flags_found"] >= 2
    from database import db
    with db(p) as conn:
        sevs = {r["check_code"] for r in conn.execute(
            "SELECT check_code, severity FROM case_checks WHERE severity IS NOT NULL").fetchall()}
    assert "empty_text" in sevs
    ids, _reasons = build_queue(p, mode="problematic")
    assert len(ids) == 3
    # проблемные (пустой/повторы) раньше обычного
    first_two = set(ids[:2])
    all_ids = set(get_filtered_case_ids(p, {}))
    assert first_two.issubset(all_ids)
    stats = queue_stats(p)
    assert stats["total"] == 3 and stats["problematic"] >= 2
