
DARK_STYLE = """
QWidget { background:#0b1220; color:#e5e7eb; font-family:Segoe UI; }
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
"""

LIGHT_STYLE = """
QWidget { background:#f8fafc; color:#0f172a; font-family:Segoe UI; }
#Card {
    background: #ffffff;
    border:1px solid #e2e8f0;
    border-radius:12px;
}
#CardTitle { font-size:12px; font-weight:600; color:#1d4ed8; }
QListWidget { background:#ffffff; border:none; }
QListWidget::item { padding:10px; border-bottom:1px solid #e2e8f0; }
QListWidget::item:selected { background:#e0f2fe; }
"""

STYLE = DARK_STYLE

THEMES = {
    "Dark": DARK_STYLE,
    "Light": LIGHT_STYLE,
}
