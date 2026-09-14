from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel,
    QGroupBox, QFormLayout
)
from PySide6.QtCore import Qt, Signal
from database import db
from ui_base import BaseScreen
from ui_compat import (
    FLUENT, FCheckBox, FComboBox, FPrimaryButton, FPushButton, FSpinBox,
    THEME_NAMES, apply_theme, get_theme_mode, notify, set_theme_mode,
)
from datetime import datetime, UTC


class SettingsScreen(BaseScreen):
    """Экран настроек приложения."""

    settings_closed = Signal()

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent

        self.init_ui()
        self.load_settings()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 12, 24, 12)

        # Заголовок
        title = QLabel("НАСТРОЙКИ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Настройки ревью
        review_group = QGroupBox("Режим ревью")
        review_layout = QFormLayout()

        self.auto_next_checkbox = FCheckBox(
            "Автоматически переходить к следующему кейсу после выбора статуса")
        self.auto_next_checkbox.setChecked(True)
        review_layout.addRow(self.auto_next_checkbox)

        self.comment_for_bad_combo = FComboBox()
        self.comment_for_bad_combo.addItem("Не обязателен", "none")
        self.comment_for_bad_combo.addItem("Мягкое предупреждение", "warn")
        self.comment_for_bad_combo.addItem("Обязателен", "required")
        self.comment_for_bad_combo.setCurrentIndex(1)
        review_layout.addRow("Комментарий для статуса «Плохо»:", self.comment_for_bad_combo)

        review_group.setLayout(review_layout)
        layout.addWidget(review_group)

        # Оформление (Fluent: светлая/тёмная/системная)
        ui_group = QGroupBox("Оформление")
        ui_layout = QFormLayout()
        self.theme_combo = FComboBox()
        self.theme_combo.addItem("Системная", "system")
        self.theme_combo.addItem("Светлая", "light")
        self.theme_combo.addItem("Тёмная", "dark")
        self.theme_combo.currentIndexChanged.connect(self.on_theme_changed)
        ui_layout.addRow("Тема:", self.theme_combo)
        self.fluent_hint = QLabel()
        self.fluent_hint.setWordWrap(True)
        ui_layout.addRow(self.fluent_hint)
        ui_group.setLayout(ui_layout)
        layout.addWidget(ui_group)

        # Настройки автопроверок
        checks_group = QGroupBox("Автопроверки")
        checks_layout = QFormLayout()

        self.min_length_spin = FSpinBox()
        self.min_length_spin.setMinimum(0)
        self.min_length_spin.setMaximum(1000)
        self.min_length_spin.setValue(10)
        checks_layout.addRow("Минимальная длина текста:", self.min_length_spin)

        self.max_length_spin = FSpinBox()
        self.max_length_spin.setMinimum(100)
        self.max_length_spin.setMaximum(100000)
        self.max_length_spin.setValue(10000)
        checks_layout.addRow("Максимальная длина текста:", self.max_length_spin)

        self.check_url_checkbox = FCheckBox("Проверять наличие URL")
        self.check_url_checkbox.setChecked(True)
        checks_layout.addRow(self.check_url_checkbox)

        self.check_email_checkbox = FCheckBox("Проверять наличие email")
        self.check_email_checkbox.setChecked(True)
        checks_layout.addRow(self.check_email_checkbox)

        self.check_phone_checkbox = FCheckBox("Проверять наличие телефона")
        self.check_phone_checkbox.setChecked(True)
        checks_layout.addRow(self.check_phone_checkbox)

        self.check_spaces_checkbox = FCheckBox("Проверять много пробелов")
        self.check_spaces_checkbox.setChecked(True)
        checks_layout.addRow(self.check_spaces_checkbox)

        self.check_caps_checkbox = FCheckBox("Проверять много заглавных букв")
        self.check_caps_checkbox.setChecked(True)
        checks_layout.addRow(self.check_caps_checkbox)

        self.check_duplicate_checkbox = FCheckBox("Проверять дубли")
        self.check_duplicate_checkbox.setChecked(True)
        checks_layout.addRow(self.check_duplicate_checkbox)

        self.check_repeat_checkbox = FCheckBox("Проверять повторы слов/символов")
        self.check_repeat_checkbox.setChecked(True)
        checks_layout.addRow(self.check_repeat_checkbox)

        self.check_junk_checkbox = FCheckBox("Проверять служебный мусор и HTML")
        self.check_junk_checkbox.setChecked(True)
        checks_layout.addRow(self.check_junk_checkbox)

        self.max_sentence_spin = FSpinBox()
        self.max_sentence_spin.setMinimum(50)
        self.max_sentence_spin.setMaximum(5000)
        self.max_sentence_spin.setValue(400)
        checks_layout.addRow("Макс. длина предложения:", self.max_sentence_spin)

        checks_group.setLayout(checks_layout)
        layout.addWidget(checks_group)

        # Кнопки
        buttons_layout = QHBoxLayout()

        btn_save = FPrimaryButton("Сохранить настройки")
        btn_save.setMinimumHeight(50)
        btn_save.clicked.connect(self.on_save)

        btn_reset = FPushButton("Сбросить по умолчанию")
        btn_reset.setMinimumHeight(50)
        btn_reset.clicked.connect(self.on_reset)

        btn_back = FPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(50)
        btn_back.clicked.connect(self.on_back)

        buttons_layout.addWidget(btn_save)
        buttons_layout.addWidget(btn_reset)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    @staticmethod
    def _apply_check(checkbox, value) -> None:
        checkbox.setChecked((value if value is not None else 'true') == 'true')

    def load_settings(self):
        """Загружает настройки из базы."""
        mode = get_theme_mode()
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == mode:
                self.theme_combo.blockSignals(True)
                self.theme_combo.setCurrentIndex(i)
                self.theme_combo.blockSignals(False)
                break
        if FLUENT:
            self.fluent_hint.setText(f"Активна Fluent-тема: {THEME_NAMES.get(mode, mode)}.")
        else:
            self.fluent_hint.setText(
                "Fluent-библиотека не установлена (pip install PySide6-Fluent-Widgets) — "
                "используется классическая тема.")
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM settings")
                settings = {row['key']: row['value'] for row in cursor.fetchall()}

            # Применяем настройки
            self.auto_next_checkbox.setChecked(settings.get('auto_next_case', 'true') == 'true')

            comment_mode = settings.get('require_comment_for_bad', 'warn')
            for i in range(self.comment_for_bad_combo.count()):
                if self.comment_for_bad_combo.itemData(i) == comment_mode:
                    self.comment_for_bad_combo.setCurrentIndex(i)
                    break

            try:
                min_len = int(settings.get('checks_min_length', '10'))
                max_len = int(settings.get('checks_max_length', '10000'))
            except ValueError:
                min_len, max_len = 10, 10000
            if min_len > max_len:
                min_len, max_len = max_len, min_len
            self.min_length_spin.setValue(max(0, min(min_len, 1000)))
            self.max_length_spin.setValue(max(100, min(max_len, 100000)))
            try:
                max_sent = int(settings.get('checks_max_sentence_len', '400'))
            except ValueError:
                max_sent = 400
            self.max_sentence_spin.setValue(max(50, min(max_sent, 5000)))
            _set = self._apply_check
            _set(self.check_url_checkbox, settings.get('checks_url'))
            _set(self.check_email_checkbox, settings.get('checks_email'))
            _set(self.check_phone_checkbox, settings.get('checks_phone'))
            _set(self.check_spaces_checkbox, settings.get('checks_spaces'))
            _set(self.check_caps_checkbox, settings.get('checks_caps'))
            _set(self.check_duplicate_checkbox, settings.get('checks_duplicate'))
            _set(self.check_repeat_checkbox, settings.get('checks_repeat_words'))
            _set(self.check_junk_checkbox, settings.get('checks_junk'))

        except Exception:
            # Тихие дефолты только если БД недоступна; виджеты уже с дефолтами из init_ui
            pass

    def refresh(self):
        self.load_settings()

    def on_theme_changed(self):
        mode = self.theme_combo.currentData() or "system"
        set_theme_mode(mode)
        if FLUENT:
            apply_theme(mode)
            self.fluent_hint.setText("Тема применена сразу.")
        else:
            self.fluent_hint.setText(
                "Fluent-библиотека не установлена (pip install PySide6-Fluent-Widgets) — "
                "используется классическая тема.")

    def on_save(self):
        """Сохраняет настройки."""
        if self.min_length_spin.value() > self.max_length_spin.value():
            notify(self, "warning", "Настройки",
                   "Минимальная длина не может быть больше максимальной")
            return
        try:
            now = datetime.now(UTC).isoformat()
            with db(self.project_path) as conn:
                cursor = conn.cursor()

                settings = [
                    ('auto_next_case', str(self.auto_next_checkbox.isChecked()).lower()),
                    ('require_comment_for_bad', self.comment_for_bad_combo.currentData()),
                    ('checks_min_length', str(self.min_length_spin.value())),
                    ('checks_max_length', str(self.max_length_spin.value())),
                    ('checks_max_sentence_len', str(self.max_sentence_spin.value())),
                    ('checks_url', str(self.check_url_checkbox.isChecked()).lower()),
                    ('checks_email', str(self.check_email_checkbox.isChecked()).lower()),
                    ('checks_phone', str(self.check_phone_checkbox.isChecked()).lower()),
                    ('checks_spaces', str(self.check_spaces_checkbox.isChecked()).lower()),
                    ('checks_caps', str(self.check_caps_checkbox.isChecked()).lower()),
                    ('checks_duplicate', str(self.check_duplicate_checkbox.isChecked()).lower()),
                    ('checks_repeat_words', str(self.check_repeat_checkbox.isChecked()).lower()),
                    ('checks_punct', str(self.check_repeat_checkbox.isChecked()).lower()),
                    ('checks_repeat_chars', str(self.check_repeat_checkbox.isChecked()).lower()),
                    ('checks_long_sentence', 'true'),
                    ('checks_junk', str(self.check_junk_checkbox.isChecked()).lower()),
                    ('checks_html', str(self.check_junk_checkbox.isChecked()).lower()),
                    ('checks_markdown', str(self.check_junk_checkbox.isChecked()).lower()),
                    ('checks_encoding', str(self.check_junk_checkbox.isChecked()).lower()),
                    ('checks_suspicious', str(self.check_junk_checkbox.isChecked()).lower()),
                ]

                for key, value in settings:
                    cursor.execute("""
                        INSERT INTO settings (key, value, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(key) DO UPDATE SET
                            value = ?,
                            updated_at = ?
                    """, (key, value, now, value, now))

            notify(self, "success", "Настройки", "Настройки сохранены")

        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось сохранить настройки: {str(e)}")

    def on_reset(self):
        """Сбрасывает настройки по умолчанию."""
        self.auto_next_checkbox.setChecked(True)
        self.comment_for_bad_combo.setCurrentIndex(1)
        self.min_length_spin.setValue(10)
        self.max_length_spin.setValue(10000)
        self.max_sentence_spin.setValue(400)
        self.check_url_checkbox.setChecked(True)
        self.check_email_checkbox.setChecked(True)
        self.check_phone_checkbox.setChecked(True)
        self.check_spaces_checkbox.setChecked(True)
        self.check_caps_checkbox.setChecked(True)
        self.check_duplicate_checkbox.setChecked(True)
        self.check_repeat_checkbox.setChecked(True)
        self.check_junk_checkbox.setChecked(True)

    def on_back(self):
        """Возврат к проекту."""
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.settings_closed.emit()
