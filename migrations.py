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


DEFAULT_TAXONOMY = [
    ("correctness", "Правильность", None, [
        ("correctness.factual", "Фактическая ошибка"),
        ("correctness.hallucination", "Галлюцинация"),
        ("correctness.wrong_condition", "Неверное условие"),
        ("correctness.wrong_calc", "Неверный расчёт"),
    ]),
    ("completeness", "Полнота", None, [
        ("completeness.incomplete", "Неполный ответ"),
        ("completeness.missed_condition", "Пропущено важное условие"),
        ("completeness.missed_scenario", "Не рассмотрен сценарий"),
    ]),
    ("relevance", "Релевантность", None, [
        ("relevance.off_topic", "Не отвечает на вопрос"),
        ("relevance.extra_info", "Лишняя информация"),
        ("relevance.evasion", "Уход от темы"),
    ]),
    ("format", "Формат", None, [
        ("format.wrong_format", "Неверный формат"),
        ("format.too_long", "Слишком длинный"),
        ("format.too_short", "Слишком короткий"),
    ]),
    ("safety", "Безопасность", None, [
        ("safety.dangerous", "Опасный ответ"),
        ("safety.policy", "Нарушение политики"),
        ("safety.personal_data", "Работа с персональными данными"),
    ]),
    ("other", "Другое", None, [
        ("other.other", "Другое"),
    ]),
]


def _utcnow() -> str:
    from datetime import UTC, datetime
    return datetime.now(UTC).isoformat()


DEFAULT_PROFILE_CONFIG = {
    "statuses": [
        {"code": "good", "name": "Хорошо", "hotkey": "1", "enabled": True},
        {"code": "bad", "name": "Плохо", "hotkey": "2", "enabled": True},
        {"code": "uncertain", "name": "Сомневаюсь", "hotkey": "3", "enabled": True},
        {"code": "duplicate", "name": "Дубль", "hotkey": "4", "enabled": True},
        {"code": "skip", "name": "Пропустить", "hotkey": "5", "enabled": True},
    ],
    "require_category_for_bad": False,
    "require_comment_for_bad": None,  # None = брать из настроек проекта
}


def migrate_to_v6(cursor) -> None:
    """Профили ревью (ТЗ §31-36). Старые проекты → Default-профиль."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS review_profiles (
            profile_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            config_json TEXT NOT NULL,
            is_default INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    now = _utcnow()
    cursor.execute("""
        INSERT INTO review_profiles (name, description, config_json, is_default,
                                     created_at, updated_at)
        VALUES (?, ?, ?, 1, ?, ?)
        ON CONFLICT(name) DO NOTHING
    """, ("Default", "Стандартная схема: 5 статусов, клавиши 1–5",
          json.dumps(DEFAULT_PROFILE_CONFIG, ensure_ascii=False), now, now))
    logger.info("migrated to v6 (review_profiles)")


def migrate_to_v7(cursor) -> None:
    """Версии датасетов и Golden (ТЗ §37-42, §61-63).

    Версия — неизменяемый снимок: dataset_cases хранит case_id + статус
    и комментарий на момент фиксации. Заморозка = статус, правок не бывает.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS datasets (
            dataset_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            dataset_type TEXT NOT NULL DEFAULT 'working'
                CHECK (dataset_type IN ('working','golden','test','safety','archive')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dataset_versions (
            version_id INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset_id INTEGER NOT NULL,
            version_number INTEGER NOT NULL,
            description TEXT,
            status TEXT NOT NULL DEFAULT 'draft'
                CHECK (status IN ('draft','review','frozen','archived')),
            case_count INTEGER DEFAULT 0,
            content_hash TEXT,
            created_at TEXT NOT NULL,
            frozen_at TEXT,
            UNIQUE (dataset_id, version_number),
            FOREIGN KEY (dataset_id) REFERENCES datasets(dataset_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS dataset_cases (
            version_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            status TEXT,
            comment TEXT,
            PRIMARY KEY (version_id, case_id),
            FOREIGN KEY (version_id) REFERENCES dataset_versions(version_id)
                ON DELETE CASCADE
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_cases_case "
        "ON dataset_cases(case_id)"
    )
    logger.info("migrated to v7 (datasets)")


def stable_key_for(source_id, content_hash, case_id) -> str:
    """Стабильный ключ кейса: source_id → content_hash → case_id."""
    if source_id and str(source_id).strip():
        return "src:" + str(source_id).strip()
    if content_hash:
        return "hash:" + str(content_hash)
    return f"case:{case_id}"


def ensure_dataset_keys(cursor) -> int:
    """Backfill stable_key для старых снимков. Возвращает число строк."""
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(dataset_cases)").fetchall()]
    if "stable_key" not in cols:
        cursor.execute("ALTER TABLE dataset_cases ADD COLUMN stable_key TEXT")
    rows = cursor.execute("""
        SELECT dc.version_id, dc.case_id, c.source_id, c.content_hash
        FROM dataset_cases dc
        LEFT JOIN cases c ON c.case_id = dc.case_id
        WHERE dc.stable_key IS NULL
    """).fetchall()
    for r in rows:
        key = stable_key_for(r["source_id"] if r else None,
                             r["content_hash"] if r else None,
                             r["case_id"])
        cursor.execute("UPDATE dataset_cases SET stable_key=? "
                       "WHERE version_id=? AND case_id=?",
                       (key, r["version_id"], r["case_id"]))
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_cases_key "
        "ON dataset_cases(version_id, stable_key)"
    )
    if rows:
        logger.info("backfilled %s dataset stable_keys", len(rows))
    return len(rows)


def migrate_to_v8(cursor) -> None:
    """Сравнение версий по стабильным ключам (ТЗ §53)."""
    ensure_dataset_keys(cursor)
    logger.info("migrated to v8 (dataset stable keys)")


def migrate_to_v9(cursor) -> None:
    """Полный снимок разметки (исправление неполного dataset_cases).

    Добавляет: error_category_id/subcategory/severity, tags_json, text_hash.
    Только ADD COLUMN + INDEX, без DROP. Старые снимки остаются с NULL
    в новых полях (неизвестность, а не «пусто») — compare их учитывает.
    """
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(dataset_cases)").fetchall()]
    for col, ddl in (
        ("error_category_id", "ALTER TABLE dataset_cases "
                              "ADD COLUMN error_category_id INTEGER"),
        ("error_subcategory_id", "ALTER TABLE dataset_cases "
                                 "ADD COLUMN error_subcategory_id INTEGER"),
        ("error_severity", "ALTER TABLE dataset_cases ADD COLUMN error_severity TEXT"),
        ("tags_json", "ALTER TABLE dataset_cases ADD COLUMN tags_json TEXT"),
        ("text_hash", "ALTER TABLE dataset_cases ADD COLUMN text_hash TEXT"),
    ):
        if col not in cols:
            cursor.execute(ddl)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_dataset_cases_key "
        "ON dataset_cases(version_id, stable_key)"
    )
    logger.info("migrated to v9 (dataset full snapshot)")


def migrate_to_v5(cursor) -> None:
    """Таксономия ошибок + классификация кейсов (ТЗ §19-23)."""
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS error_categories (
            category_id INTEGER PRIMARY KEY AUTOINCREMENT,
            parent_id INTEGER,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1,
            created_at TEXT NOT NULL,
            FOREIGN KEY (parent_id) REFERENCES error_categories(category_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_errors (
            case_id INTEGER PRIMARY KEY,
            category_id INTEGER,
            subcategory_id INTEGER,
            severity TEXT DEFAULT 'medium'
                CHECK (severity IN ('low', 'medium', 'high', 'critical')),
            updated_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_case_errors_cat "
        "ON case_errors(category_id, subcategory_id)"
    )
    now = _utcnow()
    order = 0
    for code, name, _desc, subs in DEFAULT_TAXONOMY:
        cursor.execute("""
            INSERT INTO error_categories
                (parent_id, code, name, sort_order, is_active, created_at)
            VALUES (NULL, ?, ?, ?, 1, ?)
            ON CONFLICT(code) DO UPDATE SET name=name
        """, (code, name, order, now))
        parent_id = cursor.execute(
            "SELECT category_id FROM error_categories WHERE code=?", (code,)).fetchone()[0]
        order += 1
        for sub_order, (sub_code, sub_name) in enumerate(subs):
            cursor.execute("""
                INSERT INTO error_categories
                    (parent_id, code, name, sort_order, is_active, created_at)
                VALUES (?, ?, ?, ?, 1, ?)
                ON CONFLICT(code) DO UPDATE SET name=name
            """, (parent_id, sub_code, sub_name, sub_order, now))
    logger.info("migrated to v5 (error taxonomy)")


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
            # Классификация ошибки: перенести, если у keeper нет своей
            has_err = cursor.execute(
                "SELECT 1 FROM case_errors WHERE case_id=?", (keeper,)).fetchone()
            if not has_err:
                cursor.execute(
                    "UPDATE case_errors SET case_id=? WHERE case_id=?", (keeper, loser))
            else:
                cursor.execute("DELETE FROM case_errors WHERE case_id=?", (loser,))
            # Теги: merge без дублей
            cursor.execute("""
                INSERT OR IGNORE INTO case_tags (case_id, tag_id, created_at)
                SELECT ?, tag_id, created_at FROM case_tags WHERE case_id=?
            """, (keeper, loser))
            # История и проверки: перепривязать
            cursor.execute("UPDATE history SET case_id=? WHERE case_id=?", (keeper, loser))
            cursor.execute("UPDATE case_checks SET case_id=? WHERE case_id=?", (keeper, loser))
            # Bulk/dataset-ссылки: перепривязать, чтобы не было сирот
            try:
                cursor.execute("UPDATE bulk_operation_items SET case_id=? WHERE case_id=?",
                               (keeper, loser))
            except Exception:
                pass
            try:
                cursor.execute("UPDATE dataset_cases SET case_id=? WHERE case_id=?",
                               (keeper, loser))
            except Exception:
                pass
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
