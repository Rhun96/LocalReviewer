"""Обратная связь с боя: фильтр после импорта, Excel-разметка, прыжок,
эталон в кейсе, bulk-удаление прогонов."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile

import openpyxl
from database import init_database
from importer import import_file
from filter_service import get_filtered_case_ids


def _proj(rows):
    tmp = tempfile.mkdtemp()
    init_database(tmp)
    import_file(tmp, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "a": "response_text",
                 "i": "source_id", "e": "operator_response"}, rows)
    return tmp


def test_file_filter_reset_on_import():
    from types import SimpleNamespace
    import import_wizard
    from import_wizard import ImportWizard
    import_wizard.notify = lambda *a, **k: None
    p = _proj([{"q": "q1", "a": "a1", "i": "k1", "e": ""}])
    fid, _, _ = import_file(p, "g.xlsx", "excel", "S", 0,
                            {"q": "primary_text", "i": "source_id"},
                            [{"q": "q2", "i": "k2"}])
    rev = SimpleNamespace(filters={"file_id": 999, "statuses": ["bad"]})
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    wiz = ImportWizard(p, None)
    try:
        wiz.parent_window = SimpleNamespace(screens={"review": rev})
        wiz._on_import_done((fid, 1, 0),
                            [], SimpleNamespace(close=lambda: None))
        assert rev.filters == {"statuses": ["bad"]}
    finally:
        wiz.close()


def test_annotation_excel_aliases():
    import annotation_io_service as aio
    tmp = tempfile.mkdtemp()
    path = os.path.join(tmp, "ann.xlsx")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ид", "статус", "комментарий", "лишняя"])
    ws.append(["k1", "bad", "плохо", "x"])
    ws.append(["", "good", "", ""])
    wb.save(path)
    rows, errors = aio.read_annotation_table(path)
    assert len(rows) == 1 and rows[0]["id"] == "k1"
    assert rows[0]["status"] == "bad" and rows[0]["comment"] == "плохо"
    assert len(errors) == 1


def test_annotation_apply_jumps_to_first_case():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import annotation_io_service as aio
    from annotation_io_dialog import ImportAnnotationsDialog
    p = _proj([{"q": "q1", "a": "a1", "i": "k1", "e": ""}])
    rows = [{"id": "k1", "status": "bad", "comment": "c",
             "category": "", "subcategory": "", "severity": ""}]
    dlg = ImportAnnotationsDialog(p, None)
    try:
        dlg._preview_data = aio.preview_import(p, rows)
        dlg.mode_combo.setCurrentIndex(2)  # update
        dlg._apply()
        ids = get_filtered_case_ids(p, {})
        assert dlg.result_case_id == ids[0]
        assert dlg.btn_goto.isEnabled()
    finally:
        dlg.close()


def test_metadata_labels_ru():
    from constants import metadata_column_label as L
    assert L("operator_response") == "Эталон"
    assert L("product") == "Продукт"
    assert L("topic") == "Тема"
    assert L("custom:Моя") == "custom:Моя"
    assert L("Запрос") == "Запрос"


def test_jump_opens_case_outside_filter():
    import tempfile as _t
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from database import init_database as _init
    from importer import import_file as _imp
    from review_screen import ReviewScreen
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "a.xlsx", "excel", "S", 0, {"q": "primary_text"},
         [{"q": "q1"}, {"q": "q2"}])
    _imp(p, "b.xlsx", "excel", "S", 0, {"q": "primary_text"},
         [{"q": "q3"}])
    from database import db
    with db(p) as conn:
        fida = conn.execute("SELECT file_id FROM files WHERE file_name LIKE 'a%'"
                            ).fetchone()["file_id"]
        cid_b = conn.execute("SELECT case_id FROM cases WHERE primary_text='q3'"
                             ).fetchone()["case_id"]
    w = ReviewScreen(p)
    try:
        w.show()
        w.filters = {"file_id": fida}
        w.load_case_ids()
        assert cid_b not in w.case_ids
        assert w.ensure_visible_case(cid_b) is True
        assert w.filters == {}
        assert w.current_case_id == cid_b
    finally:
        w.close()


def test_reference_fallback_keys():
    from bug_report_service import case_reference
    assert case_reference({"operator_response": "a"}) == "a"
    assert case_reference({"Эталон": "b"}) == "b"
    assert case_reference({"reference": "c"}) == "c"
    assert case_reference({"wrong": "x"}) == ""
    assert case_reference(None) == ""
    assert case_reference({"operator_response": "", "эталонный ответ": "d"}) == "d"


def test_goto_enabled_after_preview():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from annotation_io_dialog import ImportAnnotationsDialog
    p = _proj([{"q": "q1", "a": "a1", "i": "k1", "e": ""}])
    dlg = ImportAnnotationsDialog(p, None)
    try:
        assert not dlg.btn_goto.isEnabled()
        dlg._rows = [{"id": "k1", "status": "bad", "comment": "c",
                      "category": "", "subcategory": "", "severity": ""}]
        dlg._preview()
        assert dlg.btn_goto.isEnabled()
        assert dlg.result_case_id is not None
    finally:
        dlg.close()


def test_reference_panel_in_case():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from review_screen import ReviewScreen
    p = _proj([{"q": "q1", "a": "a1", "i": "k1", "e": "правильно так"}])
    w = ReviewScreen(p)
    try:
        w.show()
        labels = [x.text() for x in w.findChildren(
            __import__("PySide6.QtWidgets", fromlist=["QLabel"]).QLabel)]
        assert any("Эталон" in t for t in labels), labels
        assert any("правильно так" in t for t in labels)
    finally:
        w.close()


def test_runs_bulk_delete():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import model_run_service as m
    import runs_screen as rs
    rs.confirm = lambda *a, **k: True
    p = tempfile.mkdtemp()
    init_database(p)
    ra = m.create_run(p, "A", "mx")
    rb = m.create_run(p, "B", "mx")
    assert len(m.list_runs(p)) == 2
    from runs_screen import ModelRunsScreen
    w = ModelRunsScreen(p, None)
    try:
        w.show()
        for i in range(w.runs_list.count()):
            w.runs_list.item(i).setSelected(True)
        w._delete_run()
        assert m.list_runs(p) == []
        _ = (ra, rb)
    finally:
        w.close()
