"""Массовые операции (ТЗ §5-7): статус/теги/комментарий + history + отмена."""
import json
import logging
from constants import STATUSES
from database import db, utcnow

logger = logging.getLogger(__name__)

_BULK_INSERT = (
    "INSERT INTO bulk_operations (op_type, params_json, case_count, created_at) "
    "VALUES (?, ?, ?, ?)"
)
_HISTORY_INSERT = (
    "INSERT INTO history (case_id, event_type, field_name, old_value, new_value, "
    "created_at, operation_id) VALUES (?, ?, ?, ?, ?, ?, ?)"
)
_ITEMS_INSERT = (
    "INSERT INTO bulk_operation_items "
    "(operation_id, case_id, field_name, old_value, new_value) "
    "VALUES (?, ?, ?, ?, ?)"
)


def _chunked(ids: list, size: int = 500):
    for i in range(0, len(ids), size):
        yield ids[i:i + size]


def bulk_set_status(project_path: str, case_ids: list, status: str) -> int:
    """Установить статус (или 'unreviewed' для сброса). Возвращает число обработанных."""
    if status not in STATUSES:
        raise ValueError(f"Неизвестный статус: {status!r}")
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    if not case_ids:
        return 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("set_status", json.dumps({"status": status}, ensure_ascii=False),
             len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _chunked(case_ids):
            ph = ",".join(["?"] * len(chunk))
            old = {r["case_id"]: r["status"] for r in cur.execute(
                f"SELECT case_id, status FROM annotations WHERE case_id IN ({ph})", chunk)}
            for cid in chunk:
                old_status = old.get(cid, "unreviewed")
                if old_status == status:
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, status, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                """, (cid, status, now, status, now))
                cur.execute(_HISTORY_INSERT,
                            (cid, "status_changed", "status", old_status, status, now, op_id))
                cur.execute(
                    _ITEMS_INSERT, (op_id, cid, "status", old_status, status))
                done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    logger.info("bulk set_status=%s done=%s/%s op=%s",
                status, done, len(case_ids), op_id)
    return done


def bulk_add_tag(project_path: str, case_ids: list, tag_id: int) -> int:
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    if not case_ids:
        return 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("add_tag", json.dumps({"tag_id": tag_id}), len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _chunked(case_ids):
            for cid in chunk:
                cur.execute(
                    "INSERT OR IGNORE INTO case_tags "
                    "(case_id, tag_id, created_at) VALUES (?, ?, ?)",
                    (cid, tag_id, now),
                )
                if cur.rowcount > 0:
                    cur.execute(_HISTORY_INSERT,
                                (cid, "tag_added", "tag", None, str(tag_id), now, op_id))
                    cur.execute(
                        _ITEMS_INSERT, (op_id, cid, "tag_added", None, str(tag_id)))
                    done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    return done


def bulk_set_comment(project_path: str, case_ids: list, text: str, mode: str = "replace") -> int:
    """mode: replace | append | clear."""
    if mode not in ("replace", "append", "clear"):
        raise ValueError(f"Bad mode: {mode!r}")
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    if not case_ids:
        return 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("set_comment", json.dumps({"mode": mode, "text": text}, ensure_ascii=False),
             len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _chunked(case_ids):
            ph = ",".join(["?"] * len(chunk))
            old = {r["case_id"]: (r["comment"] or "") for r in cur.execute(
                f"SELECT case_id, comment FROM annotations WHERE case_id IN ({ph})", chunk)}
            for cid in chunk:
                prev = old.get(cid, "")
                if mode == "clear":
                    new = ""
                elif mode == "append":
                    new = (prev + "\n" + text).strip() if prev else text
                else:
                    new = text
                if new == prev:
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, status, comment, updated_at)
                    VALUES (?, 'unreviewed', ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                """, (cid, new or None, now, new or None, now))
                cur.execute(_HISTORY_INSERT,
                            (cid, "comment_changed", "comment", prev, new, now, op_id))
                cur.execute(
                    _ITEMS_INSERT, (op_id, cid, "comment", prev, new))
                done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    return done


def undo_bulk_operation(project_path: str, operation_id: int) -> int:
    """Откат массовой операции по сохранённым old_value. Возвращает число откатов."""
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        row = cur.execute(
            "SELECT operation_id, undone FROM bulk_operations WHERE operation_id=?", (operation_id,)
        ).fetchone()
        if not row:
            raise ValueError(f"Операция #{operation_id} не найдена")
        if row["undone"]:
            return 0
        items = cur.execute(
            "SELECT case_id, field_name, old_value, new_value "
            "FROM bulk_operation_items WHERE operation_id=?",
            (operation_id,),
        ).fetchall()
        done = 0
        for it in items:
            cid = it["case_id"]
            field, old, _new = it["field_name"], it["old_value"], it["new_value"]
            if field == "status":
                cur.execute("""
                    INSERT INTO annotations (case_id, status, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                """, (cid, old or "unreviewed", now, old or "unreviewed", now))
            elif field == "comment":
                cur.execute("""
                    INSERT INTO annotations (case_id, comment, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                """, (cid, old or None, now, old or None, now))
            elif field == "tag_added":
                # new_value хранит tag_id строкой
                cur.execute("DELETE FROM case_tags WHERE case_id=? AND tag_id=?",
                            (cid, int(_new)))
            else:
                continue
            cur.execute(_HISTORY_INSERT,
                        (cid, "bulk_undone", field, _new, old, now, operation_id))
            done += 1
        cur.execute("UPDATE bulk_operations SET undone=1 WHERE operation_id=?",
                    (operation_id,))
    logger.info("undo bulk op=%s done=%s", operation_id, done)
    return done
