"""Rules Engine (ТЗ §12-18): registry правил, severity, включаемость, новые проверки.

Важно (§18): автопроверка ≠ ошибка. Правила только подсвечивают повод проверить.
"""
import hashlib
import logging
import re
import unicodedata
from collections import Counter

from database import db, utcnow
from workers import Cancelled

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


def reset_checks(project_path: str, case_ids: list | None = None,
                 file_id: int | None = None) -> int:
    """Сбросить автопроверки: вся БД, файл или явная выборка. Возвращает число удалённых."""
    from database import db as _db
    with _db(project_path) as conn:
        cur = conn.cursor()
        if case_ids is not None:
            ids = list(dict.fromkeys(int(c) for c in case_ids))
            if not ids:
                return 0
            done = 0
            for i in range(0, len(ids), 500):
                chunk = ids[i:i + 500]
                ph = ",".join(["?"] * len(chunk))
                cur.execute(f"DELETE FROM case_checks WHERE case_id IN ({ph})", chunk)
                done += cur.rowcount or 0
            return done
        if file_id is not None:
            cur.execute("DELETE FROM case_checks WHERE case_id IN "
                        "(SELECT case_id FROM cases WHERE file_id = ?)", (file_id,))
        else:
            cur.execute("DELETE FROM case_checks")
        return cur.rowcount or 0


def run_autochecks(project_path: str, file_id: int = None, case_ids: list | None = None,
                   progress_callback=None, cancel_event=None) -> dict:
    """Батчами по 2000, duplicate через глобальный hash-счётчик, severity в БД.

    Дубли считаются по ВСЕЙ выборке (два прохода), а не внутри батча 2000 —
    иначе дубль через границу батчей терялся.
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
        sel_ids = (list(dict.fromkeys(int(c) for c in case_ids))
                   if case_ids is not None else None)
        if sel_ids is not None and not sel_ids:
            return {"total_checked": 0, "flags_found": 0}
        if sel_ids is not None:
            total = len(sel_ids)
        else:
            total = cursor.execute(
                "SELECT COUNT(*) AS c FROM cases" + (" WHERE file_id = ?" if file_id else ""),
                ([file_id] if file_id else [])).fetchone()["c"]
        if sel_ids is not None:
            for i in range(0, len(sel_ids), 500):
                chunk = sel_ids[i:i + 500]
                ph = ",".join(["?"] * len(chunk))
                cursor.execute(f"DELETE FROM case_checks WHERE case_id IN ({ph})", chunk)
        elif file_id:
            cursor.execute(
                "DELETE FROM case_checks WHERE case_id IN "
                "(SELECT case_id FROM cases WHERE file_id = ?)",
                (file_id,),
            )
        else:
            cursor.execute("DELETE FROM case_checks")
        conn.commit()

        chunks: list = []
        if sel_ids is not None:
            for i in range(0, len(sel_ids), 500):
                chunk = sel_ids[i:i + 500]
                ph = ",".join(["?"] * len(chunk))
                chunks.append((
                    "SELECT case_id, primary_text, response_text FROM cases "
                    f"WHERE case_id IN ({ph})", chunk))
        else:
            base = "SELECT case_id, primary_text, response_text FROM cases"
            params: list = []
            if file_id:
                base += " WHERE file_id = ?"
                params.append(file_id)
            chunks.append((base, params))

        # Проход 1: глобальные счётчики хэшей для duplicate (вся выборка).
        global_counts: Counter = Counter()
        if settings.get("check_duplicate", True):
            for query, qparams in chunks:
                cursor.execute(query, qparams)
                while True:
                    if cancel_event is not None and cancel_event.is_set():
                        raise Cancelled(
                            f"Прервано пользователем: проверено 0 из {total}")
                    rows = cursor.fetchmany(2000)
                    if not rows:
                        break
                    for r in rows:
                        h = compute_text_hash(
                            f"{r['primary_text'] or ''} {r['response_text'] or ''}")
                        global_counts[h] += 1

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

        for query, qparams in chunks:
            cursor.execute(query, qparams)
            while True:
                if cancel_event is not None and cancel_event.is_set():
                    conn.commit()
                    raise Cancelled(
                        f"Прервано пользователем: проверено {total_checked} из {total}")
                rows = cursor.fetchmany(2000)
                if not rows:
                    break
                for case in rows:
                    total_checked += 1
                    d = {"primary_text": case["primary_text"],
                         "response_text": case["response_text"]}
                    flags = check_case(d, settings)
                    if settings.get("check_duplicate", True):
                        h = compute_text_hash(
                            f"{case['primary_text'] or ''} {case['response_text'] or ''}")
                        if global_counts[h] > 1:
                            flags.append(("duplicate", RULES["duplicate"]["name"],
                                          f"Повторов в выборке: {global_counts[h]}"))
                    for code, name, details in flags:
                        batch.append((case["case_id"], code, name, details,
                                      rule_severity(code), now))
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


def ensure_case_check(project_path: str, case_id: int, code: str,
                      name: str, details: str | None = None) -> None:
    """Гарантирует строку case_checks для вердикта без полного пересчёта.

    Живые проверки кейса видны сразу, а в БД попадают только по
    «Пересчитать проверки». Вердикт на несохранённую сработку сначала
    фиксирует саму сработку (иначе precision в отчётах её не увидит),
    затем пишется как обычно через set_check_verdict.
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        hit = cur.execute("SELECT 1 FROM case_checks WHERE case_id=? AND check_code=?",
                          (case_id, code)).fetchone()
        if hit:
            return
        cur.execute("""
            INSERT INTO case_checks
                (case_id, check_code, check_name, details, severity, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (case_id, code, name, details or "", rule_severity(code), utcnow()))


VERDICTS = ("confirmed", "false_positive")


def set_check_verdict(project_path: str, case_id: int, check_code: str,
                      verdict: str | None) -> None:
    """Вердикт человека по срабатыванию (ТЗ §75): confirmed / false_positive.

    verdict=None — снять вердикт. Пишет историю CHECK (check_confirmed /
    check_rejected) — по ней считается precision правил.
    """
    if verdict is not None and verdict not in VERDICTS:
        raise ValueError(f"Плохой вердикт: {verdict!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        old = cur.execute("SELECT verdict FROM case_check_verdicts "
                          "WHERE case_id=? AND check_code=?",
                          (case_id, check_code)).fetchone()
        if verdict is None:
            cur.execute("DELETE FROM case_check_verdicts WHERE case_id=? AND check_code=?",
                        (case_id, check_code))
        else:
            cur.execute("""
                INSERT INTO case_check_verdicts (case_id, check_code, verdict, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(case_id, check_code) DO UPDATE SET
                    verdict=?, updated_at=?
            """, (case_id, check_code, verdict, now, verdict, now))
        old_v = old["verdict"] if old else None
        if old_v != verdict:
            event = ("check_confirmed" if verdict == "confirmed"
                     else "check_rejected" if verdict == "false_positive"
                     else "check_verdict_cleared")
            cur.execute("""
                INSERT INTO history (case_id, event_type, field_name, old_value,
                                     new_value, created_at)
                VALUES (?, ?, 'check', ?, ?, ?)
            """, (case_id, event, check_code, verdict or "", now))


def get_check_verdicts(project_path: str, case_id: int) -> dict:
    """check_code -> verdict для кейса."""
    with db(project_path) as conn:
        rows = conn.cursor().execute(
            "SELECT check_code, verdict FROM case_check_verdicts WHERE case_id=?",
            (case_id,)).fetchall()
        return {r["check_code"]: r["verdict"] for r in rows}


def get_checks_precision(project_path: str, file_id: int | None = None) -> list:
    """Precision правил (ТЗ §75-76): confirmed / все с вердиктом.

    Строки: check_code, check_name, triggered (кейсов), verdicts, confirmed,
    false_positive, precision (None без вердиктов). Низкий precision =
    правило бесполезно для датасета (feedback loop).
    """
    with db(project_path) as conn:
        cur = conn.cursor()
        if file_id is not None:
            scope = "WHERE cc.case_id IN (SELECT case_id FROM cases WHERE file_id = ?)"
            params: list = [file_id]
        else:
            scope, params = "", []
        rows = cur.execute(f"""
            SELECT cc.check_code AS check_code,
                   MIN(cc.check_name) AS check_name,
                   COUNT(DISTINCT cc.case_id) AS triggered,
                   COUNT(DISTINCT v.case_id) AS verdicts,
                   COUNT(DISTINCT CASE WHEN v.verdict='confirmed' THEN v.case_id END)
                       AS confirmed,
                   COUNT(DISTINCT CASE WHEN v.verdict='false_positive' THEN v.case_id END)
                       AS false_positive
            FROM case_checks cc
            LEFT JOIN case_check_verdicts v
              ON v.case_id = cc.case_id AND v.check_code = cc.check_code
            {scope}
            GROUP BY cc.check_code
            ORDER BY triggered DESC
        """, params).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            d["precision"] = (d["confirmed"] / d["verdicts"]
                              if d["verdicts"] else None)
            out.append(d)
        return out
