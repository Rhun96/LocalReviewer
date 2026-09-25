"""ui_compat доступен и безопасен без GUI."""


def test_compat_names():
    import ui_compat as u
    for name in ("FPushButton", "FPrimaryButton", "FTitleLabel", "FSubtitleLabel",
                 "FBodyLabel", "FCaptionLabel", "FCard", "FLineEdit", "FTextEdit",
                 "FComboBox", "FCheckBox", "notify", "confirm", "apply_theme",
                 "effective_theme", "clear_in_fluent", "maybe_style",
                  "get_theme_mode", "set_theme_mode"):
        assert hasattr(u, name), name
    assert u.apply_theme("nonsense") == "system"
    assert u.effective_theme() in ("light", "dark")
    assert isinstance(u.FLUENT, bool)


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
