"""Качество разметки: противоречия, QC-выборка, согласие версий."""
import tempfile

import pytest

from bulk_operation_service import bulk_set_status
from database import init_database
from filter_service import get_filtered_case_ids
from importer import import_file


def _proj(rows):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0, {"q": "primary_text"}, rows)
    return tmp


def test_find_conflicts():
    import consistency_service as qc
    p = _proj([{"q": "как обменять билет на поезд на другую дату"},
               {"q": "как обменять билет на поезд на другую дату!"},
               {"q": "нужна ли виза в турцию"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    bulk_set_status(p, [ids[1]], "bad")
    res = qc.find_conflicts(p, threshold=0.3)
    assert res["total"] == 1, res
    pair = res["pairs"][0]
    assert {pair["case_a"], pair["case_b"]} == {ids[0], ids[1]}
    assert {pair["status_a"], pair["status_b"]} == {"good", "bad"}
    bulk_set_status(p, [ids[1]], "good")
    assert qc.find_conflicts(p, threshold=0.3)["total"] == 0
    with pytest.raises(ValueError):
        qc.find_conflicts(p, threshold=2)


def test_conflicts_default_threshold_catches_paraphrase():
    import consistency_service as qc
    p = _proj([{"q": "Нужно перенести поездку на поезде на день позже. Как обменять билет?"},
               {"q": "Как перенести поездку на поезде на другую дату?"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    bulk_set_status(p, [ids[1]], "bad")
    res = qc.find_conflicts(p)
    assert res["total"] == 1, res


def test_conflicts_pair_preview_and_open():
    """Превью пары без прыжков; открыть — первый кейс пары."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from consistency_dialog import ConsistencyDialog
    p = _proj([{"q": "как обменять билет на поезд на другую дату"},
               {"q": "как обменять билет на поезд на другую дату!"},
               {"q": "нужна ли виза в турцию"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, [ids[0]], "good")
    bulk_set_status(p, [ids[1]], "bad")
    d = ConsistencyDialog(p, None)
    try:
        d.show()
        for i in range(d.cf_thr.count()):
            if d.cf_thr.itemData(i) == 0.3:
                d.cf_thr.setCurrentIndex(i)
                break
        d._find_conflicts()
        assert d.cf_list.count() == 1
        assert d.cf_pair_a.toPlainText() and d.cf_pair_b.toPlainText()
        assert "обменять билет" in d.cf_pair_a.toPlainText()
        d._open_selected()
        assert d.result_case_id in (ids[0], ids[1])
        # кнопки пары ведут к кейсам 1 и 2
        d._pair_ids = (ids[0], ids[1])
        d._open_pair_case(0)
        assert d.result_case_id == ids[0]
        d._open_pair_case(1)
        assert d.result_case_id == ids[1]
    finally:
        d.close()


def test_qc_sample():
    import consistency_service as qc
    p = _proj([{"q": "a1"}, {"q": "a2"}, {"q": "a3"}, {"q": "a4"}, {"q": "a5"}])
    ids = get_filtered_case_ids(p, {})
    assert qc.qc_sample(p)["sample"] == []
    bulk_set_status(p, ids[:3], "good")
    r1 = qc.qc_sample(p, n=2, seed=42)
    r2 = qc.qc_sample(p, n=2, seed=42)
    assert r1["total_reviewed"] == 3 and r1["seed"] == 42
    assert [c["case_id"] for c in r1["sample"]] == [c["case_id"] for c in r2["sample"]]
    assert len(r1["sample"]) == 2
    assert len(qc.qc_sample(p, n=100)["sample"]) == 3
    with pytest.raises(ValueError):
        qc.qc_sample(p, n=0)


def test_version_agreement():
    from dataset_service import (compare_versions, create_dataset,
                                 create_version, version_agreement)
    p = _proj([{"q": "a1"}, {"q": "a2"}, {"q": "a3"}])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    ds = create_dataset(p, "D")
    v1 = create_version(p, ds)
    bulk_set_status(p, ids[:1], "bad")
    v2 = create_version(p, ds)
    agr = version_agreement(p, compare_versions(p, v1, v2))
    assert agr["matched"] == 3 and agr["agreed"] == 2
    assert agr["pct"] == pytest.approx(2 / 3, abs=1e-3)
    assert agr["verdict_changed"] == 1
    assert len(agr["verdict_changed_keys"]) == 1
    assert len(agr["disagreed_keys"]) == 1
