"""Таксономия: seed, CRUD, архив вместо удаления, классификация кейса."""
import tempfile
from database import init_database
from importer import import_file
from taxonomy_service import (
    archive_category, create_category, delete_category, get_case_error,
    list_categories, rename_category, set_case_error,
)


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "вопрос раз"}, {"q": "вопрос два"}])
    return tmp


def test_seed():
    p = _proj()
    cats = list_categories(p)
    assert len(cats) == 6
    total_subs = sum(len(c["subs"]) for c in cats)
    assert total_subs == 17
    assert all(c["is_active"] for c in cats)


def test_classify_and_history():
    from database import db
    p = _proj()
    cats = list_categories(p)
    comp = next(c for c in cats if c["code"] == "completeness")
    sub = next(s for s in comp["subs"] if "incomplete" in s["code"])
    set_case_error(p, 1, comp["category_id"], sub["category_id"], "high")
    err = get_case_error(p, 1)
    assert err["category_name"] == "Полнота"
    assert err["subcategory_name"] == "Неполный ответ"
    assert err["severity"] == "high"
    with db(p) as conn:
        ev = conn.execute(
            "SELECT * FROM history WHERE case_id=1 AND event_type='category_changed'"
        ).fetchone()
        assert ev is not None
    # снять классификацию
    set_case_error(p, 1, None)
    assert get_case_error(p, 1) is None


def test_archive_keeps_markup():
    p = _proj()
    cats = list_categories(p)
    comp = next(c for c in cats if c["code"] == "completeness")
    set_case_error(p, 1, comp["category_id"], None, "low")
    # удалить используемую нельзя
    try:
        delete_category(p, comp["category_id"])
        raise AssertionError("should raise")
    except ValueError:
        pass
    # архив можно, разметка живёт
    archive_category(p, comp["category_id"])
    assert get_case_error(p, 1)["category_name"] == "Полнота"
    assert all(c["code"] != "completeness" for c in list_categories(p))


def test_custom_and_rename():
    p = _proj()
    cid = create_category(p, "Моя причина")
    rename_category(p, cid, "Моя причина 2")
    cats = list_categories(p)
    assert len(cats) == 7
    # чужая подкатегория отвергается
    other_sub = [s for c in cats for s in c["subs"] if c["code"] == "safety"][0]
    try:
        set_case_error(p, 2, cid, other_sub["category_id"])
        raise AssertionError("should raise")
    except ValueError:
        pass


def _comp_ids(p):
    from database import db
    with db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness'").fetchone()
        sub = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness.hallucination'").fetchone()
    return cat["category_id"], sub["category_id"]


def test_cause_drops_when_leaving_bad_single():
    """Плохо → Хорошо: причина слетает и нигде не хранится."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from bulk_operation_service import bulk_set_status
    from database import db
    from filter_service import get_filtered_case_ids
    from review_screen import ReviewScreen
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "bad")
    cat, sub = _comp_ids(p)
    set_case_error(p, ids[0], cat, sub, "high")
    assert get_case_error(p, ids[0]) is not None
    w = ReviewScreen(p)
    try:
        w.show()
        w.load_case(w.case_ids.index(ids[0]))
        w.set_status("good")
        assert get_case_error(p, ids[0]) is None
        with db(p) as conn:
            n = conn.execute("SELECT COUNT(*) AS c FROM case_errors "
                             "WHERE case_id=?", (ids[0],)).fetchone()["c"]
            assert n == 0
    finally:
        w.close()


def test_cause_drops_when_leaving_bad_bulk():
    from bulk_operation_service import bulk_set_status
    from filter_service import get_filtered_case_ids
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "bad")
    cat, sub = _comp_ids(p)
    for cid in ids:
        set_case_error(p, cid, cat, sub, "high")
    bulk_set_status(p, ids, "good")
    for cid in ids:
        assert get_case_error(p, cid) is None
