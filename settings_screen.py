from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QGroupBox, QFormLayout, QScrollArea
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
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        try:
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        except Exception:
            pass
        content = QWidget()
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

        self.skip_reviewed_checkbox = FCheckBox("Пропускать уже просмотренные при переходе")
        self.skip_reviewed_checkbox.setChecked(False)
        review_layout.addRow(self.skip_reviewed_checkbox)

        self.checks_first_checkbox = FCheckBox("Сначала кейсы с автопроверками при переходе")
        self.checks_first_checkbox.setChecked(False)
        review_layout.addRow(self.checks_first_checkbox)

        self.no_return_good_checkbox = FCheckBox("Не возвращаться к «Хорошо» при переходе")
        self.no_return_good_checkbox.setChecked(False)
        review_layout.addRow(self.no_return_good_checkbox)

        self.comment_for_bad_combo = FComboBox()
        self.comment_for_bad_combo.addItem("Не обязателен", "none")
        self.comment_for_bad_combo.addItem("Мягкое предупреждение", "warn")
        self.comment_for_bad_combo.addItem("Обязателен", "required")
        self.comment_for_bad_combo.setCurrentIndex(1)
        review_layout.addRow("Комментарий для статуса «Плохо»:", self.comment_for_bad_combo)

        self.btn_taxonomy = FPushButton("⚠ Таксономия ошибок…")
        self.btn_taxonomy.setToolTip("Категории и подкатегории причин, архив, свои категории")
        self.btn_taxonomy.clicked.connect(self.open_taxonomy)
        review_layout.addRow(self.btn_taxonomy)

        profile_row = QHBoxLayout()
        self.profile_combo = FComboBox()
        self.profile_combo.setMinimumHeight(30)
        profile_row.addWidget(self.profile_combo)
        self.btn_profiles = FPushButton("Профили…")
        self.btn_profiles.setToolTip("Редактор схем разметки: статусы, клавиши, обязательные поля")
        self.btn_profiles.clicked.connect(self.open_profiles)
        profile_row.addWidget(self.btn_profiles)
        review_layout.addRow("Профиль ревью:", profile_row)

        review_group.setLayout(review_layout)
        layout.addWidget(review_group)

        # Веса умной очереди (ТЗ §9): без ML, просто баллы
        prio_group = QGroupBox("Веса очереди")
        prio_layout = QFormLayout()
        self.prio_spins: dict = {}
        for key, label, default in (
            ("w_crit", "Критическая автопроверка:", 100),
            ("w_multi", "Несколько автопроверок:", 50),
            ("w_single", "Одна автопроверка:", 30),
            ("w_discuss", "Тег «нужно обсудить»:", 30),
            ("w_unrev", "Непроверенный кейс:", 10),
            ("w_rev", "Штраф за проверенный:", -20),
        ):
            spin = FSpinBox()
            spin.setMinimum(-500)
            spin.setMaximum(500)
            spin.setValue(default)
            spin.setMaximumWidth(180)
            self.prio_spins[key] = spin
            prio_layout.addRow(label, spin)
        prio_group.setLayout(prio_layout)
        layout.addWidget(prio_group)

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

        # Рабочее место V2.1 P0: восстановление сессии (глобально, QSettings).
        session_group = QGroupBox("Рабочее место")
        session_layout = QFormLayout()
        self.restore_checkbox = FCheckBox(
            "Восстанавливать последнее рабочее состояние")
        self.restore_checkbox.setChecked(True)
        self.restore_checkbox.setToolTip(
            "Проект, экран, кейс, фильтр, очередь, столбцы, сортировка, страница")
        try:
            from session_service import is_restore_enabled
            self.restore_checkbox.setChecked(bool(is_restore_enabled()))
        except Exception:
            pass
        self.restore_checkbox.checkStateChanged.connect(self.on_restore_toggled)
        session_layout.addRow(self.restore_checkbox)
        self.btn_clean_session = FPushButton("Начать с чистого состояния")
        self.btn_clean_session.setToolTip(
            "Сбрасывает только сохранённую сессию, не данные проекта")
        self.btn_clean_session.clicked.connect(self.on_clean_session)
        session_layout.addRow(self.btn_clean_session)
        session_group.setLayout(session_layout)
        layout.addWidget(session_group)

        # Приватность V2.2 §2–§3: буфер + диагностический режим (глобально).
        privacy_group = QGroupBox("Приватность")
        privacy_layout = QFormLayout()
        self.clipboard_combo = FComboBox()
        for secs, label in ((0, "Выкл."), (30, "30 секунд"),
                            (60, "60 секунд"), (300, "5 минут")):
            self.clipboard_combo.addItem(label, secs)
        self.clipboard_combo.setToolTip(
            "Автоочистка буфера после копирования. "
            "Чужой текст, скопированный поверх, не трогаем.")
        try:
            import clipboard_service as _clip
            _cur = _clip.get_clear_after()
            for i in range(self.clipboard_combo.count()):
                if self.clipboard_combo.itemData(i) == _cur:
                    self.clipboard_combo.setCurrentIndex(i)
                    break
        except Exception:
            pass
        self.clipboard_combo.currentIndexChanged.connect(self.on_clipboard_changed)
        privacy_layout.addRow("Очищать буфер обмена:", self.clipboard_combo)
        self.debug_content_checkbox = FCheckBox(
            "Диагностический режим: писать содержимое кейсов в лог")
        self.debug_content_checkbox.setToolTip(
            "По умолчанию ВЫКЛ: в лог идут только ID/счётчики. "
            "Включай только для отладки, потом выключи.")
        try:
            import app_logging as _log
            self.debug_content_checkbox.setChecked(bool(_log.is_content_debug_enabled()))
        except Exception:
            pass
        self.debug_content_checkbox.checkStateChanged.connect(self.on_debug_toggled)
        privacy_layout.addRow(self.debug_content_checkbox)
        privacy_group.setLayout(privacy_layout)
        layout.addWidget(privacy_group)

        # Настройки автопроверок
        checks_group = QGroupBox("Автопроверки")
        checks_layout = QFormLayout()

        self.min_length_spin = FSpinBox()
        self.min_length_spin.setMinimum(0)
        self.min_length_spin.setMaximum(1000)
        self.min_length_spin.setValue(10)
        # Спины компактные: иначе строка тянется на всю ширину и выглядит криво
        self.min_length_spin.setMaximumWidth(180)
        checks_layout.addRow("Минимальная длина текста:", self.min_length_spin)

        self.max_length_spin = FSpinBox()
        self.max_length_spin.setMinimum(100)
        self.max_length_spin.setMaximum(100000)
        self.max_length_spin.setValue(10000)
        self.max_length_spin.setMaximumWidth(180)
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

        self.check_repeat_words_checkbox = FCheckBox("Проверять повторы слов (да да да)")
        self.check_repeat_words_checkbox.setChecked(True)
        checks_layout.addRow(self.check_repeat_words_checkbox)

        self.check_punct_checkbox = FCheckBox("Проверять серии знаков (!!!!!)")
        self.check_punct_checkbox.setChecked(True)
        checks_layout.addRow(self.check_punct_checkbox)

        self.check_repeat_chars_checkbox = FCheckBox("Проверять повторы символов (аааааа)")
        self.check_repeat_chars_checkbox.setChecked(True)
        checks_layout.addRow(self.check_repeat_chars_checkbox)

        self.check_long_sentence_checkbox = FCheckBox("Проверять длинные предложения")
        self.check_long_sentence_checkbox.setChecked(True)
        checks_layout.addRow(self.check_long_sentence_checkbox)

        self.check_junk_checkbox = FCheckBox("Проверять служебный мусор (SYSTEM:, <END>)")
        self.check_junk_checkbox.setChecked(True)
        checks_layout.addRow(self.check_junk_checkbox)

        self.check_html_checkbox = FCheckBox("Проверять HTML-разметку")
        self.check_html_checkbox.setChecked(True)
        checks_layout.addRow(self.check_html_checkbox)

        self.check_markdown_checkbox = FCheckBox("Проверять Markdown (заголовки/таблицы)")
        self.check_markdown_checkbox.setChecked(True)
        checks_layout.addRow(self.check_markdown_checkbox)

        self.check_encoding_checkbox = FCheckBox("Проверять битую кодировку")
        self.check_encoding_checkbox.setChecked(True)
        checks_layout.addRow(self.check_encoding_checkbox)

        self.check_suspicious_checkbox = FCheckBox("Проверять невидимые символы")
        self.check_suspicious_checkbox.setChecked(True)
        checks_layout.addRow(self.check_suspicious_checkbox)

        self.max_sentence_spin = FSpinBox()
        self.max_sentence_spin.setMinimum(50)
        self.max_sentence_spin.setMaximum(5000)
        self.max_sentence_spin.setValue(400)
        self.max_sentence_spin.setMaximumWidth(180)
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

        content.setLayout(layout)
        scroll.setWidget(content)
        outer.addWidget(scroll)
        try:
            from ui_compat import clear_in_fluent
            clear_in_fluent(scroll, content)
        except Exception:
            pass
        self.setLayout(outer)

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
            self.skip_reviewed_checkbox.setChecked(
                settings.get('skip_reviewed', 'false') == 'true')
            self.checks_first_checkbox.setChecked(
                settings.get('checks_first', 'false') == 'true')
            self.no_return_good_checkbox.setChecked(
                settings.get('no_return_good', 'false') == 'true')
            for key, spin in self.prio_spins.items():
                try:
                    spin.setValue(int(settings.get(f'prio_{key}', spin.value())))
                except (TypeError, ValueError):
                    pass

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
            # Совместимость: старые БД могли хранить только групповые ключи.
            _set(self.check_repeat_words_checkbox, settings.get('checks_repeat_words'))
            _set(self.check_punct_checkbox, settings.get('checks_punct',
                  settings.get('checks_repeat_words')))
            _set(self.check_repeat_chars_checkbox, settings.get('checks_repeat_chars',
                  settings.get('checks_repeat_words')))
            _set(self.check_long_sentence_checkbox, settings.get('checks_long_sentence'))
            _set(self.check_junk_checkbox, settings.get('checks_junk'))
            _set(self.check_html_checkbox, settings.get('checks_html',
                  settings.get('checks_junk')))
            _set(self.check_markdown_checkbox, settings.get('checks_markdown',
                  settings.get('checks_junk')))
            _set(self.check_encoding_checkbox, settings.get('checks_encoding',
                  settings.get('checks_junk')))
            _set(self.check_suspicious_checkbox, settings.get('checks_suspicious',
                  settings.get('checks_junk')))
            self.reload_profiles()

        except Exception:
            # Тихие дефолты только если БД недоступна; виджеты уже с дефолтами из init_ui
            pass

    def reload_profiles(self):
        from review_profile_service import get_active_profile, list_profiles
        try:
            profiles = list_profiles(self.project_path)
            active = get_active_profile(self.project_path)
        except Exception:
            profiles, active = [], None
        self.profile_combo.blockSignals(True)
        self.profile_combo.clear()
        for p in profiles:
            self.profile_combo.addItem(p["name"], p["profile_id"])
        if active:
            for i in range(self.profile_combo.count()):
                if self.profile_combo.itemData(i) == active["profile_id"]:
                    self.profile_combo.setCurrentIndex(i)
                    break
        self.profile_combo.blockSignals(False)

    def open_profiles(self):
        from profile_dialog import ProfileDialog
        dlg = ProfileDialog(self.project_path, self)
        dlg.exec()
        self.reload_profiles()

    def refresh(self):
        self.load_settings()
        try:
            from session_service import is_restore_enabled
            self.restore_checkbox.setChecked(bool(is_restore_enabled()))
        except Exception:
            pass
        try:
            import clipboard_service as _clip
            _cur = _clip.get_clear_after()
            for i in range(self.clipboard_combo.count()):
                if self.clipboard_combo.itemData(i) == _cur:
                    self.clipboard_combo.blockSignals(True)
                    self.clipboard_combo.setCurrentIndex(i)
                    self.clipboard_combo.blockSignals(False)
                    break
        except Exception:
            pass
        try:
            import app_logging as _log
            self.debug_content_checkbox.setChecked(bool(_log.is_content_debug_enabled()))
        except Exception:
            pass

    def on_restore_toggled(self, *_a):
        try:
            from session_service import set_restore_enabled
            set_restore_enabled(bool(self.restore_checkbox.isChecked()))
        except Exception:
            pass

    def on_clipboard_changed(self, *_a):
        try:
            import clipboard_service as _clip
            _clip.set_clear_after(self.clipboard_combo.currentData())
        except Exception:
            pass

    def on_debug_toggled(self, *_a):
        try:
            import app_logging as _log
            _log.set_content_debug_enabled(bool(self.debug_content_checkbox.isChecked()))
        except Exception:
            pass

    def on_clean_session(self):
        """'Начать с чистого': только сессия, данные целы."""
        try:
            from session_service import clear_project_session, clear_session
            clear_project_session(self.project_path)
            clear_session()
            notify(self, "success", "Сессия",
                   "Сохранённое рабочее состояние сброшено. Данные проекта целы.")
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))

    def open_taxonomy(self):
        from taxonomy_editor import TaxonomyDialog
        dlg = TaxonomyDialog(self.project_path, self)
        dlg.exec()

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

    def _collect_settings(self) -> list:
        # 1-в-1 с autocheck_service.DEFAULTS: каждый ключ — свой чекбокс.
        out = [
            ('auto_next_case', str(self.auto_next_checkbox.isChecked()).lower()),
            ('skip_reviewed', str(self.skip_reviewed_checkbox.isChecked()).lower()),
            ('checks_first', str(self.checks_first_checkbox.isChecked()).lower()),
            ('no_return_good', str(self.no_return_good_checkbox.isChecked()).lower()),
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
            ('checks_repeat_words', str(self.check_repeat_words_checkbox.isChecked()).lower()),
            ('checks_punct', str(self.check_punct_checkbox.isChecked()).lower()),
            ('checks_repeat_chars', str(self.check_repeat_chars_checkbox.isChecked()).lower()),
            ('checks_long_sentence', str(self.check_long_sentence_checkbox.isChecked()).lower()),
            ('checks_junk', str(self.check_junk_checkbox.isChecked()).lower()),
            ('checks_html', str(self.check_html_checkbox.isChecked()).lower()),
            ('checks_markdown', str(self.check_markdown_checkbox.isChecked()).lower()),
            ('checks_encoding', str(self.check_encoding_checkbox.isChecked()).lower()),
            ('checks_suspicious', str(self.check_suspicious_checkbox.isChecked()).lower()),
        ]
        for key, spin in self.prio_spins.items():
            out.append((f'prio_{key}', str(spin.value())))
        return out

    def _write_settings(self) -> None:
        now = datetime.now(UTC).isoformat()
        with db(self.project_path) as conn:
            cursor = conn.cursor()
            for key, value in self._collect_settings():
                cursor.execute("""
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = ?,
                        updated_at = ?
                """, (key, value, now, value, now))
        pid = self.profile_combo.currentData()
        if pid:
            from review_profile_service import set_active_profile
            set_active_profile(self.project_path, int(pid))

    def on_save(self):
        """Сохраняет настройки."""
        if self.min_length_spin.value() > self.max_length_spin.value():
            notify(self, "warning", "Настройки",
                   "Минимальная длина не может быть больше максимальной")
            return
        try:
            self._write_settings()
            notify(self, "success", "Настройки", "Настройки сохранены")
        except Exception as e:
            notify(self, "error", "Ошибка", f"Не удалось сохранить настройки: {str(e)}")

    def on_reset(self):
        """Сбрасывает настройки по умолчанию."""
        from review_queue_service import DEFAULT_WEIGHTS
        self.auto_next_checkbox.setChecked(True)
        self.skip_reviewed_checkbox.setChecked(False)
        self.checks_first_checkbox.setChecked(False)
        self.no_return_good_checkbox.setChecked(False)
        for key, spin in self.prio_spins.items():
            spin.setValue(DEFAULT_WEIGHTS.get(key, 0))
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
        self.check_repeat_words_checkbox.setChecked(True)
        self.check_punct_checkbox.setChecked(True)
        self.check_repeat_chars_checkbox.setChecked(True)
        self.check_long_sentence_checkbox.setChecked(True)
        self.check_junk_checkbox.setChecked(True)
        self.check_html_checkbox.setChecked(True)
        self.check_markdown_checkbox.setChecked(True)
        self.check_encoding_checkbox.setChecked(True)
        self.check_suspicious_checkbox.setChecked(True)

    def on_back(self):
        """Возврат к проекту."""
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.settings_closed.emit()
