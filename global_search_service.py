"""Глобальный поиск кейса (ТЗ V2.2 §13): Ctrl+P, command-like диалог.

Ищем по case_id / source_id (точно + частично), при необходимости — по
тексту вопроса. Кириллица — через lower_ru (SQLite LOWER не знает её).
Одно совпадение — сразу открыть; несколько — компактный список.
Тяжёлый text search ограничен лимитом, живёт в фоне у вызывающего кода
(здесь только синхронный сервис + тесты).
"""
import logging

from database import db

logger = logging.getLogger(__name__)

LIMIT = 50


def search_cases(project_path: str, query: str, limit: int = LIMIT) -> list:
    """Возвращает [{case_id, source_id, snippet}].

    Пустой запрос -> []. Сначала ID-совпадения (точные вверх), потом текст.
    """
    q = (query or "").strip()
    if not q:
        return []
    out: list = []
    seen: set = set()
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            # 1) точный case_id
            try:
                cid = int(q)
                r = cur.execute(
                    "SELECT case_id, source_id, substr(primary_text, 1, 120) AS sn "
                    "FROM cases WHERE case_id = ?", (cid,)).fetchone()
                if r:
                    out.append({"case_id": r["case_id"],
                                "source_id": r["source_id"] or "",
                                "snippet": (r["sn"] or "")[:120]})
                    seen.add(r["case_id"])
            except (TypeError, ValueError):
                pass
            # 2) точный source_id
            try:
                rows = cur.execute(
                    "SELECT case_id, source_id, substr(primary_text, 1, 120) AS sn "
                    "FROM cases WHERE source_id = ? LIMIT 10", (q,)).fetchall()
                for r in rows:
                    if r["case_id"] not in seen:
                        out.append({"case_id": r["case_id"],
                                    "source_id": r["source_id"] or "",
                                    "snippet": (r["sn"] or "")[:120]})
                        seen.add(r["case_id"])
            except Exception:
                pass
            # 3) частичный source_id (LIKE, lower_ru для кириллицы)
            if len(out) < limit:
                try:
                    pat = f"%{q}%"
                    rows = cur.execute(
                        "SELECT case_id, source_id, substr(primary_text, 1, 120) AS sn "
                        "FROM cases WHERE lower_ru(COALESCE(source_id,'')) "
                        "LIKE lower_ru(?) ESCAPE '\\' LIMIT ?",
                        (pat, limit)).fetchall()
                    for r in rows:
                        if r["case_id"] not in seen:
                            out.append({"case_id": r["case_id"],
                                        "source_id": r["source_id"] or "",
                                        "snippet": (r["sn"] or "")[:120]})
                            seen.add(r["case_id"])
                        if len(out) >= limit:
                            break
                except Exception:
                    pass
            # 4) текст вопроса (подстрока, только если ID ничего не дали)
            if not out:
                try:
                    pat = f"%{q}%"
                    rows = cur.execute(
                        "SELECT case_id, source_id, substr(primary_text, 1, 120) AS sn "
                        "FROM cases WHERE lower_ru(COALESCE(primary_text,'')) "
                        "LIKE lower_ru(?) ESCAPE '\\' LIMIT ?",
                        (pat, limit)).fetchall()
                    for r in rows:
                        out.append({"case_id": r["case_id"],
                                    "source_id": r["source_id"] or "",
                                    "snippet": (r["sn"] or "")[:120]})
                except Exception:
                    pass
    except Exception as e:
        logger.warning("global search failed: %s", e)
        return []
    return out[:limit]
