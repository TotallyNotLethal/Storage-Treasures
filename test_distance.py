import math
import sys
import types
import unittest


def _install_dummy_requests():
    if "requests" in sys.modules:
        return
    dummy_requests = types.SimpleNamespace(get=lambda *args, **kwargs: None)
    sys.modules["requests"] = dummy_requests


def _install_dummy_pgeocode():
    if "pgeocode" in sys.modules:
        return

    class DummyPostalInfo:
        latitude = None
        longitude = None

    class DummyNominatim:
        def __init__(self, *args, **kwargs):
            pass

        def query_postal_code(self, *args, **kwargs):
            return DummyPostalInfo()

    dummy_pgeocode = types.SimpleNamespace(Nominatim=DummyNominatim)
    sys.modules["pgeocode"] = dummy_pgeocode


def _install_dummy_qt():
    if "PySide6" in sys.modules:
        return

    class Dummy:
        def __init__(self, *args, **kwargs):
            pass

    def _build_module(name, attributes):
        mod = types.ModuleType(name)
        for attr in attributes:
            setattr(mod, attr, Dummy)
        mod.__getattr__ = lambda _name: Dummy
        return mod

    qt_module = types.ModuleType("PySide6")

    qt_core = _build_module(
        "PySide6.QtCore",
        [
            "QThread",
            "Signal",
            "QTimer",
            "QSortFilterProxyModel",
            "QRegularExpression",
        ],
    )
    qt_core.Qt = types.SimpleNamespace(Horizontal=1)

    qt_widgets = _build_module(
        "PySide6.QtWidgets",
        [
            "QApplication",
            "QMainWindow",
            "QWidget",
            "QListWidget",
            "QListWidgetItem",
            "QLabel",
            "QVBoxLayout",
            "QHBoxLayout",
            "QScrollArea",
            "QPushButton",
            "QFileDialog",
            "QSplitter",
            "QFrame",
            "QGridLayout",
            "QSizePolicy",
            "QLineEdit",
            "QComboBox",
            "QSlider",
            "QMenu",
            "QDialog",
            "QDialogButtonBox",
            "QMessageBox",
            "QDoubleSpinBox",
            "QTableView",
            "QAbstractItemView",
            "QToolButton",
            "QTabWidget",
            "QSpinBox",
            "QCheckBox",
            "QFormLayout",
            "QStyle",
        ],
    )

    qt_gui = _build_module(
        "PySide6.QtGui",
        [
            "QPixmap",
            "QFont",
            "QPdfWriter",
            "QPainter",
            "QPageSize",
            "QStandardItemModel",
            "QStandardItem",
        ],
    )

    qt_module.QtCore = qt_core
    qt_module.QtWidgets = qt_widgets
    qt_module.QtGui = qt_gui

    sys.modules["PySide6"] = qt_module
    sys.modules["PySide6.QtCore"] = qt_core
    sys.modules["PySide6.QtWidgets"] = qt_widgets
    sys.modules["PySide6.QtGui"] = qt_gui


def _install_dummy_pil():
    if "PIL" in sys.modules:
        return

    pil_module = types.ModuleType("PIL")
    image_module = types.ModuleType("PIL.Image")
    image_draw_module = types.ModuleType("PIL.ImageDraw")
    image_font_module = types.ModuleType("PIL.ImageFont")

    for mod in (image_module, image_draw_module, image_font_module):
        mod.new = lambda *args, **kwargs: None

    pil_module.Image = image_module
    pil_module.ImageDraw = image_draw_module
    pil_module.ImageFont = image_font_module

    sys.modules["PIL"] = pil_module
    sys.modules["PIL.Image"] = image_module
    sys.modules["PIL.ImageDraw"] = image_draw_module
    sys.modules["PIL.ImageFont"] = image_font_module


_install_dummy_requests()
_install_dummy_pgeocode()
_install_dummy_qt()
_install_dummy_pil()

from main import AuctionBrowser


class DummyBrowser:
    def __init__(self, coords=(0.0, 0.0)):
        self._coords = coords

    def get_search_coordinates(self):
        return self._coords


class CalculateDistanceTests(unittest.TestCase):
    def test_accepts_string_coordinates(self):
        browser = DummyBrowser(coords=(34.0, -118.0))
        marker = {"lat": "34.05", "lng": "-118.25"}

        distance = AuctionBrowser.calculate_distance_miles(browser, marker)

        self.assertIsInstance(distance, float)
        self.assertFalse(math.isnan(distance))

    def test_invalid_coordinates_return_none(self):
        browser = DummyBrowser(coords=(34.0, -118.0))
        marker = {"lat": "invalid", "lng": "-118.25"}

        distance = AuctionBrowser.calculate_distance_miles(browser, marker)

        self.assertIsNone(distance)


if __name__ == "__main__":
    unittest.main()
