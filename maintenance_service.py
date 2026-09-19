"""Гигиена БД: сироты удалённых файлов (кейсы + хвосты).

Сироты — кейсы, чей file_id отсутствует в files (удаление мимо каскада).
Они невидимы везде (все выборки JOIN files), но врут в сырых COUNT.
Чистка явная, с отчётом; bulk-операции и снимки версий не трогаем
(это журнал и аудит, а не мусор).
"""
import logging

from database import db

logger = logging.getLogger(__name__)

_ORPHAN = ("cases c WHERE NOT EXISTS "
           "(SELECT 1 FROM files f WHERE f.file_id = c.file_id)")

# Дети кейсов с каскадом: удалятся сами при FK ON, явно — при FK OFF.
_CASCADE_CHILDREN = (
    "annotations", "case_tags", "history", "case_checks",
    "case_check_verdicts", "case_errors", "bug_report_cases",
)
# Дети с SET NULL: обнуляем ссылки явно (независимо от FK).
_NULL_CHILDREN = (
    "run_answers", "run_preferences", "output_reviews", "regression_results",
)


def integrity_report(project_path: str) -> dict:
    """Подсчёт сирот и висячих ссылок. Только чтение."""
    with db(project_path) as conn:
        cur = conn.cursor()
        try:
            orphans = [r["case_id"] for r in cur.execute(
                f"SELECT c.case_id FROM {_ORPHAN}").fetchall()]
        except Exception:
            orphans = []
        children = {}
        if orphans:
            ph = ",".join(["?"] * len(orphans))
            for t in _CASCADE_CHILDREN + _NULL_CHILDREN:
                try:
                    n = cur.execute(
                        f"SELECT COUNT(*) AS c FROM {t} WHERE case_id IN ({ph})",
                        orphans).fetchone()["c"]
                    if n:
                        children[t] = n
                except Exception:
                    continue
        files = cur.execute("SELECT COUNT(*) AS c FROM files").fetchone()["c"]
        cases = cur.execute("SELECT COUNT(*) AS c FROM cases").fetchone()["c"]
    return {"files": files, "cases": cases, "orphan_cases": len(orphans),
            "children": children, "healthy": not orphans}


def purge_orphans(project_path: str) -> dict:
    """Удаляет сирот и обнуляет ссылки. Возвращает счётчики."""
    removed: dict = {}
    with db(project_path) as conn:
        cur = conn.cursor()
        orphans = [r["case_id"] for r in cur.execute(
            f"SELECT c.case_id FROM {_ORPHAN}").fetchall()]
        if not orphans:
            return {"orphan_cases": 0, "children": {}, "nulled": {}}
        children = {}
        for t in _CASCADE_CHILDREN:
            try:
                ph = ",".join(["?"] * len(orphans))
                cur.execute(f"DELETE FROM {t} WHERE case_id IN ({ph})", orphans)
                if cur.rowcount:
                    children[t] = cur.rowcount
            except Exception as e:
                logger.warning("purge %s failed: %s", t, e)
        nulled = {}
        for t in _NULL_CHILDREN:
            try:
                ph = ",".join(["?"] * len(orphans))
                cur.execute(f"UPDATE {t} SET case_id=NULL WHERE case_id IN ({ph})",
                            orphans)
                if cur.rowcount:
                    nulled[t] = cur.rowcount
            except Exception as e:
                logger.warning("purge null %s failed: %s", t, e)
        ph = ",".join(["?"] * len(orphans))
        cur.execute(f"DELETE FROM cases WHERE case_id IN ({ph})", orphans)
        removed = {"orphan_cases": cur.rowcount, "children": children,
                   "nulled": nulled}
    logger.info("purged orphans: %s", removed)
    return removed
