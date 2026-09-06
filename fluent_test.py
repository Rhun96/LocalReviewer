import sys
from PySide6.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QWidget, QFrame
from PySide6.QtCore import Qt
from qfluentwidgets import (
    setTheme, Theme, setThemeColor,
    PrimaryPushButton, PushButton, TogglePushButton, CardWidget,
    TitleLabel, SubtitleLabel, BodyLabel, CaptionLabel,
    LineEdit, TextEdit, ComboBox, CheckBox, SwitchButton,
    TableWidget, InfoBar, InfoBarPosition
)


class FluentTest(QWidget):
    """Тестовое окно с компонентами QFluentWidgets."""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Local Reviewer — Fluent Design")
        self.resize(1000, 750)
        
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 30, 40, 30)
        
        # Заголовки
        title = TitleLabel("LOCAL REVIEWER")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        subtitle = SubtitleLabel("локальная разметка датасетов")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)
        
        caption = CaptionLabel("Кейс 143 / 1200 | Файл: run_2026_06.xlsx | Статус: Не проверено")
        caption.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(caption)
        
        # Карточка с текстом кейса
        text_card = CardWidget()
        text_layout = QVBoxLayout()
        text_layout.setSpacing(10)
        text_card.setLayout(text_layout)
        
        label1 = BodyLabel("Основной текст:")
        label1.setStyleSheet("font-weight: bold;")
        text_layout.addWidget(label1)
        
        content1 = BodyLabel("Как оформить возврат товара, купленного онлайн?")
        content1.setWordWrap(True)
        text_layout.addWidget(content1)
        
        # Разделитель
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background-color: #333; max-height: 1px;")
        text_layout.addWidget(line)
        
        label2 = BodyLabel("Ответ модели:")
        label2.setStyleSheet("font-weight: bold;")
        text_layout.addWidget(label2)
        
        content2 = BodyLabel("Для оформления возврата товара перейдите в личный кабинет, найдите заказ и нажмите кнопку «Оформить возврат». Заполните форму и выберите способ возврата.")
        content2.setWordWrap(True)
        text_layout.addWidget(content2)
        
        layout.addWidget(text_card)
        
        # Карточка со статусами
        status_card = CardWidget()
        status_layout = QVBoxLayout()
        status_layout.setSpacing(10)
        status_card.setLayout(status_layout)
        
        status_label = BodyLabel("Статус (клавиши 1-5)")
        status_label.setStyleSheet("font-weight: bold;")
        status_layout.addWidget(status_label)
        
        row1 = QHBoxLayout()
        btn_good = PrimaryPushButton("Хорошо [1]")
        btn_bad = PushButton("Плохо [2]")
        btn_uncertain = PushButton("Сомневаюсь [3]")
        row1.addWidget(btn_good)
        row1.addWidget(btn_bad)
        row1.addWidget(btn_uncertain)
        status_layout.addLayout(row1)
        
        row2 = QHBoxLayout()
        btn_duplicate = PushButton("Дубль [4]")
        btn_skip = PushButton("Пропустить [5]")
        row2.addWidget(btn_duplicate)
        row2.addWidget(btn_skip)
        status_layout.addLayout(row2)
        
        layout.addWidget(status_card)
        
        # Карточка с тегами
        tags_card = CardWidget()
        tags_layout = QVBoxLayout()
        tags_layout.setSpacing(10)
        tags_card.setLayout(tags_layout)
        
        tags_label = BodyLabel("Теги")
        tags_label.setStyleSheet("font-weight: bold;")
        tags_layout.addWidget(tags_label)
        
        row3 = QHBoxLayout()
        tag1 = TogglePushButton("факты")
        tag1.setChecked(True)
        tag2 = TogglePushButton("формат")
        tag3 = TogglePushButton("стиль")
        tag4 = TogglePushButton("длина")
        row3.addWidget(tag1)
        row3.addWidget(tag2)
        row3.addWidget(tag3)
        row3.addWidget(tag4)
        tags_layout.addLayout(row3)
        
        layout.addWidget(tags_card)
        
        # Карточка с комментарием
        comment_card = CardWidget()
        comment_layout = QVBoxLayout()
        comment_layout.setSpacing(10)
        comment_card.setLayout(comment_layout)
        
        comment_label = BodyLabel("Комментарий")
        comment_label.setStyleSheet("font-weight: bold;")
        comment_layout.addWidget(comment_label)
        
        comment_edit = TextEdit()
        comment_edit.setPlaceholderText("Введите комментарий...")
        comment_edit.setMaximumHeight(60)
        comment_layout.addWidget(comment_edit)
        
        row4 = QHBoxLayout()
        btn_templates = PushButton("Шаблоны")
        btn_add = PushButton("+ Новый шаблон")
        row4.addWidget(btn_templates)
        row4.addWidget(btn_add)
        row4.addStretch()
        comment_layout.addLayout(row4)
        
        layout.addWidget(comment_card)
        
        # Навигация
        nav_layout = QHBoxLayout()
        btn_prev = PushButton("← Предыдущий")
        btn_next = PrimaryPushButton("Следующий →")
        btn_back = PushButton("Назад к проекту")
        
        nav_layout.addWidget(btn_prev)
        nav_layout.addWidget(btn_next)
        nav_layout.addStretch()
        nav_layout.addWidget(btn_back)
        layout.addLayout(nav_layout)
        
        self.setLayout(layout)


def main():
    app = QApplication(sys.argv)
    
    # Тёмная тема + зелёный акцент
    setTheme(Theme.DARK)
    setThemeColor("#00FF41")
    
    window = FluentTest()
    window.show()
    
    sys.exit(app.exec())

if __name__ == "__main__":
    main()