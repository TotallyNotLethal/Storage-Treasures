
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor
from PySide6.QtCore import Qt

def sparkline(values, velocity=None, w=140, h=40):
    pix = QPixmap(w, h)
    pix.fill(Qt.transparent)

    if len(values) < 2:
        return pix

    if velocity is None:
        color = Qt.green
    elif velocity < 5:
        color = QColor("#22c55e")   # green
    elif velocity < 20:
        color = QColor("#f59e0b")   # amber
    else:
        color = QColor("#ef4444")   # red

    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(color, 2))

    mn, mx = min(values), max(values)
    span = max(mx - mn, 1)

    for i in range(len(values) - 1):
        x1 = int(i * (w / (len(values) - 1)))
        y1 = int(h - ((values[i] - mn) / span) * h)
        x2 = int((i + 1) * (w / (len(values) - 1)))
        y2 = int(h - ((values[i + 1] - mn) / span) * h)
        p.drawLine(x1, y1, x2, y2)

    p.end()
    return pix
