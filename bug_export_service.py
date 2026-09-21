"""Экспорт Bug Report текстом (ТЗ V2 §9): Jira / Markdown / Plain Text.

Архитектура: Bug Report -> formatters. API-адаптеры трекеров добавятся
позже без изменения UI (тот же вход — dict бага).
"""
import bug_report_service as bugs


def _ctx_lines(bug: dict) -> list:
    lines = []
    if bug.get("model_name"):
        ver = f" {bug['model_version']}" if bug.get("model_version") else ""
        lines.append(("Model", f"{bug['model_name']}{ver}"))
    if bug.get("prompt_version"):
        lines.append(("Prompt version", bug["prompt_version"]))
    if bug.get("system_prompt_version"):
        lines.append(("System prompt", bug["system_prompt_version"]))
    if bug.get("category_name"):
        cat = bug["category_name"]
        if bug.get("subcategory_name"):
            cat += f" → {bug['subcategory_name']}"
        lines.append(("Category", cat))
    for c in bug.get("cases", []):
        q = (c.get("primary_text") or "")[:300]
        lines.append((f"Case {c.get('source_id') or c['case_id']}", q))
    return lines


class JiraFormatter:
    """Готовая карточка для вставки в Jira (текстом, без API)."""

    @staticmethod
    def format(bug: dict) -> str:
        parts = [f"*Баг #{bug['bug_id']}: {bug['title']}*",
                 f"Severity: {bug['severity']} | Status: {bug['status']}"]
        if bug.get("description"):
            parts += ["", "*Описание:*", bug["description"]]
        parts += ["", "*Фактическое поведение:*",
                  bug.get("actual_behavior") or "—"]
        parts += ["", "*Ожидаемое поведение:*",
                  bug.get("expected_behavior") or "—"]
        ctx = _ctx_lines(bug)
        if ctx:
            parts.append("")
            parts.append("*Контекст воспроизведения:*")
            parts.extend(f"- {k}: {v}" for k, v in ctx)
        if bug.get("external_id"):
            parts.append(f"External: {bug.get('external_tracker', '')} "
                         f"{bug['external_id']}".rstrip())
        return "\n".join(parts)


class MarkdownFormatter:
    @staticmethod
    def format(bug: dict) -> str:
        parts = [f"# Bug #{bug['bug_id']}: {bug['title']}", "",
                 f"**Severity:** {bug['severity']} | **Status:** {bug['status']}"]
        if bug.get("description"):
            parts += ["", "## Описание", "", bug["description"]]
        parts += ["", "## Фактическое поведение", "",
                  bug.get("actual_behavior") or "—"]
        parts += ["", "## Ожидаемое поведение", "",
                  bug.get("expected_behavior") or "—"]
        ctx = _ctx_lines(bug)
        if ctx:
            parts += ["", "## Контекст", ""]
            parts.extend(f"- **{k}:** {v}" for k, v in ctx)
        if bug.get("external_url"):
            parts += ["", f"External: [{bug.get('external_id', '')}]"
                          f"({bug['external_url']})"]
        elif bug.get("external_id"):
            parts += ["", f"External: {bug.get('external_tracker', '')} "
                          f"{bug['external_id']}".rstrip()]
        return "\n".join(parts)


class PlainTextFormatter:
    @staticmethod
    def format(bug: dict) -> str:
        parts = [f"Баг #{bug['bug_id']}: {bug['title']}",
                 f"Severity: {bug['severity']} | Status: {bug['status']}"]
        if bug.get("description"):
            parts += ["", f"Описание: {bug['description']}"]
        parts += ["", f"Факт: {bug.get('actual_behavior') or '—'}",
                  f"Ожидание: {bug.get('expected_behavior') or '—'}"]
        for k, v in _ctx_lines(bug):
            parts.append(f"{k}: {v}")
        return "\n".join(parts)


FORMATTERS = {"jira": JiraFormatter, "markdown": MarkdownFormatter,
              "plain": PlainTextFormatter}


def render(project_path: str, bug_id: int, fmt: str) -> str:
    """Текст бага в формате jira/markdown/plain (для копирования)."""
    if fmt not in FORMATTERS:
        raise ValueError(f"Плохой формат: {fmt!r}")
    bug = bugs.get_bug(project_path, bug_id)
    if not bug:
        raise ValueError("Баг не найден")
    return FORMATTERS[fmt].format(bug)


def render_case(project_path: str, case_id: int, fmt: str) -> str:
    """Контекст кейса одним действием (V2.1 §8): Markdown/Plain в буфер.

    Поля: CASE ID / SOURCE ID / QUERY / MODEL RESPONSE / REFERENCE / STATUS /
    CATEGORY / SUBCATEGORY / SEVERITY / COMMENT / AUTOCHECK RESULTS / MODEL /
    MODEL VERSION / PROMPT VERSION / SYSTEM PROMPT VERSION.
    Без диалогов, UTF-8, пустые — пустыми, большие поля не режем.
    """
    if fmt not in ("markdown", "plain"):
        raise ValueError(f"Плохой формат: {fmt!r}")
    from bug_report_service import build_from_case
    pre = build_from_case(project_path, case_id)
    # Статус/коммент/категория/тяжесть — из разметки, не из pseudo-бага.
    status = pre.get("review_status", "") or ""
    comment = pre.get("review_comment", "") or ""
    category = pre.get("category_name") or ""
    subcategory = pre.get("subcategory_name") or ""
    case_sev = ""
    try:
        from database import db as _db
        with _db(project_path) as _conn:
            _err = _conn.execute(
                "SELECT severity FROM case_errors WHERE case_id=?",
                (case_id,)).fetchone()
            if _err and _err["severity"]:
                case_sev = _err["severity"]
    except Exception:
        pass
    checks_lines: list = []
    try:
        from autocheck_service import check_case as _cc, get_check_settings as _gcs
        try:
            _settings = _gcs(project_path)
        except Exception:
            _settings = None
        for code, name, details in _cc({"primary_text": pre.get("query", ""),
                                        "response_text": pre.get("model_response", "")},
                                       _settings):
            checks_lines.append(f"{code}: {name}" + (f" ({details})" if details else ""))
    except Exception:
        pass
    if fmt == "markdown":
        parts = [f"# Кейс #{case_id}", ""]
        rows = [
            ("CASE ID", str(case_id)),
            ("SOURCE ID", pre.get("source_id", "") or ""),
            ("QUERY", pre.get("query", "") or ""),
            ("MODEL RESPONSE", pre.get("model_response", "") or ""),
            ("REFERENCE", pre.get("reference", "") or ""),
            ("STATUS", status),
            ("CATEGORY", category),
            ("SUBCATEGORY", subcategory),
            ("SEVERITY", case_sev),
            ("COMMENT", comment),
            ("AUTOCHECK RESULTS",
             "; ".join(checks_lines) if checks_lines else "no issues"),
            ("MODEL", pre.get("model_name", "") or ""),
            ("MODEL VERSION", pre.get("model_version", "") or ""),
            ("PROMPT VERSION", pre.get("prompt_version", "") or ""),
            ("SYSTEM PROMPT VERSION", pre.get("system_prompt_version", "") or ""),
        ]
        for k, v in rows:
            parts.append(f"- **{k}:** {v}" if v else f"- **{k}:** —")
        return "\n".join(parts)
    rows = [
        ("CASE ID", str(case_id)),
        ("SOURCE ID", pre.get("source_id", "") or ""),
        ("QUERY", pre.get("query", "") or ""),
        ("MODEL RESPONSE", pre.get("model_response", "") or ""),
        ("REFERENCE", pre.get("reference", "") or ""),
        ("STATUS", status),
        ("CATEGORY", category),
        ("SUBCATEGORY", subcategory),
        ("SEVERITY", case_sev),
        ("COMMENT", comment),
        ("AUTOCHECK RESULTS",
         "; ".join(checks_lines) if checks_lines else "no issues"),
        ("MODEL", pre.get("model_name", "") or ""),
        ("MODEL VERSION", pre.get("model_version", "") or ""),
        ("PROMPT VERSION", pre.get("prompt_version", "") or ""),
        ("SYSTEM PROMPT VERSION", pre.get("system_prompt_version", "") or ""),
    ]
    out = [f"Кейс #{case_id}", ""]
    out.extend(f"{k}: {v}" for k, v in rows)
    return "\n".join(out)
