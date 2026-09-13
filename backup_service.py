"""Безопасное резервное копирование SQLite: online-backup, валидация путей, ротация."""
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from constants import MAX_BACKUPS_KEEP

logger = logging.getLogger(__name__)


def _backups_dir(project_path: str) -> Path:
    d = Path(project_path) / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _safe_backup_path(project_path: str, backup_path: str) -> Path:
    base = (Path(project_path) / "backups").resolve()
    p = Path(backup_path).resolve()
    if p.parent != base or p.suffix != ".sqlite":
        raise ValueError("Недопустимый путь резервной копии")
    return p


def _rotate(backups_dir: Path, keep: int = MAX_BACKUPS_KEEP) -> None:
    files = sorted(backups_dir.glob("project_backup_*.sqlite"), key=lambda f: f.stat().st_mtime)
    for old in files[:-keep] if len(files) > keep else []:
        try:
            old.unlink()
        except OSError:
            logger.warning("cannot rotate backup %s", old)


def _integrity_ok(path: Path) -> bool:
    try:
        conn = sqlite3.connect(str(path), timeout=10)
        try:
            row = conn.execute("PRAGMA integrity_check").fetchone()
            return bool(row and row[0] == "ok")
        finally:
            conn.close()
    except Exception:
        return False


def create_backup(project_path: str) -> str:
    project_dir = Path(project_path)
    db_path = project_dir / "project.sqlite"
    if not db_path.exists():
        raise FileNotFoundError("База данных не найдена")

    backups_dir = _backups_dir(project_path)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup_path = backups_dir / f"project_backup_{timestamp}.sqlite"

    src = sqlite3.connect(str(db_path), timeout=10)
    try:
        dst = sqlite3.connect(str(backup_path), timeout=10)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()

    if not _integrity_ok(backup_path):
        try:
            backup_path.unlink()
        except OSError:
            pass
        raise RuntimeError("Резервная копия не прошла проверку целостности")

    _rotate(backups_dir)
    logger.info("backup created: %s", backup_path)
    return str(backup_path)


def get_backups_list(project_path: str) -> list:
    backups_dir = Path(project_path) / "backups"
    if not backups_dir.exists():
        return []
    backups = []
    for file in backups_dir.glob("project_backup_*.sqlite"):
        try:
            stat = file.stat()
        except OSError:
            continue
        backups.append({
            "path": str(file),
            "name": file.name,
            "size": stat.st_size,
            "created": datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    backups.sort(key=lambda x: x["created"], reverse=True)
    return backups


def restore_backup(project_path: str, backup_path: str) -> bool:
    src = _safe_backup_path(project_path, backup_path)
    if not src.exists():
        raise FileNotFoundError("Резервная копия не найдена")
    if not _integrity_ok(src):
        raise RuntimeError("Резервная копия повреждена (integrity_check failed)")

    project_dir = Path(project_path)
    db_path = project_dir / "project.sqlite"

    if db_path.exists():
        create_backup(project_path)

    # Восстановление тоже через backup API (консистентно, без копирования живого файла)
    s = sqlite3.connect(str(src), timeout=10)
    try:
        d = sqlite3.connect(str(db_path), timeout=10)
        try:
            s.backup(d)
        finally:
            d.close()
    finally:
        s.close()
    logger.info("restored from %s", src)
    return True


def delete_backup(project_path: str, backup_path: str) -> bool:
    """Удаляет только файл внутри backups/. Требует project_path (защита от path traversal)."""
    try:
        p = _safe_backup_path(project_path, backup_path)
        p.unlink()
        return True
    except FileNotFoundError:
        return False
    except (ValueError, OSError) as e:
        logger.warning("delete_backup refused: %s", e)
        return False
