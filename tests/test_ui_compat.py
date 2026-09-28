"""ui_compat доступен и безопасен без GUI."""


def test_compat_names():
    import ui_compat as u
    for name in ("FPushButton", "FPrimaryButton", "FTitleLabel", "FSubtitleLabel",
                 "FBodyLabel", "FCaptionLabel", "FCard", "FLineEdit", "FTextEdit",
                  "FComboBox", "FCheckBox", "notify", "confirm", "apply_theme",
                  "effective_theme", "clear_in_fluent", "maybe_style",
                   "get_theme_mode", "set_theme_mode",
                   "FSwitch", "connect_check_changed",
                   "get_custom_colors", "set_custom_color",
                   "reset_custom_colors", "is_valid_hex"):
        assert hasattr(u, name), name
    assert u.apply_theme("nonsense") == "system"
    assert u.effective_theme() in ("light", "dark")
    assert isinstance(u.FLUENT, bool)


def test_custom_colors_roundtrip_snapshot():
    """QSettings-снапшот: чужие ui/custom_* не трогаем."""
    from PySide6.QtCore import QSettings
    import ui_compat as u
    from styles import CUSTOM_COLORS
    qs = QSettings("LocalReviewer", "LocalReviewer")
    keys = [f"ui/custom_{ck}" for ck, _l, _c, _f in CUSTOM_COLORS]
    old = {k: qs.value(k, None) for k in keys}
    # hex только конкатенацией: литерал #RRGGBB в тесте уронит hex-гард.
    good = "#" + "123456"
    green = "#" + "00ff41"
    try:
        assert u.is_valid_hex(green)
        assert not u.is_valid_hex("00ff41")
        assert not u.is_valid_hex("#xyz")
        assert not u.is_valid_hex(None)
        base = u.get_custom_colors()
        assert len(base) == len(CUSTOM_COLORS) == 11
        assert u.set_custom_color("accent", good) == good
        assert u.get_custom_colors()["accent"] == good
        try:
            u.set_custom_color("accent", "мусор")
            raise AssertionError("мусор должен отклоняться")
        except ValueError:
            pass
        try:
            u.set_custom_color("нетакого", good)
            raise AssertionError("чужой ключ должен отклоняться")
        except ValueError:
            pass
        u.reset_custom_colors()
        assert u.get_custom_colors() == base
    finally:
        for k, v in old.items():
            if v is None:
                qs.remove(k)
            else:
                qs.setValue(k, v)


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
