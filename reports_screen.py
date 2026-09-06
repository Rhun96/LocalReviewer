from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QFileDialog, QMessageBox, QTableWidget, QTableWidgetItem,
    QTabWidget, QGroupBox, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from database import get_db_connection
from report_service import get_overall_report, get_files_report, get_tags_report, get_checks_report
from export_service import export_results_to_xlsx, export_report_to_xlsx
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from io import BytesIO


class ReportsScreen(QWidget):
    """Экран отчётов."""
    reports_closed = Signal()

    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        self.init_ui()
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
                color: #00FF41;
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

        layout.addWidget(self.tabs)

        # Кнопки
        buttons_layout = QHBoxLayout()
        buttons_layout.setSpacing(15)

        btn_export_results = QPushButton("📥 Экспорт результатов (xlsx)")
        btn_export_results.setMinimumHeight(45)
        btn_export_results.clicked.connect(self.on_export_results)

        btn_export_report = QPushButton("📊 Экспорт отчёта (xlsx)")
        btn_export_report.setMinimumHeight(45)
        btn_export_report.clicked.connect(self.on_export_report)

        btn_back = QPushButton("🚪 Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(45)
        btn_back.clicked.connect(self.on_back)

        buttons_layout.addWidget(btn_export_results)
        buttons_layout.addWidget(btn_export_report)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)

        self.setLayout(layout)

    def create_overall_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.overall_table = QTableWidget()
        self.overall_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #00FF41;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.overall_table)
        widget.setLayout(layout)
        return widget

    def create_charts_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)

        btn_refresh = QPushButton("🔄 Обновить графики")
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
        self.files_table = QTableWidget()
        self.files_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #00FF41;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.files_table)
        widget.setLayout(layout)
        return widget

    def create_tags_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.tags_table = QTableWidget()
        self.tags_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #00FF41;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.tags_table)
        widget.setLayout(layout)
        return widget

    def create_checks_tab(self):
        widget = QWidget()
        layout = QVBoxLayout()
        self.checks_table = QTableWidget()
        self.checks_table.setStyleSheet("""
            QTableWidget {
                background-color: #001A0A;
                border: 1px solid #00FF41;
                color: #00FF41;
                font-size: 14px;
                gridline-color: #003315;
            }
            QTableWidget::item { padding: 8px; }
            QHeaderView::section {
                background-color: #003315;
                color: #00FF41;
                border: 1px solid #00FF41;
                padding: 8px;
                font-weight: bold;
            }
        """)
        layout.addWidget(self.checks_table)
        widget.setLayout(layout)
        return widget

    def load_reports(self):
        self.load_overall_report()
        self.load_files_report()
        self.load_tags_report()
        self.load_checks_report()
        self.refresh_charts()

    def load_overall_report(self):
        report = get_overall_report(self.project_path)
        self.overall_table.clear()
        self.overall_table.setColumnCount(2)
        self.overall_table.setRowCount(8)
        self.overall_table.setHorizontalHeaderLabels(["Показатель", "Значение"])
        data = [
            ("Всего кейсов", report['total']),
            ("Проверено", report['reviewed']),
            ("Не проверено", report['unreviewed']),
            ("Хорошо", report['good']),
            ("Плохо", report['bad']),
            ("Сомневаюсь", report['uncertain']),
            ("Дубль", report['duplicate']),
            ("Пропущено", report['skip']),
        ]
        for row, (name, value) in enumerate(data):
            self.overall_table.setItem(row, 0, QTableWidgetItem(name))
            self.overall_table.setItem(row, 1, QTableWidgetItem(str(value)))
        self.overall_table.resizeColumnsToContents()

    def load_files_report(self):
        files = get_files_report(self.project_path)
        self.files_table.clear()
        self.files_table.setColumnCount(4)
        self.files_table.setRowCount(len(files))
        self.files_table.setHorizontalHeaderLabels([
            "Файл", "Всего кейсов", "Проверено", "Дата импорта"
        ])
        for row, file in enumerate(files):
            self.files_table.setItem(row, 0, QTableWidgetItem(file['file_name']))
            self.files_table.setItem(row, 1, QTableWidgetItem(str(file['cases_count'])))
            self.files_table.setItem(row, 2, QTableWidgetItem(str(file['reviewed_count'])))
            self.files_table.setItem(row, 3, QTableWidgetItem(file['imported_at'][:19]))
        self.files_table.resizeColumnsToContents()

    def load_tags_report(self):
        tags = get_tags_report(self.project_path)
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
        checks = get_checks_report(self.project_path)
        self.checks_table.clear()
        self.checks_table.setColumnCount(2)
        self.checks_table.setRowCount(len(checks))
        self.checks_table.setHorizontalHeaderLabels([
            "Автопроверка", "Количество срабатываний"
        ])
        for row, check in enumerate(checks):
            self.checks_table.setItem(row, 0, QTableWidgetItem(check['check_name']))
            self.checks_table.setItem(row, 1, QTableWidgetItem(str(check['count'])))
        self.checks_table.resizeColumnsToContents()

    def refresh_charts(self):
        """Обновляет графики."""
        while self.charts_layout.count():
            item = self.charts_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        report = get_overall_report(self.project_path)
        files = get_files_report(self.project_path)
        tags = get_tags_report(self.project_path)

        # График 1: Круговая диаграмма статусов
        self._create_pie_chart(report)

        # График 2: Столбчатая диаграмма по файлам
        if files:
            self._create_files_bar_chart(files)

        # График 3: Горизонтальная диаграмма тегов
        if tags:
            self._create_tags_bar_chart(tags[:10])

    def _create_pie_chart(self, report):
        """Круговая диаграмма распределения статусов с легендой."""
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

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
        fig.patch.set_facecolor('#0A0F0A')
        ax.set_facecolor('#0A0F0A')

        # Круговая диаграмма БЕЗ подписей на секторах
        wedges, texts, autotexts = ax.pie(
            sizes,
            colors=colors,
            autopct='%1.1f%%',
            startangle=90,
            pctdistance=0.75,
            textprops={'color': 'white', 'fontsize': 11, 'fontweight': 'bold'}
        )

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
            facecolor='#0A0F0A',
            edgecolor='#00FF41',
            labelcolor='#00FF41'
        )

        ax.set_title('Распределение статусов', color='#00FF41', fontsize=14, pad=15)

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
        names = [f['file_name'][:20] for f in files]
        totals = [f['cases_count'] for f in files]
        reviewed = [f['reviewed_count'] for f in files]

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 6), dpi=100)
        fig.patch.set_facecolor('#0A0F0A')
        ax.set_facecolor('#0A0F0A')

        x = range(len(names))
        width = 0.35

        ax.bar([i - width/2 for i in x], totals, width,
               label='Всего', color='#00441A', edgecolor='#00FF41')
        ax.bar([i + width/2 for i in x], reviewed, width,
               label='Проверено', color='#00AA2A', edgecolor='#00FF41')

        ax.set_ylabel('Кейсы', color='#00FF41', fontsize=12)
        ax.set_title('Прогресс по файлам', color='#00FF41', fontsize=14, pad=15)
        ax.set_xticks(list(x))
        ax.set_xticklabels(names, rotation=45, ha='right', color='#00FF41', fontsize=10)
        ax.tick_params(colors='#00FF41', labelsize=10)
        ax.legend(facecolor='#0A0F0A', edgecolor='#00FF41', labelcolor='#00FF41', fontsize=11)

        for spine in ax.spines.values():
            spine.set_color('#00441A')

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
        names = [t['tag_name'] for t in tags]
        counts = [t['cases_count'] for t in tags]

        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, max(4, len(tags) * 0.5)), dpi=100)
        fig.patch.set_facecolor('#0A0F0A')
        ax.set_facecolor('#0A0F0A')

        y_pos = range(len(names))
        ax.barh(y_pos, counts, color='#00AA2A', edgecolor='#00FF41', height=0.6)
        ax.set_yticks(y_pos)
        ax.set_yticklabels(names, color='#00FF41', fontsize=11)
        ax.set_xlabel('Количество кейсов', color='#00FF41', fontsize=12)
        ax.set_title('Топ тегов', color='#00FF41', fontsize=14, pad=15)
        ax.tick_params(colors='#00FF41', labelsize=10)
        ax.invert_yaxis()

        for spine in ax.spines.values():
            spine.set_color('#00441A')

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
            try:
                count = export_results_to_xlsx(self.project_path, file_path)
                QMessageBox.information(
                    self,
                    "Экспорт завершён",
                    f"Экспортировано {count} кейсов в:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать: {str(e)}")

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
            try:
                export_report_to_xlsx(self.project_path, file_path)
                QMessageBox.information(
                    self,
                    "Экспорт завершён",
                    f"Отчёт сохранён в:\n{file_path}"
                )
            except Exception as e:
                QMessageBox.critical(self, "Ошибка", f"Не удалось экспортировать: {str(e)}")

    def on_back(self):
        self.reports_closed.emit()