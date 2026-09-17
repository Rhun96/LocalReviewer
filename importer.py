"""Импорт данных в БД: батчинг, транзакции, валидация, дедуп."""
import hashlib
import json
import logging
from pathlib import Path

from constants import ALLOWED_ROLES
from database import db, utcnow
from workers import Cancelled

logger = logging.getLogger(__name__)
BATCH = 2000


def compute_content_hash(row_data: dict) -> str:
    content = json.dumps(row_data, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def file_sha256(file_path: str) -> str:
    """Хэш файла чанками (для дедупа повторных импортов одного файла)."""
    h = hashlib.sha256()
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def find_file_by_hash(project_path: str, file_hash: str) -> dict | None:
    """Уже импортированный файл с таким хэшем (или None)."""
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT file_id, file_name, row_count, imported_at FROM files "
            "WHERE file_hash = ? ORDER BY imported_at DESC LIMIT 1",
            (file_hash,)).fetchone()
        return dict(row) if row else None


def find_file_by_name(project_path: str, file_name: str) -> dict | None:
    """Файл с таким именем (для импортов до хэшей: хэш тогда неизвестен)."""
    with db(project_path) as conn:
        row = conn.cursor().execute(
            "SELECT file_id, file_name, row_count, imported_at, file_hash FROM files "
            "WHERE file_name = ? ORDER BY imported_at DESC LIMIT 1",
            (file_name,)).fetchone()
        return dict(row) if row else None


def _custom_name(role: str) -> str:
    """Своя категория из маппинга: 'custom:Моё' -> 'Моё' (валидация имени)."""
    name = role.split(":", 1)[1].strip()
    if not name or len(name) > 64:
        raise ValueError(f"Плохое имя категории: {role!r}")
    if any(ch in name for ch in "\n\r\t"):
        raise ValueError(f"Плохое имя категории: {role!r}")
    return name


def _validate_mapping(mapping: dict) -> None:
    for col, role in mapping.items():
        if role is None or role in ALLOWED_ROLES:
            continue
        if isinstance(role, str) and role.startswith("custom:"):
            _custom_name(role)
            continue
        raise ValueError(f"Неизвестная роль {role!r} для колонки {col!r}")


def import_file(
    project_path: str,
    file_path: str,
    file_type: str,
    sheet_name: str,
    header_row: int,
    mapping: dict,
    data: list,
    progress_callback=None,
    cancel_event=None,
) -> tuple:
    """Возвращает (file_id, imported, skipped).

    Дедуп внутри файла по content_hash. Дубли source_id внутри файла
    НЕ пропускаются (нужны для conflicted в датасетах), но считаются
    и логируются как предупреждение (ТЗ §81).
    row_count в files — исходное число строк файла, а не imported.
    """
    _validate_mapping(mapping)
    file_name = Path(file_path).name
    now = utcnow()

    role_columns: dict = {}
    metadata_cols: list = []
    for col_name, role in mapping.items():
        if role == "ignore" or role is None:
            continue
        if role == "metadata":
            metadata_cols.append(col_name)
        else:
            role_columns.setdefault(role, []).append(col_name)

    def get_role_value(row, role):
        cols = role_columns.get(role, [])
        if not cols:
            return None
        values = []
        for col in cols:
            v = row.get(col, "")
            if v is not None and str(v).strip():
                values.append(str(v).strip())
        if not values:
            return None
        return values[0] if len(values) == 1 else "\n\n".join(values)

    with db(project_path) as conn:
        cursor = conn.cursor()
        try:
            digest = file_sha256(str(file_path))
        except OSError:
            digest = None
        cursor.execute("""
            INSERT INTO files (
                file_name, file_path, file_type, sheet_name,
                header_row, row_count, imported_at, mapping_json, file_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            file_name, str(file_path), file_type, sheet_name,
            header_row, len(data), now,
            json.dumps(mapping, ensure_ascii=False), digest,
        ))
        file_id = cursor.lastrowid

        cases_batch, ann_batch = [], []
        imported = skipped = 0
        seen_hashes: set = set()
        seen_source_ids: dict = {}
        dup_source_ids: set = set()

        def flush():
            nonlocal imported
            if not cases_batch:
                return
            before = conn.total_changes
            cursor.executemany("""
                INSERT OR IGNORE INTO cases (
                    file_id, row_index, source_id, content_hash,
                    primary_text, response_text, group_name,
                    comment_from_source, metadata_json, raw_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, cases_batch)
            # imported считает ТОЛЬКО кейсы: аннотации вставляются ниже
            # и в дельту уже не входят.
            imported += conn.total_changes - before
            # Аннотации: вставляем для всех hash батча, IGNORE покроет дубли
            cursor.executemany("""
                INSERT OR IGNORE INTO annotations (case_id, status, comment, updated_at)
                SELECT case_id, 'unreviewed', NULL, ?
                FROM cases WHERE file_id = ? AND content_hash = ?
            """, ann_batch)
            cases_batch.clear()
            ann_batch.clear()

        for row_index, row in enumerate(data):
            if cancel_event is not None and cancel_event.is_set():
                break
            if not isinstance(row, dict):
                skipped += 1
                continue
            primary_text = get_role_value(row, "primary_text") or ""
            response_text = get_role_value(row, "response_text")
            group_name = get_role_value(row, "group_name")
            source_id = get_role_value(row, "source_id")
            comment_from_source = get_role_value(row, "comment_source")

            metadata = {col: row.get(col, "") for col in metadata_cols}
            for role_key in ("ticket_number", "product", "operator_response", "source"):
                val = get_role_value(row, role_key)
                if val:
                    metadata[role_key] = val
            # Тема кейса — отдельная роль маппинга (своё окно в ревью).
            topic_val = get_role_value(row, "topic_text")
            if topic_val:
                metadata["topic"] = topic_val
            # Свои категории маппинга -> ключи метаданных
            for role in role_columns:
                if isinstance(role, str) and role.startswith("custom:"):
                    val = get_role_value(row, role)
                    if val:
                        metadata[_custom_name(role)] = val

            content_hash = compute_content_hash(row)
            if content_hash in seen_hashes:
                skipped += 1
                continue
            seen_hashes.add(content_hash)
            if source_id and str(source_id).strip():
                sid = str(source_id).strip()
                if sid in seen_source_ids:
                    dup_source_ids.add(sid)
                else:
                    seen_source_ids[sid] = row_index

            cases_batch.append((
                file_id, row_index, source_id, content_hash,
                primary_text, response_text, group_name,
                comment_from_source,
                json.dumps(metadata, ensure_ascii=False) if metadata else None,
                json.dumps(row, ensure_ascii=False), now,
            ))
            ann_batch.append((now, file_id, content_hash))
            if len(cases_batch) >= BATCH:
                flush()
            if progress_callback and (row_index + 1) % 500 == 0:
                try:
                    progress_callback(row_index + 1, len(data))
                except Exception:
                    pass

        flush()
        if cancel_event is not None and cancel_event.is_set():
            # Частичный импорт при отмене: фиксируем что успели, считаем честно.
            imported = cursor.execute(
                "SELECT COUNT(*) AS c FROM cases WHERE file_id=?",
                (file_id,)).fetchone()["c"]
            skipped = len(data) - imported
            logger.info("import file_id=%s CANCELLED imported=%s skipped=%s",
                        file_id, imported, skipped)
            raise Cancelled(f"Прервано пользователем: импортировано {imported} из {len(data)}")
        # Пересчёт skipped: дубли внутри файла + IGNORE в БД.
        # imported уже посчитан через changes() (только cases); сверяем с фактом.
        total_rows = len(data)
        actual = cursor.execute(
            "SELECT COUNT(*) AS c FROM cases WHERE file_id=?",
            (file_id,)).fetchone()["c"]
        if actual != imported:
            logger.warning("import count mismatch changes=%s actual=%s", imported, actual)
            imported = actual
        # skipped = всего - вставлено (покрывает невалидные + дубли)
        skipped = total_rows - imported
        # row_count — исходное число строк файла (не затираем на imported).
        cursor.execute(
            "UPDATE files SET row_count = ? WHERE file_id = ?",
            (total_rows, file_id),
        )
        if dup_source_ids:
            logger.warning("import file_id=%s duplicate source_id: %s (пример: %s)",
                           file_id, len(dup_source_ids),
                           sorted(dup_source_ids)[:5])
        logger.info("import file_id=%s imported=%s skipped=%s dup_source_ids=%s",
                    file_id, imported, skipped, len(dup_source_ids))
        return file_id, imported, skipped
