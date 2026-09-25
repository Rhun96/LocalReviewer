"""Регрессионное тестирование: baseline vs candidate, gate PASS/FAIL, экспорт."""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QFileDialog, QFormLayout, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt
from ui_compat import (FComboBox, FLineEdit, FPrimaryButton, FPushButton,
                       FSpinBox, clear_in_fluent, confirm, notify,
                       polish_table)
import regression_service as rg


class RegressionDialog(QDialog):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.setWindowTitle("Регрессионное тестирование")
        self.setMinimumSize(920, 660)
        self._reg_id = None
        self._init_ui()
        self._reload_lists()

    def _init_ui(self):
        layout = QVBoxLayout()
        form = QFormLayout()
        self.name_edit = FLineEdit()
        self.name_edit.setPlaceholderText("Название запуска, например rel-1.8")
        form.addRow("Название:", self.name_edit)
        self.base_combo = FComboBox()
        form.addRow("Baseline (эталон):", self.base_combo)
        self.cand_combo = FComboBox()
        form.addRow("Кандидат (прогон или версия):", self.cand_combo)
        gate_row = QHBoxLayout()
        self.gate_crit = FSpinBox()
        self.gate_crit.setRange(0, 100000)
        self.gate_crit.setValue(0)
        gate_row.addWidget(QLabel("Макс. критических:"))
        gate_row.addWidget(self.gate_crit)
        self.gate_rate = FSpinBox()
        self.gate_rate.setRange(0, 100)
        self.gate_rate.setValue(2)
        self.gate_rate.setSuffix(" %")
        gate_row.addWidget(QLabel("Макс. regression rate:"))
        gate_row.addWidget(self.gate_rate)
        gate_row.addStretch()
        form.addRow("Gate:", gate_row)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_run = FPrimaryButton("▶ Запустить сравнение")
        btn_run.clicked.connect(self._run)
        btn_row.addWidget(btn_run)
        btn_row.addWidget(QLabel("Прошлые:"))
        self.past_combo = FComboBox()
        btn_row.addWidget(self.past_combo, 2)
        btn_load = FPushButton("Открыть")
        btn_load.clicked.connect(self._load_past)
        btn_row.addWidget(btn_load)
        btn_del = FPushButton("🗑")
        btn_del.setMaximumWidth(44)
        btn_del.clicked.connect(self._delete_past)
        btn_row.addWidget(btn_del)
        layout.addLayout(btn_row)

        self.summary = QLabel("Выбери baseline и кандидата, нажми «Запустить».")
        self.summary.setWordWrap(True)
        self.summary.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.summary)

        # Карточки gate: итог считывается за секунду, детали — ниже в таблице.
        self.gate_cards = {}
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for _key, _caption in (("gate", "Gate"), ("total", "Всего"),
                               ("reg", "Регрессии"), ("imp", "Улучшения"),
                               ("same", "Без изменений")):
            _frame, _value = self._make_gate_card(_caption)
            self.gate_cards[_key] = (_frame, _value)
            cards_row.addWidget(_frame)
        layout.addLayout(cards_row)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Итог:"))
        self.result_combo = FComboBox()
        self.result_combo.addItem("Все", None)
        for code in ("REGRESSION", "IMPROVED", "UNCHANGED", "NEW", "REMOVED",
                     "UNRESOLVED"):
            self.result_combo.addItem(rg.RESULT_NAMES.get(code, code), code)
        filt.addWidget(self.result_combo)
        filt.addWidget(QLabel("Severity:"))
        self.sev_combo = FComboBox()
        self.sev_combo.addItem("Все", None)
        for code in ("critical", "warning", "info"):
            self.sev_combo.addItem(rg.SEVERITY_NAMES.get(code, code), code)
        filt.addWidget(self.sev_combo)
        btn_apply = FPushButton("Применить")
        btn_apply.clicked.connect(self._load_results)
        filt.addWidget(btn_apply)
        btn_export = FPushButton("📤 Экспорт регрессий")
        btn_export.clicked.connect(self._export)
        filt.addWidget(btn_export)
        btn_bug = FPushButton("🐞 Создать баг")
        btn_bug.setToolTip("Баг из выбранной строки — контекст подставится сам")
        btn_bug.clicked.connect(self._create_bug)
        filt.addWidget(btn_bug)
        layout.addLayout(filt)

        # V2.1 §15: assertions — панель + колонка «Проверки» в таблице.
        from PySide6.QtWidgets import QGroupBox as _GB, QListWidget as _LW
        agroup = _GB("✓ Проверки ответов (без LLM, формальные условия)")
        alay = QVBoxLayout()
        self.assert_list = _LW()
        self.assert_list.setMaximumHeight(96)
        alay.addWidget(self.assert_list)
        abtns = QHBoxLayout()
        btn_a_add = FPushButton("＋ Проверка")
        btn_a_add.clicked.connect(self._assert_add)
        btn_a_del = FPushButton("－ Убрать")
        btn_a_del.clicked.connect(self._assert_delete)
        btn_a_run = FPrimaryButton("▶ Проверить кандидата")
        btn_a_run.setToolTip("Массовый запуск в фоне: прогресс, отмена")
        btn_a_run.clicked.connect(self._assert_run)
        abtns.addWidget(btn_a_add)
        abtns.addWidget(btn_a_del)
        abtns.addStretch()
        abtns.addWidget(btn_a_run)
        alay.addLayout(abtns)
        self.assert_summary = QLabel("Проверки не запускались.")
        self.assert_summary.setWordWrap(True)
        alay.addWidget(self.assert_summary)
        agroup.setLayout(alay)
        layout.addWidget(agroup)
        self._assert_map: dict = {}

        self.table = QTableWidget()
        layout.addWidget(self.table, 2)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass
        btn_close = FPushButton("Закрыть")
        btn_close.clicked.connect(self.accept)
        layout.addWidget(btn_close)
        self.setLayout(layout)
        self._reload_assertions()

    @staticmethod
    def _make_gate_card(caption: str):
        """Мини-карточка сводки: подпись сверху, крупное значение."""
        frame = QFrame()
        frame.setObjectName("gateCard")
        frame.setStyleSheet(
            "#gateCard { border: 1px solid #3a3a3a; border-radius: 8px; }")
        frame.setSizePolicy(QSizePolicy.Policy.Expanding,
                            QSizePolicy.Policy.Fixed)
        lay = QVBoxLayout()
        lay.setSpacing(2)
        lay.setContentsMargins(8, 6, 8, 6)
        cap = QLabel(caption)
        cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cap.setStyleSheet("font-size: 11px; color: #888888;")
        val = QLabel("—")
        val.setAlignment(Qt.AlignmentFlag.AlignCenter)
        val.setStyleSheet("font-size: 16px; font-weight: bold;")
        lay.addWidget(cap)
        lay.addWidget(val)
        frame.setLayout(lay)
        return frame, val

    def _reload_lists(self):
        try:
            pool = rg.list_baseline_candidates(self.project_path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        self.base_combo.clear()
        for b in pool:
            mark = "" if b.get("frozen", True) else " ⚠ не заморожен"
            self.base_combo.addItem(b["label"] + mark, (b["type"], b["id"]))
        # Кандидат — тот же пул: прогон или версия датасета (v20).
        self.cand_combo.clear()
        for b in pool:
            mark = "" if b.get("frozen", True) else " ⚠ не заморожен"
            self.cand_combo.addItem(b["label"] + mark, (b["type"], b["id"]))
        self._reload_past()

    def _reload_past(self):
        try:
            past = rg.list_regressions(self.project_path)
        except Exception:
            past = []
        self.past_combo.clear()
        for p in past:
            self.past_combo.addItem(
                f"{p['name']} [{p['gate_result']}] "
                f"регр:{p['regressions']}/{p['total']}", p["regression_id"])

    def _run(self):
        name = self.name_edit.text().strip()
        base = self.base_combo.currentData()
        cand = self.cand_combo.currentData()
        if not name:
            notify(self, "warning", "Внимание", "Введи название запуска")
            return
        if not base or not cand:
            notify(self, "warning", "Внимание", "Выбери baseline и кандидата")
            return
        try:
            rid = rg.run_regression(
                self.project_path, name, base[0], base[1], cand[0], cand[1],
                gate_max_critical=self.gate_crit.value(),
                gate_max_rate=self.gate_rate.value() / 100)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._reg_id = rid
        self._reload_past()
        self._show_summary()
        self._load_results()

    def _load_past(self):
        rid = self.past_combo.currentData()
        if not rid:
            return
        self._reg_id = rid
        self._show_summary()
        self._load_results()

    def _delete_past(self):
        rid = self.past_combo.currentData()
        if not rid:
            return
        if not confirm(self, "Подтверждение", "Удалить запуск регрессии?"):
            return
        try:
            rg.delete_regression(self.project_path, rid)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        if self._reg_id == rid:
            self._reg_id = None
        self._reload_past()

    def _show_summary(self):
        reg = rg.get_regression(self.project_path, self._reg_id)
        if not reg:
            return
        gate = reg["gate_result"] or "?"
        n_reg = reg["regressions"] or 0
        n_imp = reg["improvements"] or 0
        if n_reg > n_imp:
            balance = "в целом хуже baseline"
        elif n_imp > n_reg:
            balance = "в целом лучше baseline"
        else:
            balance = "паритет с baseline"
        passed = gate == "PASS"
        self._set_gate_card("gate", "✅ PASS" if passed else "❌ FAIL",
                            "#2ea043" if passed else "#c0392b")
        self._set_gate_card("total", str(reg["total"] or 0), None)
        self._set_gate_card("reg", str(n_reg),
                            "#c0392b" if n_reg else None)
        self._set_gate_card("imp", str(n_imp),
                            "#2ea043" if n_imp else None)
        self._set_gate_card("same", str(reg["unchanged"] or 0), None)
        self.summary.setText(
            f"{reg['name']}: {rg.candidate_label(self.project_path, reg)}, "
            f"rate {reg['regression_rate']:.1%}."
            f" ⚖️ Баланс: {balance} (по числу кейсов; решает gate).")

    def _set_gate_card(self, key: str, value: str, color: str | None):
        try:
            frame, val = self.gate_cards[key]
            val.setText(value)
            border = color or "#3a3a3a"
            frame.setStyleSheet(
                "#gateCard { border: 1px solid " + border
                + "; border-radius: 8px; }")
            if color:
                val.setStyleSheet("font-size: 16px; font-weight: bold; "
                                  "color: " + color + ";")
            else:
                val.setStyleSheet("font-size: 16px; font-weight: bold;")
        except Exception:
            pass

    def _load_results(self):
        if not self._reg_id:
            return
        try:
            rows = rg.list_regression_results(
                self.project_path, self._reg_id,
                result=self.result_combo.currentData(),
                severity=self.sev_combo.currentData())
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.table.clear()
        self.table.setColumnCount(7)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["Ключ", "Было", "Стало", "Итог", "Severity", "Проверки", "Запрос"])
        amap = getattr(self, "_assert_map", None) or {}
        for i, r in enumerate(rows):
            key = r["source_id"] or r["stable_key"]
            self.table.setItem(i, 0, QTableWidgetItem(str(key)[:40]))
            self.table.setItem(i, 1, QTableWidgetItem(r["baseline_status"] or "—"))
            self.table.setItem(i, 2, QTableWidgetItem(r["candidate_status"] or "—"))
            self.table.setItem(i, 3, QTableWidgetItem(
                rg.RESULT_NAMES.get(r["result"], r["result"] or "")))
            self.table.setItem(i, 4, QTableWidgetItem(
                rg.SEVERITY_NAMES.get(r["severity"], r["severity"] or "")))
            a = amap.get(r["stable_key"])
            if a is None:
                cell = QTableWidgetItem("—")
            else:
                cell = QTableWidgetItem(f"✓ {a['passed']}  ❌ {a['failed']}")
                det = "; ".join(f"{d['name']}: {d['detail']}"
                                for d in (a.get("details") or [])[:5])
                if det:
                    cell.setToolTip(det)
            self.table.setItem(i, 5, cell)
            self.table.setItem(i, 6, QTableWidgetItem((r["primary_text"] or "")[:80]))
        self.table.resizeColumnsToContents()

    def _export(self):
        if not self._reg_id:
            notify(self, "warning", "Внимание", "Сначала запусти сравнение")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Экспорт регрессий", "regressions.xlsx",
            "Excel (*.xlsx)")
        if not path:
            return
        try:
            out = rg.export_regressions_xlsx(self.project_path, self._reg_id, path)
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            return
        notify(self, "success", "Экспорт", f"Сохранено:\n{out}")

    def _create_bug(self):
        """Баг из выбранной строки регрессии — без ручного копирования (§34)."""
        if not self._reg_id:
            notify(self, "warning", "Внимание", "Сначала запусти сравнение")
            return
        item = self.table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери строку в таблице")
            return
        # Строка таблицы 1-в-1 соответствует выдаче с текущими фильтрами.
        try:
            rows = rg.list_regression_results(
                self.project_path, self._reg_id,
                result=self.result_combo.currentData(),
                severity=self.sev_combo.currentData())
            row = rows[item.row()] if 0 <= item.row() < len(rows) else None
        except Exception as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        if not row:
            return
        try:
            prefill = rg.bug_prefill(self.project_path, self._reg_id,
                                     row["stable_key"])
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        from bug_report_dialog import BugReportDialog
        dlg = BugReportDialog(self.project_path, prefill, None, self)
        dlg.exec()

    # --- assertions V2.1 §15 ---

    def _reload_assertions(self):
        try:
            import regression_assertion_service as ra
            items = ra.list_assertions(self.project_path)
        except Exception:
            items = []
        from PySide6.QtCore import Qt as _Qt
        from PySide6.QtWidgets import QListWidgetItem as _LWI
        self.assert_list.clear()
        for a in items:
            mark = "✓" if a.get("enabled") else "○"
            it = _LWI(f"{mark} {a.get('name','')} "
                      f"[{a.get('atype','')}/{a.get('severity','')}]")
            it.setData(_Qt.ItemDataRole.UserRole, a.get("assert_id"))
            it.setToolTip(str(a.get("params_json") or ""))
            self.assert_list.addItem(it)

    def _assert_add(self):
        from PySide6.QtWidgets import QInputDialog
        import regression_assertion_service as ra
        from constants import ASSERTION_TYPES
        names = [f"{c} — {n}" for c, n in ASSERTION_TYPES]
        pick, ok = QInputDialog.getItem(self, "Проверка", "Тип:", names, 0, False)
        if not ok:
            return
        atype = pick.split(" — ", 1)[0].strip()
        name, ok = QInputDialog.getText(self, "Проверка", "Название:")
        if not ok or not (name or "").strip():
            return
        params: dict = {}
        if atype in ("min_length", "max_length"):
            val, ok = QInputDialog.getInt(self, "Проверка", "N:", 10, 1, 100000)
            if not ok:
                return
            params = {"n": val}
        elif atype in ("contains", "not_contains", "exact_match"):
            val, ok = QInputDialog.getText(self, "Проверка", "Текст:")
            if not ok or not val:
                return
            params = {"text": val}
        elif atype == "regex":
            val, ok = QInputDialog.getText(self, "Проверка", "Pattern:")
            if not ok or not val:
                return
            import re as _re
            try:
                _re.compile(val)
            except _re.error as e:
                notify(self, "warning", "Ошибка", f"Битый regex: {e}")
                return
            params = {"pattern": val}
        elif atype == "contains_keyword":
            val, ok = QInputDialog.getText(self, "Проверка",
                                           "Ключевые слова через запятую:")
            if not ok or not val.strip():
                return
            params = {"keywords": [k.strip() for k in val.split(",")
                                   if k.strip()]}
        try:
            ra.create_assertion(self.project_path, name.strip(), atype, params)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._reload_assertions()

    def _assert_delete(self):
        item = self.assert_list.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери проверку в списке")
            return
        from PySide6.QtCore import Qt as _Qt
        aid = item.data(_Qt.ItemDataRole.UserRole)
        if not confirm(self, "Подтверждение", "Убрать проверку?"):
            return
        try:
            import regression_assertion_service as ra
            ra.delete_assertion(self.project_path, aid)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._reload_assertions()

    def _assert_run(self):
        cand = self.cand_combo.currentData() or (None, None)
        if cand[0] != "run" or not cand[1]:
            notify(self, "warning", "Внимание",
                   "Проверки — только для кандидата-прогона "
                   "(у версий нет текстов ответов)")
            return
        run_id = cand[1]
        import regression_assertion_service as ra
        asserts = [a for a in ra.list_assertions(self.project_path)
                   if a.get("enabled")]
        if not asserts:
            notify(self, "warning", "Внимание",
                   "Нет включённых проверок — добавь и запусти снова")
            return
        from PySide6.QtWidgets import QProgressDialog as _PD
        from PySide6.QtCore import Qt as _Qt
        pd = _PD("Проверки ответов…", "Отмена", 0, 100, self)
        pd.setWindowModality(_Qt.WindowModality.WindowModal)
        pd.setMinimumDuration(300)
        cancelled = {"v": False}
        pd.canceled.connect(lambda: cancelled.__setitem__("v", True))
        import workers
        holder: dict = {}

        def _job():
            def _cb(pct):
                try:
                    pd.setValue(int(pct))
                except Exception:
                    pass
                if cancelled["v"]:
                    from workers import Cancelled as _C
                    raise _C("отменено пользователем")
            return ra.run_assertions(self.project_path, run_id, asserts,
                                     progress_cb=_cb,
                                     cancel_flag=lambda: cancelled["v"])

        def _done(res):
            try:
                pd.close()
            except Exception:
                pass
            holder["map"] = res
            self._assert_map = res
            s = ra.summarize(res)
            self.assert_summary.setText(
                f"✓ {s['checked'] - s['failed']} без нарушений, "
                f"❌ {s['failed']} с нарушениями "
                f"(критических: {s['failed_critical']}). "
                "Gate это не блокирует (счёт информативный).")
            self._load_results()
            self._worker = None

        def _err(msg):
            try:
                pd.close()
            except Exception:
                pass
            if "отмен" in str(msg).lower():
                notify(self, "warning", "Отмена", "Проверки отменены")
            else:
                notify(self, "error", "Ошибка", str(msg))
            self._worker = None

        self._worker = workers.run_in_background(
            _job, on_finished=_done, on_error=_err)
