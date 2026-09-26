"""Экран «Главная» (дашборд): цифры, динамика, последние действия.

Только честные данные из существующих сервисов: среднего времени проверки
у нас нет (не храним) — вместо него карточка открытых багов.
"""
from datetime import date as _date
from datetime import timedelta as _td
from io import BytesIO

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QVBoxLayout,
    QScrollArea, QWidget,
)

from ui_base import BaseScreen
from ui_compat import FComboBox, FPushButton, clear_in_fluent, effective_theme
import analytics_service as an
import history_service as hs

_EVENT_NAMES = {
    "status_changed": "Изменение статуса",
    "category_changed": "Изменение категории",
    "comment_changed": "Комментарий",
    "check_confirmed": "Проверка подтверждена",
    "check_rejected": "Проверка отклонена",
    "check_verdict_cleared": "Вердикт проверки снят",
    "case_hidden": "Кейс скрыт",
    "case_shown": "Кейс показан",
    "BUG_CREATED": "Баг создан",
    "BUG_STATUS_CHANGED": "Статус бага",
    "BUG_EXTERNAL_LINKED": "Баг: трекер",
    "BUG_UPDATED": "Баг обновлён",
    "BUG_CASE_ADDED": "Кейс привязан к багу",
    "BUG_CASE_REMOVED": "Кейс отвязан от бага",
}


class DashboardScreen(BaseScreen):
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self._cards: dict = {}
        self._init_ui()
        self.refresh()

    def _init_ui(self):
        outer = QVBoxLayout()
        outer.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(8)
        layout.setContentsMargins(20, 10, 20, 10)

        title = QLabel("🏠 ГЛАВНАЯ")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Охват (правило: данные всегда и по проекту, и по файлам).
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Охват:"))
        self.scope_combo = FComboBox()
        self.scope_combo.addItem("Весь проект", None)
        try:
            from report_service import get_files_list as _gfl
            for f in _gfl(self.project_path):
                self.scope_combo.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        self.scope_combo.currentIndexChanged.connect(self.refresh)
        scope_row.addWidget(self.scope_combo, 1)
        scope_row.addWidget(QLabel("Период:"))
        self.period_combo = FComboBox()
        self.period_combo.addItem("Всё время", "")
        self.period_combo.addItem("Сегодня", "today")
        self.period_combo.addItem("7 дней", "7d")
        self.period_combo.addItem("14 дней", "14d")
        self.period_combo.addItem("30 дней", "30d")
        self.period_combo.currentIndexChanged.connect(self.refresh)
        scope_row.addWidget(self.period_combo, 1)
        layout.addLayout(scope_row)

        from styles import SEMANTIC as _SEM
        cards_row = QHBoxLayout()
        cards_row.setSpacing(8)
        for _key, _title, _color in (
                ("reviewed", "Проверено кейсов", _SEM["success"]),
                ("complete", "Полнота", ""),
                ("bad", "Плохие ответы", _SEM["danger"]),
                ("bugs", "Открытые баги", _SEM["warning"])):
            _frame = QFrame()
            _frame.setStyleSheet(
                "QFrame { background: rgba(127, 127, 127, 0.08);"
                " border: 1px solid rgba(127, 127, 127, 0.25);"
                " border-radius: 8px; }")
            _box = QVBoxLayout()
            _box.setSpacing(0)
            _box.setContentsMargins(10, 6, 10, 6)
            _t = QLabel(_title)
            _t.setStyleSheet("font-size: 11px; border: none; background: transparent;")
            _t.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _v = QLabel("—")
            _v.setStyleSheet(
                f"font-size: 18px; font-weight: bold; border: none;"
                f" background: transparent;{(' color: ' + _color + ';') if _color else ''}")
            _v.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _s = QLabel("")
            _s.setStyleSheet("font-size: 10px; border: none; background: transparent;")
            _s.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _box.addWidget(_t)
            _box.addWidget(_v)
            _box.addWidget(_s)
            _frame.setLayout(_box)
            cards_row.addWidget(_frame)
            self._cards[_key] = (_v, _s)
        layout.addLayout(cards_row)

        dyn_title = QLabel("📈 Динамика за 30 дней")
        dyn_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        layout.addWidget(dyn_title)
        self.chart_label = QLabel("Пока нет данных")
        self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label.setMinimumHeight(220)
        layout.addWidget(self.chart_label)
        clear_in_fluent(self.chart_label)

        act_row = QHBoxLayout()
        act_title = QLabel("🕘 Последние действия")
        act_title.setStyleSheet("font-size: 13px; font-weight: bold;")
        act_row.addWidget(act_title)
        act_row.addStretch()
        btn_all = FPushButton("Вся история →")
        btn_all.setMinimumHeight(28)
        btn_all.clicked.connect(self._open_history)
        act_row.addWidget(btn_all)
        layout.addLayout(act_row)
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(220)
        self.recent_list.itemDoubleClicked.connect(self._open_case)
        layout.addWidget(self.recent_list)
        clear_in_fluent(self.recent_list)

        content.setLayout(layout)
        scroll.setWidget(content)
        clear_in_fluent(scroll)
        outer.addWidget(scroll)
        self.setLayout(outer)

    def refresh(self):
        scope = {}
        try:
            fid = self.scope_combo.currentData()
            if fid is not None:
                scope = {"file_id": int(fid)}
        except Exception:
            scope = {}
        try:
            mode = self.period_combo.currentData() or ""
            today = _date.today()
            if mode == "today":
                scope["reviewed_from"] = scope["reviewed_to"] = today.isoformat()
            elif mode and mode.endswith("d"):
                scope["reviewed_from"] = (
                    today - _td(days=int(mode[:-1]))).isoformat()
                scope["reviewed_to"] = today.isoformat()
        except Exception:
            pass
        try:
            cards = an.card_counts(self.project_path, scope)["cards"]
            pcts = an.percentages({"cards": cards})
        except Exception:
            cards, pcts = {}, {}
        try:
            dyn = an.dynamics(self.project_path, scope, limit_days=90)
        except Exception:
            dyn = []
        last7 = dyn[:7]
        rev7 = sum(d["reviewed"] for d in last7)
        bad7 = sum(d["bad"] for d in last7)

        def _fmt(n):
            return f"{n:,}".replace(",", " ")

        total = (cards.get("total") or {}).get("value", 0) or 0
        reviewed = (cards.get("reviewed") or {}).get("value", 0) or 0
        bad = (cards.get("bad") or {}).get("value", 0) or 0
        complete = round(100.0 * reviewed / total, 1) if total else None
        bad_pct = pcts.get("bad")
        try:
            week_ago = (_date.today() - _td(days=7)).isoformat()
            bscope = dict(scope, reviewed_from=week_ago)
            bugs = an.bugs_stats(self.project_path, scope or None)
            bugs7 = an.bugs_stats(self.project_path, bscope)
        except Exception:
            bugs, bugs7 = {"present": False}, {"present": False}

        def _set(key, value, sub):
            try:
                slot = self._cards.get(key)
                if slot:
                    slot[0].setText(value)
                    slot[1].setText(sub)
            except Exception:
                pass

        _set("reviewed", _fmt(reviewed), f"из {_fmt(total)} · +{rev7} за 7 дн")
        _set("complete",
             f"{complete:.1f}%" if complete is not None else "—",
             f"{_fmt(reviewed)}/{_fmt(total)}")
        _set("bad",
             f"{bad_pct:.1f}%" if bad_pct is not None else "—",
             f"{_fmt(bad)} шт · за 7 дн: {bad7}")
        if isinstance(bugs, dict) and bugs.get("present"):
            created7 = bugs7.get("created", 0) if isinstance(bugs7, dict) else 0
            _set("bugs", _fmt(bugs.get("open", 0) or 0),
                 f"создано за 7 дн: {created7}")
        else:
            _set("bugs", "0", "багов пока нет")
        self._draw_chart(dyn)
        self._load_recent()

    def _draw_chart(self, dyn):
        pts = sorted(dyn, key=lambda d: d["day"])[-30:]
        if not pts:
            self.chart_label.setText("Пока нет данных")
            self.chart_label.setPixmap(QPixmap())
            return
        try:
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            from styles import FLUENT_DARK as _FD, FLUENT_LIGHT as _FL
            from styles import SEMANTIC as _SEM
        except Exception:
            return
        try:
            pal = _FD if effective_theme() == "dark" else _FL
            days = [p["day"][5:] for p in pts]
            rev = [p["reviewed"] for p in pts]
            bad = [p["bad"] for p in pts]
            plt.style.use("dark_background" if effective_theme() == "dark"
                          else "default")
            fig, ax = plt.subplots(figsize=(10, 3.2), dpi=100)
            fig.patch.set_facecolor(pal["bg"])
            ax.set_facecolor(pal["bg"])
            ax.plot(days, rev, marker="o", markersize=3,
                    color=_SEM["success"], linewidth=2, label="Проверено")
            ax.plot(days, bad, marker="o", markersize=3,
                    color=_SEM["danger"], linewidth=2, label="Плохих")
            ax.grid(True, alpha=0.25, linestyle="--")
            ax.set_axisbelow(True)
            ax.tick_params(colors=pal["text"], labelsize=9)
            for tick in ax.get_xticklabels():
                tick.set_rotation(30)
                tick.set_ha("right")
            ax.legend(facecolor=pal["bg"], edgecolor=pal["text"],
                      labelcolor=pal["text"], fontsize=9)
            for spine in ax.spines.values():
                spine.set_color(pal["border"])
            fig.tight_layout()
            buf = BytesIO()
            fig.savefig(buf, format="png", bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            plt.close(fig)
            buf.seek(0)
            pix = QPixmap()
            pix.loadFromData(buf.read())
            self.chart_label.setPixmap(pix.scaledToWidth(
                900, Qt.TransformationMode.SmoothTransformation))
            self.chart_label.setText("")
        except Exception:
            pass

    def _load_recent(self):
        from ui_compat import format_dt as _fdt
        try:
            fid = self.scope_combo.currentData()
        except Exception:
            fid = None
        try:
            mode = self.period_combo.currentData() or ""
            today = _date.today()
            dfrom = dto = None
            if mode == "today":
                dfrom = dto = today.isoformat()
            elif mode and mode.endswith("d"):
                dfrom = (today - _td(days=int(mode[:-1]))).isoformat()
        except Exception:
            dfrom = dto = None
        try:
            if fid is not None:
                from database import db as _db
                with _db(self.project_path) as conn:
                    cids = [r["case_id"] for r in conn.execute(
                        "SELECT case_id FROM cases WHERE file_id = ?",
                        (int(fid),)).fetchall()]
                events = hs.search_history(
                    self.project_path, case_ids=cids, limit=8,
                    date_from=dfrom, date_to=dto) if cids else []
            else:
                events = hs.search_history(
                    self.project_path, limit=8, date_from=dfrom, date_to=dto)
        except Exception:
            events = []
        self.recent_list.clear()
        if not events:
            item = QListWidgetItem("Пока тихо — разметка появится здесь")
            item.setData(Qt.ItemDataRole.UserRole, None)
            self.recent_list.addItem(item)
            return
        for ev in events:
            name = _EVENT_NAMES.get(ev.get("event_type") or "",
                                   ev.get("event_type") or "—")
            case = ev.get("source_id") or ev.get("case_id") or "—"
            item = QListWidgetItem(
                f"{_fdt(ev.get('created_at'))} · {name} · кейс {case}")
            item.setData(Qt.ItemDataRole.UserRole, ev.get("case_id"))
            self.recent_list.addItem(item)

    def _open_history(self):
        try:
            mw = getattr(getattr(self, "parent_window", None),
                         "main_window", None)
            if mw is not None and hasattr(mw, "show_screen"):
                mw.show_screen("history")
        except Exception:
            pass

    def _open_case(self, item):
        try:
            cid = item.data(Qt.ItemDataRole.UserRole)
            if cid is None:
                return
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
