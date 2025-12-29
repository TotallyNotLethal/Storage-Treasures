
from PySide6.QtWidgets import QFrame, QVBoxLayout, QLabel

class Card(QFrame):
    def __init__(self, title=None, fixed_height=None):
        super().__init__()
        self.setObjectName("Card")
        if fixed_height:
            self.setFixedHeight(fixed_height)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(12, 10, 12, 10)
        self.layout.setSpacing(6)
        if title:
            t = QLabel(title)
            t.setObjectName("CardTitle")
            self.layout.addWidget(t)

def clear_layout(layout):
    while layout.count():
        w = layout.takeAt(0).widget()
        if w:
            w.deleteLater()
