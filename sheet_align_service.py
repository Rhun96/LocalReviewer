"""Сравнение структуры листов и упорядочивание (для файлов с прогонами).

Задача: в одном xlsx несколько листов-прогонов с разной раскладкой колонок
(ID в разных местах, другой порядок, лишние/недостающие колонки).
Сравнение показывает расхождения с эталонным листом; «Упорядочить»
переставляет колонки целевого листа по эталону. Значения не трогаем,
форматирование ячеек не сохраняем (только данные).
Нормализация — только .xlsx (openpyxl читает и пишет); сравнение — xlsx/ods.
"""
import logging
from file_reader import FileReader

logger = logging.getLogger(__name__)
_reader = FileReader()


def guess_roles(headers: list) -> dict:
    """Автоподбор ролей по названиям колонок (можно поменять вручную)."""
    out: dict = {}
    low = {h: str(h).lower() for h in headers}

    def take(pred, role):
        for h, name in low.items():
            if h in out:
                continue
            if pred(name):
                out[h] = role
                return True
        return False

    take(lambda s: "ответ" in s or "answer" in s or "response" in s, "answer")
    take(lambda s: s.strip() in ("id", "ид", "номер", "ticket", "key")
         or "id" in s.split() or "идентификатор" in s
         or s.strip().endswith("_id"), "source_id")
    take(lambda s: any(k in s for k in ("вопрос", "запрос", "промпт", "обращени",
                                        "текст", "prompt", "question", "query",
                                        "text")), "prompt")
    return out


# Совместимость: раньше жила в runs_screen.
def _guess_roles(headers: list) -> dict:
    return guess_roles(headers)


def _headers_and_rows(file_path, file_type, sheet, max_rows=0):
    if file_type == "excel":
        if max_rows:
            prev = _reader.read_excel_preview(file_path, sheet, max_rows=max_rows)
            return prev["headers"], prev["rows"]
        return None, _reader.read_excel_data(file_path, sheet, header_row=0)
    if file_type == "ods":
        if max_rows:
            prev = _reader.read_ods_preview(file_path, sheet, max_rows=max_rows)
            return prev["headers"], prev["rows"]
        data = _reader.read_ods_data(file_path, sheet, header_row=0)
        if not data:
            return [], []
        headers = list(data[0].keys())
        return headers, [[r.get(h, "") for h in headers] for r in data]
    raise ValueError(f"Структуру сравниваем у xlsx/ods, а не {file_type!r}")


def sheet_headers(file_path, file_type, sheet):
    headers, _ = _headers_and_rows(file_path, file_type, sheet, max_rows=5)
    return headers or []


def column_values(file_path, file_type, sheet, column, limit=20000):
    """Уникальные значения колонки (кап; truncated=True если обрезали)."""
    _h, rows = _headers_and_rows(file_path, file_type, sheet, max_rows=0)
    if file_type == "ods":
        headers = _h
    else:
        headers, rows = _full_xlsx_rows(file_path, sheet, limit=limit)
    if column not in headers:
        return [], False
    idx = headers.index(column)
    seen, truncated = [], False
    for i, r in enumerate(rows):
        if i >= limit:
            truncated = True
            break
        v = str(r[idx] if idx < len(r) else "").strip()
        if v and v not in seen:
            seen.append(v)
    return sorted(seen), truncated


def _full_xlsx_rows(file_path, sheet, limit=0):
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"Лист {sheet!r} не найден")
        ws = wb[sheet]
        all_rows = [list(r) for r in ws.iter_rows(values_only=True)]
        if not all_rows:
            return [], []
        headers = [(str(h) if h not in (None, "") else "") for h in all_rows[0]]
        body = all_rows[1:]
        if limit:
            body = body[:limit]
        return headers, [[("" if v is None else v) for v in r] for r in body]
    finally:
        wb.close()


def filter_rows(headers, rows, conditions, _extra=None) -> list:
    """Строки под ВСЕ условия [(колонка, значение)] (строковое сравнение).

    conditions=None/[] — без фильтра. Старый вызов
    filter_rows(h, r, col, val) тоже работает.
    """
    if isinstance(conditions, str) and isinstance(_extra, str):
        conditions = [(conditions, _extra)]
    if not conditions:
        return rows
    out = rows
    for column, value in conditions:
        if not column:
            continue
        idx = headers.index(column) if column in headers else -1
        if idx < 0:
            continue
        out = [r for r in out
               if str(r[idx] if idx < len(r) else "").strip() == value]
    return out


def sheet_stats(file_path, file_type, sheet, conditions=None, _extra=None):
    """Строки всего / по фильтру + покрытие ID (если угадывается).

    conditions — список [(колонка, значение)]. Старый вызов
    sheet_stats(path, type, sheet, col, val) тоже работает.
    """
    if isinstance(conditions, str) and isinstance(_extra, str):
        conditions = [(conditions, _extra)]
    headers, rows = _headers_and_rows(file_path, file_type, sheet, max_rows=0)
    if file_type != "ods":
        headers, rows = _full_xlsx_rows(file_path, sheet)
    total = len(rows)
    filtered = filter_rows(headers, rows, conditions)
    id_cov = None
    roles = guess_roles(headers)
    id_col = next((h for h, r in roles.items() if r == "source_id"), None)
    if id_col and id_col in headers:
        idx = headers.index(id_col)
        filled = sum(1 for r in filtered
                     if str(r[idx] if idx < len(r) else "").strip())
        id_cov = {"column": id_col, "filled": filled, "total": len(filtered)}
    return {"total": total, "filtered": len(filtered),
            "conditions": conditions or [], "id_coverage": id_cov}


def compare_sheets(file_path, file_type, ref_sheet, target_sheet):
    """Расхождения структуры target относительно эталона ref."""
    ref_headers, _ = _headers_and_rows(file_path, file_type, ref_sheet, max_rows=5)
    tgt_headers, _ = _headers_and_rows(file_path, file_type, target_sheet, max_rows=5)
    ref_headers = ref_headers or []
    tgt_headers = tgt_headers or []
    ref_pos = {h: i for i, h in enumerate(ref_headers)}
    tgt_pos = {h: i for i, h in enumerate(tgt_headers)}
    missing = [h for h in ref_headers if h not in tgt_pos]
    extra = [h for h in tgt_headers if h not in ref_pos]
    moved = [{"header": h, "ref_index": ref_pos[h], "target_index": tgt_pos[h]}
             for h in ref_headers if h in tgt_pos and ref_pos[h] != tgt_pos[h]]
    try:
        ref_roles = {h: r for h, r in guess_roles(ref_headers).items()}
        tgt_roles = {h: r for h, r in guess_roles(tgt_headers).items()}
    except Exception:
        ref_roles, tgt_roles = {}, {}
    role_notes = []
    for role in ("answer", "source_id", "prompt"):
        rc = [h for h, r in ref_roles.items() if r == role]
        tc = [h for h, r in tgt_roles.items() if r == role]
        if rc != tc:
            role_notes.append({"role": role, "ref": rc, "target": tc})
    return {
        "ref_sheet": ref_sheet, "target_sheet": target_sheet,
        "ref_headers": ref_headers, "target_headers": tgt_headers,
        "missing_in_target": missing, "extra_in_target": extra,
        "moved": moved,
        "same_order": not missing and not extra and not moved,
        "ref_roles": ref_roles, "target_roles": tgt_roles,
        "role_notes": role_notes,
    }


def _read_sheet_values_xlsx(file_path, sheet):
    """Все строки листа значениями (без пропусков): [headers, row, ...]."""
    import openpyxl
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    try:
        if sheet not in wb.sheetnames:
            raise ValueError(f"Лист {sheet!r} не найден")
        ws = wb[sheet]
        return [list(r) for r in ws.iter_rows(values_only=True)]
    finally:
        wb.close()


def normalize_sheet(file_path, ref_sheet, target_sheet, keep_extra=True):
    """Колонки target в порядке ref. Возвращает (headers, rows).

    Недостающие колонки — пустые с именем из эталона; лишние — в конец
    (keep_extra) или отбрасываются. Число строк сохраняется.
    """
    ref_all = _read_sheet_values_xlsx(file_path, ref_sheet)
    tgt_all = _read_sheet_values_xlsx(file_path, target_sheet)
    if not ref_all or not tgt_all:
        raise ValueError("Пустой лист")
    ref_headers = [(str(h) if h not in (None, "") else "") for h in ref_all[0]]
    tgt_headers = [(str(h) if h not in (None, "") else "") for h in tgt_all[0]]
    tgt_index = {}
    for i, h in enumerate(tgt_headers):
        tgt_index.setdefault(h, i)
    out_headers = list(ref_headers)
    extras = [h for h in tgt_headers if h not in set(ref_headers)]
    if keep_extra:
        out_headers.extend(extras)
    out_rows = []
    for row in tgt_all[1:]:
        vals = [(row[tgt_index[h]] if h in tgt_index and tgt_index[h] < len(row)
                 else "") for h in out_headers]
        out_rows.append([("" if v is None else v) for v in vals])
    return out_headers, out_rows


def write_sheet_xlsx(output_path, sheet_name, headers, rows):
    """Новый xlsx с одним упорядоченным листом."""
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = (sheet_name or "Лист")[:31]
    ws.append(list(headers))
    for r in rows:
        ws.append(list(r))
    wb.save(output_path)
    return output_path


def write_file_xlsx(source_path, output_path, target_sheet, headers, rows):
    """Копия файла, где целевой лист заменён упорядоченным; остальные как есть."""
    import openpyxl
    src = openpyxl.load_workbook(source_path, read_only=True, data_only=True)
    try:
        dst = openpyxl.Workbook()
        first = True
        for name in src.sheetnames:
            if name == target_sheet:
                ws = dst.active if first else dst.create_sheet(title=name[:31])
                if first:
                    ws.title = name[:31]
                ws.append(list(headers))
                for r in rows:
                    ws.append(list(r))
            else:
                ws = dst.active if first else dst.create_sheet(title=name[:31])
                if first:
                    ws.title = name[:31]
                for row in src[name].iter_rows(values_only=True):
                    ws.append([("" if v is None else v) for v in row])
            first = False
        dst.save(output_path)
    finally:
        src.close()
    return output_path
