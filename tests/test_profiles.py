"""Профили ревью: seed, CRUD, активный, валидация конфига."""
import tempfile
from database import init_database
from review_profile_service import (
    create_profile, delete_profile, enabled_statuses, get_active_profile,
    get_profile, list_profiles, set_active_profile, update_profile,
    validate_config,
)


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    return tmp


def test_seed_default():
    p = _proj()
    profiles = list_profiles(p)
    assert len(profiles) == 1 and profiles[0]["is_default"]
    active = get_active_profile(p)
    assert active["name"] == "Default"
    assert len(enabled_statuses(active["config"])) == 5


def test_crud_and_active():
    p = _proj()
    cfg = {"statuses": [
        {"code": "good", "name": "Ок", "hotkey": "q", "enabled": True},
        {"code": "bad", "name": "Брак", "hotkey": "w", "enabled": True},
        {"code": "skip", "name": "Дальше", "hotkey": "", "enabled": True},
        {"code": "uncertain", "name": "?", "hotkey": "", "enabled": False},
        {"code": "duplicate", "name": "Дубль", "hotkey": "", "enabled": False},
    ], "require_category_for_bad": True, "require_comment_for_bad": "required"}
    pid = create_profile(p, "Строгий", cfg)
    set_active_profile(p, pid)
    active = get_active_profile(p)
    assert active["name"] == "Строгий"
    assert active["config"]["require_category_for_bad"] is True
    assert [s["code"] for s in enabled_statuses(active["config"])] == ["good", "bad", "skip"]
    # default удалить нельзя
    default_id = [x["profile_id"] for x in list_profiles(p) if x["is_default"]][0]
    try:
        delete_profile(p, default_id)
        raise AssertionError("should raise")
    except ValueError:
        pass
    delete_profile(p, pid)
    assert get_active_profile(p)["is_default"]  # fallback на default


def test_validate_rejects():
    bad_cfgs = [
        {},
        {"statuses": []},
        {"statuses": [{"code": "nope", "name": "X", "hotkey": "1", "enabled": True}]},
        {"statuses": [
            {"code": "good", "name": "A", "hotkey": "1", "enabled": True},
            {"code": "bad", "name": "B", "hotkey": "1", "enabled": True}]},
        {"statuses": [
            {"code": "good", "name": "A", "hotkey": "", "enabled": False}]},
    ]
    for cfg in bad_cfgs:
        try:
            validate_config(cfg)
            raise AssertionError(f"should raise: {cfg}")
        except ValueError:
            pass
    # update несуществующего
    p = _proj()
    try:
        update_profile(p, 9999, "X", validate_config({
            "statuses": [{"code": "good", "name": "G", "hotkey": "1",
                          "enabled": True}]}))
        raise AssertionError("should raise")
    except ValueError:
        pass
    assert get_profile(p, 9999) is None
