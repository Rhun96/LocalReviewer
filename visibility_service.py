"""Скрытие мусорных строк из ревью (v19): не удаление, а невидимость.

Скрытые кейсы: вне очереди/фильтров/счётчиков/версий/экспорта, но в БД
и истории остаются; показываются только серыми по тумблеру таблицы.
"""
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)


def _set_many(project_path: str, case_ids: list, hidden: bool) -> int:
    ids = list(dict.fromkeys(int(c) for c in (case_ids or [])))
    if not ids:
        return 0
    now, done = utcnow(), 0
    with db(project_path) as conn:
        cur = conn.cursor()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            rows = cur.execute(
                f"SELECT case_id, COALESCE(hidden, 0) AS h FROM cases "
                f"WHERE case_id IN ({ph})", chunk).fetchall()
            targets = [r["case_id"] for r in rows
                       if bool(r["h"]) != bool(hidden)]
            for cid in targets:
                cur.execute("UPDATE cases SET hidden=? WHERE case_id=?",
                            (1 if hidden else 0, cid))
                cur.execute("""
                    INSERT INTO history
                        (case_id, event_type, field_name, old_value,
                         new_value, created_at)
                    VALUES (?, ?, 'hidden', ?, ?, ?)
                """, (cid, "case_hidden" if hidden else "case_shown",
                      "0" if hidden else "1", "1" if hidden else "0", now))
                done += 1
    if done:
        logger.info("%s %s cases hidden=%s", project_path, done, hidden)
    return done


def hide_cases(project_path: str, case_ids: list) -> int:
    """Скрыть из ревью. Возвращает число реально изменённых."""
    return _set_many(project_path, case_ids, True)


def unhide_cases(project_path: str, case_ids: list) -> int:
    """Вернуть в ревью. Возвращает число реально изменённых."""
    return _set_many(project_path, case_ids, False)


def hidden_count(project_path: str, file_id: int | None = None) -> int:
    with db(project_path) as conn:
        if file_id:
            row = conn.execute("SELECT COUNT(*) AS c FROM cases "
                               "WHERE file_id=? AND COALESCE(hidden, 0) = 1",
                               (file_id,)).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM cases "
                               "WHERE COALESCE(hidden, 0) = 1").fetchone()
        return row["c"] if row else 0
