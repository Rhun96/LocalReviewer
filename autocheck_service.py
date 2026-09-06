import re
import hashlib
from datetime import datetime
from database import get_db_connection


# Типы автопроверок
CHECK_TYPES = [
    ('empty_text', 'Пустой текст'),
    ('too_short', 'Слишком короткий текст'),
    ('too_long', 'Слишком длинный текст'),
    ('has_url', 'Содержит URL'),
    ('has_email', 'Содержит email'),
    ('has_phone', 'Содержит телефон'),
    ('many_spaces', 'Много пробелов'),
    ('many_caps', 'Много заглавных букв'),
    ('duplicate', 'Точный дубль'),
]


def get_check_settings(project_path: str) -> dict:
    """Загружает настройки автопроверок из базы."""
    try:
        conn = get_db_connection(project_path)
        cursor = conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        settings = {row['key']: row['value'] for row in cursor.fetchall()}
        conn.close()
        
        return {
            'min_length': int(settings.get('checks_min_length', '10')),
            'max_length': int(settings.get('checks_max_length', '10000')),
            'check_url': settings.get('checks_url', 'true') == 'true',
            'check_email': settings.get('checks_email', 'true') == 'true',
            'check_phone': settings.get('checks_phone', 'true') == 'true',
            'check_spaces': settings.get('checks_spaces', 'true') == 'true',
            'check_caps': settings.get('checks_caps', 'true') == 'true',
        }
    except:
        return {
            'min_length': 10,
            'max_length': 10000,
            'check_url': True,
            'check_email': True,
            'check_phone': True,
            'check_spaces': True,
            'check_caps': True,
        }


def normalize_text(text: str) -> str:
    """Нормализует текст для сравнения."""
    if not text:
        return ''
    text = text.lower().strip()
    text = re.sub(r'\s+', ' ', text)
    return text


def compute_text_hash(text: str) -> str:
    """Вычисляет хэш нормализованного текста."""
    normalized = normalize_text(text)
    return hashlib.md5(normalized.encode()).hexdigest()


def check_case(case: dict, settings: dict = None) -> list:
    """
    Проверяет один кейс и возвращает список сработавших проверок.
    """
    if settings is None:
        settings = {
            'min_length': 10,
            'max_length': 10000,
            'check_url': True,
            'check_email': True,
            'check_phone': True,
            'check_spaces': True,
            'check_caps': True,
        }
    
    checks = []
    
    primary_text = case.get('primary_text') or ''
    response_text = case.get('response_text') or ''
    
    full_text = f"{primary_text} {response_text}".strip()
    
    # 1. Пустой текст
    if not full_text:
        checks.append(('empty_text', 'Пустой текст', 'Текст полностью пуст'))
    
    # 2. Слишком короткий текст
    if full_text and len(full_text) < settings.get('min_length', 10):
        checks.append(('too_short', 'Слишком короткий текст', f'Длина: {len(full_text)} символов'))
    
    # 3. Слишком длинный текст
    if full_text and len(full_text) > settings.get('max_length', 10000):
        checks.append(('too_long', 'Слишком длинный текст', f'Длина: {len(full_text)} символов'))
    
    # 4. URL
    if settings.get('check_url', True):
        url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
        urls = re.findall(url_pattern, full_text)
        if urls:
            checks.append(('has_url', 'Содержит URL', f'Найдено: {len(urls)}'))
    
    # 5. Email
    if settings.get('check_email', True):
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, full_text)
        if emails:
            checks.append(('has_email', 'Содержит email', f'Найдено: {len(emails)}'))
    
    # 6. Телефон
    if settings.get('check_phone', True):
        phone_pattern = r'(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}'
        phones = re.findall(phone_pattern, full_text)
        if phones:
            checks.append(('has_phone', 'Содержит телефон', f'Найдено: {len(phones)}'))
    
    # 7. Много пробелов
    if settings.get('check_spaces', True) and full_text:
        spaces_ratio = full_text.count(' ') / len(full_text)
        if spaces_ratio > 0.3:
            checks.append(('many_spaces', 'Много пробелов', f'{int(spaces_ratio * 100)}% текста'))
    
    # 8. Много заглавных букв
    if settings.get('check_caps', True) and full_text:
        letters = [c for c in full_text if c.isalpha()]
        if letters:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio > 0.5 and len(letters) > 10:
                checks.append(('many_caps', 'Много заглавных букв', f'{int(caps_ratio * 100)}% заглавных'))
    
    return checks


def run_autochecks(project_path: str, file_id: int = None) -> dict:
    """
    Запускает автопроверки для всех кейсов проекта или конкретного файла.
    """
    conn = get_db_connection(project_path)
    cursor = conn.cursor()
    
    # Загружаем настройки проверок
    settings = get_check_settings(project_path)
    
    # Получаем кейсы
    query = """
        SELECT case_id, primary_text, response_text
        FROM cases
    """
    params = []
    
    if file_id:
        query += " WHERE file_id = ?"
        params.append(file_id)
    
    cursor.execute(query, params)
    cases = cursor.fetchall()
    
    now = datetime.now().isoformat()
    total_flags = 0
    
    # Удаляем старые проверки
    if file_id:
        cursor.execute("""
            DELETE FROM case_checks 
            WHERE case_id IN (SELECT case_id FROM cases WHERE file_id = ?)
        """, (file_id,))
    else:
        cursor.execute("DELETE FROM case_checks")
    
    # Проверяем каждый кейс
    for case in cases:
        case_dict = dict(case)
        checks = check_case(case_dict, settings)
        
        for check_code, check_name, details in checks:
            cursor.execute("""
                INSERT INTO case_checks (case_id, check_code, check_name, details, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (case_dict['case_id'], check_code, check_name, details, now))
            total_flags += 1
    
    conn.commit()
    conn.close()
    
    return {
        'total_checked': len(cases),
        'flags_found': total_flags,
    }


def get_case_checks(project_path: str, case_id: int) -> list:
    """Возвращает автопроверки для конкретного кейса."""
    conn = get_db_connection(project_path)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT check_code, check_name, details, created_at
        FROM case_checks
        WHERE case_id = ?
        ORDER BY created_at DESC
    """, (case_id,))
    
    checks = [dict(row) for row in cursor.fetchall()]
    conn.close()
    
    return checks