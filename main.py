import sys, json, requests, sqlite3, webbrowser, csv, base64, math
from datetime import datetime, timezone
from vision_worker import VisionWorker

import pgeocode

from PySide6.QtCore import Qt, QThread, Signal, QTimer, QSortFilterProxyModel, QRegularExpression, QUrl
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QListWidget, QListWidgetItem,
    QLabel, QVBoxLayout, QHBoxLayout, QScrollArea, QPushButton,
    QFileDialog, QSplitter, QFrame, QGridLayout, QSizePolicy,
    QLineEdit, QComboBox, QSlider, QMenu, QDialog, QDialogButtonBox,
    QMessageBox, QDoubleSpinBox, QTableView, QAbstractItemView, QToolButton,
    QTabWidget, QSpinBox, QCheckBox, QFormLayout, QStyle, QStackedLayout,
)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtGui import (
    QPixmap,
    QFont,
    QPdfWriter,
    QPainter,
    QPageSize,
    QStandardItemModel,
    QStandardItem,
)

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
from styles import STYLE, THEMES


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


class MapPreview(QWidget):
    def __init__(self, on_open_full_map, parent=None):
        super().__init__(parent)
        self.setMinimumSize(240, 170)
        self.setMaximumHeight(240)

        self.on_open_full_map = on_open_full_map
        self.marker = None

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        toolbar.setContentsMargins(0, 0, 0, 0)

        self.btn_recenter = QToolButton()
        self.btn_recenter.setText("Recenter")
        self.btn_recenter.setIcon(self.style().standardIcon(QStyle.SP_BrowserReload))
        self.btn_recenter.clicked.connect(self.recenter)
        self.btn_recenter.setEnabled(False)

        self.btn_open_full = QToolButton()
        self.btn_open_full.setText("Open Full Map")
        self.btn_open_full.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
        self.btn_open_full.clicked.connect(self.open_full_map)
        self.btn_open_full.setEnabled(False)

        toolbar.addWidget(self.btn_recenter)
        toolbar.addWidget(self.btn_open_full)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self.web_view = QWebEngineView()
        self.web_view.setContextMenuPolicy(Qt.NoContextMenu)
        self.web_view.setStyleSheet("border:1px solid #1f2937; border-radius:12px;")

        self.fallback_label = QLabel("Add a facility location to preview the map.")
        self.fallback_label.setAlignment(Qt.AlignCenter)
        self.fallback_label.setWordWrap(True)
        self.fallback_label.setStyleSheet(
            "border:1px dashed #1f2937; border-radius:12px; padding:12px; color:#9ca3af;"
        )

        self.stack = QStackedLayout()
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.setStackingMode(QStackedLayout.StackAll)
        self.stack.addWidget(self.fallback_label)
        self.stack.addWidget(self.web_view)

        container = QWidget()
        container.setLayout(self.stack)
        layout.addWidget(container)

        self.show_fallback()

    def show_fallback(self, message="Add a facility location to preview the map."):
        self.fallback_label.setText(message)
        self.stack.setCurrentWidget(self.fallback_label)
        self.btn_recenter.setEnabled(False)
        self.btn_open_full.setEnabled(False)

    def show_map(self):
        self.stack.setCurrentWidget(self.web_view)
        self.btn_recenter.setEnabled(True)
        self.btn_open_full.setEnabled(True)

    def load_marker(self, marker):
        self.marker = marker if marker else None
        if not marker:
            self.show_fallback("Map preview unavailable without coordinates.")
            return

        lat, lng = marker.get("lat"), marker.get("lng")
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            self.show_fallback("Map preview unavailable without valid coordinates.")
            return

        html = f"""
        <!DOCTYPE html>
        <html>
          <head>
            <meta charset='utf-8' />
            <meta name='viewport' content='initial-scale=1.0'>
            <link
              rel='stylesheet'
              href='https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
              integrity='sha256-sA+e2H1Lg0JEZ5dj62nCayG4h3GcGZTcECI1qek4z+M='
              crossorigin=''
            />
            <style>
              html, body, #map {{ height: 100%; margin: 0; }}
              #map {{ border-radius: 12px; }}
            </style>
          </head>
          <body>
            <div id='map'></div>
            <script
              src='https://unpkg.com/leaflet@1.9.4/dist/leaflet.js'
              integrity='sha256-o9N1j7kQdwy3vWx3XvGkkgZ+3Jj8GkMq1kE1A6Bv700='
              crossorigin=''
            ></script>
            <script>
              const center = [{lat}, {lng}];
              const map = L.map('map', {{ zoomControl: true }}).setView(center, 13);
              L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
                maxZoom: 19,
                attribution: '© OpenStreetMap'
              }}).addTo(map);
              L.marker(center).addTo(map);
            </script>
          </body>
        </html>
        """

        self.web_view.setHtml(html, QUrl("https://local.map"))
        self.show_map()

    def recenter(self):
        if self.marker:
            self.load_marker(self.marker)

    def open_full_map(self):
        if self.marker and self.on_open_full_map:
            self.on_open_full_map()

# ================= MAIN =================
class AuctionBrowser(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("StorageAuctions — Auction Intelligence")
        self.resize(1800, 1000)

        init_db()
        self.state = AppState()
        self.sniper = SniperAlerts()

        self.apply_theme(self.state.preferences.get("theme"))

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
        self.zip_coord_cache = {}
        self.geocoder = pgeocode.Nominatim("us")

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

        btn_settings = QToolButton()
        btn_settings.setText("Settings")
        btn_settings.clicked.connect(self.open_settings_dialog)

        search_bar.addWidget(QLabel("ZIP"))
        search_bar.addWidget(self.zip_input)
        search_bar.addWidget(QLabel("Miles"))
        search_bar.addWidget(self.radius_input)
        search_bar.addWidget(btn_settings)
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
        self.score_slider.setToolTip("Only show auctions with a profit/risk score at or above this threshold.")
        fl.addWidget(self.score_slider)

        fl.addSpacing(6)

        fl.addWidget(self.lbl_time_val)
        self.time_slider = QSlider(Qt.Horizontal)
        self.time_slider.setRange(0, 72)
        self.time_slider.setValue(72)
        self.time_slider.setToolTip("Only show auctions ending within this many hours.")
        fl.addWidget(self.time_slider)

        helper_label = QLabel(
            "Filters limit the auctions shown below based on profit score and hours remaining."
        )
        helper_label.setStyleSheet("color:#9ca3af; font-size:12px;")
        helper_label.setWordWrap(True)
        fl.addWidget(helper_label)

        self.score_slider.valueChanged.connect(self.on_score_slider)
        self.time_slider.valueChanged.connect(self.on_time_slider)

        left_layout.addWidget(filters)

        # ---- AUCTION LIST CONTROLS ----
        list_toolbar = QHBoxLayout()
        list_toolbar.setSpacing(6)

        list_toolbar.addWidget(QLabel("Sort:"))

        self.btn_sort_time = QToolButton()
        self.btn_sort_time.setText("Time Remaining")
        self.btn_sort_time.setCheckable(True)
        self.btn_sort_time.clicked.connect(lambda: self.set_sort("time"))
        list_toolbar.addWidget(self.btn_sort_time)

        self.btn_sort_score = QToolButton()
        self.btn_sort_score.setText("Profit Score")
        self.btn_sort_score.setCheckable(True)
        self.btn_sort_score.clicked.connect(lambda: self.set_sort("score"))
        list_toolbar.addWidget(self.btn_sort_score)

        self.btn_sort_velocity = QToolButton()
        self.btn_sort_velocity.setText("Bid Velocity")
        self.btn_sort_velocity.setCheckable(True)
        self.btn_sort_velocity.clicked.connect(lambda: self.set_sort("velocity"))
        list_toolbar.addWidget(self.btn_sort_velocity)

        list_toolbar.addStretch()

        self.filter_input = QLineEdit()
        self.filter_input.setPlaceholderText("Filter auctions…")
        self.filter_input.textChanged.connect(self.on_filter_text)
        list_toolbar.addWidget(self.filter_input)

        left_layout.addLayout(list_toolbar)

        # ---- AUCTION LIST (FIXED HEIGHT) ----
        self.list_model = QStandardItemModel(0, 7)
        self.list_model.setHorizontalHeaderLabels([
            "★",
            "Location",
            "Unit",
            "Bid",
            "Score",
            "Velocity",
            "Time Remaining",
        ])

        self.proxy_model = QSortFilterProxyModel()
        self.proxy_model.setFilterCaseSensitivity(Qt.CaseInsensitive)
        self.proxy_model.setFilterKeyColumn(-1)
        self.proxy_model.setSortRole(Qt.UserRole)
        self.proxy_model.setSourceModel(self.list_model)

        self.list = QTableView()
        self.list.setModel(self.proxy_model)
        self.list.setFixedHeight(650)
        self.list.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.list.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.list.horizontalHeader().setStretchLastSection(True)
        self.list.verticalHeader().setVisible(False)
        self.list.setSortingEnabled(True)
        self.list.clicked.connect(self.select_auction)
        self.list.doubleClicked.connect(self.select_auction)
        self.list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self.open_list_menu)

        left_layout.addWidget(self.list)

        status_layout = QHBoxLayout()
        self.filter_status = QLabel("0 results")
        self.filter_status.setStyleSheet("color:#9ca3af;")
        status_layout.addWidget(self.filter_status)
        status_layout.addStretch()
        left_layout.addLayout(status_layout)

        self.field_column_map = {
            "time": 6,
            "score": 4,
            "velocity": 5,
        }
        self.sort_button_map = {
            "time": self.btn_sort_time,
            "score": self.btn_sort_score,
            "velocity": self.btn_sort_velocity,
        }
        self.sort_order = Qt.AscendingOrder
        self.sort_column = None
        self.set_sort("time")

        splitter.addWidget(left_panel)

        # ========== RIGHT PANEL ==========
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        splitter.addWidget(scroll)

        self.tabs = QTabWidget()
        scroll.setWidget(self.tabs)
        self.tabs.currentChanged.connect(self.on_tab_changed)

        overview = QWidget()
        overview_layout = QVBoxLayout(overview)
        overview_layout.setSpacing(14)
        self.tabs.addTab(overview, "Overview")

        # ---- HEADER ----
        self.header = Card(fixed_height=90)
        overview_layout.addWidget(self.header)

        self.title = QLabel()
        self.title.setFont(QFont("Segoe UI", 18, QFont.Bold))
        self.subtitle = QLabel()
        self.subtitle.setStyleSheet("color:#9ca3af;")

        header_row = QHBoxLayout()
        header_row.setContentsMargins(0, 0, 0, 0)
        header_row.setSpacing(10)
        header_row.addWidget(self.title)

        self.distance_badge = QLabel("Distance: --")
        self.distance_badge.setStyleSheet(
            "background:#0ea5e9; color:white; padding:6px 10px;"
            "border-radius:10px; font-weight:600;"
        )
        header_row.addWidget(self.distance_badge)
        header_row.addStretch()

        self.header.layout.addLayout(header_row)
        self.header.layout.addWidget(self.subtitle)

        toolbar = QFrame()
        toolbar.setObjectName("ActionToolbar")
        toolbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        toolbar.setStyleSheet(
            "#ActionToolbar {"
            "background: #0b1222; border: 1px solid #1f2937; border-radius: 12px;"
            "padding: 10px 12px;"
            "}"
            "#ActionToolbar QToolButton {"
            "background: #111827; color: #e5e7eb; border: 1px solid #1f2937;"
            "border-radius: 10px; padding: 8px 12px;"
            "}"
            "#ActionToolbar QToolButton:hover { background: #0f172a; border-color: #374151; }"
            "#ActionToolbar QToolButton:pressed { background: #0b1222; }"
        )
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 0, 4, 0)
        toolbar_layout.setSpacing(10)

        btn_map = QToolButton()
        btn_map.setText("Open Map")
        btn_map.setIcon(self.style().standardIcon(QStyle.SP_DriveNetIcon))
        btn_map.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_map.clicked.connect(self.open_map)
        toolbar_layout.addWidget(btn_map)

        btn_export = QToolButton()
        btn_export.setText("Export CSV")
        btn_export.setIcon(self.style().standardIcon(QStyle.SP_DialogSaveButton))
        btn_export.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_export.clicked.connect(self.export_csv)
        toolbar_layout.addWidget(btn_export)

        btn_export_vision = QToolButton()
        btn_export_vision.setText("Export Vision")
        btn_export_vision.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        btn_export_vision.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        btn_export_vision.setPopupMode(QToolButton.InstantPopup)
        vision_menu = QMenu()
        vision_csv = vision_menu.addAction("Vision CSV")
        vision_pdf = vision_menu.addAction("Vision PDF")
        vision_csv.triggered.connect(self.export_vision_csv)
        vision_pdf.triggered.connect(self.export_vision_pdf)
        btn_export_vision.setMenu(vision_menu)
        toolbar_layout.addWidget(btn_export_vision)

        toolbar_layout.addStretch()
        overview_layout.addWidget(toolbar)

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
        overview_layout.addWidget(self.analysis_banner)

        # ---- KPIs ----
        kpi = QGridLayout()
        overview_layout.addLayout(kpi)

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
        overview_content = QHBoxLayout()
        overview_layout.addLayout(overview_content)

        self.card_details = Card("Auction Details")
        overview_content.addWidget(self.card_details, 2)

        scroll_style = (
            "QScrollArea { border: none; }"
            "QScrollBar:vertical { width: 8px; background: transparent; margin: 0px; }"
            "QScrollBar::handle:vertical { background: #1f2937; border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #334155; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar:horizontal { height: 0px; }"
        )

        self.details_scroll = QScrollArea()
        self.details_scroll.setWidgetResizable(True)
        self.details_scroll.setFrameShape(QFrame.NoFrame)
        self.details_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.details_scroll.setStyleSheet(scroll_style)
        self.details_scroll.setMinimumHeight(260)
        self.details_scroll.setMaximumHeight(520)

        details_container = QWidget()
        self.details_layout = QVBoxLayout(details_container)
        self.details_layout.setContentsMargins(0, 0, 0, 0)
        self.details_layout.setSpacing(8)
        self.details_scroll.setWidget(details_container)
        self.card_details.layout.addWidget(self.details_scroll)

        self.map_card = Card("Map Preview")
        self.map_preview = MapPreview(self.open_map)
        self.map_card.layout.addWidget(self.map_preview)
        overview_content.addWidget(self.map_card, 1)

        gallery = QWidget()
        gallery_layout = QVBoxLayout(gallery)
        gallery_layout.setSpacing(14)
        self.tabs.addTab(gallery, "Gallery")

        self.card_images = Card("Images")
        gallery_layout.addWidget(self.card_images)
        controls = QHBoxLayout()
        controls.setSpacing(8)
        self.btn_analyze = QPushButton("Analyze Images")
        self.btn_analyze.setToolTip("Analyze images to estimate resale value.")
        self.btn_analyze.clicked.connect(self.analyze_images)
        self.btn_cancel_analyze = QPushButton("Cancel analysis")
        self.btn_cancel_analyze.setVisible(False)
        self.btn_cancel_analyze.setToolTip("Stop the current image analysis run.")
        self.btn_cancel_analyze.clicked.connect(self.cancel_analysis)
        controls.addWidget(self.btn_analyze)
        controls.addWidget(self.btn_cancel_analyze)
        controls.addStretch()
        self.card_images.layout.insertLayout(1, controls)

        self.images_scroll = QScrollArea()
        self.images_scroll.setWidgetResizable(True)
        self.images_scroll.setFrameShape(QFrame.NoFrame)
        self.images_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.images_scroll.setStyleSheet(scroll_style)
        self.images_scroll.setMinimumHeight(340)
        self.images_scroll.setMaximumHeight(720)

        images_container = QWidget()
        images_layout = QVBoxLayout(images_container)
        images_layout.setContentsMargins(6, 6, 6, 6)
        images_layout.setSpacing(12)

        self.vision_card = Card("Vision Breakdown")
        vision_header = QHBoxLayout()
        vision_header.setContentsMargins(0, 0, 0, 0)

        self.btn_reset_ai = QPushButton("Reset to AI output")
        self.btn_reset_ai.setVisible(False)
        self.btn_reset_ai.clicked.connect(self.reset_manual_overrides)
        vision_header.addStretch()
        vision_header.addWidget(self.btn_reset_ai)
        self.vision_card.layout.addLayout(vision_header)

        self.vision_status = QLabel()
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_card.layout.addWidget(self.vision_status)

        self.vision_container = QVBoxLayout()
        self.vision_container.setSpacing(6)
        self.vision_items_displayed = []
        self.vision_card.layout.addLayout(self.vision_container)
        images_layout.addWidget(self.vision_card)

        self.image_grid = QGridLayout()
        self.image_grid.setSpacing(12)
        grid_container = QWidget()
        grid_layout = QVBoxLayout(grid_container)
        grid_layout.setContentsMargins(0, 0, 0, 0)
        grid_layout.setSpacing(6)
        grid_layout.addLayout(self.image_grid)

        self.grid_card = Card("Auction Images")
        self.grid_card.layout.addWidget(grid_container)
        images_layout.addWidget(self.grid_card)

        self.images_scroll.setWidget(images_container)
        self.card_images.layout.addWidget(self.images_scroll)

        self.render_vision_items([])

        activity = QWidget()
        activity_layout = QVBoxLayout(activity)
        activity_layout.setSpacing(14)
        self.tabs.addTab(activity, "Activity")

        self.recent_card = Card("Recent Vision Results", fixed_height=180)
        recent_layout = QVBoxLayout()
        recent_layout.setContentsMargins(0, 0, 0, 0)
        self.recent_list = QListWidget()
        self.recent_list.setFixedHeight(140)
        self.recent_list.setToolTip(
            "Cached analyses open immediately without reprocessing images."
        )
        self.recent_list.itemClicked.connect(self.load_cached_analysis)
        recent_layout.addWidget(self.recent_list)
        self.recent_card.layout.addLayout(recent_layout)
        activity_layout.addWidget(self.recent_card)

        self.apply_preferences(refresh=False)

        # ---- TIMER ----
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(1000)

        self.bootstrap()
        self.refresh_recent_vision_results()

    def on_tab_changed(self, index):
        if not self.current:
            return

        self.update_profit_ratio_display()
        self.update_distance_badge(self.current.get("facility", {}).get("marker"))

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

    def apply_theme(self, theme_name):
        app = QApplication.instance()
        if not app:
            return
        theme = THEMES.get(theme_name) or STYLE
        app.setStyleSheet(theme)

    def apply_preferences(self, refresh=True):
        prefs = self.state.preferences

        zip_code = prefs.get("default_zip", "44647")
        if zip_code:
            self.zip_input.setText(zip_code)

        radius = str(prefs.get("default_radius", 25))
        idx = self.radius_input.findText(radius)
        if idx != -1:
            self.radius_input.setCurrentIndex(idx)

        min_score = max(0, min(100, int(prefs.get("min_score_default", 0) or 0)))
        max_hours = max(0, min(72, int(prefs.get("max_hours_default", 72) or 0)))
        self.score_slider.setValue(min_score)
        self.time_slider.setValue(max_hours)

        self.apply_theme(prefs.get("theme"))

        SEARCH_PARAMS["search_term"] = zip_code
        SEARCH_PARAMS["search_radius"] = radius

        if refresh:
            self.refresh_search()

    def open_settings_dialog(self):
        prefs = self.state.preferences.copy()
        dlg = QDialog(self)
        dlg.setWindowTitle("Preferences")
        layout = QVBoxLayout(dlg)
        form = QFormLayout()

        zip_input = QLineEdit(prefs.get("default_zip", ""))

        radius_combo = QComboBox()
        radius_options = [self.radius_input.itemText(i) for i in range(self.radius_input.count())]
        radius_combo.addItems(radius_options)
        radius_combo.setCurrentText(str(prefs.get("default_radius", 25)))

        min_score_spin = QSpinBox()
        min_score_spin.setRange(0, 100)
        min_score_spin.setValue(int(prefs.get("min_score_default", 0) or 0))

        max_hours_spin = QSpinBox()
        max_hours_spin.setRange(0, 72)
        max_hours_spin.setValue(int(prefs.get("max_hours_default", 72) or 72))

        theme_combo = QComboBox()
        theme_combo.addItems(THEMES.keys())
        theme_combo.setCurrentText(prefs.get("theme", "Dark"))

        lock_checkbox = QCheckBox("Lock auction list during analysis")
        lock_checkbox.setChecked(prefs.get("lock_during_analysis", True))

        banner_checkbox = QCheckBox("Show analysis banner")
        banner_checkbox.setChecked(prefs.get("show_analysis_banner", True))

        form.addRow("Default ZIP", zip_input)
        form.addRow("Default Radius (miles)", radius_combo)
        form.addRow("Min Score slider default", min_score_spin)
        form.addRow("Max Hours slider default", max_hours_spin)
        form.addRow("Theme", theme_combo)

        layout.addLayout(form)
        layout.addWidget(QLabel("Analysis behaviors"))
        layout.addWidget(lock_checkbox)
        layout.addWidget(banner_checkbox)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        layout.addWidget(buttons)

        if dlg.exec() == QDialog.Accepted:
            prefs.update({
                "default_zip": zip_input.text().strip() or prefs.get("default_zip", "44647"),
                "default_radius": int(radius_combo.currentText()),
                "min_score_default": min_score_spin.value(),
                "max_hours_default": max_hours_spin.value(),
                "theme": theme_combo.currentText(),
                "lock_during_analysis": lock_checkbox.isChecked(),
                "show_analysis_banner": banner_checkbox.isChecked(),
            })
            self.state.preferences = prefs
            self.state.save()
            self.apply_preferences()

    def refresh_search(self):
        zip_code = self.zip_input.text().strip()
        radius = self.radius_input.currentText()

        if not zip_code.isdigit() or len(zip_code) != 5:
            return

        SEARCH_PARAMS["search_term"] = zip_code
        SEARCH_PARAMS["search_radius"] = radius

        self.list_model.removeRows(0, self.list_model.rowCount())
        self.filtered = []
        self.update_filter_status()
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

        lock_enabled = self.state.preferences.get("lock_during_analysis", True)
        if lock_enabled:
            self.lock_auction_list()
        self.btn_analyze.setEnabled(False)
        self.btn_analyze.setText(
            "Analyzing images… (list locked)" if lock_enabled else "Analyzing images…"
        )
        self.btn_analyze.setToolTip(
            "Selection is locked during analysis to avoid mixing auctions." if lock_enabled else "Analysis is running in the background."
        )
        self.btn_cancel_analyze.setVisible(True)
        self.btn_cancel_analyze.setEnabled(True)
        self.had_vision_error = False
        self.vision_status.setStyleSheet("color:#9ca3af;")
        self.vision_status.setText("Downloading and analyzing images…")

        clear_layout(self.vision_container)
        lock_note = (
            "selection locked to prevent cross-auction updates."
            if lock_enabled
            else "analysis running in the background."
        )
        placeholder = QLabel(
            f"Analyzing images… (0/{len(image_urls)}) — {lock_note}"
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

            self.update_totals_display({"low": lo, "high": hi})
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

    def apply_filters(self):
        self.list_model.removeRows(0, self.list_model.rowCount())
        self.filtered = []

        min_score = self.score_slider.value()
        max_hours = self.time_slider.value()
        now = datetime.now(timezone.utc)

        for a in self.auctions:
            exp = datetime.fromisoformat(
                a["expire_date"]["utc"]["datetime"]
            ).replace(tzinfo=timezone.utc)

            delta = exp - now
            hrs = max(delta.total_seconds() / 3600, 0)

            if delta.total_seconds() <= 0:
                time_left = "ENDED"
                sort_hours = float("inf")
            else:
                days = delta.days
                hours = delta.seconds // 3600
                minutes = (delta.seconds % 3600) // 60
                time_left = f"{days}d {hours}h" if days > 0 else f"{hours}h {minutes}m"
                sort_hours = hrs

            vel = bid_velocity(a["auction_id"])
            score = profit_score(a, vel)

            if score < min_score or hrs > max_hours:
                continue

            star_item = QStandardItem("⭐" if a["auction_id"] in self.state.watchlist else "")
            star_item.setEditable(False)
            star_item.setData(0, Qt.UserRole)

            location_item = QStandardItem(f"{a['city']} {a['state']}")
            location_item.setEditable(False)

            unit_item = QStandardItem(a.get("unit_size", ""))
            unit_item.setEditable(False)

            bid_amount = float(a["current_bid"].get("amount", 0))
            bid_item = QStandardItem(f"${bid_amount:.0f}")
            bid_item.setEditable(False)
            bid_item.setData(bid_amount, Qt.UserRole)

            score_item = QStandardItem(f"{score}/100")
            score_item.setEditable(False)
            score_item.setData(score, Qt.UserRole)

            vel_item = QStandardItem(f"{vel:.2f}/hr")
            vel_item.setEditable(False)
            vel_item.setData(vel, Qt.UserRole)

            time_item = QStandardItem(time_left)
            time_item.setEditable(False)
            time_item.setData(sort_hours, Qt.UserRole)

            self.list_model.appendRow([
                star_item,
                location_item,
                unit_item,
                bid_item,
                score_item,
                vel_item,
                time_item,
            ])

            self.filtered.append(a)

        self.proxy_model.invalidateFilter()
        self.on_filter_text(self.filter_input.text())
        self.apply_sort()
        self.update_filter_status()

    def on_filter_text(self, text):
        regex = QRegularExpression(text, QRegularExpression.CaseInsensitiveOption)
        self.proxy_model.setFilterRegularExpression(regex)
        self.update_filter_status()

    def update_filter_status(self):
        visible = self.proxy_model.rowCount()
        total = len(self.filtered)
        self.filter_status.setText(f"{visible} shown / {total} matched filters")

    def set_sort(self, field):
        column = self.field_column_map.get(field)
        if column is None:
            return

        if getattr(self, "sort_column", None) == column:
            self.sort_order = (
                Qt.DescendingOrder
                if self.sort_order == Qt.AscendingOrder
                else Qt.AscendingOrder
            )
        else:
            self.sort_column = column
            self.sort_order = Qt.AscendingOrder

        for key, btn in self.sort_button_map.items():
            btn.setChecked(key == field)

        self.apply_sort()

    def apply_sort(self):
        if getattr(self, "sort_column", None) is None:
            return
        self.list.sortByColumn(self.sort_column, self.sort_order)

    def auction_from_index(self, index):
        if not index.isValid():
            return None
        source_index = self.proxy_model.mapToSource(index)
        row = source_index.row()
        if row < 0 or row >= len(self.filtered):
            return None
        return self.filtered[row]

    # ================= WATCHLIST =================
    def open_list_menu(self, pos):
        index = self.list.indexAt(pos)
        auction = self.auction_from_index(index)
        if not auction:
            return
        aid = auction["auction_id"]

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
    def select_auction(self, index):
        auction = self.auction_from_index(index)
        if not auction:
            return

        aid = auction["auction_id"]

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

        clear_layout(self.details_layout)
        clear_layout(self.image_grid)
        self.image_tile_map = {}

        def row(k, v):
            row_frame = QFrame()
            row_layout = QHBoxLayout(row_frame)
            row_layout.setContentsMargins(6, 4, 6, 4)
            row_layout.setSpacing(12)

            title_lbl = QLabel(k)
            title_lbl.setStyleSheet("font-weight:600;")
            title_lbl.setMinimumWidth(120)

            value_lbl = QLabel(str(v))
            value_lbl.setWordWrap(True)
            value_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            max_width = max(self.card_details.width(), self.details_scroll.viewport().width())
            value_lbl.setMaximumWidth(max(max_width - 40, 320))

            row_layout.addWidget(title_lbl)
            row_layout.addWidget(value_lbl, 1)
            self.details_layout.addWidget(row_frame)

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
        self.details_layout.addWidget(QLabel("Bid Trend"))
        self.details_layout.addWidget(lbl)

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

        self.update_distance_badge(a.get("facility", {}).get("marker"))
        self.update_map_preview(a.get("facility", {}))

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
        show_banner = self.state.preferences.get("show_analysis_banner", True)
        if active and show_banner:
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
        self.update_profit_ratio_display(totals)

    def update_profit_ratio_display(self, totals=None):
        if not self.current:
            self.lbl_score.setText("--")
            return

        current_bid = float(self.current.get("current_bid", {}).get("amount") or 0)
        lo = float(totals.get("low", 0) if totals else 0)
        hi = float(totals.get("high", 0) if totals else 0)

        if totals and current_bid > 0:
            low_ratio = lo / current_bid
            high_ratio = hi / current_bid
            self.lbl_score.setText(f"{low_ratio:.1f}x – {high_ratio:.1f}x")
            return

        vel = bid_velocity(self.current.get("auction_id"))
        score = profit_score(self.current, vel)
        self.lbl_score.setText(f"{score}/100")

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
        marker = None
        if self.current:
            marker = (self.current.get("facility") or {}).get("marker")
        if not marker:
            QMessageBox.information(self, "Map", "Location not available for this facility.")
            return

        lat, lng = marker.get("lat"), marker.get("lng")
        if lat is None or lng is None:
            QMessageBox.information(self, "Map", "Location not available for this facility.")
            return

        webbrowser.open(f"https://www.google.com/maps?q={lat},{lng}")

    def get_search_coordinates(self):
        zip_code = str(SEARCH_PARAMS.get("search_term", "")).strip()
        if not zip_code:
            return None

        if zip_code in self.zip_coord_cache:
            return self.zip_coord_cache[zip_code]

        try:
            info = self.geocoder.query_postal_code(zip_code)
            lat, lng = float(info.latitude), float(info.longitude)
            if math.isnan(lat) or math.isnan(lng):
                raise ValueError("Invalid coordinates")
            coords = (lat, lng)
        except Exception:
            coords = None

        self.zip_coord_cache[zip_code] = coords
        return coords

    def calculate_distance_miles(self, facility_marker):
        if not facility_marker:
            return None

        search_coords = self.get_search_coordinates()
        if not search_coords:
            return None

        lat1, lng1 = search_coords
        lat2_raw, lng2_raw = facility_marker.get("lat"), facility_marker.get("lng")

        try:
            lat2, lng2 = float(lat2_raw), float(lng2_raw)
        except (TypeError, ValueError):
            return None

        if None in (lat2, lng2) or math.isnan(lat2) or math.isnan(lng2):
            return None

        def to_radians(deg):
            return deg * math.pi / 180

        r = 3958.8  # Earth radius in miles
        dlat = to_radians(lat2 - lat1)
        dlng = to_radians(lng2 - lng1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(to_radians(lat1))
            * math.cos(to_radians(lat2))
            * math.sin(dlng / 2) ** 2
        )
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
        return r * c

    def update_distance_badge(self, facility_marker):
        distance = self.calculate_distance_miles(facility_marker)
        zip_code = SEARCH_PARAMS.get("search_term", "")

        if distance is None:
            self.distance_badge.setText("Distance unavailable")
            self.distance_badge.setStyleSheet(
                "background:#6b7280; color:white; padding:6px 10px;"
                "border-radius:10px; font-weight:600;"
            )
            return

        self.distance_badge.setText(f"{distance:.1f} mi from {zip_code}")
        badge_color = "#22c55e" if distance <= 25 else "#f59e0b" if distance <= 75 else "#ef4444"
        self.distance_badge.setStyleSheet(
            f"background:{badge_color}; color:white; padding:6px 10px;"
            "border-radius:10px; font-weight:600;"
        )

    def update_map_preview(self, facility):
        marker = facility.get("marker") if facility else None
        self.map_preview.load_marker(marker)

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
    win = AuctionBrowser()
    win.show()
    sys.exit(app.exec())
