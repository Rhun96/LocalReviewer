"""Подсказки разметки: rule-backend, поддержка, ручное применение."""
import tempfile

from database import init_database
from importer import import_file
from bulk_operation_service import bulk_set_status
from filter_service import get_filtered_case_ids
import category_suggestion_service as sug


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": "как вернуть билет на поезд"},
                 {"q": "как вернуть билет на поезд?"},
                 {"q": "можно ли вернуть билет на поезд"},
                 {"q": "завтрак в отеле включен"}])
    return tmp


def test_status_suggestion_needs_agreement():
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[1:3], "bad")
    res = sug.suggest_annotations(p, ids[0])
    assert res["status"]["status"] == "bad"
    assert res["status"]["support"] == 2
    assert res["category"] is None  # причин нет
    # один размеченный — поддержки нет
    res2 = sug.suggest_annotations(p, ids[3], min_support=3)
    assert res2["status"] is None


def test_category_suggestion():
    from taxonomy_service import list_categories, set_case_error
    p = _proj()
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[1:3], "bad")
    cats = list_categories(p)
    for cid in ids[1:3]:
        set_case_error(p, cid, cats[0]["category_id"],
                       cats[0]["subs"][0]["category_id"], "high")
    res = sug.suggest_annotations(p, ids[0])
    cat = res["category"]
    assert cat["category_id"] == cats[0]["category_id"]
    assert cat["subcategory_id"] == cats[0]["subs"][0]["category_id"]
    assert cat["support"] == 2
    assert cat["category_name"] == cats[0]["name"]
    try:
        sug.suggest_annotations(p, ids[0], backend="nope")
        raise AssertionError("should raise")
    except ValueError:
        pass
