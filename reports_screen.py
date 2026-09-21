from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QFileDialog, QTableWidgetItem,
    QTabWidget, QScrollArea
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from report_service import (get_files_list, get_overall_report, get_files_report,
                            get_tags_report, get_checks_report,
                            get_quality_trend)
from export_service import export_results_to_xlsx, export_report_to_xlsx
from datetime import datetime
from ui_base import BaseScreen
from ui_compat import (FComboBox, FPushButton, FTable, clear_in_fluent,
                       effective_theme, notify, polish_table)
from workers import run_in_background
from io import BytesIO


def _plt():
    """Ленивый pyplot: импорт matplotlib (~0.4с) только при первом графике,
    а не при каждом открытии проекта."""
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    return plt


def _chart_palette() -> dict:
    """Цвета графиков под текущую тему (иначе тёмные графики на светлом фоне)."""
    if effective_theme() == "dark":
        return {"style": "dark_background", "bg": "#0A0F0A", "fg": "#e8e8e8",
                "spine": "#3a3a3a", "bar_total": "#1d5c33", "bar_done": "#00CC66",
                "pct_stroke": "#000000"}
    return {"style": "default", "bg": "#ffffff", "fg": "#1b1b1b",
            "spine": "#cccccc", "bar_total": "#bcd8c6", "bar_done": "#0b7a34",
            "pct_stroke": "#ffffff"}


class ReportsScreen(BaseScreen):
    """Экран отчётов."""
    reports_closed = Signal()

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self.report_file_id = None
        self.init_ui()
        self._reload_scope()
        self.load_reports()

    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 20, 40, 20)

        # Заголовок
        title = QLabel("📈 ОТЧЁТЫ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        # Охват отчётов: весь проект или один файл
        scope_row = QHBoxLayout()
        scope_row.addWidget(QLabel("Охват:"))
        self.scope_combo = FComboBox()
        self.scope_combo.currentIndexChanged.connect(self._on_scope_changed)
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)

        # Вкладки
        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("""
            QTabWidget::pane {
                border: 2px solid #00FF41;
                border-radius: 4px;
                background-color: #000000;
            }
            QTabBar::tab {
                background-color: #001A0A;
                color: #e8e8e8;
                border: 1px solid #00FF41;
                padding: 10px 20px;
                font-size: 14px;
            }
            QTabBar::tab:selected {
                background-color: #003315;
                font-weight: bold;
            }
        """)

        # Вкладка 1: Общий отчёт
        self.overall_tab = self.create_overall_tab()
        self.tabs.addTab(self.overall_tab, "📊 Общий отчёт")

        # Вкладка 2: Графики
        self.charts_tab = self.create_charts_tab()
        self.tabs.addTab(self.charts_tab, "📉 Графики")

        # Вкладка 3: По файлам
        self.files_tab = self.create_files_tab()
        self.tabs.addTab(self.files_tab, "📁 По файлам")

        # Вкладка 4: По тегам
        self.tags_tab = self.create_tags_tab()
        self.tabs.addTab(self.tags_tab, "🏷️ По тегам")

        # Вкладка 5: Автопроверки
        self.checks_tab = self.create_checks_tab()
        self.tabs.addTab(self.checks_tab, "⚠️ Автопроверки")

        # Вкладка: Модели (лидерборд прогонов)
        self.models_tab = self.create_models_tab()
        self.tabs.addTab(self.models_tab, "🏆 Модели")

        # Вкладка 6: Личное (ТЗ V2 §23, без командных дашбордов)
        self.personal_tab = self.create_personal_tab()
        self.tabs.addTab(self.personal_tab, "🙂 Личное")

        # Графики тяжёлые (~0.6с с matplotlib): рисуем только когда вкладка
        # открыта, а не при каждом заходе в отчёты.
        self.tabs.currentChanged.connect(self._on_tab_changed)

        layout.addWidget(self.tabs)
        clear_in_fluent(self.tabs)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)

        btn_export_results = FPushButton("📥 Экспорт результатов (xlsx)")
        btn_export_results.setMinimumHeight(45)
        btn_export_results.clicked.connect(self.on_export_results)

        btn_export_report = FPushButton("📊 Экспорт отчёта (xlsx)")
        btn_export_report.setMinimumHeight(45)
        btn_export_report.clicked.connect(self.on_export_report)

        btn_export_jsonl = FPushButton("📄 Экспорт JSONL")
        btn_export_jsonl.setMinimumHeight(45)
        btn_export_jsonl.setToolTip("Один кейс — одна строка JSON (UTF-8)")
        btn_export_jsonl.clicked.connect(self.on_export_jsonl)

        btn_export_ann = FPushButton("🏷 Экспорт разметки")
        btn_export_ann.setMinimumHeight(45)
        btn_export_ann.setToolTip("Только разметка (JSONL для обмена)")
        btn_export_ann.clicked.connect(self.on_export_annotations)

        btn_mgmt = FPushButton("📋 Сводный отчёт")
        btn_mgmt.setMinimumHeight(45)
        btn_mgmt.setToolTip("Сводка xlsx: цифры, вердикт к релизу")
        btn_mgmt.clicked.connect(self.on_export_management)

        btn_back = FPushButton("🚪 Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(45)
        btn_back.clicked.connect(self.on_back)

        buttons_layout.addWidget(btn_export_results)
        buttons_layout.addWidget(btn_export_report)
        buttons_layout.addWidget(btn_export_jsonl)
        buttons_layout.addWidget(btn_export_ann)
        buttons_layout.addWidget(btn_mgmt)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def create_overall_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.overall_table = FTable()
        self.overall_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #e8e8e8;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #e8e8e8;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.overall_table)
        clear_in_fluent(self.overall_table)
        polish_table(self.overall_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def create_charts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)

        btn_refresh = FPushButton("🔄 Обновить графики")
        btn_refresh.setMinimumHeight(35)
        btn_refresh.setStyleSheet("""
            QPushButton { border-color: #00AAFF; color: #00AAFF; }
            QPushButton:hover { background-color: #002233; }
        """)
        btn_refresh.clicked.connect(self.refresh_charts)
        layout.addWidget(btn_refresh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("QScrollArea { border: none; background-color: #000000; }")

        self.charts_container = QWidget()
        self.charts_layout = QVBoxLayout()
        self.charts_layout.setSpacing(20)
        self.charts_container.setLayout(self.charts_layout)
        scroll.setWidget(self.charts_container)
        layout.addWidget(scroll)

        widget.setLayout(layout)
        return widget

    def create_files_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.files_table = FTable()
        self.files_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #e8e8e8;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #e8e8e8;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.files_table)
        clear_in_fluent(self.files_table)
        polish_table(self.files_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def create_tags_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.tags_table = FTable()
        self.tags_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #e8e8e8;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #e8e8e8;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.tags_table)
        clear_in_fluent(self.tags_table)
        polish_table(self.tags_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def create_checks_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.checks_table = FTable()
        self.checks_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #e8e8e8;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #e8e8e8;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.checks_table)
        clear_in_fluent(self.checks_table)
        polish_table(self.checks_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def _reload_scope(self):
        """Список файлов в комбо охвата; выбор сохраняем, если файл жив."""
        try:
            current = self.scope_combo.currentData()
        except Exception:
            current = None
        try:
            self.scope_combo.blockSignals(True)
            self.scope_combo.clear()
            self.scope_combo.addItem("Весь проект", None)
            ids = set()
            for f in get_files_list(self.project_path):
                self.scope_combo.addItem(f["file_name"], f["file_id"])
                ids.add(f["file_id"])
            if current in ids:
                for i in range(self.scope_combo.count()):
                    if self.scope_combo.itemData(i) == current:
                        self.scope_combo.setCurrentIndex(i)
                        break
                self.report_file_id = current
            else:
                self.report_file_id = None
        except Exception:
            self.report_file_id = None
        finally:
            try:
                self.scope_combo.blockSignals(False)
            except Exception:
                pass

    def _on_scope_changed(self):
        try:
            self.report_file_id = self.scope_combo.currentData()
        except Exception:
            self.report_file_id = None
        self.load_reports()

    def _on_tab_changed(self, _index: int):
        try:
            if self.tabs.currentWidget() is self.charts_tab:
                self.refresh_charts()
        except Exception:
            pass

    def load_reports(self):
        try:
            self.load_overall_report()
            self.load_files_report()
            self.load_tags_report()
            self.load_checks_report()
            self.load_models_report()
            self.load_personal_report()
            if self.tabs.currentWidget() is self.charts_tab:
                self.refresh_charts()
        except Exception as e:
            self.show_error("Не удалось загрузить отчёты", e)

    def refresh(self):
        self._reload_scope()
        self.load_reports()

    def load_overall_report(self):
        from report_service import (consistency_check, get_alerts,
                                    get_error_top, get_golden_info)
        fid = self.report_file_id
        report = get_overall_report(self.project_path, fid)
        data = []
        if fid is None:
            try:
                for a in get_alerts(self.project_path):
                    mark = {"critical": "🛑", "warning": "⚠️"}.get(a["level"], "ℹ️")
                    data.append((f"{mark} {a['text']}", ""))
            except Exception:
                pass
        data += [
            ("Всего кейсов", report.get('total', 0)),
            ("Проверено", report.get('reviewed', 0)),
            ("Не проверено", report.get('unreviewed', 0)),
            ("Хорошо", report.get('good', 0)),
            ("Плохо", report.get('bad', 0)),
            ("Сомневаюсь", report.get('uncertain', 0)),
            ("Дубль", report.get('duplicate', 0)),
            ("Пропущено", report.get('skip', 0)),
        ]
        try:
            chk = consistency_check(self.project_path, fid)
            bad = [c["name"] for c in chk["checks"] if not c["ok"]]
            data.append(("Сверка сумм", "✅" if chk["ok"]
                         else f"❌ {', '.join(bad)}"))
        except Exception:
            pass
        try:
            gi = get_golden_info(self.project_path)
            if gi["count"]:
                data.append(("Эталоны", f"{gi['count']}, свеж. "
                                        f"{gi['oldest_days']} дн."))
            else:
                data.append(("Эталоны", "нет замороженных"))
        except Exception:
            pass
        try:
            top = get_error_top(self.project_path, fid, limit=3)
            s = sum(e["n"] for e in top)
            tot_bad = report.get('bad', 0) or 1
            data.append(("Концентрация топ-3", f"{s / tot_bad:.0%}"))
        except Exception:
            pass
        self.overall_table.clear()
        self.overall_table.setColumnCount(2)
        self.overall_table.setRowCount(len(data))
        self.overall_table.setHorizontalHeaderLabels(["Показатель", "Значение"])
        self.overall_table.setSortingEnabled(False)
        for row, (name, value) in enumerate(data):
            self.overall_table.setItem(row, 0, QTableWidgetItem(name))
            self.overall_table.setItem(row, 1, QTableWidgetItem(str(value)))
        self.overall_table.resizeColumnsToContents()

    def load_files_report(self):
        files = get_files_report(self.project_path)
        if self.report_file_id is not None:
            files = [f for f in files if f["file_id"] == self.report_file_id]
        self.files_table.clear()
        self.files_table.setColumnCount(4)
        self.files_table.setRowCount(len(files))
        self.files_table.setHorizontalHeaderLabels([
            "Файл", "Всего кейсов", "Проверено", "Дата импорта"
        ])
        self.files_table.setSortingEnabled(True)
        for row, file in enumerate(files):
            self.files_table.setItem(row, 0, QTableWidgetItem(file['file_name']))
            self.files_table.setItem(row, 1, QTableWidgetItem(str(file['cases_count'])))
            self.files_table.setItem(row, 2, QTableWidgetItem(str(file['reviewed_count'])))
            self.files_table.setItem(row, 3, QTableWidgetItem((file['imported_at'] or '')[:19]))
        self.files_table.resizeColumnsToContents()

    def load_tags_report(self):
        tags = get_tags_report(self.project_path, self.report_file_id)
        self.tags_table.clear()
        self.tags_table.setColumnCount(3)
        self.tags_table.setRowCount(len(tags))
        self.tags_table.setHorizontalHeaderLabels([
            "Тег", "Количество кейсов", "Системный"
        ])
        for row, tag in enumerate(tags):
            self.tags_table.setItem(row, 0, QTableWidgetItem(tag['tag_name']))
            self.tags_table.setItem(row, 1, QTableWidgetItem(str(tag['cases_count'])))
            self.tags_table.setItem(row, 2, QTableWidgetItem("Да" if tag['is_system'] else "Нет"))
        self.tags_table.resizeColumnsToContents()

    def load_checks_report(self):
        checks = get_checks_report(self.project_path, self.report_file_id)
        self.checks_table.clear()
        self.checks_table.setColumnCount(4)
        self.checks_table.setRowCount(len(checks))
        self.checks_table.setHorizontalHeaderLabels([
            "Автопроверка", "Срабатываний", "Подтв. / Ложные", "Precision"
        ])
        for row, check in enumerate(checks):
            self.checks_table.setItem(row, 0, QTableWidgetItem(check['check_name']))
            self.checks_table.setItem(row, 1, QTableWidgetItem(str(check['count'])))
            self.checks_table.setItem(
                row, 2, QTableWidgetItem(
                    f"{check.get('confirmed') or 0} / {check.get('false_positive') or 0}"))
            prec = check.get('precision')
            cell = (f"{prec:.0%}" if prec is not None else "— нет вердиктов")
            if prec is not None and prec < 0.3 and (check.get('confirmed') or 0) + (
                    check.get('false_positive') or 0) >= 3:
                cell += " ⚠ правило бесполезно?"
            self.checks_table.setItem(row, 3, QTableWidgetItem(cell))
        self.checks_table.resizeColumnsToContents()

    def create_models_tab(self):
        """Лидерборд прогонов: разметка, победы, gate."""
        widget = QWidget()
        layout = QVBoxLayout()
        hint = QLabel("Прогоны: качество ответов, победы в парах, gate-кандидаты")
        layout.addWidget(hint)
        self.models_table = FTable()
        layout.addWidget(self.models_table)
        # Иначе остаётся библиотечный CSS (прозрачный фон и т.п.) и таблица
        # выбивается из общего стиля.
        clear_in_fluent(self.models_table)
        polish_table(self.models_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def load_models_report(self):
        from report_service import get_model_leaderboard
        board = get_model_leaderboard(self.project_path)
        self.models_table.clear()
        self.models_table.setColumnCount(8)
        self.models_table.setRowCount(len(board))
        self.models_table.setHorizontalHeaderLabels([
            "Прогон", "Модель", "Ответов", "Размечено",
            "Хорошо", "Плохо", "Побед", "Gate",
        ])
        for row, b in enumerate(board):
            self.models_table.setItem(row, 0, QTableWidgetItem(str(b["name"])))
            self.models_table.setItem(row, 1, QTableWidgetItem(str(b["model_name"])))
            self.models_table.setItem(row, 2, QTableWidgetItem(str(b["answers"])))
            self.models_table.setItem(row, 3, QTableWidgetItem(str(b["reviewed"])))
            self.models_table.setItem(row, 4, QTableWidgetItem(str(b["good"])))
            self.models_table.setItem(row, 5, QTableWidgetItem(str(b["bad"])))
            self.models_table.setItem(
                row, 6, QTableWidgetItem(f"{b['wins']}/{b['pairs']}"))
            self.models_table.setItem(
                row, 7, QTableWidgetItem(f"{b['gates_passed']}/{b['gates']}"))
        self.models_table.resizeColumnsToContents()

    def create_personal_tab(self):
        """Вкладка личной аналитики (§23)."""
        widget = QWidget()
        layout = QVBoxLayout()
        hint = QLabel("Моя статистика (только личная, без командных метрик)")
        layout.addWidget(hint)
        self.personal_table = FTable()
        layout.addWidget(self.personal_table)
        clear_in_fluent(self.personal_table)
        polish_table(self.personal_table, stretch_last=True)
        widget.setLayout(layout)
        return widget

    def load_personal_report(self):
        from report_service import get_personal_stats
        stats = get_personal_stats(self.project_path)
        rows = []
        rev = stats.get("review", {})
        rows.append(("Размечено кейсов", f"{rev.get('reviewed', 0)}/{rev.get('total', 0)}"))
        # V2.1 §17: покрытие одной цифрой — понятнее графика.
        try:
            cov = (100.0 * rev.get("reviewed", 0) / rev["total"]
                   if rev.get("total") else 0.0)
        except Exception:
            cov = 0.0
        rows.append(("Покрытие", f"{cov:.0f}%"))
        for key, label in (("good", "Хорошо"), ("bad", "Плохо"),
                           ("uncertain", "Сомневаюсь"), ("duplicate", "Дубль"),
                           ("skip", "Пропущено")):
            rows.append((label, rev.get(key, 0)))
        rows.append(("False positives автопроверок",
                     stats.get("false_positives", 0)))
        rows.append(("--- Ошибки по категориям ---", ""))
        for e in stats.get("errors", [])[:10]:
            rows.append((e["category"], e["n"]))
        rows.append(("--- Баги по статусам ---", ""))
        for b in stats.get("bugs", []):
            rows.append((b["status"], b["n"]))
        regs = stats.get("regressions", {}) or {}
        if regs.get("total"):
            rows.append(("--- Регрессии ---", ""))
            rows.append(("Запусков", regs.get("total", 0)))
            rows.append(("PASS", regs.get("passed", 0)))
            rows.append(("Регрессий всего", regs.get("regressions", 0)))
            rows.append(("Улучшений всего", regs.get("improvements", 0)))
        from report_service import get_velocity
        try:
            velo = get_velocity(self.project_path, file_id=self.report_file_id)
        except Exception:
            velo = {}
        if velo:
            rows.append(("--- Скорость ---", ""))
            rows.append(("Кейсов/день", velo.get("avg_per_day", 0)))
            rows.append(("Активных дней", velo.get("active_days", 0)))
            rows.append(("Осталось", velo.get("remaining", 0)))
            eta = velo.get("eta_days")
            rows.append(("Прогноз, дней", eta if eta is not None else "—"))
            rows.append(("Готово к дате", velo.get("eta_date") or "—"))
        rows.append(("--- Тренд (7 дней) ---", ""))
        for d in stats.get("by_day", [])[:7]:
            rows.append((d["day"], d["n"]))
        self.personal_table.clear()
        self.personal_table.setColumnCount(2)
        self.personal_table.setRowCount(len(rows))
        self.personal_table.setHorizontalHeaderLabels(["Показатель", "Значение"])
        for i, (k, v) in enumerate(rows):
            self.personal_table.setItem(i, 0, QTableWidgetItem(str(k)))
            self.personal_table.setItem(i, 1, QTableWidgetItem(str(v)))
        self.personal_table.resizeColumnsToContents()

    def _create_quality_trend_chart(self, pts):
        """Линия bad-rate по версиям датасетов."""
        plt = _plt()
        pal = _chart_palette()
        labels = [f"{p['dataset']} v{p['version']}" for p in pts]
        rates = [p["bad_rate"] * 100 for p in pts]
        plt.style.use(pal["style"])
        fig, ax = plt.subplots(figsize=(10, 4), dpi=100)
        fig.patch.set_facecolor(pal["bg"])
        ax.set_facecolor(pal["bg"])
        ax.plot(labels, rates, marker="o", color="#CC3333", linewidth=2)
        ax.set_ylabel("Bad-rate, %", color=pal["fg"])
        ax.set_title("Качество по версиям", color=pal["fg"], fontsize=14, pad=15)
        ax.tick_params(colors=pal["fg"])
        for tick in ax.get_xticklabels():
            tick.set_rotation(20)
            tick.set_ha("right")
            tick.set_color(pal["fg"])
        fig.tight_layout()
        buf = BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight",
                    facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)
        pixmap = QPixmap()
        pixmap.loadFromData(buf.read())
        lbl = QLabel()
        lbl.setPixmap(pixmap.scaled(
            700, 450,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.charts_layout.addWidget(lbl)

    def refresh_charts(self):
        """Обновляет графики."""
        while self.charts_layout.count():
            item = self.charts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        report = get_overall_report(self.project_path, self.report_file_id)
        files = get_files_report(self.project_path)
        tags = get_tags_report(self.project_path, self.report_file_id)
        trend = get_quality_trend(self.project_path)

        # График 1: Круговая диаграмма статусов
        self._create_pie_chart(report)

        # График 2: Столбчатая диаграмма по файлам
        if files:
            self._create_files_bar_chart(files)

        # График 3: Горизонтальная диаграмма тегов
        if tags:
            self._create_tags_bar_chart(tags[:10])

        # График 4: bad-rate по версиям
        pts = [p for p in trend if p["total"] > 0 and p["bad_rate"] is not None]
        if pts:
            self._create_quality_trend_chart(pts)

    def _create_pie_chart(self, report):
        """Круговая диаграмма распределения статусов с легендой."""
        plt = _plt()
        pal = _chart_palette()
        labels = []
        sizes = []
        colors = []

        status_data = [
            ('Не проверено', report['unreviewed'], '#555555'),
            ('Хорошо', report['good'], '#00CC44'),
            ('Плохо', report['bad'], '#CC3333'),
            ('Сомневаюсь', report['uncertain'], '#CCAA00'),
            ('Дубль', report['duplicate'], '#CC7700'),
            ('Пропущено', report['skip'], '#888888'),
        ]

        for label, size, color in status_data:
            if size > 0:
                labels.append(f"{label} ({size})")
                sizes.append(size)
                colors.append(color)

        if not sizes:
            lbl = QLabel("Нет данных для отображения")
            lbl.setStyleSheet("color: #00AA2A; font-size: 14px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.charts_layout.addWidget(lbl)
            return

        plt.style.use(pal["style"])
        fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
        fig.patch.set_facecolor(pal["bg"])
        ax.set_facecolor(pal["bg"])

        # Круговая диаграмма БЕЗ подписей на секторах.
        # Проценты — цветом темы с обводкой: читаются на любом секторе в обеих темах.
        import matplotlib.patheffects as _pe
        wedges, texts, autotexts = ax.pie(
            sizes,
            colors=colors,
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.75,
            textprops={'color': pal["fg"], 'fontsize': 11, 'fontweight': 'bold'},
        )
        for t in autotexts:
            t.set_path_effects([_pe.withStroke(linewidth=3, foreground=pal["pct_stroke"])])

        # Убираем подписи на секторах, оставляем только проценты
        for text in texts:
            text.set_text('')

        # Легенда справа
        ax.legend(
            wedges, labels,
            title="Статусы",
            loc="center left",
            bbox_to_anchor=(1.05, 0.5),
            fontsize=11,
            title_fontsize=12,
            facecolor=pal["bg"],
            edgecolor=pal["fg"],
            labelcolor=pal["fg"]
        )

        ax.set_title('Распределение статусов', color=pal["fg"], fontsize=14, pad=15)

        fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        pixmap = QPixmap()
        pixmap.loadFromData(buf.read())

        lbl = QLabel()
        lbl.setPixmap(pixmap.scaled(
            700, 450,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.charts_layout.addWidget(lbl)

    def _create_files_bar_chart(self, files):
        """Столбчатая диаграмма по файлам."""
        plt = _plt()
        pal = _chart_palette()
        names = [f['file_name'][:20] for f in files]
        totals = [f['cases_count'] for f in files]
        reviewed = [f['reviewed_count'] for f in files]

        plt.style.use(pal["style"])
        fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
        fig.patch.set_facecolor(pal["bg"])
        ax.set_facecolor(pal["bg"])

        x = range(len(names))
        width = 0.35

        ax.bar([i - width/2 for i in x], totals, width,
               label='Всего', color=pal["bar_total"], edgecolor=pal["spine"])
        ax.bar([i + width/2 for i in x], reviewed, width,
               label='Проверено', color=pal["bar_done"], edgecolor=pal["spine"])

        ax.set_ylabel('Кейсы', color=pal["fg"], fontsize=12)
        ax.set_title('Прогресс по файлам', color=pal["fg"], fontsize=14, pad=15)
        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=45, ha='right', color=pal["fg"], fontsize=10)
        ax.tick_params(colors=pal["fg"], labelsize=10)
        ax.legend(facecolor=pal["bg"], edgecolor=pal["fg"], labelcolor=pal["fg"], fontsize=11)

        for spine in ax.spines.values():
            spine.set_color(pal["spine"])

        fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        pixmap = QPixmap()
        pixmap.loadFromData(buf.read())

        lbl = QLabel()
        lbl.setPixmap(pixmap.scaled(
            700, 450,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.charts_layout.addWidget(lbl)

    def _create_tags_bar_chart(self, tags):
        """Горизонтальная диаграмма тегов."""
        plt = _plt()
        pal = _chart_palette()
        names = [t['tag_name'] for t in tags]
        counts = [t['cases_count'] for t in tags]

        plt.style.use(pal["style"])
        fig, ax = plt.subplots(figsize=(10, max(4, len(tags) * 0.5)), dpi=100)
        fig.patch.set_facecolor(pal["bg"])
        ax.set_facecolor(pal["bg"])

        y_pos = range(len(names))
        ax.barh(y_pos, counts, color=pal["bar_done"], edgecolor=pal["spine"], height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, color=pal["fg"], fontsize=11)
        ax.set_xlabel('Количество кейсов', color=pal["fg"], fontsize=12)
        ax.set_title('Топ тегов', color=pal["fg"], fontsize=14, pad=15)
        ax.tick_params(colors=pal["fg"], labelsize=10)
        ax.invert_yaxis()

        for spine in ax.spines.values():
            spine.set_color(pal["spine"])

        fig.tight_layout()

        buf = BytesIO()
        fig.savefig(buf, format='png', bbox_inches='tight', facecolor=fig.get_facecolor())
        plt.close(fig)
        buf.seek(0)

        pixmap = QPixmap()
        pixmap.loadFromData(buf.read())

        lbl = QLabel()
        lbl.setPixmap(pixmap.scaled(
            700, 450,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation
        ))
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.charts_layout.addWidget(lbl)

    def on_export_results(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"review_results_{timestamp}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить результаты разметки",
            default_name,
            "Excel файлы (*.xlsx)"
        )
        if file_path:
            self.setEnabled(False)
            run_in_background(
                export_results_to_xlsx, self.project_path, file_path,
                on_finished=lambda count: (
                    self.setEnabled(True),
                    notify(self, "success", "Экспорт завершён",
                           f"Экспортировано {count} кейсов в:\n{file_path}")),
                on_error=lambda msg: (
                    self.setEnabled(True),
                    notify(self, "error", "Ошибка", f"Не удалось экспортировать:\n{msg}")),
            )

    def on_export_jsonl(self):
        from export_service import JSONL_OPTIONAL, export_results_jsonl
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
        from report_service import get_files_list
        from ui_compat import FCheckBox, FComboBox
        dlg = QDialog(self)
        dlg.setWindowTitle("Экспорт JSONL")
        dlg.setMinimumWidth(420)
        layout = QVBoxLayout()
        layout.addWidget(QLabel("Охват:"))
        file_combo = FComboBox()
        file_combo.addItem("Весь проект", None)
        try:
            for f in get_files_list(self.project_path):
                file_combo.addItem(f["file_name"], f["file_id"])
        except Exception:
            pass
        layout.addWidget(file_combo)
        layout.addWidget(QLabel("Доп. поля (база: id, query, response, status,"
                                " category, subcategory, severity, comment):"))
        boxes = {}
        for field in JSONL_OPTIONAL:
            cb = FCheckBox(field)
            boxes[field] = cb
            layout.addWidget(cb)
        btns = QHBoxLayout()
        from ui_compat import FPrimaryButton
        ok = FPrimaryButton("Экспортировать")
        cancel = FPushButton("Отмена")
        btns.addWidget(ok)
        btns.addWidget(cancel)
        layout.addLayout(btns)
        dlg.setLayout(layout)
        chosen = {}

        def _go():
            chosen["file_id"] = file_combo.currentData()
            chosen["extra"] = [f for f, cb in boxes.items() if cb.isChecked()]
            dlg.accept()

        ok.clicked.connect(_go)
        cancel.clicked.connect(dlg.reject)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить JSONL", f"results_{timestamp}.jsonl",
            "JSONL (*.jsonl)")
        if not file_path:
            return
        self.setEnabled(False)
        run_in_background(
            export_results_jsonl, self.project_path, file_path,
            chosen["file_id"], chosen["extra"],
            on_finished=lambda count: (
                self.setEnabled(True),
                notify(self, "success", "Экспорт завершён",
                       f"Экспортировано {count} кейсов в:\n{file_path}")),
            on_error=lambda msg: (
                self.setEnabled(True),
                notify(self, "error", "Ошибка", f"Не удалось экспортировать:\n{msg}")),
        )

    def on_export_management(self):
        from export_service import export_management_report
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"summary_{timestamp}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить отчёт для руководства",
            default_name, "Excel файлы (*.xlsx)")
        if not file_path:
            return
        self.setEnabled(False)
        run_in_background(
            export_management_report, self.project_path, file_path,
            self.report_file_id,
            on_finished=lambda _ok: (
                self.setEnabled(True),
                notify(self, "success", "Экспорт завершён",
                       f"Отчёт сохранён:\n{file_path}")),
            on_error=lambda msg: (
                self.setEnabled(True),
                notify(self, "error", "Ошибка", f"Не удалось экспортировать:\n{msg}")),
        )

    def on_export_report(self):
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_name = f"report_{timestamp}.xlsx"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "Сохранить отчёт",
            default_name,
            "Excel файлы (*.xlsx)"
        )
        if file_path:
            self.setEnabled(False)
            run_in_background(
                export_report_to_xlsx, self.project_path, file_path,
                on_finished=lambda _r: (
                    self.setEnabled(True),
                    notify(self, "success", "Экспорт завершён",
                           f"Отчёт сохранён в:\n{file_path}")),
                on_error=lambda msg: (
                    self.setEnabled(True),
                    notify(self, "error", "Ошибка", f"Не удалось экспортировать:\n{msg}")),
            )

    def on_back(self):
        mw = getattr(getattr(self, "parent_window", None), "main_window", None)
        if mw is not None and hasattr(mw, "show_screen"):
            mw.show_screen("project")
        else:
            self.reports_closed.emit()

    def on_export_annotations(self):
        from annotation_io_dialog import ExportAnnotationsDialog
        ExportAnnotationsDialog(self.project_path, self).exec()
