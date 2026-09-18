"""Прогоны модели и сравнение ответов (ТЗ §45-48, §51-53).

Model Run = ответы одной версии модели (/оператора/эталона) по ключам кейсов.
Сопоставление с проектом — по stable_key: source_id в первую очередь,
иначе нормализованный текст промпта (предупреждаем, надёжность ниже, §53).
Absolute quality живёт в annotations.status (не дублируем); здесь храним
только pairwise-предпочтения A vs B (§48: не смешивать).
"""
import hashlib
import json
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

VERDICTS = ("a_better", "b_better", "tie", "unknown")
VERDICT_NAMES = {"a_better": "A лучше", "b_better": "B лучше",
                 "tie": "Одинаково", "unknown": "Нельзя определить"}


def _norm(text: str | None) -> str:
    import re
    import unicodedata
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    return re.sub(r"\s+", " ", text)


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(_norm(prompt).encode("utf-8")).hexdigest()


def create_run(project_path: str, name: str, model_name: str,
               model_version: str = "", prompt_version: str = "",
               system_prompt_version: str = "", description: str = "") -> int:
    name = (name or "").strip()
    if not name or len(name) > 128:
        raise ValueError("Название 1–128 символов")
    model_name = (model_name or "").strip()
    if not model_name:
        raise ValueError("Укажи модель (или operator / reference)")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO model_runs
                    (name, model_name, model_version, prompt_version,
                     system_prompt_version, description, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, model_name, model_version, prompt_version,
                  system_prompt_version, description, now))
        except Exception as e:
            raise ValueError("Прогон с таким именем уже есть") from e
        return cur.lastrowid


def list_runs(project_path: str) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT r.run_id, r.name, r.model_name, r.model_version,
                   r.prompt_version, r.system_prompt_version, r.source_file,
                   r.description, r.created_at,
                   COUNT(a.stable_key) AS answers
            FROM model_runs r
            LEFT JOIN run_answers a ON a.run_id = r.run_id
            GROUP BY r.run_id
            ORDER BY r.created_at ASC, r.run_id ASC
        """).fetchall()
        return [dict(x) for x in rows]


def get_run(project_path: str, run_id: int) -> dict | None:
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT * FROM model_runs WHERE run_id=?", (run_id,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["answers"] = conn.cursor().execute(
            "SELECT COUNT(*) AS c FROM run_answers WHERE run_id=?",
            (run_id,)).fetchone()["c"]
        return d


def delete_run(project_path: str, run_id: int) -> None:
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM model_runs WHERE run_id=?", (run_id,))
        if cur.rowcount == 0:
            raise ValueError("Прогон не найден")


def _base_index(cursor, need_text: bool = True) -> tuple:
    """({src_key: case_id}, {norm_primary: [case_id]}).

    need_text=False — без текстового индекса (когда у всех строк прогона
    есть source_id: primary_text даже не читаем, экономим RAM на 100k+).
    """
    by_src: dict = {}
    by_text: dict = {}
    cols = "case_id, source_id" + (", primary_text" if need_text else "")
    for r in cursor.execute(f"SELECT {cols} FROM cases").fetchall():
        sid = (r["source_id"] or "").strip()
        if sid:
            by_src.setdefault("src:" + sid, r["case_id"])
        if need_text:
            norm = _norm(r["primary_text"])
            if norm:
                by_text.setdefault(norm, []).append(r["case_id"])
    return by_src, by_text


def import_run_rows(project_path: str, run_id: int, rows: list,
                    progress_callback=None, cancel_event=None) -> dict:
    """Сохраняет ответы прогона. Строка: {answer, source_id?, prompt?,
    product?, metadata?}.

    Возвращает {total, matched, new, dups, no_key}. dups — повторы ключа
    внутри файла (взят первый). no_key — строки без ID и без промпта
    (сопоставить нельзя, только просмотр).
    """
    from workers import Cancelled
    now = utcnow()
    total = matched = new = dups = no_key = 0
    with db(project_path) as conn:
        cur = conn.cursor()
        if not cur.execute("SELECT 1 FROM model_runs WHERE run_id=?",
                           (run_id,)).fetchone():
            raise ValueError("Прогон не найден")
        by_src, by_text = _base_index(
            cur, need_text=any(not str(row.get("source_id") or "").strip()
                               for row in rows if isinstance(row, dict)))
        seen: set = set()
        batch: list = []
        total = len(rows)

        def flush():
            nonlocal matched, new
            if not batch:
                return
            for stable_key, case_id, answer, product, meta, prompt in batch:
                cur.execute("""
                    INSERT OR IGNORE INTO run_answers
                        (run_id, stable_key, case_id, answer_text,
                         product, metadata_json, prompt_text, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """, (run_id, stable_key, case_id, answer, product, meta, prompt, now))
                if cur.rowcount > 0:
                    if case_id is not None:
                        matched += 1
                    else:
                        new += 1
            batch.clear()

        for i, row in enumerate(rows):
            if cancel_event is not None and cancel_event.is_set():
                raise Cancelled(f"Прервано пользователем: строк {i} из {total}")
            if not isinstance(row, dict):
                continue
            answer = row.get("answer")
            answer = str(answer) if answer not in (None, "") else None
            sid = str(row.get("source_id") or "").strip()
            prompt = str(row.get("prompt") or "")
            product = str(row.get("product") or "").strip()
            meta = row.get("metadata")
            meta_json = None
            if isinstance(meta, dict) and meta:
                clean = {str(k): str(v) for k, v in meta.items()
                         if str(v or "").strip()}
                if clean:
                    try:
                        meta_json = json.dumps(clean, ensure_ascii=False)
                    except (TypeError, ValueError):
                        meta_json = None
            if sid:
                key = "src:" + sid
            elif _norm(prompt):
                key = "phash:" + _prompt_hash(prompt)
            else:
                no_key += 1
                continue
            if key in seen:
                dups += 1
                continue
            seen.add(key)
            case_id = None
            if key in by_src:
                case_id = by_src[key]
            elif key.startswith("phash:"):
                cands = by_text.get(_norm(prompt), [])
                if len(cands) == 1:
                    case_id = cands[0]
            batch.append((key, case_id, answer, product, meta_json, prompt or None))
            if len(batch) >= 500:
                flush()
            if progress_callback and (i + 1) % 500 == 0:
                try:
                    progress_callback(i + 1, total)
                except Exception:
                    pass
        flush()
    logger.info("run %s import: total=%s matched=%s new=%s dups=%s no_key=%s",
                run_id, total, matched, new, dups, no_key)
    return {"run_id": run_id, "total": total, "matched": matched, "new": new,
            "dups": dups, "no_key": no_key}


def list_answers(project_path: str, run_id: int) -> list:
    """Ответы прогона с контекстом кейса (промпт/ID/статус)."""
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT a.stable_key, a.case_id, a.answer_text,
                   a.product, a.metadata_json, a.prompt_text,
                   c.source_id, c.primary_text,
                   COALESCE(an.status, 'unreviewed') AS case_status
            FROM run_answers a
            LEFT JOIN cases c ON c.case_id = a.case_id
            LEFT JOIN annotations an ON an.case_id = a.case_id
            WHERE a.run_id = ?
            ORDER BY a.stable_key
        """, (run_id,)).fetchall()
        return [dict(r) for r in rows]


def _case_product(metadata_json: str | None) -> str:
    """Продукт кейса из metadata (для показа в сравнении)."""
    try:
        meta = json.loads(metadata_json or "") or {}
    except (TypeError, ValueError):
        return ""
    if not isinstance(meta, dict):
        return ""
    return str(meta.get("product") or "").strip()


def compare_runs(project_path: str, run_a: int, run_b: int) -> dict:
    """A vs B рядом: ответы по общим ключам + вердикты + absolute кейса.

    counts: both/only_a/only_b/verdicts{...}. Строки отсортированы по ключу.
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        for rid in (run_a, run_b):
            if not cur.execute("SELECT 1 FROM model_runs WHERE run_id=?",
                               (rid,)).fetchone():
                raise ValueError(f"Прогон #{rid} не найден")
            rows_a = {r["stable_key"]: dict(r) for r in cur.execute(
                "SELECT stable_key, case_id, answer_text, product, prompt_text"
                " FROM run_answers WHERE run_id=?",
                (run_a,)).fetchall()}
            rows_b = {r["stable_key"]: dict(r) for r in cur.execute(
                "SELECT stable_key, case_id, answer_text, product, prompt_text"
                " FROM run_answers WHERE run_id=?",
                (run_b,)).fetchall()}
        prefs = {}
        for r in cur.execute("""
                SELECT stable_key, verdict, rank_a, rank_b, comment
                FROM run_preferences WHERE run_a_id=? AND run_b_id=?
            """, (run_a, run_b)).fetchall():
            prefs[r["stable_key"]] = dict(r)
        ctx = {}
        all_case_ids = {r["case_id"] for r in list(rows_a.values())
                        + list(rows_b.values()) if r["case_id"]}
        if all_case_ids:
            ph = ",".join(["?"] * len(all_case_ids))
            for r in cur.execute(f"""
                    SELECT c.case_id, c.source_id, c.primary_text,
                           c.metadata_json,
                           COALESCE(an.status, 'unreviewed') AS case_status
                    FROM cases c
                    LEFT JOIN annotations an ON an.case_id = c.case_id
                    WHERE c.case_id IN ({ph})
                """, list(all_case_ids)).fetchall():
                ctx[r["case_id"]] = dict(r)
    out = []
    counts = {"both": 0, "only_a": 0, "only_b": 0,
              "a_better": 0, "b_better": 0, "tie": 0, "unknown": 0,
              "no_verdict": 0}
    for key in sorted(set(rows_a) | set(rows_b)):
        ra, rb = rows_a.get(key), rows_b.get(key)
        pref = prefs.get(key, {})
        verdict = pref.get("verdict", "unknown")
        case_id = (ra or rb)["case_id"]
        info = ctx.get(case_id, {}) if case_id else {}
        if ra and rb:
            counts["both"] += 1
        elif ra:
            counts["only_a"] += 1
        else:
            counts["only_b"] += 1
        if pref:
            counts[verdict] += 1
        else:
            counts["no_verdict"] += 1
        out.append({
            "stable_key": key,
            "case_id": case_id,
            "source_id": info.get("source_id"),
            "primary_text": info.get("primary_text"),
            "case_status": info.get("case_status", "unreviewed"),
            "product_a": ((ra or {}).get("product") or "").strip(),
            "product_b": ((rb or {}).get("product") or "").strip(),
            "prompt_a": (ra or {}).get("prompt_text") or "",
            "prompt_b": (rb or {}).get("prompt_text") or "",
            "product_case": _case_product(info.get("metadata_json")),
            "answer_a": ra["answer_text"] if ra else None,
            "answer_b": rb["answer_text"] if rb else None,
            "verdict": pref.get("verdict", "unknown") if pref else "unknown",
            "rank_a": pref.get("rank_a"),
            "rank_b": pref.get("rank_b"),
            "comment": pref.get("comment"),
            "has_verdict": bool(pref),
        })
    return {"run_a": run_a, "run_b": run_b, "rows": out, "counts": counts}


def set_preference(project_path: str, run_a: int, run_b: int, stable_key: str,
                   verdict: str, rank_a: int | None = None,
                   rank_b: int | None = None, comment: str | None = None) -> None:
    """Предпочтение A vs B по ключу (verdict + опциональные ранги 1–3)."""
    if verdict not in VERDICTS:
        raise ValueError(f"Плохой вердикт: {verdict!r}")
    for label, rank in (("rank_a", rank_a), ("rank_b", rank_b)):
        if rank is not None and (not isinstance(rank, int) or not 1 <= rank <= 3):
            raise ValueError(f"{label}: 1–3 или пусто")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        case_row = cur.execute("SELECT case_id FROM run_answers "
                               "WHERE run_id=? AND stable_key=?",
                               (run_a, stable_key)).fetchone()
        if not case_row:
            case_row = cur.execute("SELECT case_id FROM run_answers "
                                   "WHERE run_id=? AND stable_key=?",
                                   (run_b, stable_key)).fetchone()
        case_id = case_row["case_id"] if case_row else None
        try:
            cur.execute("""
                INSERT INTO run_preferences
                    (run_a_id, run_b_id, stable_key, case_id, verdict,
                     rank_a, rank_b, comment, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_a_id, run_b_id, stable_key) DO UPDATE SET
                    verdict=?, rank_a=?, rank_b=?, comment=?, updated_at=?
            """, (run_a, run_b, stable_key, case_id, verdict, rank_a, rank_b,
                  comment, now, verdict, rank_a, rank_b, comment, now))
        except Exception as e:
            raise ValueError(f"Не удалось сохранить предпочтение: {e}") from e


def preference_stats(project_path: str, run_a: int, run_b: int) -> dict:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT verdict, COUNT(*) AS c FROM run_preferences
            WHERE run_a_id=? AND run_b_id=? GROUP BY verdict
        """, (run_a, run_b)).fetchall()
        out = {"a_better": 0, "b_better": 0, "tie": 0, "unknown": 0}
        for r in rows:
            out[r["verdict"]] = r["c"]
        out["total"] = sum(out.values())
        return out
