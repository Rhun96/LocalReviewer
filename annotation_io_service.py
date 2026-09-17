"""Обмен только разметкой (ТЗ V2 §15): экспорт + импорт Merge/Update/Preview.

Формат — JSONL, одна строка: id (source_id или case_id), case_id, status,
category/subcategory (КОДЫ таксономии — устойчивы к переименованиям),
severity, comment. Режимы импорта: Preview (только отчёт), Merge (только
пустые поля + новые), Update (перезапись различий). Конфликт молча не
перезаписывается никогда: Preview показывает всё заранее.
"""
import json as _json
import logging
from database import db, utcnow

logger = logging.getLogger(__name__)

ANN_FIELDS = ("status", "category", "subcategory", "severity", "comment")


def export_annotations(project_path: str, output_path: str,
                       file_id=None) -> int:
    """Только разметка. Возвращает число строк."""
    from export_service import _resolve_text_output
    out = _resolve_text_output(output_path, ".jsonl")
    tmp = str(out) + ".part"
    count = 0
    with db(project_path) as conn:
        cur = conn.cursor()
        cond, params = "", []
        if file_id:
            cond, params = " WHERE c.file_id = ?", [file_id]
        cur.execute(f"""
            SELECT c.case_id, c.source_id,
                   COALESCE(a.status, 'unreviewed') AS status,
                   a.comment AS comment,
                   ec.code AS category, es.code AS subcategory,
                   e.severity AS severity
            FROM cases c
            LEFT JOIN annotations a ON a.case_id = c.case_id
            LEFT JOIN case_errors e ON e.case_id = c.case_id
            LEFT JOIN error_categories ec ON ec.category_id = e.category_id
            LEFT JOIN error_categories es ON es.category_id = e.subcategory_id
            {cond}
            ORDER BY c.case_id
        """, params)
        cols = [d[0] for d in cur.description]
        with open(tmp, "w", encoding="utf-8") as fh:
            while True:
                batch = cur.fetchmany(2000)
                if not batch:
                    break
                for r in batch:
                    row = dict(zip(cols, r, strict=True))
                    sid = (row["source_id"] or "").strip()
                    fh.write(_json.dumps({
                        "id": sid or str(row["case_id"]),
                        "case_id": row["case_id"],
                        "status": row["status"],
                        "category": row["category"] or "",
                        "subcategory": row["subcategory"] or "",
                        "severity": row["severity"] or "",
                        "comment": row["comment"] or "",
                    }, ensure_ascii=False) + "\n")
                    count += 1
    from pathlib import Path as _Path
    _Path(tmp).replace(out)
    logger.info("exported %s annotations -> %s", count, out)
    return count


def _resolve_category(cursor, code: str | None):
    """Код -> category_id (пусто -> None). Неизвестный код — ValueError."""
    if not code:
        return None
    row = cursor.execute("SELECT category_id FROM error_categories WHERE code=?",
                         (code,)).fetchone()
    if not row:
        raise ValueError(f"Неизвестная категория: {code!r}")
    return row["category_id"]


def _current_snapshot(cursor, case_id: int) -> dict:
    ann = cursor.execute("SELECT status, comment FROM annotations WHERE case_id=?",
                         (case_id,)).fetchone()
    err = cursor.execute("""
        SELECT ec.code AS category, es.code AS subcategory, e.severity
        FROM case_errors e
        LEFT JOIN error_categories ec ON ec.category_id = e.category_id
        LEFT JOIN error_categories es ON es.category_id = e.subcategory_id
        WHERE e.case_id = ?
    """, (case_id,)).fetchone()
    return {
        "status": ann["status"] if ann else "unreviewed",
        "comment": (ann["comment"] or "") if ann else "",
        "category": err["category"] if err and err["category"] else "",
        "subcategory": err["subcategory"] if err and err["subcategory"] else "",
        "severity": err["severity"] if err and err["severity"] else "",
    }


def preview_import(project_path: str, rows: list) -> dict:
    """Сухой прогон: new/updating/unchanged/not_found/conflicts (+примеры).

    new — кейс без разметки вообще (статус unreviewed, пусто остальное).
    conflict — различие в НЕпустом поле (Merge его не тронет).
    """
    import re as _re
    report = {"total": 0, "new": [], "updating": [], "unchanged": [],
              "not_found": [], "conflicts": [], "errors": []}
    with db(project_path) as conn:
        cur = conn.cursor()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                report["errors"].append({"line": i + 1, "error": "not an object"})
                continue
            report["total"] += 1
            key = str(row.get("id", "") or "").strip()
            hit = None
            if key:
                hit = cur.execute("SELECT case_id FROM cases WHERE source_id=? "
                                  "OR CAST(case_id AS TEXT)=?", (key, key)).fetchone()
            if not hit:
                report["not_found"].append({"id": key or f"строка {i + 1}"})
                continue
            cid = hit["case_id"]
            status = str(row.get("status", "") or "").strip() or "unreviewed"
            if status != "unreviewed" and not _re.match(r"^[a-z][a-z0-9_]{0,31}$",
                                                       status):
                report["errors"].append({"id": key, "error": f"плохой статус {status!r}"})
                continue
            try:
                cat_id = _resolve_category(cur, str(row.get("category", "")
                                                   or "").strip() or None)
                sub_id = _resolve_category(cur, str(row.get("subcategory", "")
                                                   or "").strip() or None)
                if sub_id is not None:
                    sub = cur.execute("SELECT parent_id FROM error_categories "
                                      "WHERE category_id=?", (sub_id,)).fetchone()
                    if not sub or sub["parent_id"] != cat_id:
                        raise ValueError("подкатегория не принадлежит категории")
                sev = str(row.get("severity", "") or "").strip()
                if sev and sev not in ("low", "medium", "high", "critical"):
                    raise ValueError(f"плохой severity {sev!r}")
            except ValueError as e:
                report["errors"].append({"id": key, "error": str(e)})
                continue
            incoming = {"status": status,
                        "comment": str(row.get("comment", "") or ""),
                        "category": str(row.get("category", "") or ""),
                        "subcategory": str(row.get("subcategory", "") or ""),
                        "severity": sev}
            current = _current_snapshot(cur, cid)
            entry = {"id": key, "case_id": cid, "incoming": incoming,
                     "current": current}
            diffs = [f for f in ANN_FIELDS if incoming[f] != current[f]]
            if not diffs:
                report["unchanged"].append(entry)
                continue
            filled = [f for f in diffs if current[f] not in ("", "unreviewed")]
            # new = различий нет в заполненных полях... точнее: кейс чистый
            is_clean = (current["status"] == "unreviewed" and not current["comment"]
                        and not current["category"] and not current["severity"])
            if is_clean:
                report["new"].append(entry)
            elif not filled:
                report["updating"].append(entry)
            else:
                entry["conflict_fields"] = filled
                report["conflicts"].append(entry)
    return report


def apply_import(project_path: str, preview: dict, mode: str) -> dict:
    """Применяет preview: update (всё кроме not_found/errors/unchanged),
    merge (только new + updating). Возвращает {applied, skipped}."""
    if mode not in ("merge", "update"):
        raise ValueError("Режим: merge/update (смотри сначала Preview)")
    targets = list(preview.get("new", [])) + list(preview.get("updating", []))
    if mode == "update":
        targets += preview.get("conflicts", [])
    applied = skipped = 0
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        for entry in targets:
            cid, inc = entry["case_id"], entry["incoming"]
            try:
                cat_id = _resolve_category(cur, inc["category"] or None)
                sub_id = _resolve_category(cur, inc["subcategory"] or None)
            except ValueError:
                skipped += 1
                continue
            before = _current_snapshot(cur, cid)
            if mode == "merge":
                do_status = (before["status"] == "unreviewed"
                             and inc["status"] != "unreviewed")
                do_comment = not before["comment"] and bool(inc["comment"])
                do_err = (not before["category"] and not before["severity"]
                          and (inc["category"] or inc["severity"]))
            else:
                do_status = do_comment = do_err = True
            if do_status and inc["status"] != "unreviewed":
                cur.execute("""
                    INSERT INTO annotations (case_id, status, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                """, (cid, inc["status"], now, inc["status"], now))
            if do_comment and inc["comment"]:
                cur.execute("""
                    INSERT INTO annotations (case_id, comment, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                """, (cid, inc["comment"], now, inc["comment"], now))
            if do_err and (inc["category"] or inc["severity"]):
                cur.execute("""
                    INSERT INTO case_errors (case_id, category_id, subcategory_id,
                                             severity, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET category_id=?, subcategory_id=?,
                        severity=?, updated_at=?
                """, (cid, cat_id, sub_id, inc["severity"] or "medium", now,
                      cat_id, sub_id, inc["severity"] or "medium", now))
            if do_status or do_comment or do_err:
                cur.execute("INSERT INTO history (case_id, event_type, field_name,"
                            " old_value, new_value, created_at) VALUES "
                            "(?, 'annotation_imported', 'annotation', ?, ?, ?)",
                            (cid, mode, f"{before['status']}->{inc['status']}", now))
                applied += 1
            else:
                skipped += 1
    return {"applied": applied, "skipped": skipped,
            "not_found": len(preview.get("not_found", [])),
            "errors": len(preview.get("errors", []))}


def read_annotation_file(file_path: str) -> tuple:
    """Читает JSONL разметки: (rows, errors). Формат строгий, но терпимый."""
    rows, errors = [], []
    with open(file_path, encoding="utf-8-sig") as fh:
        for n, line in enumerate(fh, 1):
            s = line.strip()
            if not s:
                continue
            try:
                item = _json.loads(s)
            except ValueError as e:
                errors.append({"line": n, "error": str(e)})
                continue
            if not isinstance(item, dict) or not str(item.get("id", "")).strip():
                errors.append({"line": n, "error": "нужен объект с полем id"})
                continue
            rows.append(item)
    return rows, errors
