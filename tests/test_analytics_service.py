"""Аналитика: карточки, период, динамика, drill-down равенство, экспорт."""
import tempfile

import analytics_service as an
from database import init_database, db
from importer import import_file
from bulk_operation_service import bulk_set_status
from filter_service import get_filtered_case_ids, count_filtered_cases


def _proj():
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"},
                 {"q": "q3", "i": "k3"}, {"q": "q4", "i": "k4"}])
    with db(p) as conn:
        ids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases ORDER BY case_id").fetchall()]
    bulk_set_status(p, ids[:2], "good")
    bulk_set_status(p, ids[2:3], "bad")
    with db(p) as conn:
        conn.execute("UPDATE annotations SET updated_at='2020-01-01T00:00:00+00:00'"
                     " WHERE case_id=?", (ids[0],))
        conn.execute("INSERT INTO case_errors (case_id, severity, updated_at)"
                     " VALUES (?, 'high', ?)",
                     (ids[2], "2026-09-23T10:00:00+00:00"))
    return p, ids


def test_cards_and_key_drill_equality():
    """Ключевой тест ТЗ: число на карточке == кейсов после клика."""
    p, ids = _proj()
    res = an.card_counts(p, {})
    cards = res["cards"]
    assert cards["total"]["value"] == 4
    assert cards["reviewed"]["value"] == 3
    assert cards["good"]["value"] == 2
    assert cards["bad"]["value"] == 1
    assert cards["unreviewed"]["value"] == 1
    for key, card in cards.items():
        n = count_filtered_cases(p, card["filters"])
        assert n == card["value"], (key, n, card["value"])
        assert len(get_filtered_case_ids(p, card["filters"])) == card["value"]
    pct = an.percentages(res)
    assert pct["good"] == round(100 * 2 / 3, 1)
    assert pct["bad"] == round(100 * 1 / 3, 1)


def test_period_filters_and_empty_states():
    p, ids = _proj()
    res = an.card_counts(p, {"reviewed_from": "2026-01-01"})
    assert res["cards"]["reviewed"]["value"] == 2  # без позапрошлогоднего
    assert res["cards"]["good"]["value"] == 1
    res = an.card_counts(p, {"reviewed_from": "2030-01-01"})
    assert res["cards"]["reviewed"]["value"] == 0
    assert an.percentages(res) == {"good": None, "bad": None,
                                   "uncertain": None}
    assert an.dynamics(p, {"reviewed_from": "2030-01-01"}) == []
    # drill по периоду тоже сходится
    flt = res["cards"]["bad"]["filters"]
    assert flt["reviewed_from"] == "2030-01-01"
    assert count_filtered_cases(p, flt) == 0


def test_dynamics_groups_by_day():
    p, ids = _proj()
    dyn = an.dynamics(p, {})
    assert len(dyn) >= 2
    total = sum(d["reviewed"] for d in dyn)
    assert total == 3
    assert sum(d["bad"] for d in dyn) == 1
    assert sum(d["good"] for d in dyn) == 2
    days = [d["day"] for d in dyn]
    assert days == sorted(days, reverse=True)
    assert "2020-01-01" in days


def test_top_categories_and_severity():
    p, ids = _proj()
    top = an.top_categories(p, {})
    assert top == []  # категории не заданы — честно пусто, не нули
    sev = an.severity_dist(p, {})
    assert len(sev) == 1 and sev[0]["severity"] == "high"
    assert sev[0]["problems"] == 1
    assert count_filtered_cases(p, sev[0]["filters"]) == 1
    # период отсекает ошибку
    assert an.severity_dist(p, {"reviewed_from": "2030-01-01"}) == []


def test_verdict_dist_and_bugs():
    p, ids = _proj()
    dist = {d["base"]: d["value"] for d in an.verdict_dist(p, {})}
    assert dist == {"good": 2, "bad": 1, "uncertain": 0, "skip": 0,
                    "duplicate": 0, "unreviewed": 1}
    bugs = an.bugs_stats(p, {})
    assert bugs["present"] is True and bugs["created"] == 0
    import bug_report_service as bugs_svc
    bugs_svc.create_bug(p, "t", [ids[2]], severity="High")
    bugs = an.bugs_stats(p, {})
    assert (bugs["created"], bugs["open"], bugs["linked_cases"]) == (1, 1, 1)
    assert bugs["by_severity"] == [{"severity": "High", "n": 1}]


def test_export_csv_with_header():
    import csv as _csv
    p, ids = _proj()
    out = p + "/analytics.csv"
    got = an.export_csv(p, {"reviewed_from": "2026-01-01"}, out)
    import os as _os
    assert _os.path.normcase(got) == _os.path.normcase(out)
    with open(out, encoding="utf-8-sig") as fh:
        rows = list(_csv.reader(fh, delimiter=";"))
    assert rows[0][0].startswith("# LocalReviewer")
    assert "2026-01-01" in rows[1]
    flat = [c for r in rows for c in r]
    assert "bad" in flat and "день" in flat


def test_export_xlsx_sections():
    import tempfile
    from openpyxl import load_workbook
    p, ids = _proj()
    out = tempfile.mkdtemp() + "/analytics.xlsx"
    got = an.export_xlsx(p, {}, out)
    import os as _os
    assert _os.path.normcase(got) == _os.path.normcase(out)
    wb = load_workbook(out, read_only=True, data_only=True)
    assert wb.sheetnames == ["Сводка", "Динамика", "Проблемы", "Тяжесть"]
    ws = wb["Сводка"]
    assert ws.cell(row=1, column=1).value.startswith("LocalReviewer")
    assert ws.cell(row=2, column=1).value == "Период:"


def test_case_ids_drill_filter():
    p, ids = _proj()
    flt = {"case_ids": ids[:2]}
    assert count_filtered_cases(p, flt) == 2
    assert get_filtered_case_ids(p, flt) == ids[:2]
    big = {"case_ids": list(range(1, 1200))}
    assert count_filtered_cases(p, big) == 4  # чанки IN, лишних нет


def test_compare_periods_facts_only():
    """A vs B: факты и дельты, без выводов; пустой период — прочерки."""
    p, ids = _proj()
    res = an.compare_periods(p, {"reviewed_from": "2020-01-01",
                                 "reviewed_to": "2020-12-31"},
                             {"reviewed_from": "2026-01-01"})
    by_m = {r["metric"]: r for r in res["rows"]}
    assert by_m["Проверено"] == {"metric": "Проверено", "a": 1, "b": 2,
                                 "delta": 1.0}
    assert by_m["Bad %"]["a"] == 0.0
    assert by_m["Bad %"]["b"] == 50.0
    assert by_m["Bad %"]["delta"] == 50.0
    assert len(res["top_a"]) == 0  # в 2020 ошибок не было — честно пусто
    empty = an.compare_periods(p, {"reviewed_from": "2030-01-01"}, {})
    em = {r["metric"]: r for r in empty["rows"]}
    assert em["Good %"] == {"metric": "Good %", "a": None, "b": 66.7,
                            "delta": None}


def test_file_scope_limits_summary():
    """Охват файлом режет и карточки, и динамику, и топ."""
    from database import db
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "a.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "a1", "i": "a1"}, {"q": "a2", "i": "a2"}])
    import_file(p, "b.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "b1", "i": "b1"}])
    with db(p) as conn:
        fids = {r["file_name"]: r["file_id"] for r in conn.execute(
            "SELECT file_id, file_name FROM files").fetchall()}
        aids = [r["case_id"] for r in conn.execute(
            "SELECT case_id FROM cases WHERE file_id=?", (fids["a.xlsx"],)).fetchall()]
    bulk_set_status(p, aids, "good")
    all_cards = an.card_counts(p, {})["cards"]
    assert all_cards["reviewed"]["value"] == 2
    scoped = an.card_counts(p, {"file_id": fids["b.xlsx"]})["cards"]
    assert scoped["reviewed"]["value"] == 0
    assert scoped["total"]["value"] == 1
    dyn = an.dynamics(p, {"file_id": fids["a.xlsx"]})
    assert sum(d["reviewed"] for d in dyn) == 2
    assert an.top_categories(p, {"file_id": fids["b.xlsx"]}) == []


def test_regression_analytics_empty_single_pair():
    """V2 §3: нет запусков / один запуск / пара (новые/испр/оставшиеся)."""
    import model_run_service as m
    import regression_service as rg
    from dataset_service import create_dataset, create_version, freeze_version
    from filter_service import get_filtered_case_ids
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(4)])
    assert an.regression_analytics(p) == {"present": False}
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    ds = create_dataset(p, "T", dataset_type="test")
    v = create_version(p, ds)
    freeze_version(p, v)
    c = m.create_run(p, "cand", "mx")
    m.import_run_rows(p, c, [{"source_id": f"k{i}", "answer": f"a{i}"}
                             for i in range(4)])
    rg.set_output_review(p, c, "src:k0", "bad")
    rg.set_output_review(p, c, "src:k1", "good")
    r1 = rg.run_regression(p, "r1", "dataset_version", v, "run", c)
    one = an.regression_analytics(p)
    assert one["present"] is True and one["prev"] is None
    assert len(one["new_ids"]) == 1 and len(one["improved_ids"]) == 0
    assert one["fixed_ids"] == [] and one["stayed_ids"] == []
    # цифра == drill: кейсы из new_ids открываются тем же фильтром
    assert set(get_filtered_case_ids(p, {"case_ids": one["new_ids"]})) == \
        set(one["new_ids"])
    rg.set_output_review(p, c, "src:k0", "good")
    rg.set_output_review(p, c, "src:k1", "bad")
    r2 = rg.run_regression(p, "r2", "dataset_version", v, "run", c)
    assert r2 != r1
    two = an.regression_analytics(p)
    assert two["present"] is True
    assert two["latest"]["regression_id"] == r2
    assert two["prev"]["regression_id"] == r1
    assert len(two["new_ids"]) == 1
    assert len(two["fixed_ids"]) == 1
    assert two["stayed_ids"] == []
    assert set(two["new_ids"]) | set(two["fixed_ids"])
    for key in ("new_ids", "fixed_ids", "stayed_ids"):
        flt = {"case_ids": two[key]}
        if two[key]:
            assert set(get_filtered_case_ids(p, flt)) == set(two[key])
    scoped = an.regression_analytics(p, {"file_id": 999999})
    assert scoped["present"] is True
    assert scoped["new_ids"] == [] and scoped["fixed_ids"] == []


def test_version_breakdown_runs_and_datasets():
    """V2 §4: срез по model/prompt без LLM-домыслов + слепки датасетов."""
    import model_run_service as m
    import regression_service as rg
    from dataset_service import create_dataset, create_version, freeze_version
    from filter_service import get_filtered_case_ids
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(4)])
    assert an.version_breakdown(p, "model_version") == {
        "dim": "model_version", "rows": []}
    a = m.create_run(p, "A", "mx", model_version="1.0", prompt_version="p1")
    b = m.create_run(p, "B", "mx", model_version="2.0", prompt_version="p1")
    m.import_run_rows(p, a, [{"source_id": "k0", "answer": "a0"},
                             {"source_id": "k1", "answer": "a1"}])
    m.import_run_rows(p, b, [{"source_id": "k2", "answer": "a2"},
                             {"source_id": "k3", "answer": "a3"}])
    rg.set_output_review(p, a, "src:k0", "bad")
    rg.set_output_review(p, a, "src:k1", "good")
    rg.set_output_review(p, b, "src:k2", "good")
    rg.set_output_review(p, b, "src:k3", "good")
    mv = an.version_breakdown(p, "model_version")
    by_v = {r["value"]: r for r in mv["rows"]}
    assert by_v["1.0"]["bad"] == 1 and by_v["1.0"]["total"] == 2
    assert by_v["1.0"]["rate"] == 50.0
    assert by_v["2.0"]["bad"] == 0 and by_v["2.0"]["rate"] == 0.0
    assert set(get_filtered_case_ids(
        p, {"case_ids": by_v["1.0"]["case_ids"]})) == \
        set(by_v["1.0"]["case_ids"])
    pv = an.version_breakdown(p, "prompt_version")
    assert len(pv["rows"]) == 1 and pv["rows"][0]["value"] == "p1"
    assert pv["rows"][0]["total"] == 4 and pv["rows"][0]["bad"] == 1
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids, "good")
    ds = create_dataset(p, "T", dataset_type="test")
    v1 = create_version(p, ds)
    freeze_version(p, v1)
    bulk_set_status(p, ids[:1], "bad")
    create_version(p, ds)
    dv = an.version_breakdown(p, "dataset")
    assert [r["bad"] for r in dv["rows"]] == [1, 0]
    assert dv["rows"][1]["rate"] == 0.0
    assert len(dv["rows"][0]["case_ids"]) == 1


def test_detect_anomalies_quiet_spike_and_surge():
    """V2 §5: тихо на малом/чистом, шип Bad, всплеск+однотипность."""
    from datetime import datetime as _dt, timedelta as _td, UTC as _UTC
    from database import db
    from filter_service import get_filtered_case_ids
    now = _dt.now(_UTC)
    recent = now.isoformat()
    base_day = (now - _td(days=10)).isoformat()
    # тихо: мало данных — молчим
    p0 = tempfile.mkdtemp()
    init_database(p0)
    import_file(p0, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": "q1", "i": "k1"}, {"q": "q2", "i": "k2"}])
    ids0 = get_filtered_case_ids(p0, {})
    bulk_set_status(p0, ids0, "good")
    assert an.detect_anomalies(p0) == []
    # шип Bad: база 12 (1 плохой), неделя 12 (6 плохих)
    p1 = tempfile.mkdtemp()
    init_database(p1)
    import_file(p1, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(24)])
    ids1 = get_filtered_case_ids(p1, {})
    bulk_set_status(p1, ids1[:11], "good")
    bulk_set_status(p1, ids1[11:12], "bad")
    bulk_set_status(p1, ids1[12:18], "good")
    bulk_set_status(p1, ids1[18:24], "bad")
    with db(p1) as conn:
        for cid in ids1[:12]:
            conn.execute("UPDATE annotations SET updated_at=? "
                         "WHERE case_id=?", (base_day, cid))
        for cid in ids1[12:]:
            conn.execute("UPDATE annotations SET updated_at=? "
                         "WHERE case_id=?", (recent, cid))
    hits = an.detect_anomalies(p1)
    spike = [h for h in hits if h["code"] == "bad_spike"]
    assert len(spike) == 1 and spike[0]["level"] == "critical"
    assert spike[0]["case_ids"] and \
        set(get_filtered_case_ids(p1, {"case_ids": spike[0]["case_ids"]})) == \
        set(spike[0]["case_ids"])
    # всплеск категории + однотипность: 6 свежих одной категории
    p2 = tempfile.mkdtemp()
    init_database(p2)
    import_file(p2, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(6)])
    ids2 = get_filtered_case_ids(p2, {})
    bulk_set_status(p2, ids2, "bad")
    from taxonomy_service import set_case_error
    with db(p2) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "LIMIT 1").fetchone()
        assert cat is not None
        cid_cat = cat["category_id"]
    for cid in ids2:
        set_case_error(p2, cid, cid_cat, None, "high")
    with db(p2) as conn:
        for cid in ids2:
            conn.execute("UPDATE annotations SET updated_at=? "
                         "WHERE case_id=?", (recent, cid))
            conn.execute("UPDATE case_errors SET updated_at=? "
                         "WHERE case_id=?", (recent, cid))
    hits2 = an.detect_anomalies(p2)
    codes2 = {h["code"] for h in hits2}
    assert "cat_surge" in codes2 and "uniform" in codes2
    for h in hits2:
        if h["case_ids"]:
            assert set(get_filtered_case_ids(
                p2, {"case_ids": h["case_ids"]})) == set(h["case_ids"])


def test_main_changes_facts_and_drill():
    """V2 §6: новые кейсы/Bad/баги/время/категории — факты + клики."""
    from datetime import datetime as _dt, timedelta as _td, UTC as _UTC
    from database import db
    from filter_service import get_filtered_case_ids
    now = _dt.now(_UTC)
    old = (now - _td(days=40)).isoformat()
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(4)])
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[:3], "good")
    bulk_set_status(p, ids[3:], "bad")
    with db(p) as conn:
        for cid in ids:
            conn.execute("UPDATE annotations SET review_duration_s=10.0 "
                         "WHERE case_id=?", (cid,))
        old_ids = ids[:1]
        for cid in old_ids:
            conn.execute("UPDATE cases SET created_at=? WHERE case_id=?",
                         (old, cid))
    from taxonomy_service import set_case_error
    from bug_report_service import create_bug
    with db(p) as conn:
        cat = conn.execute("SELECT category_id FROM error_categories "
                           "LIMIT 1").fetchone()
    set_case_error(p, ids[3], cat["category_id"], None, "high")
    create_bug(p, "t", [ids[3]])
    res = an.main_changes(p, {})
    assert res["period"] and res["prev"]
    by_k = {i["key"]: i for i in res["items"]}
    assert set(by_k) == {"new_cases", "bad", "bugs", "time", "new_cats"}
    assert by_k["new_cases"]["cur"] == 3
    assert by_k["bad"]["cur"] == 1
    assert by_k["bugs"]["cur"] == 1
    assert by_k["time"]["cur"] == 10.0
    assert by_k["new_cats"]["cur"] == 1
    for key in ("new_cases", "bad", "bugs", "new_cats"):
        hit = by_k[key]
        if hit["case_ids"]:
            assert set(get_filtered_case_ids(
                p, {"case_ids": hit["case_ids"]})) == set(hit["case_ids"])
    assert by_k["time"]["nodrill"] is True


def test_bad_breakdown_chain_to_cases():
    """V2 §1: Bad -> категории -> типы -> кейсы, цифра == drill."""
    from database import db
    from filter_service import get_filtered_case_ids
    p = tempfile.mkdtemp()
    init_database(p)
    import_file(p, "f.xlsx", "excel", "S", 0,
                {"q": "primary_text", "i": "source_id"},
                [{"q": f"q{i}", "i": f"k{i}"} for i in range(5)])
    assert an.bad_breakdown(p) == {"total": 0, "rows": []}
    ids = get_filtered_case_ids(p, {})
    bulk_set_status(p, ids[:2], "good")
    bulk_set_status(p, ids[2:], "bad")
    from taxonomy_service import set_case_error
    with db(p) as conn:
        corr = conn.execute("SELECT category_id FROM error_categories "
                            "WHERE code='correctness'").fetchone()
        corr_sub = conn.execute("SELECT category_id FROM error_categories "
                                "WHERE code='correctness.hallucination'"
                                ).fetchone()
        comp = conn.execute("SELECT category_id FROM error_categories "
                            "WHERE code='completeness'").fetchone()
        comp_sub = conn.execute("SELECT category_id FROM error_categories "
                                "WHERE code='completeness.incomplete'"
                                ).fetchone()
    cats = [corr["category_id"], comp["category_id"]]
    set_case_error(p, ids[2], cats[0], corr_sub["category_id"], "high")
    set_case_error(p, ids[3], cats[0], corr_sub["category_id"], "high")
    set_case_error(p, ids[4], cats[1], comp_sub["category_id"], "high")
    res = an.bad_breakdown(p)
    assert res["total"] == 3
    by_c = {r["category_id"]: r for r in res["rows"]}
    assert by_c[cats[0]]["n"] == 2 and by_c[cats[1]]["n"] == 1
    assert len(by_c[cats[0]]["subs"]) == 1
    assert by_c[cats[0]]["subs"][0]["n"] == 2
    for row in res["rows"]:
        if row["category_id"] == "":
            continue
        assert set(get_filtered_case_ids(p, row["filters"])) == \
            set(row["case_ids"])
        assert len(row["case_ids"]) == row["n"]
        for s in row["subs"]:
            got = set(get_filtered_case_ids(p, s["filters"]))
            assert len(got) == s["n"], (s, got)
