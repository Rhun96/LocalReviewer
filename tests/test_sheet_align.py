"""SheetAlign: сравнение структуры листов, упорядочивание, выгрузка."""
import os
import tempfile

import pytest


def _make_xlsx(path, sheets):
    import openpyxl
    wb = openpyxl.Workbook()
    first = True
    for name, rows in sheets:
        ws = wb.active if first else wb.create_sheet(title=name)
        if first:
            ws.title = name
        for r in rows:
            ws.append(list(r))
        first = False
    wb.save(path)
    return path


def test_compare_detects_moves_and_extras():
    import sheet_align_service as s
    p = _make_xlsx(os.path.join(tempfile.mkdtemp(), "r.xlsx"), [
        ("v17", [["ответ", "вопрос", "id"], ["a1", "q1", "k1"]]),
        ("v18", [["id", "лишняя", "вопрос", "ответ"], ["k1", "x", "q1", "a1"]]),
    ])
    d = s.compare_sheets(p, "excel", "v17", "v18")
    assert d["same_order"] is False
    assert d["extra_in_target"] == ["лишняя"]
    assert d["missing_in_target"] == []
    moved = {m["header"]: (m["ref_index"], m["target_index"]) for m in d["moved"]}
    assert moved["ответ"] == (0, 3) and moved["id"] == (2, 0)
    assert d["ref_roles"].get("ответ") == "answer"


def test_normalize_and_export_roundtrip():
    import sheet_align_service as s
    from file_reader import FileReader
    p = _make_xlsx(os.path.join(tempfile.mkdtemp(), "r.xlsx"), [
        ("v17", [["ответ", "вопрос", "id"], ["a1", "q1", "k1"]]),
        ("v18", [["id", "вопрос", "ответ"], ["k1", "q1", "a1"]]),
    ])
    headers, rows = s.normalize_sheet(p, "v17", "v18")
    assert headers == ["ответ", "вопрос", "id"]
    assert rows[0] == ["a1", "q1", "k1"]
    out = os.path.join(tempfile.mkdtemp(), "ord.xlsx")
    s.write_sheet_xlsx(out, "v18", headers, rows)
    assert FileReader.read_excel_data(out, "v18") == [
        {"ответ": "a1", "вопрос": "q1", "id": "k1"}]
    whole = os.path.join(tempfile.mkdtemp(), "whole.xlsx")
    s.write_file_xlsx(p, whole, "v18", headers, rows)
    assert FileReader.read_excel_sheets(whole) == ["v17", "v18"]
    assert FileReader.read_excel_data(whole, "v18")[0]["ответ"] == "a1"


def test_normalize_missing_and_drop_extra():
    import sheet_align_service as s
    p = _make_xlsx(os.path.join(tempfile.mkdtemp(), "r.xlsx"), [
        ("A", [["id", "ответ"], ["k", "a"]]),
        ("B", [["ответ", "мусор"], ["a", "z"]]),
    ])
    headers, rows = s.normalize_sheet(p, "A", "B", keep_extra=False)
    assert headers == ["id", "ответ"]
    assert rows[0] == ["", "a"]  # недостающая — пустая
    headers2, _ = s.normalize_sheet(p, "A", "B", keep_extra=True)
    assert headers2 == ["id", "ответ", "мусор"]
    with pytest.raises(ValueError):
        s.compare_sheets(p, "csv", "A", "B")


def test_filter_values_stats_and_rows():
    import sheet_align_service as s
    p = _make_xlsx(os.path.join(tempfile.mkdtemp(), "r.xlsx"), [
        ("A", [["id", "cat"], ["k1", "ava"], ["k2", "cc"], ["k3", "ava"]]),
    ])
    vals, truncated = s.column_values(p, "excel", "A", "cat")
    assert vals == ["ava", "cc"] and truncated is False
    assert s.column_values(p, "excel", "A", "nope")[0] == []
    st = s.sheet_stats(p, "excel", "A", "cat", "ava")
    assert (st["total"], st["filtered"]) == (3, 2)
    assert st["id_coverage"] == {"column": "id", "filled": 2, "total": 2}
    headers, rows = s.normalize_sheet(p, "A", "A")
    sub = s.filter_rows(headers, rows, "cat", "cc")
    assert len(sub) == 1 and sub[0][0] == "k2"


def test_multi_condition_filter():
    import sheet_align_service as s
    headers = ["id", "product", "channel"]
    rows = [["k1", "avia", "chat"], ["k2", "avia", "mail"],
            ["k3", "rail", "chat"], ["k4", "avia", "chat"]]
    assert len(s.filter_rows(headers, rows, [("product", "avia")])) == 3
    both = s.filter_rows(headers, rows, [("product", "avia"), ("channel", "chat")])
    assert [r[0] for r in both] == ["k1", "k4"]
    assert s.filter_rows(headers, rows, []) == rows
    assert s.filter_rows(headers, rows, None) == rows
    assert s.filter_rows(headers, rows, [("nope", "x")]) == rows
