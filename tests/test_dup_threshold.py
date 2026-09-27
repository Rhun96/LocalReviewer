"""Порог дублей под движок (компрессия скоров эмбеддингов)."""
import tempfile

from PySide6.QtWidgets import QApplication

from database import init_database
from similar_dialog import DuplicatesDialog


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def test_dup_threshold_per_backend(monkeypatch):
    """Детерминированно: бэкенд подменяем (на CI файлов модели нет)."""
    import similarity_service as sim
    _app()
    p = _proj()
    tf = sim.get_backend("tfidf")
    monkeypatch.setattr(
        sim, "resolve_backend",
        lambda _prefer=None: (tf, ""))
    d = DuplicatesDialog(p, None, None)
    try:
        d.show()
        assert d.thr_spin.value() == 90
        assert "70–80" in d.hint_label.text()
    finally:
        d.close()
    em = sim.get_backend("embedding")
    monkeypatch.setattr(
        sim, "resolve_backend",
        lambda _prefer=None: (em, ""))
    d = DuplicatesDialog(p, None, None)
    try:
        d.show()
        assert d.thr_spin.value() == 95
        assert "93–98" in d.hint_label.text()
    finally:
        d.close()
