
from PySide6.QtCore import QThread, Signal

class Worker(QThread):
    done = Signal(object)
    def __init__(self, fn):
        super().__init__()
        self.fn = fn
    def run(self):
        self.done.emit(self.fn())

class ImageLoader(QThread):
    loaded = Signal(QPixmap, object)

    def __init__(self, url, target_label):
        super().__init__()
        self.url = url
        self.target_label = target_label

    def run(self):
        try:
            r = requests.get(self.url, timeout=10)
            pix = QPixmap()
            pix.loadFromData(r.content)
            self.loaded.emit(pix, self.target_label)
        except Exception:
            pass
