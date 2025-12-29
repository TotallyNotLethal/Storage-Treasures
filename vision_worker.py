from PySide6.QtCore import QThread, Signal
import requests

from vision_gpt import analyze_image
from vision_cache import image_hash, get_cached, set_cached

class VisionWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(dict)

    def __init__(self, images):
        super().__init__()
        self.images = images

    def run(self):
        total_low = 0
        total_high = 0
        all_items = []
        seen_names = []
        seen_keys = set()

        for img_bytes in self.images:
            result = analyze_image(img_bytes, seen_items=seen_names)
            items = result.get("items", [])

            for it in items:
                low = float(it.get("low", 0))
                high = float(it.get("high", 0))
                conf = float(it.get("confidence", 0))
                name = str(it.get("name", "")).strip()
                brand = str(it.get("brand", "")).strip()

                key = f"{name.lower()}|{brand.lower()}" if name else None

                # Skip duplicates already counted in previous images
                if key and key in seen_keys:
                    continue

                # Confidence-weighted contribution
                total_low += low * conf
                total_high += high * conf

                if key:
                    seen_keys.add(key)
                    seen_names.append(name)

                all_items.append(it)

        self.result = {
            "items": all_items,
            "total_low": int(total_low),
            "total_high": int(total_high)
        }
        
        self.finished.emit(self.result)

