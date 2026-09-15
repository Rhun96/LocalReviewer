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
