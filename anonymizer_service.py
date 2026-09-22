"""Обезличивание экспортной копии (ТЗ V2.2 §6): опционально, только копия.

Сущности: EMAIL / PHONE / URL / POSSIBLE_SECRET. PERSON осознанно нет
(без NER — ложные срабатывания, решение пользователя).

Правила:
- один и тот же объект внутри одного экспорта -> один плейсхолдер
  (<EMAIL_1> ... <EMAIL_1>);
- разные объекты -> разные номера;
- исходные данные проекта НЕ изменяются: сервис трансформирует только
  строки, переданные ему; вызывающий код пишет результат в файл экспорта;
- по умолчанию экспорт «как есть»; обезличенный — только по явному выбору
  пользователя в диалоге (as_is / anonymized / cancel).
"""
import privacy_scan_service as scan

PLACEHOLDERS = ("EMAIL", "PHONE", "URL", "SECRET")


class Anonymizer:
    """Стабильные плейсхолдеры на время одного экспорта."""

    def __init__(self):
        self._maps: dict = {k: {} for k in PLACEHOLDERS}
        self._counters: dict = {k: 0 for k in PLACEHOLDERS}

    def _token(self, kind: str, raw: str) -> str:
        m = self._maps[kind]
        if raw not in m:
            self._counters[kind] += 1
            m[raw] = f"<{kind}_{self._counters[kind]}>"
        return m[raw]

    def anonymize(self, text: str) -> str:
        if not text or not isinstance(text, str):
            return text if isinstance(text, str) else ""
        # Порядок важен: секреты первыми (в них могут быть URL/email-подстроки).
        try:
            text = scan.SECRET_RE.sub(
                lambda mt: self._token("SECRET", mt.group(0)), text)
            text = scan.EMAIL_RE.sub(
                lambda mt: self._token("EMAIL", mt.group(0)), text)
            text = scan.PHONE_RE.sub(
                lambda mt: self._token("PHONE", mt.group(0)), text)
            text = scan.URL_RE.sub(
                lambda mt: self._token("URL", mt.group(0)), text)
        except Exception:
            pass
        return text

    def stats(self) -> dict:
        return {k: len(v) for k, v in self._maps.items()}


def anonymize_row(row: dict, fields: tuple = (
        "query", "response", "comment", "primary_text",
        "response_text", "review_comment"),
        anonymizer: Anonymizer | None = None) -> tuple:
    """Возвращает (новый_dict, anonymizer). Исходный dict не меняется."""
    anon = anonymizer or Anonymizer()
    out = dict(row)
    for f in fields:
        if out.get(f):
            out[f] = anon.anonymize(out[f])
    return out, anon
