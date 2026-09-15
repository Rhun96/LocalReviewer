"""Схема и подключение SQLite с миграциями, PRAGMA и индексами."""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import datetime, UTC
from pathlib import Path

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 9
DB_TIMEOUT = 10.0


def utcnow() -> str:
    return datetime.now(UTC).isoformat()


def _apply_pragmas(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA synchronous=NORMAL")


def get_db_connection(project_path: str) -> sqlite3.Connection:
    """Совместимое API: возвращает открытое соединение (закрывать вызывающему коду)."""
    db_path = Path(project_path) / "project.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"База данных не найдена: {db_path}")
    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row
    _apply_pragmas(conn)
    return conn


@contextmanager
def db(project_path: str):
    """Предпочтительный API: with db(path) as conn (commit/rollback/close автоматически)."""
    conn = get_db_connection(project_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def _create_schema_v1(cursor: sqlite3.Cursor) -> None:
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS files (
            file_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_name TEXT NOT NULL,
            file_path TEXT NOT NULL,
            file_type TEXT NOT NULL,
            file_hash TEXT,
            sheet_name TEXT,
            header_row INTEGER DEFAULT 0,
            row_count INTEGER DEFAULT 0,
            imported_at TEXT NOT NULL,
            mapping_json TEXT,
            notes TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            case_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id INTEGER NOT NULL,
            row_index INTEGER NOT NULL,
            source_id TEXT,
            content_hash TEXT,
            primary_text TEXT,
            response_text TEXT,
            group_name TEXT,
            comment_from_source TEXT,
            metadata_json TEXT,
            raw_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (file_id) REFERENCES files(file_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'unreviewed'
                CHECK (status IN ('unreviewed','good','bad','uncertain','duplicate','skip')),
            comment TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_code TEXT NOT NULL UNIQUE,
            tag_name TEXT NOT NULL,
            is_system INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_tags (
            case_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            PRIMARY KEY (case_id, tag_id),
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            history_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            field_name TEXT,
            old_value TEXT,
            new_value TEXT,
            comment TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS case_checks (
            check_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL,
            check_code TEXT NOT NULL,
            check_name TEXT NOT NULL,
            details TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT NOT NULL
        )
    """)


def _create_indexes(cursor: sqlite3.Cursor) -> None:
    cursor.executescript("""
        CREATE INDEX IF NOT EXISTS idx_cases_file ON cases(file_id, row_index);
        CREATE INDEX IF NOT EXISTS idx_cases_hash ON cases(content_hash);
        CREATE INDEX IF NOT EXISTS idx_ann_status ON annotations(status);
        CREATE INDEX IF NOT EXISTS idx_case_tags_tag ON case_tags(tag_id, case_id);
        CREATE INDEX IF NOT EXISTS idx_checks_case ON case_checks(case_id, check_code);
        CREATE INDEX IF NOT EXISTS idx_history_case ON history(case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_files_imported ON files(imported_at DESC);
    """)


def _seed(cursor: sqlite3.Cursor) -> None:
    system_tags = [
        ('style', 'стиль', 1),
        ('facts', 'факты', 1),
        ('format', 'формат', 1),
        ('length', 'длина', 1),
        ('safety', 'безопасность', 1),
        ('toxicity', 'токсичность', 1),
        ('duplicate', 'дубль', 1),
        ('spam', 'спам', 1),
        ('links', 'ссылки', 1),
        ('personal_data', 'личные данные', 1),
        ('needs_fix', 'требуется исправление', 1),
        ('needs_discussion', 'нужно обсудить', 1),
    ]
    now = utcnow()
    for tag_code, tag_name, is_system in system_tags:
        cursor.execute("""
            INSERT OR IGNORE INTO tags (tag_code, tag_name, is_system, created_at)
            VALUES (?, ?, ?, ?)
        """, (tag_code, tag_name, is_system, now))
    for key, value in [
        ('auto_next_case', 'true'),
        ('require_comment_for_bad', 'warn'),
        ('theme_font_size', '10'),
    ]:
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, now))


def _migrate_to_v2(cursor: sqlite3.Cursor) -> None:
    # Таблица шаблонов раньше создавалась лениво в templates_service.
    # Теперь — часть схемы, чтобы не было дрейфа между БД.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS comment_templates (
            template_id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL UNIQUE,
            is_system INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    now = utcnow()
    for t in [
        "Слишком коротко", "Не по задаче", "Нарушен формат",
        "Сомнительные факты", "Есть ссылка", "Похоже на дубль",
        "Требуется исправление", "Нужно обсудить",
        "Грамматические ошибки", "Стилистические проблемы",
    ]:
        cursor.execute(
            "INSERT OR IGNORE INTO comment_templates "
            "(text, is_system, created_at) VALUES (?, 1, ?)",
            (t, now),
        )
    # Дедуп повторных импортов: старые БД могут содержать дубли от импортёра
    # без дедупа — сначала backfill + слияние, иначе UNIQUE-индекс упадёт.
    from migrations import ensure_uq_cases_hash
    removed = ensure_uq_cases_hash(cursor)
    if removed:
        logger.warning("migrate_to_v2: merged %s duplicate cases (backup created before)", removed)


def init_database(project_path: str):
    """Создаёт/мигрирует БД проекта. Идемпотентно. Перед миграцией — autobackup."""
    project_dir = Path(project_path)
    project_dir.mkdir(parents=True, exist_ok=True)
    db_path = project_dir / "project.sqlite"
    existed = db_path.exists()

    conn = sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = sqlite3.Row  # миграции обращаются к колонкам по имени
    try:
        _apply_pragmas(conn)
        cursor = conn.cursor()
        version = cursor.execute("PRAGMA user_version").fetchone()[0] or 0
        if version < 1:
            _create_schema_v1(cursor)
            _create_indexes(cursor)
            _seed(cursor)
            cursor.execute("PRAGMA user_version=1")
            version = 1
        else:
            # На старых БД могли отсутствовать индексы/ограничения — дотягиваем.
            _create_indexes(cursor)
        if existed and 1 <= version < SCHEMA_VERSION:
            # ТЗ §91: перед ЛЮБОЙ миграцией существующей БД — автоматический бэкап.
            # Важно: v2-миграция удаляет дубли, бэкап должен быть ДО неё.
            try:
                from backup_service import create_backup
                create_backup(project_path)
            except Exception as e:
                logger.warning("autobackup before migrate failed: %s", e)
        if version < 2:
            _migrate_to_v2(cursor)
            cursor.execute("PRAGMA user_version=2")
            version = 2
        else:
            # Застрявшие БД: версия 2+, а UNIQUE-индекса нет (падала прошлая миграция).
            has_uq = cursor.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='uq_cases_file_hash'"
            ).fetchone()
            if not has_uq:
                from migrations import ensure_uq_cases_hash
                removed = ensure_uq_cases_hash(cursor)
                if removed:
                    logger.warning("repaired missing uq index, merged %s duplicates", removed)
        if version < 3:
            from migrations import migrate_to_v3
            migrate_to_v3(cursor)
            cursor.execute("PRAGMA user_version=3")
            version = 3
        if version < 4:
            from migrations import migrate_to_v4
            migrate_to_v4(cursor)
            cursor.execute("PRAGMA user_version=4")
            version = 4
        if version < 5:
            from migrations import migrate_to_v5
            migrate_to_v5(cursor)
            cursor.execute("PRAGMA user_version=5")
            version = 5
        if version < 6:
            from migrations import migrate_to_v6
            migrate_to_v6(cursor)
            cursor.execute("PRAGMA user_version=6")
            version = 6
        if version < 7:
            from migrations import migrate_to_v7
            migrate_to_v7(cursor)
            cursor.execute("PRAGMA user_version=7")
            version = 7
        if version < 8:
            from migrations import migrate_to_v8
            migrate_to_v8(cursor)
            cursor.execute("PRAGMA user_version=8")
            version = 8
        if version < 9:
            from migrations import migrate_to_v9
            migrate_to_v9(cursor)
            cursor.execute("PRAGMA user_version=9")
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("init_database failed: %s", db_path)
        raise
    finally:
        conn.close()
    return db_path
