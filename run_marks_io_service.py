"""Импорт оценок ответов прогона из таблицы (xlsx/csv/ods).

Сценарий: разметка в Excel (сам + стажёр) -> Preview -> Apply в
output_reviews выбранного прогона. Маппинг колонок задаёт пользователь
ОДИН раз (диалог запоминает его в settings проекта) — привязки к
конкретному датасету нет: ID/статус/комментарий/тяжесть из любых колонок.

Значения НЕ зашиты: диалог показывает все уникальные значения колонок
статуса/тяжести, пользователь мапит каждое (код / пропустить / как есть),
маппинг хранится в проекте. Встроенный словарь — только предзаполнение:
1/хорошо → good, 0/плохо → bad (+ сомневаюсь/дубль/пропуск),
ОК → нет, низкая/средняя/высокая → уровни.
У output_reviews нет поля тяжести: она идёт префиксом комментария
(«Критичность: высокая»), исходный комментарий дописывается следом.

Бакеты Preview — 1-в-1 как в импорте разметки кейсов:
new (ответ чистый), updating (дозаполнение пустого), conflicts
(перезапись непустого — только режим Update), unchanged, not_found
(ответа с таким ID в прогоне нет — сначала импортируй ответы), errors.
"""
import logging

from database import db, utcnow

logger = logging.getLogger(__name__)

SETTINGS_KEY = "runmarks_last_mapping"

STATUS_MAP = {
    "1": "good", "хорошо": "good", "good": "good", "+": "good",
    "да": "good", "yes": "good", "совпадает": "good",
    "0": "bad", "плохо": "bad", "bad": "bad", "-": "bad",
    "нет": "bad", "no": "bad", "не совпадает": "bad",
    "сомневаюсь": "uncertain", "uncertain": "uncertain",
    "дубль": "duplicate", "duplicate": "duplicate",
    "пропуск": "skip", "skip": "skip", "пропустить": "skip",
}

SEVERITY_MAP = {
    "низкая": "низкая", "low": "низкая", "н": "низкая",
    "средняя": "средняя", "medium": "средняя", "с": "средняя",
    "средне": "средняя",
    "высокая": "высокая", "high": "высокая", "в": "высокая",
}
SEVERITY_NONE = {"", "ок", "ok", "—", "-", "нет", "н/д", "na", "n/a"}


STATUS_CODES = ("good", "bad", "uncertain", "duplicate", "skip")
SEVERITY_LEVELS = ("низкая", "средняя", "высокая")


def parse_status(raw) -> str | None:
    """Код статуса или None (пусто — не трогать). Бросает ValueError."""
    s = str(raw or "").strip().lower()
    if not s:
        return None
    if s in STATUS_MAP:
        return STATUS_MAP[s]
    raise ValueError(f"неизвестный статус {raw!r}")


def resolve_status(raw, custom: dict | None) -> str | None:
    """Статус с учётом пользовательского маппинга значений.

    custom: {сырое значение: код | ""}. "" = пропустить (как пусто).
    Нет в custom — откат на встроенный словарь, чужое — ValueError.
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if custom:
        for k, v in custom.items():
            if str(k).strip().lower() == s.lower():
                return v or None
    return parse_status(raw)


def parse_severity(raw) -> str | None:
    """Каноническая тяжесть RU, None (нет), либо сырой текст как есть."""
    s = str(raw or "").strip()
    if not s:
        return None
    low = s.lower()
    if low in SEVERITY_NONE:
        return None
    if low in SEVERITY_MAP:
        return SEVERITY_MAP[low]
    return s


def resolve_severity(raw, custom: dict | None):
    """Тяжесть с учётом маппинга: {сырое: уровень | 'none' | 'as_is' | ''}.

    '' и 'none' = нет; уровень из SEVERITY_LEVELS; 'as_is' = текст как есть.
    Нет в custom — встроенный словарь (чужое сохраняется текстом).
    """
    s = str(raw or "").strip()
    if not s:
        return None
    if custom:
        for k, v in custom.items():
            if str(k).strip().lower() == s.lower():
                v = (v or "").strip().lower()
                if v in ("", "none"):
                    return None
                if v in SEVERITY_LEVELS:
                    return v
                return s  # as_is и всё неизвестное — текст как есть
    return parse_severity(raw)


def distinct_values(rows: list, header: str, limit: int = 100) -> list:
    """Уникальные непустые значения колонки (для маппинга в диалоге)."""
    seen: list = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        v = str(row.get(header, "") or "").strip()
        if v and v not in seen:
            seen.append(v)
            if len(seen) >= limit:
                break
    return seen


def build_comment(comment, severity: str | None) -> str:
    """Комментарий с префиксом тяжести (пустые части выбрасываем)."""
    parts = []
    if severity:
        parts.append(f"Критичность: {severity}")
    c = str(comment or "").strip()
    if c:
        parts.append(c)
    return "\n".join(parts)


def split_comment(comment) -> tuple:
    """Обратное к build_comment: (тяжесть|None, тело). Для шапки разметки."""
    body = str(comment or "").strip()
    if not body:
        return None, ""
    first, _, rest = body.partition("\n")
    if first.strip().lower().startswith("критичность:"):
        sev = first.split(":", 1)[1].strip() or None
        return sev, rest.strip()
    return None, body


def list_sheets(file_path: str) -> list:
    """Листы xlsx/ods (для выбора в диалоге). csv — один безымянный."""
    from pathlib import Path as _Path
    from file_reader import FileReader as _FR
    ext = _Path(file_path).suffix.lower()
    try:
        if ext == ".xlsx":
            return list(_FR.read_excel_sheets(file_path))
        if ext == ".ods":
            return list(_FR.read_ods_sheets(file_path))
    except Exception as e:
        logger.warning("sheets list failed: %s", e)
    return []


def read_marks_table(file_path: str, sheet: str | None = None) -> tuple:
    """Сырые строки таблицы: [{header: value}], заголовки — как есть.

    Возвращает (headers, rows, errors): headers — исходные заголовки
    первой строки (для маппинга в диалоге), rows — dict по заголовкам.
    Лист: указанный, иначе первый.
    """
    from pathlib import Path as _Path
    from file_reader import FileReader as _FR
    ext = _Path(file_path).suffix.lower()
    try:
        if ext == ".xlsx":
            sheets = _FR.read_excel_sheets(file_path)
            data = _FR.read_excel_data(file_path, sheet or sheets[0], 0)
        elif ext == ".ods":
            sheets = _FR.read_ods_sheets(file_path)
            data = _FR.read_ods_data(file_path, sheet or sheets[0], 0)
        elif ext == ".csv":
            data = _FR.read_csv_data(file_path)
        else:
            raise ValueError(f"Формат {ext!r}: нужен xlsx, csv или ods")
    except (ValueError, IndexError) as e:
        raise ValueError(str(e)) from e
    headers: list = []
    rows, errors = [], []
    for n, row in enumerate(data, 2):
        if not isinstance(row, dict):
            errors.append({"line": n, "error": "не строка таблицы"})
            continue
        if not headers:
            headers = [str(k or "").strip() for k in row.keys()]
        item = {str(k or "").strip(): ("" if v is None else str(v)).strip()
                for k, v in row.items()}
        if not any(item.values()):
            continue
        rows.append(item)
    if not headers:
        raise ValueError("Пустой файл: нет заголовков")
    return headers, rows, errors


def guess_mapping(headers: list) -> dict:
    """Предзаполнение маппинга по именам колонок (ID/статус/коммент/тяжесть)."""
    low = {h.lower(): h for h in headers}
    out = {"id": "", "status": "", "comment": "", "severity": ""}

    def _find(*names):
        for n in names:
            if n in low:
                return low[n]
        for h, orig in low.items():
            if any(n in h for n in names):
                return orig
        return ""

    out["id"] = _find("ид письма", "ид", "id", "source_id", "номер обращения",
                      "обращения")
    out["status"] = _find("совпада", "статус", "status", "вердикт",
                          "оценка", "хорошо", "1")
    out["comment"] = _find("комментарий", "коммент", "comment", "замечание")
    out["severity"] = _find("критичность", "тяжесть", "severity",
                            "критич")
    return out


def load_mapping(project_path: str) -> dict:
    """Последний маппинг из settings (без миграции — свободные ключи)."""
    try:
        import json as _json
        with db(project_path) as conn:
            row = conn.execute("SELECT value FROM settings WHERE key=?",
                               (SETTINGS_KEY,)).fetchone()
            if row and row["value"]:
                m = _json.loads(row["value"])
                if isinstance(m, dict):
                    out = {k: str(m.get(k, "") or "") for k in
                           ("id", "status", "comment", "severity", "sheet")}
                    for k in ("status_values", "severity_values"):
                        v = m.get(k)
                        if isinstance(v, dict):
                            out[k] = {str(kk): str(vv or "")
                                      for kk, vv in v.items()}
                    return out
    except Exception as e:
        logger.warning("runmarks mapping load failed: %s", e)
    return {}


def save_mapping(project_path: str, mapping: dict) -> None:
    try:
        import json as _json
        with db(project_path) as conn:
            conn.execute(
                "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, "
                "updated_at=excluded.updated_at",
                (SETTINGS_KEY, _json.dumps(mapping, ensure_ascii=False),
                 utcnow()))
    except Exception as e:
        logger.warning("runmarks mapping save failed: %s", e)


def _resolve_answer(cur, run_id: int, key: str):
    """Ответ прогона по ID кейса: source_id точно (регистр не важен),
    иначе case_id числом."""
    if not key:
        return None
    hit = cur.execute("""
        SELECT a.stable_key FROM run_answers a
        LEFT JOIN cases c ON c.case_id = a.case_id
        WHERE a.run_id = ? AND (lower_ru(c.source_id) = lower_ru(?)
             OR CAST(a.case_id AS TEXT) = ?)
        LIMIT 1
    """, (run_id, key, key)).fetchone()
    if hit:
        return hit["stable_key"]
    try:
        cid = int(key)
    except (TypeError, ValueError):
        return None
    hit = cur.execute("SELECT stable_key FROM run_answers "
                      "WHERE run_id = ? AND case_id = ? LIMIT 1",
                      (run_id, cid)).fetchone()
    return hit["stable_key"] if hit else None


def preview_marks(project_path: str, run_id: int, rows: list,
                  mapping: dict) -> dict:
    """Сухой прогон. Бакеты как в annotation IO (new/updating/conflicts/...)."""
    report = {"total": 0, "new": [], "updating": [], "unchanged": [],
              "not_found": [], "conflicts": [], "errors": []}
    id_col, st_col = mapping.get("id", ""), mapping.get("status", "")
    cm_col, sv_col = mapping.get("comment", ""), mapping.get("severity", "")
    st_vals = mapping.get("status_values") or {}
    sv_vals = mapping.get("severity_values") or {}
    if not id_col or not st_col:
        raise ValueError("Нужны колонки ID и статуса")
    with db(project_path) as conn:
        cur = conn.cursor()
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                report["errors"].append({"line": i + 1,
                                         "error": "not an object"})
                continue
            report["total"] += 1
            key = str(row.get(id_col, "") or "").strip()
            stable = _resolve_answer(cur, run_id, key)
            if not stable:
                report["not_found"].append({"id": key or f"строка {i + 1}"})
                continue
            try:
                status = resolve_status(row.get(st_col, ""), st_vals)
                severity = (resolve_severity(row.get(sv_col, ""), sv_vals)
                            if sv_col else None)
            except ValueError as e:
                report["errors"].append({"id": key, "error": str(e)})
                continue
            comment = build_comment(row.get(cm_col, "") if cm_col else "",
                                    severity)
            cur_row = cur.execute(
                "SELECT status, comment FROM output_reviews "
                "WHERE run_id = ? AND stable_key = ?",
                (run_id, stable)).fetchone()
            current = {"status": (cur_row["status"] if cur_row else None)
                       or "unreviewed",
                       "comment": (cur_row["comment"] if cur_row else None)
                       or ""}
            incoming = {"status": status or "unreviewed", "comment": comment}
            entry = {"id": key, "stable_key": stable, "incoming": incoming,
                     "current": current}
            diffs = [f for f in ("status", "comment")
                     if incoming[f] != current[f]]
            if not diffs:
                report["unchanged"].append(entry)
                continue
            is_clean = (current["status"] == "unreviewed"
                        and not current["comment"])
            if is_clean:
                report["new"].append(entry)
                continue
            filled = [f for f in diffs if current[f] not in ("", "unreviewed")]
            if not filled:
                report["updating"].append(entry)
            else:
                entry["conflict_fields"] = filled
                report["conflicts"].append(entry)
    return report


def apply_marks(project_path: str, run_id: int, preview: dict,
                mode: str) -> dict:
    """Применяет preview: merge (new + updating), update (+ conflicts)."""
    if mode not in ("merge", "update"):
        raise ValueError("Режим: merge/update (смотри сначала Preview)")
    import regression_service as _rg
    targets = list(preview.get("new", [])) + list(preview.get("updating", []))
    if mode == "update":
        targets += preview.get("conflicts", [])
    applied = skipped = 0
    for entry in targets:
        inc = entry["incoming"]
        status = inc["status"]
        if status == "unreviewed" and not inc["comment"]:
            skipped += 1
            continue
        if status == "unreviewed":
            status = "uncertain"
        try:
            _rg.set_output_review(project_path, run_id, entry["stable_key"],
                                  status, inc["comment"] or None)
            applied += 1
        except ValueError:
            skipped += 1
    logger.info("run marks applied=%s skipped=%s mode=%s",
                applied, skipped, mode)
    return {"applied": applied, "skipped": skipped,
            "not_found": len(preview.get("not_found", [])),
            "errors": len(preview.get("errors", []))}
