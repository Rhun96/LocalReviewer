"""Живой прогон эмбеддингов (только если модель скачана; в CI — skip)."""
import tempfile

import pytest
from PySide6.QtWidgets import QApplication

from database import db, init_database
import embedding_service as emb
from importer import import_file

embmod = pytest.importorskip("transformers", reason="no transformers")
if not emb.model_files_present():
    pytest.skip("no embedding model", allow_module_level=True)


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(p, "f.xlsx", "excel", "S", 0, mapping,
                [{"q": "как вернуть билет", "a": "оформи возврат"},
                 {"q": "хочу сдать билет", "a": "возврат за 5 дней"},
                 {"q": "где мой заказ", "a": "трек в sms"},
                 {"q": "тарифы связи", "a": "смена тарифа"}])
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    return p, ids


def test_live_index_and_search():
    _ = QApplication.instance() or QApplication([])
    p, ids = _proj()
    res = emb.ensure_indexed(p, ids)
    assert res["done"] == 4 and res["failed"] == 0
    assert emb.indexed_count(p) == 4
    out = emb.find_similar_embedding(p, ids[0], min_score=0.3, scope="project")
    assert out["backend"] == "embedding"
    assert out["indexed"] >= 4
    assert any(r["case_id"] == ids[1] for r in out["results"]), out
    dup = emb.find_duplicates_embedding(p, threshold=0.5)
    assert dup["backend"] == "embedding"
    assert isinstance(dup["pairs"], list)


def test_live_dialog_uses_embedding():
    from PySide6.QtCore import QSettings
    _ = QApplication.instance() or QApplication([])
    qs = QSettings("LocalReviewer", "LocalReviewer")
    old = qs.value("ui/similarity_backend", None)
    p, ids = _proj()
    emb.ensure_indexed(p, ids)
    try:
        qs.setValue("ui/similarity_backend", "embedding")
        from similar_dialog import SimilarDialog
        d = SimilarDialog(p, ids[0], None)
        try:
            d.show()
            assert "embedding" in d.info.text(), d.info.text()
        finally:
            d.close()
    finally:
        if old is None:
            qs.remove("ui/similarity_backend")
        else:
            qs.setValue("ui/similarity_backend", old)
