"""Контроль качества разметки: противоречия себе и QC-выборка.

Противоречие — пара похожих кейсов (TF-IDF) с противоположными вердиктами
по base-семантике (good vs bad). QC-выборка — случайные N размеченных
кейсов на перепроверку (seed — воспроизводимость).
"""
import logging
import random

logger = logging.getLogger(__name__)


def find_conflicts(project_path: str, file_id=None, threshold: float = 0.4,
                   limit: int = 200, progress_callback=None,
                   cancel_event=None) -> dict:
    """Пары [case_a, case_b, score, статусы] с good-против-bad.

    O(n²) через find_duplicates: файлы > 3000 кейсов отклоняются там же.
    """
    from review_profile_service import code_to_base
    from similarity_service import find_duplicates
    try:
        threshold = float(threshold)
    except (TypeError, ValueError):
        raise ValueError("threshold: 0..1") from None
    if not 0 <= threshold <= 1:
        raise ValueError("threshold: 0..1")
    limit = max(1, min(int(limit), 1000))
    dup = find_duplicates(project_path, file_id=file_id, threshold=threshold,
                          limit=2000, progress_callback=progress_callback,
                          cancel_event=cancel_event)
    pairs = dup.get("pairs", [])
    if not pairs:
        return {"total": 0, "pairs": [], "truncated": False}
    mapping = code_to_base(project_path)
    ids = list({p["case_a"] for p in pairs} | {p["case_b"] for p in pairs})
    info = {}
    from database import db
    with db(project_path) as conn:
        ph = ",".join(["?"] * len(ids))
        for r in conn.execute(f"""
                SELECT c.case_id, c.source_id, c.primary_text,
                       COALESCE(a.status, 'unreviewed') AS status
                FROM cases c
                LEFT JOIN annotations a ON a.case_id = c.case_id
                WHERE c.case_id IN ({ph})""", ids).fetchall():
            info[r["case_id"]] = dict(r)
    out = []
    for p in pairs:
        a, b = info.get(p["case_a"]), info.get(p["case_b"])
        if not a or not b:
            continue
        ba = mapping.get(a["status"], a["status"])
        bb = mapping.get(b["status"], b["status"])
        if {ba, bb} != {"good", "bad"}:
            continue
        out.append({"case_a": p["case_a"], "case_b": p["case_b"],
                    "score": p["score"],
                    "source_a": a["source_id"] or f"case:{a['case_id']}",
                    "source_b": b["source_id"] or f"case:{b['case_id']}",
                    "status_a": a["status"], "status_b": b["status"],
                    "text_a": (a["primary_text"] or "")[:80],
                    "text_b": (b["primary_text"] or "")[:80]})
    return {"total": len(out), "pairs": out[:limit],
            "truncated": len(out) > limit}


def qc_sample(project_path: str, file_id=None, n: int = 20,
              seed: int | None = None) -> dict:
    """Случайные N размеченных кейсов. Возвращает и seed (повторимость)."""
    from review_profile_service import code_to_base
    try:
        n = int(n)
    except (TypeError, ValueError):
        raise ValueError("n: 1..500") from None
    if not 1 <= n <= 500:
        raise ValueError("n: 1..500")
    eff = seed if seed is not None else random.randint(0, 999999)
    mapping = code_to_base(project_path)
    unrev = ["unreviewed"] + [c for c, b in mapping.items()
                              if b == "unreviewed" and c != "unreviewed"]
    ph = ",".join(["?"] * len(unrev))
    cond = "AND c.file_id = ?" if file_id else ""
    params: list = list(unrev)
    if file_id:
        params.append(file_id)
    from database import db
    with db(project_path) as conn:
        rows = conn.execute(f"""
            SELECT c.case_id, c.source_id,
                   COALESCE(a.status, 'unreviewed') AS status
            FROM cases c
            JOIN files f ON f.file_id = c.file_id
            JOIN annotations a ON a.case_id = c.case_id
            WHERE COALESCE(a.status, 'unreviewed') NOT IN ({ph}) {cond}
        """, params).fetchall()
    ids = sorted(r["case_id"] for r in rows)
    by_id = {r["case_id"]: dict(r) for r in rows}
    picked = random.Random(eff).sample(ids, min(n, len(ids)))
    return {"total_reviewed": len(ids), "requested": n, "seed": eff,
            "sample": [by_id[c] for c in picked]}
