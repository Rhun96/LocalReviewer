"""Порог дублей под движок (компрессия скоров эмбеддингов)."""
import tempfile

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from database import init_database
from similar_dialog import DuplicatesDialog


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def _set_backend(name):
    qs = QSettings("LocalReviewer", "LocalReviewer")
    old = qs.value("ui/similarity_backend", None)
    qs.setValue("ui/similarity_backend", name)
    return old


def _restore_backend(old):
    qs = QSettings("LocalReviewer", "LocalReviewer")
    if old is None:
        qs.remove("ui/similarity_backend")
    else:
        qs.setValue("ui/similarity_backend", old)


def test_dup_threshold_per_backend():
    _app()
    p = _proj()
    old = _set_backend("tfidf")
    try:
        d = DuplicatesDialog(p, None, None)
        try:
            d.show()
            assert d.thr_spin.value() == 90
            assert "70–80" in d.hint_label.text()
        finally:
            d.close()
    finally:
        _restore_backend(old)
    old = _set_backend("embedding")
    try:
        d = DuplicatesDialog(p, None, None)
        try:
            d.show()
            assert d.thr_spin.value() == 95
            assert "93–98" in d.hint_label.text()
        finally:
            d.close()
    finally:
        _restore_backend(old)
