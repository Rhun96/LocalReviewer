from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QSpinBox, QCheckBox, QGroupBox, QMessageBox, QFormLayout,
    QComboBox
)
from PySide6.QtCore import Qt, Signal
from database import get_db_connection
from datetime import datetime


class SettingsScreen(QWidget):
    """Экран настроек приложения."""
    
    settings_closed = Signal()
    
    def __init__(self, project_path: str, parent=None):
        super().__init__(parent)
        self.project_path = project_path
        self.parent_window = parent
        
        self.init_ui()
        self.load_settings()
    
    def init_ui(self):
        layout = QVBoxLayout()
        layout.setSpacing(20)
        layout.setContentsMargins(40, 20, 40, 20)
        
        # Заголовок
        title = QLabel("НАСТРОЙКИ")
        title.setObjectName("title")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        
        # Настройки ревью
        review_group = QGroupBox("Режим ревью")
        review_layout = QFormLayout()
        
        self.auto_next_checkbox = QCheckBox("Автоматически переходить к следующему кейсу после выбора статуса")
        self.auto_next_checkbox.setChecked(True)
        review_layout.addRow(self.auto_next_checkbox)
        
        self.comment_for_bad_combo = QComboBox()
        self.comment_for_bad_combo.addItem("Не обязателен", "none")
        self.comment_for_bad_combo.addItem("Мягкое предупреждение", "warn")
        self.comment_for_bad_combo.addItem("Обязателен", "required")
        self.comment_for_bad_combo.setCurrentIndex(1)
        review_layout.addRow("Комментарий для статуса «Плохо»:", self.comment_for_bad_combo)
        
        review_group.setLayout(review_layout)
        layout.addWidget(review_group)
        
        # Настройки автопроверок
        checks_group = QGroupBox("Автопроверки")
        checks_layout = QFormLayout()
        
        self.min_length_spin = QSpinBox()
        self.min_length_spin.setMinimum(0)
        self.min_length_spin.setMaximum(1000)
        self.min_length_spin.setValue(10)
        checks_layout.addRow("Минимальная длина текста:", self.min_length_spin)
        
        self.max_length_spin = QSpinBox()
        self.max_length_spin.setMinimum(100)
        self.max_length_spin.setMaximum(100000)
        self.max_length_spin.setValue(10000)
        checks_layout.addRow("Максимальная длина текста:", self.max_length_spin)
        
        self.check_url_checkbox = QCheckBox("Проверять наличие URL")
        self.check_url_checkbox.setChecked(True)
        checks_layout.addRow(self.check_url_checkbox)
        
        self.check_email_checkbox = QCheckBox("Проверять наличие email")
        self.check_email_checkbox.setChecked(True)
        checks_layout.addRow(self.check_email_checkbox)
        
        self.check_phone_checkbox = QCheckBox("Проверять наличие телефона")
        self.check_phone_checkbox.setChecked(True)
        checks_layout.addRow(self.check_phone_checkbox)
        
        self.check_spaces_checkbox = QCheckBox("Проверять много пробелов")
        self.check_spaces_checkbox.setChecked(True)
        checks_layout.addRow(self.check_spaces_checkbox)
        
        self.check_caps_checkbox = QCheckBox("Проверять много заглавных букв")
        self.check_caps_checkbox.setChecked(True)
        checks_layout.addRow(self.check_caps_checkbox)
        
        checks_group.setLayout(checks_layout)
        layout.addWidget(checks_group)
        
        # Кнопки
        buttons_layout = QHBoxLayout()
        
        btn_save = QPushButton("Сохранить настройки")
        btn_save.setMinimumHeight(50)
        btn_save.clicked.connect(self.on_save)
        
        btn_reset = QPushButton("Сбросить по умолчанию")
        btn_reset.setMinimumHeight(50)
        btn_reset.clicked.connect(self.on_reset)
        
        btn_back = QPushButton("Назад к проекту")
        btn_back.setObjectName("danger")
        btn_back.setMinimumHeight(50)
        btn_back.clicked.connect(self.on_back)
        
        buttons_layout.addWidget(btn_save)
        buttons_layout.addWidget(btn_reset)
        buttons_layout.addStretch()
        buttons_layout.addWidget(btn_back)
        layout.addLayout(buttons_layout)
        
        self.setLayout(layout)
    
    def load_settings(self):
        """Загружает настройки из базы."""
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            cursor.execute("SELECT key, value FROM settings")
            settings = {row['key']: row['value'] for row in cursor.fetchall()}
            conn.close()
            
            # Применяем настройки
            self.auto_next_checkbox.setChecked(settings.get('auto_next_case', 'true') == 'true')
            
            comment_mode = settings.get('require_comment_for_bad', 'warn')
            for i in range(self.comment_for_bad_combo.count()):
                if self.comment_for_bad_combo.itemData(i) == comment_mode:
                    self.comment_for_bad_combo.setCurrentIndex(i)
                    break
            
            self.min_length_spin.setValue(int(settings.get('checks_min_length', '10')))
            self.max_length_spin.setValue(int(settings.get('checks_max_length', '10000')))
            self.check_url_checkbox.setChecked(settings.get('checks_url', 'true') == 'true')
            self.check_email_checkbox.setChecked(settings.get('checks_email', 'true') == 'true')
            self.check_phone_checkbox.setChecked(settings.get('checks_phone', 'true') == 'true')
            self.check_spaces_checkbox.setChecked(settings.get('checks_spaces', 'true') == 'true')
            self.check_caps_checkbox.setChecked(settings.get('checks_caps', 'true') == 'true')
            
        except Exception as e:
            pass
    
    def on_save(self):
        """Сохраняет настройки."""
        try:
            conn = get_db_connection(self.project_path)
            cursor = conn.cursor()
            now = datetime.now().isoformat()
            
            settings = [
                ('auto_next_case', str(self.auto_next_checkbox.isChecked()).lower()),
                ('require_comment_for_bad', self.comment_for_bad_combo.currentData()),
                ('checks_min_length', str(self.min_length_spin.value())),
                ('checks_max_length', str(self.max_length_spin.value())),
                ('checks_url', str(self.check_url_checkbox.isChecked()).lower()),
                ('checks_email', str(self.check_email_checkbox.isChecked()).lower()),
                ('checks_phone', str(self.check_phone_checkbox.isChecked()).lower()),
                ('checks_spaces', str(self.check_spaces_checkbox.isChecked()).lower()),
                ('checks_caps', str(self.check_caps_checkbox.isChecked()).lower()),
            ]
            
            for key, value in settings:
                cursor.execute("""
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET
                        value = ?,
                        updated_at = ?
                """, (key, value, now, value, now))
            
            conn.commit()
            conn.close()
            
            QMessageBox.information(self, "Настройки", "Настройки сохранены")
            
        except Exception as e:
            QMessageBox.critical(self, "Ошибка", f"Не удалось сохранить настройки: {str(e)}")
    
    def on_reset(self):
        """Сбрасывает настройки по умолчанию."""
        self.auto_next_checkbox.setChecked(True)
        self.comment_for_bad_combo.setCurrentIndex(1)
        self.min_length_spin.setValue(10)
        self.max_length_spin.setValue(10000)
        self.check_url_checkbox.setChecked(True)
        self.check_email_checkbox.setChecked(True)
        self.check_phone_checkbox.setChecked(True)
        self.check_spaces_checkbox.setChecked(True)
        self.check_caps_checkbox.setChecked(True)
    
    def on_back(self):
        """Возврат к проекту."""
        self.settings_closed.emit()