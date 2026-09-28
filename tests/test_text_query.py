"""Text-query семантический поиск: TF-IDF-скоринг, скопы, fallback, диалог."""
import tempfile

import pytest
from PySide6.QtWidgets import QApplication

from database import init_database
from importer import import_file


def _proj(rows):
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
                [{"q": q} for q in rows])
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_by_text_paraphrase_above_noise():
    import similarity_service as sim
    p = _proj(["Нужно перенести поездку на поезде на день позже. Как обменять билет?",
               "Как перенести поездку на поезде на другую дату?",
               "Нужна ли виза в Турцию?"])
    res = sim.find_by_text(p, "обменять билет на поезд", min_score=0.0,
                           scope="project")
    by_id = {r["snippet"]: r["score"] for r in res["results"]}
    scores = sorted(by_id.values(), reverse=True)
    assert scores[0] > 0.4
    assert scores[-1] < 0.2
    assert res["backend"] == "tfidf"


def test_by_text_empty_and_validation():
    import similarity_service as sim
    p = _proj(["что-то осмысленное здесь"])
    res = sim.find_by_text(p, "   ", scope="project")
    assert res["results"] == [] and res["total"] == 0
    with pytest.raises(ValueError):
        sim.find_by_text(p, "запрос", scope="nope")
    with pytest.raises(ValueError):
        sim.find_by_text(p, "запрос", min_score=2)
    with pytest.raises(ValueError):
        sim.find_by_text(p, "запрос", scope="file")
    with pytest.raises(ValueError):
        sim.find_by_text(p, "запрос", fields=())


def test_by_text_file_scope():
    import similarity_service as sim
    from database import db
    p = _proj(["вернуть билет можно", "вернуть билет можно?", "другой текст"])
    with db(p) as conn:
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    file_res = sim.find_by_text(p, "вернуть билет", min_score=0.3,
                                scope="file", file_id=fid)
    proj_res = sim.find_by_text(p, "вернуть билет", min_score=0.3,
                                scope="project")
    assert len(file_res["results"]) == len(proj_res["results"]) == 2


def test_search_semantic_empty_and_fallback(monkeypatch):
    import global_search_service as gs
    import similarity_service as sim
    import embedding_service as emb
    p = _proj(["как вернуть билет на поезд",
               "можно ли вернуть билет на поезд",
               "завтрак в отеле включен"])
    assert gs.search_semantic(p, "  ")["results"] == []
    # Эмбеддинг-движок без модели в рантайме → молча TF-IDF + пометка.
    em = sim.get_backend("embedding")
    monkeypatch.setattr(sim, "resolve_backend", lambda _p=None: (em, ""))
    def _raise(*a, **k):
        raise emb.EmbeddingUnavailableError("no model (test)")
    monkeypatch.setattr(emb, "encode_texts", _raise)
    res = gs.search_semantic(p, "вернуть билет")
    assert res["backend"] == "tfidf" and res["note"]
    assert res["total"] >= 1
    assert all("score" in r for r in res["results"])


def test_search_semantic_backends_positional():
    import similarity_service as sim
    p = _proj(["похожий текст раз", "похожий текст два"])
    tf = sim.get_backend("tfidf")
    out = tf.find_by_text(p, "похожий текст", 0.3, "project", None,
                          ("primary_text",), 10)
    assert "results" in out and out["total"] >= 1


def test_global_dialog_modes_and_scope(monkeypatch):
    """Hermetic: движок фиксируем (иначе зависит от QSettings/весов машины),
    данные — на 2 хита (1 хит сразу открывается через auto-accept)."""
    import similarity_service as sim
    monkeypatch.setattr(sim, "resolve_backend",
                        lambda _prefer=None: (sim.get_backend("tfidf"), ""))
    _app()
    from global_search_dialog import GlobalSearchDialog
    p = _proj(["вернуть билет сегодня", "вернуть билет завтра",
               "совсем другое"])
    d = GlobalSearchDialog(p, None, file_id=None)
    try:
        d.show()
        assert d._mode() == "exact"
        assert d.btn_mode_exact.isChecked()
        assert not d.scope_combo.isEnabled()
        d.btn_mode_semantic.setChecked(True)
        assert d._mode() == "semantic"
        assert not d.btn_mode_exact.isChecked()
        # без file_id скоп файла недоступен даже в семантике
        assert not d.scope_combo.isEnabled()
    finally:
        d.close()
    from database import db
    with db(p) as conn:
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    d2 = GlobalSearchDialog(p, None, file_id=fid)
    try:
        d2.show()
        d2.btn_mode_semantic.setChecked(True)
        assert d2._mode() == "semantic"
        assert d2.scope_combo.isEnabled()
        d2.edit.setText("вернуть билет")
        d2._search_semantic()
        assert d2.list.count() == 2
        assert "движок" in d2.engine_info.text()
    finally:
        d2.close()
