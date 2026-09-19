"""Датасеты и версии (ТЗ §37-44, §61-63): снимок кейсов, freeze, сравнение."""
import hashlib
import json
import logging
import sqlite3
from database import db, utcnow
from migrations import stable_key_for

logger = logging.getLogger(__name__)

DATASET_TYPES = ("working", "golden", "test", "safety", "archive")
VERSION_STATUSES = ("draft", "review", "frozen", "archived")
VERSION_STATUS_NAMES = {"draft": "Черновик", "review": "На ревью",
                        "frozen": "Заморожена", "archived": "В архиве"}

# frozen/archived неизменяемы: разрешены только draft->review->frozen->archived,
# draft->frozen, review->frozen, frozen->archived. Назад из frozen/archived нельзя.
_ALLOWED_TRANSITIONS = {
    None: ("draft",),
    "draft": ("draft", "review", "frozen", "archived"),
    "review": ("review", "frozen", "archived", "draft"),
    "frozen": ("frozen", "archived"),
    "archived": ("archived",),
}


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
                   d.locked,
                   COUNT(v.version_id) AS versions
            FROM datasets d
            LEFT JOIN dataset_versions v ON v.dataset_id = d.dataset_id
            GROUP BY d.dataset_id
            ORDER BY d.name
        """).fetchall()
        return [dict(r) for r in rows]


def _snapshot_hash(case_ids: list) -> str:
    # Legacy-фолбэк для пустых/старых вызовов (только состав).
    return hashlib.sha256(json.dumps(sorted(case_ids)).encode()).hexdigest()


def _snapshot_hash_detailed(entries: list) -> str:
    """Хэш содержимого версии: состав + разметка + тексты.

    entries — [{stable_key, status, comment, error..., tags, text_hash}].
    Старые версии (только ids) хранят legacy-хэш — это нормально.
    """
    norm = sorted(
        (
            e.get("stable_key", ""),
            e.get("status", ""),
            e.get("comment") or "",
            str(e.get("error_category_id") or ""),
            str(e.get("error_subcategory_id") or ""),
            e.get("error_severity") or "",
            e.get("tags_json") or "[]",
            e.get("text_hash") or "",
        )
        for e in entries
    )
    return hashlib.sha256(
        json.dumps(norm, ensure_ascii=False).encode("utf-8")).hexdigest()


def _text_hash(primary: str | None, response: str | None) -> str:
    base = f"{primary or ''}\n{response or ''}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def _dataset_case_columns(cursor) -> set:
    try:
        return {r[1] for r in cursor.execute(
            "PRAGMA table_info(dataset_cases)").fetchall()}
    except Exception:
        return {"version_id", "case_id", "stable_key", "status", "comment"}


def _dataset_locked(cur, dataset_id: int) -> bool:
    """Locked = состав зафиксирован (терпимо к pre-v16 БД без колонки)."""
    try:
        cols = {r[1] for r in cur.execute("PRAGMA table_info(datasets)").fetchall()}
        if "locked" not in cols:
            return False
        row = cur.execute("SELECT locked FROM datasets WHERE dataset_id=?",
                          (dataset_id,)).fetchone()
        return bool(row and row["locked"])
    except Exception:
        return False


def set_dataset_locked(project_path: str, dataset_id: int, locked: bool) -> None:
    """Запереть/отпереть датасет. Разблокировка — явная, через тот же вызов."""
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        if not cur.execute("SELECT 1 FROM datasets WHERE dataset_id=?",
                           (dataset_id,)).fetchone():
            raise ValueError("Датасет не найден")
        cur.execute("UPDATE datasets SET locked=?, updated_at=? WHERE dataset_id=?",
                    (1 if locked else 0, now, dataset_id))


def create_version(project_path: str, dataset_id: int, case_ids: list | None = None,
                   description: str = "", file_id: int | None = None) -> int:
    """Полный снимок разметки: статус/комментарий/ошибка/теги/хэш текста.

    case_ids — явный список; file_id — весь файл; иначе весь проект.
    version_number назначается через MAX+1 с ретраем при гонке (UNIQUE).
    case_count — фактическое число вставленных строк, а не len(case_ids).
    """
    now = utcnow()
    # Состав определяем заранее (вне транзакции вставки версии).
    with db(project_path) as conn:
        cur = conn.cursor()
        ds = cur.execute("SELECT 1 FROM datasets WHERE dataset_id=?",
                         (dataset_id,)).fetchone()
        if not ds:
            raise ValueError("Датасет не найден")
        if _dataset_locked(cur, dataset_id):
            raise ValueError("Датасет заперт (locked): состав зафиксирован")
        if case_ids is None:
            if file_id is not None:
                case_ids = [r["case_id"] for r in cur.execute(
                    "SELECT case_id FROM cases WHERE file_id=?", (file_id,)).fetchall()]
            else:
                case_ids = [r["case_id"] for r in
                            cur.execute("SELECT case_id FROM cases").fetchall()]
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))

    last_err: Exception | None = None
    for _attempt in range(3):
        try:
            with db(project_path) as conn:
                cur = conn.cursor()
                row = cur.execute(
                    "SELECT COALESCE(MAX(version_number), 0) AS m "
                    "FROM dataset_versions WHERE dataset_id=?",
                    (dataset_id,)).fetchone()
                version_number = (row["m"] or 0) + 1
                cur.execute("""
                    INSERT INTO dataset_versions
                        (dataset_id, version_number, description, status, case_count,
                         content_hash, created_at)
                    VALUES (?, ?, ?, 'draft', ?, ?, ?)
                """, (dataset_id, version_number, description, 0,
                      _snapshot_hash(case_ids), now))
                version_id = cur.lastrowid
                cols = _dataset_case_columns(cur)
                full = {"error_category_id", "error_subcategory_id",
                        "error_severity", "tags_json", "text_hash"} <= cols
                entries: list = []
                for i in range(0, len(case_ids), 500):
                    chunk = case_ids[i:i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    rows = cur.execute(f"""
                            SELECT c.case_id, c.source_id, c.content_hash,
                                   c.primary_text, c.response_text,
                                   COALESCE(a.status, 'unreviewed') AS status,
                                   a.comment AS comment
                            FROM cases c LEFT JOIN annotations a
                              ON a.case_id = c.case_id
                            WHERE c.case_id IN ({ph})
                        """, chunk).fetchall()
                    err_map: dict = {}
                    tag_map: dict = {}
                    if full and rows:
                        ids = [r["case_id"] for r in rows]
                        ph2 = ",".join(["?"] * len(ids))
                        for er in cur.execute(
                                f"SELECT case_id, category_id, subcategory_id, severity "
                                f"FROM case_errors WHERE case_id IN ({ph2})",
                                ids).fetchall():
                            err_map[er["case_id"]] = er
                        for tr in cur.execute(
                                f"SELECT case_id, tag_id FROM case_tags "
                                f"WHERE case_id IN ({ph2})", ids).fetchall():
                            tag_map.setdefault(tr["case_id"], []).append(tr["tag_id"])
                    for r in rows:
                        key = stable_key_for(
                            r["source_id"], r["content_hash"], r["case_id"])
                        tags = sorted(tag_map.get(r["case_id"], []))
                        tags_json = json.dumps(tags) if full else None
                        er = err_map.get(r["case_id"])
                        th = _text_hash(r["primary_text"], r["response_text"])
                        entries.append({
                            "stable_key": key, "status": r["status"],
                            "comment": r["comment"],
                            "error_category_id": er["category_id"] if er else None,
                            "error_subcategory_id": er["subcategory_id"] if er else None,
                            "error_severity": er["severity"] if er else None,
                            "tags_json": tags_json, "text_hash": th,
                        })
                        if full:
                            cur.execute("""
                                INSERT OR IGNORE INTO dataset_cases
                                    (version_id, case_id, stable_key, status, comment,
                                     error_category_id, error_subcategory_id,
                                     error_severity, tags_json, text_hash)
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """, (version_id, r["case_id"], key, r["status"],
                                  r["comment"],
                                  er["category_id"] if er else None,
                                  er["subcategory_id"] if er else None,
                                  er["severity"] if er else None,
                                  tags_json, th))
                        else:
                            cur.execute("""
                                INSERT OR IGNORE INTO dataset_cases
                                    (version_id, case_id, stable_key, status, comment)
                                VALUES (?, ?, ?, ?, ?)
                            """, (version_id, r["case_id"], key,
                                  r["status"], r["comment"]))
                actual = cur.execute(
                    "SELECT COUNT(*) AS c FROM dataset_cases WHERE version_id=?",
                    (version_id,)).fetchone()["c"]
                cur.execute("""
                    UPDATE dataset_versions SET case_count=?, content_hash=?
                    WHERE version_id=?
                """, (actual, _snapshot_hash_detailed(entries)
                      if entries else _snapshot_hash(case_ids), version_id))
            logger.info("dataset %s version %s: %s cases",
                        dataset_id, version_number, actual)
            return version_id
        except sqlite3.IntegrityError as e:
            # Гонка version_number (UNIQUE dataset_id+version_number) — ретрай.
            if "dataset_versions" in str(e).lower() or "unique" in str(e).lower():
                last_err = e
                continue
            raise
    raise ValueError(
        "Не удалось создать версию (гонка номеров, попробуйте ещё раз)"
    ) from last_err


def list_versions(project_path: str, dataset_id: int) -> list:
    with db(project_path) as conn:
        rows = conn.cursor().execute("""
            SELECT version_id, version_number, description, status, case_count,
                   content_hash, created_at, frozen_at
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
        row = cur.execute("SELECT status FROM dataset_versions WHERE version_id=?",
                          (version_id,)).fetchone()
        if not row:
            raise ValueError("Версия не найдена")
        current = row["status"]
        allowed = _ALLOWED_TRANSITIONS.get(current, ())
        if status not in allowed and status != current:
            if current in ("frozen", "archived"):
                raise ValueError(
                    "Замороженная/архивная версия неизменяема — создайте новую версию")
            raise ValueError(f"Переход {current} → {status} запрещён")
        if status == "frozen":
            cur.execute("UPDATE dataset_versions SET status='frozen', frozen_at=? "
                        "WHERE version_id=?", (now, version_id))
        else:
            cur.execute("UPDATE dataset_versions SET status=? WHERE version_id=?",
                        (status, version_id))


def freeze_version(project_path: str, version_id: int) -> None:
    """Freeze: версия становится неизменяемой (снимок и так immutable).

    Freeze необратим — перед ним делаем страховой бэкап проекта.
    """
    try:
        from backup_service import create_backup
        create_backup(project_path)
    except Exception as e:
        logger.warning("backup before freeze failed: %s", e)
    set_version_status(project_path, version_id, "frozen")


def delete_version(project_path: str, version_id: int) -> None:
    """Удалить версию (снимок). Датасет остаётся; frozen — тоже можно, явно."""
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute("SELECT status, dataset_id FROM dataset_versions WHERE version_id=?",
                          (version_id,)).fetchone()
        if not row:
            raise ValueError("Версия не найдена")
        if _dataset_locked(cur, row["dataset_id"]):
            raise ValueError("Датасет заперт (locked): версии удалять нельзя")
        cur.execute("DELETE FROM dataset_versions WHERE version_id=?", (version_id,))


def _version_map(cursor, version_id: int) -> dict:
    """stable_key -> список [dict(case_id, status, comment, error..., tags, text_hash)]."""
    cols = _dataset_case_columns(cursor)
    want = ["case_id", "stable_key", "status", "comment"]
    for c in ("error_category_id", "error_subcategory_id", "error_severity",
              "tags_json", "text_hash"):
        if c in cols:
            want.append(c)
    rows = cursor.execute(f"SELECT {', '.join(want)} FROM dataset_cases "
                          "WHERE version_id=?", (version_id,)).fetchall()
    out: dict = {}
    for r in rows:
        d = dict(r)
        key = d.get("stable_key") or f"case:{d['case_id']}"
        out.setdefault(key, []).append(d)
    return out


def _row_changed(a: dict, b: dict) -> list:
    """Какие поля разметки изменились.

    error/tags: NULL = «нет ошибки/тегов» (новые снимки всегда пишут явно,
    старые pre-v9 тоже NULL — сравнение честное: None vs значение = change).
    text_hash: NULL старых снимков = неизвестно — пропускаем, чтобы не врать.
    status/comment сравниваются всегда (были с v7).
    """
    changes: list = []
    if (a.get("status") or "") != (b.get("status") or ""):
        changes.append("status")
    if (a.get("comment") or "") != (b.get("comment") or ""):
        changes.append("comment")
    for f in ("error_category_id", "error_subcategory_id", "error_severity"):
        if str(a.get(f) or "") != str(b.get(f) or ""):
            changes.append("error")
            break
    ta = a.get("tags_json") or "[]"
    tb = b.get("tags_json") or "[]"
    if ta != tb:
        changes.append("tags")
    ha, hb = a.get("text_hash"), b.get("text_hash")
    if ha and hb and ha != hb:
        changes.append("text")
    return changes


def compare_versions(project_path: str, version_a: int, version_b: int) -> dict:
    """A vs B по стабильным ключам (source_id → content_hash).

    added/removed/changed/unchanged — case_id из версии B (для removed — из A).
    conflicted — ключи, задвоенные хотя бы с одной стороны (детали по ним
    не считаются, чтобы не врать).
    changed — изменение status/comment/error/tags/text (см. details[].changes).
    details[].before/after — статусы (совместимость), details[].changes — поля.
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
                               "a_cases": [c["case_id"] for c in rows_a],
                               "b_cases": [c["case_id"] for c in rows_b]})
            continue
        if rows_a and not rows_b:
            removed.append(rows_a[0]["case_id"])
        elif rows_b and not rows_a:
            added.append(rows_b[0]["case_id"])
        else:
            ra, rb = rows_a[0], rows_b[0]
            ch = _row_changed(ra, rb)
            if ch:
                changed.append(rb["case_id"])
                details.append({"case_id": rb["case_id"], "key": key,
                                "before": ra.get("status"), "after": rb.get("status"),
                                "changes": ch})
            else:
                unchanged.append(rb["case_id"])
    return {"added": added, "removed": removed, "changed": changed,
            "unchanged": unchanged, "conflicted": conflicted, "details": details,
            "counts": {"added": len(added), "removed": len(removed),
                       "changed": len(changed), "unchanged": len(unchanged),
                       "conflicted": len(conflicted)}}


def version_agreement(project_path: str, cmp: dict) -> dict:
    """Согласие разметок двух версий: % совпавших статусов по общим ключам.

    Общие ключи = без изменений + изменённые (конфликты задвоенных ID
    исключаются, чтобы не врать). Статусы — по base-семантике.
    """
    from review_profile_service import code_to_base
    mapping = code_to_base(project_path)
    details = (cmp or {}).get("details", []) or []
    matched = len((cmp or {}).get("unchanged", []) or []) + len(details)
    agreed = len((cmp or {}).get("unchanged", []) or [])
    disagreed_keys = []
    for d in details:
        if "status" not in (d.get("changes", []) or []):
            agreed += 1
            continue
        before = mapping.get(d.get("before") or "", d.get("before") or "")
        after = mapping.get(d.get("after") or "", d.get("after") or "")
        if before == after:
            agreed += 1
        else:
            disagreed_keys.append(d.get("key"))
    pct = round(agreed / matched, 4) if matched else None
    ver_changed = []
    for d in details:
        if "status" not in (d.get("changes", []) or []):
            continue
        before = mapping.get(d.get("before") or "", d.get("before") or "")
        after = mapping.get(d.get("after") or "", d.get("after") or "")
        if before != after:
            ver_changed.append(d.get("key"))
    return {"matched": matched, "agreed": agreed, "disagreed": matched - agreed,
            "pct": pct, "disagreed_keys": disagreed_keys,
            "verdict_changed": len(ver_changed),
            "verdict_changed_keys": ver_changed}
