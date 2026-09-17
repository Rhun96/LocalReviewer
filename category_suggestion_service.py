"""Подсказки разметки (ТЗ V2 §18-19, §33): статус и категория по похожим.

Первый backend — RuleBased (TF-IDF-близость к уже размеченным кейсам проекта).
Ничего не применяется автоматически: UI показывает «Предложено … [Применить]».
Будущие backend (embedding/LLM) — классами ниже через тот же suggest().
"""
import logging
from database import db

logger = logging.getLogger(__name__)


class SuggestionBackend:
    name = "base"

    def suggest(self, project_path: str, case_id: int, **kwargs) -> dict:
        raise NotImplementedError


class RuleBasedSuggestionBackend(SuggestionBackend):
    """Веса слов похожих размеченных кейсов (TF-IDF similarity)."""
    name = "rule"

    def suggest(self, project_path: str, case_id: int, top_n: int = 5,
                min_score: float = 0.4, min_support: int = 2) -> dict:
        import similarity_service as sim
        try:
            res = sim.find_similar(project_path, case_id, min_score=min_score,
                                   scope="project",
                                   fields=("primary_text", "response_text"),
                                   top_n=max(10, top_n * 3))
        except Exception as e:
            logger.warning("suggest similarity failed: %s", e)
            return {"status": None, "category": None}
        cands = [r for r in res.get("results", []) if r.get("reviewed")]
        if not cands:
            return {"status": None, "category": None}
        with db(project_path) as conn:
            cur = conn.cursor()
            info = {}
            for r in cands[:top_n * 2]:
                row = cur.execute("""
                    SELECT COALESCE(a.status, 'unreviewed') AS status,
                           e.category_id, e.subcategory_id
                    FROM cases c
                    LEFT JOIN annotations a ON a.case_id = c.case_id
                    LEFT JOIN case_errors e ON e.case_id = c.case_id
                    WHERE c.case_id = ?
                """, (r["case_id"],)).fetchone()
                if row:
                    info[r["case_id"]] = dict(row)
        status_w: dict = {}
        cat_w: dict = {}
        for r in cands:
            meta = info.get(r["case_id"], {})
            st = meta.get("status") or "unreviewed"
            if st != "unreviewed":
                status_w[st] = status_w.get(st, 0.0) + r["score"]
            key = (meta.get("category_id"), meta.get("subcategory_id"))
            if key[0]:
                cat_w[key] = cat_w.get(key, 0.0) + r["score"]
        out = {"status": None, "category": None}
        if status_w:
            best, w = max(status_w.items(), key=lambda kv: kv[1])
            support = sum(1 for r in cands
                          if (info.get(r["case_id"], {}).get("status")) == best)
            if support >= min_support:
                out["status"] = {"status": best, "score": round(w, 3),
                                 "support": support}
        if cat_w:
            (cid, sid), w = max(cat_w.items(), key=lambda kv: kv[1])
            support = sum(1 for r in cands
                          if (info.get(r["case_id"], {}).get("category_id"),
                              info.get(r["case_id"], {}).get("subcategory_id"))
                          == (cid, sid))
            if support >= min_support:
                out["category"] = {"category_id": cid, "subcategory_id": sid,
                                   "score": round(w, 3), "support": support}
        if out["category"]:
            try:
                with db(project_path) as conn:
                    cur = conn.cursor()
                    c = cur.execute("SELECT name FROM error_categories "
                                    "WHERE category_id=?", (cid,)).fetchone()
                    s = cur.execute("SELECT name FROM error_categories "
                                    "WHERE category_id=?", (sid,)).fetchone() \
                        if sid else None
                    out["category"]["category_name"] = c["name"] if c else ""
                    out["category"]["subcategory_name"] = s["name"] if s else ""
            except Exception:
                pass
        return out


BACKENDS = {"rule": RuleBasedSuggestionBackend()}
# Заглушки под будущие backend (§18): EmbeddingCategorySuggestion,
# LLMCategorySuggestion — регистрируются здесь же.


def suggest_annotations(project_path: str, case_id: int, backend: str = "rule",
                        **kwargs) -> dict:
    """{status: {...}|None, category: {...}|None} — только предложение."""
    be = BACKENDS.get(backend)
    if be is None:
        raise ValueError(f"Неизвестный backend: {backend!r}")
    return be.suggest(project_path, case_id, **kwargs)
