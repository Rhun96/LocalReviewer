"""Баги: мультивыбор+балк, колонка дубликатов, диалог похожих."""
import tempfile

from PySide6.QtWidgets import QApplication

from database import init_database
import bug_report_service as bugs


def _proj(n=3):
    p = tempfile.mkdtemp()
    init_database(p)
    return p


def _app():
    return QApplication.instance() or QApplication([])


def _win(p):
    from bug_reports_screen import BugReportsScreen
    return BugReportsScreen(p, None)


def _select_rows(w, rows):
    from PySide6.QtCore import QItemSelectionModel as _SM
    w.table.blockSignals(True)
    try:
        sm = w.table.selectionModel()
        sm.clearSelection()
        for r in rows:
            sm.select(w.table.model().index(r, 0),
                      _SM.SelectionFlag.Select | _SM.SelectionFlag.Rows)
    finally:
        w.table.blockSignals(False)


def test_multiselect_bulk_status_and_dup_column():
    _app()
    p = _proj()
    a = bugs.create_bug(p, "корень")
    b = bugs.create_bug(p, "дубль")
    bugs.create_bug(p, "третий")
    w = _win(p)
    try:
        w.show()
        from PySide6.QtWidgets import QAbstractItemView
        assert w.table.selectionMode() == \
            QAbstractItemView.SelectionMode.ExtendedSelection
        assert w.table.columnCount() == 9
        _select_rows(w, [0, 1])
        assert w._selected_ids() == [a, b]
        w._bulk_apply(status="Confirmed")
        got = {r["bug_id"]: r for r in bugs.list_bugs(p)}
        assert got[a]["status"] == "Confirmed"
        assert got[b]["status"] == "Confirmed"
        bugs.mark_duplicate(p, b, a)
        w.refresh()
        dups = [w.table.item(r, 8).text()
                for r in range(w.table.rowCount())]
        assert f"→ #{a}" in dups
    finally:
        w.close()


def test_merge_flow_and_delete_guard(monkeypatch):
    _app()
    import bug_reports_screen as scr
    monkeypatch.setattr(scr, "confirm", lambda *_a, **_k: True)
    p = _proj()
    a = bugs.create_bug(p, "корень")
    b = bugs.create_bug(p, "дубль")
    w = _win(p)
    try:
        w.show()
        # сначала current (он же выделение строки 0), потом +строка 1
        # без открытия карточки (иначе гвард автосейва вмешается)
        from PySide6.QtCore import QItemSelectionModel as _SM2
        w.table.blockSignals(True)
        try:
            w.table.setCurrentCell(0, 0)
            w.table.selectionModel().select(
                w.table.model().index(1, 0),
                _SM2.SelectionFlag.Select | _SM2.SelectionFlag.Rows)
        finally:
            w.table.blockSignals(False)
        assert w._selected_ids() == [a, b]
        w._merge_flow()
        got = {r["bug_id"]: r for r in bugs.list_bugs(p)}
        assert got[b]["duplicate_of"] == a
        # цель с дубликатами не удаляется через балк
        _select_rows(w, [0, 1])
        w._delete_bugs()
        remaining = {r["bug_id"] for r in bugs.list_bugs(p)}
        assert a in remaining
    finally:
        w.close()


def test_similar_dialog_lists_and_merges(monkeypatch):
    _app()
    import bug_similar_dialog as dlg_mod
    monkeypatch.setattr(dlg_mod, "confirm", lambda *_a, **_k: True)
    p = _proj()
    bugs.create_bug(p, "Возврат денег не пришёл")
    bugs.create_bug(p, "Не пришёл возврат денег")
    bugs.create_bug(p, "Упал импорт таблицы")
    from bug_similar_dialog import BugSimilarDialog
    d = BugSimilarDialog(p, None)
    try:
        d.show()
        assert d.groups_list.count() == 1
        d.groups_list.setCurrentRow(0)
        d._merge_current()
        assert d.groups_list.count() == 1  # «похожих нет» — тоже 1 строка
        assert d.groups_list.item(0).text() == "Похожих открытых багов нет"
        from report_service import bug_semantic_groups
        assert bug_semantic_groups(p) == []
    finally:
        d.close()
