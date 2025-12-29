
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QPixmap

class ImageViewer(QDialog):
    def __init__(self, pix, boxes=None):
        super().__init__()
        self.setWindowTitle("Image Viewer")
        self.resize(900, 900)
        layout = QVBoxLayout(self)

        annotated = QPixmap(pix)
        if boxes:
            self._draw_boxes(annotated, boxes)

        lbl = QLabel()
        lbl.setPixmap(annotated.scaled(
            880, 880, Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        layout.addWidget(lbl)

    def _draw_boxes(self, pixmap, boxes):
        painter = QPainter(pixmap)
        width = pixmap.width()
        height = pixmap.height()

        colors = [
            "#22c55e",
            "#f59e0b",
            "#3b82f6",
            "#ef4444",
            "#a855f7",
        ]

        pen_width = max(2, width // 200)
        font = QFont("Segoe UI", max(10, width // 100))

        for i, it in enumerate(boxes):
            box = it.get("box") or {}
            x = float(box.get("x", 0))
            y = float(box.get("y", 0))
            w = float(box.get("w", 0))
            h = float(box.get("h", 0))

            if w <= 0 or h <= 0:
                continue

            left = max(0, min(width, int(x * width)))
            top = max(0, min(height, int(y * height)))
            right = max(0, min(width, int((x + w) * width)))
            bottom = max(0, min(height, int((y + h) * height)))

            if right <= left or bottom <= top:
                continue

            color = QColor(colors[i % len(colors)])
            pen = QPen(color)
            pen.setWidth(pen_width)
            painter.setPen(pen)
            painter.drawRect(left, top, right - left, bottom - top)

            label = it.get("name") or "Object"
            painter.setFont(font)
            painter.fillRect(
                left,
                max(0, top - font.pointSize() * 2),
                painter.fontMetrics().horizontalAdvance(label) + 12,
                font.pointSize() * 2 + 6,
                color,
            )
            painter.setPen(QColor("white"))
            painter.drawText(left + 6, max(font.pointSize(), top - 4), label)

        painter.end()
