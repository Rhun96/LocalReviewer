"""Расширенная проверка целостности проекта (ТЗ V2.2 §9–§10).

Только чтение + безопасный ремонт сирот. Принцип:
- check_project() — read-only отчёт: database / cases / annotations /
  tags / datasets / runs / regression / bugs / highlights;
- repair_safe() — чинит ТОЛЬКО orphan-связи (кейсы удалённых файлов +
  висячие tag-линки). Разметку, баги, снапшоты, runs, history НЕ трогаем.
  Перед массовым repair вызывающий код делает backup (диалог так и делает).

Каждый issue: {"scope": str, "detail": str, "fixable": bool}.
"""
import logging

from database import SCHEMA_VERSION, db

logger = logging.getLogger(__name__)

_VALID_STATUSES = {"unreviewed", "good", "bad", "uncertain",
                   "duplicate", "skip"}


def _tables(conn) -> set:
    try:
        return {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    except Exception:
        return set()


def check_project(project_path: str) -> dict:
    """Read-only проверка. Не бросает исключений (ошибку возвращает issue)."""
    issues: list = []
    stats: dict = {}
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            # --- database ---
            try:
                row = cur.execute("PRAGMA integrity_check").fetchone()
                if not row or row[0] != "ok":
                    issues.append({"scope": "database",
                                   "detail": f"PRAGMA integrity_check: {row[0] if row else '?'}",
                                   "fixable": False})
            except Exception as e:
                issues.append({"scope": "database",
                               "detail": f"integrity_check failed: {e}",
                               "fixable": False})
            try:
                ver = cur.execute("PRAGMA user_version").fetchone()[0] or 0
                stats["schema_version"] = int(ver)
                if ver != SCHEMA_VERSION:
                    issues.append({"scope": "database",
                                   "detail": f"version {ver}, expected {SCHEMA_VERSION}",
                                   "fixable": False})
            except Exception:
                pass
            tables = _tables(conn)

            def _count(sql: str, args=()) -> int:
                try:
                    r = cur.execute(sql, args).fetchone()
                    return int(r[0]) if r else 0
                except Exception:
                    return 0

            # --- cases: битые ссылки на файлы ---
            if "cases" in tables and "files" in tables:
                n = _count("SELECT COUNT(*) FROM cases c WHERE NOT EXISTS "
                          "(SELECT 1 FROM files f WHERE f.file_id = c.file_id)")
                stats["orphan_cases"] = n
                if n:
                    issues.append({"scope": "cases",
                                   "detail": f"кейсов-сирот (файл удалён): {n}",
                                   "fixable": True})
                # дубликаты стабильных source_id внутри файла
                try:
                    dup = cur.execute("""
                        SELECT COUNT(*) FROM (
                            SELECT file_id, source_id FROM cases
                            WHERE source_id IS NOT NULL AND source_id <> ''
                            GROUP BY file_id, source_id HAVING COUNT(*) > 1
                        )""").fetchone()
                    if dup and dup[0]:
                        issues.append({"scope": "cases",
                                       "detail": f"дубликатов source_id в файлах: {dup[0]}",
                                       "fixable": False})
                except Exception:
                    pass
            # --- annotations ---
            if "annotations" in tables:
                n = _count("SELECT COUNT(*) FROM annotations a WHERE NOT EXISTS "
                          "(SELECT 1 FROM cases c WHERE c.case_id = a.case_id)")
                if n:
                    issues.append({"scope": "annotations",
                                   "detail": f"разметок на несуществующие кейсы: {n}",
                                   "fixable": False})
                try:
                    rows = cur.execute(
                        "SELECT DISTINCT status FROM annotations").fetchall()
                    bad = [r[0] for r in rows
                           if (r[0] or "") not in _VALID_STATUSES]
                    if bad:
                        issues.append({"scope": "annotations",
                                       "detail": f"недопустимые статусы: {bad[:5]}",
                                       "fixable": False})
                except Exception:
                    pass
            # --- tags ---
            if "case_tags" in tables:
                n = _count("SELECT COUNT(*) FROM case_tags t WHERE NOT EXISTS "
                          "(SELECT 1 FROM cases c WHERE c.case_id = t.case_id)")
                stats["orphan_tag_links"] = n
                if n:
                    issues.append({"scope": "tags",
                                   "detail": f"висячих tag-линков: {n}",
                                   "fixable": True})
                if "tags" in tables:
                    n2 = _count("SELECT COUNT(*) FROM case_tags t WHERE NOT EXISTS "
                               "(SELECT 1 FROM tags g WHERE g.tag_id = t.tag_id)")
                    if n2:
                        issues.append({"scope": "tags",
                                       "detail": f"линков на несуществующие теги: {n2}",
                                       "fixable": True})
            # --- datasets ---
            for tbl in ("datasets", "dataset_versions", "dataset_cases"):
                if tbl not in tables:
                    issues.append({"scope": "datasets",
                                   "detail": f"нет таблицы {tbl}",
                                   "fixable": False})
                    break
            else:
                n = _count("SELECT COUNT(*) FROM dataset_versions v WHERE NOT EXISTS "
                          "(SELECT 1 FROM datasets d WHERE d.dataset_id = v.dataset_id)")
                if n:
                    issues.append({"scope": "datasets",
                                   "detail": f"версий без датасета: {n}",
                                   "fixable": False})
                n = _count("SELECT COUNT(*) FROM dataset_cases dc WHERE NOT EXISTS "
                          "(SELECT 1 FROM dataset_versions v "
                          "WHERE v.version_id = dc.version_id)")
                if n:
                    issues.append({"scope": "datasets",
                                   "detail": f"слепков без версии: {n}",
                                   "fixable": False})
            # --- runs / regression ---
            if "model_runs" in tables and "run_answers" in tables:
                n = _count("SELECT COUNT(*) FROM run_answers a WHERE a.case_id IS NOT NULL "
                          "AND NOT EXISTS (SELECT 1 FROM cases c "
                          "WHERE c.case_id = a.case_id)")
                if n:
                    issues.append({"scope": "runs",
                                   "detail": f"ответов на удалённые кейсы: {n}",
                                   "fixable": False})
            if "regressions" in tables:
                try:
                    cols = {r[1] for r in cur.execute(
                        "PRAGMA table_info(regressions)").fetchall()}
                    if cols:
                        n = _count("SELECT COUNT(*) FROM regression_results r "
                                  "WHERE NOT EXISTS (SELECT 1 FROM regressions g "
                                  "WHERE g.regression_id = r.regression_id)")
                        if n:
                            issues.append({"scope": "regression",
                                           "detail": f"результатов без запуска: {n}",
                                           "fixable": False})
                except Exception:
                    pass
            # --- bugs ---
            if "bug_report_cases" in tables:
                n = _count("SELECT COUNT(*) FROM bug_report_cases bc WHERE NOT EXISTS "
                          "(SELECT 1 FROM cases c WHERE c.case_id = bc.case_id)")
                if n:
                    issues.append({"scope": "bugs",
                                   "detail": f"связей баг→удалённый кейс: {n}",
                                   "fixable": False})
                n = _count("SELECT COUNT(*) FROM bug_report_cases bc WHERE NOT EXISTS "
                          "(SELECT 1 FROM bug_reports b WHERE b.bug_id = bc.bug_id)")
                if n:
                    issues.append({"scope": "bugs",
                                   "detail": f"связей на удалённые баги: {n}",
                                   "fixable": True})
            # --- highlights ---
            if "case_highlights" in tables:
                n = _count("SELECT COUNT(*) FROM case_highlights h WHERE NOT EXISTS "
                          "(SELECT 1 FROM cases c WHERE c.case_id = h.case_id)")
                if n:
                    issues.append({"scope": "highlights",
                                   "detail": f"подсветок на удалённые кейсы: {n}",
                                   "fixable": False})
                n = _count("SELECT COUNT(*) FROM case_highlights "
                          "WHERE start_offset < 0 OR end_offset <= start_offset "
                          "OR end_offset - start_offset > 1000000")
                if n:
                    issues.append({"scope": "highlights",
                                   "detail": f"подсветок с невозможным диапазоном: {n}",
                                   "fixable": False})
    except Exception as e:
        logger.warning("integrity check failed: %s", e)
        issues.append({"scope": "database", "detail": f"check failed: {e}",
                       "fixable": False})
    ok = not issues
    logger.info("integrity check: ok=%s issues=%s", ok, len(issues))
    return {"ok": ok, "issues": issues, "stats": stats}


def repair_safe(project_path: str) -> dict:
    """Безопасный ремонт: только orphan-связи. Возвращает счётчики."""
    import maintenance_service as maint
    done: dict = {}
    try:
        orph = maint.purge_orphans(project_path)
        done["orphan_cases"] = orph.get("orphan_cases", 0)
    except Exception as e:
        logger.warning("repair orphans failed: %s", e)
        done["orphan_cases"] = 0
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            tables = _tables(conn)
            nulled = 0
            if "case_tags" in tables:
                try:
                    cur.execute("DELETE FROM case_tags WHERE NOT EXISTS "
                               "(SELECT 1 FROM cases c "
                               "WHERE c.case_id = case_tags.case_id)")
                    nulled += cur.rowcount or 0
                except Exception:
                    pass
                try:
                    cur.execute("DELETE FROM case_tags WHERE NOT EXISTS "
                               "(SELECT 1 FROM tags g "
                               "WHERE g.tag_id = case_tags.tag_id)")
                    nulled += cur.rowcount or 0
                except Exception:
                    pass
            done["tag_links"] = nulled
            if "bug_report_cases" in tables:
                try:
                    cur.execute("DELETE FROM bug_report_cases WHERE NOT EXISTS "
                               "(SELECT 1 FROM bug_reports b "
                               "WHERE b.bug_id = bug_report_cases.bug_id)")
                    done["bug_links"] = cur.rowcount or 0
                except Exception:
                    done["bug_links"] = 0
    except Exception as e:
        logger.warning("repair tag links failed: %s", e)
    logger.info("safe repair: %s", done)
    return done
