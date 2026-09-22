"""Review screen, Review profile, statuses and shortcuts. (mixin split of review_screen.py)."""


from PySide6.QtWidgets import (
    QTextEdit, QSizePolicy, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
from PySide6.QtWidgets import QApplication
from constants import STATUS_NAMES
from database import db
from styles import STATUS_STYLES
from ui_compat import (
    FPushButton,
)
import logging


logger = logging.getLogger(__name__)


class ProfileMixin:
    """Review profile, statuses and shortcuts."""

    def load_profile(self) -> dict:
        """Активный профиль ревью; fallback — дефолтная схема."""
        try:
            from review_profile_service import get_active_profile
            self.profile = get_active_profile(self.project_path)
        except Exception as e:
            logger.warning("profile fallback: %s", e)
            from migrations import DEFAULT_PROFILE_CONFIG
            import copy
            self.profile = {"profile_id": 0, "name": "Default",
                            "config": copy.deepcopy(DEFAULT_PROFILE_CONFIG)}
        return self.profile


    def profile_statuses(self) -> list:
        cfg = (getattr(self, "profile", None) or {}).get("config", {})
        return [s for s in cfg.get("statuses", []) if s.get("enabled")]

    def _status_base(self, code: str) -> str:
        for s in (getattr(self, "profile", None) or {}).get("config", {}).get(
                "statuses", []):
            if s.get("code") == code:
                base = s.get("base") or code
                return base if base in ("unreviewed", "good", "bad",
                                        "uncertain", "duplicate", "skip") else code
        if code in ("unreviewed", "good", "bad", "uncertain", "duplicate", "skip"):
            return code
        return code

    def _status_display(self, code: str) -> str:
        for s in (getattr(self, "profile", None) or {}).get("config", {}).get(
                "statuses", []):
            if s.get("code") == code:
                return s.get("name") or code
        return STATUS_NAMES.get(code, code)

    def apply_profile(self):
        """Кнопки и хоткеи из активного профиля (коды — произвольные)."""
        if getattr(self, "profile", None) is None:
            self.load_profile()
        layout = getattr(self, "status_layout", None)
        if layout is not None:
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            self.status_buttons = {}
            specs = self.profile_statuses()
            cols = 3
            for i, spec in enumerate(specs):
                code = spec["code"]
                base = spec.get("base") or code
                btn = FPushButton()
                btn.setMinimumHeight(30)
                btn.setSizePolicy(QSizePolicy.Policy.Expanding,
                                  QSizePolicy.Policy.Fixed)
                try:
                    btn.setStyleSheet(STATUS_STYLES.get(base, ""))
                except Exception:
                    pass
                hotkey = (spec.get("hotkey") or "").strip()
                suffix = f" [{hotkey}]" if hotkey else ""
                btn.setText(f"{self.BASE_EMOJI.get(base, '')} "
                            f"{spec.get('name', code)}{suffix}")
                btn.clicked.connect(lambda _c, s=code: self.set_status(s))
                layout.addWidget(btn, i // cols, i % cols)
                self.status_buttons[code] = btn
            for _c in range(cols):
                try:
                    layout.setColumnStretch(_c, 1)
                except Exception:
                    pass
        self.rebuild_shortcuts()

    def load_review_settings(self) -> dict:
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT key, value FROM settings")
                settings = {row['key']: row['value'] for row in cursor.fetchall()}
            return {
                'auto_next_case': settings.get('auto_next_case', 'true') == 'true',
                'require_comment_for_bad': settings.get('require_comment_for_bad', 'warn'),
                'skip_reviewed': settings.get('skip_reviewed', 'false') == 'true',
                'checks_first': settings.get('checks_first', 'false') == 'true',
                'no_return_good': settings.get('no_return_good', 'false') == 'true',
            }
        except Exception as e:
            logger.warning("review settings fallback: %s", e)
            return {
                'auto_next_case': True,
                'require_comment_for_bad': 'warn',
                'skip_reviewed': False,
                'checks_first': False,
                'no_return_good': False,
            }

    def _shortcuts_allowed(self) -> bool:
        focus = QApplication.focusWidget()
        if focus is None:
            return True
        # Не перехватываем цифры/стрелки при вводе текста или выборе в комбо.
        # Во Fluent-режиме FLineEdit/FTextEdit/FComboBox — НЕ наследники
        # QLineEdit/QTextEdit/QComboBox, поэтому проверяем и их явно,
        # иначе цифры 1–5 меняют статус прямо во время набора комментария.
        from PySide6.QtWidgets import QLineEdit, QSpinBox
        from ui_compat import FComboBox as _FC, FLineEdit as _FL, FTextEdit as _FT
        try:
            fluent_types = tuple(t for t in (_FL, _FT, _FC) if isinstance(t, type))
        except Exception:
            fluent_types = ()
        return not isinstance(
            focus, (QLineEdit, QTextEdit, QComboBox, QSpinBox, *fluent_types))

    def init_shortcuts(self):
        self._shortcuts = []
        self.rebuild_shortcuts()

    def rebuild_shortcuts(self):
        """Хоткеи из профиля (+ стрелки всегда). Старые удаляем."""
        for sc in getattr(self, "_shortcuts", []):
            try:
                sc.setParent(None)
                sc.deleteLater()
            except Exception:
                pass
        self._shortcuts = []

        def guarded(fn):
            return lambda: fn() if self._shortcuts_allowed() else None

        def _add(key, fn):
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(guarded(fn))
            self._shortcuts.append(sc)

        try:
            statuses = self.profile_statuses()
        except Exception:
            statuses = []
        if not statuses:
            statuses = [{"code": c, "hotkey": k} for c, k in
                        (("good", "1"), ("bad", "2"), ("uncertain", "3"),
                         ("duplicate", "4"), ("skip", "5"))]
        for spec in statuses:
            hotkey = (spec.get("hotkey") or "").strip()
            code = spec.get("code")
            if hotkey and code:
                _add(hotkey, lambda s=code: self.set_status(s))
        def _nav(fn):
            def _go():
                if not self._shortcuts_allowed():
                    return
                fn()
                try:
                    self.focus_work_area()
                except Exception:
                    pass
            return _go

        _add("Right", _nav(self.next_case))
        _add("Left", _nav(self.prev_case))
        # Ctrl+Z — отмена одиночного действия; в полях ввода работает
        # нативный undo текста (guarded пропускает), вне полей — наш.
        _add("Ctrl+Z", self.undo_single)
        # §26: рабочие хоткеи, если не заняты статусами профиля.
        used = {(s.get("hotkey") or "").strip().upper() for s in statuses}
        if "B" not in used:
            _add("B", self.open_bug_report)
        if "H" not in used:
            _add("H", self.open_history)
        if "S" not in used:
            _add("S", self.open_similar)
        _add("Ctrl+A", self.on_bulk_select_all)
        _add("Ctrl+Shift+A", self.on_bulk_clear)
        # Ctrl+H — свободен (профили — одиночные символы): скрыть кейс.
        _add("Ctrl+H", self.toggle_hide_current)
        # V2.2 §13: Ctrl+P — глобальный поиск кейса (свободен, печати нет).
        # Без guarded: Ctrl+P текстом не набирается, а фокус почти всегда
        # в комментарии — с guard поиск «не работает» (проверено жалобой).
        # Строгий «Плохо» всё равно держит open_global_search изнутри.
        try:
            sc_find = QShortcut(QKeySequence("Ctrl+P"), self)
            sc_find.setContext(Qt.ShortcutContext.WindowShortcut)
            sc_find.activated.connect(self.open_global_search)
            self._shortcuts.append(sc_find)
        except Exception:
            pass
        # Ctrl+Enter: в Qt Return (основной) и Enter (кейпад) — разные
        # клавиши, вешаем оба. Без guarded: сохранение должно работать
        # и внутри полей ввода.
        for _key in ("Ctrl+Return", "Ctrl+Enter"):
            try:
                sc_save = QShortcut(QKeySequence(_key), self)
                sc_save.setContext(Qt.ShortcutContext.WindowShortcut)
                sc_save.activated.connect(self.save_marks_hotkey)
                self._shortcuts.append(sc_save)
            except Exception:
                pass

    def save_marks_hotkey(self):
        """Ctrl+Enter: сохранить разметку (черновик комментария). Везде."""
        if not self.current_case_id:
            return
        self.save_comment(silent=True)
        try:
            self.save_indicator.setText("💾 Сохранено (Ctrl+Enter)")
        except Exception:
            pass
        try:
            self.focus_work_area()
        except Exception:
            pass
