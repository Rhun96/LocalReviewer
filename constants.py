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
]

ALLOWED_ROLES = {
    "primary_text", "response_text", "group_name", "source_id",
    "comment_source", "metadata", "ticket_number", "product",
    "operator_response", "source", "ignore",
}

MAPPING_ROLES = [
    ("ignore", "Не импортировать"),
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
    "ID": "c.case_id",
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
