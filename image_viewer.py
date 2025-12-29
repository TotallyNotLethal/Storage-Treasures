
from PySide6.QtWidgets import QDialog, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class ImageViewer(QDialog):
    def __init__(self, pix):
        super().__init__()
        self.setWindowTitle("Image Viewer")
        self.resize(900, 900)
        layout = QVBoxLayout(self)
        lbl = QLabel()
        lbl.setPixmap(pix.scaled(
            880, 880, Qt.KeepAspectRatio, Qt.SmoothTransformation
        ))
        layout.addWidget(lbl)
