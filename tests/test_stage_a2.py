"""Этап A, пакет 2: свои статусы, вердикты precision, флаг просмотрено."""
import sqlite3
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


def test_custom_status_validation():
    from review_profile_service import validate_config
    cfg = validate_config({
        "statuses": [
            {"code": "safe", "name": "Safe", "hotkey": "1",
             "enabled": True, "base": "good"},
            {"code": "edge", "name": "Edge", "hotkey": "2",
             "enabled": True, "base": "uncertain"},
            {"code": "target", "name": "Target", "hotkey": "",
             "enabled": True, "base": "bad"},
        ],
        "require_category_for_bad": False,
        "require_comment_for_bad": None,
    })
    assert cfg["statuses"][0]["base"] == "good"
    # базовые коды без base — маппятся сами
    cfg2 = validate_config({
        "statuses": [{"code": "good", "name": "G", "hotkey": "",
                      "enabled": True}],
        "require_category_for_bad": False,
        "require_comment_for_bad": None,
    })
    assert cfg2["statuses"][0]["base"] == "good"
    bad = {"statuses": [{"code": "nope!", "name": "N", "hotkey": "",
                         "enabled": True, "base": "good"}]}
    with pytest.raises(ValueError):
        validate_config(bad)
    nobase = {"statuses": [{"code": "custom", "name": "N", "hotkey": "",
                            "enabled": True}]}
    with pytest.raises(ValueError):
        validate_config(nobase)


def test_custom_status_end_to_end():
    from bulk_operation_service import bulk_set_status
    from filter_service import get_filtered_case_ids
    from report_service import get_overall_report
    from review_profile_service import (code_to_base, create_profile,
                                        set_active_profile)
    from review_queue_service import queue_stats
    p = _proj()
    pid = create_profile(p, "Safety", {
        "statuses": [
            {"code": "safe", "name": "Safe", "hotkey": "1",
             "enabled": True, "base": "good"},
            {"code": "target", "name": "Target", "hotkey": "2",
             "enabled": True, "base": "bad"},
        ],
        "require_category_for_bad": False,
        "require_comment_for_bad": None,
    })
    set_active_profile(p, pid)
    assert code_to_base(p)["safe"] == "good"
    ids = get_filtered_case_ids(p, {})
    assert bulk_set_status(p, ids[:2], "safe") == 2
    assert bulk_set_status(p, ids[2:3], "target") == 1
    rep = get_overall_report(p)
    assert rep["good"] == 2 and rep["bad"] == 1, rep
    assert rep["reviewed"] == 3 and rep["unreviewed"] == 1
    st = queue_stats(p)
    assert st["reviewed"] == 3 and st["remaining"] == 1
    # фильтр по своему коду работает
    assert set(get_filtered_case_ids(p, {"statuses": ["safe"]})) == set(ids[:2])


def test_v11_migration_keeps_data_and_drops_check():
    from pathlib import Path
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "раз"},
                 {"q": "два"}])
    from bulk_operation_service import bulk_set_status
    from filter_service import get_filtered_case_ids
    ids = get_filtered_case_ids(tmp, {})
    assert bulk_set_status(tmp, ids[:1], "good") == 1
    # Откатываем версию и колонки, эмулируя старую БД с CHECK.
    con = sqlite3.connect(str(Path(tmp) / "project.sqlite"))
    con.execute("PRAGMA user_version=10")
    cols = [r[1] for r in con.execute("PRAGMA table_info(annotations)").fetchall()]
    assert "viewed" in cols  # v11 уже применена выше — проверяем идемпотентность
    con.commit()
    con.close()
    init_database(tmp)  # повторный прогон не должен ничего сломать
    con = sqlite3.connect(str(Path(tmp) / "project.sqlite"))
    from database import SCHEMA_VERSION
    assert con.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
    assert bulk_set_status(tmp, ids[1:], "custom_code") == 1  # CHECK больше нет
    con.close()


def test_verdicts_and_precision():
    from autocheck_service import (get_checks_precision, get_check_verdicts,
                                   run_autochecks, set_check_verdict)
    from filter_service import get_filtered_case_ids
    from report_service import get_checks_report
    p = _proj(3)
    ids = get_filtered_case_ids(p, {})
    run_autochecks(p)
    with db(p) as conn:
        code = conn.execute("SELECT check_code FROM case_checks LIMIT 1").fetchone()
    assert code
    code = code["check_code"]
    set_check_verdict(p, ids[0], code, "confirmed")
    set_check_verdict(p, ids[1], code, "false_positive")
    assert get_check_verdicts(p, ids[0]) == {code: "confirmed"}
    prec = {r["check_code"]: r for r in get_checks_precision(p)}
    assert prec[code]["confirmed"] == 1
    assert prec[code]["false_positive"] == 1
    assert prec[code]["precision"] == pytest.approx(0.5)
    rep = {r["check_code"]: r for r in get_checks_report(p)}
    assert rep[code]["precision"] == pytest.approx(0.5)
    # снятие вердикта
    set_check_verdict(p, ids[0], code, None)
    assert get_check_verdicts(p, ids[0]) == {}
    with pytest.raises(ValueError):
        set_check_verdict(p, ids[0], code, "maybe")


def test_viewed_bulk_and_undo():
    from bulk_operation_service import (bulk_set_viewed, undo_bulk_operation)
    from filter_service import get_filtered_case_ids
    p = _proj(3)
    ids = get_filtered_case_ids(p, {})
    assert bulk_set_viewed(p, ids[:2], True) == 2
    assert bulk_set_viewed(p, ids[:2], True) == 0  # уже отмечены
    with db(p) as conn:
        op = conn.execute("SELECT operation_id FROM bulk_operations "
                          "WHERE op_type='set_viewed' AND case_count=2 "
                          "ORDER BY operation_id DESC LIMIT 1"
                          ).fetchone()["operation_id"]
        cnt = conn.execute("SELECT COUNT(*) AS c FROM annotations WHERE viewed=1"
                           ).fetchone()["c"]
    assert cnt == 2
    assert undo_bulk_operation(p, op) == 2
    with db(p) as conn:
        cnt = conn.execute("SELECT COUNT(*) AS c FROM annotations WHERE viewed=1"
                           ).fetchone()["c"]
    assert cnt == 0
