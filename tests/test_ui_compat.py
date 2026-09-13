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
