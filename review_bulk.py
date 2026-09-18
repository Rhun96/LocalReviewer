"""Review screen, Bulk operations: run, recheck, undo. (mixin split of review_screen.py)."""


from PySide6.QtWidgets import (
    QDialog,
)
from PySide6.QtCore import Qt
from ui_compat import (
    confirm, notify,
)
import logging


logger = logging.getLogger(__name__)


class BulkMixin:
    """Bulk operations: run, recheck, undo."""

    def on_bulk_run(self):
        ids = self._bulk_target_ids()
        if not ids:
            notify(self, "warning", "Внимание", "Нет кейсов для массовой операции")
            return
        # Защита от неявного «вся выборка»: пустой ручной выбор подсвечиваем отдельно.
        if not self.bulk_selected:
            if not confirm(
                self, "Подтверждение",
                f"Ручной выбор пуст — операция применится ко ВСЕЙ текущей выборке "
                f"({len(ids)} кейсов).\nПродолжить?",
            ):
                return
        from bulk_dialog import BulkDialog
        dlg = BulkDialog(len(ids), self, project_path=self.project_path)
        if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.result_op:
            return
        op, val = dlg.result_op
        if op == "add_tag":
            op_label = f"добавить тег (id={val})"
        elif op == "remove_tag":
            op_label = f"убрать тег (id={val})"
        elif op == "replace_tags":
            op_label = f"заменить набор тегов ({len(val)} шт.)"
        elif op == "mark_viewed":
            op_label = "отметить просмотренными"
        elif op == "unmark_viewed":
            op_label = "снять «просмотрено»"
        elif op in ("recheck", "reset_checks"):
            op_label = {"recheck": "пересчитать проверки",
                        "reset_checks": "сбросить проверки"}[op]
        else:
            op_label = f"{op} → {val}"
        if not confirm(
            self, "Подтверждение",
            f"Вы собираетесь изменить {len(ids)} кейсов.\nОперация: {op_label}.\nПродолжить?",
        ):
            return
        sender_btn = self.sender()
        if sender_btn is not None:
            sender_btn.setEnabled(False)
            sender_btn.setText("⏳ Выполняется…")
        import threading
        from PySide6.QtWidgets import QProgressDialog
        from PySide6.QtCore import QTimer
        cancel_event = threading.Event()
        progress = QProgressDialog("Массовая операция…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)

        def _work_outer():
            from workers import run_in_background as _run

            def _make_work():
                from bulk_operation_service import (
                    bulk_add_tag, bulk_remove_tag, bulk_set_comment,
                    bulk_set_status, bulk_set_tags, bulk_set_viewed)
                from autocheck_service import run_autochecks, reset_checks

                def _call(fn, *a):
                    return fn(*a, progress_callback=_progress,
                              cancel_event=cancel_event)

                if op == "status":
                    return _call(bulk_set_status, self.project_path, ids, val)
                if op == "comment_replace":
                    return _call(bulk_set_comment, self.project_path, ids, val,
                                 mode="replace")
                if op == "comment_append":
                    return _call(bulk_set_comment, self.project_path, ids, val,
                                 mode="append")
                if op == "comment_clear":
                    return _call(bulk_set_comment, self.project_path, ids, "",
                                 mode="clear")
                if op == "add_tag":
                    return _call(bulk_add_tag, self.project_path, ids, int(val))
                if op == "remove_tag":
                    return _call(bulk_remove_tag, self.project_path, ids, int(val))
                if op == "replace_tags":
                    return _call(bulk_set_tags, self.project_path, ids,
                                 [int(t) for t in val])
                if op == "mark_viewed":
                    return _call(bulk_set_viewed, self.project_path, ids, True)
                if op == "unmark_viewed":
                    return _call(bulk_set_viewed, self.project_path, ids, False)
                if op == "recheck":
                    return run_autochecks(self.project_path, case_ids=ids,
                                          progress_callback=_progress,
                                          cancel_event=cancel_event)["flags_found"]
                if op == "reset_checks":
                    # Мгновенный DELETE без прогресса — отмена не нужна.
                    return reset_checks(self.project_path, case_ids=ids)
                raise ValueError(op)

            holder: dict = {}

            def _progress(done, total):
                pct = int(done / total * 100) if total else 0
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(pct)

            worker = _run(_make_work)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(done):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            self.bulk_selected.clear()
            self.load_case_ids()
            self.load_table_data()
            self.update_filter_indicator()
            self.update_queue_indicator()
            self._review_finished = False
            if self.case_ids:
                self.load_case(min(self.current_index, len(self.case_ids) - 1))
            # Bulk мог сменить статус текущего кейса — pending пересчитываем.
            if (self.current_case or {}).get('status') != 'bad':
                self._bad_reset()
            if op == "recheck":
                text = f"Проверки пересчитаны для {len(ids)} кейсов, срабатываний: {done}"
            elif op == "reset_checks":
                text = f"Сброшено срабатываний: {done} (кейсов: {len(ids)})"
            else:
                text = f"{done} кейсов обработано"
            notify(self, "success", "Готово", text)

        def _fail(msg):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
                sender_btn.setText("⚡ Массовое действие…")
            if "Прервано пользователем" in (msg or ""):
                notify(self, "warning", "Операция прервана",
                       f"{msg}\nИзменения откачены — можно запустить снова.")
            else:
                notify(self, "error", "Ошибка", f"Массовая операция не удалась:\n{msg}")

        # Запуск через очередь событий, чтобы прогресс успел отрисоваться.
        QTimer.singleShot(0, _work_outer)

    def on_recheck_all(self):
        """Пересчёт автопроверок в БД (фон) — питает фильтры по проверкам и очередь."""
        import threading
        from PySide6.QtWidgets import QProgressDialog
        cancel_event = threading.Event()
        progress = QProgressDialog("Пересчёт автопроверок…", "Отмена", 0, 100, self)
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setAutoClose(True)
        progress.canceled.connect(cancel_event.set)
        progress.setValue(0)

        sender_btn = self.sender()
        if sender_btn is not None:
            sender_btn.setEnabled(False)

        def _work():
            from autocheck_service import run_autochecks
            from workers import run_in_background as _run
            fid = (self.filters or {}).get("file_id")
            holder = {}

            def _progress(done, total):
                pct = int(done / total * 100) if total else 0
                w = holder.get("w")
                if w is not None:
                    w.signals.progress.emit(pct)

            worker = _run(run_autochecks, self.project_path,
                          file_id=fid, progress_callback=_progress, cancel_event=cancel_event)
            holder["w"] = worker
            worker.signals.progress.connect(progress.setValue)
            worker.signals.finished.connect(_done)
            worker.signals.error.connect(_fail)

        def _done(res):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
            try:
                self.load_case_ids()
                self.load_table_data()
                self.update_queue_indicator()
            except Exception:
                pass
            fid = (self.filters or {}).get("file_id")
            scope = "по файлу" if fid else "по проекту"
            cancelled = isinstance(res, dict) and res.get("cancelled")
            notify(
                self, "success", "Автопроверки",
                f"Пересчёт {scope}: проверено кейсов: {res.get('total_checked', 0)}\n"
                f"Срабатываний: {res.get('flags_found', 0)}"
                + ("\n⚠️ Прервано пользователем — запустите снова для полного пересчёта."
                   if cancelled else ""))

        def _fail(msg):
            progress.close()
            if sender_btn is not None:
                sender_btn.setEnabled(True)
            if "Прервано пользователем" in msg:
                try:
                    self.load_case_ids()
                    self.load_table_data()
                    self.update_queue_indicator()
                except Exception:
                    pass
                notify(
                    self, "warning", "Автопроверки",
                    f"{msg}\nЧастичные результаты сохранены — "
                    "запустите снова для полного пересчёта.")
            else:
                notify(self, "error", "Ошибка",
                       f"Не удалось пересчитать проверки:\n{msg}")

        # _work создаёт воркер и цепляет сигналы: запуск через очередь событий,
        # чтобы progress успел отрисоваться до старта тяжёлой задачи
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, _work)

    def on_bulk_undo(self):
        from database import db as _db
        try:
            with _db(self.project_path) as conn:
                row = conn.execute(
                    "SELECT operation_id FROM bulk_operations "
                    "WHERE undone=0 ORDER BY operation_id DESC LIMIT 1"
                ).fetchone()
            if not row:
                notify(self, "warning", "Отмена", "Нет операций для отмены")
                return
            op_id = row["operation_id"]
        except Exception as e:
            self.show_error("Не удалось найти операцию", e)
            return
        if not confirm(self, "Подтверждение", f"Отменить массовую операцию #{op_id}?"):
            return
        try:
            from bulk_operation_service import undo_bulk_operation
            done = undo_bulk_operation(self.project_path, op_id)
            self.load_case_ids()
            self.load_table_data()
            self.update_filter_indicator()
            self.update_queue_indicator()
            self._review_finished = False
            notify(self, "success", "Готово", f"Отменено изменений: {done}")
        except Exception as e:
            self.show_error("Не удалось отменить", e)
