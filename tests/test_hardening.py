"""V2.2 §9–§10, §13, §6: integrity, safe repair, Ctrl+P поиск, anon-экспорт."""
import tempfile

import global_search_service as gs
import integrity_check_service as integ


def _proj(rows):
    from database import init_database
    from importer import import_file
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text", "i": "source_id"},
                rows)
    return p


def test_integrity_healthy_and_orphan_flow():
    from database import db
    p = _proj([{"q": "q1", "i": "A1"}, {"q": "q2", "i": "A2"}])
    rep = integ.check_project(p)
    assert rep["ok"] is True, rep["issues"]
    # ломаем: кейс-сирота мимо каскада
    with db(p) as conn:
        conn.execute("PRAGMA foreign_keys=OFF")
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
        conn.execute("INSERT INTO cases (file_id, row_index, source_id, primary_text, created_at)"
                     " VALUES (?, 999, 'ORPH', 'orphan', datetime('now'))", (fid,))
        orphan_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute("DELETE FROM files WHERE file_id=?", (fid,))
        conn.execute("PRAGMA foreign_keys=ON")
    rep2 = integ.check_project(p)
    assert rep2["ok"] is False
    assert any(i["scope"] == "cases" and i["fixable"] for i in rep2["issues"])
    done = integ.repair_safe(p)
    assert done.get("orphan_cases", 0) >= 1
    rep3 = integ.check_project(p)
    assert all(i["scope"] != "cases" for i in rep3["issues"]), rep3["issues"]
    _ = orphan_id


def test_integrity_bad_highlight_range():
    from database import db
    p = _proj([{"q": "q1", "i": "H1"}])
    with db(p) as conn:
        cid = conn.execute("SELECT case_id FROM cases").fetchone()["case_id"]
        conn.execute("INSERT INTO case_highlights "
                     "(case_id, start_offset, end_offset, color, text_hash, created_at)"
                     " VALUES (?, 10, 5, 'green', 'x', datetime('now'))", (cid,))
    rep = integ.check_project(p)
    assert any(i["scope"] == "highlights" for i in rep["issues"])


def test_global_search_exact_partial_text():
    p = _proj([{"q": "Возврат денег за билет", "i": "TICKET-101"},
               {"q": "Смена тарифа", "i": "TARIFF-202"},
               {"q": "возврат средств", "i": "OTHER-303"}])
    from database import db
    with db(p) as conn:
        cid = conn.execute(
            "SELECT case_id FROM cases WHERE source_id='TICKET-101'").fetchone()["case_id"]
    # точный source_id
    r = gs.search_cases(p, "TICKET-101")
    assert len(r) == 1 and r[0]["source_id"] == "TICKET-101"
    # частичный
    r = gs.search_cases(p, "TICKET")
    assert any(x["source_id"] == "TICKET-101" for x in r)
    # case_id числом
    r = gs.search_cases(p, str(cid))
    assert r and r[0]["case_id"] == cid
    # текст (кириллица, регистр не важен)
    r = gs.search_cases(p, "ВОЗВРАТ")
    assert len(r) >= 2
    assert gs.search_cases(p, "") == []
    assert gs.search_cases(p, "такого-нет-вообще-xyz") == []


def test_ctrl_p_fires_with_focus_in_comment():
    """Регрессия: Ctrl+P был обёрнут в guarded и молча гас при фокусе
    в комментарии (а фокус почти всегда там). Теперь — прямой шорткат."""
    import tempfile as _t
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from database import init_database as _init
    from importer import import_file as _imp
    from review_screen import ReviewScreen
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0,
         {"q": "primary_text", "i": "source_id"},
         [{"q": "q1", "i": "A1"}])
    w = ReviewScreen(p)
    try:
        w.show()
        w.load_case(0)
        # фокус — в поле комментария, как в живом ревью
        try:
            w.comment_edit.setFocus()
            assert w._shortcuts_allowed() is False
        except Exception:
            pass
        sc = next(s for s in w._shortcuts
                  if s.key().toString() == "Ctrl+P")
        calls = []
        w.open_global_search = lambda: calls.append(1)
        sc.activated.emit()
        assert calls == [1]
    finally:
        w.close()


def test_clip_pill_shows_and_hides():
    """Пилюля в шапке ревью: видна пока тикает, прячется после."""
    import tempfile as _t
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from database import init_database as _init
    from importer import import_file as _imp
    from review_screen import ReviewScreen
    import clipboard_service as _clip
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
         [{"q": "q1"}])
    _clip.reset_pending()
    w = ReviewScreen(p)
    try:
        w.show()
        w.load_case(0)
        w._tick_clip_pill()
        assert not w.clip_pill.isVisible()
        _clip.safe_copy("контекст кейса")
        w._tick_clip_pill()
        assert w.clip_pill.isVisible()
        assert "сек" in w.clip_pill.text()
        _clip.reset_pending()
        w._tick_clip_pill()
        assert not w.clip_pill.isVisible()
    finally:
        w.close()
        _clip.reset_pending()


def test_global_keys_filter_ctrl_p():
    """App-фильтр Ctrl+P: в ревью открывает поиск (даже из поля ввода),
    при модалке и вне ревью — молчит. Обход мёртвого QShortcutMap."""
    import tempfile as _t
    from PySide6.QtWidgets import QApplication, QWidget, QDialog
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent
    QApplication.instance() or QApplication([])
    from database import init_database as _init
    from importer import import_file as _imp
    from review_screen import ReviewScreen
    from app_shortcuts import ReviewKeysFilter
    p = _t.mkdtemp()
    _init(p)
    _imp(p, "f.xlsx", "excel", "S", 0, {"q": "primary_text"},
         [{"q": "q1"}])
    w = ReviewScreen(p)
    other = QWidget()
    filt = ReviewKeysFilter()
    try:
        w.show()
        w.load_case(0)
        w.comment_edit.setFocus()
        QApplication.instance().processEvents()
        calls = []
        w.open_global_search = lambda: calls.append(1)

        def _press(key, mods):
            w.comment_edit.setFocus()
            QApplication.instance().processEvents()
            return filt.eventFilter(
                w, QKeyEvent(QEvent.Type.KeyPress, key, mods))

        from PySide6.QtCore import Qt
        # Ctrl+P в поле комментария — открыть и съесть событие
        assert _press(Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier) is True
        assert calls == [1]
        # просто P — не наше
        assert _press(Qt.Key.Key_P, Qt.KeyboardModifier.NoModifier) is False
        assert calls == [1]
        # Ctrl+T — не наше
        assert _press(Qt.Key.Key_T, Qt.KeyboardModifier.ControlModifier) is False
        assert calls == [1]
        # модалка открыта — молчим
        dlg = QDialog(w)
        dlg.setModal(True)
        dlg.show()
        QApplication.instance().processEvents()
        assert _press(Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier) is False
        assert calls == [1]
        dlg.close()
        # фокус вне ревью — молчим
        other.setFocus()
        QApplication.instance().processEvents()
        if QApplication.focusWidget() is other:
            assert _press(Qt.Key.Key_P, Qt.KeyboardModifier.ControlModifier) is False
            assert calls == [1]
    finally:
        other.close()
        w.close()


def test_anonymized_exports_keep_source():
    from database import db
    from export_service import export_results_jsonl, export_results_to_xlsx
    import json as _j
    p = _proj([{"q": "позвони +7 900 111-22-33", "i": "P1"}])
    out = p + "/a.jsonl"
    n = export_results_jsonl(p, out, anonymize=True)
    assert n == 1
    obj = _j.loads(open(out, encoding="utf-8").read().splitlines()[0])
    assert "<PHONE_" in obj["query"] and "+7 900" not in obj["query"]
    # исходник цел
    with db(p) as conn:
        txt = conn.execute("SELECT primary_text FROM cases").fetchone()[0]
        assert "+7 900 111-22-33" in txt
    out2 = p + "/b.xlsx"
    assert export_results_to_xlsx(p, out2, anonymize=True) == 1
    import openpyxl
    wb = openpyxl.load_workbook(out2, read_only=True, data_only=True)
    ws = wb.active
    blob = " ".join(str(c.value or "") for row in ws.iter_rows(min_row=2) for c in row)
    assert "<PHONE_" in blob and "+7 900" not in blob
