DARK_STYLE = """
QWidget {
    background:#0b1220;
    color:#e5e7eb;
    font-family:Segoe UI;
}

#Card {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:1,
        stop:0 #1a2333, stop:1 #0f172a);
    border:1px solid #1f2937;
    border-radius:12px;
}

#CardTitle { font-size:12px; font-weight:600; color:#93c5fd; }

QListWidget { background:#0f172a; border:none; }
QListWidget::item { padding:10px; border-bottom:1px solid #1f2937; }
QListWidget::item:selected { background:#1d4ed8; }

QPushButton, QToolButton {
    background: #111827;
    border: 1px solid #1f2937;
    border-radius: 10px;
    color: #e5e7eb;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: #1f2a3d;
    border-color: #3b82f6;
}
QPushButton:pressed, QToolButton:pressed {
    background: #1b2435;
    border-color: #2563eb;
}
QPushButton:disabled, QToolButton:disabled {
    background: #0f172a;
    color: #6b7280;
    border-color: #111827;
}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #0f172a;
    border: 1px solid #1f2937;
    border-radius: 8px;
    color: #e5e7eb;
    padding: 6px 8px;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 1px #3b82f6;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #1f2937;
}
QComboBox::down-arrow {
    image: none;
    border: 5px solid transparent;
    border-top-color: #e5e7eb;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #0f172a;
    border: 1px solid #1f2937;
    selection-background-color: #1d4ed8;
    selection-color: #e5e7eb;
}

QSlider::groove:horizontal {
    background: #1f2937;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #2563eb;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #3b82f6;
    border: 1px solid #1d4ed8;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #60a5fa;
}
QSlider::handle:horizontal:pressed {
    background: #2563eb;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #1f2937;
    border-radius: 6px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #24314a;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 4px;
}
QScrollBar::handle:horizontal {
    background: #1f2937;
    border-radius: 6px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #24314a;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QTableView {
    background: #0f172a;
    alternate-background-color: #0c1725;
    border: 1px solid #1f2937;
    border-radius: 10px;
    gridline-color: #1f2937;
    selection-background-color: #1d4ed8;
    selection-color: #e5e7eb;
}
QHeaderView::section {
    background: #111827;
    color: #9ca3af;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #1f2937;
}
QTableView::item {
    padding: 8px 10px;
}
QTableView::item:selected:active {
    background: #1d4ed8;
}
"""

LIGHT_STYLE = """
QWidget {
    background:#f8fafc;
    color:#0f172a;
    font-family:Segoe UI;
}

#Card {
    background: #ffffff;
    border:1px solid #e2e8f0;
    border-radius:12px;
}

#CardTitle { font-size:12px; font-weight:600; color:#1d4ed8; }

QListWidget { background:#ffffff; border:none; }
QListWidget::item { padding:10px; border-bottom:1px solid #e2e8f0; }
QListWidget::item:selected { background:#e0f2fe; }

QPushButton, QToolButton {
    background: #e5e7eb;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    color: #0f172a;
    padding: 8px 12px;
    font-weight: 600;
}
QPushButton:hover, QToolButton:hover {
    background: #dbeafe;
    border-color: #60a5fa;
}
QPushButton:pressed, QToolButton:pressed {
    background: #bfdbfe;
    border-color: #3b82f6;
}
QPushButton:disabled, QToolButton:disabled {
    background: #f1f5f9;
    color: #94a3b8;
    border-color: #e2e8f0;
}

QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    color: #0f172a;
    padding: 6px 8px;
}
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QComboBox:focus,
QSpinBox:focus, QDoubleSpinBox:focus {
    border-color: #3b82f6;
    box-shadow: 0 0 0 1px #bfdbfe;
}
QComboBox::drop-down {
    subcontrol-origin: padding;
    subcontrol-position: top right;
    width: 24px;
    border-left: 1px solid #e2e8f0;
}
QComboBox::down-arrow {
    image: none;
    border: 5px solid transparent;
    border-top-color: #0f172a;
    margin-right: 6px;
}
QComboBox QAbstractItemView {
    background: #ffffff;
    border: 1px solid #e2e8f0;
    selection-background-color: #e0f2fe;
    selection-color: #0f172a;
}

QSlider::groove:horizontal {
    background: #e2e8f0;
    height: 6px;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #3b82f6;
    height: 6px;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background: #60a5fa;
    border: 1px solid #3b82f6;
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #93c5fd;
}
QSlider::handle:horizontal:pressed {
    background: #2563eb;
}

QScrollBar:vertical {
    background: transparent;
    width: 12px;
    margin: 4px;
}
QScrollBar::handle:vertical {
    background: #e2e8f0;
    border-radius: 6px;
    min-height: 24px;
}
QScrollBar::handle:vertical:hover {
    background: #cbd5e1;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 12px;
    margin: 4px;
}
QScrollBar::handle:horizontal {
    background: #e2e8f0;
    border-radius: 6px;
    min-width: 24px;
}
QScrollBar::handle:horizontal:hover {
    background: #cbd5e1;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

QTableView {
    background: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    gridline-color: #e2e8f0;
    selection-background-color: #e0f2fe;
    selection-color: #0f172a;
}
QHeaderView::section {
    background: #f1f5f9;
    color: #475569;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
}
QTableView::item {
    padding: 8px 10px;
}
QTableView::item:selected:active {
    background: #e0f2fe;
}
"""

STYLE = DARK_STYLE

THEMES = {
    "Dark": DARK_STYLE,
    "Light": LIGHT_STYLE,
}
