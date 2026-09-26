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


def test_palette_combo_snapshot():
    from PySide6.QtCore import QSettings
    qs = QSettings("LocalReviewer", "LocalReviewer")
    old = qs.value("ui/palette", None)
    w, _p = _win()
    try:
        w.show()
        assert w.palette_combo.count() == 2
        for i in range(w.palette_combo.count()):
            if w.palette_combo.itemData(i) == "ref":
                w.palette_combo.setCurrentIndex(i)
                break
        from ui_compat import get_palette_mode
        assert get_palette_mode() == "ref"
    finally:
        w.close()
        if old is None:
            qs.remove("ui/palette")
        else:
            qs.setValue("ui/palette", old)
