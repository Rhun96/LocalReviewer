"""Даты Excel не роняют импорт (datetime is not JSON serializable)."""
import datetime as _dt
import tempfile

import openpyxl
from database import init_database
from file_reader import FileReader
from importer import _cell_str, import_file


def test_cell_str_dates():
    assert _cell_str(_dt.datetime(2024, 1, 15, 0, 0)) == "2024-01-15"
    assert _cell_str(_dt.datetime(2024, 1, 15, 14, 30)) == "2024-01-15 14:30"
    assert _cell_str(_dt.date(2024, 1, 15)) == "2024-01-15"
    assert _cell_str("plain") == "plain"
    assert _cell_str(42) == 42


def _xlsx_with_dates(n=1200):
    tmp = tempfile.mkdtemp()
    path = tmp + "/dates.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ID", "Дата", "Вопрос"])
    base = _dt.datetime(2024, 1, 1, 10, 30)
    for i in range(n):
        ws.append([f"D-{i}", base + _dt.timedelta(days=i), f"вопрос {i}"])
    wb.save(path)
    return path


def test_big_excel_with_datetimes_imports():
    path = _xlsx_with_dates()
    data = FileReader.read_excel_data(path, "Sheet", 0)
    assert isinstance(data[0]["Дата"], str)
    p = tempfile.mkdtemp()
    init_database(p)
    fid, n, skipped = import_file(
        p, path, "excel", "Sheet", 0,
        {"ID": "source_id", "Дата": "metadata", "Вопрос": "primary_text"},
        data)
    assert n == 1200 and skipped == 0, (n, skipped)
    from database import db
    with db(p) as conn:
        row = conn.execute("SELECT primary_text FROM cases LIMIT 1").fetchone()
        assert "вопрос" in row["primary_text"]
