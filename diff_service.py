"""Визуальный diff текстов (ТЗ V2 §13): было/стало словами и строками.

Используется в сравнении прогонов, истории и багах. Raw JSON — только
отдельным раскрываемым блоком, diff — основной интерфейс.
"""
import difflib
import html as _html


def word_diff_html(old: str | None, new: str | None) -> tuple:
    """(html_old, html_new): удалённое — красным, добавленное — зелёным."""
    if not old and not new:
        return "(пусто)", "(пусто)"
    wo = (old or "").split()
    wn = (new or "").split()
    sm = difflib.SequenceMatcher(a=wo, b=wn, autojunk=False)
    out_old, out_new = [], []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            out_old.append(_html.escape(" ".join(wo[i1:i2])))
            out_new.append(_html.escape(" ".join(wn[j1:j2])))
        else:
            from styles import DIFF as _D
            if i1 != i2:
                out_old.append(
                    f'<span style="background-color:{_D["del_bg"]}; '
                    f'color:{_D["del_text"]};">'
                    + _html.escape(" ".join(wo[i1:i2])) + "</span>")
            if j1 != j2:
                out_new.append(
                    f'<span style="background-color:{_D["add_bg"]}; '
                    f'color:{_D["add_text"]};">'
                    + _html.escape(" ".join(wn[j1:j2])) + "</span>")
    html_old = " ".join(out_old) if old else "(пусто)"
    html_new = " ".join(out_new) if new else "(пусто)"
    return html_old, html_new


def _diff_html(answer_a: str | None, answer_b: str | None) -> tuple:
    """Совместимость со старым именем из compare_dialog."""
    return word_diff_html(answer_a, answer_b)
