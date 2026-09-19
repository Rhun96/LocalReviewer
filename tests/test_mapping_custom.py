"""Свои категории маппинга: хранение, валидация, переприменение выбора."""
import tempfile

import pytest

from database import init_database
import mapping_custom as mc


def _proj():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    return tmp


def test_crud_and_persistence():
    p = _proj()
    assert mc.load_custom_categories(p) == []
    assert mc.add_custom_category(p, "Канал") == ["Канал"]
    assert mc.add_custom_category(p, " Тема ") == ["Канал", "Тема"]
    assert mc.load_custom_categories(p) == ["Канал", "Тема"]
    assert mc.custom_roles(p) == [("custom:Канал", "📎 Канал"),
                                  ("custom:Тема", "📎 Тема")]
    assert mc.remove_custom_category(p, "Канал") == ["Тема"]
    assert mc.load_custom_categories(p) == ["Тема"]
    with pytest.raises(ValueError):
        mc.remove_custom_category(p, "Нет такой")


def test_validation():
    p = _proj()
    with pytest.raises(ValueError):
        mc.add_custom_category(p, "   ")
    with pytest.raises(ValueError):
        mc.add_custom_category(p, "x" * 65)
    with pytest.raises(ValueError):
        mc.add_custom_category(p, "a\nb")
    mc.add_custom_category(p, "Канал")
    with pytest.raises(ValueError):
        mc.add_custom_category(p, "Канал")
    with pytest.raises(ValueError):
        mc.save_custom_categories(p, ["ok", ""])
    assert mc.load_custom_categories(p) == ["Канал"]


def test_reapply_mapping():
    roles = [("ignore", "Не импортировать"), ("answer", "Ответ"),
             ("custom:Канал", "📎 Канал")]
    saved = {"a": "answer", "b": "custom:Канал", "c": "custom:Удалена"}
    assert mc.reapply_mapping(["a", "b", "c"], roles, saved) == {
        "a": "answer", "b": "custom:Канал", "c": None}
    assert mc.reapply_mapping(["a"], roles, {}) == {"a": None}
