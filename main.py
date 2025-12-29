import sys, json, requests, sqlite3, webbrowser, csv, base64
from datetime import datetime, timezone
from vision_worker import VisionWorker

from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QFileDialog, QSplitter, QFrame, QGridLayout,
    QLineEdit, QComboBox, QSlider, QMenu, QDialog, QDialogButtonBox,
    QMessageBox, QDoubleSpinBox,
)
from PySide6.QtGui import QPixmap, QFont, QPdfWriter, QPainter, QPageSize

from config import API_BASE, HEADERS, SEARCH_PARAMS
from db import (
    init_db,
    save_bid,
    bid_velocity,
    get_recent_bids,
    save_vision_result,
    load_vision_result,
    get_recent_vision_results,
    reset_manual_vision_result,
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


class ClickableLabel(QLabel):
    clicked = Signal(object)

    def __init__(self, payload=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.payload = payload or {}

    def mousePressEvent(self, event):
        self.clicked.emit(self.payload)
        super().mousePressEvent(event)

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
        self.had_vision_error = False
        self.analysis_cancelled = False
        self.vision_aid_in_progress = None
        self.analysis_placeholder = None
        self.vision_worker = None
        self.recent_vision_results = []
        self.image_tile_map = {}
        self.using_manual = False

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

        self.recent_card = Card("Recent Vision Results", fixed_height=180)
        recent_layout = QVBoxLayout()
        recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_list = QListWidget()
        self.recent_list.setFixedHeight(140)
        self.recent_list.itemClicked.connect(self.load_cached_analysis)
        recent_layout.addWidget(self.recent_list)
        self.recent_card.layout.addLayout(recent_layout)
        left_layout.addWidget(self.recent_card)

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

        # Inline banner for analysis lock state (hidden by default)
        self.analysis_banner = QFrame()
        self.analysis_banner.setStyleSheet(
            "background: rgba(15, 23, 42, 0.7); color: white;"
            "padding: 10px; border-radius: 10px;"
        )
        banner_layout = QHBoxLayout(self.analysis_banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.setSpacing(10)
        self.analysis_label = QLabel()
        self.analysis_label.setWordWrap(True)
        banner_layout.addWidget(self.analysis_label)
        self.analysis_banner.setVisible(False)
        self.main.addWidget(self.analysis_banner)

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
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_analyze = QPushButton("Analyze Images")
        self.btn_analyze.clicked.connect(self.analyze_images)
        self.btn_cancel_analyze = QPushButton("Cancel analysis")
        self.btn_cancel_analyze.setVisible(False)
        self.btn_cancel_analyze.clicked.connect(self.cancel_analysis)
        controls.addWidget(self.btn_analyze)
        controls.addWidget(self.btn_cancel_analyze)
        controls.addStretch()
        self.card_images.layout.insertLayout(0, controls)

        vision_header = QHBoxLayout()
        vision_header.setContentsMargins(0, 0, 0, 0)
        self.vision_title = QLabel("Vision Breakdown")
        self.vision_title.setStyleSheet("font-weight:600;")
        vision_header.addWidget(self.vision_title)

        self.btn_reset_ai = QPushButton("Reset to AI output")
        self.btn_reset_ai.setVisible(False)
        self.btn_reset_ai.clicked.connect(self.reset_manual_overrides)
        vision_header.addStretch()
        vision_header.addWidget(self.btn_reset_ai)
        self.card_images.layout.addLayout(vision_header)

        self.vision_status = QLabel()
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.card_images.layout.addWidget(self.vision_status)

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
        btn_export_vision = QPushButton("Export Vision")
        vision_menu = QMenu()
        vision_csv = vision_menu.addAction("Vision CSV")
        vision_pdf = vision_menu.addAction("Vision PDF")
        vision_csv.triggered.connect(self.export_vision_csv)
        vision_pdf.triggered.connect(self.export_vision_pdf)
        btn_export_vision.setMenu(vision_menu)

        actions.addStretch()
        actions.addWidget(btn_map)
        actions.addWidget(btn_export)
        actions.addWidget(btn_export_vision)

        # ---- TIMER ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

        self.bootstrap()
        self.refresh_recent_vision_results()

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

    def refresh_recent_vision_results(self):
        self.recent_vision_results = get_recent_vision_results(limit=10)
        self.recent_list.clear()

        if not self.recent_vision_results:
            placeholder = QListWidgetItem("No saved analyses yet.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.recent_list.addItem(placeholder)
            return

        for entry in self.recent_vision_results:
            ts = entry.get("updated_at")
            try:
                dt = datetime.fromisoformat(ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                ts_fmt = dt.astimezone().strftime("%b %d • %I:%M %p")
            except Exception:
                ts_fmt = "Unknown time"

            label = f"{entry['facility_name']} — {ts_fmt}"
            self.recent_list.addItem(label)

    def fetch_ip(self):
        r = requests.get(f"{API_BASE}/p/users/check/user-ip", headers=HEADERS)
        d = r.json()
        return d if isinstance(d, str) else d.get("ip")

    def fetch_list(self):
        r = requests.get(f"{API_BASE}/p/auctions", headers=HEADERS, params=SEARCH_PARAMS)
        return r.json()["auctions"]
        
    def on_image_loaded(self, pix, label):
        label.setText("")
        url = getattr(label, "payload", {}).get("url")
        if url:
            meta = self.image_tile_map.get(url, {})
            meta["base_pixmap"] = pix
            self.image_tile_map[url] = meta
            self.set_label_pixmap(url, pix)
        else:
            label.setPixmap(
                pix.scaled(
                    220, 220,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation
                )
            )

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

        aid = self.current["auction_id"]

        image_urls = [
            img.get("image_path_large") or img.get("image_path")
            for img in self.current.get("images", [])
            if img.get("image_path_large") or img.get("image_path")
        ]

        if not image_urls:
            self.show_analysis_error("No images available for this auction.")
            return

        self.analysis_cancelled = False
        self.vision_aid_in_progress = aid
        auction_name = (
            self.current.get("facility_name")
            or self.current.get("facility", {}).get("name")
            or "this auction"
        )
        self.set_analysis_active(True, auction_name)

        # Reset per-image summaries for this auction
        self.state.vision_image_summaries[aid] = {}
        self.set_all_image_statuses("Analyzing…", "#0ea5e9")

        self.lock_auction_list()
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText("Analyzing images… (list locked)")
        self.btn_analyze.setToolTip(
            "Selection is locked during analysis to avoid mixing auctions."
        )
        self.btn_cancel_analyze.setVisible(True)
        self.btn_cancel_analyze.setEnabled(True)
        self.had_vision_error = False
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_status.setText("Downloading and analyzing images…")

        clear_layout(self.vision_container)
        placeholder = QLabel(
            "Analyzing images… (0/%d) — selection locked to prevent cross-auction updates."
            % len(image_urls)
        )
        placeholder.setStyleSheet("color:#9ca3af;")
        self.analysis_placeholder = placeholder
        self.vision_container.addWidget(placeholder)
        self.vision_items_displayed = []

        self.vision_worker = VisionWorker(image_urls, aid)
        self.vision_worker.progress.connect(self.on_vision_progress)
        self.vision_worker.error.connect(self.on_vision_error)
        self.vision_worker.cancelled.connect(self.on_vision_cancelled)
        self.vision_worker.finished.connect(self.on_vision_done)
        self.vision_worker.start()

    def on_vision_done(self, aid, result):
        if aid != self.vision_aid_in_progress or not self.current:
            return

        clean_run = not self.had_vision_error and not self.analysis_cancelled

        if clean_run:
            self.vision_resale[aid] = result
            self.vision_resale[aid].pop("manual_items", None)
            self.vision_resale[aid].pop("manual_total_low", None)
            self.vision_resale[aid].pop("manual_total_high", None)
            facility_name = (
                self.current.get("facility_name")
                or self.current.get("facility", {}).get("name")
                or ""
            )
            save_vision_result(aid, result, facility_name=facility_name)
            self.refresh_recent_vision_results()

            lo = result.get("total_low", 0)
            hi = result.get("total_high", 0)

            self.lbl_resale.setText(f"${lo:,} – ${hi:,}")
            self.vision_status.setStyleSheet("color:#9ca3af;")
            self.vision_status.setText("")
            self.render_vision_items(result.get("items", []))
            self.using_manual = False
        else:
            note = (
                "Analysis canceled; no results saved."
                if self.analysis_cancelled
                else "Analysis encountered errors; results were not saved."
            )
            self.vision_status.setStyleSheet(
                "color:#9ca3af;" if self.analysis_cancelled else "color:#ef4444;"
            )
            self.vision_status.setText(note)
            self.render_vision_items([])

        self.vision_worker = None
        self.set_analysis_active(False)
        self.unlock_auction_list()
        self.vision_aid_in_progress = None

    def on_vision_progress(self, aid, current, total, items, image_idx, image_url, image_items, annotated_image):
        if aid != self.vision_aid_in_progress:
            return

        self.btn_analyze.setText(
            f"Analyzing images… (list locked) ({current}/{total})"
        )
        self.vision_status.setText(f"Processing images ({current}/{total})…")

        if self.analysis_placeholder:
            self.analysis_placeholder.setText(
                f"Analyzing images… ({current}/{total}) — selection locked to prevent cross-auction updates."
            )

        new_items = items[len(self.vision_items_displayed):]
        if new_items:
            if self.vision_container.count() == 1:
                w = self.vision_container.itemAt(0).widget()
                if isinstance(w, QLabel) and "Analyzing images" in w.text():
                    self.vision_container.removeWidget(w)
                    w.deleteLater()
                    self.analysis_placeholder = None

            self.append_vision_items(new_items)
            self.vision_items_displayed.extend(new_items)

        if image_url:
            self.store_image_items(aid, image_url, image_idx, image_items, annotated_image)
            if image_items:
                label = f"Analyzed ({len(image_items)} items)"
                color = "#22c55e"
            else:
                label = "Analyzed (no items)"
                color = "#6b7280"
            self.set_image_status(image_url, label, color)

            if annotated_image:
                pix = QPixmap()
                pix.loadFromData(annotated_image)
                self.set_label_pixmap(image_url, pix, is_annotated=True)

    def on_vision_cancelled(self, aid):
        if aid != self.vision_aid_in_progress:
            return
        self.analysis_cancelled = True
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_status.setText("Analysis canceled; no results saved.")
        self.set_all_image_statuses("Canceled", "#ef4444")
        self.render_vision_items([])
        self.vision_worker = None
        self.set_analysis_active(False)
        self.unlock_auction_list()
        self.vision_aid_in_progress = None

    def on_vision_error(self, aid, message):
        if aid != self.vision_aid_in_progress:
            return
        self.vision_status.setStyleSheet("color:#ef4444;")
        self.vision_status.setText(message)
        self.had_vision_error = True
        self.set_all_image_statuses("Error", "#ef4444")
        self.set_analysis_active(False)
        self.unlock_auction_list()
        self.vision_aid_in_progress = None
        self.vision_worker = None

    def cancel_analysis(self):
        if not self.vision_worker or self.analysis_cancelled:
            return
        self.analysis_cancelled = True
        self.vision_worker.request_cancel()
        self.btn_cancel_analyze.setEnabled(False)
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_status.setText("Canceling analysis…")

    def show_analysis_error(self, message):
        self.vision_status.setStyleSheet("color:#ef4444;")
        self.vision_status.setText(message)
        self.had_vision_error = True


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

    def load_cached_analysis(self, item):
        if not item or not self.recent_vision_results or self.vision_worker:
            return

        idx = self.recent_list.row(item)
        if idx < 0 or idx >= len(self.recent_vision_results):
            return

        aid = self.recent_vision_results[idx]["auction_id"]

        def fetch():
            r = requests.get(
                f"{API_BASE}/p/auctions/{aid}",
                headers=HEADERS,
                params={"refresh": "true", "user_ip": self.user_ip},
            )
            return r.json()

        self.run_worker(fetch, self.render)

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
        self.set_analysis_active(False)
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
            items, totals, manual_active = self.resolve_display_items(res)
            lo = totals["low"]
            hi = totals["high"]
            self.using_manual = manual_active
            self.render_vision_items(items, manual_active=manual_active)
        else:
            self.using_manual = False
            self.render_vision_items([])

        self.title.setText(a["facility_name"])
        self.subtitle.setText(f"{a['address']} • {a['city']} {a['state']}")

        self.lbl_score.setText(f"{score}/100")
        self.lbl_velocity.setText(f"{vel:.2f}/hr")
        if lo is not None and hi is not None:
            self.update_totals_display({"low": lo, "high": hi})
        else:
            self.lbl_resale.setText("--")

        clear_layout(self.card_details.layout)
        clear_layout(self.image_grid)
        self.image_tile_map = {}

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
        for idx, img in enumerate(a.get("images", []), start=1):
            url = img.get("image_path_large") or img.get("image_path")
            if not url:
                continue

            tile = QFrame()
            tile_layout = QVBoxLayout(tile)
            tile_layout.setContentsMargins(4, 4, 4, 4)
            tile_layout.setSpacing(6)

            lbl = ClickableLabel({"url": url, "index": idx})
            lbl.clicked.connect(self.on_image_clicked)
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setFixedSize(220, 220)
            lbl.setStyleSheet("color:#9ca3af; border:1px dashed #1f2937;")
            lbl.setText("Loading…")

            status = QLabel("Not analyzed")
            status.setAlignment(Qt.AlignCenter)
            status.setStyleSheet(
                "color:#9ca3af; padding:2px 6px; border-radius:8px;"
                "background:#111827; font-size:11px;"
            )

            tile_layout.addWidget(lbl)
            tile_layout.addWidget(status)
            self.image_grid.addWidget(tile, r, c)

            self.image_tile_map[url] = {
                "label": lbl,
                "status": status,
                "index": idx,
            }

            loader = ImageLoader(url, lbl)
            loader.loaded.connect(self.on_image_loaded)
            self.image_threads.append(loader)
            loader.finished.connect(lambda l=loader: self.image_threads.remove(l))
            loader.start()

            c += 1
            if c == 3:
                c = 0
                r += 1

        self.apply_image_summaries(aid)

    def render_vision_items(self, items, manual_active=False):
        clear_layout(self.vision_container)
        self.analysis_placeholder = None
        self.vision_items_displayed = []
        self.btn_reset_ai.setVisible(manual_active)

        if not items:
            placeholder = QLabel("Analyze images to see itemized estimates.")
            placeholder.setStyleSheet("color:#9ca3af;")
            self.vision_container.addWidget(placeholder)
            return

        self.append_vision_items(items)
        self.vision_items_displayed = list(items)

    def apply_image_summaries(self, aid):
        summaries = self.state.vision_image_summaries.get(aid)
        if not summaries:
            return

        for url, info in summaries.items():
            items = info.get("items", [])
            meta = self.image_tile_map.get(url, {})
            meta["items"] = items
            self.image_tile_map[url] = meta
            if items:
                label = f"Analyzed ({len(items)} items)"
                color = "#22c55e"
            else:
                label = "Analyzed (no items)"
                color = "#6b7280"
            self.set_image_status(url, label, color)

            annotated = info.get("annotated")
            if annotated:
                try:
                    data = base64.b64decode(annotated)
                    pix = QPixmap()
                    pix.loadFromData(data)
                    self.set_label_pixmap(url, pix, is_annotated=True)
                except Exception:
                    pass

    def set_label_pixmap(self, url, pixmap, is_annotated=False):
        meta = self.image_tile_map.get(url)
        if not meta:
            return

        if is_annotated:
            meta["annotated_pixmap"] = pixmap
        else:
            meta["base_pixmap"] = pixmap

        self.image_tile_map[url] = meta

        label = meta.get("label")
        if not label:
            return

        active = meta.get("annotated_pixmap") or meta.get("base_pixmap")
        if not active:
            return

        label.setPixmap(
            active.scaled(
                220,
                220,
                Qt.KeepAspectRatio,
                Qt.SmoothTransformation,
            )
        )

        def handler(event, p=active, lbl=label, boxes=meta.get("items", [])):
            lbl.clicked.emit(lbl.payload)
            if p:
                overlay_boxes = [] if meta.get("annotated_pixmap") else boxes
                ImageViewer(p, boxes=overlay_boxes).exec()

        label.mousePressEvent = handler

    def set_analysis_active(self, active, auction_name=""):
        self.card_details.setEnabled(not active)
        if active:
            name = auction_name or self.title.text() or "this auction"
            self.analysis_label.setText(
                f"Analyzing {name} — switching is disabled until completion."
            )
            self.analysis_banner.setVisible(True)
        else:
            self.analysis_label.clear()
            self.analysis_banner.setVisible(False)

    def lock_auction_list(self):
        self.list.setEnabled(False)
        self.list.setContextMenuPolicy(Qt.NoContextMenu)
        self.list.setToolTip(
            "Selection is temporarily disabled while image analysis runs."
        )
        self.recent_list.setEnabled(False)

    def unlock_auction_list(self):
        self.list.setEnabled(True)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.setToolTip("")
        self.btn_analyze.setEnabled(True)
        self.btn_analyze.setText("Analyze Images")
        self.btn_analyze.setToolTip("Analyze images to estimate resale value.")
        self.btn_cancel_analyze.setVisible(False)
        self.btn_cancel_analyze.setEnabled(True)
        self.recent_list.setEnabled(True)

    def get_confidence_badge(self, conf):
        if conf >= 0.8:
            return "High", "#22c55e"
        if conf >= 0.5:
            return "Medium", "#eab308"
        return "Low", "#ef4444"

    def resolve_display_items(self, res):
        manual_items = res.get("manual_items") or []
        if manual_items:
            low = res.get("manual_total_low")
            high = res.get("manual_total_high")
            if low is None or high is None:
                low, high = self.sum_estimates(manual_items)
            return manual_items, {"low": float(low or 0), "high": float(high or 0)}, True

        return (
            res.get("items", []),
            {
                "low": float(res.get("total_low", 0)),
                "high": float(res.get("total_high", 0)),
            },
            False,
        )

    def sum_estimates(self, items):
        low = high = 0.0
        for it in items:
            if it.get("hidden"):
                continue
            low += float(it.get("low", 0) or 0)
            high += float(it.get("high", 0) or 0)
        return low, high

    def update_totals_display(self, totals):
        lo = float(totals.get("low", 0))
        hi = float(totals.get("high", 0))
        self.lbl_resale.setText(f"${lo:,.0f} – ${hi:,.0f}")

    def append_vision_items(self, items):
        for it in items:
            row = self.build_vision_row(it)
            self.vision_container.addWidget(row)

    def collect_manual_items_from_ui(self):
        manual_items = []
        for i in range(self.vision_container.count()):
            w = self.vision_container.itemAt(i).widget()
            if not w or not hasattr(w, "name_input"):
                continue

            low_val = w.low_input.value()
            high_val = w.high_input.value()
            if high_val < low_val:
                high_val = low_val
                w.high_input.setValue(high_val)

            manual_items.append(
                {
                    "name": w.name_input.text().strip() or "Unknown item",
                    "brand": w.brand_input.text().strip() or "Unknown brand",
                    "confidence": float(getattr(w, "confidence", 0)),
                    "low": low_val,
                    "high": high_val,
                    "hidden": w.hide_btn.isChecked(),
                }
            )
        return manual_items

    def toggle_row_hidden(self, row, hidden):
        for widget in (row.name_input, row.brand_input, row.low_input, row.high_input):
            widget.setEnabled(not hidden)
        row.hide_btn.setText("Show" if hidden else "Hide")
        row.setStyleSheet("opacity:0.6;" if hidden else "")

    def persist_manual_edits(self):
        if not self.current:
            return

        aid = self.current.get("auction_id")
        if not aid:
            return

        res = self.vision_resale.get(aid)
        if not res:
            self.vision_status.setStyleSheet("color:#ef4444;")
            self.vision_status.setText("No AI output to edit. Run Analyze Images first.")
            return

        manual_items = self.collect_manual_items_from_ui()
        low, high = self.sum_estimates(manual_items)
        totals = {"low": low, "high": high}

        res["manual_items"] = manual_items
        res["manual_total_low"] = low
        res["manual_total_high"] = high
        self.vision_resale[aid] = res

        facility_name = (
            self.current.get("facility_name")
            or self.current.get("facility", {}).get("name")
            or ""
        )

        save_vision_result(
            aid,
            res,
            facility_name=facility_name,
            manual_items=manual_items,
            manual_totals=totals,
        )

        self.using_manual = True
        self.update_totals_display(totals)
        self.render_vision_items(manual_items, manual_active=True)
        self.vision_status.setStyleSheet("color:#22c55e;")
        self.vision_status.setText("Manual edits saved. Totals updated.")

    def reset_manual_overrides(self):
        if not self.current:
            return

        aid = self.current.get("auction_id")
        if not aid:
            return

        reset_manual_vision_result(aid)
        res = self.vision_resale.get(aid)
        if res:
            res.pop("manual_items", None)
            res.pop("manual_total_low", None)
            res.pop("manual_total_high", None)
            self.vision_resale[aid] = res
            items, totals, manual_active = self.resolve_display_items(res)
            self.using_manual = manual_active
            self.render_vision_items(items, manual_active=manual_active)
            self.update_totals_display(totals)

        self.btn_reset_ai.setVisible(False)
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_status.setText("Reverted to AI output.")

    def set_all_image_statuses(self, text, color):
        for url in self.image_tile_map.keys():
            self.set_image_status(url, text, color)

    def set_image_status(self, url, text, color):
        meta = self.image_tile_map.get(url)
        if not meta:
            return
        lbl = meta.get("status")
        if not lbl:
            return
        lbl.setText(text)
        lbl.setStyleSheet(
            "color:white; padding:2px 6px; border-radius:8px;"
            f"background:{color}; font-size:11px;"
        )

    def store_image_items(self, aid, url, index, items, annotated_bytes=None):
        if not url:
            return
        if aid not in self.state.vision_image_summaries:
            self.state.vision_image_summaries[aid] = {}

        existing = self.state.vision_image_summaries[aid].get(url, {})

        self.state.vision_image_summaries[aid][url] = {
            "index": index,
            "url": url,
            "items": items or [],
            "annotated": base64.b64encode(annotated_bytes).decode("utf-8")
            if annotated_bytes
            else existing.get("annotated"),
        }

        meta = self.image_tile_map.get(url, {})
        meta["items"] = items or []
        self.image_tile_map[url] = meta

    def on_image_clicked(self, payload):
        if not payload or not self.current:
            return

        url = payload.get("url")
        aid = self.current.get("auction_id")
        if not url or not aid:
            return

        summary = self.state.vision_image_summaries.get(aid, {}).get(url, {})
        items = summary.get("items", [])
        self.show_image_dialog(url, items)

    def show_image_dialog(self, url, items):
        dlg = QDialog(self)
        dlg.setWindowTitle("Image analysis details")
        layout = QVBoxLayout(dlg)

        info = QLabel(f"<b>Image</b>: {url}")
        info.setWordWrap(True)
        layout.addWidget(info)

        if not items:
            layout.addWidget(QLabel("No analysis available yet for this image."))
        else:
            for it in items:
                name = it.get("name") or "Unknown"
                brand = it.get("brand") or "Unknown brand"
                conf = float(it.get("confidence", 0)) * 100
                low = float(it.get("low", 0))
                high = float(it.get("high", 0))
                line = QLabel(
                    f"• <b>{name}</b> — {brand} | {conf:.0f}% | ${low:,.0f}-${high:,.0f}"
                )
                line.setWordWrap(True)
                layout.addWidget(line)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok)
        buttons.accepted.connect(dlg.accept)
        layout.addWidget(buttons)
        dlg.exec()

    def build_vision_row(self, it):
        name = it.get("name") or "Unknown item"
        brand = it.get("brand") or "Unknown brand"
        conf = float(it.get("confidence", 0))
        low = float(it.get("low", 0))
        high = float(it.get("high", 0))
        hidden = bool(it.get("hidden"))

        badge_label, badge_color = self.get_confidence_badge(conf)

        row = QWidget()
        row_layout = QHBoxLayout(row)
        row_layout.setContentsMargins(0, 0, 0, 0)
        row_layout.setSpacing(8)

        badge = QLabel(f"{badge_label} • {conf*100:.0f}%")
        badge.setStyleSheet(
            "color:white; padding:2px 8px; border-radius:8px; font-weight:600;"
            f"background:{badge_color};"
        )
        row_layout.addWidget(badge)

        name_input = QLineEdit(name)
        name_input.setPlaceholderText("Item name")
        brand_input = QLineEdit(brand)
        brand_input.setPlaceholderText("Brand")

        low_input = QDoubleSpinBox()
        low_input.setRange(0, 1_000_000)
        low_input.setDecimals(0)
        low_input.setValue(low)
        low_input.setPrefix("$")

        high_input = QDoubleSpinBox()
        high_input.setRange(0, 1_000_000)
        high_input.setDecimals(0)
        high_input.setValue(high)
        high_input.setPrefix("$")

        hide_btn = QPushButton("Hide")
        hide_btn.setCheckable(True)
        hide_btn.setChecked(hidden)
        hide_btn.toggled.connect(lambda checked, r=row: self.toggle_row_hidden(r, checked))

        save_btn = QPushButton("Save")
        save_btn.clicked.connect(self.persist_manual_edits)

        row.name_input = name_input
        row.brand_input = brand_input
        row.low_input = low_input
        row.high_input = high_input
        row.hide_btn = hide_btn
        row.confidence = conf

        row_layout.addWidget(name_input, 2)
        row_layout.addWidget(brand_input, 2)
        row_layout.addWidget(low_input)
        row_layout.addWidget(high_input)
        row_layout.addWidget(hide_btn)
        row_layout.addWidget(save_btn)

        self.toggle_row_hidden(row, hidden)

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

    def format_end_time(self):
        exp = (
            self.current
            and self.current.get("expire_date", {})
            .get("utc", {})
            .get("datetime")
        )
        if not exp:
            return "Unknown"
        try:
            dt = datetime.fromisoformat(exp)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone().strftime("%b %d, %Y %I:%M %p %Z")
        except Exception:
            return str(exp)

    def get_vision_export_data(self):
        if not self.current:
            QMessageBox.information(
                self,
                "No auction selected",
                "Select an auction to export its vision summary.",
            )
            return None

        aid = self.current.get("auction_id")
        res = self.vision_resale.get(aid)
        if not res:
            res = load_vision_result(aid)
            if res:
                self.vision_resale[aid] = res

        if not res:
            QMessageBox.information(
                self,
                "No analysis yet",
                "Run Analyze Images to generate a vision summary before exporting.",
            )
            return None

        items, totals, _ = self.resolve_display_items(res)

        badge_data = []
        for it in items:
            if it.get("hidden"):
                continue
            conf = float(it.get("confidence", 0))
            badge_label, badge_color = self.get_confidence_badge(conf)
            badge_data.append(
                {
                    "name": it.get("name") or "Unknown item",
                    "brand": it.get("brand") or "Unknown brand",
                    "confidence": conf,
                    "badge": badge_label,
                    "badge_color": badge_color,
                    "low": float(it.get("low", 0)),
                    "high": float(it.get("high", 0)),
                }
            )

        meta = {
            "facility": self.current.get("facility_name") or "Unknown facility",
            "location": f"{self.current.get('address', '')}, {self.current.get('city', '')} {self.current.get('state', '')}",
            "end_time": self.format_end_time(),
            "current_bid": self.current.get("current_bid", {}).get("formatted")
            or f"${self.current.get('current_bid', {}).get('amount', 0):,.0f}",
            "total_bids": self.current.get("total_bids", "0"),
            "bid_velocity": f"{bid_velocity(aid):.2f}/hr",
            "unit_size": self.current.get("unit_size") or "",
        }

        totals = {
            "low": float(totals.get("low", 0)),
            "high": float(totals.get("high", 0)),
        }

        return {"metadata": meta, "totals": totals, "items": badge_data}

    def export_vision_csv(self):
        data = self.get_vision_export_data()
        if not data:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Vision CSV", "", "CSV Files (*.csv)"
        )
        if not path:
            return

        meta = data["metadata"]
        totals = data["totals"]

        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["Facility", meta["facility"]])
            w.writerow(["Location", meta["location"]])
            w.writerow(["Unit Size", meta["unit_size"]])
            w.writerow(["Auction End", meta["end_time"]])
            w.writerow(["Current Bid", meta["current_bid"]])
            w.writerow(["Total Bids", meta["total_bids"]])
            w.writerow(["Bid Velocity", meta["bid_velocity"]])
            w.writerow([])
            w.writerow(["Vision Totals", ""])
            w.writerow(["Low", f"${totals['low']:,.0f}"])
            w.writerow(["High", f"${totals['high']:,.0f}"])
            w.writerow([])
            w.writerow([
                "Item",
                "Brand",
                "Confidence",
                "Confidence Badge",
                "Low Estimate",
                "High Estimate",
            ])
            for it in data["items"]:
                w.writerow(
                    [
                        it["name"],
                        it["brand"],
                        f"{it['confidence']*100:.0f}%",
                        it["badge"],
                        f"${it['low']:,.0f}",
                        f"${it['high']:,.0f}",
                    ]
                )

    def export_vision_pdf(self):
        data = self.get_vision_export_data()
        if not data:
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Vision PDF", "", "PDF Files (*.pdf)"
        )
        if not path:
            return

        meta = data["metadata"]
        totals = data["totals"]

        writer = QPdfWriter(path)
        writer.setPageSize(QPageSize(QPageSize.Letter))
        painter = QPainter(writer)

        margin = 60
        y = margin
        width = writer.width() - margin * 2
        line_height = 28

        def ensure_space():
            nonlocal y
            if y > writer.height() - margin:
                writer.newPage()
                y = margin

        def draw(text, size=12, bold=False):
            nonlocal y
            ensure_space()
            font = painter.font()
            font.setPointSize(size)
            font.setBold(bold)
            painter.setFont(font)
            painter.drawText(margin, y, width, line_height, Qt.AlignLeft, text)
            y += line_height

        draw("Vision Summary Export", size=16, bold=True)
        draw(meta["facility"], size=14, bold=True)
        draw(meta["location"])
        draw(f"Unit Size: {meta['unit_size']}")
        draw(f"Auction Ends: {meta['end_time']}")
        draw(f"Current Bid: {meta['current_bid']}  |  Total Bids: {meta['total_bids']}")
        draw(f"Bid Velocity: {meta['bid_velocity']}")

        y += 12
        draw(
            f"Vision Totals — Low: ${totals['low']:,.0f} | High: ${totals['high']:,.0f}",
            bold=True,
        )

        y += 12
        draw("Itemized Estimates", bold=True)
        for it in data["items"]:
            ensure_space()
            line = (
                f"• {it['name']} ({it['brand']}) — {it['badge']} "
                f"{it['confidence']*100:.0f}% — ${it['low']:,.0f} to ${it['high']:,.0f}"
            )
            draw(line)

        painter.end()

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
