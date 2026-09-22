"""Единые константы: статусы, роли маппинга, проверки."""

STATUSES = ("unreviewed", "good", "bad", "uncertain", "duplicate", "skip")

STATUS_NAMES = {
    "unreviewed": "Не проверено",
    "good": "Хорошо",
    "bad": "Плохо",
    "uncertain": "Сомневаюсь",
    "duplicate": "Дубль",
    "skip": "Пропустить",
}

STATUS_OPTIONS = [
    ("unreviewed", "Не проверено"),
    ("good", "Хорошо"),
    ("bad", "Плохо"),
    ("uncertain", "Сомневаюсь"),
    ("duplicate", "Дубль"),
    ("skip", "Пропустить"),
]

CHECK_OPTIONS = [
    ("empty_text", "Пустой текст"),
    ("too_short", "Слишком короткий"),
    ("too_long", "Слишком длинный"),
    ("has_url", "Содержит URL"),
    ("has_email", "Содержит email"),
    ("has_phone", "Содержит телефон"),
    ("many_spaces", "Много пробелов"),
    ("many_caps", "Много заглавных"),
    ("duplicate", "Дубль"),
    ("repeat_words", "Повтор слов"),
    ("many_punct", "Много знаков"),
    ("repeat_chars", "Повтор символов"),
    ("long_sentence", "Длинное предложение"),
    ("junk_markers", "Служебный мусор"),
    ("html_tags", "HTML-разметка"),
    ("markdown_heavy", "Много Markdown"),
    ("broken_encoding", "Битая кодировка"),
    ("suspicious_chars", "Подозрительные символы"),
]

CHECK_SEVERITIES = [
    ("critical", "🔴 critical"),
    ("error", "🔴 error"),
    ("warning", "🟡 warning"),
    ("info", "🔵 info"),
]

ALLOWED_ROLES = {
    "primary_text", "response_text", "group_name", "source_id",
    "comment_source", "metadata", "ticket_number", "product",
    "operator_response", "source", "topic_text", "ignore",
}

MAPPING_ROLES = [
    ("ignore", "Не импортировать"),
    ("topic_text", "📌 Тема"),
    ("primary_text", "Запрос"),
    ("response_text", "Ответ модели"),
    ("ticket_number", "Номер обращения"),
    ("product", "Продукт"),
    ("operator_response", "Ответ оператора"),
    ("group_name", "Группа / категория"),
    ("source_id", "Идентификатор"),
    ("comment_source", "Комментарий из источника"),
    ("source", "Источник (ссылка на БЗ)"),
    ("metadata", "Дополнительное поле"),
]

# Системные колонки таблицы ревью
TABLE_SYSTEM_COLUMNS = ["ID", "Строка", "Файл", "Запрос", "Ответ", "Статус", "Комментарий"]

COLUMN_TO_SQL = {
    # ID показывает идентификатор из маппинга (source_id), иначе внутренний номер
    "ID": "COALESCE(NULLIF(c.source_id, ''), CAST(c.case_id AS TEXT))",
    "Строка": "c.row_index + 1",
    "Файл": "f.file_name",
    "Запрос": "c.primary_text",
    "Ответ": "c.response_text",
    "Статус": "COALESCE(a.status, 'unreviewed')",
    "Комментарий": "a.comment",
}

PAGE_SIZE = 50
TABLE_PREVIEW_LIMIT = 100
HISTORY_LIMIT = 500
MAX_EXPORT_IN_CHUNK = 500
MAX_BACKUPS_KEEP = 20

# Русские подписи колонок из метаданных (ключи показать стыдно).
METADATA_COLUMN_LABELS = {
    "operator_response": "Эталон",
    "product": "Продукт",
    "topic": "Тема",
    "source": "Источник",
    "ticket_number": "Номер обращения",
}


def metadata_column_label(key: str) -> str:
    """Подпись колонки для показа; ключи и системные имена — как есть."""
    return METADATA_COLUMN_LABELS.get(key, key)

# V2.1 §15: типы regression assertions (без LLM, только формальные условия).
ASSERTION_TYPES = [
    ("not_empty", "Непустой ответ"),
    ("min_length", "Мин. длина"),
    ("max_length", "Макс. длина"),
    ("contains", "Содержит текст"),
    ("not_contains", "Не содержит текст"),
    ("regex", "Регулярное выражение"),
    ("exact_match", "Точное совпадение"),
    ("contains_url", "Содержит URL"),
    ("contains_email", "Содержит email"),
    ("contains_phone", "Содержит телефон"),
    ("contains_keyword", "Содержит ключевое слово"),
    ("no_service_text", "Без служебного текста"),
]

ASSERTION_SEVERITIES = ("critical", "warning", "info")
ASSERTION_RESULTS = ("PASS", "FAIL", "SKIPPED")
