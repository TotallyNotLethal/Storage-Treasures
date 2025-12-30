
import json
from pathlib import Path


class AppState:
    CONFIG_FILE = Path.home() / ".storage_treasures_prefs.json"

    def __init__(self):
        self.watchlist = set()
        self.refresh_seconds = 30
        # aid -> {url: {"index": int, "items": list, "url": str, "annotated": str|None}}
        self.vision_image_summaries = {}
        self.preferences = {
            "default_zip": "44647",
            "default_radius": 25,
            "min_score_default": 0,
            "max_hours_default": 72,
            "theme": "Dark",
            "lock_during_analysis": True,
            "show_analysis_banner": True,
        }
        self.load()

    def load(self):
        if not self.CONFIG_FILE.exists():
            return
        try:
            data = json.loads(self.CONFIG_FILE.read_text())
            prefs = data.get("preferences", {})
            if isinstance(prefs, dict):
                self.preferences.update(prefs)
        except Exception:
            # fall back to in-memory defaults on error
            pass

    def save(self):
        payload = {"preferences": self.preferences}
        try:
            self.CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            self.CONFIG_FILE.write_text(json.dumps(payload, indent=2))
        except Exception:
            # Avoid crashing the app when disk writes fail
            pass
        
class SearchState:
    def __init__(self):
        self.zipcode = "44647"
        self.radius = 25
        self.sort = "expire_date"

class FilterState:
    def __init__(self):
        self.min_score = 0
        self.max_minutes = None
