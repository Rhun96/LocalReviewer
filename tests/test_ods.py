"""ODS: чтение, превью, импорт."""
import os
import tempfile

import pytest
from database import init_database
from file_reader import FileReader
from importer import import_file

odf = pytest.importorskip("odf")


def _make_ods(path, sheets_rows):
    from odf.opendocument import OpenDocumentSpreadsheet
    from odf.table import Table, TableRow, TableCell
    from odf.text import P
    doc = OpenDocumentSpreadsheet()
    for name, rows in sheets_rows:
        t = Table(name=name)
        for row in rows:
            tr = TableRow()
            for v in row:
                tc = TableCell()
                tc.addElement(P(text=v))
                tr.addElement(tc)
            t.addElement(tr)
        doc.spreadsheet.addElement(t)
    doc.save(path)
    return path


def test_ods_detect_and_read(tmp_path=None):
    p = _make_ods(os.path.join(tempfile.mkdtemp(), "t.ods"),
                  [("Sheet1", [["q", "i"], ["privet", "k1"], ["poka", "k2"]]),
                   ("Second", [["a"], ["b"]])])
    fr = FileReader()
    assert fr.detect_file_type(p) == "ods"
    assert fr.read_ods_sheets(p) == ["Sheet1", "Second"]
    prev = fr.read_ods_preview(p, "Sheet1")
    assert prev["headers"] == ["q", "i"] and len(prev["rows"]) == 2
    data = fr.read_ods_data(p, "Sheet1")
    assert data == [{"q": "privet", "i": "k1"}, {"q": "poka", "i": "k2"}]
    with pytest.raises(ValueError):
        fr.read_ods_preview(p, "Nope")


def test_ods_import():
    p = _make_ods(os.path.join(tempfile.mkdtemp(), "t.ods"),
                  [("S", [["q", "i"], ["privet", "k1"]])])
    proj = tempfile.mkdtemp()
    init_database(proj)
    fid, imp, skipped = import_file(proj, p, "ods", "S", 0,
                                    {"q": "primary_text", "i": "source_id"},
                                    FileReader.read_ods_data(p, "S"))
    assert (imp, skipped) == (1, 0)
    from filter_service import get_filtered_case_ids
    assert len(get_filtered_case_ids(proj, {})) == 1
