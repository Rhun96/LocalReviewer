"""Этап D: TF-IDF-похожие — scoring, области, дубли, валидация."""
import tempfile

import pytest
from database import init_database
from importer import import_file
import similarity_service as sim


def _proj(rows):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": q} for q in rows])
    return tmp


def _ids(p):
    from filter_service import get_filtered_case_ids
    return get_filtered_case_ids(p, {})


def test_identical_and_paraphrase():
    p = _proj(["как вернуть билет на поезд",
               "как вернуть билет на поезд?",
               "можно ли вернуть билет на поезд",
               "завтрак в отеле включен"])
    ids = _ids(p)
    res = sim.find_similar(p, ids[0], min_score=0.3, scope="project")
    by_id = {r["case_id"]: r["score"] for r in res["results"]}
    assert by_id[ids[1]] == pytest.approx(1.0)
    assert by_id[ids[2]] > 0.3
    assert ids[3] not in by_id
    assert all(r["status"] == "unreviewed" for r in res["results"])


def test_empty_query_and_validation():
    p = _proj(["", "что-то осмысленное здесь"])
    ids = _ids(p)
    res = sim.find_similar(p, ids[0], scope="project")
    assert res["results"] == [] and res["total"] == 0
    with pytest.raises(ValueError):
        sim.find_similar(p, ids[0], scope="nope")
    with pytest.raises(ValueError):
        sim.find_similar(p, ids[0], min_score=2)
    with pytest.raises(ValueError):
        sim.find_similar(p, 999999)
    with pytest.raises(ValueError):
        sim.find_similar(p, ids[1], fields=())


def test_scopes_and_fields():
    p = _proj(["вернуть билет можно", "вернуть билет можно?", "другой текст"])
    ids = _ids(p)
    file_res = sim.find_similar(p, ids[0], min_score=0.3, scope="file")
    proj_res = sim.find_similar(p, ids[0], min_score=0.3, scope="project")
    assert len(file_res["results"]) == len(proj_res["results"]) == 1
    # Golden/архив пусты — пустой список, а не ошибка
    assert sim.find_similar(p, ids[0], scope="golden")["results"] == []
    assert sim.find_similar(p, ids[0], scope="archive")["results"] == []
    resp = sim.find_similar(p, ids[0], min_score=0.3, scope="project",
                            fields=("response_text",))
    assert resp["results"] == []


def test_duplicates_and_cap():
    p = _proj(["один и тот же текст", "один и тот же текст!",
               "совсем другое", "один и тот же текст"])
    # третий — точный дубль по хэшу, импортёр оставил 3 кейса
    d = sim.find_duplicates(p, threshold=0.9)
    assert d["total"] >= 1
    assert all(x["score"] >= 0.9 for x in d["pairs"])
    with pytest.raises(ValueError):
        sim.find_duplicates(p, threshold=1.5)


def test_reviewed_mark():
    from bulk_operation_service import bulk_set_status
    p = _proj(["похожий текст раз", "похожий текст два"])
    ids = _ids(p)
    bulk_set_status(p, [ids[1]], "bad")
    res = sim.find_similar(p, ids[0], min_score=0.3, scope="project")
    assert len(res["results"]) == 1
    assert res["results"][0]["reviewed"] is True
    assert res["results"][0]["status"] == "bad"
