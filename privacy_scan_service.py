"""Privacy Scan перед экспортом (ТЗ V2.2 §4): только stdlib, без LLM.

Сканируем очевидные шаблоны:
- EMAIL, PHONE (RU/KZ/BY-форматы через +7/8/+375), URL, POSSIBLE_SECRET
  (api-ключи/токены/приватные ключи).

PERSON осознанно НЕ делаем (без NER одни ложные срабатывания) — решение
пользователя. Credit-card-паттерны выключены по умолчанию (много FP на
номерах обращений): считать умеем, но в has_sensitive не учитываем, пока
пользователь явно не попросит.

Формулировки только «возможный/похож на/обнаружен шаблон» — сканер никогда
не утверждает, что значение точно секрет.
"""
import logging
import re

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(
    r"(?:\+7|8|\+375)[\s\-()]?\d[\d\s\-()]{7,}\d")
URL_RE = re.compile(
    r"https?://[^\s<>\"]+|www\.[^\s<>\"]+")

_SECRET_PATTERNS = (
    r"sk-[A-Za-z0-9]{8,}",
    r"ghp_[A-Za-z0-9]{8,}",
    r"gho_[A-Za-z0-9]{8,}",
    r"AKIA[0-9A-Z]{16}",
    r"xox[bpas]-[A-Za-z0-9-]{6,}",
    r"api[_-]?key\s*[:=]\s*\S+",
    r"secret\s*[:=]\s*\S+",
    r"token\s*[:=]\s*\S+",
    r"Bearer\s+[A-Za-z0-9\-._~+/]+=*",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)
SECRET_RE = re.compile("|".join(_SECRET_PATTERNS), re.IGNORECASE)

# Карты: номер обращения и т.п. — держим консервативно, off по умолчанию.
CARD_RE = re.compile(r"\b(?:\d[ \-]?){13,19}\b")


def _count(rx: re.Pattern, text: str) -> int:
    try:
        return len(rx.findall(text or ""))
    except Exception:
        return 0


def scan_text(text: str, *, cards: bool = False) -> dict:
    """Подсчёт шаблонов в одном тексте. Пустые/Unicode — безопасно."""
    s = text if isinstance(text, str) else ("" if text is None else str(text))
    out = {
        "emails": _count(EMAIL_RE, s),
        "phones": _count(PHONE_RE, s),
        "urls": _count(URL_RE, s),
        "secrets": _count(SECRET_RE, s),
    }
    if cards:
        out["cards"] = _count(CARD_RE, s)
    return out


def merge(*scans: dict) -> dict:
    out = {"emails": 0, "phones": 0, "urls": 0, "secrets": 0}
    for s in scans:
        for k in out:
            try:
                out[k] += int(s.get(k, 0) or 0)
            except (TypeError, ValueError):
                pass
    return out


def scan_export(project_path: str, file_id=None, *,
                limit: int = 100000) -> dict:
    """Сводка для диалога перед экспортом: счётчики + скан текстов.

    Возвращает: cases, comments, emails, phones, urls, secrets,
    has_sensitive (True если хоть один шаблон > 0).
    Читает только нужные колонки, батчами; контент за пределы функции
    не утекает (только счётчики — в лог можно счётчики, не тексты).
    """
    from database import db
    cases = 0
    comments = 0
    total = {"emails": 0, "phones": 0, "urls": 0, "secrets": 0}
    try:
        with db(project_path) as conn:
            cur = conn.cursor()
            cond = "WHERE COALESCE(c.hidden, 0) = 0"
            params: list = []
            if file_id:
                cond += " AND c.file_id = ?"
                params.append(file_id)
            cur.execute(f"SELECT COUNT(*) AS c FROM cases c {cond}", params)
            row = cur.fetchone()
            cases = int(row["c"]) if row else 0
            cur.execute(
                f"SELECT c.primary_text, c.response_text, a.comment "
                f"FROM cases c LEFT JOIN annotations a ON a.case_id = c.case_id "
                f"{cond} ORDER BY c.case_id", params)
            seen = 0
            while True:
                batch = cur.fetchmany(2000)
                if not batch:
                    break
                for r in batch:
                    seen += 1
                    if seen > limit:
                        break
                    if r["comment"]:
                        comments += 1
                    for col in ("primary_text", "response_text", "comment"):
                        v = r[col]
                        if v:
                            s = scan_text(v)
                            for k in total:
                                total[k] += s[k]
                if seen > limit:
                    break
    except Exception as e:
        logger.warning("privacy scan failed: %s", e)
    has_sensitive = any(total.values())
    out = {"cases": cases, "comments": comments, **total,
           "has_sensitive": has_sensitive}
    logger.info("privacy scan: cases=%s comments=%s sensitive=%s",
                cases, comments, has_sensitive)
    return out


def summary_lines(summary: dict) -> list:
    """Строки для диалога («17 возможных телефонов» — без утверждений)."""
    lines = []
    if summary.get("phones"):
        lines.append(f"{summary['phones']} возможных телефонов")
    if summary.get("emails"):
        lines.append(f"{summary['emails']} возможных email")
    if summary.get("urls"):
        lines.append(f"{summary['urls']} возможных URL")
    if summary.get("secrets"):
        lines.append(f"{summary['secrets']} возможных token/секретов")
    return lines
