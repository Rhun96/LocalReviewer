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


def search_semantic(project_path: str, query: str, scope: str = "project",
                    file_id: int | None = None, min_score: float | None = None,
                    top_n: int = 10) -> dict:
    """Поиск по смыслу произвольного текста (text-query).

    Движок — из настроек (resolve_backend): эмбеддинги, если модель на месте,
    иначе TF-IDF с честной пометкой. Ошибка эмбеддинг-слоя в рантайме
    (нет torch/весов) — тоже молча TF-IDF + пометка, а не красная ошибка.
    Возвращает {results, total, backend, note, indexed, scope_total, missing}.
    Пустой запрос → пустые результаты (не ошибка).
    """
    q = (query or "").strip()
    empty = {"query": query or "", "total": 0, "results": [], "backend": "tfidf",
             "note": "", "indexed": 0, "scope_total": 0, "missing": []}
    if not q:
        return empty
    import similarity_service as sim
    be, note = sim.resolve_backend()
    if min_score is None:
        if be.name == "embedding":
            try:
                from ui_compat import get_embed_threshold as _thr
                min_score = float(_thr())
            except Exception:
                min_score = 0.65
        else:
            min_score = 0.3
    try:
        res = be.find_by_text(project_path, q, min_score=min_score,
                              scope=scope, file_id=file_id, top_n=top_n)
    except ValueError:
        raise
    except Exception as e:
        logger.warning("semantic search backend failed, TF-IDF fallback: %s", e)
        be = sim.get_backend("tfidf")
        note = (note + "; " if note else "") + "эмбеддинги недоступны — TF-IDF"
        res = be.find_by_text(project_path, q, min_score=0.3,
                              scope=scope, file_id=file_id, top_n=top_n)
    rows = [{"case_id": r["case_id"],
             "source_id": r.get("source_id") or "",
             "snippet": (r.get("snippet") or "")[:160],
             "score": r.get("score", 0.0),
             "status": r.get("status", "unreviewed"),
             "reviewed": r.get("reviewed", False)}
            for r in res.get("results", [])]
    return {"query": q, "total": res.get("total", len(rows)), "results": rows,
            "backend": getattr(be, "name", "tfidf"), "note": note,
            "indexed": res.get("indexed", 0),
            "scope_total": res.get("scope_total", 0),
            "missing": res.get("missing") or []}
