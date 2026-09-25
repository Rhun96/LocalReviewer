"""Сводка/Качество: карточки, drill-down проводка, период."""
import tempfile

import analytics_service as an
from database import init_database, db
from importer import import_file
from bulk_operation_service import bulk_set_status


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"},
                 {"q": "q3", "i": "k3"}])
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    bulk_set_status(p, ids[:1], "good")
    bulk_set_status(p, ids[1:2], "bad")
    return p, ids


class _MW:
    def __init__(self):
        self.calls = []

    def show_screen(self, key, filters=None):
        self.calls.append((key, dict(filters or {})))


class _PW:
    def __init__(self, mw):
        self.main_window = mw


def test_summary_cards_and_drill():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from filter_service import count_filtered_cases
    p, ids = _proj()
    mw = _MW()
    w = ReportsScreen(p, None)
    try:
        w.parent_window = _PW(mw)
        w.show()
        w.tabs.setCurrentWidget(w.summary_tab)
        w.load_summary_report()
        assert "2" in w.summary_cards["reviewed"].text()
        assert w.summary_empty.text() == ""
        # клик по Bad ведет в ревью с тем же предикатом (ключевой тест UI)
        w.summary_cards["bad"].click()
        assert len(mw.calls) == 1
        key, flt = mw.calls[0]
        assert key == "review"
        assert count_filtered_cases(p, flt) == 1
        # динамика и топ построились
        assert w.summary_dyn.rowCount() >= 1
    finally:
        w.close()


def test_summary_empty_state_and_period():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    p, ids = _proj()
    w = ReportsScreen(p, None)
    try:
        w.show()
        w.tabs.setCurrentWidget(w.summary_tab)
        for i in range(w.period_combo.count()):
            if w.period_combo.itemData(i) == "today":
                w.period_combo.setCurrentIndex(i)
                break
        w.load_summary_report()
        assert "2" in w.summary_cards["reviewed"].text()
        # период в будущем — честное «Нет данных»
        sc = w._analytics_scope()
        assert sc["reviewed_from"] <= sc["reviewed_to"]
        res = an.card_counts(p, {"reviewed_from": "2030-01-01"})
        assert res["cards"]["reviewed"]["value"] == 0
    finally:
        w.close()


def test_quality_tab_tables_and_drill():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    p, ids = _proj()
    mw = _MW()
    w = ReportsScreen(p, None)
    try:
        w.parent_window = _PW(mw)
        w.show()
        w.tabs.setCurrentWidget(w.quality_tab)
        w.load_quality_report()
        assert w.quality_verdicts.rowCount() == 6
        goods = [w.quality_verdicts.item(r, 1).text()
                 for r in range(w.quality_verdicts.rowCount())]
        assert "1" in goods
        # тяжести нет — блок пуст, а не нули (правило универсальности)
        assert w.quality_sev.rowCount() == 0
        # клик по строке вердикта ведет в ревью
        w._drill_verdict(w.quality_verdicts.item(0, 0))
        assert mw.calls and mw.calls[0][0] == "review"
    finally:
        w.close()


def test_drill_lands_in_table_with_exact_rows():
    """Drill-down целиком: таблица показывает ровно строки метрики."""
    import tempfile
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QSettings as _QS
    QApplication.instance() or QApplication([])
    from database import init_database
    from importer import import_file
    from bulk_operation_service import bulk_set_status
    from database import db as _db
    # QSettings общий с рабочей машиной: открытием проекта тесты обязаны
    # не пачкать recent/last (проверено болью — чистим за собой).
    _qs = _QS("LocalReviewer", "LocalReviewer")
    _saved = {k: _qs.value(k, None) for k in
              ("session/recent", "session/last_project")}
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"},
                 {"q": "q3", "i": "k3"}])
    with _db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    bulk_set_status(p, ids[:1], "good")
    bulk_set_status(p, ids[1:2], "bad")
    from main import MainWindow
    mw = MainWindow()
    try:
        mw.open_project(p)
        QApplication.instance().processEvents()
        rev = mw.project_window.screens["review"]
        rep = mw.project_window.screens["reports"]
        # пользователь до этого смотрел таблицу без фильтров
        rev.view_stack.setCurrentIndex(1)
        rev.load_table_data()
        assert rev.cases_table.rowCount() == 3
        rep.tabs.setCurrentWidget(rep.summary_tab)
        rep.load_summary_report()
        rep._drill_card("bad")
        QApplication.instance().processEvents()
        assert rev.view_stack.currentIndex() == 1
        assert rev.cases_table.rowCount() == 1, rev.cases_table.rowCount()
        cols = list(rev.selected_columns)
        sidx = cols.index("Статус") + 1
        assert "Плохо" in rev.cases_table.item(0, sidx).text()
    finally:
        mw.close()
        try:
            for k, v in _saved.items():
                if v is None:
                    _qs.remove(k)
                else:
                    _qs.setValue(k, v)
            _qs.sync()
        except Exception:
            pass


def test_filter_dialog_period_roundtrip():
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from filter_dialog import FilterDialog
    p, ids = _proj()
    dlg = FilterDialog(p, None)
    try:
        dlg.show()
        for i in range(dlg.period_preset.count()):
            if dlg.period_preset.itemData(i) == "7d":
                dlg.period_preset.setCurrentIndex(i)
                break
        dlg.on_apply()
        flt = dlg.get_filters()
        assert flt["reviewed_from"] and flt["reviewed_to"]
        assert flt["reviewed_from"] <= flt["reviewed_to"]
        from filter_service import count_filtered_cases
        import analytics_service as _an
        # период без статусов = всё тронутое (включая пустую разметку импорта)
        assert count_filtered_cases(p, flt) == 3
        flt["statuses"] = _an.reviewed_codes(p)
        assert count_filtered_cases(p, flt) == 2
        dlg2 = FilterDialog(p, None)
        try:
            dlg2.show()
            dlg2.set_filters(flt)
            back = dlg2._collect_ui_filters()
            assert back["reviewed_from"] == flt["reviewed_from"]
            assert back["reviewed_to"] == flt["reviewed_to"]
        finally:
            dlg2.close()
    finally:
        dlg.close()
