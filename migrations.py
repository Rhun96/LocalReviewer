"""Миграции схемы SQLite без потери данных. Только ADD/CREATE, никаких DROP."""
import hashlib
import json
import logging

logger = logging.getLogger(__name__)


def migrate_to_v3(cursor) -> None:
    """bulk_operations + saved_filters + history.operation_id (ТЗ §77-78, §28-29)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_operations (
            operation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            op_type TEXT NOT NULL,
            params_json TEXT,
            case_count INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            undone INTEGER DEFAULT 0
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bulk_operation_items (
            operation_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            field_name TEXT NOT NULL,
            old_value TEXT,
            new_value TEXT,
            PRIMARY KEY (operation_id, case_id, field_name),
            FOREIGN KEY (operation_id) REFERENCES bulk_operations(operation_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_filters (
            filter_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            filter_json TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    # operation_id в history: SQLite не умеет ADD COLUMN IF NOT EXISTS -> проверяем pragma
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(history)").fetchall()]
    if "operation_id" not in cols:
        cursor.execute("ALTER TABLE history ADD COLUMN operation_id INTEGER")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_history_op ON history(operation_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_bulk_items_case ON bulk_operation_items(case_id)"
    )
    logger.info("migrated to v3 (bulk_operations, saved_filters, history.operation_id)")


def migrate_to_v4(cursor) -> None:
    """severity автопроверок (ТЗ §17)."""
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(case_checks)").fetchall()]
    if "severity" not in cols:
        cursor.execute("ALTER TABLE case_checks ADD COLUMN severity TEXT DEFAULT 'warning'")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_checks_sev ON case_checks(check_code, severity)"
    )
    logger.info("migrated to v4 (case_checks.severity)")


def _backfill_null_hashes(cursor) -> int:
    """У старых строк content_hash может быть NULL — считаем из raw_json/текстов.

    Без этого дубли с NULL-хэшами не находятся и UNIQUE-индекс их пропустит молча.
    Возвращает число обновлённых строк.
    """
    rows = cursor.execute(
        "SELECT case_id, raw_json, primary_text, response_text FROM cases "
        "WHERE content_hash IS NULL").fetchall()
    fixed = 0
    for r in rows:
        base = r["raw_json"] or json.dumps(
            {"primary_text": r["primary_text"] or "", "response_text": r["response_text"] or ""},
            sort_keys=True, ensure_ascii=False)
        h = hashlib.sha256(base.encode("utf-8")).hexdigest()
        cursor.execute("UPDATE cases SET content_hash=? WHERE case_id=?", (h, r["case_id"]))
        fixed += 1
    if fixed:
        logger.info("backfilled %s NULL content_hash", fixed)
    return fixed


def _dedup_cases(cursor) -> int:
    """Слияние точных дублей (file_id, content_hash) от старого импортёра без дедупа.

    Keeper: сначала размеченный (статус != unreviewed), затем минимальный case_id.
    Наследие проигравших переносится: теги (merge), история и проверки
    перепривязываются, аннотация переносится если у keeper её нет.
    Возвращает число удалённых строк.
    """
    groups = cursor.execute("""
        SELECT file_id, content_hash, COUNT(*) AS c
        FROM cases
        WHERE content_hash IS NOT NULL
        GROUP BY file_id, content_hash
        HAVING COUNT(*) > 1
    """).fetchall()
    removed = 0
    for g in groups:
        rows = cursor.execute("""
            SELECT c.case_id, COALESCE(a.status, 'unreviewed') AS status
            FROM cases c LEFT JOIN annotations a ON a.case_id = c.case_id
            WHERE c.file_id = ? AND c.content_hash = ?
            ORDER BY (COALESCE(a.status, 'unreviewed') != 'unreviewed') DESC, c.case_id
        """, (g["file_id"], g["content_hash"])).fetchall()
        keeper = rows[0]["case_id"]
        for loser_row in rows[1:]:
            loser = loser_row["case_id"]
            # Аннотация: перенести, если у keeper нет своей
            has_keeper = cursor.execute(
                "SELECT 1 FROM annotations WHERE case_id=?", (keeper,)).fetchone()
            if not has_keeper:
                cursor.execute(
                    "UPDATE annotations SET case_id=? WHERE case_id=?", (keeper, loser))
            # Теги: merge без дублей
            cursor.execute("""
                INSERT OR IGNORE INTO case_tags (case_id, tag_id, created_at)
                SELECT ?, tag_id, created_at FROM case_tags WHERE case_id=?
            """, (keeper, loser))
            # История и проверки: перепривязать
            cursor.execute("UPDATE history SET case_id=? WHERE case_id=?", (keeper, loser))
            cursor.execute("UPDATE case_checks SET case_id=? WHERE case_id=?", (keeper, loser))
            cursor.execute("DELETE FROM cases WHERE case_id=?", (loser,))
            removed += 1
    if removed:
        logger.warning("dedup: merged %s duplicate cases (%s groups)", removed, len(groups))
    return removed


def ensure_uq_cases_hash(cursor) -> int:
    """Backfill NULL-хэшей + слияние дублей + UNIQUE-индекс. Возвращает число удалённых дублей."""
    _backfill_null_hashes(cursor)
    removed = _dedup_cases(cursor)
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_cases_file_hash ON cases(file_id, content_hash)"
    )
    return removed
