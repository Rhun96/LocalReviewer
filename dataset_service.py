"""Датасеты и версии (ТЗ §37-44, §61-63): снимок кейсов, freeze, сравнение."""
import hashlib
import json
import logging
from database import db, utcnow
from migrations import stable_key_for

logger = logging.getLogger(__name__)

DATASET_TYPES = ("working", "golden", "test", "safety", "archive")
VERSION_STATUSES = ("draft", "review", "frozen", "archived")


def create_dataset(project_path: str, name: str, description: str = "",
                   dataset_type: str = "working") -> int:
    name = (name or "").strip()
    if not name or len(name) > 128:
        raise ValueError("Название 1–128 символов")
    if dataset_type not in DATASET_TYPES:
        raise ValueError(f"Плохой тип: {dataset_type!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO datasets (name, description, dataset_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
            """, (name, description, dataset_type, now, now))
        except Exception as e:
            raise ValueError("Датасет с таким именем уже есть") from e
        return cur.lastrowid


def list_datasets(project_path: str) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT d.dataset_id, d.name, d.description, d.dataset_type,
                   COUNT(v.version_id) AS versions
            FROM datasets d
            LEFT JOIN dataset_versions v ON v.dataset_id = d.dataset_id
            GROUP BY d.dataset_id
            ORDER BY d.name
        """).fetchall()
        return [dict(r) for r in rows]


def _snapshot_hash(case_ids: list) -> str:
    return hashlib.sha256(json.dumps(sorted(case_ids)).encode()).hexdigest()


def create_version(project_path: str, dataset_id: int, case_ids: list | None = None,
                   description: str = "", file_id: int | None = None) -> int:
    """Снимок текущих статусов/комментариев.

    case_ids — явный список; file_id — весь файл; иначе весь проект.
    """
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        ds = cur.execute("SELECT 1 FROM datasets WHERE dataset_id=?",
                         (dataset_id,)).fetchone()
        if not ds:
            raise ValueError("Датасет не найден")
        if case_ids is None:
            if file_id is not None:
                case_ids = [r["case_id"] for r in cur.execute(
                    "SELECT case_id FROM cases WHERE file_id=?", (file_id,)).fetchall()]
            else:
                case_ids = [r["case_id"] for r in
                            cur.execute("SELECT case_id FROM cases").fetchall()]
        case_ids = list(dict.fromkeys(int(c) for c in case_ids))
        row = cur.execute("SELECT COALESCE(MAX(version_number), 0) AS m "
                          "FROM dataset_versions WHERE dataset_id=?",
                          (dataset_id,)).fetchone()
        version_number = (row["m"] or 0) + 1
        cur.execute("""
            INSERT INTO dataset_versions
                (dataset_id, version_number, description, status, case_count,
                 content_hash, created_at)
            VALUES (?, ?, ?, 'draft', ?, ?, ?)
        """, (dataset_id, version_number, description, len(case_ids),
              _snapshot_hash(case_ids), now))
        version_id = cur.lastrowid
        for i in range(0, len(case_ids), 500):
            chunk = case_ids[i:i + 500]
            ph = ",".join(["?"] * len(chunk))
            for r in cur.execute(f"""
                    SELECT c.case_id, c.source_id, c.content_hash,
                           COALESCE(a.status, 'unreviewed') AS status,
                           a.comment AS comment
                    FROM cases c LEFT JOIN annotations a ON a.case_id = c.case_id
                    WHERE c.case_id IN ({ph})
                """, chunk).fetchall():
                key = stable_key_for(r["source_id"], r["content_hash"], r["case_id"])
                cur.execute("""
                    INSERT OR IGNORE INTO dataset_cases
                        (version_id, case_id, stable_key, status, comment)
                    VALUES (?, ?, ?, ?, ?)
                """, (version_id, r["case_id"], key, r["status"], r["comment"]))
    logger.info("dataset %s version %s: %s cases", dataset_id, version_number, len(case_ids))
    return version_id


def list_versions(project_path: str, dataset_id: int) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT version_id, version_number, description, status, case_count,
                   created_at, frozen_at
            FROM dataset_versions
            WHERE dataset_id = ?
            ORDER BY version_number
        """, (dataset_id,)).fetchall()
        return [dict(r) for r in rows]


def set_version_status(project_path: str, version_id: int, status: str) -> None:
    if status not in VERSION_STATUSES:
        raise ValueError(f"Плохой статус: {status!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        if status == "frozen":
            cur.execute("UPDATE dataset_versions SET status='frozen', frozen_at=? "
                        "WHERE version_id=?", (now, version_id))
        else:
            cur.execute("UPDATE dataset_versions SET status=? WHERE version_id=?",
                        (status, version_id))
        if cur.rowcount == 0:
            raise ValueError("Версия не найдена")


def freeze_version(project_path: str, version_id: int) -> None:
    """Freeze: версия становится неизменяемой (снимок и так immutable)."""
    set_version_status(project_path, version_id, "frozen")


def _version_map(cursor, version_id: int) -> dict:
    """stable_key -> список [(case_id, status, comment)]."""
    rows = cursor.execute("SELECT case_id, stable_key, status, comment FROM dataset_cases "
                          "WHERE version_id=?", (version_id,)).fetchall()
    out: dict = {}
    for r in rows:
        key = r["stable_key"] or f"case:{r['case_id']}"
        out.setdefault(key, []).append((r["case_id"], r["status"], r["comment"]))
    return out


def compare_versions(project_path: str, version_a: int, version_b: int) -> dict:
    """A vs B по стабильным ключам (source_id → content_hash).

    added/removed/changed/unchanged — case_id из версии B (для removed — из A).
    conflicted — ключи, задвоенные хотя бы с одной стороны.
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        map_a = _version_map(cur, version_a)
        map_b = _version_map(cur, version_b)
    added, removed, changed, unchanged, conflicted, details = [], [], [], [], [], []
    for key in sorted(set(map_a) | set(map_b)):
        rows_a, rows_b = map_a.get(key, []), map_b.get(key, [])
        if len(rows_a) > 1 or len(rows_b) > 1:
            conflicted.append({"key": key,
                               "a_cases": [c for c, _, _ in rows_a],
                               "b_cases": [c for c, _, _ in rows_b]})
            continue
        if rows_a and not rows_b:
            removed.append(rows_a[0][0])
        elif rows_b and not rows_a:
            added.append(rows_b[0][0])
        else:
            (_ca, sa, _), (_cb, sb, _) = rows_a[0], rows_b[0]
            if sa != sb:
                changed.append(_cb)
                details.append({"case_id": _cb, "key": key, "before": sa, "after": sb})
            else:
                unchanged.append(_cb)
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged, "conflicted": conflicted, "details": details,
            "counts": {"added": len(added), "removed": len(removed),
                       "changed": len(changed), "unchanged": len(unchanged),
                       "conflicted": len(conflicted)}}
