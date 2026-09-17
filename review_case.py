"""Review screen: case view, navigation, status flow (mixin)."""


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QTextEdit, QScrollArea, QGroupBox, QFrame,
    QGridLayout, QSizePolicy, QDialog,
)
from PySide6.QtCore import Qt
from database import db
from ui_compat import (
    FLUENT, FPushButton, clear_in_fluent,
    confirm, notify,
)
import json
import logging


logger = logging.getLogger(__name__)


class CaseMixin:
    """Single-case view, navigation, status flow, comments."""

    def create_case_view(self):
        """Создаёт вид одного кейса."""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)

        # === 1. Текст кейса (плоский контейнер: вложенные группы
        # криво рисуют заголовки, проверено на скринах) ===
        case_wrap = QWidget()
        case_wrap_layout = QVBoxLayout()
        case_wrap_layout.setSpacing(8)
        case_wrap_layout.setContentsMargins(0, 0, 0, 0)
        text_scroll = QScrollArea()
        text_scroll.setWidgetResizable(True)
        text_scroll.setMinimumHeight(150)
        text_scroll.setStyleSheet("""
            QScrollArea {
                border: 2px solid #00441A;
                border-radius: 8px;
                background-color: #0A0F0A;
            }
        """)
        self.case_content = QWidget()
        self.case_layout = QVBoxLayout()
        self.case_layout.setSpacing(10)
        self.case_layout.setContentsMargins(12, 12, 12, 12)
        # Контент будет заполняться динамически в update_case_display
        self.case_layout.addStretch()
        self.case_content.setLayout(self.case_layout)
        text_scroll.setWidget(self.case_content)
        case_wrap_layout.addWidget(text_scroll)
        clear_in_fluent(text_scroll)
        case_wrap.setLayout(case_wrap_layout)
        layout.addWidget(case_wrap)

        # === 2. Навигация (сразу после текста) ===
        nav_group = QGroupBox("🧭 Навигация")
        nav_layout = QHBoxLayout()
        nav_layout.setSpacing(6)
        btn_prev = FPushButton("⬅️ Пред.")
        btn_prev.setMinimumHeight(30)
        btn_prev.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_prev.clicked.connect(self.prev_case)
        btn_filters = FPushButton("🎛️ Фильтры")
        btn_filters.setStyleSheet("""
            QPushButton { border-color: #FFAA00; color: #FFAA00; }
            QPushButton:hover { background-color: #332200; }
        """)
        btn_filters.setMinimumHeight(30)
        btn_filters.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_filters.clicked.connect(self.open_filters)
        btn_next = FPushButton("➡️ След.")
        btn_next.setMinimumHeight(30)
        btn_next.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_next.clicked.connect(self.next_case)
        btn_back = FPushButton("🚪 Назад")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(30)
        btn_back.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        btn_back.clicked.connect(self.on_back)
        self.btn_finish = FPushButton("🏁 Завершить ревью")
        self.btn_finish.setMinimumHeight(30)
        self.btn_finish.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.btn_finish.setToolTip("Сохранить версию датасета (снимок всех оценок)")
        self.btn_finish.clicked.connect(self.on_finish_review)
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_filters)
        nav_layout.addWidget(btn_next)
        nav_layout.addWidget(btn_back)
        nav_layout.addWidget(self.btn_finish)
        for _i in range(5):
            nav_layout.setStretch(_i, 1)
        nav_group.setLayout(nav_layout)
        layout.addWidget(nav_group)

        # === 3. Автопроверки ===
        self.checks_group = QGroupBox("⚠️ Автопроверки")
        self.checks_label = QLabel("✅ Нет предупреждений")
        self.checks_label.setWordWrap(True)
        self.checks_label.setStyleSheet("color: #00AA2A; font-size: 11px;")
        checks_layout = QVBoxLayout()
        checks_layout.addWidget(self.checks_label)
        self.verdicts_widget = QWidget()
        self.verdicts_layout = QGridLayout()
        self.verdicts_layout.setSpacing(4)
        self.verdicts_layout.setContentsMargins(0, 4, 0, 0)
        self.verdicts_widget.setLayout(self.verdicts_layout)
        checks_layout.addWidget(self.verdicts_widget)
        self.checks_group.setLayout(checks_layout)
        layout.addWidget(self.checks_group)

        # === 4. Статус (кнопки строятся из профиля — коды произвольные) ===
        status_group = QGroupBox("🎯 Статус")
        self.status_layout = QGridLayout()
        self.status_layout.setSpacing(6)
        self.status_buttons = {}
        # Равномерные колонки: в узком окне кнопки сжимаются одинаково,
        # текст остаётся по центру и не «съезжает»
        for _c in range(3):
            self.status_layout.setColumnStretch(_c, 1)
        status_group.setLayout(self.status_layout)
        layout.addWidget(status_group)

        # === 5. Комментарий ===
        comment_group = QGroupBox("💬 Комментарий")
        comment_layout = QVBoxLayout()
        comment_layout.setSpacing(6)
        templates_layout = QHBoxLayout()
        btn_templates = FPushButton("📋 Шаблоны")
        self.btn_templates = btn_templates
        btn_templates.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_templates.setMinimumHeight(28)
        btn_templates.clicked.connect(self.show_templates_menu)
        btn_add_template = FPushButton("➕ Новый")
        btn_add_template.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_add_template.setMinimumHeight(28)
        btn_add_template.clicked.connect(self.add_new_template)
        btn_del_template = FPushButton("🗑️ Удалить")
        btn_del_template.setStyleSheet("""
            QPushButton { border-color: #FF3B3B; color: #FF3B3B; }
            QPushButton:hover { background-color: #330000; }
        """)
        btn_del_template.setMinimumHeight(28)
        btn_del_template.clicked.connect(self.delete_template)
        btn_save_comment = FPushButton("💾 Сохранить")
        btn_save_comment.setMinimumHeight(28)
        btn_save_comment.clicked.connect(self.save_comment_manual)
        btn_undo_single = FPushButton("↩")
        btn_undo_single.setMaximumWidth(44)
        btn_undo_single.setToolTip("Отменить последнее действие (Ctrl+Z)")
        btn_undo_single.clicked.connect(self.undo_single)
        templates_layout.addWidget(btn_templates)
        templates_layout.addWidget(btn_add_template)
        templates_layout.addWidget(btn_del_template)
        templates_layout.addWidget(btn_save_comment)
        templates_layout.addWidget(btn_undo_single)
        templates_layout.addStretch()
        comment_layout.addLayout(templates_layout)
        self.comment_edit = QTextEdit()
        self.comment_edit.setMaximumHeight(60)
        # Выделение мышью видно в любой теме: яркий фон + тёмный текст.
        self.comment_edit.setStyleSheet("""
            QTextEdit {
                selection-background-color: #00AAFF;
                selection-color: #000000;
            }
        """)
        comment_layout.addWidget(self.comment_edit)
        self.save_indicator = QLabel("")
        self.save_indicator.setStyleSheet("color: #00AA2A; font-size: 10px;")
        comment_layout.addWidget(self.save_indicator)
        comment_group.setLayout(comment_layout)
        layout.addWidget(comment_group)

        # === 6. Теги (раскрывающиеся) ===
        self.btn_toggle_tags = FPushButton("🏷️ Теги (нажмите для раскрытия)")
        self.btn_toggle_tags.setMinimumHeight(30)
        self.btn_toggle_tags.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        self.btn_toggle_tags.clicked.connect(self.toggle_tags)
        tags_row = QHBoxLayout()
        tags_row.addWidget(self.btn_toggle_tags)
        self.btn_taxonomy = FPushButton("⚠ Таксономия…")
        self.btn_taxonomy.setMinimumHeight(30)
        self.btn_taxonomy.setToolTip("Редактор категорий и подкатегорий ошибок")
        self.btn_taxonomy.clicked.connect(self.open_taxonomy_editor)
        tags_row.addWidget(self.btn_taxonomy)
        self.btn_new_tag = FPushButton("＋ Тег")
        self.btn_new_tag.setMinimumHeight(30)
        self.btn_new_tag.setToolTip("Создать свой тег")
        self.btn_new_tag.clicked.connect(self.on_create_tag)
        tags_row.addWidget(self.btn_new_tag)
        self.btn_del_tag = FPushButton("－ Тег")
        self.btn_del_tag.setMinimumHeight(30)
        self.btn_del_tag.setToolTip("Удалить неиспользуемый тег")
        self.btn_del_tag.clicked.connect(self.on_delete_tag)
        tags_row.addWidget(self.btn_del_tag)
        self.btn_similar = FPushButton("🔍 Похожие")
        self.btn_similar.setMinimumHeight(30)
        self.btn_similar.setToolTip("Похожие кейсы (TF-IDF) — только контекст")
        self.btn_similar.clicked.connect(self.open_similar)
        tags_row.addWidget(self.btn_similar)
        self.btn_bug = FPushButton("🐞 Баг")
        self.btn_bug.setMinimumHeight(30)
        self.btn_bug.setToolTip("Создать Bug Report из кейса")
        self.btn_bug.clicked.connect(self.open_bug_report)
        tags_row.addWidget(self.btn_bug)
        self.btn_quick_bug = FPushButton("⚡ Быстрый баг")
        self.btn_quick_bug.setMinimumHeight(30)
        self.btn_quick_bug.setToolTip("Быстрый баг: только заголовок")
        self.btn_quick_bug.clicked.connect(self.open_quick_bug)
        tags_row.addWidget(self.btn_quick_bug)
        self.btn_case_bugs = FPushButton("🐞 Баги (0)")
        self.btn_case_bugs.setMinimumHeight(30)
        self.btn_case_bugs.setToolTip("Баги текущего кейса — клик открывает")
        self.btn_case_bugs.clicked.connect(self.open_case_bugs)
        tags_row.addWidget(self.btn_case_bugs)
        self.btn_context = FPushButton("📤 Контекст")
        self.btn_context.setMinimumHeight(30)
        self.btn_context.setToolTip("Контекст кейса в буфер (Markdown/Plain)")
        self.btn_context.clicked.connect(self.copy_case_context)
        tags_row.addWidget(self.btn_context)
        layout.addLayout(tags_row)
        self.tags_group = QGroupBox("🏷️ Теги")
        self.tags_layout = QGridLayout()
        self.tags_layout.setSpacing(4)
        self.tags_group.setLayout(self.tags_layout)
        self.tags_group.setVisible(False)  # Скрыты по умолчанию
        layout.addWidget(self.tags_group)

        widget.setLayout(layout)
        return widget

    def open_history(self):
        """Переход к истории (H)."""
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("history")

    def load_case(self, index: int):
        if index < 0 or index >= len(self.case_ids):
            return
        # Строгий режим: не даём тихо сменить кейс и сбросить pending.
        # load_case вызывается только после _bad_can_leave, но bulk/_done и
        # программные переходы могли прийти в обход — проверяем здесь тоже.
        try:
            new_id = self.case_ids[index]
        except Exception:
            return
        if new_id != self.current_case_id:
            # Смена кейса в строгом режиме запрещена (жульничество через таблицу
            # тоже закрыто: двойной клик идёт через _bad_can_leave).
            if (self._bad_pending and self.current_case_id is not None
                    and not self._bad_can_leave()):
                return
            if self.current_case_id:
                self.save_comment(silent=True)
            self._bad_reset()  # новый кейс — чистый лист
        elif self.current_case_id:
            # Перезагрузка того же кейса (после bulk/фильтров): черновик
            # сохраняем, pending сохраняем.
            self.save_comment(silent=True)
        self.current_index = index
        self.current_case_id = self.case_ids[index]
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT c.*, f.file_name, f.file_id, a.status, a.comment
                    FROM cases c
                    JOIN files f ON c.file_id = f.file_id
                    LEFT JOIN annotations a ON c.case_id = a.case_id
                    WHERE c.case_id = ?
                """, (self.current_case_id,))
                row = cursor.fetchone()
                if not row:
                    return
                self.current_case = dict(row)

                # Загружаем маппинг файла
                file_id = row['file_id']
                cursor.execute("SELECT mapping_json FROM files WHERE file_id = ?", (file_id,))
                mrow = cursor.fetchone()
                if mrow and mrow['mapping_json']:
                    try:
                        self.current_file_mapping = json.loads(mrow['mapping_json'])
                    except (ValueError, TypeError):
                        self.current_file_mapping = {}
                else:
                    self.current_file_mapping = {}

                cursor.execute("""
                    SELECT t.tag_id, t.tag_name, t.tag_code
                    FROM tags t
                    JOIN case_tags ct ON t.tag_id = ct.tag_id
                    WHERE ct.case_id = ?
                """, (self.current_case_id,))
                case_tags = {r['tag_id'] for r in cursor.fetchall()}
            try:
                from taxonomy_service import get_case_error
                self.current_error = get_case_error(self.project_path, self.current_case_id)
            except Exception:
                self.current_error = None
            self.update_case_display()
            self.update_tags_display(case_tags)
            self.update_info_label()
            self.update_queue_indicator()
            self.run_autochecks_for_case()
            self.comment_edit.setPlainText(self.current_case.get('comment') or '')
            self.save_indicator.setText("")
        except Exception as e:
            self.show_error("Не удалось загрузить кейс", e)

    def update_case_display(self):
        """Три окна: Тема / Текст / Ответ (Ответ шире, меньше скролла)."""
        if not self.current_case:
            return

        # Очищаем старый контент
        while self.case_layout.count():
            item = self.case_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        def _text_widget(text: str):
            w = QLabel(str(text) if text else "(пусто)")
            w.setWordWrap(True)
            w.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            w.setStyleSheet("font-size: 14px; padding: 6px;")
            return w

        def _header(text: str):
            h = QLabel(text)
            if not FLUENT:
                h.setStyleSheet("font-size: 12px; font-weight: bold; color: #00DD38;")
            return h

        def _box(title: str):
            # Панель + обычный заголовок вместо вложенного QGroupBox:
            # вложенные группы криво рисуют заголовки.
            panel = QFrame()
            panel.setObjectName("caseBox")
            panel.setStyleSheet(
                "#caseBox { border: 1px solid #3a3a3a; border-radius: 8px; }")
            lay = QVBoxLayout()
            lay.setSpacing(6)
            lay.setContentsMargins(10, 10, 10, 10)
            lay.addWidget(_header(title))
            panel.setLayout(lay)
            return panel, lay

        # Парсим сырые данные и метаданные
        raw_data = {}
        if self.current_case.get('raw_json'):
            try:
                raw_data = json.loads(self.current_case['raw_json'])
            except (ValueError, TypeError):
                pass
        try:
            metadata = json.loads(self.current_case.get('metadata_json') or '{}')
        except (ValueError, TypeError):
            metadata = {}
        if not isinstance(metadata, dict):
            metadata = {}
        mapping = self.current_file_mapping
        primary_cols = [col for col, role in mapping.items() if role == 'primary_text']
        response_cols = [col for col, role in mapping.items() if role == 'response_text']
        topic = (metadata.get('topic') or '').strip()
        topic_title = "📌 Тема"
        text_cols = list(primary_cols)
        if not topic and len(primary_cols) >= 2:
            # Тема и Текст — одна категория «Запрос»: ищем колонку,
            # похожую на тему по имени, иначе берём первую.
            # Работает и на старых импортах без роли Темы.
            # Одна колонка — делить нечего, Темы нет.
            import re as _re
            named = [c for c in primary_cols
                     if _re.search(r"тем|subj|title|topic", c, _re.IGNORECASE)]
            tcol = named[0] if named else primary_cols[0]
            topic = str(raw_data.get(tcol, '') or '').strip()
            if topic:
                topic_title = f"📌 Тема ({tcol})"
                text_cols = [c for c in primary_cols if c != tcol]

        # 1. Тема (явная роль — или первая колонка Запроса)
        if topic:
            box, lay = _box(topic_title)
            lay.addWidget(_text_widget(topic))
            self.case_layout.addWidget(box, 1)

        # 2. Текст (запрос): подпись колонки — только если их несколько.
        box, lay = _box("📝 Текст")
        if text_cols:
            for col_name in text_cols:
                if len(text_cols) > 1:
                    lay.addWidget(_header(f"📌 {col_name}:"))
                lay.addWidget(_text_widget(raw_data.get(col_name, '')))
        else:
            # Одна колонка Запроса без Темы — показываем как есть.
            lay.addWidget(_header("📌 Запрос:"))
            lay.addWidget(_text_widget(self.current_case.get('primary_text')))
        source = (metadata.get('source') or '').strip()
        if source and not topic:
            # Источник — сюда, только если нет окна Темы.
            lay.addWidget(_header("🔗 Источник:"))
            src_text = QLabel(source)
            src_text.setWordWrap(True)
            src_text.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard)
            src_text.setOpenExternalLinks(False)
            src_text.setStyleSheet("font-size: 13px; padding: 6px; color: #00AAFF;")
            lay.addWidget(src_text)
        self.case_layout.addWidget(box, 2)

        # 3. Ответ (шире остальных, чтобы меньше скроллить)
        box, lay = _box("💬 Ответ")
        if response_cols:
            for col_name in response_cols:
                if len(response_cols) > 1:
                    lay.addWidget(_header(f"💬 {col_name}:"))
                lay.addWidget(_text_widget(raw_data.get(col_name, '')))
        else:
            lay.addWidget(_text_widget(self.current_case.get('response_text')))
        self.case_layout.addWidget(box, 4)

        self.case_layout.addStretch(0)

    def update_info_label(self):
        if not self.current_case:
            return
        code = self.current_case.get('status') or 'unreviewed'
        base = self._status_base(code)
        status = f"{self.BASE_EMOJI.get(base, '')} {self._status_display(code)}".strip()
        sid = (self.current_case.get('source_id') or "").strip()
        sid_part = f" | 🆔 {sid}" if sid else f" | 🆔 case:{self.current_case.get('case_id')}"
        text = (
            f"📋 Кейс {self.current_index + 1} / {len(self.case_ids)} | "
            f"📄 {self.current_case.get('file_name')}{sid_part} | "
            f"{status}"
        )
        err = getattr(self, "current_error", None)
        if err and err.get("category_name"):
            from taxonomy_service import SEVERITY_NAMES
            sub = f" → {err['subcategory_name']}" if err.get("subcategory_name") else ""
            sev = SEVERITY_NAMES.get(err.get("severity", ""), "")
            text += f" | ⚠ {err['category_name']}{sub} [{sev}]"
        self.info_label.setText(text)
        self.update_finish_button()
        try:
            from bug_report_service import bugs_for_case
            n = len(bugs_for_case(self.project_path, self.current_case_id))
            self.btn_case_bugs.setText(f"🐞 Баги ({n})")
        except Exception:
            pass

    def _review_scope(self):
        """Скоуп ревью: файл из фильтров или весь проект.

        Считаем только то, что проверяется: условный «Ревью 1» — кейсы
        файла «Ревью 1»; все файлы — только если фильтр по файлу не задан.
        """
        return (self.filters or {}).get("file_id")

    def _scope_stats(self) -> dict:
        from review_queue_service import queue_stats
        return queue_stats(self.project_path, file_id=self._review_scope())

    def _scope_name(self) -> str:
        fid = self._review_scope()
        if fid is None:
            return "проект"
        try:
            with db(self.project_path) as conn:
                row = conn.cursor().execute(
                    "SELECT file_name FROM files WHERE file_id=?", (fid,)).fetchone()
                if row:
                    return f"файл «{row['file_name']}»"
        except Exception:
            pass
        return "файл"

    def update_finish_button(self):
        """Кнопка «Завершить ревью» активна только при 100% в текущем скоупе."""
        btn = getattr(self, "btn_finish", None)
        if btn is None:
            return
        try:
            stats = self._scope_stats()
            total, remaining = stats["total"], stats["remaining"]
        except Exception:
            btn.setEnabled(False)
            return
        if total and remaining == 0:
            btn.setEnabled(True)
            btn.setToolTip(f"Всё размечено ({self._scope_name()}) — "
                           "сохранить версию датасета (снимок всех оценок)")
        else:
            btn.setEnabled(False)
            if total:
                btn.setToolTip(f"Осталось разметить: {remaining} ({self._scope_name()})")
            else:
                btn.setToolTip("Нет кейсов")

    def on_finish_review(self):
        """Итог по текущему скоупу + переход к сохранению версии датасета."""
        if not self._bad_can_leave():
            return
        from report_service import get_overall_report
        try:
            rep = get_overall_report(self.project_path, file_id=self._review_scope())
        except Exception as e:
            self.show_error("Не удалось посчитать итог", e)
            return
        scope = self._scope_name()
        logger.info("finish review pressed: scope=%s total=%s reviewed=%s",
                    scope, rep["total"], rep["reviewed"])
        if not rep["total"] or rep["reviewed"] < rep["total"]:
            notify(self, "warning", "Ещё не всё",
                   f"Осталось разметить: {rep['total'] - rep['reviewed']} ({scope})")
            return
        summary = (f"{scope.capitalize()}: проверено {rep['reviewed']} из {rep['total']}\n"
                   f"✅ Хорошо: {rep['good']}\n"
                   f"❌ Плохо: {rep['bad']}\n"
                   f"❓ Сомневаюсь: {rep['uncertain']}\n"
                   f"🔄 Дубль: {rep['duplicate']}\n"
                   f"⏭️ Пропущено: {rep['skip']}")
        if confirm(self, "Завершить ревью",
                   summary + "\n\nСохранить версию датасета?"):
            from datasets_dialog import DatasetsDialog
            DatasetsDialog(self.project_path, self).exec()

    def save_comment_manual(self):
        """Явное «Сохранить» — запоминаем для одиночной отмены (Ctrl+Z)."""
        if not self.current_case_id:
            return
        prev = (self.current_case or {}).get("comment") or ""
        self.save_comment(silent=False)
        new = self.comment_edit.toPlainText().strip()
        if new != prev.strip():
            self._last_single = {"kind": "comment", "case_id": self.current_case_id,
                                 "old": prev, "new": new}

    def undo_single(self):
        """Отмена последнего одиночного действия (статус/тег/комментарий)."""
        act = getattr(self, "_last_single", None)
        if not act:
            notify(self, "warning", "Отмена", "Нечего отменять")
            return
        try:
            from database import utcnow as _utcnow
            now = _utcnow()
            with db(self.project_path) as conn:
                cur = conn.cursor()
                cid = act["case_id"]
                if act["kind"] == "status":
                    cur.execute("""
                        INSERT INTO annotations (case_id, status, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(case_id) DO UPDATE SET status=?, updated_at=?
                    """, (cid, act["old"], now, act["old"], now))
                    cur.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'status_changed', 'status', ?, ?, ?)
                    """, (cid, act["new"], act["old"], now))
                elif act["kind"] == "comment":
                    cur.execute("""
                        INSERT INTO annotations (case_id, comment, updated_at)
                        VALUES (?, ?, ?)
                        ON CONFLICT(case_id) DO UPDATE SET comment=?, updated_at=?
                    """, (cid, act["old"] or None, now, act["old"] or None, now))
                    cur.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'comment_changed', 'comment', ?, ?, ?)
                    """, (cid, act["new"], act["old"], now))
                elif act["kind"] == "tag":
                    if act["added"]:
                        cur.execute("DELETE FROM case_tags WHERE case_id=? AND tag_id=?",
                                    (cid, act["tag_id"]))
                        cur.execute("""
                            INSERT INTO history (case_id, event_type, field_name,
                                                 old_value, new_value, created_at)
                            VALUES (?, 'tag_removed', 'tag', ?, NULL, ?)
                        """, (cid, str(act["tag_id"]), now))
                    else:
                        cur.execute("INSERT OR IGNORE INTO case_tags "
                                    "(case_id, tag_id, created_at) VALUES (?, ?, ?)",
                                    (cid, act["tag_id"], now))
                        cur.execute("""
                            INSERT INTO history (case_id, event_type, field_name,
                                                 old_value, new_value, created_at)
                            VALUES (?, 'tag_added', 'tag', NULL, ?, ?)
                        """, (cid, str(act["tag_id"]), now))
                else:
                    return
        except Exception as e:
            self.show_error("Не удалось отменить", e)
            return
        self._last_single = None
        notify(self, "success", "Отмена", "Действие отменено")
        if self.case_ids and cid in self.case_ids:
            self.load_case(self.case_ids.index(cid))
            self.update_queue_indicator()

    def _comment_changed(self) -> bool:
        saved = (self.current_case or {}).get('comment') or ''
        return self.comment_edit.toPlainText().strip() != saved.strip()

    def save_comment(self, silent=False):
        if not self.current_case_id:
            return
        if silent and not self._comment_changed():
            return
        try:
            comment = self.comment_edit.toPlainText().strip()
            from database import utcnow as _utcnow
            now = _utcnow()
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO annotations (case_id, status, comment, updated_at)
                    VALUES (?, 'unreviewed', ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET
                        comment = ?,
                        updated_at = ?
                """, (
                    self.current_case_id, comment or None, now,
                    comment or None, now
                ))
            if self.current_case is not None:
                self.current_case['comment'] = comment or None
            if not silent:
                self.save_indicator.setText(f"💾 Комментарий сохранён ({now[:19]})")
        except Exception as e:
            if not silent:
                self.show_error("Не удалось сохранить комментарий", e)
            else:
                logger.warning("save_comment silent failed: %s", e)

    def _bad_reset(self) -> None:
        self._bad_pending = False
        self._bad_agreed = False
        self._bad_cause_done = False

    def _bad_can_leave(self) -> bool:
        """Можно ли уйти с кейса в строгом режиме (всегда True вне pending).

        Задумка: «Плохо» → комментарий → причина. Без комментария (если не
        согласился в мягком режиме) и без причины с кейса не уйти — смотреть
        таблицу и фильтры можно, перейти на другой кейс нельзя.
        """
        if not self._bad_pending:
            return True
        if not self._bad_agreed:
            comment = self.comment_edit.toPlainText().strip()
            if not comment:
                notify(self, "warning", "Заполните комментарий",
                       "Чтобы уйти с кейса: напиши комментарий, нажми «Плохо» "
                       "и укажи причину. Или выбери другой статус.")
                self.comment_edit.setFocus()
                return False
        if not self._bad_cause_done:
            notify(self, "warning", "Укажите причину",
                   "Нажми «Плохо» и выбери причину — "
                   "или выбери другой статус.")
            self.comment_edit.setFocus()
            return False
        return True

    def set_status(self, status: str):
        if not self.current_case_id:
            return
        # Настройки — свежие из БД, а не кэшированные: режимы
        # «мягкое/обязательное» должны работать сразу после смены в настройках
        try:
            self.settings = self.load_review_settings()
        except Exception as e:
            logger.warning("settings reload failed: %s", e)
        try:
            self.load_profile()
        except Exception as e:
            logger.warning("profile reload failed: %s", e)
        # Выход из строгого режима — выбором любого не-«плохого» статуса
        # (base-семантика: свои коды с base 'bad' — тоже «плохие»).
        is_bad = self._status_base(status) == "bad"
        if not is_bad:
            self._bad_reset()
        comment = self.comment_edit.toPlainText().strip()
        profile_cfg = (getattr(self, "profile", None) or {}).get("config", {})
        comment_mode = profile_cfg.get("require_comment_for_bad", None)
        if comment_mode is None:
            comment_mode = self.settings.get('require_comment_for_bad', 'warn')
        if is_bad:
            if not comment:
                if comment_mode == 'required':
                    notify(
                        self,
                        "warning",
                        "Требуется комментарий",
                        "Для статуса «Плохо» необходимо добавить комментарий. "
                        "Переход заблокирован: напиши комментарий, нажми «Плохо» "
                        "и укажи причину. Или выбери другой статус."
                    )
                    self._bad_pending = True
                    self._bad_agreed = False
                    self._bad_cause_done = False
                    self.save_indicator.setText(
                        "✏️ Напиши комментарий и снова нажми «Плохо»")
                    self.comment_edit.setFocus()
                    return
                # warn: «Да» = согласие идти без комментария (единственное
                # исключение), «Нет» = строгий режим до комментария + причины.
                if not confirm(
                    self,
                    "Рекомендация",
                    "Для статуса «Плохо» рекомендуется добавить комментарий.\n\n"
                    "Продолжить без комментария?",
                    ok_text="Да",
                    cancel_text="Нет",
                ):
                    self._bad_pending = True
                    self._bad_agreed = False
                    self._bad_cause_done = False
                    self.save_indicator.setText(
                        "✏️ Напиши комментарий и снова нажми «Плохо»")
                    notify(self, "warning", "Заполните комментарий",
                           "Переход заблокирован: напиши комментарий, нажми "
                           "«Плохо» и укажи причину. Или выбери другой статус.")
                    self.comment_edit.setFocus()
                    return
                self._bad_pending = True
                self._bad_agreed = True
                self._bad_cause_done = False
        try:
            from database import utcnow as _utcnow2
            now = _utcnow2()
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT status FROM annotations WHERE case_id = ?",
                    (self.current_case_id,)
                )
                old_row = cursor.fetchone()
                old_status = old_row['status'] if old_row else 'unreviewed'
                cursor.execute("""
                    INSERT INTO annotations (case_id, status, comment, updated_at)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(case_id) DO UPDATE SET
                        status = ?,
                        comment = ?,
                        updated_at = ?
                """, (
                    self.current_case_id, status, comment or None, now,
                    status, comment or None, now
                ))
                if old_status != status:
                    cursor.execute("""
                        INSERT INTO history
                            (case_id, event_type, field_name, old_value, new_value, created_at)
                        VALUES (?, 'status_changed', 'status', ?, ?, ?)
                    """, (self.current_case_id, old_status, status, now))
            self.current_case['status'] = status
            self.current_case['comment'] = comment or None
            if old_status != status:
                self._last_single = {"kind": "status",
                                     "case_id": self.current_case_id,
                                     "old": old_status, "new": status}
            if is_bad:
                # Причина обязательна в строгом режиме и по профилю
                # («Профили → Причина обязательна для Плохо»).
                # Пропуск разрешён только вне pending при выключенном флаге.
                pending = self._bad_pending
                required_by_profile = bool(profile_cfg.get(
                    "require_category_for_bad", False))
                if pending or required_by_profile:
                    completed = self._ask_error_cause()
                    if not completed:
                        self._bad_pending = True
                        notify(self, "warning", "Укажите причину",
                               "Без причины с кейса не уйти. "
                               "Нажми «Плохо» и выбери причину — "
                               "или выбери другой статус.")
                        self.update_info_label()
                        return
                    self._bad_cause_done = True
                    self._bad_pending = False
                elif comment and not self._bad_cause_done:
                    # Разовый вопрос без блокировки.
                    if self._ask_error_cause():
                        self._bad_cause_done = True
            self.update_info_label()
            self.update_queue_indicator()
            self.save_indicator.setText(f"💾 Статус сохранён: {status}")
            if self.settings.get('auto_next_case', True):
                self.next_case()
        except Exception as e:
            self.show_error("Не удалось сохранить статус", e)

    def _ask_error_cause(self) -> bool:
        """Быстрый выбор причины после «Плохо» (ТЗ §23).

        Возвращает True, если причина выбрана и сохранена.
        При сломанной таксономии/диалоге возвращает False, чтобы обязательный
        режим не пропускался молча, — выйти можно другим статусом.
        """
        try:
            from taxonomy_dialog import ErrorCauseDialog
            from taxonomy_service import set_case_error
        except Exception as e:
            logger.warning("taxonomy unavailable: %s", e)
            notify(self, "error", "Таксономия",
                   "Не удалось открыть выбор причины. Выбери другой статус "
                   "или исправь таксономию в настройках.")
            return False
        try:
            dlg = ErrorCauseDialog(self.project_path, self,
                                   case_id=self.current_case_id)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result:
                cat_id, sub_id, sev = dlg.result
                set_case_error(self.project_path, self.current_case_id,
                               cat_id, sub_id, sev)
                # подтянем имена для шапки
                from taxonomy_service import get_case_error
                self.current_error = get_case_error(
                    self.project_path, self.current_case_id)
                return True
            return False
        except Exception as e:
            logger.warning("error cause dialog failed: %s", e)
            notify(self, "error", "Таксономия",
                   f"Не удалось сохранить причину: {e}")
            return False

    def _next_index(self) -> int | None:
        """Следующий индекс с учётом настроек перехода (ТЗ §11).

        skip_reviewed — пропускать размеченные; no_return_good — пропускать
        «Хорошо»; checks_first — сначала кейсы с автопроверками.
        Возвращает None, если подходящих впереди нет.
        """
        nxt = self.current_index + 1
        if nxt >= len(self.case_ids):
            return None
        if not (self.settings.get('skip_reviewed') or self.settings.get('checks_first')
                or self.settings.get('no_return_good')):
            return nxt
        remaining = self.case_ids[nxt:]
        try:
            with db(self.project_path) as conn:
                cur = conn.cursor()
                statuses: dict = {}
                flagged: set = set()
                for i in range(0, len(remaining), 500):
                    chunk = remaining[i:i + 500]
                    ph = ",".join(["?"] * len(chunk))
                    for r in cur.execute(
                            f"SELECT case_id, status FROM annotations "
                            f"WHERE case_id IN ({ph})", chunk).fetchall():
                        statuses[r["case_id"]] = r["status"]
                    for r in cur.execute(
                            f"SELECT DISTINCT case_id FROM case_checks "
                            f"WHERE case_id IN ({ph})", chunk).fetchall():
                        flagged.add(r["case_id"])
        except Exception as e:
            logger.warning("next-index fallback: %s", e)
            return nxt
        order = list(remaining)
        if self.settings.get('checks_first'):
            order.sort(key=lambda cid: (cid not in flagged))
        for cid in order:
            st = statuses.get(cid, "unreviewed")
            base = self._status_base(st)
            if self.settings.get('skip_reviewed') and base != "unreviewed":
                continue
            if self.settings.get('no_return_good') and base == "good":
                continue
            return self.case_ids.index(cid)
        return None

    def next_case(self):
        if not self._bad_can_leave():
            return
        nxt = self._next_index()
        if nxt is not None:
            self.load_case(nxt)
            return
        # Последний кейс выборки: если текущий скоуп готов — тихая подсказка
        # про версию датасета (без модалок и без флагов «один раз»).
        try:
            stats = self._scope_stats()
            complete = stats["total"] > 0 and stats["remaining"] == 0
        except Exception:
            complete = False
        logger.info("last case reached: scope=%s complete=%s",
                    self._scope_name(), complete)
        if complete:
            notify(self, "success", "Ревью завершено",
                   f"Всё размечено ({self._scope_name()}). Сохрани версию датасета "
                   "кнопкой «🏁 Завершить ревью».")
        else:
            notify(self, "success", "Конец", "🎉 Это последний кейс в выборке")

    def prev_case(self):
        if not self._bad_can_leave():
            return
        if self.current_index > 0:
            self.load_case(self.current_index - 1)
        else:
            notify(self, "success", "Начало", "📍 Это первый кейс в выборке")

    def on_back(self):
        if not self._bad_can_leave():
            return
        if self.current_case_id:
            self.save_comment(silent=True)
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.review_closed.emit()

    def _jump_to_case(self, case_id: int):
        """Переход из похожих/дублей: строгий режим «Плохо» соблюдаем."""
        if not self._bad_can_leave():
            self.view_stack.setCurrentIndex(0)
            try:
                self.btn_toggle_view.setText("📋 Таблица")
            except Exception:
                pass
            return
        try:
            case_id = int(case_id)
        except (TypeError, ValueError):
            return
        if case_id in self.case_ids:
            self.view_stack.setCurrentIndex(0)
            try:
                self.btn_toggle_view.setText("📋 Таблица")
            except Exception:
                pass
            self.load_case(self.case_ids.index(case_id))
        else:
            notify(self, "warning", "Внимание",
                   "Кейс вне текущей выборки — сбрось фильтры, чтобы открыть его.")
