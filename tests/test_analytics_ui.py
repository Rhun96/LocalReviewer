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


def test_personal_review_time_block():
    """Личное: среднее/медиана из замеров; пусто — честное «нет»."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from database import db as _db
    p, ids = _proj()

    def _rows(w):
        return {(w.personal_table.item(r, 0).text(),
                 w.personal_table.item(r, 1).text())
                for r in range(w.personal_table.rowCount())}

    w = ReportsScreen(p, None)
    try:
        w.show()
        w.tabs.setCurrentWidget(w.personal_tab)
        w.load_personal_report()
        assert ("Замеры", "нет (копятся с этого обновления)") in _rows(w)
    finally:
        w.close()
    with _db(p) as conn:
        conn.execute("UPDATE annotations SET review_duration_s=60.0 "
                     "WHERE case_id=?", (ids[0],))
        conn.execute("UPDATE annotations SET review_duration_s=120.0 "
                     "WHERE case_id=?", (ids[1],))
    w = ReportsScreen(p, None)
    try:
        w.show()
        w.tabs.setCurrentWidget(w.personal_tab)
        w.load_personal_report()
        rows = _rows(w)
        assert ("Среднее на кейс", "1 мин 30 с") in rows
        assert ("Медиана", "1 мин 30 с") in rows
        assert ("Замеров", "2") in rows
    finally:
        w.close()


def test_quality_dynamics_block():
    """Качество: таблица динамики причин (прошлая/эта/Δ)."""
    from datetime import datetime, timedelta, UTC
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from bulk_operation_service import bulk_set_status
    from database import db as _db
    from filter_service import get_filtered_case_ids
    from taxonomy_service import set_case_error
    p, ids = _proj()
    all_ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, all_ids, "bad")
    with _db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness'").fetchone()
        sub = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness.hallucination'").fetchone()
    for cid in all_ids:
        set_case_error(p, cid, cat["category_id"], sub["category_id"], "high")
    today = datetime.now(UTC).date()
    monday = today - timedelta(days=today.weekday())
    dprev = (monday - timedelta(days=14)).isoformat() + " 10:00:00"
    dlast = (monday - timedelta(days=7)).isoformat() + " 10:00:00"
    with _db(p) as conn:
        conn.execute("UPDATE case_errors SET updated_at=? WHERE case_id=?",
                     (dprev, all_ids[0]))
        conn.execute("UPDATE case_errors SET updated_at=? WHERE case_id<>?",
                     (dlast, all_ids[0]))
    w = ReportsScreen(p, None)
    try:
        w.show()
        w.tabs.setCurrentWidget(w.quality_tab)
        w.load_quality_report()
        assert w.quality_dyn.rowCount() == 1
        assert w.quality_dyn.item(0, 0).text() == "Правильность"
        assert w.quality_dyn.item(0, 1).text() == "1"
        assert w.quality_dyn.item(0, 2).text() == "2"
        assert w.quality_dyn.item(0, 3).text() == "+1"
        assert "→" in w.quality_dyn_label.text()
        # тяжесть: 4-я колонка показывает какие категории внутри
        assert w.quality_sev.columnCount() == 4
        assert w.quality_sev.rowCount() == 1
        assert w.quality_sev.item(0, 0).text() == "Высокая"
        assert "Правильность" in w.quality_sev.item(0, 3).text()
        # категории: 4-я колонка — подкатегории; сводка — тоже с ними
        assert w.quality_cats.columnCount() == 4
        assert "Галлюцинация" in w.quality_cats.item(0, 3).text()
        w.tabs.setCurrentWidget(w.summary_tab)
        w.load_summary_report()
        _top_texts = [w.summary_top.item(r).text()
                      for r in range(w.summary_top.count())]
        assert any("Галлюцинация" in t for t in _top_texts)
        # таблицы влезают целиком (внутреннего скролла нет)
        for t in (w.quality_verdicts, w.quality_sev,
                  w.quality_cats, w.quality_dyn):
            assert t.verticalScrollBar().maximum() == 0
    finally:
        w.close()


def test_summary_top_drill_reaches_review():
    """Основные проблемы: клик ведёт в ревью с фильтром причины."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from bulk_operation_service import bulk_set_status
    from database import db as _db
    from filter_service import get_filtered_case_ids
    from taxonomy_service import set_case_error
    p, ids = _proj()
    all_ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, all_ids, "bad")
    with _db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness'").fetchone()
        sub = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness.hallucination'").fetchone()
    for cid in all_ids:
        set_case_error(p, cid, cat["category_id"], sub["category_id"], "high")
    mw = _MW()
    w = ReportsScreen(p, None)
    try:
        w.parent_window = _PW(mw)
        w.show()
        w.tabs.setCurrentWidget(w.summary_tab)
        w.load_summary_report()
        assert w.summary_top.count() >= 1
        w._drill_top(w.summary_top.item(0))
        assert mw.calls and mw.calls[0][0] == "review"
        assert mw.calls[0][1].get("error_category_id") == cat["category_id"]
    finally:
        w.close()


def test_summary_top_sub_rows_drill():
    """Подкатегории — отдельные кликабельные строки цепочки."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from bulk_operation_service import bulk_set_status
    from database import db as _db
    from filter_service import get_filtered_case_ids
    from taxonomy_service import set_case_error
    p, ids = _proj()
    all_ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, all_ids, "bad")
    with _db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness'").fetchone()
        sub = conn.execute("SELECT category_id FROM error_categories "
                           "WHERE code='correctness.hallucination'").fetchone()
    for cid in all_ids:
        set_case_error(p, cid, cat["category_id"], sub["category_id"], "high")
    mw = _MW()
    w = ReportsScreen(p, None)
    try:
        w.parent_window = _PW(mw)
        w.show()
        w.tabs.setCurrentWidget(w.summary_tab)
        w.load_summary_report()
        texts = [w.summary_top.item(i).text()
                 for i in range(w.summary_top.count())]
        sub_rows = [t for t in texts if t.startswith("↳")]
        assert len(sub_rows) == 1 and "Галлюцинация" in sub_rows[0]
        idx = texts.index(sub_rows[0])
        w._drill_top(w.summary_top.item(idx))
        assert mw.calls and mw.calls[0][0] == "review"
        assert mw.calls[0][1].get("error_category_id") == sub["category_id"]
    finally:
        w.close()


def test_quality_tables_stretch_first_column():
    """Текст влезает: первая колонка тянется, проценты компактны."""
    from PySide6.QtWidgets import QApplication, QHeaderView
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    p, _ids = _proj()
    w = ReportsScreen(p, None)
    try:
        w.show()
        for t in (w.quality_verdicts, w.quality_sev,
                  w.quality_cats, w.quality_dyn):
            assert t.horizontalHeader().sectionResizeMode(0) == \
                QHeaderView.ResizeMode.Stretch
    finally:
        w.close()


def test_files_quality_tab_and_drill():
    """Файлы: полнота/грязь + клик ведёт в ревью файла."""
    from PySide6.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    from reports_screen import ReportsScreen
    from database import db as _db
    p, ids = _proj()
    with _db(p) as conn:
        fid = conn.execute("SELECT file_id FROM files").fetchone()["file_id"]
    mw = _MW()
    w = ReportsScreen(p, None)
    try:
        w.parent_window = _PW(mw)
        w.show()
        w.tabs.setCurrentWidget(w.files_tab)
        w.load_files_report()
        assert w.files_table.columnCount() == 7
        assert w.files_table.rowCount() == 1
        assert w.files_table.item(0, 3).text() == "66.7"
        w._drill_file(w.files_table.item(0, 0))
        assert mw.calls and mw.calls[0][0] == "review"
        assert mw.calls[0][1] == {"file_id": fid}
    finally:
        w.close()


def test_single_click_no_drill_double_click_drills():
    """Одиночный клик выделяет, в ревью ведёт только двойной."""
    from PySide6.QtWidgets import QApplication
    from PySide6.QtTest import QTest
    from PySide6.QtCore import Qt
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
        assert w.badcomp_list.count() >= 1
        pos = w.badcomp_list.visualItemRect(
            w.badcomp_list.item(0)).center()
        QTest.mouseClick(w.badcomp_list.viewport(), Qt.LeftButton,
                         pos=pos)
        assert mw.calls == []
        QTest.mouseDClick(w.badcomp_list.viewport(), Qt.LeftButton,
                          pos=pos)
        assert len(mw.calls) == 1 and mw.calls[0][0] == "review"
    finally:
        w.close()
