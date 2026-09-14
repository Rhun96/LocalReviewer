"""Rules Engine (ТЗ §12-18): registry правил, severity, включаемость, новые проверки.

Важно (§18): автопроверка ≠ ошибка. Правила только подсвечивают повод проверить.
"""
import hashlib
import logging
import re
import unicodedata
from collections import Counter

from database import db, utcnow

logger = logging.getLogger(__name__)

# code -> {name, description, severity, setting}
RULES = {
    "empty_text": {"name": "Пустой текст", "description": "Текст полностью пуст",
                   "severity": "error", "setting": None},
    "too_short": {"name": "Слишком короткий текст", "description": "Длина меньше минимума",
                  "severity": "warning", "setting": None},
    "too_long": {"name": "Слишком длинный текст", "description": "Длина больше максимума",
                 "severity": "warning", "setting": None},
    "has_url": {"name": "Содержит URL", "description": "Найдена ссылка",
                "severity": "info", "setting": "check_url"},
    "has_email": {"name": "Содержит email", "description": "Найден email",
                  "severity": "info", "setting": "check_email"},
    "has_phone": {"name": "Содержит телефон", "description": "Найден RU-телефон",
                  "severity": "info", "setting": "check_phone"},
    "many_spaces": {"name": "Много пробелов", "description": "Доля пробелов > 30%",
                    "severity": "warning", "setting": "check_spaces"},
    "many_caps": {"name": "Много заглавных букв", "description": "CAPS > 50% при длине > 10",
                  "severity": "warning", "setting": "check_caps"},
    "duplicate": {"name": "Точный дубль", "description": "Нормализованный текст повторяется",
                  "severity": "warning", "setting": "check_duplicate"},
    "repeat_words": {"name": "Повтор слов", "description": "Одно слово подряд 3+ раз (да да да)",
                     "severity": "warning", "setting": "check_repeat_words"},
    "many_punct": {"name": "Много знаков", "description": "Серия !/? 5+ подряд",
                   "severity": "info", "setting": "check_punct"},
    "repeat_chars": {"name": "Повтор символов", "description": "Один символ 6+ подряд",
                     "severity": "info", "setting": "check_repeat_chars"},
    "long_sentence": {"name": "Длинное предложение", "description": "Предложение длиннее лимита",
                      "severity": "info", "setting": "check_long_sentence"},
    "junk_markers": {"name": "Служебный мусор", "description": "<END>/SYSTEM:/assistant: и т.п.",
                     "severity": "error", "setting": "check_junk"},
    "html_tags": {"name": "HTML-разметка", "description": "Найдены HTML-теги",
                  "severity": "info", "setting": "check_html"},
    "markdown_heavy": {"name": "Много Markdown", "description": "Заголовки/таблицы/код-блоки",
                       "severity": "info", "setting": "check_markdown"},
    "broken_encoding": {"name": "Битая кодировка", "description": "� или кракозябры",
                        "severity": "error", "setting": "check_encoding"},
    "suspicious_chars": {"name": "Подозрительные символы", "description": "Невидимки/управляющие",
                         "severity": "warning", "setting": "check_suspicious"},
}

CHECK_TYPES = [(code, meta["name"]) for code, meta in RULES.items()]

DEFAULTS = {
    "min_length": 10,
    "max_length": 10000,
    "max_sentence_len": 400,
    "check_url": True,
    "check_email": True,
    "check_phone": True,
    "check_spaces": True,
    "check_caps": True,
    "check_duplicate": True,
    "check_repeat_words": True,
    "check_punct": True,
    "check_repeat_chars": True,
    "check_long_sentence": True,
    "check_junk": True,
    "check_html": True,
    "check_markdown": True,
    "check_encoding": True,
    "check_suspicious": True,
}

_SETTING_KEYS = {
    "min_length": "checks_min_length",
    "max_length": "checks_max_length",
    "max_sentence_len": "checks_max_sentence_len",
    "check_url": "checks_url",
    "check_email": "checks_email",
    "check_phone": "checks_phone",
    "check_spaces": "checks_spaces",
    "check_caps": "checks_caps",
    "check_duplicate": "checks_duplicate",
    "check_repeat_words": "checks_repeat_words",
    "check_punct": "checks_punct",
    "check_repeat_chars": "checks_repeat_chars",
    "check_long_sentence": "checks_long_sentence",
    "check_junk": "checks_junk",
    "check_html": "checks_html",
    "check_markdown": "checks_markdown",
    "check_encoding": "checks_encoding",
    "check_suspicious": "checks_suspicious",
}


def rule_severity(code: str) -> str:
    return RULES.get(code, {}).get("severity", "warning")


def get_check_settings(project_path: str) -> dict:
    try:
        with db(project_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            raw = {row["key"]: row["value"] for row in cursor.fetchall()}
        out = {}
        for field, default in DEFAULTS.items():
            key = _SETTING_KEYS[field]
            val = raw.get(key)
            if isinstance(default, bool):
                out[field] = (val == "true") if val is not None else default
            else:
                try:
                    out[field] = int(val) if val is not None else default
                except ValueError:
                    out[field] = default
        return out
    except (OSError, RuntimeError) as e:
        logger.warning("check settings fallback: %s", e)
        return dict(DEFAULTS)


def normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKC", text).lower().strip()
    return re.sub(r"\s+", " ", text)


def compute_text_hash(text: str) -> str:
    return hashlib.sha256(normalize_text(text).encode("utf-8")).hexdigest()


def check_case(case: dict, settings: dict = None) -> list:
    """Возвращает [(code, name, details)] — severity смотрится через rule_severity(code)."""
    if settings is None:
        settings = dict(DEFAULTS)
    else:
        merged = dict(DEFAULTS)
        merged.update(settings)
        settings = merged

    def on(key: str) -> bool:
        return bool(settings.get(key, True))

    checks = []
    primary_text = case.get("primary_text") or ""
    response_text = case.get("response_text") or ""
    full_text = f"{primary_text} {response_text}".strip()

    if not full_text:
        checks.append(("empty_text", RULES["empty_text"]["name"], "Текст полностью пуст"))
        return checks
    if len(full_text) < settings.get("min_length", 10):
        checks.append(("too_short", RULES["too_short"]["name"],
                       f"Длина: {len(full_text)} символов"))
    if len(full_text) > settings.get("max_length", 10000):
        checks.append(("too_long", RULES["too_long"]["name"],
                       f"Длина: {len(full_text)} символов"))
    if on("check_url"):
        urls = re.findall(r"https?://[^\s<>\"']+|www\.[^\s<>\"']+", full_text)
        if urls:
            checks.append(("has_url", RULES["has_url"]["name"], f"Найдено: {len(urls)}"))
    if on("check_email"):
        emails = re.findall(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}", full_text)
        if emails:
            checks.append(("has_email", RULES["has_email"]["name"], f"Найдено: {len(emails)}"))
    if on("check_phone"):
        phones = re.findall(
            r"(\+7|8)[\s\-]?\(?\d{3}\)?[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2}", full_text)
        if phones:
            checks.append(("has_phone", RULES["has_phone"]["name"], f"Найдено: {len(phones)}"))
    if on("check_spaces") and len(full_text) >= 20:
        spaces = sum(1 for c in full_text if c.isspace())
        ratio = spaces / len(full_text)
        if ratio > 0.3:
            checks.append(("many_spaces", RULES["many_spaces"]["name"],
                           f"{int(ratio * 100)}% текста"))
    if on("check_caps"):
        letters = [c for c in full_text if c.isalpha()]
        if len(letters) > 10:
            caps_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
            if caps_ratio > 0.5:
                checks.append(("many_caps", RULES["many_caps"]["name"],
                               f"{int(caps_ratio * 100)}% заглавных"))
    if on("check_repeat_words"):
        m = re.search(r"(?i)\b(\w+)(?:\s+\1){2,}\b", full_text)
        if m:
            checks.append(("repeat_words", RULES["repeat_words"]["name"],
                           f"Повтор: «{m.group(0)[:40]}»"))
    if on("check_punct"):
        m = re.search(r"([!?])\1{4,}", full_text)
        if m:
            checks.append(("many_punct", RULES["many_punct"]["name"],
                           f"Серия: «{m.group(0)[:20]}»"))
    if on("check_repeat_chars"):
        m = re.search(r"(.)\1{5,}", full_text)
        if m and not m.group(0).strip("!?") == "":
            # исключаем пересечение с many_punct, если серия из !/?
            if not re.fullmatch(r"[!?]+", m.group(0)):
                checks.append(("repeat_chars", RULES["repeat_chars"]["name"],
                               f"Символ «{m.group(1)}» × {len(m.group(0))}"))
    if on("check_long_sentence"):
        limit = settings.get("max_sentence_len", 400)
        for sent in re.split(r"[.!?…\n]+", full_text):
            if len(sent.strip()) > limit:
                checks.append(("long_sentence", RULES["long_sentence"]["name"],
                               f"Предложение {len(sent.strip())} символов при лимите {limit}"))
                break
    if on("check_junk"):
        m = re.search(r"(?i)(<END>|SYSTEM\s*:|assistant\s*:|<\s*/?(system|human|assistant)[^>]*>)",
                      full_text)
        if m:
            checks.append(("junk_markers", RULES["junk_markers"]["name"],
                           f"Маркер: «{m.group(0)[:30]}»"))
    if on("check_html"):
        m = re.search(r"</?[a-zA-Z][^>]{0,60}>", full_text)
        if m:
            checks.append(("html_tags", RULES["html_tags"]["name"], "Найдена HTML-разметка"))
    if on("check_markdown"):
        md = len(re.findall(r"(?m)^(#{1,6}\s|```|\|.+\|)", full_text))
        if md >= 3:
            checks.append(("markdown_heavy", RULES["markdown_heavy"]["name"],
                           f"Markdown-блоков: {md}"))
    if on("check_encoding"):
        mixed = r"[А-Яа-яЁё][a-zA-Z]{3,}|[a-zA-Z][А-Яа-яЁё]{3,}"
        if "�" in full_text or re.search(mixed, full_text):
            checks.append(("broken_encoding", RULES["broken_encoding"]["name"],
                           "Возможна битая кодировка"))
    if on("check_suspicious"):
        bad = [c for c in full_text
               if unicodedata.category(c) in ("Cf", "Cc") and c not in ("\n", "\t")]
        if bad:
            checks.append(("suspicious_chars", RULES["suspicious_chars"]["name"],
                           f"Невидимых символов: {len(bad)}"))
    return checks


class Cancelled(Exception):
    """Отмена длительной операции пользователем."""


def run_autochecks(project_path: str, file_id: int = None,
                   progress_callback=None, cancel_event=None) -> dict:
    """Батчами по 2000, duplicate через hash-счётчик, severity в БД.

    Коммит после каждого батча: UI остаётся живым между чанками, прогресс
    отображается через progress_callback(done, total), отмена — через cancel_event.
    """
    import sqlite3 as _sqlite3
    from database import DB_TIMEOUT
    from pathlib import Path as _Path

    settings = get_check_settings(project_path)
    db_path = _Path(project_path) / "project.sqlite"
    conn = _sqlite3.connect(str(db_path), timeout=DB_TIMEOUT)
    conn.row_factory = _sqlite3.Row
    try:
        from database import _apply_pragmas
        _apply_pragmas(conn)
        cursor = conn.cursor()
        # Отдельный курсор для записи: executemany тем же курсором,
        # которым идёт fetchmany SELECT, обрывает итерацию (проверено: 3000 -> 2000).
        wcur = conn.cursor()
        total = cursor.execute(
            "SELECT COUNT(*) AS c FROM cases" + (" WHERE file_id = ?" if file_id else ""),
            ([file_id] if file_id else [])).fetchone()["c"]
        if file_id:
            cursor.execute(
                "DELETE FROM case_checks WHERE case_id IN "
                "(SELECT case_id FROM cases WHERE file_id = ?)",
                (file_id,),
            )
        else:
            cursor.execute("DELETE FROM case_checks")
        conn.commit()

        base = "SELECT case_id, primary_text, response_text FROM cases"
        params: list = []
        if file_id:
            base += " WHERE file_id = ?"
            params.append(file_id)

        now = utcnow()
        total_checked = 0
        total_flags = 0
        batch: list = []

        def flush():
            nonlocal batch, total_flags
            if batch:
                wcur.executemany("""
                    INSERT INTO case_checks
                        (case_id, check_code, check_name, details, severity, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, batch)
                batch = []
                conn.commit()
            if progress_callback and total:
                try:
                    progress_callback(total_checked, total)
                except Exception:
                    pass

        cursor.execute(base, params)
        while True:
            if cancel_event is not None and cancel_event.is_set():
                conn.commit()
                raise Cancelled(f"Прервано пользователем: проверено {total_checked} из {total}")
            rows = cursor.fetchmany(2000)
            if not rows:
                break
            hashes = [compute_text_hash(f"{r['primary_text'] or ''} {r['response_text'] or ''}")
                      for r in rows]
            counts = Counter(hashes)
            for case, h in zip(rows, hashes, strict=True):
                total_checked += 1
                d = {"primary_text": case["primary_text"], "response_text": case["response_text"]}
                flags = check_case(d, settings)
                if settings.get("check_duplicate", True) and counts[h] > 1:
                    flags.append(("duplicate", RULES["duplicate"]["name"],
                                  f"Повторов в выборке: {counts[h]}"))
                for code, name, details in flags:
                    batch.append((case["case_id"], code, name, details, rule_severity(code), now))
                    total_flags += 1
                if len(batch) >= 2000:
                    flush()
            flush()
        if progress_callback and total:
            try:
                progress_callback(total, total)
            except Exception:
                pass
        return {"total_checked": total_checked, "flags_found": total_flags}
    except Cancelled:
        raise
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


def get_case_checks(project_path: str, case_id: int) -> list:
    with db(project_path) as conn:
        cursor = conn.cursor()
        cols = [r[1] for r in cursor.execute("PRAGMA table_info(case_checks)").fetchall()]
        if "severity" in cols:
            cursor.execute("""
                SELECT check_code, check_name, details, severity, created_at
                FROM case_checks WHERE case_id = ? ORDER BY created_at DESC
            """, (case_id,))
            rows = cursor.fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d.setdefault("severity", rule_severity(d.get("check_code", "")))
                out.append(d)
            return out
        cursor.execute("""
            SELECT check_code, check_name, details, created_at
            FROM case_checks WHERE case_id = ? ORDER BY created_at DESC
        """, (case_id,))
        out = []
        for r in cursor.fetchall():
            d = dict(r)
            d["severity"] = rule_severity(d.get("check_code", ""))
            out.append(d)
        return out
