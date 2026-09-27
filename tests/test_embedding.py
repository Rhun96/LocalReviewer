"""Эмбеддинги: хранение/версии/косинус/фолбэк (без модели)."""
import tempfile

import numpy as np
import pytest

from bulk_operation_service import bulk_set_status
from database import db, init_database
import embedding_service as emb
from importer import import_file


@pytest.fixture()
def proj():
    p = tempfile.mkdtemp()
    init_database(p)
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(p, "f.xlsx", "excel", "S", 0, mapping,
                [{"q": f"q{i}", "a": f"a{i}"} for i in range(4)])
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    bulk_set_status(p, ids[:2], "good")
    return p, ids


def _vec(seed: int):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal(emb.DIMENSIONS).astype("float32")
    return v / max(np.linalg.norm(v), 1e-9)


def test_build_text_and_hash_stable():
    t1 = emb.build_text("  Запрос? ", "Ответ! ", None)
    t2 = emb.build_text("Запрос?", "Ответ!", "")
    assert t1 == t2 == "Запрос? Ответ!"
    assert emb.source_hash(t1) == emb.source_hash(t2)
    assert emb.source_hash("a") != emb.source_hash("b")
    assert emb.DIMENSIONS == 768


def test_store_load_skip_and_stale(proj):
    p, ids = proj
    assert emb.store_vector(p, ids[0], _vec(1), emb.source_hash("q0 a0"))
    assert not emb.store_vector(p, ids[0], _vec(1), emb.source_hash("q0 a0"))
    assert emb.indexed_count(p) == 1
    got = emb.load_vectors(p, ids)
    assert set(got) == {ids[0]}
    assert got[ids[0]].shape == (emb.DIMENSIONS,)
    # чужой текст/версия/битый вектор — не видны
    assert emb.stale_ids(p, [ids[1]]) == [ids[1]]
    with db(p) as conn:
        conn.execute(
            "INSERT INTO case_embeddings (case_id, model_name, model_version,"
            " source_hash, dimensions, embedding_data, created_at, updated_at,"
            " is_active) VALUES (?, ?, 'v0', 'x', ?, ?, 't', 't', 1)",
            (ids[1], emb.MODEL_NAME, emb.DIMENSIONS, b"\x00" * 8))
    assert emb.load_vectors(p, [ids[1]]) == {}
    assert emb.stale_ids(p, [ids[0]]) == []


def test_dim_mismatch_rejected(proj):
    p, _ids = proj
    with pytest.raises(ValueError):
        emb.store_vector(p, 1, np.zeros(8, dtype="float32"), "x")


def test_no_model_fallback(monkeypatch, proj):
    p, ids = proj
    monkeypatch.setattr(emb, "_MODEL", None)
    monkeypatch.setattr(emb, "model_files_present", lambda: False)
    with pytest.raises(emb.EmbeddingUnavailableError):
        emb.find_similar_embedding(p, ids[0])
    with pytest.raises(emb.EmbeddingUnavailableError):
        emb.find_duplicates_embedding(p)
    import similarity_service as sim
    be, note = sim.resolve_backend("embedding")
    assert be.name == "tfidf" and note
    assert sim.get_backend("embedding").name == "embedding"


def test_similarity_settings_snapshot():
    from PySide6.QtCore import QSettings
    from ui_compat import (get_similarity_backend, set_similarity_backend,
                           get_embed_threshold, set_embed_threshold,
                           get_embed_topk, set_embed_topk,
                           get_embed_auto, set_embed_auto)
    qs = QSettings("LocalReviewer", "LocalReviewer")
    keys = ("ui/similarity_backend", "ui/embed_threshold", "ui/embed_topk",
            "ui/embed_auto")
    old = {k: qs.value(k, None) for k in keys}
    try:
        assert set_similarity_backend("embedding") == "embedding"
        assert get_similarity_backend() == "embedding"
        assert set_similarity_backend("nope") == "tfidf"
        assert set_embed_threshold(0.8) == 0.8
        assert get_embed_threshold() == 0.8
        assert set_embed_topk(7) == 7
        assert get_embed_topk() == 7
        assert set_embed_auto(False) is False
        assert get_embed_auto() is False
    finally:
        for k, v in old.items():
            if v is None:
                qs.remove(k)
            else:
                qs.setValue(k, v)


def test_backends_accept_positional_like_dialogs(proj):
    """Регресс: воркеры зовут find_* позиционно (краш дубликатов)."""
    import similarity_service as sim
    p, ids = proj
    tf = sim.get_backend("tfidf")
    out = tf.find_duplicates(p, None, 0.9, 200, None, None)
    assert "pairs" in out and "total" in out
    out2 = tf.find_similar(p, ids[0], 0.3, "project", ("primary_text",), 10)
    assert "results" in out2
    em = sim.get_backend("embedding")
    try:
        em.find_duplicates(p, None, 0.9, 200, None, None)
    except emb.EmbeddingUnavailableError:
        pass
    try:
        em.find_similar(p, ids[0], 0.6, "file", ("primary_text",), 10)
    except emb.EmbeddingUnavailableError:
        pass
