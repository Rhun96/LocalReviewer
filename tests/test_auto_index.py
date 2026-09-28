"""Import-hook автоиндексации: предикат, no-op пути, свежесть индекса."""
import tempfile

import numpy as np
from PySide6.QtWidgets import QApplication

from database import init_database
from importer import import_file
import embedding_service as emb


def _proj(n=3):
    p = tempfile.mkdtemp()
    init_database(p)
    mapping = {"q": "primary_text", "a": "response_text"}
    import_file(p, "f.xlsx", "excel", "S", 0, mapping,
                [{"q": f"q{i}", "a": f"a{i}"} for i in range(n)])
    from database import db
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    return p, ids, fid


def _app():
    return QApplication.instance() or QApplication([])


def test_auto_index_wanted_matrix(monkeypatch):
    import ui_compat as _uc
    monkeypatch.setattr(_uc, "get_similarity_backend", lambda: "tfidf")
    monkeypatch.setattr(_uc, "get_embed_auto", lambda: True)
    monkeypatch.setattr(emb, "model_files_present", lambda: True)
    ok, _ = emb.auto_index_wanted()
    assert ok is False  # движок TF-IDF — индексировать нечего
    monkeypatch.setattr(_uc, "get_similarity_backend", lambda: "embedding")
    monkeypatch.setattr(_uc, "get_embed_auto", lambda: False)
    ok, _ = emb.auto_index_wanted()
    assert ok is False  # тумблер выключен
    monkeypatch.setattr(_uc, "get_embed_auto", lambda: True)
    monkeypatch.setattr(emb, "model_files_present", lambda: False)
    ok, why = emb.auto_index_wanted()
    assert ok is False and why
    monkeypatch.setattr(emb, "model_files_present", lambda: True)
    ok, _ = emb.auto_index_wanted()
    assert ok is True


def test_maybe_auto_index_noop_paths(monkeypatch):
    """Без эмбеддинг-условий ensure_indexed не зовётся, диалогов нет."""
    _app()
    import ui_compat as _uc
    from import_wizard import ImportWizard
    p, _ids, fid = _proj()
    wiz = ImportWizard(p, None)
    try:
        def _boom(*a, **k):
            raise AssertionError("ensure_indexed must not run")
        monkeypatch.setattr(emb, "ensure_indexed", _boom)
        monkeypatch.setattr(_uc, "get_similarity_backend", lambda: "tfidf")
        monkeypatch.setattr(_uc, "get_embed_auto", lambda: True)
        wiz._maybe_auto_index(fid)  # молча ничего не делает
        monkeypatch.setattr(_uc, "get_similarity_backend", lambda: "embedding")
        monkeypatch.setattr(emb, "model_files_present", lambda: False)
        wiz._maybe_auto_index(fid)  # нет весов — тоже молча
        wiz._maybe_auto_index(999999)  # чужой file_id — пустые ids
    finally:
        wiz.close()


def test_ensure_indexed_skips_fresh_without_model():
    """Свежий индекс: total=0 без загрузки модели (позитив import-hook)."""
    p, ids, _fid = _proj(2)
    rng = np.random.default_rng(7)
    from database import db
    with db(p) as conn:
        rows = conn.execute(
            "SELECT case_id, primary_text, response_text FROM cases").fetchall()
    for r in rows:
        text = emb.build_text(r["primary_text"], r["response_text"], None)
        vec = rng.standard_normal(emb.DIMENSIONS).astype("float32")
        vec = vec / max(float((vec ** 2).sum() ** 0.5), 1e-9)
        assert emb.store_vector(p, r["case_id"], vec, emb.source_hash(text))
    res = emb.ensure_indexed(p, ids)
    assert res == {"done": 0, "failed": 0, "total": 0}
    assert emb.indexed_count(p) == 2
