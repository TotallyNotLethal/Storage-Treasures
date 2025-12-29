from PySide6.QtCore import QThread, Signal
import requests
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont

from vision_gpt import analyze_image

class VisionWorker(QThread):
    # progress: aid, current index, total, all_items, image_index, image_url, image_items, annotated_image_bytes
    progress = Signal(str, int, int, list, int, str, list, object)
    error = Signal(str, str)
    cancelled = Signal(str)
    finished = Signal(str, dict)

    def __init__(self, image_urls, auction_id):
        super().__init__()
        self.image_urls = image_urls
        self.auction_id = auction_id
        self._cancel_requested = False

    def request_cancel(self):
        self._cancel_requested = True

    def run(self):
        total_low = 0
        total_high = 0
        all_items = []
        seen_names = []
        seen_keys = set()

        total = len(self.image_urls)

        for idx, url in enumerate(self.image_urls, start=1):
            if self._cancel_requested:
                self.cancelled.emit(self.auction_id)
                return

            img_bytes = None

            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                img_bytes = r.content
            except Exception as e:
                self.error.emit(
                    self.auction_id,
                    f"Failed to fetch image {idx}/{total}: {e}",
                )

            image_items = []

            annotated_bytes = None

            if img_bytes:
                result = analyze_image(img_bytes, seen_items=seen_names)
                items = result.get("items", [])
                image_items = list(items)
                annotated_bytes = self._annotate_image(img_bytes, image_items)

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

            if self._cancel_requested:
                self.cancelled.emit(self.auction_id)
                return

            self.progress.emit(
                self.auction_id,
                idx,
                total,
                list(all_items),
                idx,
                url,
                image_items,
                annotated_bytes,
            )

        if self._cancel_requested:
            self.cancelled.emit(self.auction_id)
            return

        self.result = {
            "items": all_items,
            "total_low": int(total_low),
            "total_high": int(total_high)
        }

        self.finished.emit(self.auction_id, self.result)

    def _annotate_image(self, image_bytes, items):
        try:
            with Image.open(BytesIO(image_bytes)) as im:
                draw = ImageDraw.Draw(im)
                width, height = im.size

                colors = [
                    "#22c55e",
                    "#f59e0b",
                    "#3b82f6",
                    "#ef4444",
                    "#a855f7",
                ]

                try:
                    font = ImageFont.truetype("DejaVuSans.ttf", max(14, width // 80))
                except Exception:
                    font = ImageFont.load_default()

                for i, it in enumerate(items):
                    box = it.get("box") or {}
                    x = float(box.get("x", 0))
                    y = float(box.get("y", 0))
                    w = float(box.get("w", 0))
                    h = float(box.get("h", 0))

                    if x > 1 or y > 1 or w > 1 or h > 1:
                        x /= width
                        y /= height
                        w /= width
                        h /= height

                    x2 = x + w
                    y2 = y + h

                    x = max(0.0, min(1.0, x))
                    y = max(0.0, min(1.0, y))
                    x2 = max(0.0, min(1.0, x2))
                    y2 = max(0.0, min(1.0, y2))

                    if x2 <= x or y2 <= y:
                        continue

                    left = int(x * width)
                    top = int(y * height)
                    right = int(x2 * width)
                    bottom = int(y2 * height)

                    if right <= left or bottom <= top:
                        continue

                    color = colors[i % len(colors)]
                    draw.rectangle([left, top, right, bottom], outline=color, width=max(2, width // 200))

                    label = it.get("name") or "Object"
                    text_w, text_h = draw.textsize(label, font=font)
                    pad = 4
                    rect = [left, max(0, top - text_h - pad * 2), left + text_w + pad * 2, top]
                    draw.rectangle(rect, fill=color)
                    draw.text((left + pad, rect[1] + pad), label, fill="white", font=font)

                out = BytesIO()
                im.save(out, format="PNG")
                return out.getvalue()
        except Exception:
            return None

