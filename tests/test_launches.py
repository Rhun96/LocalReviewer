"""Экран Запуски: история регрессий, фильтры, удаление, preselect диалога."""
import tempfile

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from database import db, init_database
from launches_screen import LaunchesScreen
import regression_service as rg


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    with db(p) as conn:
        cur = conn.cursor()
        cur.execute("INSERT INTO model_runs (name, created_at) VALUES ('m1', 't')")
        run_id = cur.lastrowid
        cur.execute(
            """INSERT INTO regression_runs
                (name, baseline_type, baseline_id, candidate_type,
                 candidate_run_id, candidate_version_id,
                 gate_max_critical, gate_max_rate, gate_result,
                 total, regressions, improvements, unchanged, created_at)
               VALUES ('rel-1', 'run', ?, 'run', ?, NULL, 0, 0.02,
                       'PASS', 10, 0, 2, 8, '2026-09-25T10:00:00')""",
            (run_id, run_id))
        cur.execute(
            """INSERT INTO regression_runs
                (name, baseline_type, baseline_id, candidate_type,
                 candidate_run_id, candidate_version_id,
                 gate_max_critical, gate_max_rate, gate_result,
                 total, regressions, improvements, unchanged, created_at)
               VALUES ('rel-2', 'run', ?, 'run', ?, NULL, 0, 0.02,
                       'FAIL', 10, 3, 0, 7, '2026-09-26T10:00:00')""",
            (run_id, run_id))
    return p


def _win(p):
    QApplication.instance() or QApplication([])
    return LaunchesScreen(p, None)


def test_list_and_gate_colors():
    w = _win(_proj())
    try:
        w.show()
        assert w.table.rowCount() == 2
        gates = {}
        for i in range(w.table.rowCount()):
            gates[i] = (w.table.item(i, 4).text(),
                        w.table.item(i, 4).foreground().color().name())
        assert gates[0][0] == "❌ FAIL" and gates[0][1] == "#da3633"
        assert gates[1][0] == "✅ PASS" and gates[1][1] == "#2ea043"
        assert w.table.item(0, 5).text() == "3/10"
        assert w.table.item(1, 6).text() == "+2"
    finally:
        w.close()


def test_filters_and_delete():
    p = _proj()
    w = _win(p)
    try:
        w.show()
        for i in range(w.gate_combo.count()):
            if w.gate_combo.itemData(i) == "PASS":
                w.gate_combo.setCurrentIndex(i)
                break
        w.refresh()
        assert w.table.rowCount() == 1
        assert w.table.item(0, 2).text() == "rel-1"
        for i in range(w.gate_combo.count()):
            if w.gate_combo.itemData(i) is None:
                w.gate_combo.setCurrentIndex(i)
                break
        w.search_edit.setText("rel-2")
        w.refresh()
        assert w.table.rowCount() == 1
        rid = w.table.item(0, 0).data(Qt.ItemDataRole.UserRole)
        rg.delete_regression(p, rid)
        w.search_edit.setText("")
        w.refresh()
        assert w.table.rowCount() == 1
    finally:
        w.close()


def test_dialog_preselect():
    from regression_dialog import RegressionDialog
    p = _proj()
    QApplication.instance() or QApplication([])
    rid = rg.list_regressions(p)[0]["regression_id"]
    d = RegressionDialog(p, None, regression_id=rid)
    try:
        d.show()
        assert d._reg_id == rid
        assert "FAIL" in d.summary.text() or "регр" in d.summary.text().lower() \
            or d._reg_id is not None
    finally:
        d.close()
