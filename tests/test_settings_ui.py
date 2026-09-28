"""Настройки: тумблеры вместо чекбоксов (E), save/load через свитчи."""
import tempfile

from PySide6.QtWidgets import QApplication, QCheckBox

from database import init_database
from settings_screen import SettingsScreen
from ui_compat import FSwitch, connect_check_changed

SWITCHES = (
    "auto_next_checkbox", "skip_reviewed_checkbox", "checks_first_checkbox",
    "no_return_good_checkbox", "restore_checkbox", "debug_content_checkbox",
    "check_url_checkbox", "check_email_checkbox", "check_phone_checkbox",
    "check_spaces_checkbox", "check_caps_checkbox", "check_duplicate_checkbox",
    "check_repeat_words_checkbox", "check_punct_checkbox",
    "check_repeat_chars_checkbox", "check_long_sentence_checkbox",
    "check_junk_checkbox", "check_html_checkbox", "check_markdown_checkbox",
    "check_encoding_checkbox", "check_suspicious_checkbox",
)


def _win():
    QApplication.instance() or QApplication([])
    p = tempfile.mkdtemp()
    init_database(p)
    return SettingsScreen(p, None), p


def test_all_switches_present_with_defaults():
    w, _p = _win()
    try:
        w.show()
        for name in SWITCHES:
            sw = getattr(w, name)
            assert isinstance(sw, FSwitch), name
        assert w.auto_next_checkbox.isChecked()
        assert not w.skip_reviewed_checkbox.isChecked()
        assert w.check_url_checkbox.isChecked()
    finally:
        w.close()


def test_switch_save_load_roundtrip():
    w, p = _win()
    try:
        w.show()
        w.check_url_checkbox.setChecked(False)
        w.skip_reviewed_checkbox.setChecked(True)
        w.on_save()
    finally:
        w.close()
    w2 = SettingsScreen(p, None)
    try:
        w2.show()
        assert not w2.check_url_checkbox.isChecked()
        assert w2.skip_reviewed_checkbox.isChecked()
        assert w2.check_email_checkbox.isChecked()
    finally:
        w2.close()


def test_connect_check_changed_both_widgets():
    _ = QApplication.instance() or QApplication([])
    from ui_compat import FLUENT
    hits = []
    box = QCheckBox()
    connect_check_changed(box, lambda *_a: hits.append("box"))
    box.setChecked(True)
    assert hits == ["box"]
    if FLUENT:
        sw = FSwitch()
        connect_check_changed(sw, lambda *_a: hits.append("switch"))
        sw.setChecked(True)
        assert hits == ["box", "switch"]


def test_custom_colors_group_snapshot():
    """Группа «Свои цвета»: 11 полей, дефолты, мусор не пишется."""
    from PySide6.QtCore import QSettings
    from styles import CUSTOM_COLORS
    import ui_compat as u
    qs = QSettings("LocalReviewer", "LocalReviewer")
    keys = [f"ui/custom_{ck}" for ck, _l, _c, _f in CUSTOM_COLORS]
    old = {k: qs.value(k, None) for k in keys}
    w, _p = _win()
    try:
        w.show()
        assert len(w.color_edits) == len(CUSTOM_COLORS) == 11
        assert len(w.color_swatches) == 11
        base = u.get_custom_colors()
        for ck, _l, _c, _f in CUSTOM_COLORS:
            assert w.color_edits[ck].text() == base[ck]
        # валидный hex через поле — сохраняется; мусор — нет.
        w.color_edits["accent"].setText("#" + "abcdef")
        assert u.get_custom_colors()["accent"] == "#" + "abcdef"
        w.color_edits["accent"].setText("мусор")
        assert u.get_custom_colors()["accent"] == "#" + "abcdef"
        w.on_custom_colors_reset()
        assert u.get_custom_colors() == base
    finally:
        w.close()
        for k, v in old.items():
            if v is None:
                qs.remove(k)
            else:
                qs.setValue(k, v)


def test_pick_color_via_dialog(monkeypatch):
    """Клик по квадратику: выбор применяется, отмена — нет (диалог мок)."""
    from PySide6.QtCore import QSettings
    from PySide6.QtGui import QColor
    import PySide6.QtWidgets as _qw
    from styles import CUSTOM_COLORS
    import ui_compat as u
    qs = QSettings("LocalReviewer", "LocalReviewer")
    keys = [f"ui/custom_{ck}" for ck, _l, _c, _f in CUSTOM_COLORS]
    old = {k: qs.value(k, None) for k in keys}
    w, _p = _win()
    try:
        w.show()
        base = u.get_custom_colors()["accent"]
        picked = "#" + "112233"
        monkeypatch.setattr(_qw.QColorDialog, "getColor",
                            staticmethod(lambda *a, **k: QColor(picked)))
        w._pick_color("accent")
        assert u.get_custom_colors()["accent"] == picked
        assert w.color_edits["accent"].text() == picked
        monkeypatch.setattr(_qw.QColorDialog, "getColor",
                            staticmethod(lambda *a, **k: QColor()))
        w._pick_color("accent")
        assert u.get_custom_colors()["accent"] == picked
        assert base != picked
    finally:
        w.close()
        for k, v in old.items():
            if v is None:
                qs.remove(k)
            else:
                qs.setValue(k, v)
