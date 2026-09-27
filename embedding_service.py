"""Локальные эмбеддинги кейсов (Gemma-300M, опционально).

Без torch/transformers/модели ничего не ломается: любая проблема слоя —
EmbeddingUnavailableError, вызывающий код падает на TF-IDF.
torch/transformers импортируются ТОЛЬКО внутри загрузчика модели.
"""
import hashlib
import logging
import threading

import numpy as np

from database import db, utcnow

logger = logging.getLogger(__name__)

MODEL_NAME = "google/embeddinggemma-300m"
MODEL_VERSION = "v1"
DIMENSIONS = 768

_MODEL = None
_MODEL_LOCK = threading.Lock()


class EmbeddingUnavailableError(Exception):
    """Слой недоступен: нет рантайма, модели или она не загрузилась."""


def build_text(primary: str | None, response: str | None,
               comment: str | None = None) -> str:
    """Единый нормализованный текст (ТЗ §7): без ID и timestamps."""
    parts = [p.strip() for p in (primary or "", response or "",
                                 comment or "") if (p or "").strip()]
    return " ".join(" ".join(" ".join(parts).split()).split())


def source_hash(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()


def model_files_present() -> bool:
    """Веса в локальном HF-кэше (без загрузки)."""
    import glob as _glob
    import os as _os
    base = (_os.environ.get("HF_HOME") or "").strip()
    if base:
        roots = [base]
    else:
        hub = (_os.environ.get("HF_HUB_CACHE") or "").strip()
        if hub:
            roots = [hub]
        else:
            home = _os.path.expanduser("~")
            roots = [f"{home}/.cache/huggingface/hub"]
    for root in roots:
        pat = f"{root}/models--google--embeddinggemma-300m/snapshots/*/*.safetensors"
        try:
            if _glob.glob(pat):
                return True
        except Exception:
            pass
    return False


def _load_model():
    """Ленивая загрузка (нативный класс, БЕЗ trust_remote_code)."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            import torch
        except Exception:
            raise EmbeddingUnavailableError(
                "Нет torch: для эмбеддингов нужен Python-рантайм "
                "(pip install torch transformers).") from None
        try:
            from transformers import AutoModel, AutoTokenizer
        except Exception:
            raise EmbeddingUnavailableError(
                "Нет transformers: pip install transformers.") from None
        if not model_files_present():
            raise EmbeddingUnavailableError(
                "Нет весов google/embeddinggemma-300m: скачай в Настройках "
                "(нужны принятая лицензия и hf login).")
        try:
            tok = AutoTokenizer.from_pretrained(MODEL_NAME)
            net = AutoModel.from_pretrained(MODEL_NAME)
            net.eval()
            if torch.cuda.is_available():
                net = net.to("cuda")
        except Exception as e:
            raise EmbeddingUnavailableError(f"Модель не загрузилась: {e}") from e
        dim = int(getattr(getattr(net, "config", None), "hidden_size", 0) or 0)
        if dim and dim != DIMENSIONS:
            logger.warning("model dim %s != %s", dim, DIMENSIONS)
        _MODEL = (tok, net)
        return _MODEL


def encode_texts(texts: list) -> np.ndarray:
    """Батч текстов -> L2-нормированные векторы (np.float32)."""
    tok, net = _load_model()
    import torch
    dev = next(net.parameters()).device
    out = []
    with torch.no_grad():
        for s in range(0, max(1, len(texts)), 16):
            enc = tok(list(texts[s:s + 16]), padding=True, truncation=True,
                      max_length=2048, return_tensors="pt")
            enc = {k: v.to(dev) for k, v in enc.items()}
            hid = net(**enc).last_hidden_state.float()
            mask = enc["attention_mask"].unsqueeze(-1).float()
            pooled = (hid * mask).sum(1) / mask.sum(1).clamp(min=1e-6)
            pooled = pooled / pooled.norm(dim=1, keepdim=True).clamp(min=1e-9)
            out.append(pooled.cpu().numpy().astype("float32"))
    import numpy as _np
    return _np.concatenate(out, axis=0) if out else _np.zeros((0, DIMENSIONS),
                                                             dtype="float32")


def _case_texts(project_path: str, case_ids: list) -> dict:
    """{case_id: нормализованный текст} (кейс + комментарий разметки)."""
    out = {}
    ids = list(dict.fromkeys(int(c) for c in (case_ids or [])))
    if not ids:
        return out
    with db(project_path) as conn:
        cur = conn.cursor()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            for r in cur.execute(f"""
                    SELECT c.case_id, c.primary_text, c.response_text,
                           a.comment
                    FROM cases c LEFT JOIN annotations a
                        ON a.case_id = c.case_id
                    WHERE c.case_id IN ({ph})
                """, chunk).fetchall():
                out[r["case_id"]] = build_text(r["primary_text"],
                                               r["response_text"], r["comment"])
    return out


def store_vector(project_path: str, case_id: int, vector,
                 source_hash: str) -> bool:
    """Сохранить вектор; True — записан, False — такой уже есть."""
    import numpy as _np
    vec = _np.asarray(vector, dtype="float32").ravel()
    if vec.shape[0] != DIMENSIONS:
        raise ValueError(f"Плохая размерность: {vec.shape[0]}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("""
            SELECT embedding_id, source_hash FROM case_embeddings
            WHERE case_id=? AND model_name=? AND model_version=?
              AND is_active=1
        """, (case_id, MODEL_NAME, MODEL_VERSION)).fetchone()
        if row and (row["source_hash"] or "") == (source_hash or ""):
            return False
        cur.execute("""
            UPDATE case_embeddings SET is_active=0, updated_at=?
            WHERE case_id=? AND model_name=?
        """, (now, case_id, MODEL_NAME))
        cur.execute("""
            INSERT INTO case_embeddings
                (case_id, model_name, model_version, source_hash,
                 dimensions, embedding_data, created_at, updated_at, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (case_id, MODEL_NAME, MODEL_VERSION, source_hash or "",
              DIMENSIONS, vec.tobytes(), now, now))
    return True


def load_vectors(project_path: str, case_ids: list) -> dict:
    """{case_id: np-вектор} только активные текущей модели."""
    import numpy as _np
    ids = list(dict.fromkeys(int(c) for c in (case_ids or [])))
    out = {}
    if not ids:
        return out
    with db(project_path) as conn:
        cur = conn.cursor()
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            for r in cur.execute(f"""
                    SELECT case_id, embedding_data, dimensions
                    FROM case_embeddings
                    WHERE case_id IN ({ph}) AND model_name=?
                      AND model_version=? AND is_active=1
                """, (*chunk, MODEL_NAME, MODEL_VERSION)).fetchall():
                try:
                    v = _np.frombuffer(r["embedding_data"],
                                       dtype="float32").copy()
                    if v.shape[0] == DIMENSIONS and int(r["dimensions"]) == DIMENSIONS:
                        out[r["case_id"]] = v
                except Exception:
                    logger.warning("broken embedding case %s", r["case_id"])
    return out


def indexed_count(project_path: str) -> int:
    with db(project_path) as conn:
        row = conn.execute("""
            SELECT COUNT(*) AS c FROM case_embeddings
            WHERE model_name=? AND model_version=? AND is_active=1
        """, (MODEL_NAME, MODEL_VERSION)).fetchone()
    return int(row["c"] or 0) if row else 0


def stale_ids(project_path: str, case_ids: list) -> list:
    """Кейсы без актуального вектора (нет / текст сменился / битый)."""
    texts = _case_texts(project_path, case_ids)
    have = load_vectors(project_path, list(texts))
    out = []
    for cid, text in texts.items():
        vec = have.get(cid)
        if vec is None:
            out.append(cid)
            continue
        with db(project_path) as conn:
            row = conn.execute("""
                SELECT source_hash FROM case_embeddings
                WHERE case_id=? AND model_name=? AND model_version=?
                  AND is_active=1
            """, (cid, MODEL_NAME, MODEL_VERSION)).fetchone()
        if not row or (row["source_hash"] or "") != source_hash(text):
            out.append(cid)
    return out


def ensure_indexed(project_path: str, case_ids: list,
                   progress_callback=None, cancel_event=None) -> dict:
    """Доиндексировать недостающее. Тяжёлое — звать из фона."""
    ids = list(dict.fromkeys(int(c) for c in (case_ids or [])))
    texts = _case_texts(project_path, ids)
    missing = [c for c in ids if c in texts and c not in load_vectors(
        project_path, [c])]
    # hash-compare только для имеющихся текстов (дешевле, чем векторы)
    todo = []
    if missing:
        have_hash = {}
        with db(project_path) as conn:
            cur = conn.cursor()
            for i in range(0, len(missing), 500):
                chunk = missing[i:i + 500]
                ph = ",".join(["?"] * len(chunk))
                for r in cur.execute(f"""
                        SELECT case_id, source_hash FROM case_embeddings
                        WHERE case_id IN ({ph}) AND model_name=?
                          AND model_version=? AND is_active=1
                    """, (*chunk, MODEL_NAME, MODEL_VERSION)).fetchall():
                    have_hash[r["case_id"]] = r["source_hash"] or ""
        for cid in missing:
            if have_hash.get(cid, None) != source_hash(texts[cid]):
                todo.append(cid)
    done, failed, n = 0, 0, len(todo)
    for s in range(0, n, 16):
        if cancel_event is not None and cancel_event.is_set():
            raise _cancelled()
        chunk = todo[s:s + 16]
        try:
            vecs = encode_texts([texts[c] for c in chunk])
        except EmbeddingUnavailableError:
            raise
        except Exception as e:
            logger.warning("encode chunk failed: %s", e)
            failed += len(chunk)
            continue
        for cid, vec in zip(chunk, vecs, strict=True):
            try:
                store_vector(project_path, cid, vec, source_hash(texts[cid]))
                done += 1
            except Exception as e:
                logger.warning("store %s failed: %s", cid, e)
                failed += 1
        if progress_callback is not None:
            try:
                progress_callback(done + failed, n)
            except Exception:
                pass
    return {"done": done, "failed": failed, "total": n}


def _cancelled():
    try:
        from workers import Cancelled
        return Cancelled("Прервано пользователем")
    except Exception:
        return Exception("Прервано пользователем")


def _scope_ids(project_path: str, scope: str, file_id: int | None) -> list | None:
    """Область -> case_ids (как similarity_service, без цикла импорта)."""
    from similarity_service import _scope_case_ids as _sc
    with db(project_path) as conn:
        return _sc(conn.cursor(), scope, file_id)


def _enrich(project_path: str, scored: list) -> list:
    """(case_id, score) -> строки как у TF-IDF (id/статус/сниппет)."""
    out = []
    ids = [c for c, _ in scored]
    if not ids:
        return out
    with db(project_path) as conn:
        cur = conn.cursor()
        info = {}
        for i in range(0, len(ids), 500):
            chunk = ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            for r in cur.execute(f"""
                    SELECT c.case_id, c.source_id, c.primary_text,
                           COALESCE(a.status, 'unreviewed') AS st
                    FROM cases c LEFT JOIN annotations a
                        ON a.case_id = c.case_id
                    WHERE c.case_id IN ({ph})
                """, chunk).fetchall():
                info[r["case_id"]] = r
    for cid, score in scored:
        r = info.get(cid)
        if r is None:
            continue
        st = r["st"] or "unreviewed"
        out.append({"case_id": cid,
                    "source_id": r["source_id"],
                    "score": round(float(score), 4),
                    "status": st,
                    "reviewed": st != "unreviewed",
                    "snippet": (r["primary_text"] or "")[:160]})
    return out


def find_similar_embedding(project_path: str, case_id: int,
                           min_score: float = 0.6, scope: str = "file",
                           top_n: int = 10) -> dict:
    """Похожие через эмбеддинги. Формат 1-в-1 как TF-IDF."""
    if scope not in ("file", "project", "golden", "archive"):
        raise ValueError(f"Плохая область: {scope!r}")
    if not 0 <= min_score <= 1:
        raise ValueError("min_score: 0..1")
    import numpy as _np
    with db(project_path) as conn:
        qrow = conn.cursor().execute(
            "SELECT case_id, file_id FROM cases WHERE case_id=?",
            (case_id,)).fetchone()
        if not qrow:
            raise ValueError("Кейс не найден")
    ids = _scope_ids(project_path, scope, qrow["file_id"])
    if ids is None:
        with db(project_path) as conn:
            ids = [r["case_id"] for r in conn.cursor().execute(
                "SELECT case_id FROM cases").fetchall()]
    texts = _case_texts(project_path, [case_id])
    if not texts.get(case_id, "").strip():
        return {"case_id": case_id, "total": 0, "results": [],
                "indexed": 0, "backend": "embedding"}
    qvec = encode_texts([texts[case_id]])[0]
    store_vector(project_path, case_id, qvec, source_hash(texts[case_id]))
    vecs = load_vectors(project_path, ids)
    if case_id in vecs:
        del vecs[case_id]
    missing = [c for c in ids if c != case_id and c not in vecs][:2000]
    scored = [(float(_np.dot(qvec, v)), c) for c, v in vecs.items()]
    scored.sort(reverse=True)
    hits = [(c, s) for s, c in scored if s >= min_score][:max(1, top_n)]
    return {"case_id": case_id, "total": len(hits),
            "results": _enrich(project_path, hits),
            "indexed": len(vecs) + 1,
            "scope_total": len(ids),
            "missing": missing,
            "backend": "embedding"}


def find_duplicates_embedding(project_path: str, file_id: int | None = None,
                              threshold: float = 0.9, limit: int = 200,
                              progress_callback=None,
                              cancel_event=None) -> dict:
    """Пары дублей через эмбеддинги. Формат как TF-IDF."""
    import numpy as _np
    with db(project_path) as conn:
        cur = conn.cursor()
        if file_id:
            ids = [r["case_id"] for r in cur.execute(
                "SELECT case_id FROM cases WHERE file_id=?", (file_id,))]
        else:
            ids = [r["case_id"] for r in cur.execute("SELECT case_id FROM cases")]
    if len(ids) > 5000:
        raise ValueError("Слишком много кейсов для попарного сравнения "
                         f"({len(ids)}): сузь область до файла")
    vecs = load_vectors(project_path, ids)
    missing = [c for c in ids if c not in vecs]
    if missing:
        raise EmbeddingUnavailableError(
            f"Не проиндексировано кейсов: {len(missing)} — "
            "запусти переиндексацию в Настройках.")
    order, mat = list(vecs), _np.stack([vecs[c] for c in vecs])
    pairs = []
    n = len(order)
    for i in range(n):
        if cancel_event is not None and cancel_event.is_set():
            raise _cancelled()
        sims = mat[i + 1:] @ mat[i]
        for k, s in enumerate(sims):
            if float(s) >= threshold:
                pairs.append({"case_a": order[i], "case_b": order[i + 1 + k],
                              "score": round(float(s), 4)})
        if progress_callback and (i + 1) % 100 == 0:
            try:
                progress_callback(i + 1, n)
            except Exception:
                pass
    pairs.sort(key=lambda p: -p["score"])
    return {"total": len(pairs), "pairs": pairs[:limit],
            "truncated": len(pairs) > limit, "backend": "embedding"}
