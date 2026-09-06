import sqlite3
import json
from pathlib import Path
from datetime import datetime


def init_database(project_path: str):
    """
    Инициализирует базу данных SQLite в папке проекта.
    Создаёт все необходимые таблицы.
    """
    db_path = Path(project_path) / "project.sqlite"
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # Таблица файлов
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
    
    # Таблица кейсов
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
    
    # Таблица аннотаций (статусы, комментарии)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            annotation_id INTEGER PRIMARY KEY AUTOINCREMENT,
            case_id INTEGER NOT NULL UNIQUE,
            status TEXT DEFAULT 'unreviewed',
            comment TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
        )
    """)
    
    # Таблица тегов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
            tag_code TEXT NOT NULL UNIQUE,
            tag_name TEXT NOT NULL,
            is_system INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )
    """)
    
    # Таблица связей кейсов и тегов
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
    
    # Таблица истории изменений
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
    
    # Таблица автопроверок
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
    
    # Таблица настроек
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT NOT NULL
        )
    """)
    
    # Вставка системных тегов по умолчанию
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
    
    now = datetime.now().isoformat()
    for tag_code, tag_name, is_system in system_tags:
        cursor.execute("""
            INSERT OR IGNORE INTO tags (tag_code, tag_name, is_system, created_at)
            VALUES (?, ?, ?, ?)
        """, (tag_code, tag_name, is_system, now))
    
    # Вставка настроек по умолчанию
    default_settings = [
        ('auto_next_case', 'true'),
        ('require_comment_for_bad', 'warn'),
        ('theme_font_size', '10'),
    ]
    
    for key, value in default_settings:
        cursor.execute("""
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, now))
    
    conn.commit()
    conn.close()
    
    return db_path


def get_db_connection(project_path: str):
    """Получает соединение с базой данных проекта."""
    db_path = Path(project_path) / "project.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"База данных не найдена: {db_path}")
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row  # Чтобы результаты были как словари
    return conn