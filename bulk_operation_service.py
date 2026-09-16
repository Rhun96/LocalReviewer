"""Массовые операции (ТЗ §5-7): статус/теги/комментарий/просмотрено + history + отмена."""
import json
import logging
import re
from database import db, utcnow
from workers import Cancelled

logger = logging.getLogger(__name__)
_STATUS_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")

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


def _tracked(ids: list, progress_callback=None, cancel_event=None, size: int = 500):
    """Чанки с прогрессом и отменой (отмена откатывает всю операцию через db)."""
    total = len(ids)
    done = 0
    for i in range(0, total, size):
        _bulk_tick(progress_callback, cancel_event, done, total)
        yield ids[i:i + size]
        done = min(total, i + size)
    _bulk_tick(progress_callback, cancel_event, total, total)


def _bulk_tick(progress_callback, cancel_event, done: int, total: int) -> None:
    """Прогресс по чанкам + отмена. Cancelled откатывает всю операцию (db)."""
    if cancel_event is not None and cancel_event.is_set():
        raise Cancelled(f"Прервано пользователем: обработано {done} из {total}")
    if progress_callback:
        try:
            progress_callback(done, total)
        except Exception:
            pass


def bulk_set_status(project_path: str, case_ids: list, status: str,
                    progress_callback=None, cancel_event=None) -> int:
    """Установить статус (коды из активного профиля + 'unreviewed' для сброса)."""
    if not _STATUS_RE.match(status or ""):
        raise ValueError(f"Плохой код статуса: {status!r}")
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
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
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


def bulk_add_tag(project_path: str, case_ids: list, tag_id: int,
                 progress_callback=None, cancel_event=None) -> int:
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
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
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


def bulk_remove_tag(project_path: str, case_ids: list, tag_id: int,
                    progress_callback=None, cancel_event=None) -> int:
    """Убрать тег у кейсов. Возвращает число обработанных."""
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    if not case_ids:
        return 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("remove_tag", json.dumps({"tag_id": tag_id}), len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
            ph = ",".join(["?"] * len(chunk))
            had = {r["case_id"] for r in cur.execute(
                f"SELECT case_id FROM case_tags WHERE tag_id=? AND case_id IN ({ph})",
                (tag_id, *chunk))}
            for cid in chunk:
                if cid not in had:
                    continue
                cur.execute("DELETE FROM case_tags WHERE case_id=? AND tag_id=?",
                            (cid, tag_id))
                cur.execute(_HISTORY_INSERT,
                            (cid, "tag_removed", "tag", str(tag_id), None, now, op_id))
                cur.execute(
                    _ITEMS_INSERT, (op_id, cid, "tag_removed", str(tag_id), None))
                done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    return done


def bulk_set_tags(project_path: str, case_ids: list, tag_ids: list,
                  progress_callback=None, cancel_event=None) -> int:
    """Заменить набор тегов целиком. old/new — JSON-списки tag_id."""
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    want = sorted({int(t) for t in tag_ids})
    if not case_ids:
        return 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("set_tags", json.dumps({"tag_ids": want}), len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
            ph = ",".join(["?"] * len(chunk))
            cur_map: dict = {}
            for r in cur.execute(
                    f"SELECT case_id, tag_id FROM case_tags WHERE case_id IN ({ph})",
                    chunk).fetchall():
                cur_map.setdefault(r["case_id"], []).append(r["tag_id"])
            for cid in chunk:
                old = sorted(cur_map.get(cid, []))
                if old == want:
                    continue
                cur.execute("DELETE FROM case_tags WHERE case_id=?", (cid,))
                for tid in want:
                    cur.execute("INSERT INTO case_tags (case_id, tag_id, created_at)"
                                " VALUES (?, ?, ?)", (cid, tid, now))
                for tid in sorted(set(want) - set(old)):
                    cur.execute(_HISTORY_INSERT,
                                (cid, "tag_added", "tag", None, str(tid), now, op_id))
                for tid in sorted(set(old) - set(want)):
                    cur.execute(_HISTORY_INSERT,
                                (cid, "tag_removed", "tag", str(tid), None, now, op_id))
                cur.execute(_ITEMS_INSERT, (op_id, cid, "tags",
                                            json.dumps(old), json.dumps(want)))
                done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    return done


def bulk_set_comment(project_path: str, case_ids: list, text: str, mode: str = "replace",
                     progress_callback=None, cancel_event=None) -> int:
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
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
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


def bulk_set_viewed(project_path: str, case_ids: list, viewed: bool = True,
                    progress_callback=None, cancel_event=None) -> int:
    """Отметить просмотренным / снять отметку (ТЗ §5.3, служебные действия)."""
    case_ids = list(dict.fromkeys(int(c) for c in case_ids))
    if not case_ids:
        return 0
    want = 1 if viewed else 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute(
            _BULK_INSERT,
            ("set_viewed", json.dumps({"viewed": want}), len(case_ids), now),
        )
        op_id = cur.lastrowid
        done = 0
        for chunk in _tracked(case_ids, progress_callback, cancel_event):
            ph = ",".join(["?"] * len(chunk))
            old = {r["case_id"]: (r["viewed"] or 0) for r in cur.execute(
                f"SELECT case_id, viewed FROM annotations WHERE case_id IN ({ph})",
                chunk)}
            for cid in chunk:
                if old.get(cid, 0) == want:
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, status, viewed, updated_at)
                    VALUES (?, 'unreviewed', ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET viewed=?, updated_at=?
                """, (cid, want, now, want, now))
                cur.execute(_HISTORY_INSERT,
                            (cid, "viewed_changed", "viewed",
                             str(old.get(cid, 0)), str(want), now, op_id))
                cur.execute(_ITEMS_INSERT,
                            (op_id, cid, "viewed", str(old.get(cid, 0)), str(want)))
                done += 1
        cur.execute("UPDATE bulk_operations SET case_count=? WHERE operation_id=?",
                    (done, op_id))
    return done


def undo_bulk_operation(project_path: str, operation_id: int) -> int:
    """Откат массовой операции по сохранённым old_value. Возвращает число откатов.

    Защита от lost update: если текущее значение уже не равно new_value
    (пользователь правил кейс вручную после bulk), кейс пропускается —
    молча затирать ручную правку нельзя. Пропуски логируются.
    """
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
        skipped = 0
        for it in items:
            cid = it["case_id"]
            field, old, _new = it["field_name"], it["old_value"], it["new_value"]
            if field == "status":
                cur_row = cur.execute(
                    "SELECT status FROM annotations WHERE case_id=?", (cid,)).fetchone()
                cur_val = cur_row["status"] if cur_row else "unreviewed"
                if cur_val != _new:
                    skipped += 1
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, status, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                """, (cid, old or "unreviewed", now, old or "unreviewed", now))
            elif field == "comment":
                cur_row = cur.execute(
                    "SELECT comment FROM annotations WHERE case_id=?", (cid,)).fetchone()
                cur_val = (cur_row["comment"] or "") if cur_row else ""
                if cur_val != (_new or ""):
                    skipped += 1
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, comment, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                """, (cid, old or None, now, old or None, now))
            elif field == "tag_added":
                # new_value хранит tag_id строкой; DELETE идемпотентен.
                cur.execute("DELETE FROM case_tags WHERE case_id=? AND tag_id=?",
                            (cid, int(_new)))
            elif field == "tag_removed":
                # old_value хранит tag_id строкой; возврат — INSERT OR IGNORE.
                cur.execute("INSERT OR IGNORE INTO case_tags (case_id, tag_id, created_at)"
                            " VALUES (?, ?, ?)", (cid, int(old), now))
            elif field == "viewed":
                cur_row = cur.execute(
                    "SELECT viewed FROM annotations WHERE case_id=?", (cid,)).fetchone()
                cur_val = str(cur_row["viewed"] or 0) if cur_row else "0"
                if cur_val != str(_new):
                    skipped += 1
                    continue
                cur.execute("""
                    INSERT INTO annotations (case_id, viewed, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET viewed=?, updated_at=?
                """, (cid, int(old or 0), now, int(old or 0), now))
            elif field == "tags":
                # Замена набора: old/new — JSON-списки. Guard от ручных правок.
                try:
                    want_old = sorted(json.loads(old or "[]"))
                    want_new = sorted(json.loads(_new or "[]"))
                except (ValueError, TypeError):
                    skipped += 1
                    continue
                cur_set = sorted(
                    r["tag_id"] for r in cur.execute(
                        "SELECT tag_id FROM case_tags WHERE case_id=?", (cid,)))
                if cur_set != want_new:
                    skipped += 1
                    continue
                cur.execute("DELETE FROM case_tags WHERE case_id=?", (cid,))
                for tid in want_old:
                    cur.execute("INSERT INTO case_tags (case_id, tag_id, created_at)"
                                " VALUES (?, ?, ?)", (cid, int(tid), now))
            else:
                continue
            cur.execute(_HISTORY_INSERT,
                        (cid, "bulk_undone", field, _new, old, now, operation_id))
            done += 1
        cur.execute("UPDATE bulk_operations SET undone=1 WHERE operation_id=?",
                    (operation_id,))
    if skipped:
        logger.warning("undo bulk op=%s skipped=%s (ручные правки)",
                       operation_id, skipped)
    logger.info("undo bulk op=%s done=%s", operation_id, done)
    return done
