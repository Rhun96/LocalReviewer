"""ui_compat доступен и безопасен без GUI."""


def test_compat_names():
    import ui_compat as u
    for name in ("FPushButton", "FPrimaryButton", "FTitleLabel", "FSubtitleLabel",
                 "FBodyLabel", "FCaptionLabel", "FCard", "FLineEdit", "FTextEdit",
                  "FComboBox", "FCheckBox", "notify", "confirm", "apply_theme",
                  "effective_theme", "clear_in_fluent", "maybe_style",
                   "get_theme_mode", "set_theme_mode",
                   "FSwitch", "connect_check_changed",
                   "get_palette_mode", "set_palette_mode"):
        assert hasattr(u, name), name
    assert u.apply_theme("nonsense") == "system"
    assert u.effective_theme() in ("light", "dark")
    assert isinstance(u.FLUENT, bool)


def test_palette_mode_roundtrip_snapshot():
    """QSettings-снапшот: чужое значение ui/palette не трогаем."""
    from PySide6.QtCore import QSettings
    import ui_compat as u
    qs = QSettings("LocalReviewer", "LocalReviewer")
    old = qs.value("ui/palette", None)
    try:
        assert u.set_palette_mode("ref") == "ref"
        assert u.get_palette_mode() == "ref"
        assert u.set_palette_mode("nope") == "classic"
        assert u.get_palette_mode() == "classic"
    finally:
        if old is None:
            qs.remove("ui/palette")
        else:
            qs.setValue("ui/palette", old)


def test_format_dt_unified():
    from ui_compat import format_dt
    assert format_dt("2026-09-26") == "26-09-2026"
    assert format_dt("2026-09-24T18:22:15") == "24-09-2026 18:22"
    assert format_dt("2026-09-24 18:22:15") == "24-09-2026 18:22"
    assert format_dt("") == "—"
    assert format_dt(None) == "—"
    assert format_dt("мусор") == "мусор"


def test_parse_date_input_both_formats():
    from ui_compat import parse_date_input
    assert parse_date_input("26-09-2026") == "2026-09-26"
    assert parse_date_input("26.09.2026") == "2026-09-26"
    assert parse_date_input("2026-09-26") == "2026-09-26"
    assert parse_date_input("  01-02-2026  ") == "2026-02-01"
    assert parse_date_input("") == ""
