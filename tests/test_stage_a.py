"""Этап A, пакет 1: bulk-теги, проверки для выборки, шаблоны-причины, фильтры+вид, веса."""
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


def _tag_id(project_path: str, code: str) -> int:
    with db(project_path) as conn:
        return conn.execute("SELECT tag_id FROM tags WHERE tag_code=?",
                            (code,)).fetchone()["tag_id"]


def _case_tags(project_path: str, case_id: int) -> set:
    with db(project_path) as conn:
        return {r["tag_id"] for r in conn.execute(
            "SELECT tag_id FROM case_tags WHERE case_id=?", (case_id,))}


def test_bulk_remove_tag_and_undo():
    from bulk_operation_service import (bulk_add_tag, bulk_remove_tag,
                                        undo_bulk_operation)
    from filter_service import get_filtered_case_ids
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    tid = _tag_id(p, "facts")
    assert bulk_add_tag(p, ids, tid) == len(ids)
    assert bulk_remove_tag(p, ids[:2], tid) == 2
    assert _case_tags(p, ids[0]) == set()
    assert _case_tags(p, ids[2]) == {tid}
    with db(p) as conn:
        op = conn.execute("SELECT operation_id FROM bulk_operations "
                          "WHERE op_type='remove_tag' ORDER BY operation_id DESC LIMIT 1"
                          ).fetchone()["operation_id"]
    assert undo_bulk_operation(p, op) == 2
    assert _case_tags(p, ids[0]) == {tid}


def test_bulk_replace_tags_and_undo_guard():
    from bulk_operation_service import (bulk_add_tag, bulk_set_tags,
                                        undo_bulk_operation)
    from filter_service import get_filtered_case_ids
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    a, b = _tag_id(p, "facts"), _tag_id(p, "style")
    bulk_add_tag(p, [ids[0]], a)
    assert bulk_set_tags(p, ids[:2], [b]) == 2
    assert _case_tags(p, ids[0]) == {b}
    assert _case_tags(p, ids[1]) == {b}
    with db(p) as conn:
        op = conn.execute("SELECT operation_id FROM bulk_operations "
                          "WHERE op_type='set_tags' ORDER BY operation_id DESC LIMIT 1"
                          ).fetchone()["operation_id"]
    # Ручная правка после bulk: undo её не затирает
    bulk_add_tag(p, [ids[0]], a)
    assert undo_bulk_operation(p, op) == 1
    assert _case_tags(p, ids[0]) == {a, b}
    assert _case_tags(p, ids[1]) == set()


def test_reset_and_recheck_subset():
    from autocheck_service import reset_checks, run_autochecks
    from filter_service import get_filtered_case_ids
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    res = run_autochecks(p)
    assert res["total_checked"] == len(ids)
    with db(p) as conn:
        before = conn.execute("SELECT COUNT(*) AS c FROM case_checks").fetchone()["c"]
    assert before > 0
    dropped = reset_checks(p, case_ids=ids[:2])
    assert dropped > 0
    with db(p) as conn:
        left = {r["case_id"] for r in conn.execute("SELECT DISTINCT case_id FROM case_checks")}
    assert ids[0] not in left and ids[2] in left
    res2 = run_autochecks(p, case_ids=ids[:2])
    assert res2["total_checked"] == 2
    with db(p) as conn:
        back = {r["case_id"] for r in conn.execute("SELECT DISTINCT case_id FROM case_checks")}
    assert ids[0] in back and ids[2] in back


def test_templates_bound_to_cause_first():
    from templates_service import (add_comment_template, get_comment_templates,
                                   ordered_templates)
    from taxonomy_service import list_categories
    p = _proj(1)
    cats = list_categories(p)
    cat, sub = cats[0]["category_id"], cats[0]["subs"][0]["category_id"]
    assert add_comment_template(p, "Общий шаблон про длину")
    assert add_comment_template(p, "Шаблон для причины", cat, sub)
    all_t = get_comment_templates(p)
    assert any(t["category_id"] == cat for t in all_t)
    ordered = ordered_templates(p, cat, sub)
    assert ordered[0]["text"] == "Шаблон для причины"
    # Без причины порядок не ломается
    assert len(ordered_templates(p, None, None)) == len(all_t)


def test_saved_filter_extended_roundtrip_and_compat():
    from saved_filter_service import (delete_saved_filter, list_saved_filters,
                                      save_filter)
    p = _proj(1)
    cond = {"statuses": ["bad"], "tags": [], "checks": [], "search_text": ""}
    payload = {"filters": cond, "columns": ["ID", "Статус"],
               "queue_mode": "problematic", "sort": "unreviewed_first"}
    fid = save_filter(p, "Мой", payload)
    items = list_saved_filters(p)
    got = next(i for i in items if i["filter_id"] == fid)
    assert got["filters"]["filters"] == cond
    assert got["filters"]["queue_mode"] == "problematic"
    # Старый плоский формат читается как раньше
    fid2 = save_filter(p, "Старый", cond)
    got2 = next(i for i in list_saved_filters(p) if i["filter_id"] == fid2)
    assert got2["filters"]["statuses"] == ["bad"]
    assert delete_saved_filter(p, fid) and delete_saved_filter(p, fid2)


def test_priority_weights_defaults_and_custom():
    from review_queue_service import (DEFAULT_WEIGHTS, compute_priority,
                                      get_priority_weights)
    from database import utcnow
    p = _proj(1)
    assert get_priority_weights(p) == DEFAULT_WEIGHTS
    s1, _ = compute_priority(True, "error", 1, "unreviewed")
    assert s1 == 100 + 10
    with db(p) as conn:
        conn.cursor().execute(
            "INSERT INTO settings (key, value, updated_at) VALUES ('prio_w_crit', '5', ?)",
            (utcnow(),))
    assert get_priority_weights(p)["w_crit"] == 5
    s2, _ = compute_priority(True, "error", 1, "unreviewed",
                             weights=get_priority_weights(p))
    assert s2 == 5 + 10


def test_bulk_cancel_rolls_back():
    import threading
    from bulk_operation_service import bulk_set_status
    from filter_service import get_filtered_case_ids
    from workers import Cancelled
    p = _proj(3)
    ids = get_filtered_case_ids(p, {})
    ev = threading.Event()
    ev.set()  # отмена сразу
    with pytest.raises(Cancelled):
        bulk_set_status(p, ids, "good", cancel_event=ev)
    with db(p) as conn:
        n = conn.execute("SELECT COUNT(*) AS c FROM annotations "
                         "WHERE status='good'").fetchone()["c"]
    assert n == 0  # всё откачено


def test_bulk_progress_ticks():
    from bulk_operation_service import bulk_set_status
    from filter_service import get_filtered_case_ids
    p = _proj(3)
    ids = get_filtered_case_ids(p, {})
    calls = []
    done = bulk_set_status(p, ids, "good",
                           progress_callback=lambda d, t: calls.append((d, t)))
    assert done == 3 and calls and calls[-1] == (3, 3)


def test_precheck_stats():
    from import_wizard import precheck_stats
    m = {"i": "source_id", "q": "primary_text"}
    data = [{"i": "a", "q": "x"}, {"i": "a", "q": "y"},
            {"i": "", "q": ""}, {"i": "b", "q": "z"}]
    st = precheck_stats(m, data)
    assert st["total"] == 4
    assert st["sid_filled"] == 3 and st["sid_empty"] == 1
    assert st["sid_dups"] == 1 and st["dup_examples"] == ["a"]
    assert st["primary_empty"] == 1
    st2 = precheck_stats({"q": "primary_text"}, data)
    assert st2["sid_mapped"] is False


def test_default_profile_requires_cause():
    from review_profile_service import get_active_profile
    p = _proj(1)
    prof = get_active_profile(p)
    assert prof["config"]["require_category_for_bad"] is True
