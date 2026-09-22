"""Подсветка фрагментов ответа: CRUD, пересечения, протухание, рендер."""
import tempfile

import pytest
from database import SCHEMA_VERSION, init_database
from importer import import_file
import highlight_service as hl


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text"},
                [{"q": "q", "a": "alpha beta gamma delta"}])
    return tmp


def test_schema_current():
    assert SCHEMA_VERSION == 19
    p = _proj()
    from database import db
    with db(p) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == 19


def test_add_list_render():
    p = _proj()
    hid = hl.add_highlight(p, 1, 0, 5, "green")
    assert hid > 0
    items = hl.list_highlights(p, 1)
    assert len(items) == 1 and items[0]["color"] == "green"
    html = hl.render_answer_html(p, 1)
    assert "<span" in html and "alpha" in html and "2ea043" in html


def test_validation():
    p = _proj()
    with pytest.raises(ValueError):
        hl.add_highlight(p, 1, 5, 5, "green")  # пустой
    with pytest.raises(ValueError):
        hl.add_highlight(p, 1, -1, 5, "red")  # вне текста
    with pytest.raises(ValueError):
        hl.add_highlight(p, 1, 0, 9999, "red")  # за границей
    with pytest.raises(ValueError):
        hl.add_highlight(p, 1, 0, 5, "blue")  # нет цвета
    with pytest.raises(ValueError):
        hl.add_highlight(p, 999, 0, 5, "green")  # нет кейса


def test_overlap_replaced():
    p = _proj()
    hl.add_highlight(p, 1, 0, 11, "green")
    hl.add_highlight(p, 1, 6, 16, "red")  # пересекает — старый уходит
    items = hl.list_highlights(p, 1)
    assert len(items) == 1 and items[0]["color"] == "red"
    assert (items[0]["start_offset"], items[0]["end_offset"]) == (6, 16)
    hl.add_highlight(p, 1, 17, 22, "yellow")  # не пересекает — живёт рядом
    assert len(hl.list_highlights(p, 1)) == 2


def test_stale_pruned_on_text_change():
    p = _proj()
    hl.add_highlight(p, 1, 0, 5, "green")
    from database import db
    with db(p) as conn:
        conn.execute("UPDATE cases SET response_text=? WHERE case_id=1",
                     ("completely different",))
    assert hl.list_highlights(p, 1) == []
    assert "<span" not in hl.render_answer_html(p, 1)


def test_remove_range_trims_edges():
    p = _proj()
    hl.add_highlight(p, 1, 0, 11, "green")  # "alpha beta"
    assert hl.remove_range(p, 1, 6, 11) == 1
    items = hl.list_highlights(p, 1)
    assert [(i["start_offset"], i["end_offset"], i["color"]) for i in items] == [
        (0, 6, "green")]
    # середина: раскалывает на два куска тем же цветом
    assert hl.remove_range(p, 1, 1, 3) == 1
    items = hl.list_highlights(p, 1)
    assert [(i["start_offset"], i["end_offset"]) for i in items] == [(0, 1), (3, 6)]
    # мимо: ничего не задето
    assert hl.remove_range(p, 1, 10, 15) == 0
    assert len(hl.list_highlights(p, 1)) == 2
    with pytest.raises(ValueError):
        hl.remove_range(p, 1, 5, 5)


def test_multiline_offsets_survive_render():
    """Переносы/пробелы не должны сдвигать смещения (баг снятия)."""
    import tempfile as _t
    from database import init_database as _init
    from importer import import_file as _imp
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0,
         {"q": "primary_text", "a": "response_text"},
         [{"q": "q", "a": "line one\nline  two\n\tindented"}])
    html = hl.render_answer_html(p, 1)
    assert "<br>" in html
    hid = hl.add_highlight(p, 1, 0, 20, "red")
    assert hid > 0
    # снятие тем же диапазоном — попадает ровно
    assert hl.remove_range(p, 1, 0, 20) == 1
    assert hl.list_highlights(p, 1) == []


def test_qt_offsets_with_emoji():
    text = "🙂 alpha beta"
    assert hl.qt_len(text) == len(text) + 1
    assert hl.qt_offset_to_py(text, 0) == 0
    assert hl.qt_offset_to_py(text, 2) == 1  # после смайла
    assert hl.qt_offset_to_py(text, 3) == 2
    assert hl.qt_offset_to_py(text, 999) == len(text)
    assert hl.qt_offset_to_py("plain", 3) == 3  # BMP — тождество


def test_emoji_roundtrip_unpaint():
    import tempfile as _t
    from database import init_database as _init
    from importer import import_file as _imp
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0,
         {"q": "primary_text", "a": "response_text"},
         [{"q": "q", "a": "🙂 alpha beta"}])
    # Qt-видит «alpha» как 3..8, Python — как 2..7
    s = hl.qt_offset_to_py("🙂 alpha beta", 3)
    e = hl.qt_offset_to_py("🙂 alpha beta", 8)
    assert (s, e) == (2, 7)
    hid = hl.add_highlight(p, 1, s, e, "green")
    assert hid > 0
    assert hl.remove_range(p, 1, s, e) == 1
    assert hl.list_highlights(p, 1) == []


def test_explicit_range_path():
    """Путь меню: готовый диапазон, живой курсор не читается."""
    import tempfile as _t
    from database import init_database as _init
    from importer import import_file as _imp
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0,
         {"q": "primary_text", "a": "response_text"},
         [{"q": "q", "a": "alpha beta"}])
    hl.add_highlight(p, 1, 0, 5, "green")
    assert hl.remove_range(p, 1, 0, 3) == 1
    items = hl.list_highlights(p, 1)
    assert [(i["start_offset"], i["end_offset"]) for i in items] == [(3, 5)]


def test_menu_wiring_survives_checked_flag():
    """Регрессия: triggered(bool) не должен затирать диапазон (bool unpack)."""
    import os as _os
    _os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import tempfile as _t
    from PySide6.QtWidgets import QApplication, QMenu
    from database import init_database as _init
    from importer import import_file as _imp
    QApplication.instance() or QApplication([])
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0,
         {"q": "primary_text", "a": "response_text"},
         [{"q": "q", "a": "alpha beta"}])
    from review_screen import ReviewScreen
    w = ReviewScreen(p)
    try:
        menu = QMenu(w)
        a_g, _a_r, _a_y, a_un = w._wire_answer_actions(menu, (0, 5))
        a_g.trigger()  # QAction сам шлёт checked в triggered
        items = hl.list_highlights(p, 1)
        assert [(i["start_offset"], i["end_offset"]) for i in items] == [(0, 5)]
        a_un.trigger()
        assert hl.list_highlights(p, 1) == []
    finally:
        w.close()


def test_clear():
    p = _proj()
    hl.add_highlight(p, 1, 0, 5, "green")
    hl.add_highlight(p, 1, 6, 10, "red")
    assert hl.clear_highlights(p, 1) == 2
    assert hl.list_highlights(p, 1) == []
