"""Regression assertions V2.1 §15: формальные проверки ответа без LLM.

Assertion отвечает только «нарушено ли формальное условие», а не
«хорош ли ответ». Результат PASS/FAIL/SKIPPED на каждый (stable_key,
assertion). Результаты НЕ хранятся — считаются на лету, иначе протухают
при каждом новом прогоне. Массовый запуск — через workers (прогресс,
отмена через Cancelled).
"""
import json
import logging
import re

from constants import ASSERTION_SEVERITIES
from database import db, utcnow
from workers import Cancelled

logger = logging.getLogger(__name__)

TYPES = ("not_empty", "min_length", "max_length", "contains", "not_contains",
         "regex", "exact_match", "contains_url", "contains_email",
         "contains_phone", "contains_keyword", "no_service_text")

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_PHONE_RE = re.compile(r"(?:\+7|8)[\s\-()]?\d{3}[\s\-()]?\d{3}[\s\-()]?\d{2}"
                       r"[\s\-()]?\d{2}")
_JUNK_RES = (
    re.compile(r"<END>", re.IGNORECASE),
    re.compile(r"^\s*SYSTEM\s*:", re.IGNORECASE | re.MULTILINE),
    re.compile(r"^\s*assistant\s*:", re.IGNORECASE | re.MULTILINE),
)


def _params(assertion: dict) -> dict:
    raw = assertion.get("params_json") or assertion.get("params") or "{}"
    if isinstance(raw, dict):
        return raw
    try:
        p = json.loads(raw)
        return p if isinstance(p, dict) else {}
    except Exception:
        return {}


def evaluate(assertion: dict, answer_text: str | None):
    """Одна проверка. Возвращает (result, detail). Не бросает исключений."""
    atype = (assertion.get("atype") or "").strip()
    text = answer_text if isinstance(answer_text, str) else ""
    try:
        p = _params(assertion)
        if atype == "not_empty":
            return ("PASS", "") if text.strip() else ("FAIL", "пустой ответ")
        if atype == "min_length":
            try:
                n = int(p.get("n", p.get("min", "")))
            except (TypeError, ValueError):
                return ("SKIPPED", "нет параметра n")
            return ("PASS", "") if len(text) >= n else ("FAIL", f"len {len(text)} < {n}")
        if atype == "max_length":
            try:
                n = int(p.get("n", p.get("max", "")))
            except (TypeError, ValueError):
                return ("SKIPPED", "нет параметра n")
            return ("PASS", "") if len(text) <= n else ("FAIL", f"len {len(text)} > {n}")
        if atype == "contains":
            needle = str(p.get("text", p.get("value", "")) or "")
            if not needle:
                return ("SKIPPED", "пустой эталон")
            return ("PASS", "") if needle in text else ("FAIL", "нет подстроки")
        if atype == "not_contains":
            needle = str(p.get("text", p.get("value", "")) or "")
            if not needle:
                return ("SKIPPED", "пустой эталон")
            return ("PASS", "") if needle not in text else ("FAIL", "запретная подстрока")
        if atype == "regex":
            pattern = str(p.get("pattern", p.get("text", "")) or "")
            if not pattern:
                return ("SKIPPED", "пустой pattern")
            try:
                rx = re.compile(pattern)
            except re.error as e:
                return ("SKIPPED", f"битый regex: {e}")
            return ("PASS", "") if rx.search(text) else ("FAIL", "нет совпадения")
        if atype == "exact_match":
            needle = str(p.get("text", p.get("value", "")) or "")
            if not needle:
                return ("SKIPPED", "пустой эталон")
            return ("PASS", "") if text == needle else ("FAIL", "не совпало")
        if atype == "contains_url":
            return ("PASS", "") if _URL_RE.search(text) else ("FAIL", "нет URL")
        if atype == "contains_email":
            return ("PASS", "") if _EMAIL_RE.search(text) else ("FAIL", "нет email")
        if atype == "contains_phone":
            return ("PASS", "") if _PHONE_RE.search(text) else ("FAIL", "нет телефона")
        if atype == "contains_keyword":
            kws = p.get("keywords", p.get("text", p.get("value", "")))
            if isinstance(kws, str):
                kws = [kws] if kws.strip() else []
            kws = [str(k) for k in (kws or []) if str(k).strip()]
            if not kws:
                return ("SKIPPED", "нет ключевых слов")
            low = text.lower()
            hit = next((k for k in kws if k.lower() in low), None)
            return ("PASS", hit or "") if hit else ("FAIL", "нет ключевых слов")
        if atype == "no_service_text":
            hit = next((r for r in _JUNK_RES if r.search(text)), None)
            return ("PASS", "") if not hit else ("FAIL", f"мусор: {hit.pattern[:24]}")
        return ("SKIPPED", f"неизвестный тип {atype!r}")
    except Exception as e:
        logger.warning("assertion evaluate failed: %s", e)
        return ("SKIPPED", "ошибка проверки")


# --- CRUD ---

def list_assertions(project_path: str, enabled_only: bool = False) -> list:
    with db(project_path) as conn:
        q = "SELECT * FROM assertions"
        if enabled_only:
            q += " WHERE enabled = 1"
        q += " ORDER BY assert_id"
        return [dict(r) for r in conn.execute(q).fetchall()]


def create_assertion(project_path: str, name: str, atype: str,
                     params: dict | None = None,
                     enabled: bool = True,
                     severity: str = "warning") -> int:
    name = (name or "").strip()
    if not name or len(name) > 128:
        raise ValueError("Название 1–128 символов")
    if atype not in TYPES:
        raise ValueError(f"Плохой тип: {atype!r}")
    if severity not in ASSERTION_SEVERITIES:
        raise ValueError(f"Плохой severity: {severity!r}")
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.execute(
            "INSERT INTO assertions (name, atype, params_json, enabled, severity,"
            " created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (name, atype, json.dumps(params or {}, ensure_ascii=False),
             1 if enabled else 0, severity, now, now))
        return cur.lastrowid


def update_assertion(project_path: str, assert_id: int, **patch) -> None:
    allowed = ("name", "atype", "params_json", "params", "enabled", "severity")
    sets, vals = [], []
    for k in allowed:
        if k not in patch or patch[k] is None:
            continue
        if k == "name":
            v = str(patch[k]).strip()
            if not v or len(v) > 128:
                raise ValueError("Название 1–128 символов")
            sets.append("name=?")
            vals.append(v)
        elif k == "atype":
            if patch[k] not in TYPES:
                raise ValueError(f"Плохой тип: {patch[k]!r}")
            sets.append("atype=?")
            vals.append(patch[k])
        elif k in ("params_json", "params"):
            v = patch[k]
            if isinstance(v, dict):
                v = json.dumps(v, ensure_ascii=False)
            sets.append("params_json=?")
            vals.append(v)
        elif k == "enabled":
            sets.append("enabled=?")
            vals.append(1 if patch[k] else 0)
        elif k == "severity":
            if patch[k] not in ASSERTION_SEVERITIES:
                raise ValueError(f"Плохой severity: {patch[k]!r}")
            sets.append("severity=?")
            vals.append(patch[k])
    if not sets:
        return
    sets.append("updated_at=?")
    vals.append(utcnow())
    vals.append(assert_id)
    with db(project_path) as conn:
        cur = conn.execute(
            f"UPDATE assertions SET {', '.join(sets)} WHERE assert_id=?", vals)
        if cur.rowcount == 0:
            raise ValueError("Проверка не найдена")


def delete_assertion(project_path: str, assert_id: int) -> None:
    with db(project_path) as conn:
        cur = conn.execute("DELETE FROM assertions WHERE assert_id=?", (assert_id,))
        if cur.rowcount == 0:
            raise ValueError("Проверка не найдена")


# --- массовый запуск ---

def run_assertions(project_path: str, run_id: int,
                   assertions: list | None = None,
                   progress_cb=None, cancel_flag=None) -> dict:
    """stable_key -> {passed, failed, failed_critical, details}.

    Отмена: cancel_flag() is True или Cancelled из progress_cb.
    """
    if assertions is None:
        assertions = [a for a in list_assertions(project_path)
                      if a.get("enabled")]
    with db(project_path) as conn:
        answers = conn.execute(
            "SELECT stable_key, answer_text FROM run_answers WHERE run_id=?",
            (run_id,)).fetchall()
        answers = [dict(r) for r in answers]
    out: dict = {}
    total = max(1, len(answers))
    for i, ans in enumerate(answers):
        if cancel_flag is not None:
            try:
                if cancel_flag():
                    raise Cancelled("отменено пользователем")
            except Cancelled:
                raise
            except Exception:
                pass
        passed, failed, crit, details = 0, 0, 0, []
        for a in assertions:
            try:
                res, detail = evaluate(a, ans.get("answer_text"))
            except Exception:
                res, detail = "SKIPPED", "ошибка"
            if res == "PASS":
                passed += 1
            elif res == "FAIL":
                failed += 1
                if (a.get("severity") or "warning") == "critical":
                    crit += 1
                details.append({"name": a.get("name", ""), "detail": detail,
                                "severity": a.get("severity", "warning")})
            if progress_cb is not None:
                try:
                    progress_cb(int((i * len(assertions) + 1) * 100
                                    // (total * max(1, len(assertions)))))
                except Cancelled:
                    raise
                except Exception:
                    pass
        out[ans["stable_key"]] = {"passed": passed, "failed": failed,
                                  "failed_critical": crit, "details": details}
    return out


def summarize(results: dict) -> dict:
    """Сводка для gate-учёта (опционального): failed всего/критических."""
    failed = sum(1 for v in results.values() if v["failed"] > 0)
    crit = sum(1 for v in results.values() if v["failed_critical"] > 0)
    checked = len(results)
    return {"checked": checked, "failed": failed, "failed_critical": crit}
