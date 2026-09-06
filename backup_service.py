import shutil
from pathlib import Path
from datetime import datetime


def create_backup(project_path: str) -> str:
    """
    Создаёт резервную копию базы данных проекта.
    Возвращает путь к созданной копии.
    """
    project_dir = Path(project_path)
    db_path = project_dir / "project.sqlite"
    
    if not db_path.exists():
        raise Exception("База данных не найдена")
    
    # Создаём папку backups если её нет
    backups_dir = project_dir / "backups"
    backups_dir.mkdir(exist_ok=True)
    
    # Имя файла с таймстампом
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"project_backup_{timestamp}.sqlite"
    backup_path = backups_dir / backup_name
    
    # Копируем файл
    shutil.copy2(db_path, backup_path)
    
    return str(backup_path)


def get_backups_list(project_path: str) -> list:
    """Возвращает список резервных копий."""
    project_dir = Path(project_path)
    backups_dir = project_dir / "backups"
    
    if not backups_dir.exists():
        return []
    
    backups = []
    for file in backups_dir.glob("project_backup_*.sqlite"):
        stat = file.stat()
        backups.append({
            'path': str(file),
            'name': file.name,
            'size': stat.st_size,
            'created': datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    
    # Сортируем по дате (новые первые)
    backups.sort(key=lambda x: x['created'], reverse=True)
    
    return backups


def restore_backup(project_path: str, backup_path: str) -> bool:
    """
    Восстанавливает базу данных из резервной копии.
    Перед восстановлением создаёт текущую копию.
    """
    project_dir = Path(project_path)
    db_path = project_dir / "project.sqlite"
    
    if not Path(backup_path).exists():
        raise Exception("Резервная копия не найдена")
    
    # Создаём резервную копию текущей базы
    if db_path.exists():
        create_backup(project_path)
    
    # Восстанавливаем
    shutil.copy2(backup_path, db_path)
    
    return True


def delete_backup(backup_path: str) -> bool:
    """Удаляет резервную копию."""
    try:
        Path(backup_path).unlink()
        return True
    except:
        return False