"""Review screen: verdicts, tags, templates, similar, bugs (mixin)."""


from PySide6.QtWidgets import (
    QLabel,
    QMenu, QInputDialog, QDialog,
)
from database import db
from filter_dialog import FilterDialog
from filter_service import get_filtered_case_ids
from autocheck_service import check_case, get_check_settings
from templates_service import (
    add_comment_template, delete_comment_template,
    get_user_templates,
)
from ui_compat import (
    FPushButton, confirm, notify, tag_button_style,
)
import logging


logger = logging.getLogger(__name__)


class VerdictsMixin:
    """Verdicts, templates, tags, taxonomy, similar, bugs."""

    def toggle_tags(self):
        """Переключает видимость тегов."""
        self.tags_expanded = not self.tags_expanded
        if self.tags_expanded:
            self.tags_group.setVisible(True)
            self.btn_toggle_tags.setText("🏷️ Теги (нажмите для скрытия)")
        else:
            self.tags_group.setVisible(False)
            self.btn_toggle_tags.setText("🏷️ Теги (нажмите для раскрытия)")

    def open_taxonomy_editor(self):
        """Редактор таксономии прямо из ревью — всё под рукой."""
        try:
            from taxonomy_editor import TaxonomyDialog
            TaxonomyDialog(self.project_path, self).exec()
        except Exception as e:
            self.show_error("Не удалось открыть таксономию", e)

    def run_autochecks_for_case(self):
        if not self.current_case:
            self.checks_label.setText("✅ Нет предупреждений")
            return
        settings = get_check_settings(self.project_path)
        checks = check_case(self.current_case, settings)
        from styles import COLORS as _CC
        if not checks:
            self.checks_label.setText("✅ Нет предупреждений")
            self.checks_label.setStyleSheet(
                f"color: {_CC['green_dark']}; font-size: 11px;")
        else:
            from autocheck_service import rule_severity
            sev_icon = {"critical": "🔴", "error": "🔴", "warning": "🟡", "info": "🔵"}
            lines = [f"{sev_icon.get(rule_severity(c[0]), '⚠️')} {c[1]}: {c[2]}" for c in checks]
            self.checks_label.setText("\n".join(lines))
            self.checks_label.setStyleSheet(
                f"color: {_CC['amber']}; font-size: 11px;")
        self._refresh_verdicts()

    def _refresh_verdicts(self):
        """Кнопки вердиктов по срабатываниям (ТЗ §75): ✓ подтвердить / ✗ ложное.

        Берём из БД (после «Пересчитать проверки»); если там пусто —
        показываем живые проверки кейса, вердикт тогда сначала фиксирует
        саму сработку. Повторный клик снимает вердикт.
        """
        while self.verdicts_layout.count():
            item = self.verdicts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if not self.current_case_id:
            self.verdicts_widget.setVisible(False)
            return
        try:
            from autocheck_service import get_case_checks, get_check_verdicts
            stored = get_case_checks(self.project_path, self.current_case_id)
            verdicts = get_check_verdicts(self.project_path, self.current_case_id)
        except Exception as e:
            logger.warning("verdicts load failed: %s", e)
            self.verdicts_widget.setVisible(False)
            return
        rows = [{"check_code": c.get("check_code", ""),
                 "check_name": c.get("check_name", c.get("check_code", "")),
                 "details": c.get("details", ""), "live": False}
                for c in stored]
        if not rows and self.current_case:
            try:
                live = check_case(self.current_case, get_check_settings(
                    self.project_path))
            except Exception:
                live = []
            rows = [{"check_code": c[0], "check_name": c[1],
                     "details": c[2] if len(c) > 2 else "", "live": True}
                    for c in live]
        if not rows:
            self.verdicts_widget.setVisible(False)
            return
        for row, chk in enumerate(rows):
            code = chk.get("check_code", "")
            name = chk.get("check_name", code)
            cur = verdicts.get(code)
            mark = ('✅' if cur == 'confirmed'
                    else '❌' if cur == 'false_positive' else '⚪')
            tail = " (ещё не в базе)" if chk.get("live") and not cur else ""
            lbl = QLabel(f"{mark} {name}{tail}")
            lbl.setStyleSheet("font-size: 11px;")
            if chk.get("details"):
                lbl.setToolTip(str(chk["details"]))
            btn_ok = FPushButton("✓")
            btn_ok.setMaximumWidth(36)
            btn_ok.setToolTip("Подтвердить: правило сработало верно "
                              "(повторно — снять)")
            btn_ok.setCheckable(True)
            btn_ok.setChecked(cur == "confirmed")
            self._style_tag_btn(btn_ok, cur == "confirmed")
            btn_ok.clicked.connect(
                lambda _c, c=code, v=cur: self._set_verdict(
                    c, None if v == "confirmed" else "confirmed"))
            btn_no = FPushButton("✗")
            btn_no.setMaximumWidth(36)
            btn_no.setToolTip("Ложное: правило сработало зря "
                              "(повторно — снять)")
            btn_no.setCheckable(True)
            btn_no.setChecked(cur == "false_positive")
            self._style_tag_btn(btn_no, cur == "false_positive")
            btn_no.clicked.connect(
                lambda _c, c=code, v=cur: self._set_verdict(
                    c, None if v == "false_positive" else "false_positive"))
            self.verdicts_layout.addWidget(lbl, row, 0)
            self.verdicts_layout.addWidget(btn_ok, row, 1)
            self.verdicts_layout.addWidget(btn_no, row, 2)
        self.verdicts_widget.setVisible(True)

    def _set_verdict(self, check_code: str, verdict: str | None):
        if not self.current_case_id:
            return
        try:
            from autocheck_service import (
                ensure_case_check, get_case_checks, set_check_verdict)
            if not any(c.get("check_code") == check_code for c in
                       get_case_checks(self.project_path, self.current_case_id)):
                from autocheck_service import check_case, get_check_settings
                for c in check_case(self.current_case or {},
                                    get_check_settings(self.project_path)):
                    if c[0] == check_code:
                        ensure_case_check(
                            self.project_path, self.current_case_id,
                            c[0], c[1], c[2] if len(c) > 2 else "")
                        break
            set_check_verdict(self.project_path, self.current_case_id,
                              check_code, verdict)
        except Exception as e:
            self.show_error("Не удалось сохранить вердикт", e)
            return
        self._refresh_verdicts()

    def show_templates_menu(self):
        from templates_service import ordered_templates
        err = getattr(self, "current_error", None) or {}
        templates = ordered_templates(
            self.project_path, err.get("category_id"), err.get("subcategory_id"))
        if not templates:
            notify(self, "warning", "Шаблоны", "Нет доступных шаблонов")
            return
        menu = QMenu(self)
        for template in templates:
            label = template['text']
            if (err.get("category_id") and
                    template.get("category_id") == err.get("category_id")):
                if template.get("subcategory_id") == err.get("subcategory_id"):
                    label = "★ " + label
                else:
                    label = "☆ " + label
            action = menu.addAction(label)
            action.triggered.connect(
                lambda checked, t=template['text']: self.insert_template(t)
            )
        anchor = getattr(self, "btn_templates", None)
        if anchor is None:
            btns = getattr(self, "status_buttons", {}) or {}
            anchor = next(iter(btns.values()), None) or self
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))

    def insert_template(self, text: str):
        from templates_service import (TEMPLATE_VARS, build_template_context,
                                       render_template, template_vars)
        ctx = build_template_context(
            self.project_path, self.current_case_id or 0,
            getattr(self, "current_case", None),
            getattr(self, "current_error", None))
        rendered = render_template(text, ctx)
        # Неизвестные переменные — спрашиваем у человека (не придумываем).
        for var in template_vars(rendered):
            if var not in TEMPLATE_VARS:
                continue
            val, ok = QInputDialog.getText(
                self, "Шаблон", f"Значение для {{{var}}}:")
            if not ok:
                return
            ctx[var] = (val or "").strip()
        rendered = render_template(text, ctx)
        current = self.comment_edit.toPlainText()
        if current:
            self.comment_edit.setPlainText(current + "\n" + rendered)
        else:
            self.comment_edit.setPlainText(rendered)

    def add_new_template(self):
        text, ok = QInputDialog.getText(
            self,
            "Новый шаблон",
            "Введите текст шаблона комментария:"
        )
        if ok and text.strip():
            text = text.strip()
            # Привязка к причине текущего кейса (ТЗ §25): подходящие шаблоны
            # показываются первыми (★) при такой же причине.
            cat_id, sub_id = None, None
            err = getattr(self, "current_error", None) or {}
            if err.get("category_id"):
                label = err.get("category_name", "")
                if err.get("subcategory_name"):
                    label += f" → {err['subcategory_name']}"
                if confirm(self, "Привязка к причине",
                           f"Привязать шаблон к причине «{label}»?\n"
                           "Привязанные показываются первыми при такой же причине.\n"
                           "«Нет» — общий шаблон для всех."):
                    cat_id, sub_id = err.get("category_id"), err.get("subcategory_id")
            try:
                added = add_comment_template(self.project_path, text, cat_id, sub_id)
            except ValueError as e:
                notify(self, "warning", "Ошибка", str(e))
                return
            if added:
                notify(self, "success", "Шаблон добавлен", f"✅ Шаблон «{text}» добавлен")
            else:
                notify(self, "warning", "Ошибка", "Такой шаблон уже есть")

    def delete_template(self):
        """Удаляет пользовательский шаблон."""
        user_templates = get_user_templates(self.project_path)
        if not user_templates:
            notify(self, "warning", "Удаление", "Нет пользовательских шаблонов для удаления")
            return
        names = [t['text'] for t in user_templates]
        text, ok = QInputDialog.getItem(
            self,
            "Удалить шаблон",
            "Выберите шаблон для удаления:",
            names,
            0,
            False
        )
        if ok and text:
            tpl = next((t for t in user_templates if t['text'] == text), None)
            if tpl:
                if delete_comment_template(self.project_path, tpl['template_id']):
                    notify(self, "success", "Удаление", f"✅ Шаблон «{text}» удалён")
                else:
                    notify(self, "warning", "Ошибка", "Не удалось удалить шаблон")

    def update_tags_display(self, selected_tag_ids: set):
        while self.tags_layout.count():
            item = self.tags_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.selected_tags = selected_tag_ids.copy()
        self.tag_buttons.clear()
        try:
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT tag_id, tag_name, tag_code FROM tags ORDER BY tag_name")
                all_tags = cursor.fetchall()
            columns = 5
            row, col = 0, 0
            for tag in all_tags:
                tag_id = tag['tag_id']
                is_selected = tag_id in selected_tag_ids
                btn = FPushButton(tag['tag_name'])
                btn.setCheckable(True)
                btn.setChecked(is_selected)
                btn.setMinimumHeight(25)
                if is_selected:
                    btn.setStyleSheet(tag_button_style(True))
                else:
                    btn.setStyleSheet(tag_button_style(False))
                btn.clicked.connect(lambda checked, tid=tag_id: self.toggle_tag(tid))
                self.tags_layout.addWidget(btn, row, col)
                self.tag_buttons[tag_id] = btn
                col += 1
                if col >= columns:
                    col = 0
                    row += 1
        except Exception as e:
            logger.warning("tags display failed: %s", e)

    @staticmethod
    def _style_tag_btn(btn, selected: bool) -> None:
        btn.setStyleSheet(tag_button_style(selected))

    def toggle_tag(self, tag_id: int):
        added = tag_id not in self.selected_tags
        if tag_id in self.selected_tags:
            self.selected_tags.remove(tag_id)
        else:
            self.selected_tags.add(tag_id)
        self.save_tags()
        self._last_single = {"kind": "tag", "case_id": self.current_case_id,
                             "tag_id": tag_id, "added": added}
        if tag_id in self.tag_buttons:
            self._style_tag_btn(self.tag_buttons[tag_id],
                                tag_id in self.selected_tags)

    def on_create_tag(self):
        """Создать свой тег (ТЗ: пользовательские теги)."""
        text, ok = QInputDialog.getText(self, "Новый тег", "Название тега:")
        if not ok or not (text or "").strip():
            return
        name = text.strip()
        try:
            from tag_service import create_tag
            create_tag(self.project_path, name)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            self.update_tags_display(set(self.selected_tags))
        except Exception:
            pass
        notify(self, "success", "Тег", f"Тег «{name}» создан")

    def on_delete_tag(self):
        """Удалить неиспользуемый тег."""
        try:
            from tag_service import delete_tag, list_tags, usage_count
            tags = list_tags(self.project_path)
        except Exception as e:
            self.show_error("Не удалось загрузить теги", e)
            return
        if not tags:
            notify(self, "warning", "Теги", "Тегов нет")
            return
        names = []
        by_name = {}
        for t in tags:
            n = usage_count(self.project_path, t["tag_id"])
            label = f"{t['tag_name']} ({n} кейсов)"
            names.append(label)
            by_name[label] = t
        text, ok = QInputDialog.getItem(
            self, "Удалить тег", "Тег (удалить можно только неиспользуемый):",
            names, 0, False)
        if not ok or not text:
            return
        tag = by_name[text]
        if not confirm(self, "Удалить тег",
                       f"Удалить тег «{tag['tag_name']}»?",
                       ok_text="Удалить", cancel_text="Отмена"):
            return
        try:
            delete_tag(self.project_path, tag["tag_id"])
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.selected_tags.discard(tag["tag_id"])
        try:
            self.update_tags_display(set(self.selected_tags))
        except Exception:
            pass
        notify(self, "success", "Тег", f"Тег «{tag['tag_name']}» удалён")

    def save_tags(self):
        if not self.current_case_id:
            return
        try:
            from database import utcnow as _utcnow
            now = _utcnow()
            with db(self.project_path) as conn:
                cursor = conn.cursor()
                old_rows = cursor.execute(
                    "SELECT tag_id FROM case_tags WHERE case_id=?",
                    (self.current_case_id,)).fetchall()
                old_ids = {r["tag_id"] for r in old_rows}
                new_ids = set(self.selected_tags)
                cursor.execute("DELETE FROM case_tags WHERE case_id = ?", (self.current_case_id,))
                for tag_id in new_ids:
                    cursor.execute("""
                        INSERT INTO case_tags (case_id, tag_id, created_at)
                        VALUES (?, ?, ?)
                    """, (self.current_case_id, tag_id, now))
                for tid in sorted(new_ids - old_ids):
                    cursor.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'tag_added', 'tag', NULL, ?, ?)
                    """, (self.current_case_id, str(tid), now))
                for tid in sorted(old_ids - new_ids):
                    cursor.execute("""
                        INSERT INTO history (case_id, event_type, field_name,
                                             old_value, new_value, created_at)
                        VALUES (?, 'tag_removed', 'tag', ?, NULL, ?)
                    """, (self.current_case_id, str(tid), now))
        except Exception as e:
            logger.warning("save_tags failed: %s", e)

    def open_similar(self):
        """Похожие на текущий кейс (только контекст, статус не ставится)."""
        if not self.current_case_id:
            return
        from similar_dialog import SimilarDialog
        dlg = SimilarDialog(self.project_path, self.current_case_id, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_case_id:
            self._jump_to_case(dlg.result_case_id)

    def open_consistency(self):
        """Контроль качества: противоречия себе + QC-выборка."""
        from consistency_dialog import ConsistencyDialog
        from PySide6.QtWidgets import QDialog
        dlg = ConsistencyDialog(self.project_path, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_case_id:
            self._jump_to_case(dlg.result_case_id)

    def open_bug_report(self):
        """Полный Bug Report из текущего кейса (контекст подставляется)."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import build_from_case
            prefill = build_from_case(self.project_path, self.current_case_id)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, prefill, None, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_id:
            notify(self, "success", "Баг", f"Создан баг #{dlg.result_id}")

    def open_quick_bug(self):
        """Быстрый баг: только заголовок, остальное — из кейса."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import build_from_case
            prefill = build_from_case(self.project_path, self.current_case_id)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import QuickBugDialog
        dlg = QuickBugDialog(self.project_path, prefill, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_id:
            notify(self, "success", "Баг", f"Создан баг #{dlg.result_id}")
            self.update_info_label()

    def open_case_bugs(self):
        """Баги кейса (ID/status/severity/title) — клик открывает баг."""
        if not self.current_case_id:
            return
        try:
            from bug_report_service import bugs_for_case
            items = bugs_for_case(self.project_path, self.current_case_id)
        except Exception as e:
            self.show_error("Не удалось загрузить баги", e)
            return
        if not items:
            notify(self, "warning", "Баги", "У кейса пока нет багов — создай 🐞")
            return
        menu = QMenu(self)
        for b in items:
            action = menu.addAction(
                f"#{b['bug_id']} [{b['status']}/{b['severity']}] {b['title'][:60]}")
            action.triggered.connect(
                lambda _c, bid=b["bug_id"]: self._open_bug_dialog(bid))
        anchor = getattr(self, "btn_case_bugs", None) or self
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _open_bug_dialog(self, bug_id: int):
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, None, bug_id, self)
        dlg.exec()
        self.update_info_label()
        cid = getattr(dlg, "result_case_id", None)
        if cid and cid in (self.case_ids or []):
            try:
                self.load_case(self.case_ids.index(cid))
            except Exception:
                pass

    def copy_case_context(self):
        """V2.1 §8: одно действие — Markdown в буфер; Shift+клик — Plain."""
        if not self.current_case_id:
            return
        try:
            from PySide6.QtCore import Qt as _Qt
            from PySide6.QtWidgets import QApplication as _QA
            mods = _QA.keyboardModifiers()
            fmt = "plain" if (mods & _Qt.KeyboardModifier.ShiftModifier) else "markdown"
        except Exception:
            fmt = "markdown"
        self._do_copy_context(fmt, "Plain Text" if fmt == "plain" else "Markdown")

    def open_compare(self):
        """V2.1 §7 'Сравнить': ответы прогонов по текущему кейсу рядом."""
        if not self.current_case_id:
            return
        cid = self.current_case_id
        try:
            from database import db as _db
            with _db(self.project_path) as _conn:
                runs = [dict(r) for r in _conn.execute(
                    "SELECT DISTINCT a.run_id, r.name FROM run_answers a "
                    "JOIN model_runs r ON r.run_id = a.run_id "
                    "WHERE a.case_id = ? ORDER BY a.run_id DESC LIMIT 2",
                    (cid,)).fetchall()]
        except Exception as e:
            self.show_error("Не удалось найти прогоны", e)
            return
        if len(runs) < 2:
            notify(self, "warning", "Сравнение",
                   "Нужно минимум 2 прогона с этим кейсом. "
                   "Открой «Прогоны» и импортируй ответы.")
            try:
                mw = getattr(getattr(self, "parent_window", None),
                             "main_window", None)
                if mw is not None and hasattr(mw, "show_screen"):
                    mw.show_screen("runs")
            except Exception:
                pass
            return
        try:
            from compare_dialog import CompareDialog
            dlg = CompareDialog(self.project_path, runs[1]["run_id"],
                                runs[0]["run_id"], self)
            dlg.exec()
        except Exception as e:
            self.show_error("Не удалось открыть сравнение", e)
        # остаёмся на том же кейсе: контекст не разрушен

    def _do_copy_context(self, fmt: str, label: str):
        import bug_export_service as bex
        try:
            text = bex.render_case(self.project_path, self.current_case_id, fmt)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            import clipboard_service as _clip
            _clip.safe_copy(text)
            _after = _clip.get_clear_after()
            suffix = (f" Буфер очистится через {_clip.timeout_label(_after)}."
                      if _after else "")
        except Exception:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
            suffix = ""
        notify(self, "success", "Скопировано", f"Контекст ({label}) — в буфере.{suffix}")

    def copy_for_developer(self):
        """V2.2 §15: копия для разработчика без создания Bug Report.

        Тот же render_case (CASE/QUERY/RESPONSE/REFERENCE/REVIEW/...),
        Markdown в буфер; Shift+клик — Plain. Баг не создаётся.
        """
        self.copy_case_context()

    def open_duplicates(self):
        """Потенциальные дубли в области текущего фильтра/файла."""
        from similar_dialog import DuplicatesDialog
        fid = (self.filters or {}).get("file_id")
        dlg = DuplicatesDialog(self.project_path, fid, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_case_id:
            self._jump_to_case(dlg.result_case_id)

    def update_filter_indicator(self):
        base = ""
        if not self.filters:
            base = "Фильтры не применены"
        else:
            parts = []
            if self.filters.get('statuses'):
                parts.append(f"статусы: {', '.join(self.filters['statuses'])}")
            if self.filters.get('file_id'):
                parts.append("фильтр по файлу")
            if self.filters.get('has_comment') is not None:
                parts.append("фильтр по комментарию")
            if self.filters.get('tags'):
                parts.append(f"тегов: {len(self.filters['tags'])}")
            if self.filters.get('checks'):
                parts.append(f"автопроверок: {len(self.filters['checks'])}")
            if self.filters.get('check_severities'):
                parts.append(f"severity: {','.join(self.filters['check_severities'])}")
            if self.filters.get('error_category_id'):
                parts.append("по причине ✓")
            if self.filters.get('error_severities'):
                parts.append(f"крит.: {','.join(self.filters['error_severities'])}")
            if self.filters.get('search_text'):
                parts.append(f"поиск: '{self.filters['search_text']}'")
            _pf = (self.filters.get('reviewed_from') or '').strip()
            _pt = (self.filters.get('reviewed_to') or '').strip()
            if _pf or _pt:
                parts.append(f"период: {_pf or '…'}–{_pt or '…'}")
            base = ("⚠️ Фильтры: " + " · ".join(parts)) if parts else "Фильтры не применены"
        # Всегда показываем размер выборки — видно, что фильтр сработал
        self._filter_base = f"{base} · Найдено: {len(self.case_ids)}"
        try:
            import visibility_service as _vis
            _hn = _vis.hidden_count(self.project_path)
            if _hn:
                self._filter_base += f" · 👁 Скрыто: {_hn}"
        except Exception:
            pass
        self.filter_indicator.setText(self._filter_base)
        try:
            self.filter_indicator.setToolTip(self._filter_base)
        except Exception:
            pass

    def open_filters(self):
        dialog = FilterDialog(self.project_path, self)
        if self.filters:
            dialog.set_filters(self.filters)
        dialog.set_view(self._current_view())
        if dialog.exec() == FilterDialog.Accepted:
            new_filters = dialog.get_filters()
            try:
                filtered_ids = get_filtered_case_ids(self.project_path, new_filters)
            except Exception as e:
                self.show_error("Не удалось применить фильтры", e)
                return
            # Пустой результат — тоже валиден: показываем пустую выборку,
            # а не молча оставляем старые фильтры (иначе таблица и кейс-вид расходятся).
            if not filtered_ids:
                notify(
                    self,
                    "warning",
                    "Внимание",
                    "Нет кейсов, соответствующих выбранным фильтрам.\n"
                    "Показана пустая выборка."
                )
            self.filters = new_filters
            self._apply_view(dialog.get_view())
            # Выборку пересчитываем через очередь (вид мог сменить queue_mode).
            try:
                self.load_case_ids()
            except Exception:
                self.case_ids = filtered_ids
            self.current_index = 0
            self.bulk_selected.clear()
            self.update_filter_indicator()
            self.update_queue_indicator()
            notify(self, "success", "Фильтры", f"Найдено кейсов: {len(filtered_ids)}")
            if self.case_ids:
                self.load_case(0)
            else:
                self.current_case = None
                self.current_case_id = None
