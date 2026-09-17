"""Поиск похожих кейсов без LLM (ТЗ §64-70): TF-IDF + косинус, n-граммы.

Только stdlib (без sklearn/numpy): токены слов + биграммы, сглаженный IDF,
косинусная близость. Ничего не размечает автоматически — только показывает
похожий контекст для решения человека.
"""
import logging
import math
import re
import unicodedata
from collections import Counter
from database import db

logger = logging.getLogger(__name__)

FIELDS = ("primary_text", "response_text", "group_name", "product")
FIELD_NAMES = {"primary_text": "Запрос", "response_text": "Ответ",
               "group_name": "Группа", "product": "Продукт"}
SCOPES = ("file", "project", "golden", "archive")

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)


def normalize(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    return re.sub(r"\s+", " ", text)


def _tokens(text: str) -> list:
    return [t for t in _TOKEN_RE.findall(normalize(text)) if len(t) >= 2]


def _terms(text: str) -> list:
    """Униграммы + биграммы слов."""
    toks = _tokens(text)
    terms = list(toks)
    terms.extend(f"{a} {b}" for a, b in zip(toks, toks[1:], strict=False))
    return terms


def _doc_text(row: dict, fields: tuple, meta: dict | None = None) -> str:
    parts = []
    for f in fields:
        if f == "product":
            v = (meta or {}).get("product", "")
        else:
            v = row.get(f, "")
        if v:
            parts.append(str(v))
    return "\n".join(parts)


def _tfidf_vectors(docs: list) -> list:
    """docs: list[Counter]. Возвращает list[dict term -> вес]."""
    n = len(docs)
    if not n:
        return []
    df: Counter = Counter()
    for c in docs:
        for t in c:
            df[t] += 1
    idf = {t: math.log((1 + n) / (1 + f)) + 1.0 for t, f in df.items()}
    out = []
    for c in docs:
        vec = {t: (1.0 + math.log(k)) * idf[t] for t, k in c.items()}
        out.append(vec)
    return out


def _cosine(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    dot = sum(w * b[t] for t, w in a.items() if t in b)
    if not dot:
        return 0.0
    na = math.sqrt(sum(w * w for w in a.values()))
    nb = math.sqrt(sum(w * w for w in b.values()))
    if not na or not nb:
        return 0.0
    return dot / (na * nb)


def _scope_case_ids(cursor, scope: str, file_id: int | None = None) -> list | None:
    """Список case_id области или None (= все кейсы проекта)."""
    if scope == "file":
        if file_id is None:
            raise ValueError("Для области «файл» нужен file_id")
        return [r["case_id"] for r in cursor.execute(
            "SELECT case_id FROM cases WHERE file_id=?", (file_id,))]
    if scope == "golden":
        return [r["case_id"] for r in cursor.execute("""
            SELECT DISTINCT dc.case_id FROM dataset_cases dc
            JOIN dataset_versions v ON v.version_id = dc.version_id
            JOIN datasets d ON d.dataset_id = v.dataset_id
            WHERE d.dataset_type = 'golden' AND v.status = 'frozen'
        """)]
    if scope == "archive":
        return [r["case_id"] for r in cursor.execute("""
            SELECT DISTINCT dc.case_id FROM dataset_cases dc
            JOIN dataset_versions v ON v.version_id = dc.version_id
            WHERE v.status = 'archived'
        """)]
    if scope == "project":
        return None
    raise ValueError(f"Плохая область: {scope!r}")


def _load_docs(cursor, case_ids: list | None, fields: tuple) -> list:
    """[{case_id, file_id, source_id, primary_text, terms}] (+мета для product)."""
    import json as _json
    if case_ids is not None and not case_ids:
        return []
    docs = []
    ids = case_ids
    if ids is None:
        rows = cursor.execute(
            "SELECT case_id, file_id, source_id, primary_text, response_text,"
            " group_name, metadata_json FROM cases").fetchall()
    else:
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            rows = cursor.execute(f"""
                SELECT case_id, file_id, source_id, primary_text, response_text,
                       group_name, metadata_json FROM cases
                WHERE case_id IN ({ph})
            """, chunk).fetchall()
            for r in rows:
                meta = {}
                if "product" in fields and r["metadata_json"]:
                    try:
                        parsed = _json.loads(r["metadata_json"])
                        if isinstance(parsed, dict):
                            meta = parsed
                    except Exception:
                        pass
                text = _doc_text(dict(r), fields, meta)
                docs.append({"case_id": r["case_id"], "file_id": r["file_id"],
                             "source_id": r["source_id"],
                             "primary_text": r["primary_text"] or "",
                             "terms": Counter(_terms(text))})
        return docs
    for r in rows:
        meta = {}
        if "product" in fields and r["metadata_json"]:
            try:
                parsed = _json.loads(r["metadata_json"])
                if isinstance(parsed, dict):
                    meta = parsed
            except Exception:
                pass
        text = _doc_text(dict(r), fields, meta)
        docs.append({"case_id": r["case_id"], "file_id": r["file_id"],
                     "source_id": r["source_id"],
                     "primary_text": r["primary_text"] or "",
                     "terms": Counter(_terms(text))})
    return docs


def find_similar(project_path: str, case_id: int, min_score: float = 0.75,
                 scope: str = "file", fields: tuple = ("primary_text",),
                 top_n: int = 10) -> dict:
    """Похожие на кейс: [{case_id, source_id, score, status, snippet, ...}].

    score — косинус 0..1 (показываем как %). Пустой текст запроса или
    пустая область → пустой список (не ошибка).
    """
    if scope not in SCOPES:
        raise ValueError(f"Плохая область: {scope!r}")
    if not 0 <= min_score <= 1:
        raise ValueError("min_score: 0..1")
    if fields is None:
        fields = ("primary_text",)
    fields = tuple(f for f in fields if f in FIELDS)
    if not fields:
        raise ValueError("Нужно хотя бы одно поле")
    with db(project_path) as conn:
        cur = conn.cursor()
        qrow = cur.execute("SELECT case_id, file_id FROM cases WHERE case_id=?",
                           (case_id,)).fetchone()
        if not qrow:
            raise ValueError("Кейс не найден")
        file_id = qrow["file_id"]
        ids = _scope_case_ids(cur, scope, file_id)
        docs = _load_docs(cur, ids, fields)
        statuses = {r["case_id"]: r["status"] for r in cur.execute(
            "SELECT case_id, status FROM annotations").fetchall()}
    query = next((d for d in docs if d["case_id"] == case_id), None)
    if not query or not query["terms"]:
        return {"case_id": case_id, "total": 0, "results": []}
    vecs = _tfidf_vectors([d["terms"] for d in docs])
    qvec = vecs[docs.index(query)]
    out = []
    for doc, vec in zip(docs, vecs, strict=True):
        if doc["case_id"] == case_id:
            continue
        score = _cosine(qvec, vec)
        if score >= min_score:
            st = statuses.get(doc["case_id"], "unreviewed")
            out.append({"case_id": doc["case_id"],
                        "source_id": doc["source_id"],
                        "score": round(score, 4),
                        "status": st,
                        "reviewed": st != "unreviewed",
                        "snippet": (doc["primary_text"] or "")[:160]})
    out.sort(key=lambda r: -r["score"])
    return {"case_id": case_id, "total": len(out),
            "results": out[:max(1, top_n)]}


def find_duplicates(project_path: str, file_id: int | None = None,
                    threshold: float = 0.9, limit: int = 200,
                    progress_callback=None, cancel_event=None) -> dict:
    """Пары потенциальных дублей в области (файл или весь проект).

    O(n²): файлы > 3000 кейсов отклоняем с подсказкой (сузь область).
    Возвращает пары [case_a, case_b, score] по убыванию (не более limit).
    """
    from workers import Cancelled
    if not 0 <= threshold <= 1:
        raise ValueError("threshold: 0..1")
    with db(project_path) as conn:
        cur = conn.cursor()
        if file_id is not None:
            ids = [r["case_id"] for r in cur.execute(
                "SELECT case_id FROM cases WHERE file_id=?", (file_id,))]
        else:
            ids = [r["case_id"] for r in cur.execute("SELECT case_id FROM cases")]
        if len(ids) > 3000:
            raise ValueError(f"Слишком много кейсов ({len(ids)}): попарное сравнение "
                             "O(n²) — выбери файл поменьше или подними порог")
        docs = _load_docs(cur, ids, ("primary_text", "response_text"))
    vecs = _tfidf_vectors([d["terms"] for d in docs])
    pairs = []
    n = len(docs)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            raise Cancelled(f"Прервано пользователем: проверено {i} из {n}")
        if not docs[i]["terms"]:
            continue
        for j in range(i + 1, n):
            if not docs[j]["terms"]:
                continue
            s = _cosine(vecs[i], vecs[j])
            if s >= threshold:
                pairs.append({"case_a": docs[i]["case_id"],
                              "case_b": docs[j]["case_id"],
                              "score": round(s, 4)})
        if progress_callback and (i + 1) % 100 == 0:
            try:
                progress_callback(i + 1, n)
            except Exception:
                pass
    pairs.sort(key=lambda p: -p["score"])
    return {"total": len(pairs), "pairs": pairs[:limit],
            "truncated": len(pairs) > limit}


class SimilarityBackend:
    """Интерфейс движка схожести (ТЗ V2 §19, §33)."""
    name = "base"

    def find_similar(self, project_path: str, case_id: int, **kwargs) -> dict:
        raise NotImplementedError

    def find_duplicates(self, project_path: str, **kwargs) -> dict:
        raise NotImplementedError


class TfidfSimilarityBackend(SimilarityBackend):
    """Локальный TF-IDF backend (по умолчанию, без LLM/embeddings)."""
    name = "tfidf"

    def find_similar(self, project_path: str, case_id: int, **kwargs) -> dict:
        return find_similar(project_path, case_id, **kwargs)

    def find_duplicates(self, project_path: str, **kwargs) -> dict:
        return find_duplicates(project_path, **kwargs)


# Будущий EmbeddingSimilarityBackend регистрируется здесь же;
# UI ходит через get_backend() и не зависит от реализации.
BACKENDS = {"tfidf": TfidfSimilarityBackend()}


def get_backend(name: str = "tfidf") -> SimilarityBackend:
    be = BACKENDS.get(name)
    if be is None:
        raise ValueError(f"Неизвестный backend: {name!r}")
    return be
