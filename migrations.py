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
        {"code": "good", "name": "Хорошо", "hotkey": "1", "enabled": True,
         "base": "good"},
        {"code": "bad", "name": "Плохо", "hotkey": "2", "enabled": True,
         "base": "bad"},
        {"code": "uncertain", "name": "Сомневаюсь", "hotkey": "3",
         "enabled": True, "base": "uncertain"},
        {"code": "duplicate", "name": "Дубль", "hotkey": "4", "enabled": True,
         "base": "duplicate"},
        {"code": "skip", "name": "Пропустить", "hotkey": "5", "enabled": True,
         "base": "skip"},
    ],
    "require_category_for_bad": True,
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


def migrate_to_v10(cursor) -> None:
    """Привязка шаблонов к причине (ТЗ §25): category_id/subcategory_id.

    Только ADD COLUMN. Непривязанные шаблоны (NULL) показываются всегда.
    """
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(comment_templates)").fetchall()]
    if "category_id" not in cols:
        cursor.execute("ALTER TABLE comment_templates ADD COLUMN category_id INTEGER")
    if "subcategory_id" not in cols:
        cursor.execute("ALTER TABLE comment_templates ADD COLUMN subcategory_id INTEGER")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_templates_cause "
                   "ON comment_templates(category_id, subcategory_id)")
    logger.info("migrated to v10 (template cause binding)")


def migrate_to_v11(cursor) -> None:
    """Произвольные статусы + «просмотрено» + вердикты проверок (ТЗ §31-36, §75-76).

    annotations: пересборка без CHECK(status IN ...) — коды теперь из профиля,
    плюс viewed (bulk «отметить просмотренным»). Данные копируются 1-в-1
    (перед миграцией init_database делает autobackup).
    case_check_verdicts: confirmed/false_positive по (case_id, check_code).
    """
    cols = [r[1] for r in cursor.execute("PRAGMA table_info(annotations)").fetchall()]
    if "viewed" not in cols or _annotations_has_check(cursor):
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS annotations_new (
                annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                case_id INTEGER NOT NULL UNIQUE,
                status TEXT DEFAULT 'unreviewed',
                comment TEXT,
                viewed INTEGER DEFAULT 0,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
            )
        """)
        if "viewed" in cols:
            cursor.execute("""
                INSERT OR IGNORE INTO annotations_new
                    (annotation_id, case_id, status, comment, viewed, updated_at)
                SELECT annotation_id, case_id, status, comment, viewed, updated_at
                FROM annotations
            """)
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO annotations_new
                    (annotation_id, case_id, status, comment, viewed, updated_at)
                SELECT annotation_id, case_id, status, comment, 0, updated_at
                FROM annotations
            """)
        cursor.execute("DROP TABLE annotations")
        cursor.execute("ALTER TABLE annotations_new RENAME TO annotations")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_check_verdicts (
            case_id INTEGER NOT NULL,
            check_code TEXT NOT NULL,
            verdict TEXT NOT NULL CHECK (verdict IN ('confirmed', 'false_positive')),
            updated_at TEXT NOT NULL,
            PRIMARY KEY (case_id, check_code),
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_verdicts_code "
                   "ON case_check_verdicts(check_code, verdict)")
    logger.info("migrated to v11 (custom statuses, viewed, verdicts)")


def _annotations_has_check(cursor) -> bool:
    try:
        sql = cursor.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='annotations'"
        ).fetchone()
        return bool(sql and "CHECK" in (sql[0] or "").upper())
    except Exception:
        return False


def migrate_to_v12(cursor) -> None:
    """Прогоны модели и сравнение ответов (ТЗ §45-48, §51-53).

    model_runs — запуск (модель/версии промптов/файл-источник).
    run_answers — ответ прогона по stable_key + привязка к кейсу (case_id
    NULL = кейс из прогона не сопоставлен с проектом: NEW).
    run_preferences — pairwise-предпочтение A vs B отдельно от absolute
    (absolute живёт в annotations.status; ТЗ §48 не смешивать).
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS model_runs (
            run_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            model_name TEXT NOT NULL DEFAULT '',
            model_version TEXT DEFAULT '',
            prompt_version TEXT DEFAULT '',
            system_prompt_version TEXT DEFAULT '',
            source_file TEXT DEFAULT '',
            file_id INTEGER,
            description TEXT DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS run_answers (
            run_id INTEGER NOT NULL,
            stable_key TEXT NOT NULL,
            case_id INTEGER,
            answer_text TEXT,
            created_at TEXT NOT NULL,
            PRIMARY KEY (run_id, stable_key),
            FOREIGN KEY (run_id) REFERENCES model_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS run_preferences (
            run_a_id INTEGER NOT NULL,
            run_b_id INTEGER NOT NULL,
            stable_key TEXT NOT NULL,
            case_id INTEGER,
            verdict TEXT NOT NULL DEFAULT 'unknown'
                CHECK (verdict IN ('a_better','b_better','tie','unknown')),
            rank_a INTEGER,
            rank_b INTEGER,
            comment TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_a_id, run_b_id, stable_key),
            FOREIGN KEY (run_a_id) REFERENCES model_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (run_b_id) REFERENCES model_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_answers_case "
                   "ON run_answers(case_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_answers_key "
                   "ON run_answers(stable_key)")
    logger.info("migrated to v12 (model runs)")


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


def migrate_to_v13(cursor) -> None:
    """Регрессионное тестирование (ТЗ §49-60, §83).

    output_reviews — absolute-разметка ответов прогона (своя на каждый run:
    один кейс в разных прогонах может иметь разное качество).
    regression_runs — запуск сравнения (baseline + candidate + gate-пороги).
    regression_results — построчный итог (UNCHANGED/IMPROVED/REGRESSION/
    NEW/REMOVED/UNRESOLVED + severity).
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS output_reviews (
            run_id INTEGER NOT NULL,
            stable_key TEXT NOT NULL,
            case_id INTEGER,
            status TEXT NOT NULL DEFAULT 'unreviewed',
            comment TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (run_id, stable_key),
            FOREIGN KEY (run_id) REFERENCES model_runs(run_id) ON DELETE CASCADE,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE SET NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regression_runs (
            regression_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            baseline_type TEXT NOT NULL
                CHECK (baseline_type IN ('dataset_version', 'run')),
            baseline_id INTEGER NOT NULL,
            candidate_run_id INTEGER NOT NULL,
            gate_max_critical INTEGER NOT NULL DEFAULT 0,
            gate_max_rate REAL NOT NULL DEFAULT 0.02,
            gate_result TEXT DEFAULT '',
            total INTEGER DEFAULT 0,
            regressions INTEGER DEFAULT 0,
            improvements INTEGER DEFAULT 0,
            unchanged INTEGER DEFAULT 0,
            created_at TEXT NOT NULL,
            FOREIGN KEY (candidate_run_id) REFERENCES model_runs(run_id)
                ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS regression_results (
            regression_id INTEGER NOT NULL,
            stable_key TEXT NOT NULL,
            case_id INTEGER,
            baseline_status TEXT,
            candidate_status TEXT,
            result TEXT NOT NULL
                CHECK (result IN ('UNCHANGED','IMPROVED','REGRESSION',
                                  'NEW','REMOVED','UNRESOLVED')),
            severity TEXT NOT NULL DEFAULT 'info'
                CHECK (severity IN ('critical','warning','info')),
            PRIMARY KEY (regression_id, stable_key),
            FOREIGN KEY (regression_id) REFERENCES regression_runs(regression_id)
                ON DELETE CASCADE,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE SET NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_regression_results_result "
                   "ON regression_results(regression_id, result, severity)")
    logger.info("migrated to v13 (regression)")


def migrate_to_v14(cursor) -> None:
    """Bug Reports (ТЗ V2 §6): баги + связь многие-ко-многим с кейсами.

    Историю пишем в общую history (без отдельной bug_report_history):
    BUG_CREATED/UPDATED/STATUS_CHANGED/EXTERNAL_LINKED — на все связанные
    кейсы, CASE_ADDED/REMOVED — на конкретный кейс.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bug_reports (
            bug_id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'New'
                CHECK (status IN ('New','Confirmed','In Progress',
                                  'Fixed','Rejected','Duplicate')),
            severity TEXT NOT NULL DEFAULT 'Medium'
                CHECK (severity IN ('Low','Medium','High','Critical')),
            category_id INTEGER,
            subcategory_id INTEGER,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            model_name TEXT DEFAULT '',
            model_version TEXT DEFAULT '',
            prompt_version TEXT DEFAULT '',
            system_prompt_version TEXT DEFAULT '',
            external_tracker TEXT DEFAULT '',
            external_id TEXT DEFAULT '',
            external_url TEXT DEFAULT '',
            actual_behavior TEXT DEFAULT '',
            expected_behavior TEXT DEFAULT '',
            internal_comment TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bug_report_cases (
            bug_id INTEGER NOT NULL,
            case_id INTEGER NOT NULL,
            added_at TEXT NOT NULL,
            PRIMARY KEY (bug_id, case_id),
            FOREIGN KEY (bug_id) REFERENCES bug_reports(bug_id) ON DELETE CASCADE,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bugs_status ON bug_reports(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bugs_severity ON bug_reports(severity)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bugs_created ON bug_reports(created_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bugs_external ON bug_reports(external_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bug_cases_case "
                   "ON bug_report_cases(case_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bug_cases_bug "
                   "ON bug_report_cases(bug_id)")
    logger.info("migrated to v14 (bug reports)")


def migrate_to_v15(cursor) -> None:
    """Продукт, свои категории и текст вопроса в ответах прогонов.

    Только ADD COLUMN: старые ответы получают пустые значения.
    """
    cols = {r[1] for r in cursor.execute("PRAGMA table_info(run_answers)").fetchall()}
    if "product" not in cols:
        cursor.execute("ALTER TABLE run_answers ADD COLUMN product TEXT DEFAULT ''")
    if "metadata_json" not in cols:
        cursor.execute("ALTER TABLE run_answers ADD COLUMN metadata_json TEXT")
    if "prompt_text" not in cols:
        cursor.execute("ALTER TABLE run_answers ADD COLUMN prompt_text TEXT")
    logger.info("migrated to v15 (run answer product/metadata/prompt)")


def migrate_to_v16(cursor) -> None:
    """Locked-флаг датасетов (дисциплина golden): состав зафиксирован.

    Только ADD COLUMN. Locked блокирует новые версии и удаление версий;
    freeze/archive разрешены (это усиление, а не изменение состава).
    """
    cols = {r[1] for r in cursor.execute("PRAGMA table_info(datasets)").fetchall()}
    if "locked" not in cols:
        cursor.execute("ALTER TABLE datasets ADD COLUMN locked INTEGER DEFAULT 0")
    logger.info("migrated to v16 (dataset locked flag)")


def migrate_to_v17(cursor) -> None:
    """Regression assertions V2.1 §15: формальные проверки ответа без LLM.

    Только CREATE TABLE + INDEX. Результаты НЕ храним — считаются на лету
    (иначе таблица результатов протухает при каждом новом прогоне).
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS assertions (
            assert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            atype TEXT NOT NULL,
            params_json TEXT,
            enabled INTEGER DEFAULT 1,
            severity TEXT NOT NULL DEFAULT 'warning'
                CHECK (severity IN ('critical','warning','info')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_assertions_enabled "
                   "ON assertions(enabled)")
    logger.info("migrated to v17 (regression assertions)")


def migrate_to_v18(cursor) -> None:
    """Подсветка фрагментов ответа (зелёный/красный/жёлтый).

    Только CREATE TABLE + INDEX. Сами подсветки — смещения в тексте ответа;
    при смене текста ответа протухшие чистим по text_hash при чтении.
    """
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_highlights (
            highlight_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            start_offset INTEGER NOT NULL,
            end_offset INTEGER NOT NULL,
            color TEXT NOT NULL CHECK (color IN ('green','red','yellow')),
            text_hash TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_highlights_case "
                   "ON case_highlights(case_id)")
    logger.info("migrated to v18 (answer highlights)")
