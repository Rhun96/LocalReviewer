"""Подсветка фрагментов ответа: зелёный — хорошо, красный — косяк,
жёлтый — обратить внимание.

Храним смещения в тексте ответа + хэш текста. Ответ поменялся
(переимпорт) — протухшие подсветки тихо чистим при чтении, молча
не показываем чужое. Пересекающиеся при добавлении — заменяем новым
(одно место — один смысл).
"""
import html
import logging

from database import db, utcnow

logger = logging.getLogger(__name__)

COLORS = ("green", "red", "yellow")
COLOR_NAMES = {"green": "Хорошо", "red": "Косяк", "yellow": "Внимание"}
# фон + цвет букв (читается и на тёмной, и на светлой теме)
SPAN_STYLE = {
    "green": "background-color:#2ea043; color:#ffffff;",
    "red": "background-color:#c0392b; color:#ffffff;",
    "yellow": "background-color:#e3b008; color:#000000;",
}


def _response_text(project_path: str, case_id: int) -> str:
    with db(project_path) as conn:
        row = conn.execute("SELECT response_text FROM cases WHERE case_id=?",
                           (case_id,)).fetchone()
        if not row:
            raise ValueError(f"Кейс #{case_id} не найден")
        return row["response_text"] or ""


def qt_len(text: str) -> int:
    """Длина в единицах UTF-16 (как считает QTextCursor)."""
    return sum(2 if ord(c) > 0xFFFF else 1 for c in text)


def qt_offset_to_py(text: str, q: int) -> int:
    """Смещение QTextCursor (UTF-16) → индекс Python (кодпоинты).

    Без конвертации всё после первого эмодзи/смайла едет: Qt видит 🙂 как 2,
    Python — как 1. Для чистого BMP текста — тождество.
    """
    q = max(0, min(int(q), qt_len(text)))
    u16 = 0
    i = 0
    while i < len(text) and u16 < q:
        u16 += 2 if ord(text[i]) > 0xFFFF else 1
        i += 1
    return i


def _hash(text: str) -> str:
    try:
        from autocheck_service import compute_text_hash
        return compute_text_hash(text)
    except Exception:
        import hashlib
        return hashlib.sha256(text.encode("utf-8")).hexdigest()


def list_highlights(project_path: str, case_id: int) -> list:
    """Живые подсветки (протухшие по хэшу/длине удаляем сразу)."""
    try:
        text = _response_text(project_path, case_id)
    except ValueError:
        return []
    h = _hash(text)
    out, stale = [], []
    with db(project_path) as conn:
        rows = conn.execute("SELECT highlight_id, start_offset, end_offset, color,"
                            " text_hash FROM case_highlights WHERE case_id=? "
                            "ORDER BY start_offset",
                            (case_id,)).fetchall()
        for r in rows:
            d = dict(r)
            if (d["text_hash"] != h or not (0 <= d["start_offset"]
                                            < d["end_offset"] <= len(text))):
                stale.append(d["highlight_id"])
            else:
                out.append(d)
        for hid in stale:
            conn.execute("DELETE FROM case_highlights WHERE highlight_id=?", (hid,))
    if stale:
        logger.info("pruned %s stale highlights for case %s", len(stale), case_id)
    return out


def add_highlight(project_path: str, case_id: int, start: int, end: int,
                  color: str) -> int:
    if color not in COLORS:
        raise ValueError(f"Плохой цвет: {color!r}")
    text = _response_text(project_path, case_id)
    if not (isinstance(start, int) and isinstance(end, int)):
        raise ValueError("Смещения — целые числа")
    if not (0 <= start < end <= len(text)):
        raise ValueError("Выдели фрагмент внутри текста ответа")
    h = _hash(text)
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM case_highlights WHERE case_id=? AND NOT "
                    "(end_offset <= ? OR start_offset >= ?)",
                    (case_id, start, end))
        cur.execute("INSERT INTO case_highlights "
                    "(case_id, start_offset, end_offset, color, text_hash, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    (case_id, start, end, color, h, now))
        return cur.lastrowid


def clear_highlights(project_path: str, case_id: int) -> int:
    with db(project_path) as conn:
        cur = conn.execute("DELETE FROM case_highlights WHERE case_id=?", (case_id,))
        return cur.rowcount or 0


def remove_range(project_path: str, case_id: int, start: int, end: int) -> int:
    """Снять подсветку с фрагмента: пересекающиеся обрезаются по краям.

    Зелёное 0–10 минус выделение 3–5 → зелёные 0–3 и 5–10. Возвращает число
    затронутых подсветок (0 — под выделением ничего не было).
    """
    text = _response_text(project_path, case_id)
    if not (isinstance(start, int) and isinstance(end, int)):
        raise ValueError("Смещения — целые числа")
    if not (0 <= start < end <= len(text)):
        raise ValueError("Выдели фрагмент внутри текста ответа")
    h = _hash(text)
    now = utcnow()
    with db(project_path) as conn:
        cur = conn.cursor()
        hits = cur.execute("SELECT highlight_id, start_offset, end_offset, color"
                           " FROM case_highlights WHERE case_id=? AND NOT "
                           "(end_offset <= ? OR start_offset >= ?)",
                           (case_id, start, end)).fetchall()
        for r in hits:
            cur.execute("DELETE FROM case_highlights WHERE highlight_id=?",
                        (r["highlight_id"],))
            for s, e in ((r["start_offset"], min(r["end_offset"], start)),
                         (max(r["start_offset"], end), r["end_offset"])):
                if s < e:
                    cur.execute(
                        "INSERT INTO case_highlights (case_id, start_offset,"
                        " end_offset, color, text_hash, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?)",
                        (case_id, s, e, r["color"], h, now))
        return len(hits)


def _is_ws(c: str) -> bool:
    import unicodedata as _ud
    return c in " \t\r\n" or _ud.category(c) in ("Zs", "Zl", "Zp")


def _convert_run(text: str) -> tuple:
    """HTML + карта doc→src: k-й символ документа ↔ индекс исходника.

    Qt схлопывает потоки пробельных символов, и смещения едут — вера в 1-в-1
    была багом снятия. Конвертация СТРОГО посимвольная (без слияния CRLF —
    иначе границы подсветок, режущие пару, дадут разный результат в рендере
    и в карте): каждый символ — фиксированный вклад, карта детерминирована
    и одинакова для целого текста и для любого его куска. Астрал — 2 юнита
    Qt на 1 индекс Python, в карте две записи.
    """
    import unicodedata as _ud
    html_parts: list = []
    doc2src: list = []
    n = len(text)
    for i, c in enumerate(text):
        o = ord(c)
        if c == "\n" or _ud.category(c) in ("Zl", "Zp"):
            html_parts.append("<br>")
            doc2src.append(i)
        elif c in ("\r", "\t") or (_ud.category(c) == "Zs" and c != " "):
            html_parts.append("&nbsp;")
            doc2src.append(i)
        elif c == " ":
            in_run = ((i > 0 and _is_ws(text[i - 1]))
                      or (i + 1 < n and _is_ws(text[i + 1])))
            html_parts.append("&nbsp;" if in_run else " ")
            doc2src.append(i)
        elif _ud.category(c) == "Cc":
            html_parts.append("&#xFFFD;")  # мусорные управляющие — видно, 1:1
            doc2src.append(i)
        else:
            html_parts.append(html.escape(c, quote=False))
            doc2src.append(i)
            if o > 0xFFFF:
                doc2src.append(i)  # суррогатная пара Qt
    return "".join(html_parts), doc2src


def build_doc_map(text: str) -> list:
    """Карта документа для всего текста (для перевода выделения)."""
    return _convert_run(text or "")[1]


def _rich_text(text: str) -> str:
    return _convert_run(text)[0]


def doc_range_to_src(doc2src: list, text_len: int, s_doc: int,
                     e_doc: int) -> tuple | None:
    """Диапазон документа → диапазон исходника. None, если пусто/бито."""
    n = len(doc2src)
    try:
        s_doc = max(0, min(int(s_doc), n))
        e_doc = max(0, min(int(e_doc), n))
    except (TypeError, ValueError):
        return None
    if e_doc <= s_doc:
        return None
    s_src = doc2src[s_doc]
    e_src = doc2src[e_doc - 1] + 1
    s_src = max(0, min(s_src, text_len))
    e_src = max(0, min(e_src, text_len))
    return (s_src, e_src) if e_src > s_src else None


def render_answer_html(project_path: str, case_id: int) -> str:
    """Ответ с подсветками (HTML). Без подсветок — просто экранированный текст."""
    text = _response_text(project_path, case_id)
    marks = list_highlights(project_path, case_id)
    if not marks:
        return _rich_text(text) if text else "(пусто)"
    parts = []
    pos = 0
    for m in marks:
        s, e = m["start_offset"], m["end_offset"]
        if s < pos:  # на всякий случай после чистки
            continue
        parts.append(_rich_text(text[pos:s]))
        parts.append(f'<span style="{SPAN_STYLE[m["color"]]}">'
                     f'{_rich_text(text[s:e])}</span>')
        pos = e
    parts.append(_rich_text(text[pos:]))
    return "".join(parts) or "(пусто)"
