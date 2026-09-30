"""Экран «Баги» (ТЗ V2 §21): таблица, фильтры, поиск, создание/правка."""
from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QWidget,
    QAbstractItemView,
)
from PySide6.QtCore import Qt
from database import db
from ui_base import BaseScreen
from ui_compat import (FComboBox, FLineEdit, FPushButton, FPrimaryButton,
                       clear_in_fluent, confirm, notify, polish_table)
import bug_report_service as bugs


class BugReportsScreen(BaseScreen):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(8)
        title = QLabel("🐞 БАГИ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        filt = QHBoxLayout()
        filt.addWidget(QLabel("Статус:"))
        self.status_combo = FComboBox()
        self.status_combo.addItem("Все", None)
        for s in bugs.STATUSES:
            self.status_combo.addItem(bugs.BUG_STATUS_NAMES.get(s, s), s)
        filt.addWidget(self.status_combo)
        filt.addWidget(QLabel("Критичность:"))
        self.sev_combo = FComboBox()
        self.sev_combo.addItem("Все", None)
        for s in bugs.SEVERITIES:
            self.sev_combo.addItem(bugs.BUG_SEVERITY_NAMES.get(s, s), s)
        filt.addWidget(self.sev_combo)
        filt.addWidget(QLabel("Трекер:"))
        self.tracker_combo = FComboBox()
        self.tracker_combo.addItem("Все", None)
        self.tracker_combo.addItem("С external ID", "__has__")
        self.tracker_combo.addItem("Без external ID", "__none__")
        filt.addWidget(self.tracker_combo)
        layout.addLayout(filt)

        search_row = QHBoxLayout()
        self.search_edit = FLineEdit()
        self.search_edit.setPlaceholderText(
            "Поиск: заголовок, описание, ID кейса, external ID… (Enter)")
        self.search_edit.returnPressed.connect(self.refresh)
        search_row.addWidget(self.search_edit, 3)
        btn_find = FPushButton("🔍 Найти")
        btn_find.clicked.connect(self.refresh)
        search_row.addWidget(btn_find)
        layout.addLayout(search_row)

        from PySide6.QtWidgets import QSplitter
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.table = QTableWidget()
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.ExtendedSelection)
        splitter.addWidget(self.table)
        try:
            clear_in_fluent(self.table)
            polish_table(self.table, stretch_last=True)
        except Exception:
            pass
        splitter.setStretchFactor(0, 3)

        card_wrap = QWidget()
        card_layout = QVBoxLayout()
        card_layout.setContentsMargins(0, 0, 0, 0)
        self.card_title = QLabel("Карточка бага")
        self.card_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        self.card_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self.card_title)
        self.card_host = QVBoxLayout()
        self.card_host.setContentsMargins(0, 0, 0, 0)
        card_layout.addLayout(self.card_host, 1)
        card_wrap.setLayout(card_layout)
        splitter.addWidget(card_wrap)
        splitter.setStretchFactor(1, 2)
        try:
            splitter.setSizes([900, 460])
        except Exception:
            pass
        layout.addWidget(splitter, 2)
        self.card_widget = None
        self.card_id = None
        self._placeholder_card()

        btns = QHBoxLayout()
        btn_new = FPrimaryButton("＋ Баг")
        btn_new.setToolTip("Пустой баг в карточке справа (кейсы привяжешь внутри)")
        btn_new.clicked.connect(self._new_bug)
        btn_open = FPushButton("📝 Открыть")
        btn_open.setToolTip("Показать выбранный баг в карточке справа")
        btn_open.clicked.connect(self._open_bug)
        btn_copy = FPushButton("📋 Копировать")
        btn_copy.setToolTip("Скопировать выбранный баг без открытия карточки "
                            "(Jira/Markdown/Plain, контекст подтянется сам)")
        btn_copy.clicked.connect(self._copy_menu)
        btn_del = FPushButton("🗑 Удалить")
        btn_del.setToolTip("Удалить выбранные (можно несколько строк)")
        btn_del.clicked.connect(self._delete_bugs)
        btn_bulk_status = FPushButton("📝 Статус")
        btn_bulk_status.setToolTip("Сменить статус выбранным")
        btn_bulk_status.clicked.connect(self._bulk_status_menu)
        btn_bulk_sev = FPushButton("❗ Критичность")
        btn_bulk_sev.setToolTip("Сменить критичность выбранным")
        btn_bulk_sev.clicked.connect(self._bulk_sev_menu)
        btn_dup = FPushButton("🔗 Дубликат…")
        btn_dup.setToolTip("Пометить выбранный дубликатом другого (по ID)")
        btn_dup.clicked.connect(self._mark_dup_flow)
        btn_merge = FPushButton("🧬 Объединить")
        btn_merge.setToolTip("Слить выбранные в текущий (кейсы переедут)")
        btn_merge.clicked.connect(self._merge_flow)
        btn_similar = FPushButton("👯 Похожие")
        btn_similar.setToolTip("Группы похожих багов по формулировкам")
        btn_similar.clicked.connect(self._similar_flow)
        btns.addWidget(btn_new)
        btns.addWidget(btn_open)
        btns.addWidget(btn_copy)
        btns.addWidget(btn_del)
        btns.addWidget(btn_bulk_status)
        btns.addWidget(btn_bulk_sev)
        btns.addWidget(btn_dup)
        btns.addWidget(btn_merge)
        btns.addWidget(btn_similar)
        btns.addStretch()
        layout.addLayout(btns)
        self.setLayout(layout)
        self.table.itemDoubleClicked.connect(lambda _i: self._open_bug())
        try:
            self.table.itemSelectionChanged.connect(self._on_selection)
        except Exception:
            pass

    def refresh(self):
        has_ext = None
        tracker = self.tracker_combo.currentData()
        if tracker == "__has__":
            has_ext, tracker = True, None
        elif tracker == "__none__":
            has_ext, tracker = False, None
        try:
            rows = bugs.list_bugs(
                self.project_path,
                status=self.status_combo.currentData(),
                severity=self.sev_combo.currentData(),
                tracker=tracker, has_external=has_ext,
                search=self.search_edit.text())
        except Exception as e:
            notify(self, "error", "Ошибка", str(e))
            rows = []
        self._rows = rows
        try:
            with db(self.project_path) as conn:
                cats = {r["category_id"]: r["name"] for r in conn.cursor().execute(
                    "SELECT category_id, name FROM error_categories").fetchall()}
        except Exception:
            cats = {}
        try:
            self.table.blockSignals(True)
        except Exception:
            pass
        self.table.clear()
        self.table.setColumnCount(9)
        self.table.setRowCount(len(rows))
        self.table.setHorizontalHeaderLabels(
            ["ID", "Заголовок", "Статус", "Критичность", "Категория", "Кейсы",
             "External", "Обновлён", "Дубль"])
        # Цвет статуса и критичности (только foreground — делегат библиотеки).
        try:
            from PySide6.QtGui import QColor as _QC
            from styles import SEMANTIC as _SEM, COLORS as _CC
            _ST_FG = {"New": _QC(_SEM["info"]),
                      "Confirmed": _QC(_SEM["warning"]),
                      "In Progress": _QC(_CC["blue"]),
                      "Fixed": _QC(_SEM["success"]),
                      "Rejected": _QC(_CC["gray"]),
                      "Duplicate": _QC(_CC["gray"])}
            _SEV_FG = {"Critical": _QC(_SEM["danger"]),
                       "High": _QC(_SEM["danger"]),
                       "Medium": _QC(_SEM["warning"]),
                       "Low": _QC(_CC["gray"])}
        except Exception:
            _ST_FG = {}
            _SEV_FG = {}
        for i, r in enumerate(rows):
            cat = cats.get(r["category_id"], "") if r["category_id"] else ""
            st = bugs.BUG_STATUS_NAMES.get(r["status"] or "", r["status"] or "")
            sv = bugs.BUG_SEVERITY_NAMES.get(r["severity"] or "", r["severity"] or "")
            self.table.setItem(i, 0, QTableWidgetItem(str(r["bug_id"])))
            self.table.setItem(i, 1, QTableWidgetItem((r["title"] or "")[:80]))
            _st_item = QTableWidgetItem(st)
            try:
                _fg = _ST_FG.get(r["status"] or "")
                if _fg is not None:
                    _st_item.setForeground(_fg)
            except Exception:
                pass
            self.table.setItem(i, 2, _st_item)
            _sev_item = QTableWidgetItem(sv)
            try:
                _fg = _SEV_FG.get(r["severity"] or "")
                if _fg is not None:
                    _sev_item.setForeground(_fg)
            except Exception:
                pass
            self.table.setItem(i, 3, _sev_item)
            self.table.setItem(i, 4, QTableWidgetItem(cat))
            self.table.setItem(i, 5, QTableWidgetItem(str(r["cases"])))
            self.table.setItem(i, 6, QTableWidgetItem(r["external_id"] or "—"))
            from ui_compat import format_dt as _fdt
            self.table.setItem(i, 7, QTableWidgetItem(_fdt(r["updated_at"])))
            _dup = r.get("duplicate_of")
            self.table.setItem(
                i, 8, QTableWidgetItem(f"→ #{_dup}" if _dup else "—"))
            self.table.item(i, 0).setData(Qt.ItemDataRole.UserRole, r["bug_id"])
        try:
            self.table.blockSignals(False)
        except Exception:
            pass
        self.table.resizeColumnsToContents()

    def _selected_id(self) -> int | None:
        item = self.table.currentItem()
        if item is None:
            notify(self, "warning", "Внимание", "Выбери баг в таблице")
            return None
        row_item = self.table.item(item.row(), 0)
        return row_item.data(Qt.ItemDataRole.UserRole) if row_item else None

    def _clear_card(self):
        while self.card_host.count():
            item = self.card_host.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.card_widget = None

    def _placeholder_card(self):
        self._clear_card()
        self.card_id = None
        try:
            self.card_title.setText("Карточка бага")
        except Exception:
            pass
        hint = QLabel("Выбери баг слева — карточка откроется здесь")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.card_host.addWidget(hint)
        self.card_widget = hint

    def open_card(self, bug_id: int | None):
        """Карточка справа: существующий баг или пустая (None)."""
        from bug_report_dialog import BugReportWidget
        if bug_id == self.card_id and self.card_widget is not None:
            try:
                self.card_widget.title_edit.setFocus()
            except Exception:
                pass
            return
        if not self._maybe_autosave():
            return
        self._clear_card()
        self.card_id = bug_id
        try:
            self.card_title.setText(
                f"Баг #{bug_id}" if bug_id is not None else "Новый баг")
        except Exception:
            pass
        w = BugReportWidget(self.project_path, None, bug_id, self)
        try:
            w.saved.connect(self._on_card_saved)
            w.goto_case.connect(self._on_card_goto)
        except Exception:
            pass
        self.card_host.addWidget(w)
        self.card_widget = w
        if bug_id is not None:
            self._select_row(bug_id)

    def _maybe_autosave(self) -> bool:
        """Автосейв грязной карточки перед уходом. False — остаёмся."""
        from bug_report_dialog import BugReportWidget
        w = self.card_widget
        if not isinstance(w, BugReportWidget):
            return True
        try:
            ok = w.autosave()
        except Exception:
            return True
        if ok:
            return True
        self._select_row(self.card_id)
        return False

    def _select_row(self, bug_id) -> None:
        if bug_id is None:
            return
        try:
            self.table.blockSignals(True)
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == bug_id:
                    self.table.setCurrentCell(r, 0)
                    break
        except Exception:
            pass
        finally:
            try:
                self.table.blockSignals(False)
            except Exception:
                pass

    def _on_selection(self):
        try:
            item = self.table.currentItem()
            if item is None:
                return
            row_item = self.table.item(item.row(), 0)
            bid = row_item.data(Qt.ItemDataRole.UserRole) if row_item else None
            if bid is None:
                return
            self.open_card(int(bid))
        except Exception:
            pass

    def _on_card_saved(self, rid: int):
        try:
            self.refresh()
            for r in range(self.table.rowCount()):
                item = self.table.item(r, 0)
                if item is not None and item.data(Qt.ItemDataRole.UserRole) == rid:
                    self.table.setCurrentCell(r, 0)
                    break
            self.open_card(int(rid))
        except Exception:
            pass

    def _on_card_goto(self, cid: int):
        try:
            mw = getattr(getattr(self, "parent_window", None),
                         "main_window", None)
            if mw is None or not hasattr(mw, "show_screen"):
                return
            mw.show_screen("review")
            scr = mw.project_window.screens.get("review")
            if scr is not None:
                scr.ensure_visible_case(int(cid))
        except Exception:
            pass

    def _new_bug(self):
        self.open_card(None)
        try:
            self.card_widget.title_edit.setFocus()
        except Exception:
            pass

    def _open_bug(self):
        bid = self._selected_id()
        if bid is None:
            return
        self.open_card(int(bid))

    def _copy_menu(self):
        """V2.2 §16: копия бага из списка без открытия карточки."""
        bid = self._selected_id()
        if bid is None:
            return
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for fmt, label in (("jira", "Copy for Jira"),
                           ("markdown", "Copy Markdown"),
                           ("plain", "Copy Plain Text")):
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _c, f=fmt, name=label: self._do_copy(bid, f, name))
        anchor = self.sender()
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _do_copy(self, bug_id: int, fmt: str, label: str):
        import bug_export_service as bex
        try:
            text = bex.render(self.project_path, bug_id, fmt)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        try:
            import clipboard_service as _clip
            _clip.safe_copy(text)
            _after = _clip.get_clear_after()
            suffix = (f" Буфер будет очищен через {_clip.timeout_label(_after)}."
                      if _after else "")
        except Exception:
            from PySide6.QtGui import QGuiApplication
            QGuiApplication.clipboard().setText(text)
            suffix = ""
        notify(self, "success", "Скопировано", f"Баг #{bug_id} ({label}) — в буфере.{suffix}")

    def _selected_ids(self) -> list:
        """Все выделенные строки (мультивыбор); пусто — [] без ворчания."""
        out = []
        try:
            for idx in self.table.selectionModel().selectedRows():
                item = self.table.item(idx.row(), 0)
                if item is None:
                    continue
                bid = item.data(Qt.ItemDataRole.UserRole)
                if bid:
                    out.append(int(bid))
        except Exception:
            pass
        return list(dict.fromkeys(out))

    def _guard_card(self) -> bool:
        """Автосейв грязной карточки перед массовой операцией."""
        try:
            return bool(self._maybe_autosave())
        except Exception:
            return True

    def _bulk_apply(self, status=None, severity=None) -> None:
        ids = self._selected_ids()
        if not ids:
            notify(self, "warning", "Внимание", "Выбери баги в таблице")
            return
        if not self._guard_card():
            return
        try:
            n = bugs.bulk_update_bugs(self.project_path, ids, status,
                                      severity)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self.refresh()
        notify(self, "success", "Баги", f"Обновлено: {n}.")

    def _bulk_status_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for code in bugs.STATUSES:
            action = menu.addAction(bugs.BUG_STATUS_NAMES.get(code, code))
            action.triggered.connect(
                lambda _c, s=code: self._bulk_apply(status=s))
        anchor = self.sender()
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _bulk_sev_menu(self):
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        for code in bugs.SEVERITIES:
            action = menu.addAction(bugs.BUG_SEVERITY_NAMES.get(code, code))
            action.triggered.connect(
                lambda _c, s=code: self._bulk_apply(severity=s))
        anchor = self.sender()
        try:
            menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        except Exception:
            menu.exec()

    def _mark_dup_flow(self):
        ids = self._selected_ids()
        if len(ids) != 1:
            notify(self, "warning", "Внимание",
                   "Выбери ровно один баг — он станет дубликатом")
            return
        if not self._guard_card():
            return
        from PySide6.QtWidgets import QInputDialog
        target, ok = QInputDialog.getInt(
            self, "Дубликат", f"Баг #{ids[0]} — дубликат какого (ID)?",
            value=ids[0], min=1)
        if not ok:
            return
        if not confirm(self, "Подтверждение",
                       f"Баг #{ids[0]} → дубликат #{target}? "
                       "Кейсы не двигаются, статус станет «Дубликат»."):
            return
        try:
            bugs.mark_duplicate(self.project_path, ids[0], int(target))
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._placeholder_card()
        self.refresh()

    def _merge_flow(self):
        ids = self._selected_ids()
        if len(ids) < 2:
            notify(self, "warning", "Внимание",
                   "Выбери 2+ бага: текущий станет целью слияния")
            return
        if not self._guard_card():
            return
        try:
            cur = self.table.currentItem()
            target = self.table.item(
                cur.row(), 0).data(Qt.ItemDataRole.UserRole) \
                if cur is not None else None
            target = int(target) if target else ids[0]
        except Exception:
            target = ids[0]
        srcs = [c for c in ids if c != target]
        if not confirm(
                self, "Подтверждение",
                f"Слить {len(srcs)} в баг #{target}? Кейсы переедут к нему, "
                "источники станут дубликатами."):
            return
        try:
            res = bugs.merge_bugs(self.project_path, target, srcs)
        except ValueError as e:
            notify(self, "warning", "Ошибка", str(e))
            return
        self._placeholder_card()
        self.refresh()
        notify(self, "success", "Баги",
               f"В #{res['target']} влито {len(res['merged'])} "
               f"(кейсов: {res['moved_cases']}).")

    def _similar_flow(self):
        from bug_similar_dialog import BugSimilarDialog
        dlg = BugSimilarDialog(self.project_path, self)
        dlg.exec()
        self._placeholder_card()
        self.refresh()

    def _delete_bugs(self):
        ids = self._selected_ids()
        if not ids:
            notify(self, "warning", "Внимание", "Выбери баги в таблице")
            return
        if not self._guard_card():
            return
        # Цели с дубликатами — одним подтверждением вместе с ними.
        casc: dict = {}
        try:
            for bid in ids:
                kids = bugs.duplicate_children(self.project_path, bid)
                kids = [k for k in kids if k != bid]
                if kids:
                    casc[bid] = kids
        except Exception:
            pass
        if casc:
            parts = "; ".join(f"#{t} (+{', '.join('#' + str(k) for k in ks)})"
                              for t, ks in casc.items())
            if not confirm(self, "Подтверждение",
                           f"Удалить вместе с дубликатами: {parts}?"):
                return
        elif not confirm(self, "Подтверждение",
                         f"Удалить багов: {len(ids)}?"):
            return
        ok, errs = 0, []
        doomed = {k for ks in casc.values() for k in ks}
        for bid in ids:
            if bid in doomed:
                # уже снесён каскадом вместе с целью — не ошибка
                ok += 1
                continue
            try:
                bugs.delete_bug(self.project_path, bid,
                                cascade=bid in casc)
                ok += 1
            except ValueError as e:
                errs.append(f"#{bid}: {e}")
        self._placeholder_card()
        self.refresh()
        if errs:
            notify(self, "warning", "Удалено частично",
                   f"Удалено: {ok}.\n" + "\n".join(errs[:5]))
        else:
            notify(self, "success", "Баги", f"Удалено: {ok}.")
