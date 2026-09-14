"""Smoke-тесты без Qt: БД, импорт, фильтры, автопроверки, экспорт, бэкап."""
import tempfile
from pathlib import Path

from database import init_database
from importer import import_file
from filter_service import get_filtered_case_ids
from autocheck_service import check_case
from backup_service import create_backup, get_backups_list


def _make_project():
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    return tmp


def test_init_and_import():
    proj = _make_project()
    data = [{"q": "Привет", "a": "Здравствуйте!"}]
    mapping = {"q": "primary_text", "a": "response_text"}
    file_id, n = import_file(proj, "f.xlsx", "excel", "Sheet1", 0, mapping, data)
    assert n == 1 and file_id > 0
    ids = get_filtered_case_ids(proj, {})
    assert len(ids) == 1


def test_autocheck_empty():
    flags = check_case({"primary_text": "", "response_text": ""})
    assert any(c[0] == "empty_text" for c in flags)


def test_backup_roundtrip():
    proj = _make_project()
    p = create_backup(proj)
    assert Path(p).exists()
    assert len(get_backups_list(proj)) >= 1
