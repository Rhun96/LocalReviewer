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
    """Контекст кейса без бага (ТЗ V2 §22): Markdown/Plain в буфер."""
    if fmt not in ("markdown", "plain"):
        raise ValueError(f"Плохой формат: {fmt!r}")
    from bug_report_service import build_from_case
    pre = build_from_case(project_path, case_id)
    pseudo = {
        "bug_id": 0, "title": (pre.get("query") or "")[:80],
        "status": pre.get("review_status", ""), "severity": "",
        "description": pre.get("review_comment", ""),
        "actual_behavior": pre.get("model_response", ""),
        "expected_behavior": pre.get("expected_behavior", ""),
        "model_name": pre.get("model_name", ""),
        "model_version": pre.get("model_version", ""),
        "prompt_version": pre.get("prompt_version", ""),
        "system_prompt_version": pre.get("system_prompt_version", ""),
        "category_name": pre.get("category_name"),
        "subcategory_name": pre.get("subcategory_name"),
        "external_tracker": "", "external_id": "", "external_url": "",
        "cases": [{"case_id": case_id,
                   "source_id": pre.get("source_id", ""),
                   "primary_text": pre.get("query", "")}],
    }
    text = FORMATTERS[fmt].format(pseudo)
    return text.replace("Баг #0: ", "Кейс: ").replace("# Bug #0: ", "# Кейс: ")
