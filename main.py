import sys, json, requests, sqlite3, webbrowser, csv
from datetime import datetime, timezone
from vision_worker import VisionWorker

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QFileDialog, QSplitter, QFrame, QGridLayout,
    QLineEdit, QComboBox, QSlider, QMenu
)
from PySide6.QtGui import QPixmap, QFont

from config import API_BASE, HEADERS, SEARCH_PARAMS
from db import (
    init_db,
    save_bid,
    bid_velocity,
    get_recent_bids,
    save_vision_result,
    load_vision_result,
)
from scoring import profit_score
from alerts import SniperAlerts
from charts import sparkline
from vision import tag_from_text
from resale import estimate
from state import AppState
from ui_helpers import Card, clear_layout
from image_viewer import ImageViewer
from styles import STYLE


# ================= THREAD =================
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

# ================= MAIN =================
class AuctionBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StorageAuctions — Auction Intelligence")
        self.resize(1800, 1000)

        init_db()
        self.state = AppState()
        self.sniper = SniperAlerts()

        self.user_ip = None
        self.vision_resale = {}
        self.auctions = []
        self.filtered = []
        self.current = None
        self.threads = []
        self.image_threads = []

        splitter = QSplitter(Qt.Horizontal)
        self.setCentralWidget(splitter)

        # ========== LEFT PANEL ==========
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setSpacing(8)

        # ---- SEARCH CONTROLS (RESTORED) ----
        search_bar = QHBoxLayout()

        self.zip_input = QLineEdit("44647")
        self.zip_input.setPlaceholderText("ZIP")

        self.radius_input = QComboBox()
        self.radius_input.addItems(["5", "10", "25", "50", "100"])
        self.radius_input.setCurrentText("25")

        btn_refresh = QPushButton("Refresh")
        btn_refresh.clicked.connect(self.refresh_search)

        search_bar.addWidget(QLabel("ZIP"))
        search_bar.addWidget(self.zip_input)
        search_bar.addWidget(QLabel("Miles"))
        search_bar.addWidget(self.radius_input)
        search_bar.addWidget(btn_refresh)

        left_layout.addLayout(search_bar)
        
        # --- Slider value labels ---
        self.lbl_score_val = QLabel("Min Score: 0")
        self.lbl_score_val.setStyleSheet("color:#22c55e; font-weight:600;")

        self.lbl_time_val = QLabel("Max Hours: 72")
        self.lbl_time_val.setStyleSheet("color:#60a5fa; font-weight:600;")

        # ---- FILTERS PANEL ----
        filters = QFrame()
        filters.setObjectName("Card")
        fl = QVBoxLayout(filters)

        fl.addWidget(self.lbl_score_val)
        self.score_slider = QSlider(Qt.Horizontal)
        self.score_slider.setRange(0, 100)
        self.score_slider.setValue(0)
        fl.addWidget(self.score_slider)

        fl.addSpacing(6)

        fl.addWidget(self.lbl_time_val)
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 72)
        self.time_slider.setValue(72)
        fl.addWidget(self.time_slider)

        self.score_slider.valueChanged.connect(self.on_score_slider)
        self.time_slider.valueChanged.connect(self.on_time_slider)

        left_layout.addWidget(filters)

        # ---- AUCTION LIST (FIXED HEIGHT) ----
        self.list = QListWidget()
        self.list.setFixedHeight(650)
        self.list.itemClicked.connect(self.select_auction)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.open_list_menu)

        left_layout.addWidget(self.list)

        splitter.addWidget(left_panel)

        # ========== RIGHT PANEL ==========
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        root = QWidget()
        scroll.setWidget(root)
        self.main = QVBoxLayout(root)
        self.main.setSpacing(14)

        # ---- HEADER ----
        self.header = Card(fixed_height=90)
        self.main.addWidget(self.header)

        self.title = QLabel()
        self.title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("color:#9ca3af;")

        self.header.layout.addWidget(self.title)
        self.header.layout.addWidget(self.subtitle)

        # ---- KPIs ----
        kpi = QGridLayout()
        self.main.addLayout(kpi)

        self.lbl_time = QLabel("--")
        self.lbl_score = QLabel("--")
        self.lbl_velocity = QLabel("--")
        self.lbl_resale = QLabel("--")

        for l in (self.lbl_time, self.lbl_score, self.lbl_velocity, self.lbl_resale):
            l.setAlignment(Qt.AlignCenter)
            l.setFont(QFont("Segoe UI", 16, QFont.Bold))

        for i, (name, lbl) in enumerate([
            ("Time Remaining", self.lbl_time),
            ("Profit / Risk", self.lbl_score),
            ("Bid Velocity", self.lbl_velocity),
            ("Resale Estimate", self.lbl_resale)
        ]):
            c = Card(name)
            c.layout.addWidget(lbl)
            kpi.addWidget(c, 0, i)

        # ---- CONTENT ----
        content = QHBoxLayout()
        self.main.addLayout(content)

        self.card_details = Card("Auction Details")
        content.addWidget(self.card_details, 2)

        self.card_images = Card("Images")
        content.addWidget(self.card_images, 3)
        self.image_grid = QGridLayout()
        self.btn_analyze = QPushButton("Analyze Images")
        self.btn_analyze.clicked.connect(self.analyze_images)
        self.card_images.layout.insertWidget(0, self.btn_analyze)

        self.vision_title = QLabel("Vision Breakdown")
        self.vision_title.setStyleSheet("font-weight:600;")
        self.card_images.layout.addWidget(self.vision_title)

        self.vision_container = QVBoxLayout()
        self.vision_container.setSpacing(4)
        self.vision_items_displayed = []
        self.card_images.layout.addLayout(self.vision_container)

        self.card_images.layout.addLayout(self.image_grid)

        self.render_vision_items([])

        # ---- ACTIONS ----
        actions = QHBoxLayout()
        self.main.addLayout(actions)

        btn_map = QPushButton("Open in Google Maps")
        btn_map.clicked.connect(self.open_map)
        btn_export = QPushButton("Export CSV")
        btn_export.clicked.connect(self.export_csv)

        actions.addStretch()
        actions.addWidget(btn_map)
        actions.addWidget(btn_export)

        # ---- TIMER ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

        self.bootstrap()

    # ================= DATA =================
    def run_worker(self, fn, cb):
        w = Worker(fn)
        w.done.connect(cb)
        self.threads.append(w)
        w.finished.connect(lambda: self.threads.remove(w))
        w.start()

    def bootstrap(self):
        self.run_worker(self.fetch_ip, lambda ip: setattr(self, "user_ip", ip))
        self.run_worker(self.fetch_list, self.populate_list)

    def fetch_ip(self):
        r = requests.get(f"{API_BASE}/p/users/check/user-ip", headers=HEADERS)
        d = r.json()
        return d if isinstance(d, str) else d.get("ip")

    def fetch_list(self):
        r = requests.get(f"{API_BASE}/p/auctions", headers=HEADERS, params=SEARCH_PARAMS)
        return r.json()["auctions"]
        
    def on_image_loaded(self, pix, label):
        label.setText("")
        label.setPixmap(
            pix.scaled(
                220, 220,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation
            )
        )
        label.mousePressEvent = lambda e, p=pix: ImageViewer(p).exec()

    def on_score_slider(self, value):
        color = "#22c55e" if value >= 70 else "#f59e0b" if value >= 40 else "#ef4444"
        self.lbl_score_val.setStyleSheet(f"color:{color}; font-weight:600;")
        self.lbl_score_val.setText(f"Min Score: {value}")
        self.apply_filters()

    def on_time_slider(self, value):
        self.lbl_time_val.setText(f"Max Hours: {value}")
        self.apply_filters()

    def refresh_search(self):
        zip_code = self.zip_input.text().strip()
        radius = self.radius_input.currentText()

        if not zip_code.isdigit() or len(zip_code) != 5:
            return

        SEARCH_PARAMS["search_term"] = zip_code
        SEARCH_PARAMS["search_radius"] = radius

        self.list.clear()
        self.current = None
        self.run_worker(self.fetch_list, self.populate_list)
        
    def analyze_images(self):
        if not self.current:
            return

        image_bytes = []

        for img in self.current.get("images", []):
            url = img.get("image_path_large") or img.get("image_path")
            if not url:
                continue

            try:
                r = requests.get(url, timeout=10)
                r.raise_for_status()
                image_bytes.append(r.content)
            except Exception as e:
                print("Image fetch failed:", e)

        if not image_bytes:
            return

        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("Analyzing images...")

        clear_layout(self.vision_container)
        placeholder = QLabel("Analyzing images... (0/%d)" % len(image_bytes))
        placeholder.setStyleSheet("color:#9ca3af;")
        self.vision_container.addWidget(placeholder)
        self.vision_items_displayed = []

        # ✅ pass BYTES, not URLs
        self.vision_worker = VisionWorker(image_bytes)
        self.vision_worker.progress.connect(self.on_vision_progress)
        self.vision_worker.finished.connect(self.on_vision_done)
        self.vision_worker.start()

    def on_vision_done(self, result):
        if not self.current:
            return

        aid = self.current["auction_id"]

        self.vision_resale[aid] = result
        save_vision_result(aid, result)

        lo = result.get("total_low", 0)
        hi = result.get("total_high", 0)

        self.lbl_resale.setText(f"${lo:,} – ${hi:,}")

        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Analyze Images")

        self.render_vision_items(result.get("items", []))

    def on_vision_progress(self, current, total, items):
        self.btn_analyze.setText(f"Analyzing images... ({current}/{total})")

        new_items = items[len(self.vision_items_displayed):]
        if not new_items:
            return

        if self.vision_container.count() == 1:
            w = self.vision_container.itemAt(0).widget()
            if isinstance(w, QLabel) and "Analyzing images" in w.text():
                self.vision_container.removeWidget(w)
                w.deleteLater()

        self.append_vision_items(new_items)
        self.vision_items_displayed.extend(new_items)


    # ================= LIST / FILTER =================
    def populate_list(self, auctions):
        self.auctions = auctions
        self.apply_filters()
        
    def format_time_left(expire_utc):
        exp = datetime.fromisoformat(expire_utc).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        delta = exp - now

        if delta.total_seconds() <= 0:
            return "ENDED"

        days = delta.days
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60

        if days > 0:
            return f"{days}d {hours}h"
            return f"{hours}h {minutes}m"


    def apply_filters(self):
        self.list.clear()
        self.filtered = []

        min_score = self.score_slider.value()
        max_hours = self.time_slider.value()
        now = datetime.now(timezone.utc)

        for a in self.auctions:
            exp = datetime.fromisoformat(
                a["expire_date"]["utc"]["datetime"]
            ).replace(tzinfo=timezone.utc)

            delta = exp - now
            hrs = delta.total_seconds() / 3600

            if delta.total_seconds() <= 0:
                time_left = "ENDED"
            else:
                days = delta.days
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                time_left = f"{days}d {hours}h" if days > 0 else f"{hours}h {minutes}m"

            vel = bid_velocity(a["auction_id"])
            score = profit_score(a, vel)

            if score < min_score or hrs > max_hours:
                continue

            star = "⭐ " if a["auction_id"] in self.state.watchlist else ""
            item = QListWidgetItem(
                f"{star}{a['city']} {a['state']} | {a['unit_size']} | "
                f"${a['current_bid']['amount']} | {score}/100 | "
                f"⏱ {time_left}"
            )

            self.list.addItem(item)
            self.filtered.append(a)

    # ================= WATCHLIST =================
    def open_list_menu(self, pos):
        item = self.list.itemAt(pos)
        if not item:
            return
        idx = self.list.row(item)
        aid = self.filtered[idx]["auction_id"]

        menu = QMenu()
        action = menu.addAction("Toggle Watchlist ⭐")
        if menu.exec_(self.list.mapToGlobal(pos)) == action:
            self.state.toggle_watch(aid)
            self.apply_filters()

    # ================= SELECT =================
    def select_auction(self, item):
        idx = self.list.row(item)
        aid = self.filtered[idx]["auction_id"]

        def fetch():
            r = requests.get(
                f"{API_BASE}/p/auctions/{aid}",
                headers=HEADERS,
                params={"refresh": "true", "user_ip": self.user_ip}
            )
            return r.json()

        self.run_worker(fetch, self.render)

    # ================= RENDER =================
    def render(self, payload):
        if "auction" not in payload:
            return

        a = payload["auction"]
        save_bid(a)
        self.current = a

        vel = bid_velocity(a["auction_id"])
        score = profit_score(a, vel)

        tags = tag_from_text(a.get("unit_contents"))

        aid = a["auction_id"]
        lo = hi = None

        res = self.vision_resale.get(aid)
        if not res:
            res = load_vision_result(aid)
            if res:
                self.vision_resale[aid] = res

        if res:
            lo = res.get("total_low", 0)
            hi = res.get("total_high", 0)
            self.render_vision_items(res.get("items", []))
        else:
            self.render_vision_items([])

        self.title.setText(a["facility_name"])
        self.subtitle.setText(f"{a['address']} • {a['city']} {a['state']}")

        self.lbl_score.setText(f"{score}/100")
        self.lbl_velocity.setText(f"{vel:.2f}/hr")
        if lo is not None and hi is not None:
            self.lbl_resale.setText(f"${lo:,} – ${hi:,}")
        else:
            self.lbl_resale.setText("--")

        clear_layout(self.card_details.layout)
        clear_layout(self.image_grid)

        def row(k, v):
            self.card_details.layout.addWidget(QLabel(f"<b>{k}</b>: {v}"))

        row("Unit Size", a["unit_size"])
        row("Current Bid", a["current_bid"]["formatted"])
        row("Total Bids", a["total_bids"])
        row("Views", a["total_views"])
        row("Contents", a["unit_contents"] or "—")
        row("Tags", ", ".join(tags))

        bids = get_recent_bids(a["auction_id"])
        sp = sparkline(bids, velocity=vel)
        lbl = QLabel()
        lbl.setPixmap(sp)
        self.card_details.layout.addWidget(QLabel("Bid Trend"))
        self.card_details.layout.addWidget(lbl)

        r = c = 0
        for img in a.get("images", []):
            url = img.get("image_path_large") or img.get("image_path")
            if not url:
                continue
    
            lbl = QLabel("Loading…")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(220, 220)
            lbl.setStyleSheet("color:#9ca3af; border:1px dashed #1f2937;")
            self.image_grid.addWidget(lbl, r, c)
    
            loader = ImageLoader(url, lbl)
            loader.loaded.connect(self.on_image_loaded)
            self.image_threads.append(loader)
            loader.finished.connect(lambda l=loader: self.image_threads.remove(l))
            loader.start()
    
            c += 1
            if c == 3:
                c = 0
                r += 1

    def render_vision_items(self, items):
        clear_layout(self.vision_container)
        self.vision_items_displayed = []

        if not items:
            placeholder = QLabel("Analyze images to see itemized estimates.")
            placeholder.setStyleSheet("color:#9ca3af;")
            self.vision_container.addWidget(placeholder)
            return

        self.append_vision_items(items)
        self.vision_items_displayed = list(items)

    def append_vision_items(self, items):
        for it in items:
            row = self.build_vision_row(it)
            self.vision_container.addWidget(row)

    def build_vision_row(self, it):
        name = it.get("name") or "Unknown item"
        brand = it.get("brand") or "Unknown brand"
        conf = float(it.get("confidence", 0))
        low = float(it.get("low", 0))
        high = float(it.get("high", 0))

        if conf >= 0.8:
            badge_label, badge_color = "High", "#22c55e"
        elif conf >= 0.5:
            badge_label, badge_color = "Medium", "#eab308"
        else:
            badge_label, badge_color = "Low", "#ef4444"

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        badge = QLabel(f"{badge_label} • {conf*100:.0f}%")
        badge.setStyleSheet(
            "color:white; padding:2px 8px; border-radius:8px; font-weight:600;"
            f"background:{badge_color};"
        )

        info = QLabel(
            f"<b>{name}</b> — {brand} • ${low:,.0f}–${high:,.0f}"
        )
        info.setWordWrap(True)

        row_layout.addWidget(badge)
        row_layout.addWidget(info, 1)

        return row

    # ================= TIMER =================
    def update_countdown(self):
        if not self.current:
            return

        exp = datetime.fromisoformat(
            self.current["expire_date"]["utc"]["datetime"]
        ).replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        delta = exp - now
        mins = delta.total_seconds() / 60

        if mins <= 0:
            self.lbl_time.setText("ENDED")
            self.lbl_time.setStyleSheet("color:#ef4444;")
            return

        # ✅ text update (FIXED)
        self.lbl_time.setText(str(delta).split(".")[0])

        # ✅ color coding by urgency
        if mins <= 5:
            self.lbl_time.setStyleSheet("color:#ef4444;")   # red
        elif mins <= 30:
            self.lbl_time.setStyleSheet("color:#f59e0b;")   # amber
        else:
            self.lbl_time.setStyleSheet("color:#22c55e;")   # green

        # sniper alert logic preserved
        fired = self.sniper.check(mins)
        if fired:
            self.lbl_time.setStyleSheet("color:#ef4444; font-weight:700;")

    # ================= ACTIONS =================
    def open_map(self):
        if not self.current:
            return
        m = self.current["facility"]["marker"]
        webbrowser.open(f"https://www.google.com/maps?q={m['lat']},{m['lng']}")

    def export_csv(self):
        if not self.current:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Export CSV", "", "CSV Files (*.csv)")
        if not path:
            return
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            for k, v in self.current.items():
                w.writerow([k, json.dumps(v)])


# ================= MAIN =================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    win = AuctionBrowser()
    win.show()
    sys.exit(app.exec())
