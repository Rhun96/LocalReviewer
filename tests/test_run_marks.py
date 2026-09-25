"""Импорт оценок прогона: парсинг, Preview-бакеты, Merge/Update, маппинг."""
import tempfile

import run_marks_io_service as mio


def _proj():
    from database import init_database
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"},
                 {"q": "q3", "i": "k3"}])
    return p


def _run(p):
    import model_run_service as m
    rid = m.create_run(p, "old", "mx")
    m.import_run_rows(p, rid, [
        {"source_id": "k1", "answer": "a1"},
        {"source_id": "k2", "answer": "a2"},
        {"source_id": "k3", "answer": "a3"}])
    return rid


def _mapping():
    return {"id": "A", "status": "M", "comment": "N", "severity": "O"}


def test_parse_status_and_severity():
    assert mio.parse_status("1") == "good"
    assert mio.parse_status("0") == "bad"
    assert mio.parse_status("Хорошо") == "good"
    assert mio.parse_status("плохо") == "bad"
    assert mio.parse_status("  ") is None
    assert mio.parse_status(None) is None
    try:
        mio.parse_status("???")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
    assert mio.parse_severity("высокая") == "высокая"
    assert mio.parse_severity("ОК") is None
    assert mio.parse_severity("") is None
    assert mio.parse_severity("странная") == "странная"
    assert mio.build_comment("текст", "высокая") == \
        "Критичность: высокая\nтекст"
    assert mio.build_comment("", None) == ""
    assert mio.build_comment("t", None) == "t"
    assert mio.split_comment("Критичность: высокая\nтекст") == \
        ("высокая", "текст")
    assert mio.split_comment("просто текст") == (None, "просто текст")
    assert mio.split_comment("") == (None, "")


def test_read_and_guess_user_headers():
    import openpyxl
    p = tempfile.mkdtemp()
    out = p + "/marks.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ИД письма/запроса", "Совпадает ли тип ответа прошлому прогону",
               "Комментарий к прошлому прогону", "Критичность ошибки"])
    ws.append(["k1", 1, "всё ок", "высокая"])
    ws.append(["k2", 0, "не то", "низкая"])
    wb.save(out)
    headers, rows, errors = mio.read_marks_table(out)
    assert errors == []
    assert len(rows) == 2
    g = mio.guess_mapping(headers)
    assert g["id"] == "ИД письма/запроса", g
    assert g["status"] == "Совпадает ли тип ответа прошлому прогону", g
    assert g["comment"] == "Комментарий к прошлому прогону", g
    assert g["severity"] == "Критичность ошибки", g


def test_preview_buckets_and_apply():
    p = _proj()
    rid = _run(p)
    rows = [
        {"A": "k1", "M": "1", "N": "всё ок", "O": "высокая"},
        {"A": "k2", "M": "0", "N": "не то", "O": "низкая"},
        {"A": "k9", "M": "1", "N": "x", "O": ""},
        {"A": "k3", "M": "???", "N": "", "O": ""},
    ]
    rep = mio.preview_marks(p, rid, rows, _mapping())
    assert rep["total"] == 4
    assert {e["id"] for e in rep["new"]} == {"k1", "k2"}
    assert [e["id"] for e in rep["not_found"]] == ["k9"]
    assert len(rep["errors"]) == 1
    done = mio.apply_marks(p, rid, rep, "merge")
    assert done == {"applied": 2, "skipped": 0, "not_found": 1, "errors": 1}
    import regression_service as rg
    revs = {r["stable_key"]: r for r in rg.list_output_reviews(p, rid)}
    r1 = [v for v in revs.values() if v["source_id"] == "k1"][0]
    assert r1["review_status"] == "good"
    assert r1["review_comment"] == "Критичность: высокая\nвсё ок"
    # повтор — всё без изменений
    rep2 = mio.preview_marks(p, rid, rows[:2], _mapping())
    assert len(rep2["unchanged"]) == 2
    # конфликт: merge не трогает, update перезаписывает
    rows3 = [{"A": "k1", "M": "0", "N": "передумал", "O": ""}]
    rep3 = mio.preview_marks(p, rid, rows3, _mapping())
    assert len(rep3["conflicts"]) == 1
    d_merge = mio.apply_marks(p, rid, rep3, "merge")
    assert d_merge["applied"] == 0
    d_upd = mio.apply_marks(p, rid, rep3, "update")
    assert d_upd["applied"] == 1
    revs = {r["stable_key"]: r for r in rg.list_output_reviews(p, rid)}
    r1 = [v for v in revs.values() if v["source_id"] == "k1"][0]
    assert r1["review_status"] == "bad"
    assert r1["review_comment"] == "передумал"


def test_comment_only_becomes_uncertain():
    p = _proj()
    rid = _run(p)
    rows = [{"A": "k1", "M": "", "N": "замечание без вердикта", "O": ""}]
    rep = mio.preview_marks(p, rid, rows, _mapping())
    assert len(rep["new"]) == 1
    done = mio.apply_marks(p, rid, rep, "merge")
    assert done["applied"] == 1
    import regression_service as rg
    revs = list(rg.list_output_reviews(p, rid))
    r1 = [v for v in revs if v["source_id"] == "k1"][0]
    assert r1["review_status"] == "uncertain"
    assert r1["review_comment"] == "замечание без вердикта"


def test_mapping_persist():
    p = _proj()
    assert mio.load_mapping(p) == {}
    full = dict(_mapping(), sheet="S1", status_values={"1": "good"},
                severity_values={"высокая": "высокая"})
    mio.save_mapping(p, full)
    assert mio.load_mapping(p) == full


def test_custom_value_mapping():
    """Свои значения датасета: маппинг решает, а не словарь."""
    p = _proj()
    rid = _run(p)
    mapping = dict(_mapping(),
                   status_values={"зачёт": "good", "незачёт": "bad",
                                  "1": ""},
                   severity_values={"критично": "высокая",
                                    "пустяк": "none"})
    rows = [
        {"A": "k1", "M": "зачёт", "N": "c1", "O": "критично"},
        {"A": "k2", "M": "незачёт", "N": "c2", "O": "пустяк"},
        {"A": "k3", "M": "1", "N": "только коммент", "O": ""},
    ]
    rep = mio.preview_marks(p, rid, rows, mapping)
    assert len(rep["new"]) == 3, rep
    done = mio.apply_marks(p, rid, rep, "merge")
    assert done["applied"] == 3
    import regression_service as rg
    revs = {v["source_id"]: v for v in rg.list_output_reviews(p, rid)}
    assert revs["k1"]["review_status"] == "good"
    assert revs["k1"]["review_comment"] == "Критичность: высокая\nc1"
    assert revs["k2"]["review_status"] == "bad"
    assert revs["k2"]["review_comment"] == "c2"
    # «1» проигнорирован -> комментарий без статуса -> Сомневаюсь
    assert revs["k3"]["review_status"] == "uncertain"
    # неизвестное без маппинга — ошибка, а не тишина
    rep2 = mio.preview_marks(
        p, rid, [{"A": "k1", "M": "???", "N": "", "O": ""}], _mapping())
    assert len(rep2["errors"]) == 1


def test_rematch_links_answers_imported_before_questions():
    """Ловушка новичка: ответы раньше вопросов — привязка встаёт сама."""
    import model_run_service as m
    import regression_service as rg
    from database import init_database
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    rid = m.create_run(p, "old", "mx")
    m.import_run_rows(p, rid, [
        {"source_id": "k1", "answer": "a1"},
        {"source_id": "k2", "answer": "a2"}])
    assert all(a["case_id"] is None for a in m.list_answers(p, rid))
    # разметили висячий ответ до привязки — разметка не должна потеряться
    rg.set_output_review(p, rid, "src:k1", "bad", "плохо")
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    ans = {a["stable_key"]: a for a in m.list_answers(p, rid)}
    assert ans["src:k1"]["case_id"] is not None
    assert ans["src:k2"]["case_id"] is not None
    revs = {r["stable_key"]: r for r in rg.list_output_reviews(p, rid)}
    r1 = [v for v in revs.values() if v["source_id"] == "k1"][0]
    assert r1["review_status"] == "bad" and r1["review_comment"] == "плохо"


def test_rematch_normalizes_phash_key_and_moves_marks():
    import model_run_service as m
    import regression_service as rg
    from database import init_database
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    rid = m.create_run(p, "old", "mx")
    m.import_run_rows(p, rid, [{"answer": "a1", "prompt": "уникальный вопрос"}])
    only = m.list_answers(p, rid)[0]
    assert only["stable_key"].startswith("phash:")
    assert only["case_id"] is None
    rg.set_output_review(p, rid, only["stable_key"], "good", "ок")
    other = m.create_run(p, "new", "mx")
    m.set_preference(p, rid, other, only["stable_key"], "tie", 1, 1, "равны")
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "уникальный вопрос", "i": "k9"}])
    m.import_run_rows(p, other, [{"source_id": "k9", "answer": "a9"}])
    ans = m.list_answers(p, rid)
    assert len(ans) == 1 and ans[0]["case_id"] is not None
    assert ans[0]["stable_key"] == "src:k9"
    revs = list(rg.list_output_reviews(p, rid))
    assert len(revs) == 1 and revs[0]["review_status"] == "good"
    prefs = m.compare_runs(p, rid, other)
    assert prefs["counts"]["both"] == 1


def test_big_file_counts_and_applies():
    """1000 строк: счётчики по всем, применение bulk-циклом."""
    import model_run_service as m
    p = tempfile.mkdtemp()
    from database import init_database
    from importer import import_file
    init_database(p)
    cases = [{"q": f"q{i}", "i": f"k{i}"} for i in range(300)]
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"}, cases)
    rid = m.create_run(p, "big", "mx")
    m.import_run_rows(
        p, rid, [{"source_id": f"k{i}", "answer": f"a{i}"} for i in range(300)])
    rows = [{"A": f"k{i}", "M": "1" if i % 2 else "0",
             "N": f"c{i}", "O": ""} for i in range(300)]
    rep = mio.preview_marks(p, rid, rows, _mapping())
    assert rep["total"] == 300
    assert len(rep["new"]) == 300
    done = mio.apply_marks(p, rid, rep, "merge")
    assert done["applied"] == 300
    import regression_service as rg
    assert rg.output_review_stats(p, rid)["reviewed"] == 300


def test_run_detail_shows_marked():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from runs_screen import ModelRunsScreen
    p = _proj()
    rid = _run(p)
    rows = [{"A": "k1", "M": "1", "N": "", "O": ""}]
    rep = mio.preview_marks(p, rid, rows, _mapping())
    mio.apply_marks(p, rid, rep, "merge")
    w = ModelRunsScreen(p, None)
    try:
        w.show()
        w._run_id = rid
        w._on_run_selected()
        assert "размечено" in w.detail.text(), w.detail.text()
    finally:
        w.close()


def test_multi_sheet_pick():
    """Многостраничный файл: читаем указанный лист, а не только первый."""
    import openpyxl
    p = tempfile.mkdtemp()
    out = p + "/multi.xlsx"
    wb = openpyxl.Workbook()
    ws1 = wb.active
    ws1.title = "Мусор"
    ws1.append(["A", "B"])
    ws1.append(["x", "y"])
    ws2 = wb.create_sheet("Оценки")
    ws2.append(["ИД", "Статус"])
    ws2.append(["k1", 1])
    wb.save(out)
    assert mio.list_sheets(out) == ["Мусор", "Оценки"]
    h1, r1, _ = mio.read_marks_table(out)
    assert h1 == ["A", "B"] and len(r1) == 1
    h2, r2, _ = mio.read_marks_table(out, "Оценки")
    assert h2 == ["ИД", "Статус"] and r2[0]["ИД"] == "k1"


def test_import_dialog_builds():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from run_marks_import_dialog import ImportRunMarksDialog
    p = _proj()
    rid = _run(p)
    dlg = ImportRunMarksDialog(p, rid, "old", None)
    try:
        dlg.show()
        assert set(dlg.map_combos) == {"id", "status", "comment",
                                       "severity"}
        assert dlg.mode_combo.currentData() == "merge"
        assert not dlg.btn_review.isEnabled()
        # таблицы значений строятся из строк и помнят правки
        dlg._headers = ["A", "M", "N"]
        dlg._rows = [{"A": "k1", "M": "1", "N": "c"},
                     {"A": "k2", "M": "0", "N": ""}]
        for cb, val in (("id", "A"), ("status", "M"), ("comment", "N")):
            box = dlg.map_combos[cb]
            box.addItem(val, val)
            box.setCurrentIndex(box.count() - 1)
        dlg._saved_vals = {}
        dlg._rebuild_value_tables()
        assert dlg.status_vals.rowCount() == 2
        harvested = dlg._mapping()["status_values"]
        assert harvested == {"1": "good", "0": "bad"}, harvested
    finally:
        dlg.close()


def test_verdict_header_and_combo_apply():
    """Шапка оценки в разметке + оценки заодно с импортом ответов."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from run_review_dialog import RunReviewDialog
    from runs_screen import apply_marks_after_import
    p = _proj()
    rid = _run(p)
    raw = [{"A": "k1", "M": "1", "N": "c1", "O": "ОК"},
           {"A": "k2", "M": "0", "N": "c2", "O": "высокая"}]
    msg = apply_marks_after_import(
        p, rid, raw, "A",
        {"mark_status": "M", "mark_comment": "N", "mark_severity": "O"})
    assert "применено 2" in msg, msg
    dlg = RunReviewDialog(p, rid, None)
    try:
        dlg.show()
        texts = [dlg.verdict_label.text()]
        dlg.keys_list.setCurrentRow(0)
        texts.append(dlg.verdict_label.text())
        dlg.keys_list.setCurrentRow(1)
        texts.append(dlg.verdict_label.text())
        assert any("Хорошо" in t for t in texts), texts
        bad = [t for t in texts if "Плохо" in t]
        assert bad and "высокая" in bad[0], texts
    finally:
        dlg.close()


def test_runimport_mapping_persist_and_restore():
    """Маппинг импорта ответов помнится: повторный файл — в пару кликов."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import openpyxl
    from runs_screen import (RunImportDialog, load_runimport_mapping,
                             save_runimport_mapping)
    p = _proj()
    assert load_runimport_mapping(p) == {}
    save_runimport_mapping(p, {"ИД": "source_id", "Ответ": "answer"})
    assert load_runimport_mapping(p) == {"ИД": "source_id",
                                         "Ответ": "answer"}
    xlsx = tempfile.mkdtemp() + "/r.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ИД", "Ответ"])
    ws.append(["k1", "a1"])
    wb.save(xlsx)
    from file_reader import FileReader
    dlg = RunImportDialog(p, None)
    try:
        dlg.show()
        dlg.file_path = xlsx
        dlg.file_type = FileReader().detect_file_type(xlsx)
        _sheets = FileReader().read_excel_sheets(xlsx)
        dlg.sheet_combo.clear()
        dlg.sheet_combo.addItems(_sheets)
        dlg.sheet_name = _sheets[0]
        dlg._reload_preview()
        got = {h: c.currentData() for h, c in dlg.combos.items()}
        assert got.get("ИД") == "source_id", got
        assert got.get("Ответ") == "answer", got
    finally:
        dlg.close()


def test_import_dialog_autoloads_run_file():
    """Диалог оценок подхватывает файл ответов прогона сам."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    import openpyxl
    from run_marks_import_dialog import ImportRunMarksDialog
    p = _proj()
    rid = _run(p)
    xlsx = tempfile.mkdtemp() + "/ans.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ИД письма/запроса", "Совпадает ли тип", "Комментарий"])
    ws.append(["k1", 1, "c1"])
    wb.save(xlsx)
    dlg = ImportRunMarksDialog(p, rid, "old", None, initial_file=xlsx)
    try:
        dlg.show()
        assert len(dlg._rows) == 1
        assert "ИД письма/запроса" in [
            dlg.map_combos["id"].itemText(i)
            for i in range(dlg.map_combos["id"].count())]
        assert dlg.status_vals.rowCount() == 1
    finally:
        dlg.close()
