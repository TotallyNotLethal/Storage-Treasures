
class AppState:
    def __init__(self):
        self.watchlist = set()
        self.refresh_seconds = 30
        # aid -> {url: {"index": int, "items": list, "url": str, "annotated": str|None}}
        self.vision_image_summaries = {}
        
class SearchState:
    def __init__(self):
        self.zipcode = "44647"
        self.radius = 25
        self.sort = "expire_date"

class FilterState:
    def __init__(self):
        self.min_score = 0
        self.max_minutes = None
