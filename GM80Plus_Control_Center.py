"""
Aigo GM80 Plus Control Center — Direct YJX-CHIP Hardware Control (v2)
=====================================================================
Reverse-engineered & verified LIVE on hardware (Aigo GM80 Plus, YJX-CHIP, PAW3311):
  - Supported USB HID Devices (Vendor Interface MI_02, UsagePage=0xFF01, Usage=0x0010):
      * Wired Mode:    VID_A8A4 & PID_2255 (or PID_2256)
      * 2.4G Wireless: VID_A8A5 & PID_2255
  - Real 65-Byte HID Output / Input Protocol (from DeviceDriver.exe @ 0x439220):
      * TX[0] = 0x00 (Report ID), TX[1] = 0x55 (Magic), TX[2] = Cmd, TX[3] = 0xA5/0xAE
      * TX[4] = Checksum = sum(TX[5..64]) & 0xFF, RX[0] = 0xAA (Hardware ACK)
  - Verified Commands: 0x03 (FW), 0x0E/0x0F (Config), 0x22 (DPI), 0x23 (Rate),
    0x08/0x09 (Buttons), 0x30 (Live Battery Telemetry).
"""

import ctypes
import json
import os
import random
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import winreg
from ctypes import wintypes

import hid
from PIL import Image, ImageFilter, ImageOps
from PySide6.QtCore import (
    Property,
    QByteArray,
    QEasingCurve,
    QEvent,
    QFileInfo,
    QObject,
    QPointF,
    QPropertyAnimation,
    QRectF,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QImage,
    QLinearGradient,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QButtonGroup,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFileIconProvider,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QStackedWidget,
    QStyle,
    QStyleOptionSpinBox,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

# ============================================================================
# HARDWARE CONSTANTS (VERIFIED LIVE ON AIGO GM80 PLUS)
# ============================================================================
VID_WIRED = 0xA8A4
VID_WIRELESS = 0xA8A5
VALID_PIDS = (0x2255, 0x2256)
VENDOR_USAGE_PAGE = 0xFF01
VENDOR_USAGE = 0x0010

ORIGINAL_DB_PATH = os.path.expandvars(r"%LOCALAPPDATA%\GamingMouse Files\db\mouse_data.db")

# Exact GM80 Plus Manual DPI Stages & Bottom LED Colors
DEFAULT_DPI_VALUES = [800, 1200, 1600, 3200, 5000, 12000]
DEFAULT_DPI_COLORS = [
    "#FF0000",  # الدرجة 1 (800 DPI)   - أحمر
    "#00FF00",  # الدرجة 2 (1200 DPI)  - أخضر
    "#0000FF",  # الدرجة 3 (1600 DPI)  - أزرق
    "#FFFF00",  # الدرجة 4 (3200 DPI)  - أصفر
    "#00FFFF",  # الدرجة 5 (5000 DPI)  - سماوي
    "#800080",  # الدرجة 6 (12000 DPI) - بنفسجي
]
DPI_COLOR_NAMES_AR = ["أحمر", "أخضر", "أزرق", "أصفر", "سماوي", "بنفسجي"]
DPI_COLOR_NAMES_EN = ["Red", "Green", "Blue", "Yellow", "Cyan", "Purple"]

# Auto Battery Polling Interval Options: (seconds, Arabic label, English label)
BAT_POLL_OPTIONS = [
    (0,   "يدوي فقط",     "Manual Only"),
    (10,  "كل 10 ثواني",  "Every 10s"),
    (30,  "كل 30 ثانية",  "Every 30s"),
    (60,  "كل 1 دقيقة",   "Every 1 min"),
    (180, "كل 3 دقائق",   "Every 3 min"),
    (300, "كل 5 دقائق",   "Every 5 min"),
    (600, "كل 10 دقائق",  "Every 10 min"),
]

MUTEX_NAME = "Local\\AigoGM80PlusControlCenter_SingleInstance_Mutex"
SHOW_WINDOW_MSG_NAME = "AigoGM80PlusControlCenter_ShowWindow_Msg"
GAME_POLL_INTERVAL_MS = 1500

WALLPAPER_MODES = ("none", "static", "slideshow", "animated")
WALLPAPER_FIT_MODES = ("smart_fill", "fit", "stretch", "center", "tile")
WALLPAPER_FOCUS_MODES = ("top", "center", "bottom")
BATTERY_STYLES = ("classic", "pill", "ring", "vertical", "segmented")
WALLPAPER_INTERVAL_OPTIONS = [
    (10,   "كل 10 ثواني",  "Every 10s"),
    (30,   "كل 30 ثانية",  "Every 30s"),
    (60,   "كل 1 دقيقة",   "Every 1 min"),
    (180,  "كل 3 دقائق",   "Every 3 min"),
    (300,  "كل 5 دقائق",   "Every 5 min"),
    (600,  "كل 10 دقائق",  "Every 10 min"),
    (1800, "كل 30 دقيقة",  "Every 30 min"),
]
WALLPAPER_ALL_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif")
WALLPAPER_MAX_DIMENSION = 3840
WALLPAPER_RESIZE_DEBOUNCE_MS = 140
WALLPAPER_CACHE_LIMIT = 12
WALLPAPER_MOVIE_CACHE_LIMIT = 120

DEFAULT_SETTINGS = {
    "language": "ar",
    "theme_mode": "dark",
    "accent_color": "#3B82F6",
    "run_in_background": False,
    "battery_poll_seconds": 180,
    "battery_style": "classic",
    "battery_tray_style": True,
    "custom_icon": "",
    "wallpaper_mode": "none",
    "wallpaper_file": "",
    "wallpaper_fit": "smart_fill",
    "wallpaper_focus": "center",
    "wallpaper_dim": 30,
    "wallpaper_blur": 0,
    "wallpaper_panel_opacity": 90,
    "wallpaper_interval_sec": 60,
    "wallpaper_shuffle": False,
    "wallpaper_animation": True,
    "game_exit_delay_sec": 30,
    "default_profile": {
        "dpi_stage": 2,
        "polling_rate": "500 Hz",
    },
    "game_profiles": [],
}

# Verified 1-based YJX-CHIP Polling Rate Codes (from DeviceDriver.exe @ 0x4198fd & 0x41a8b2):
#   1 = 125 Hz, 2 = 250 Hz, 3 = 500 Hz, 4 = 1000 Hz
POLLING_RATES = {
    "125 Hz": 1,
    "250 Hz": 2,
    "500 Hz": 3,   # Default 500Hz
    "1000 Hz": 4,
}
POLLING_RATE_FROM_CODE = {v: k for k, v in POLLING_RATES.items()}

# Hot-plug device switch monitor interval (2.5 seconds, zero HID traffic — only USB list check!)
HOTPLUG_CHECK_INTERVAL_MS = 2500

# Verified YJX-CHIP 4-byte Button Action Codes (100% matched to official DeviceDriver.exe KeyEncode 0x410f90)
BUTTON_PRESETS = [
    ("كليك شمال (Left-Click)",              (0x20, 0x01, 0x00, 0x00)),
    ("كليك يمين (Right-Click)",             (0x20, 0x02, 0x00, 0x00)),
    ("كليك البكرة (Middle-Click)",          (0x20, 0x04, 0x00, 0x00)),
    ("تقدم للأمام (Forward)",               (0x20, 0x10, 0x00, 0x00)),
    ("رجوع للخلف (Backward)",               (0x20, 0x08, 0x00, 0x00)),
    ("دبل كليك يسار (Double-Click)",        (0x20, 0x01, 0x02, 0x00)),
    ("تمرير لأعلى (Scroll Up)",             (0x21, 0x38, 0x01, 0x00)),
    ("تمرير لأسفل (Scroll Down)",           (0x21, 0x38, 0xFF, 0x00)),
    ("زيادة الـ DPI (DPI +)",               (0xF0, 0x01, 0x01, 0x00)),
    ("تقليل الـ DPI (DPI -)",               (0xF0, 0x01, 0x02, 0x00)),
    ("تبديل الـ DPI (DPI Loop)",            (0xF0, 0x01, 0x03, 0x00)),
    ("زيادة الهرتز (Report Rate +)",        (0xF0, 0x02, 0x01, 0x00)),
    ("تقليل الهرتز (Report Rate -)",        (0xF0, 0x02, 0x02, 0x00)),
    ("تبديل الهرتز (Report Rate Loop)",     (0xF0, 0x02, 0x03, 0x00)),
    ("تشغيل / إيقاف (Play / Pause)",        (0x30, 0xCD, 0x00, 0x00)),
    ("إيقاف التشغيل (Stop)",                (0x30, 0xB7, 0x00, 0x00)),
    ("المقطع السابق (Previous Track)",      (0x30, 0xB6, 0x00, 0x00)),
    ("المقطع التالي (Next Track)",          (0x30, 0xB5, 0x00, 0x00)),
    ("رفع الصوت (Volume +)",                (0x30, 0xE9, 0x00, 0x00)),
    ("خفض الصوت (Volume -)",                (0x30, 0xEA, 0x00, 0x00)),
    ("كتم الصوت (Mute)",                    (0x30, 0xE2, 0x00, 0x00)),
    ("نسخ (Ctrl + C)",                      (0x10, 0x01, 0x06, 0x00)),
    ("لصق (Ctrl + V)",                      (0x10, 0x01, 0x19, 0x00)),
    ("قص (Ctrl + X)",                       (0x10, 0x01, 0x1B, 0x00)),
    ("إظهار سطح المكتب (Win + D)",          (0x10, 0x08, 0x07, 0x00)),
    ("جهاز الكمبيوتر (Win + E)",            (0x10, 0x08, 0x08, 0x00)),
    ("لقطة شاشة (Win + PrtSc)",             (0x10, 0x08, 0x46, 0x00)),
    ("تبديل النوافذ (Alt + Tab)",           (0x10, 0x04, 0x2B, 0x00)),
    ("تحديث الصفحة (F5)",                   (0x10, 0x00, 0x3E, 0x00)),
    ("الآلة الحاسبة (Calculator)",          (0x30, 0x92, 0x01, 0x00)),
    ("تعطيل الزر (Disabled)",               (0x00, 0x00, 0x00, 0x00)),
]
BUTTON_PRESETS_EN = [
    "Left-Click",
    "Right-Click",
    "Middle-Click",
    "Forward",
    "Backward",
    "Double-Click",
    "Scroll Up",
    "Scroll Down",
    "DPI +",
    "DPI -",
    "DPI Loop",
    "Report Rate +",
    "Report Rate -",
    "Report Rate Loop",
    "Play / Pause",
    "Stop Playback",
    "Previous Track",
    "Next Track",
    "Volume +",
    "Volume -",
    "Mute",
    "Copy (Ctrl + C)",
    "Paste (Ctrl + V)",
    "Cut (Ctrl + X)",
    "Show Desktop (Win + D)",
    "My Computer (Win + E)",
    "Screenshot (Win + PrtSc)",
    "Switch Apps (Alt + Tab)",
    "Refresh (F5)",
    "Calculator",
    "Disabled",
]
BUTTON_NAME_BY_CODE = {code: name for name, code in BUTTON_PRESETS}
BUTTON_CODE_BY_NAME = {name: code for name, code in BUTTON_PRESETS}
BUTTON_INDEX_BY_CODE = {code: idx for idx, (_, code) in enumerate(BUTTON_PRESETS)}
BUTTON_DISABLED_INDEX = len(BUTTON_PRESETS) - 1

# Exact 8-slot hardware Bank 0 table (CMD 0x08 / 0x09, matching DeviceDriver.exe 0x42b708)
# NOTE: Hardware slot 5 (0x21 0x55 0x00 0x00) is NOT wired/remappable on Aigo GM80 Plus and is always preserved.
DEFAULT_BUTTON_CODES = [
    (0x20, 0x01, 0x00, 0x00),  # HW slot 0: Left-Click
    (0x20, 0x02, 0x00, 0x00),  # HW slot 1: Right-Click
    (0x20, 0x04, 0x00, 0x00),  # HW slot 2: Middle-Click
    (0x20, 0x08, 0x00, 0x00),  # HW slot 3: Backward (Rear Side Button)
    (0x20, 0x10, 0x00, 0x00),  # HW slot 4: Forward (Front Side Button)
    (0x21, 0x55, 0x00, 0x00),  # HW slot 5: Fixed non-remappable DPI placeholder (preserved)
    (0x21, 0x38, 0x01, 0x00),  # HW slot 6: Scroll Up
    (0x21, 0x38, 0xFF, 0x00),  # HW slot 7: Scroll Down
]

# Official 7 remappable UI buttons (1..7) mapped to their exact hardware slots in CMD 0x08 / 0x09
UI_BUTTON_HW_SLOTS = (0, 1, 2, 4, 3, 6, 7)

# Official DeviceDriver.exe Disabled (macro_type=0x12) 4-byte encoding per hardware slot
DISABLED_CODE_BY_HW_SLOT = {
    0: (0x00, 0x01, 0x00, 0x00),
    1: (0x00, 0x02, 0x00, 0x00),
    2: (0x00, 0x04, 0x00, 0x00),
    3: (0x00, 0x08, 0x00, 0x00),
    4: (0x00, 0x10, 0x00, 0x00),
    6: (0x00, 0x38, 0x01, 0x00),
    7: (0x00, 0x38, 0xFF, 0x00),
}


def preset_index_for_hw_code(code: tuple[int, int, int, int], fallback_ui_idx: int) -> int:
    """Resolve a 4-byte hardware button code to its BUTTON_PRESETS index (handles Disabled 0x00..)."""
    if code and code[0] == 0x00:
        return BUTTON_DISABLED_INDEX
    if code in BUTTON_INDEX_BY_CODE:
        return BUTTON_INDEX_BY_CODE[code]
    hw_slot = UI_BUTTON_HW_SLOTS[fallback_ui_idx] if 0 <= fallback_ui_idx < len(UI_BUTTON_HW_SLOTS) else 0
    return BUTTON_INDEX_BY_CODE.get(DEFAULT_BUTTON_CODES[hw_slot], 0)


def _log_warn(msg: str):
    """Forward warnings from top-level helpers to APP_LOG once initialized (never raises)."""
    logger = globals().get("APP_LOG")
    if logger is not None:
        logger.warn(msg)


_USER_DATA_DIR_CACHE: str | None = None
_USER_DATA_INIT_DONE = False


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _is_dir_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, f".gm80_probe_{os.getpid()}")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


def get_data_dir() -> str:
    """
    Writable user data directory for settings.json, wallpapers/, game_icons/, and logs.
    Uses the folder next to the exe/script when writable (portable mode), otherwise %APPDATA%\\GM80PlusControl.
    """
    global _USER_DATA_DIR_CACHE
    if _USER_DATA_DIR_CACHE:
        return _USER_DATA_DIR_CACHE
    base = get_base_dir()
    if _is_dir_writable(base):
        _USER_DATA_DIR_CACHE = base
    else:
        appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
        fallback = os.path.join(appdata, "GM80PlusControl")
        os.makedirs(fallback, exist_ok=True)
        _USER_DATA_DIR_CACHE = fallback
    return _USER_DATA_DIR_CACHE


def ensure_user_data_initialized():
    """First-run setup: ensure writable subfolders exist, migrate settings.json, and copy default wallpapers."""
    global _USER_DATA_INIT_DONE
    if _USER_DATA_INIT_DONE:
        return
    _USER_DATA_INIT_DONE = True
    data_dir = get_data_dir()
    wp_dir = os.path.join(data_dir, "wallpapers")
    gi_dir = os.path.join(data_dir, "game_icons")
    os.makedirs(wp_dir, exist_ok=True)
    os.makedirs(gi_dir, exist_ok=True)

    # Migrate existing settings.json next to exe if we had to fall back to %APPDATA%
    base_dir = get_base_dir()
    if os.path.abspath(data_dir) != os.path.abspath(base_dir):
        src_cfg = os.path.join(base_dir, "settings.json")
        dst_cfg = os.path.join(data_dir, "settings.json")
        if os.path.exists(src_cfg) and not os.path.exists(dst_cfg):
            try:
                shutil.copy2(src_cfg, dst_cfg)
            except Exception as ex:
                _log_warn(f"Settings migration skipped: {ex}")

    # First-run copy of any bundled default wallpapers if user wallpapers folder is empty
    try:
        has_any_wp = any(
            os.path.splitext(f)[1].lower() in WALLPAPER_ALL_EXTS
            for f in os.listdir(wp_dir)
            if os.path.isfile(os.path.join(wp_dir, f))
        )
        if not has_any_wp:
            for cand_name in ("default_wallpapers", "wallpapers"):
                bundled_dir = get_resource_path(cand_name)
                if os.path.isdir(bundled_dir) and os.path.abspath(bundled_dir) != os.path.abspath(wp_dir):
                    for fn in os.listdir(bundled_dir):
                        src_f = os.path.join(bundled_dir, fn)
                        if os.path.isfile(src_f) and os.path.splitext(fn)[1].lower() in WALLPAPER_ALL_EXTS:
                            shutil.copy2(src_f, os.path.join(wp_dir, fn))
                    break
    except Exception as ex:
        _log_warn(f"Default wallpaper copy skipped: {ex}")


def get_resource_path(rel_path: str) -> str:
    """Resolve read-only bundled assets (fonts/, app_icon.ico, defaults) from source or PyInstaller bundle."""
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, rel_path)
        if os.path.exists(bundled):
            return bundled
    ext = os.path.join(get_base_dir(), rel_path)
    if os.path.exists(ext):
        return ext
    return ext


def detect_conflicting_processes() -> list[str]:
    found = []
    try:
        out = subprocess.check_output(
            ["tasklist", "/NH"],
            creationflags=subprocess.CREATE_NO_WINDOW,
            text=True,
            errors="ignore",
        )
        for p in ("DeviceDriver.exe", "GamingMS.exe"):
            if p.lower() in out.lower():
                found.append(p)
    except Exception as ex:
        _log_warn(f"Conflict process scan skipped: {ex}")
    return found


def close_conflicting_processes():
    for p in ("DeviceDriver.exe", "GamingMS.exe"):
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", p],
                creationflags=subprocess.CREATE_NO_WINDOW,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception as ex:
            _log_warn(f"Failed to terminate {p}: {ex}")


def percent_to_voltage(pct: int) -> float:
    p = max(0, min(100, pct)) / 100.0
    return round(3.30 + 0.90 * (p ** 0.85), 2)


def hex_to_colorref(hx: str) -> int:
    h = hx.lstrip("#")
    if len(h) != 6:
        return 0xFFFFFF
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def colorref_to_hex(val: int) -> str:
    return f"#{val & 0xFF:02X}{(val >> 8) & 0xFF:02X}{(val >> 16) & 0xFF:02X}"


def get_settings_path() -> str:
    ensure_user_data_initialized()
    return os.path.join(get_data_dir(), "settings.json")


def load_settings() -> dict:
    """Load settings.json with safe defaults while preserving any unknown/legacy keys."""
    cfg = {}
    p = get_settings_path()
    loaded = None
    if os.path.exists(p):
        try:
            with open(p, encoding="utf-8") as fh:
                raw = json.load(fh)
            if isinstance(raw, dict):
                loaded = raw
                cfg.update(raw)  # Preserve unknown/legacy keys intact
        except Exception:
            loaded = None

    # Apply safe defaults for known keys
    cfg["language"] = loaded.get("language") if (loaded and loaded.get("language") in ("ar", "en")) else DEFAULT_SETTINGS["language"]
    cfg["theme_mode"] = (
        loaded.get("theme_mode")
        if (loaded and loaded.get("theme_mode") in ("dark", "light", "system"))
        else DEFAULT_SETTINGS["theme_mode"]
    )
    raw_accent = loaded.get("accent_color") if loaded else None
    if isinstance(raw_accent, str) and re.fullmatch(r"#[0-9A-Fa-f]{6}", raw_accent.strip()):
        cfg["accent_color"] = raw_accent.strip().upper()
    else:
        cfg["accent_color"] = DEFAULT_SETTINGS["accent_color"]

    cfg["run_in_background"] = (
        loaded["run_in_background"]
        if (loaded and isinstance(loaded.get("run_in_background"), bool))
        else DEFAULT_SETTINGS["run_in_background"]
    )
    cfg["battery_poll_seconds"] = (
        loaded["battery_poll_seconds"]
        if (loaded and isinstance(loaded.get("battery_poll_seconds"), int) and not isinstance(loaded.get("battery_poll_seconds"), bool) and loaded["battery_poll_seconds"] >= 0)
        else DEFAULT_SETTINGS["battery_poll_seconds"]
    )
    cfg["battery_style"] = (
        loaded["battery_style"]
        if (loaded and loaded.get("battery_style") in BATTERY_STYLES)
        else DEFAULT_SETTINGS["battery_style"]
    )
    cfg["battery_tray_style"] = (
        loaded["battery_tray_style"]
        if (loaded and isinstance(loaded.get("battery_tray_style"), bool))
        else DEFAULT_SETTINGS["battery_tray_style"]
    )
    cfg["custom_icon"] = (
        loaded["custom_icon"]
        if (loaded and isinstance(loaded.get("custom_icon"), str))
        else DEFAULT_SETTINGS["custom_icon"]
    )
    # Wallpaper settings (safe defaults, backward compatible)
    cfg["wallpaper_mode"] = (
        loaded["wallpaper_mode"]
        if (loaded and loaded.get("wallpaper_mode") in WALLPAPER_MODES)
        else DEFAULT_SETTINGS["wallpaper_mode"]
    )
    cfg["wallpaper_file"] = (
        loaded["wallpaper_file"]
        if (loaded and isinstance(loaded.get("wallpaper_file"), str))
        else DEFAULT_SETTINGS["wallpaper_file"]
    )
    cfg["wallpaper_fit"] = (
        loaded["wallpaper_fit"]
        if (loaded and loaded.get("wallpaper_fit") in WALLPAPER_FIT_MODES)
        else DEFAULT_SETTINGS["wallpaper_fit"]
    )
    cfg["wallpaper_focus"] = (
        loaded["wallpaper_focus"]
        if (loaded and loaded.get("wallpaper_focus") in WALLPAPER_FOCUS_MODES)
        else DEFAULT_SETTINGS["wallpaper_focus"]
    )
    raw_dim = loaded.get("wallpaper_dim") if loaded else None
    cfg["wallpaper_dim"] = (
        max(0, min(80, raw_dim))
        if (isinstance(raw_dim, int) and not isinstance(raw_dim, bool))
        else DEFAULT_SETTINGS["wallpaper_dim"]
    )
    raw_blur = loaded.get("wallpaper_blur") if loaded else None
    cfg["wallpaper_blur"] = (
        max(0, min(20, raw_blur))
        if (isinstance(raw_blur, int) and not isinstance(raw_blur, bool))
        else DEFAULT_SETTINGS["wallpaper_blur"]
    )
    raw_op = loaded.get("wallpaper_panel_opacity") if loaded else None
    cfg["wallpaper_panel_opacity"] = (
        max(55, min(100, raw_op))
        if (isinstance(raw_op, int) and not isinstance(raw_op, bool))
        else DEFAULT_SETTINGS["wallpaper_panel_opacity"]
    )
    raw_iv = loaded.get("wallpaper_interval_sec") if loaded else None
    cfg["wallpaper_interval_sec"] = (
        max(10, min(1800, raw_iv))
        if (isinstance(raw_iv, int) and not isinstance(raw_iv, bool))
        else DEFAULT_SETTINGS["wallpaper_interval_sec"]
    )
    cfg["wallpaper_shuffle"] = (
        loaded["wallpaper_shuffle"]
        if (loaded and isinstance(loaded.get("wallpaper_shuffle"), bool))
        else DEFAULT_SETTINGS["wallpaper_shuffle"]
    )
    cfg["wallpaper_animation"] = (
        loaded["wallpaper_animation"]
        if (loaded and isinstance(loaded.get("wallpaper_animation"), bool))
        else DEFAULT_SETTINGS["wallpaper_animation"]
    )

    raw_delay = loaded.get("game_exit_delay_sec") if loaded else None
    if isinstance(raw_delay, int) and not isinstance(raw_delay, bool):
        cfg["game_exit_delay_sec"] = max(0, min(300, raw_delay))
    else:
        cfg["game_exit_delay_sec"] = DEFAULT_SETTINGS["game_exit_delay_sec"]

    dp_out = dict(DEFAULT_SETTINGS["default_profile"])
    dp = loaded.get("default_profile") if loaded else None
    if isinstance(dp, dict):
        st = dp.get("dpi_stage")
        pr = dp.get("polling_rate")
        if isinstance(st, int) and not isinstance(st, bool) and 0 <= st <= 5:
            dp_out["dpi_stage"] = st
        if pr in POLLING_RATES:
            dp_out["polling_rate"] = pr
    cfg["default_profile"] = dp_out

    valid_gps = []
    gps = loaded.get("game_profiles") if loaded else None
    if isinstance(gps, list):
        for item in gps:
            if not isinstance(item, dict):
                continue
            exe_name = str(item.get("exe_name", "")).strip()
            if not exe_name:
                continue
            st = item.get("dpi_stage", 2)
            if not isinstance(st, int) or isinstance(st, bool) or not (0 <= st <= 5):
                st = 2
            pr = item.get("polling_rate", "1000 Hz")
            if pr not in POLLING_RATES:
                pr = "1000 Hz"
            valid_gps.append({
                "id": str(item.get("id") or uuid.uuid4().hex[:10]),
                "name": str(item.get("name") or os.path.splitext(exe_name)[0]).strip(),
                "exe_name": exe_name,
                "exe_path": str(item.get("exe_path", "")),
                "icon_file": str(item.get("icon_file", "")),
                "dpi_stage": st,
                "polling_rate": pr,
                "enabled": bool(item.get("enabled", True)),
            })
    cfg["game_profiles"] = valid_gps
    return cfg


def get_game_icons_dir() -> str:
    ensure_user_data_initialized()
    d = os.path.join(get_data_dir(), "game_icons")
    os.makedirs(d, exist_ok=True)
    return d


def get_wallpapers_dir() -> str:
    ensure_user_data_initialized()
    d = os.path.join(get_data_dir(), "wallpapers")
    os.makedirs(d, exist_ok=True)
    return d


def is_animated_image_file(path: str) -> bool:
    """Return True if path is a GIF or multi-frame animated WebP."""
    if not path or not os.path.exists(path):
        return False
    ext = os.path.splitext(path)[1].lower()
    if ext == ".gif":
        return True
    if ext == ".webp":
        try:
            with Image.open(path) as im:
                return bool(getattr(im, "is_animated", False) and getattr(im, "n_frames", 1) > 1)
        except Exception:
            return False
    return False


def list_wallpaper_files(only_animated: bool = False) -> list[str]:
    """List sorted full paths of supported wallpaper images inside wallpapers/."""
    wp_dir = get_wallpapers_dir()
    found = []
    try:
        for entry in os.listdir(wp_dir):
            full = os.path.join(wp_dir, entry)
            if not os.path.isfile(full):
                continue
            ext = os.path.splitext(entry)[1].lower()
            if ext not in WALLPAPER_ALL_EXTS:
                continue
            if only_animated:
                if ext in (".gif", ".webp") and is_animated_image_file(full):
                    found.append(full)
            else:
                found.append(full)
    except Exception as ex:
        _log_warn(f"Failed to scan wallpapers folder: {ex}")
    return sorted(found, key=lambda p: os.path.basename(p).lower())


def resolve_wallpaper_path(name_or_path: str) -> str:
    """Resolve a stored wallpaper filename or path cleanly for both source and PyInstaller runs."""
    if not name_or_path:
        return ""
    if os.path.isabs(name_or_path) and os.path.exists(name_or_path):
        return name_or_path
    cand = os.path.join(get_wallpapers_dir(), os.path.basename(name_or_path))
    if os.path.exists(cand):
        return cand
    res = get_resource_path(os.path.join("wallpapers", os.path.basename(name_or_path)))
    return res if os.path.exists(res) else ""


class _ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", wintypes.HBITMAP),
        ("hbmColor", wintypes.HBITMAP),
    ]


class _BITMAP(ctypes.Structure):
    _fields_ = [
        ("bmType", wintypes.LONG),
        ("bmWidth", wintypes.LONG),
        ("bmHeight", wintypes.LONG),
        ("bmWidthBytes", wintypes.LONG),
        ("bmPlanes", wintypes.WORD),
        ("bmBitsPixel", wintypes.WORD),
        ("bmBits", ctypes.c_void_p),
    ]


class _BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


def _hicon_to_pil_rgba(hicon) -> Image.Image | None:
    """Convert Win32 HICON to crisp RGBA PIL Image preserving full alpha transparency."""
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    user32.GetIconInfo.argtypes = [wintypes.HICON, ctypes.POINTER(_ICONINFO)]
    user32.GetIconInfo.restype = wintypes.BOOL
    gdi32.GetObjectW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p]
    gdi32.GetObjectW.restype = ctypes.c_int
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]

    ii = _ICONINFO()
    if not user32.GetIconInfo(hicon, ctypes.byref(ii)):
        return None
    hdc = user32.GetDC(None)
    try:
        if not ii.hbmColor:
            return None
        bmp = _BITMAP()
        if not gdi32.GetObjectW(ii.hbmColor, ctypes.sizeof(_BITMAP), ctypes.byref(bmp)):
            return None
        w, h = int(bmp.bmWidth), int(bmp.bmHeight)
        if w <= 0 or h <= 0:
            return None

        bih = _BITMAPINFOHEADER()
        bih.biSize = ctypes.sizeof(_BITMAPINFOHEADER)
        bih.biWidth = w
        bih.biHeight = -h  # top-down DIB
        bih.biPlanes = 1
        bih.biBitCount = 32
        bih.biCompression = 0  # BI_RGB

        color_buf = ctypes.create_string_buffer(w * h * 4)
        if not gdi32.GetDIBits(hdc, ii.hbmColor, 0, h, color_buf, ctypes.byref(bih), 0):
            return None

        raw_bgra = bytearray(color_buf.raw)
        has_alpha = any(raw_bgra[i] != 0 for i in range(3, len(raw_bgra), 4))
        if not has_alpha and ii.hbmMask:
            mask_buf = ctypes.create_string_buffer(w * h * 4)
            if gdi32.GetDIBits(hdc, ii.hbmMask, 0, h, mask_buf, ctypes.byref(bih), 0):
                mraw = mask_buf.raw
                for px in range(w * h):
                    off = px * 4
                    # Mask pixel 0x00 = opaque, non-zero = transparent
                    raw_bgra[off + 3] = 0 if (mraw[off] or mraw[off + 1] or mraw[off + 2]) else 255
            else:
                for i in range(3, len(raw_bgra), 4):
                    raw_bgra[i] = 255

        img = Image.frombuffer("RGBA", (w, h), bytes(raw_bgra), "raw", "BGRA", 0, 1).copy()
        return img
    finally:
        if hdc:
            user32.ReleaseDC(None, hdc)
        if ii.hbmColor:
            gdi32.DeleteObject(ii.hbmColor)
        if ii.hbmMask:
            gdi32.DeleteObject(ii.hbmMask)


def extract_exe_icon_to_png(exe_path: str, dest_png_path: str) -> bool:
    """Extract highest-resolution icon (128x128 / 64x64) from a .exe using PrivateExtractIconsW -> RGBA PNG."""
    if not exe_path or not os.path.exists(exe_path):
        return False
    user32 = ctypes.windll.user32
    user32.PrivateExtractIconsW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.POINTER(wintypes.HICON), ctypes.POINTER(wintypes.UINT),
        wintypes.UINT, wintypes.UINT
    ]
    user32.PrivateExtractIconsW.restype = wintypes.UINT
    user32.DestroyIcon.argtypes = [wintypes.HICON]

    for sz in (128, 64, 48, 32):
        hicon = wintypes.HICON(0)
        icon_id = wintypes.UINT(0)
        try:
            count = user32.PrivateExtractIconsW(
                exe_path, 0, sz, sz, ctypes.byref(hicon), ctypes.byref(icon_id), 1, 0
            )
            if count > 0 and hicon.value:
                try:
                    img = _hicon_to_pil_rgba(hicon)
                    if img is not None:
                        if img.size != (128, 128):
                            img = img.resize((128, 128), Image.LANCZOS)
                        os.makedirs(os.path.dirname(dest_png_path), exist_ok=True)
                        img.save(dest_png_path, format="PNG")
                        return True
                finally:
                    user32.DestroyIcon(hicon)
        except Exception as ex:
            _log_warn(f"Icon extraction failed ({os.path.basename(exe_path)}): {ex}")
            if hicon.value:
                try:
                    user32.DestroyIcon(hicon)
                except Exception as ex2:
                    _log_warn(f"DestroyIcon cleanup warning: {ex2}")
    return False


def save_custom_game_image(src_path: str, dest_png_path: str) -> bool:
    """Save user-selected custom game image (.png/.jpg/.jpeg/.webp/.ico) cleanly to 128x128 RGBA PNG."""
    if not src_path or not os.path.exists(src_path):
        return False
    try:
        with Image.open(src_path) as im:
            rgba = im.convert("RGBA")
            w, h = rgba.size
            side = max(1, w, h)
            canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            canvas.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
            out = canvas.resize((128, 128), Image.LANCZOS)
            os.makedirs(os.path.dirname(dest_png_path), exist_ok=True)
            out.save(dest_png_path, format="PNG")
        return os.path.exists(dest_png_path)
    except Exception:
        return False


def _query_process_image_path(pid: int) -> str:
    if pid <= 0:
        return ""
    kernel32 = ctypes.windll.kernel32
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not hproc:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        sz = wintypes.DWORD(1024)
        if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(sz)):
            return buf.value
        return ""
    finally:
        kernel32.CloseHandle(hproc)


def get_foreground_exe_info() -> tuple[str, str]:
    """Return (lowercase_exe_basename, full_exe_path) for the currently active Windows foreground window."""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ("", "")
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value <= 0:
            return ("", "")
        full_path = _query_process_image_path(int(pid.value))
        if not full_path:
            return ("", "")
        return (os.path.basename(full_path).lower(), full_path)
    except Exception:
        return ("", "")


def enumerate_running_windows() -> list[dict]:
    """Return sorted list of {'title', 'exe_name', 'exe_path'} dicts for visible open Windows apps."""
    user32 = ctypes.windll.user32
    EnumProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.EnumWindows.argtypes = [EnumProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]

    my_pid = os.getpid()
    skip_exes = {
        "textinputhost.exe", "shellexperiencehost.exe", "searchhost.exe",
        "startmenuexperiencehost.exe", "lockapp.exe", "systemsettings.exe",
        "applicationframehost.exe", "explorer.exe",
    }
    seen = {}

    def _cb(hwnd, _lp):
        try:
            if not user32.IsWindowVisible(hwnd):
                return True
            tlen = user32.GetWindowTextLengthW(hwnd)
            if tlen <= 0:
                return True
            tbuf = ctypes.create_unicode_buffer(tlen + 2)
            user32.GetWindowTextW(hwnd, tbuf, tlen + 1)
            title = tbuf.value.strip()
            if not title:
                return True
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value <= 0 or pid.value == my_pid:
                return True
            full_path = _query_process_image_path(int(pid.value))
            if not full_path:
                return True
            exe_name = os.path.basename(full_path).lower()
            if exe_name in skip_exes or exe_name in seen:
                return True
            seen[exe_name] = {
                "title": title,
                "exe_name": exe_name,
                "exe_path": full_path,
            }
        except Exception as ex:
            _log_warn(f"Window enumeration entry skipped: {ex}")
        return True

    try:
        user32.EnumWindows(EnumProc(_cb), 0)
    except Exception as ex:
        _log_warn(f"EnumWindows failed: {ex}")
    return sorted(seen.values(), key=lambda x: x["title"].lower())


def save_settings(cfg: dict):
    """Atomically write settings.json via temp file + os.replace to prevent corruption."""
    target = get_settings_path()
    tmp_path = target + ".tmp"
    try:
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, target)
    except Exception as ex:
        _log_warn(f"Failed to save settings.json: {ex}")
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception as ex2:
            _log_warn(f"Failed to remove temp settings file: {ex2}")


def get_active_icon_path(custom_icon_name: str = "") -> str:
    data_dir = get_data_dir()
    if custom_icon_name:
        cand = custom_icon_name if os.path.isabs(custom_icon_name) else os.path.join(data_dir, custom_icon_name)
        if os.path.exists(cand):
            return cand
    custom_default = os.path.join(data_dir, "custom_icon.ico")
    if custom_icon_name and os.path.exists(custom_default):
        return custom_default
    p = get_resource_path("app_icon.ico")
    return p if os.path.exists(p) else ""


def convert_image_to_custom_ico(src_path: str, dest_ico_path: str) -> bool:
    """Convert selected PNG/JPG/ICO image cleanly via Pillow into a multi-size square .ico file."""
    try:
        with Image.open(src_path) as im:
            rgba = im.convert("RGBA")
            w, h = rgba.size
            side = max(1, w, h)
            square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
            square.paste(rgba, ((side - w) // 2, (side - h) // 2), rgba)
            square.save(
                dest_ico_path,
                format="ICO",
                sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
            )
        return os.path.exists(dest_ico_path)
    except Exception:
        if src_path.lower().endswith(".ico"):
            try:
                shutil.copy2(src_path, dest_ico_path)
                return True
            except Exception:
                return False
        return False


def update_desktop_shortcut_icon(icon_path: str) -> bool:
    """Update Aigo GM80 Plus Control.lnk icon on Windows Desktop and refresh shell icon cache."""
    if not icon_path or not os.path.exists(icon_path):
        return False
    ps_script = (
        "$ErrorActionPreference = 'SilentlyContinue'; "
        "$wsh = New-Object -ComObject WScript.Shell; "
        "$desktops = @([Environment]::GetFolderPath('Desktop'), (Join-Path $env:USERPROFILE 'Desktop')) | Select-Object -Unique; "
        "$updated = $false; "
        "foreach ($d in $desktops) { "
        "  if (-not $d -or -not (Test-Path $d)) { continue }; "
        "  $lnk = Join-Path $d 'Aigo GM80 Plus Control.lnk'; "
        "  if (Test-Path $lnk) { "
        "    $s = $wsh.CreateShortcut($lnk); "
        "    $s.IconLocation = ($env:GM80_ICON_PATH + ', 0'); "
        "    $s.Save(); "
        "    $updated = $true; "
        "  } "
        "}; "
        "if ($updated) { Write-Output 'SHORTCUT_UPDATED' }"
    )
    try:
        env = os.environ.copy()
        env["GM80_ICON_PATH"] = os.path.abspath(icon_path)
        ps_exe = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"),
            "System32",
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe",
        )
        if not os.path.exists(ps_exe):
            ps_exe = "powershell"
        res = subprocess.run(
            [ps_exe, "-NoProfile", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        # Notify Windows Shell to refresh desktop icons immediately (SHCNE_ASSOCCHANGED = 0x08000000)
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception as ex:
            _log_warn(f"Shell icon refresh notify failed: {ex}")
        return "SHORTCUT_UPDATED" in (res.stdout or "")
    except Exception as ex:
        _log_warn(f"Desktop shortcut icon update failed: {ex}")
        return False


def acquire_single_instance_or_activate():
    """
    Create Windows Named Mutex to guarantee a single GUI instance.
    If an instance is already running (even hidden in system tray), signal it to restore and return None.
    """
    kernel32 = ctypes.windll.kernel32
    user32 = ctypes.windll.user32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.GetLastError.restype = wintypes.DWORD
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]

    show_msg_id = user32.RegisterWindowMessageW(SHOW_WINDOW_MSG_NAME)
    h_mutex = kernel32.CreateMutexW(None, False, MUTEX_NAME)
    last_err = kernel32.GetLastError()
    if last_err == 183:  # ERROR_ALREADY_EXISTS
        if h_mutex:
            kernel32.CloseHandle(h_mutex)
        try:
            user32.AllowSetForegroundWindow(-1)
        except Exception as ex:
            _log_warn(f"AllowSetForegroundWindow skipped: {ex}")
        # Broadcast + direct EnumWindows post so hidden tray windows always receive it
        user32.PostMessageW(0xFFFF, show_msg_id, 0, 0)
        EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        def _enum_cb(hwnd, _lp):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            if "Aigo GM80 Plus Control" in buf.value:
                user32.PostMessageW(hwnd, show_msg_id, 0, 0)
            return True

        try:
            user32.EnumWindows(EnumWindowsProc(_enum_cb), 0)
        except Exception as ex:
            _log_warn(f"Single-instance EnumWindows skipped: {ex}")
        return None
    return h_mutex


# ============================================================================
# REAL YJX-CHIP USB HID DRIVER (100% VERIFIED WITH LIVE HARDWARE ACK 0xAA)
# ============================================================================
class YJXGM80PlusDriver:
    """
    Communicates directly with Aigo GM80 Plus (YJX-CHIP) onboard flash memory.
    Automatically supports Wired (VID_A8A4) and 2.4G Wireless Dongle (VID_A8A5),
    prioritizing Wired when both are plugged in (and syncing both if both are connected).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self.connected = False
        self.wired_path = None
        self.wireless_path = None
        self.active_path = None
        self.active_vid = 0
        self.active_pid = 0
        self.is_wired = False
        self.is_wireless = False
        self.is_bluetooth = False
        self.bt_device_name = ""
        self.firmware_info = ""
        self.serial_number = ""

        # Live hardware onboard config state
        self.dpi_values = list(DEFAULT_DPI_VALUES)
        self.dpi_colors = list(DEFAULT_DPI_COLORS)
        self.active_dpi_stage = 2          # 0-based index (2 => Level 3 / 1600 DPI)
        self.polling_rate = "500 Hz"       # Default 500 Hz
        self.debounce_ms = 8               # Default 8 ms
        self.button_codes = list(DEFAULT_BUTTON_CODES)

        # Preserved raw hardware bytes from CMD 0x0E so we never corrupt factory sensor/sleep registers
        self._hw_reserved_mode = 0x03
        self._hw_reserved_scroll = 0x00
        self._hw_reserved_b49 = 0x01
        self._hw_reserved_b50 = 0x30
        self._hw_reserved_b52 = 0x01
        self._hw_reserved_b53 = 0x01
        self._hw_led_order = "RGB"

        # Battery state
        self.lang = "ar"                   # UI language: "ar" (default) or "en"
        self.battery_percent = None        # Real int 1..100 ONLY if CMD 0x30 returns valid reading
        self.battery_voltage = None
        self.battery_charging = None       # True = USB-C cable present, False = on battery, None = unknown
        self.battery_sleeping = False      # True when mouse did not answer CMD 0x30 (deep sleep)
        self.battery_raw_hex = ""          # Raw reply bytes of the last live CMD 0x30
        self.last_poll_str = ""
        self.last_ack_hex = ""
        self.low_battery_warned = False

        self.db_path = ORIGINAL_DB_PATH if os.path.exists(ORIGINAL_DB_PATH) else os.path.join(get_base_dir(), "gm80plus_local.db")
        self._load_colors_from_db()

    @staticmethod
    def build_packet(cmd: int, hdr3: int, b5: int, b6: int = 1, b7: int = 1, b8: int = 1,
                     b9: int = 0, b10: int = 0, payload: bytes = b"") -> bytes:
        """
        Exact 65-byte YJX-CHIP HID Report (verified against DeviceDriver.exe @ 0x439220):
          pkt[0] = 0x00 (Report ID)
          pkt[1] = 0x55
          pkt[2] = cmd
          pkt[3] = hdr3 (0xA5 or 0xAE)
          pkt[4] = sum(pkt[5..64]) & 0xFF
          pkt[5..10] = sub-header
          pkt[11..] = extra payload
        """
        pkt = bytearray(65)
        pkt[0] = 0x00
        pkt[1] = 0x55
        pkt[2] = cmd & 0xFF
        pkt[3] = hdr3 & 0xFF
        pkt[5] = b5 & 0xFF
        pkt[6] = b6 & 0xFF
        pkt[7] = b7 & 0xFF
        pkt[8] = b8 & 0xFF
        pkt[9] = b9 & 0xFF
        pkt[10] = b10 & 0xFF
        for i, val in enumerate(payload):
            if 11 + i < 65:
                pkt[11 + i] = val
        pkt[4] = sum(pkt[5:65]) & 0xFF
        return bytes(pkt)

    def _txrx(self, path: bytes, report65: bytes, expect_cmd: int = None, retries: int = 2) -> bytes:
        """Send 65-byte HID report and read 64-byte hardware ACK (starts with 0xAA)."""
        dev = hid.device()
        dev.open_path(path)
        try:
            for _ in range(retries):
                dev.set_nonblocking(1)
                while dev.read(65):
                    pass
                dev.set_nonblocking(0)

                written = dev.write(report65)
                if written != 65:
                    continue
                resp = dev.read(65, timeout_ms=250)
                if resp:
                    if len(resp) == 65 and resp[0] == 0x00:
                        resp = resp[1:]
                    raw = bytes(resp)
                    if len(raw) >= 4 and raw[0] == 0xAA:
                        if expect_cmd is None or raw[1] == expect_cmd:
                            self.last_ack_hex = " ".join(f"{b:02X}" for b in raw[:16])
                            return raw
                time.sleep(0.05)
            return b""
        finally:
            dev.close()

    def _detect_bluetooth_mouse(self) -> tuple[bool, str, int | None]:
        """
        Check if Aigo GM80 Plus is connected via Bluetooth LE when neither USB Cable nor 2.4G Dongle is active.
        First scans HID bus for BTHLEDEVICES, then queries Windows PnP for Bluetooth mouse & DEVPKEY_Bluetooth_Battery.
        """
        bt_found = False
        bt_name = "GM80 Plus BT"
        for d in hid.enumerate():
            p_raw = d.get("path", b"")
            p_str = p_raw.decode("ascii", errors="ignore").upper() if isinstance(p_raw, bytes) else str(p_raw).upper()
            prod = (d.get("product_string") or "").strip()
            if ("BTHLE" in p_str or "BTHENUM" in p_str or "{00001812-" in p_str) and (
                "GM80" in prod.upper() or "MOUSE" in prod.upper() or "AIGO" in prod.upper() or d.get("usage_page") == 0x01 and d.get("usage") == 0x02
            ):
                bt_found = True
                if prod:
                    bt_name = prod
                break

        # Query Windows PnP via PowerShell for connected Bluetooth Mouse and battery level
        ps_cmd = (
            "$devs = Get-PnpDevice -Status OK -ErrorAction SilentlyContinue | "
            "Where-Object { ($_.InstanceId -match '^BTHLE|^BTHENUM|1812') -and "
            "($_.FriendlyName -match 'GM80|Aigo|Mouse|ماوس' -or $_.Class -eq 'Mouse' -or $_.Class -eq 'HIDClass') }; "
            "foreach ($d in $devs) { "
            "  $b = Get-PnpDeviceProperty -InstanceId $d.InstanceId -KeyName '{104EA319-6EE2-4701-BD47-8DDBF425BBE5} 2' -ErrorAction SilentlyContinue; "
            "  if ($b -and $null -ne $b.Data) { Write-Output ('BT_BAT:' + $d.FriendlyName + ':' + $b.Data); exit } "
            "  if ($d.FriendlyName -match 'GM80|Aigo|Mouse') { Write-Output ('BT_OK:' + $d.FriendlyName) } "
            "}"
        )
        try:
            out = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", ps_cmd],
                creationflags=subprocess.CREATE_NO_WINDOW,
                text=True,
                timeout=3,
                errors="ignore",
            ).strip()
            for line in out.splitlines():
                line = line.strip()
                if line.startswith("BT_BAT:"):
                    parts = line.split(":")
                    name = parts[1] if len(parts) > 1 and parts[1] else bt_name
                    try:
                        bat = int(parts[-1])
                        if 0 <= bat <= 100:
                            return (True, name, bat)
                    except Exception:
                        return (True, name, None)
                elif line.startswith("BT_OK:"):
                    bt_found = True
                    bt_name = line.split(":", 1)[1] or bt_name
        except Exception:
            pass

        return (bt_found, bt_name, None)

    def enumerate_devices(self, check_bt_fallback: bool = False) -> bool:
        """Find Wired (A8A4), Wireless 2.4G (A8A5), or fallback to Bluetooth LE."""
        self.wired_path = None
        self.wireless_path = None
        wired_info = None
        wireless_info = None

        for d in hid.enumerate():
            vid = d.get("vendor_id", 0)
            pid = d.get("product_id", 0)
            up = d.get("usage_page", 0)
            u = d.get("usage", 0)
            if vid == VID_WIRED and pid in VALID_PIDS and up == VENDOR_USAGE_PAGE and u == VENDOR_USAGE:
                self.wired_path = d["path"]
                wired_info = d
            elif vid == VID_WIRELESS and pid in VALID_PIDS and up == VENDOR_USAGE_PAGE and u == VENDOR_USAGE:
                self.wireless_path = d["path"]
                wireless_info = d

        if self.wired_path:
            self.connected = True
            self.active_path = self.wired_path
            self.active_vid = wired_info["vendor_id"]
            self.active_pid = wired_info["product_id"]
            self.serial_number = wired_info.get("serial_number") or ""
            self.is_wired = True
            self.is_wireless = bool(self.wireless_path)
            self.is_bluetooth = False
        elif self.wireless_path:
            self.connected = True
            self.active_path = self.wireless_path
            self.active_vid = wireless_info["vendor_id"]
            self.active_pid = wireless_info["product_id"]
            self.serial_number = wireless_info.get("serial_number") or ""
            self.is_wired = False
            self.is_wireless = True
            self.is_bluetooth = False
        else:
            self.active_path = None
            self.active_vid = 0
            self.active_pid = 0
            self.is_wired = False
            self.is_wireless = False
            if check_bt_fallback:
                bt_ok, bt_name, bt_bat = self._detect_bluetooth_mouse()
                if bt_ok:
                    self.connected = True
                    self.is_bluetooth = True
                    self.bt_device_name = bt_name
                    if bt_bat is not None:
                        self.battery_percent = bt_bat
                        self.battery_voltage = percent_to_voltage(bt_bat)
                    return True
            if not self.is_bluetooth:
                self.connected = False
        return self.connected

    def connection_label(self, lang: str = None) -> str:
        lg = lang or self.lang
        if lg == "en":
            if self.is_wired and self.is_wireless:
                return f"Connected via USB Wired + 2.4G Dongle  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
            if self.is_wired:
                return f"Connected via USB Wired  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
            if self.is_wireless:
                return f"Connected via 2.4G Wireless (Dongle)  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
            if self.is_bluetooth:
                return f"Connected via Bluetooth (125Hz)  [{self.bt_device_name or 'GM80 Plus'}]"
            return "Disconnected — Please connect mouse via USB, 2.4G Dongle, or Bluetooth"
        if self.is_wired and self.is_wireless:
            return f"متصل بالسلك USB + دنجل 2.4G  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
        if self.is_wired:
            return f"متصل بالسلك مباشرة (USB Wired)  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
        if self.is_wireless:
            return f"متصل وايرلس 2.4G (Dongle)  [VID:{self.active_vid:04X} PID:{self.active_pid:04X}]"
        if self.is_bluetooth:
            return f"متصل بلوتوث (Bluetooth - 125Hz)  [{self.bt_device_name or 'GM80 Plus'}]"
        return "غير متصل — يرجى توصيل الماوس بالسلك أو دنجل 2.4G أو البلوتوث"

    def read_hardware_state(self) -> tuple[bool, str]:
        """Read LIVE settings (DPI, Active Stage, Polling Rate, Debounce, Buttons, FW) directly from mouse flash."""
        en = (self.lang == "en")
        with self.lock:
            if not self.enumerate_devices(check_bt_fallback=True):
                return (False, "Mouse is not connected." if en else "الماوس غير متصل.")
            if self.is_bluetooth or not self.active_path:
                self.polling_rate = "125 Hz"
                return (
                    True,
                    "🔵 Connected via Bluetooth (125Hz) — Running with onboard saved settings." if en
                    else "🔵 متصل بلوتوث (Bluetooth - 125Hz) — يعمل بالإعدادات المحفوظة مسبقاً في ذاكرة الماوس.",
                )

            try:
                # 1. Read Firmware Identity (CMD 0x03)
                r_fw = self._txrx(self.active_path, self.build_packet(0x03, 0xA5, 0x38), expect_cmd=0x03)
                if r_fw and len(r_fw) >= 40:
                    txt = bytes([b if 32 <= b < 127 else 32 for b in r_fw[8:44]]).decode("ascii", errors="ignore").strip()
                    self.firmware_info = " ".join(txt.split())

                # 2. Read Main Config (CMD 0x0E)
                r_cfg = self._txrx(self.active_path, self.build_packet(0x0E, 0xA5, 0x2E), expect_cmd=0x0E)
                if not r_cfg or len(r_cfg) < 54:
                    return (False, "فشل قراءة الذاكرة الداخلية للماوس (CMD 0x0E لم يُرجع ACK).")

                self._hw_reserved_mode = r_cfg[9] if r_cfg[9] > 0 else 0x03
                rate_code = r_cfg[10]
                self.polling_rate = POLLING_RATE_FROM_CODE.get(rate_code, "500 Hz")
                stage_1based = r_cfg[12]
                self.active_dpi_stage = max(0, min(5, stage_1based - 1))

                for i in range(6):
                    val = r_cfg[13 + i * 2] | (r_cfg[14 + i * 2] << 8)
                    if 200 <= val <= 26000:
                        self.dpi_values[i] = val

                self._hw_reserved_scroll = r_cfg[48]
                self._hw_reserved_b49 = r_cfg[49]
                self._hw_reserved_b50 = r_cfg[50]
                deb = r_cfg[51]
                self.debounce_ms = max(1, min(20, deb if deb > 0 else 8))
                self._hw_reserved_b52 = r_cfg[52]
                self._hw_reserved_b53 = r_cfg[53]

                # 3. Read Button Map (CMD 0x08: Bank (0,0,0) is primary factory table in 0x42b708/0x42b870, fallback Bank (1,1,1))
                r_btn = self._txrx(self.active_path, self.build_packet(0x08, 0xA5, 0x20, 0, 0, 0, 0, 0), expect_cmd=0x08)
                if not r_btn or len(r_btn) < 32 or all(b in (0xFF, 0x00) for b in r_btn[8:20]):
                    r_btn = self._txrx(self.active_path, self.build_packet(0x08, 0xA5, 0x20, 1, 1, 1, 0, 0), expect_cmd=0x08)
                if r_btn and len(r_btn) >= 40:
                    parsed = []
                    valid_any = False
                    for idx in range(8):
                        off = 8 + idx * 4
                        code = (r_btn[off], r_btn[off + 1], r_btn[off + 2], r_btn[off + 3])
                        if code != (0xFF, 0xFF, 0xFF, 0xFF) and code != (0x00, 0x00, 0x00, 0x00):
                            valid_any = True
                        parsed.append(code)
                    if valid_any:
                        parsed[5] = DEFAULT_BUTTON_CODES[5]  # Keep fixed non-remappable slot 5 intact
                        self.button_codes = parsed

                if en:
                    return (True, f"✅ Read onboard mouse memory (ACK 0xAA 0x0E) — {self.dpi_values[self.active_dpi_stage]} DPI @ {self.polling_rate} | Debounce {self.debounce_ms}ms")
                return (True, f"✅ تمت قراءة ذاكرة الماوس الحقيقية (ACK 0xAA 0x0E) — {self.dpi_values[self.active_dpi_stage]} DPI @ {self.polling_rate} | Debounce {self.debounce_ms}ms")
            except Exception as e:
                return (False, f"Error reading mouse: {e}" if en else f"خطأ أثناء قراءة الماوس: {e}")

    def poll_battery_status(self) -> tuple[bool, str]:
        """
        100% LIVE battery query — every call opens MI_02 (UP=0xFF01, U=0x0010) afresh, sends CMD 0x30
        (65 bytes), reads the live 65-byte reply and parses it. No cached / default values are ever kept:
        all battery fields are reset before each query.
        Verified reply layout: AA 30 [hdr] [chk] 0A 01 01 01 [level] 00 ... -> level (byte 8) = real percent.
        NOTE: the firmware reply carries ONLY the percent; it has no voltage field, so voltage is an
        estimate derived from the live percent (shown with '≈'). Charging state = USB-C cable present
        (wired interface enumerated) vs. on-battery (2.4G / BT).
        """
        en = (self.lang == "en")
        with self.lock:
            self.last_poll_str = time.strftime("%I:%M:%S %p")
            # Reset every battery field so nothing stale can ever be displayed
            self.battery_percent = None
            self.battery_voltage = None
            self.battery_charging = None
            self.battery_sleeping = False
            self.battery_raw_hex = ""
            ts = self.last_poll_str

            if not self.enumerate_devices(check_bt_fallback=True):
                self.battery_percent = None
                return (False, "Mouse disconnected." if en else "الماوس غير متصل.")

            # ---- Bluetooth: live percent from Windows PnP only ----
            if self.is_bluetooth:
                self.battery_percent = None
                self.battery_voltage = None
                self.battery_charging = False
                bt_ok, bt_name, bt_bat = self._detect_bluetooth_mouse()
                if bt_bat is not None:
                    self.battery_percent = bt_bat
                    self.battery_voltage = percent_to_voltage(bt_bat)
                    return (True, f"🔋 [{ts}] Bluetooth — Battery: {bt_bat}% (≈{self.battery_voltage:.2f}V, Discharging)" if en
                            else f"🔋 [{ts}] بلوتوث — البطارية: {bt_bat}% (≈{self.battery_voltage:.2f}V، تفريغ)")
                return (False, f"🔵 [{ts}] Bluetooth: Windows did not report a battery level for the mouse" if en
                        else f"🔵 [{ts}] بلوتوث: ويندوز لم يُرجع نسبة بطارية للماوس")

            # ---- USB/2.4G: live CMD 0x30 on MI_02 ----
            try:
                self.battery_charging = bool(self.wired_path)  # USB-C cable present => charging
                paths = []
                if self.wireless_path:
                    paths.append(("2.4G", self.wireless_path))
                if self.wired_path:
                    paths.append(("USB", self.wired_path))

                any_ack = False
                for label, path in paths:
                    r30 = self._txrx(path, self.build_packet(0x30, 0xA5, 0x0A), expect_cmd=0x30, retries=3)
                    if not r30 or len(r30) < 10:
                        continue
                    any_ack = True
                    self.battery_raw_hex = " ".join(f"{b:02X}" for b in r30[:16])
                    lvl = r30[8]
                    if 1 <= lvl <= 100:
                        self.battery_percent = int(lvl)
                        self.battery_voltage = percent_to_voltage(self.battery_percent)
                        state_en = "Charging (USB-C)" if self.battery_charging else "Discharging (2.4G)"
                        state_ar = "يشحن (USB-C)" if self.battery_charging else "تفريغ (2.4G)"
                        return (True, f"🔋 [{ts}] Live CMD 0x30 [{label}]: {self.battery_percent}% (≈{self.battery_voltage:.2f}V) — {state_en} | raw: {self.battery_raw_hex}" if en
                                else f"🔋 [{ts}] قراءة حية CMD 0x30 [{label}]: {self.battery_percent}% (≈{self.battery_voltage:.2f}V) — {state_ar} | raw: {self.battery_raw_hex}")

                if any_ack:
                    # Mouse replied but with no valid level (e.g. 0x00 over cable)
                    if self.wired_path:
                        return (True, f"⚡ [{ts}] USB-C cable connected — Charging (mouse reports no % over cable) | raw: {self.battery_raw_hex}" if en
                                else f"⚡ [{ts}] كابل USB-C متصل — يشحن (الماوس لا يرسل نسبة عبر السلك) | raw: {self.battery_raw_hex}")
                    return (False, f"📡 [{ts}] Mouse replied without a valid battery level | raw: {self.battery_raw_hex}" if en
                            else f"📡 [{ts}] الماوس رد بدون نسبة بطارية صالحة | raw: {self.battery_raw_hex}")

                # No reply at all -> deep sleep
                self.battery_sleeping = True
                return (False, f"😴 [{ts}] Mouse is in deep sleep — move it to refresh" if en
                        else f"😴 [{ts}] الماوس في وضع السكون — حرّكه للتحديث")
            except Exception as e:
                return (False, f"Battery check error: {e}" if en else f"خطأ في فحص البطارية: {e}")

    def reset_factory_buttons_on_hardware(self) -> tuple[bool, str]:
        """
        Immediate hardware factory button reset matching DeviceDriver.exe @ 0x42b870 + 0x42bbe0:
          1. Resets in-memory button_codes to factory defaults (Left, Right, Middle, Backward, Forward, DPI Loop).
          2. Immediately sends the exact 0x42b870 CMD 0x09 factory packet (Bank 0 + Bank 1) + CMD 0x10 commit
             + CMD 0x0F full config to onboard flash memory.
          3. Reads back CMD 0x08 & CMD 0x0E to verify factory button bytes & config in onboard flash.
        """
        self.button_codes = list(DEFAULT_BUTTON_CODES)
        ok, msg = self.apply_to_hardware(apply_buttons=True)
        if ok:
            if self.lang == "en":
                return (True, f"✅ Factory default buttons restored & saved to onboard memory! ({msg})")
            return (True, f"✅ تمت استعادة الأزرار الافتراضية للمصنع وحفظها في ذاكرة الماوس بنجاح! ({msg})")
        return (False, msg)

    def apply_polling_rate_to_hardware(self) -> tuple[bool, str]:
        """
        Apply ONLY Polling Rate immediately using exact DeviceDriver.exe protocol on MI_02 (UP=0xFF01, U=0x0010):
          1. CMD 0x23 (0x42bac0: 00 55 23 AE [chk] 03 01 01 01 00 00 [rate_code]) -> Live Polling Rate switch
          2. CMD 0x0F (0x42bbe0: 46-byte Onboard Config Commit) -> Save to onboard flash
          3. CMD 0x0E Readback verification -> Confirm r0e[10] == rate_code (1=125Hz, 2=250Hz, 3=500Hz, 4=1000Hz)
        """
        en = (self.lang == "en")
        with self.lock:
            self._save_to_db()
            if not self.enumerate_devices(check_bt_fallback=True):
                return (False, "❌ Write Failed: Mouse disconnected (connect USB or 2.4G dongle)." if en else "❌ Write Failed: الماوس غير متصل (يرجى توصيل السلك أو دنجل 2.4G).")

            if self.is_bluetooth or not self.active_path:
                return (
                    False,
                    "⚠️ Changing polling rate requires USB or 2.4G Dongle (Bluetooth is fixed at 125Hz)." if en
                    else "⚠️ تعديل معدل الاستجابة يتطلب توصيل السلك أو الدونجل 2.4G (البلوتوث يعمل على 125Hz).",
                )

            targets = []
            if self.wired_path:
                targets.append(("USB", self.wired_path))
            if self.wireless_path:
                targets.append(("2.4G", self.wireless_path))

            rate_code = POLLING_RATES.get(self.polling_rate, 3)  # 1=125Hz, 2=250Hz, 3=500Hz, 4=1000Hz
            stage_1based = max(1, min(6, self.active_dpi_stage + 1))
            mode_byte = self._hw_reserved_mode if self._hw_reserved_mode > 0 else 0x03

            # Build CMD 0x0F (exact 0x42bbe0 layout — preserves hardware reserved bytes untouched)
            payload_0f = bytearray(46)
            payload_0f[0] = 0x00
            payload_0f[1] = mode_byte
            payload_0f[2] = rate_code
            payload_0f[3] = 0x06
            payload_0f[4] = stage_1based
            for i in range(6):
                v = max(200, min(12000, int(self.dpi_values[i])))
                payload_0f[5 + i * 2] = v & 0xFF
                payload_0f[6 + i * 2] = (v >> 8) & 0xFF
            payload_0f[40] = self._hw_reserved_scroll
            payload_0f[41] = self._hw_reserved_b49
            payload_0f[42] = self._hw_reserved_b50
            payload_0f[43] = max(1, min(20, int(self.debounce_ms)))
            payload_0f[44] = self._hw_reserved_b52
            payload_0f[45] = self._hw_reserved_b53

            pkt_0f = bytearray(65)
            pkt_0f[0:9] = [0x00, 0x55, 0x0F, 0xAE, 0x00, 0x2E, 0x01, 0x01, 0x01]
            pkt_0f[9:9 + 46] = payload_0f
            pkt_0f[4] = sum(pkt_0f[5:65]) & 0xFF

            # Build CMD 0x23 (exact 0x42bac0 packet)
            pkt_23 = self.build_packet(0x23, 0xAE, 0x03, 1, 1, 1, 0, 0, payload=bytes([rate_code]))

            verified_modes = []
            errors = []
            for label, path in targets:
                try:
                    r0f = self._txrx(path, bytes(pkt_0f), expect_cmd=0x0F, retries=2)
                    r23 = self._txrx(path, pkt_23, expect_cmd=0x23, retries=2)
                    time.sleep(0.03)
                    r_verify = self._txrx(path, self.build_packet(0x0E, 0xA5, 0x2E), expect_cmd=0x0E, retries=2)
                    rate_verified = bool(r_verify and len(r_verify) >= 54 and r_verify[10] == rate_code)
                    if r0f and r23 and rate_verified:
                        verified_modes.append(label)
                    else:
                        actual_rb = r_verify[10] if (r_verify and len(r_verify) > 10) else "?"
                        errors.append(f"{label}: CMD23={bool(r23)}, r0e[10]={actual_rb}")
                except Exception as ex:
                    errors.append(f"{label}: {ex}")

            if verified_modes:
                modes_txt = " + ".join(verified_modes)
                if en:
                    return (
                        True,
                        f"✅ Applied & saved {self.polling_rate} to onboard memory "
                        f"(CMD 0x23 + 0x0F | ACK 0xAA | r0e[10]={rate_code} on {modes_txt})",
                    )
                return (
                    True,
                    f"✅ تم تطبيق وحفظ {self.polling_rate} في ذاكرة الماوس "
                    f"(CMD 0x23 + 0x0F | ACK 0xAA | r0e[10]={rate_code} على {modes_txt})",
                )
            if en:
                return (False, f"❌ Failed to set polling rate to {self.polling_rate} ({'; '.join(errors)}).")
            return (False, f"❌ فشل تغيير معدل الاستجابة إلى {self.polling_rate} ({'; '.join(errors)}).")

    def apply_profile_to_hardware(self, dpi_stage: int, polling_rate: str, profile_name: str = "") -> tuple[bool, str]:
        """
        Apply a Game Profile or Default Profile (DPI Stage + Polling Rate) cleanly via MI_02
        using verified YJX-CHIP sequence: CMD 0x0F -> CMD 0x22 -> CMD 0x23 -> CMD 0x0E readback.
        Does not touch button remapping bank (CMD 0x09).
        """
        en = (self.lang == "en")
        with self.lock:
            self.active_dpi_stage = max(0, min(5, int(dpi_stage)))
            self.polling_rate = polling_rate if polling_rate in POLLING_RATES else "500 Hz"
            self._save_to_db()

            if not self.enumerate_devices(check_bt_fallback=True):
                return (
                    False,
                    "❌ Game Profile skipped: Mouse disconnected." if en
                    else "❌ تعذر تطبيق وضع اللعبة: الماوس غير متصل."
                )

            if self.is_bluetooth or not self.active_path:
                return (
                    False,
                    "⚠️ Game Profile requires USB or 2.4G Dongle (Bluetooth runs saved onboard profile)." if en
                    else "⚠️ أوضاع الألعاب تتطلب السلك أو الدونجل 2.4G (البلوتوث يعمل بالإعدادات المحفوظة مسبقاً)."
                )

            targets = []
            if self.wired_path:
                targets.append(("USB", self.wired_path))
            if self.wireless_path:
                targets.append(("2.4G", self.wireless_path))

            rate_code = POLLING_RATES.get(self.polling_rate, 3)
            stage_1based = self.active_dpi_stage + 1
            active_dpi_val = self.dpi_values[self.active_dpi_stage]
            mode_byte = self._hw_reserved_mode if self._hw_reserved_mode > 0 else 0x03

            payload_0f = bytearray(46)
            payload_0f[0] = 0x00
            payload_0f[1] = mode_byte
            payload_0f[2] = rate_code
            payload_0f[3] = 0x06
            payload_0f[4] = stage_1based
            for i in range(6):
                v = max(200, min(12000, int(self.dpi_values[i])))
                payload_0f[5 + i * 2] = v & 0xFF
                payload_0f[6 + i * 2] = (v >> 8) & 0xFF
            payload_0f[40] = self._hw_reserved_scroll
            payload_0f[41] = self._hw_reserved_b49
            payload_0f[42] = self._hw_reserved_b50
            payload_0f[43] = max(1, min(20, int(self.debounce_ms)))
            payload_0f[44] = self._hw_reserved_b52
            payload_0f[45] = self._hw_reserved_b53

            pkt_0f = bytearray(65)
            pkt_0f[0:9] = [0x00, 0x55, 0x0F, 0xAE, 0x00, 0x2E, 0x01, 0x01, 0x01]
            pkt_0f[9:9 + 46] = payload_0f
            pkt_0f[4] = sum(pkt_0f[5:65]) & 0xFF

            pkt_22 = self.build_packet(
                0x22, 0xAE, 0x03, 1, 1, 1, 0, 0,
                payload=bytes([stage_1based, active_dpi_val & 0xFF, (active_dpi_val >> 8) & 0xFF]),
            )
            pkt_23 = self.build_packet(0x23, 0xAE, 0x03, 1, 1, 1, 0, 0, payload=bytes([rate_code]))

            verified_modes = []
            errors = []
            for label, path in targets:
                try:
                    r0f = self._txrx(path, bytes(pkt_0f), expect_cmd=0x0F, retries=2)
                    r22 = self._txrx(path, pkt_22, expect_cmd=0x22, retries=2)
                    r23 = self._txrx(path, pkt_23, expect_cmd=0x23, retries=2)
                    time.sleep(0.03)
                    r_verify = self._txrx(path, self.build_packet(0x0E, 0xA5, 0x2E), expect_cmd=0x0E, retries=2)
                    rate_ok = bool(r_verify and len(r_verify) >= 54 and r_verify[10] == rate_code)
                    stage_ok = bool(r_verify and len(r_verify) >= 54 and r_verify[12] == stage_1based)
                    if r0f and r22 and r23 and rate_ok and stage_ok:
                        verified_modes.append(label)
                    else:
                        actual_r = r_verify[10] if (r_verify and len(r_verify) > 10) else "?"
                        actual_s = r_verify[12] if (r_verify and len(r_verify) > 12) else "?"
                        errors.append(f"{label}: r0e[10]={actual_r}, r0e[12]={actual_s}")
                except Exception as ex:
                    errors.append(f"{label}: {ex}")

            tag = profile_name if profile_name else ("Default Profile" if en else "الوضع الافتراضي")
            if verified_modes:
                modes_txt = " + ".join(verified_modes)
                if en:
                    return (
                        True,
                        f"🎮 Applied [{tag}]: {active_dpi_val} DPI (Stage {stage_1based}) • {self.polling_rate} ({modes_txt})"
                    )
                return (
                    True,
                    f"🎮 تم تطبيق [{tag}]: {active_dpi_val} DPI (الدرجة {stage_1based}) • {self.polling_rate} ({modes_txt})"
                )
            if en:
                return (False, f"❌ Failed to apply [{tag}] ({'; '.join(errors)}).")
            return (False, f"❌ فشل تطبيق [{tag}] ({'; '.join(errors)}).")

    def apply_to_hardware(self, apply_buttons: bool = True) -> tuple[bool, str]:
        """
        Execute the EXACT DeviceDriver.exe Apply sequence for YJX-CHIP (device_type=101, 0x42a2f0):
          1. CMD 0x10 (0x42b650: 00 55 10 A5 22 00 00 00 05) -> Macro/Table flash commit
          2. CMD 0x09 (0x42b6b0 / 0x42b870: Bank 0 0xA5 + Bank 1 0xAE) -> 8x 4-byte button table
          3. CMD 0x0F (0x42bbe0: 46-byte Onboard Config Commit to flash)
          4. CMD 0x22 (0x42b910: 00 55 22 AE [chk] 03 01 01 01 00 00 [stage] [dpi_lo] [dpi_hi]) -> Live DPI & LED
          5. CMD 0x23 (0x42bac0: 00 55 23 AE [chk] 03 01 01 01 00 00 [rate_code]) -> Live Polling Rate trigger
          6. Mandatory Readback verification via CMD 0x0E (checks r0e[10] == rate_code) & CMD 0x08 (checks buttons).
        """
        en = (self.lang == "en")
        with self.lock:
            self._save_to_db()
            if not self.enumerate_devices(check_bt_fallback=True):
                return (False, "❌ Write Failed: Mouse disconnected (connect USB or 2.4G dongle)." if en else "❌ Write Failed: الماوس غير متصل (يرجى توصيل السلك أو دنجل 2.4G).")

            if self.is_bluetooth or not self.active_path:
                return (
                    False,
                    "⚠️ Changing settings requires USB or 2.4G Dongle (Bluetooth runs saved onboard profile at 125Hz)." if en
                    else "⚠️ تعديل الإعدادات يتطلب توصيل السلك أو الدونجل 2.4G (البلوتوث يعمل بالإعدادات المحفوظة مسبقاً على 125Hz).",
                )

            targets = []
            if self.wired_path:
                targets.append(("USB", self.wired_path))
            if self.wireless_path:
                targets.append(("2.4G", self.wireless_path))

            rate_code = POLLING_RATES.get(self.polling_rate, 3)  # 1=125Hz, 2=250Hz, 3=500Hz, 4=1000Hz
            stage_1based = max(1, min(6, self.active_dpi_stage + 1))
            active_dpi_val = self.dpi_values[self.active_dpi_stage]
            mode_byte = self._hw_reserved_mode if self._hw_reserved_mode > 0 else 0x03

            # 1. Build CMD 0x10 (0x42b650: 00 55 10 A5 22 00 00 00 05)
            pkt_10 = bytearray(65)
            pkt_10[0:9] = [0x00, 0x55, 0x10, 0xA5, 0x05, 0x00, 0x00, 0x00, 0x05]
            pkt_10[4] = sum(pkt_10[5:65]) & 0xFF

            # 2. Build CMD 0x09 (0x42b6b0 / 0x42b870) for Bank (0,0,0) and Bank (1,1,1)
            def _make_btn_pkt(hdr3_val: int, bank_val: int) -> bytes:
                p = bytearray(65)
                p[0:9] = [0x00, 0x55, 0x09, hdr3_val, 0x00, 0x20, bank_val, bank_val, bank_val]
                codes8 = list(self.button_codes)
                while len(codes8) < 8:
                    codes8.append(DEFAULT_BUTTON_CODES[len(codes8)])
                codes8[5] = DEFAULT_BUTTON_CODES[5]  # Always preserve fixed non-remappable slot 5
                for idx in range(8):
                    p[9 + idx * 4: 13 + idx * 4] = list(codes8[idx])
                p[4] = sum(p[5:65]) & 0xFF
                return bytes(p)

            pkt_09_bank0 = _make_btn_pkt(0xA5, 0x00)
            pkt_09_bank1 = _make_btn_pkt(0xAE, 0x01)

            # 3. Build CMD 0x0F (0x42bbe0: 46-byte Onboard Config Commit)
            payload_0f = bytearray(46)
            payload_0f[0] = 0x00
            payload_0f[1] = mode_byte
            payload_0f[2] = rate_code
            payload_0f[3] = 0x06
            payload_0f[4] = stage_1based
            for i in range(6):
                v = max(200, min(12000, int(self.dpi_values[i])))
                payload_0f[5 + i * 2] = v & 0xFF
                payload_0f[6 + i * 2] = (v >> 8) & 0xFF
            payload_0f[40] = self._hw_reserved_scroll
            payload_0f[41] = self._hw_reserved_b49
            payload_0f[42] = self._hw_reserved_b50
            payload_0f[43] = max(1, min(20, int(self.debounce_ms)))
            payload_0f[44] = self._hw_reserved_b52
            payload_0f[45] = self._hw_reserved_b53

            pkt_0f = bytearray(65)
            pkt_0f[0:9] = [0x00, 0x55, 0x0F, 0xAE, 0x00, 0x2E, 0x01, 0x01, 0x01]
            pkt_0f[9:9 + 46] = payload_0f
            pkt_0f[4] = sum(pkt_0f[5:65]) & 0xFF

            # 4. Build CMD 0x22 (0x42b910: Live DPI & LED stage)
            pkt_22 = self.build_packet(
                0x22, 0xAE, 0x03, 1, 1, 1, 0, 0,
                payload=bytes([stage_1based, active_dpi_val & 0xFF, (active_dpi_val >> 8) & 0xFF]),
            )

            # 5. Build CMD 0x23 (0x42bac0: Live Polling Rate switch — sent LAST as in 0x42a312!)
            pkt_23 = self.build_packet(0x23, 0xAE, 0x03, 1, 1, 1, 0, 0, payload=bytes([rate_code]))

            verified_modes = []
            errors = []
            for label, path in targets:
                try:
                    # Exact DeviceDriver.exe Apply sequence (0x42a2f0): 0x10 -> 0x09 -> 0x0F -> 0x22 -> 0x23
                    self._txrx(path, bytes(pkt_10), expect_cmd=0x10, retries=1)
                    r09_ok = True
                    if apply_buttons:
                        r09_a = self._txrx(path, pkt_09_bank0, expect_cmd=0x09, retries=2)
                        r09_b = self._txrx(path, pkt_09_bank1, expect_cmd=0x09, retries=2)
                        r09_ok = bool(r09_a and r09_b)

                    r0f = self._txrx(path, bytes(pkt_0f), expect_cmd=0x0F, retries=2)
                    r22 = self._txrx(path, pkt_22, expect_cmd=0x22, retries=2)
                    r23 = self._txrx(path, pkt_23, expect_cmd=0x23, retries=2)

                    # Mandatory Readback Verification (CMD 0x0E & CMD 0x08)
                    time.sleep(0.03)
                    r_verify = self._txrx(path, self.build_packet(0x0E, 0xA5, 0x2E), expect_cmd=0x0E, retries=2)
                    rate_verified = bool(r_verify and len(r_verify) >= 54 and r_verify[10] == rate_code)

                    btn_verified = True
                    if apply_buttons:
                        rb_chk = self._txrx(path, self.build_packet(0x08, 0xA5, 0x20, 0, 0, 0, 0, 0), expect_cmd=0x08, retries=2)
                        if rb_chk and len(rb_chk) >= 40:
                            for idx in UI_BUTTON_HW_SLOTS:
                                off = 8 + idx * 4
                                if (rb_chk[off], rb_chk[off + 1], rb_chk[off + 2], rb_chk[off + 3]) != self.button_codes[idx]:
                                    btn_verified = False
                                    break

                    if r0f and r22 and r23 and r09_ok and rate_verified and btn_verified:
                        verified_modes.append(label)
                    else:
                        actual_rate = POLLING_RATE_FROM_CODE.get(r_verify[10], f"code={r_verify[10]}") if (r_verify and len(r_verify) > 10) else "No Readback"
                        errors.append(f"{label}: Rate={actual_rate}, BtnOK={btn_verified}")
                except Exception as ex:
                    errors.append(f"{label}: {ex}")

            if verified_modes:
                modes_txt = " + ".join(verified_modes)
                if en:
                    return (
                        True,
                        f"✅ Success (Verified ACK 0xAA + Readback on {modes_txt}): Saved to onboard memory — "
                        f"Stage {stage_1based} ({active_dpi_val} DPI) | {self.polling_rate} (r0e[10]={rate_code}) | Debounce {self.debounce_ms}ms | Buttons OK",
                    )
                return (
                    True,
                    f"✅ Success (Verified ACK 0xAA + Readback على {modes_txt}): تم الحفظ في ذاكرة الماوس — "
                    f"الدرجة {stage_1based} ({active_dpi_val} DPI) | {self.polling_rate} (r0e[10]={rate_code}) | Debounce {self.debounce_ms}ms | الأزرار مطابقة",
                )
            if en:
                return (False, f"❌ Write Failed: Verification failed ({'; '.join(errors)}).")
            return (False, f"❌ Write Failed: فشل التحقق من الحفظ في الماوس ({'; '.join(errors)}).")

    def _load_colors_from_db(self):
        if not os.path.exists(self.db_path):
            return
        try:
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM t_configdata WHERE profile = 1")
            rows = dict(cur.fetchall())
            conn.close()
            if "gm80_real_colors_v3" in rows:
                for i in range(6):
                    k = f"dpi_group{i}_rgb"
                    if k in rows:
                        self.dpi_colors[i] = colorref_to_hex(int(rows[k]))
        except Exception:
            pass

    def _save_to_db(self):
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cur = conn.cursor()
            cur.execute(
                """CREATE TABLE IF NOT EXISTS t_configdata(
                    config_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    profile INTEGER, key TEXT, value TEXT
                )"""
            )
            updates = {
                "gm80_real_colors_v3": "1",
                "report_rate": str(POLLING_RATES.get(self.polling_rate, 3)),
                "button_respondtime": str(self.debounce_ms),
                "dpi_index": str(self.active_dpi_stage),
                "dpi_count": "6",
                "dpi_flag": "6",
            }
            for i in range(6):
                updates[f"dpi_group{i}_value"] = str(self.dpi_values[i])
                updates[f"dpi_group{i}_rgb"] = str(hex_to_colorref(self.dpi_colors[i]))
            for k, v in updates.items():
                cur.execute("SELECT config_id FROM t_configdata WHERE profile = 1 AND key = ?", (k,))
                row = cur.fetchone()
                if row:
                    cur.execute("UPDATE t_configdata SET value = ? WHERE config_id = ?", (v, row[0]))
                else:
                    cur.execute("INSERT INTO t_configdata (profile, key, value) VALUES (1, ?, ?)", (k, v))
            conn.commit()
            conn.close()
        except Exception:
            pass


# ============================================================================
# LOGGING & DEVELOPER LOG BRIDGE (FILE + COLLAPSIBLE UI DRAWER)
# ============================================================================
class AppLogger(QObject):
    """Lightweight logger writing bounded diagnostics to gm80_app.log and emitting to Developer Log."""
    entry_added = Signal(str)
    MAX_LINES = 400
    MAX_FILE_BYTES = 256 * 1024

    def __init__(self):
        super().__init__()
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._log_path = os.path.join(get_data_dir(), "gm80_app.log")

    def log(self, level: str, message: str):
        ts = time.strftime("%H:%M:%S")
        clean = str(message).replace("\r", " ").replace("\n", " ").strip()
        line = f"[{ts}] [{level.upper()}] {clean}"
        with self._lock:
            self._lines.append(line)
            if len(self._lines) > self.MAX_LINES:
                self._lines = self._lines[-self.MAX_LINES:]
            try:
                if os.path.exists(self._log_path) and os.path.getsize(self._log_path) > self.MAX_FILE_BYTES:
                    with open(self._log_path, encoding="utf-8", errors="ignore") as rf:
                        tail = rf.readlines()[-200:]
                    with open(self._log_path, "w", encoding="utf-8") as wf:
                        wf.writelines(tail)
                with open(self._log_path, "a", encoding="utf-8") as af:
                    af.write(line + "\n")
            except OSError:
                return
        try:
            self.entry_added.emit(line)
        except RuntimeError:
            pass

    def info(self, msg: str):
        self.log("INFO", msg)

    def hid(self, msg: str):
        self.log("HID", msg)

    def warn(self, msg: str):
        self.log("WARN", msg)

    def error(self, msg: str):
        self.log("ERR", msg)

    def snapshot(self) -> list[str]:
        with self._lock:
            return list(self._lines)

    def clear(self):
        with self._lock:
            self._lines.clear()


APP_LOG = AppLogger()


# ============================================================================
# WORKER SIGNALS FOR THREAD-SAFE UI UPDATES
# ============================================================================
class WorkerSignals(QObject):
    poll_done = Signal(bool, str)
    apply_done = Signal(bool, str)
    init_read_done = Signal(bool, str)
    game_profile_done = Signal(bool, str, str, str, bool)
    hotplug_changed = Signal(bool, bool, bool)
    conflict_found = Signal(list)
    conflict_closed = Signal()
    shortcut_icon_done = Signal(bool, bool)


# ============================================================================
# TYPOGRAPHY, BIDI ISOLATION & CENTRAL TRANSLATIONS (AR RTL / EN LTR)
# ============================================================================
LRI = "\u2066"  # Unicode Left-to-Right Isolate
PDI = "\u2069"  # Unicode Pop Directional Isolate
MONO_FONT_FAMILY = "Cascadia Mono, Consolas, Courier New"


def ltr(text: str) -> str:
    """Isolate Latin/numeric fragments so they never jump or scramble inside Arabic RTL prose."""
    return f"{LRI}{text}{PDI}"


def load_bundled_fonts() -> str:
    """Load bundled OFL IBM Plex Sans Arabic fonts via QFontDatabase; fall back to Segoe UI."""
    font_files = (
        "IBMPlexSansArabic-Regular.ttf",
        "IBMPlexSansArabic-Medium.ttf",
        "IBMPlexSansArabic-SemiBold.ttf",
        "IBMPlexSansArabic-Bold.ttf",
    )
    loaded_family = ""
    for fname in font_files:
        fpath = get_resource_path(os.path.join("fonts", fname))
        if os.path.exists(fpath):
            fid = QFontDatabase.addApplicationFont(fpath)
            if fid >= 0:
                fams = QFontDatabase.applicationFontFamilies(fid)
                if fams and not loaded_family:
                    loaded_family = fams[0]
    if loaded_family:
        APP_LOG.info(f"Loaded bundled UI font: {loaded_family}")
        return loaded_family
    APP_LOG.warn("Bundled Arabic font not found; falling back to Segoe UI")
    return "Segoe UI"


def format_button_preset(idx: int, lang: str) -> str:
    """Format button preset label with proper BiDi isolation in Arabic mode without mutating BUTTON_PRESETS."""
    if not (0 <= idx < len(BUTTON_PRESETS)):
        return ""
    if lang == "en":
        return BUTTON_PRESETS_EN[idx]
    raw = BUTTON_PRESETS[idx][0]
    m = re.match(r"^(.*?)\s*(\([^()]+\))\s*$", raw)
    if m:
        return f"{m.group(1).strip()} {ltr(m.group(2))}"
    return raw


def format_dpi_color_label(hex_color: str, stage_idx: int, lang: str) -> str:
    """Show factory color name if unchanged, otherwise show the custom chosen hex code."""
    hx = (hex_color or "#FFFFFF").upper()
    if 0 <= stage_idx < len(DEFAULT_DPI_COLORS) and hx == DEFAULT_DPI_COLORS[stage_idx].upper():
        name = DPI_COLOR_NAMES_EN[stage_idx] if lang == "en" else DPI_COLOR_NAMES_AR[stage_idx]
        return f"LED: {name}" if lang == "en" else f"اللمبة: {name}"
    return f"LED: {hx}" if lang == "en" else f"اللمبة: {ltr(hx)}"


STRINGS: dict[str, dict[str, str]] = {
    "ar": {
        "win_title": f"{ltr('Aigo GM80 Plus Control')} — مركز التحكم",
        "product_title": ltr("Aigo GM80 Plus"),
        "product_sub": f"شريحة {ltr('YJX-CHIP')}  •  سنسور {ltr('PAW3311')}  •  تحكم مباشر بالذاكرة الداخلية",
        "btn_settings": "الإعدادات",
        "btn_refresh": "تحديث الآن",
        "btn_read_hw": "قراءة من الماوس",
        "btn_save_hw": "حفظ وتطبيق في ذاكرة الماوس",
        "btn_saving_hw": "جاري الحفظ في الماوس...",
        "btn_restoring_btns": "جاري استعادة الأزرار...",
        "tab_dpi": f"درجات {ltr('DPI')} والألوان",
        "tab_perf": f"معدل الاستجابة و {ltr('Debounce')}",
        "tab_buttons": "برمجة الأزرار",
        "tab_games": "أوضاع الألعاب",
        # Connection & Battery
        "conn_off": "غير متصل",
        "conn_bt": f"بلوتوث • {ltr('BT')}",
        "conn_wired_24g": f"سلكي + {ltr('2.4G')} • {ltr('USB-C')}",
        "conn_wired": f"سلكي • {ltr('USB-C')}",
        "conn_24g": f"وايرلس • {ltr('2.4G')}",
        "bat_checking": "جاري الفحص",
        "bat_offline": "غير متصل",
        "bat_charging": "يشحن",
        "bat_discharging": "على البطارية",
        "bat_low": "بطارية منخفضة",
        "bat_sleep": "سكون",
        "bat_waiting": "بانتظار الرد",
        "bat_last_updated": "آخر تحديث: {time}",
        # DPI tab
        "dpi_section_title": f"درجات {ltr('DPI')} الستة الثابتة ({ltr('800')} إلى {ltr('12000 DPI')})",
        "dpi_section_desc": "انقر على أي درجة لتحديدها، واضبط لون اللمبة السفلية الخاص بها بشكل مستقل عن لون الواجهة.",
        "dpi_restore_btn": "استعادة درجات الكتالوج",
        "dpi_stage_n": "الدرجة {n}",
        "dpi_pick_title": "اختر لون لمبة الدرجة {n}",
        "dpi_selected_status": "تم اختيار الدرجة {n} ({dpi}) — اضغط «حفظ وتطبيق» لتحديث الماوس.",
        # Perf tab
        "rate_title": f"معدل الاستجابة ({ltr('Polling Rate')})",
        "rate_desc": f"تردد إرسال بيانات الحركة للكمبيوتر — الموصى به {ltr('500 Hz')} لأفضل توازن بين الأداء والبطارية.",
        "perf_restore_btn": f"استعادة الافتراضي ({ltr('500 Hz / 8 ms')})",
        "deb_title": f"زمن منع الدبل كليك ({ltr('Debounce Time')})",
        "deb_desc": f"ضبط زمن استجابة المفاتيح بالمللي ثانية لمنع النقر المزدوج الوهمي (الافتراضي {ltr('8 ms')}).",
        "fw_line": "الفيرموير: {fw}  •  السيريال: {sn}",
        "fw_unread": "غير مقروء",
        "btn_kill_orig": f"إغلاق برنامج {ltr('GamingMouse')} الأصلي",
        # Buttons tab
        "btn_section_title": "تخصيص أزرار الماوس السبعة",
        "btn_section_desc": "الأزرار الفعلية المدعومة في الفيرموير فقط — تُحفظ مباشرة في الذاكرة الداخلية للماوس.",
        "btn_restore_defaults": "استعادة الأزرار الافتراضية",
        "btn_lock_left": "قفل الزر الأيسر",
        "btn_1": f"الزر الأيسر {ltr('(Left-Click)')}",
        "btn_2": f"الزر الأيمن {ltr('(Right-Click)')}",
        "btn_3": f"زر البكرة {ltr('(Middle-Click)')}",
        "btn_4": f"الجانبي الأمامي {ltr('(Forward)')}",
        "btn_5": f"الجانبي الخلفي {ltr('(Backward)')}",
        "btn_6": f"تمرير البكرة لأعلى {ltr('(Scroll Up)')}",
        "btn_7": f"تمرير البكرة لأسفل {ltr('(Scroll Down)')}",
        "btn_viz_title": f"معاينة تفاعلية — {ltr('Aigo GM80 Plus')}",
        "btn_viz_hint": "اضغط أي زر في الماوس أو حرّك البكرة للتجربة الفورية",
        "btn_viz_pressed": "الزر {n} · {name}",
        "left_click_warn_title": "تحذير الزر الأيسر",
        "left_click_warn_body": "تغيير وظيفة الزر الأيسر قد يمنعك من النقر العادي. هل تريد المتابعة؟",
        # Games tab
        "games_title": "أوضاع الألعاب التلقائية",
        "games_add": "إضافة لعبة",
        "games_detect": "التقاط نافذة مفتوحة",
        "games_default_lbl": "الوضع الافتراضي عند الخروج:",
        "games_delay_lbl": "مهلة العودة:",
        "games_delay_suffix": " ث",
        "games_empty_title": "لم يتم إضافة أي أوضاع ألعاب بعد",
        "games_empty_desc": "اضغط «إضافة لعبة» لاختيار ملف التشغيل، أو «التقاط نافذة مفتوحة» لاختيار لعبة مفتوحة بضغطة واحدة.",
        "games_banner_default": "الوضع النشط: الوضع الافتراضي ({dpi} • {rate})",
        "games_banner_active": "اللعبة النشطة: {name} ({dpi} • {rate})",
        "games_banner_countdown": "تم الخروج من {name} — العودة للافتراضي خلال {sec} ثانية",
        "games_pill_active": "نشط الآن",
        "games_pill_countdown": "العودة خلال {sec} ث",
        "games_pill_paused": "متوقف مؤقتاً",
        "games_pill_ready": "جاهز",
        "games_pause": "إيقاف",
        "games_resume": "تفعيل",
        "games_edit": "تعديل",
        "games_delete_tip": "حذف الوضع",
        "games_delete_title": "حذف وضع اللعبة",
        "games_delete_body": "هل تريد حذف وضع اللعبة «{name}» ({exe})؟",
        "games_saved_toast": "تم حفظ وضع اللعبة: {name}",
        # Settings dialog
        "dlg_settings_title": f"الإعدادات — {ltr('Aigo GM80 Plus')}",
        "dlg_settings_hdr": "إعدادات البرنامج",
        "set_nav_general": "عام",
        "set_nav_appearance": "المظهر",
        "set_nav_wallpaper": "الخلفية",
        "set_nav_battery": "البطارية",
        "set_nav_icon": "أيقونة البرنامج",
        "set_sec_general_desc": "سلوك النافذة والإغلاق والتشغيل في الخلفية.",
        "set_sec_appearance_desc": "تخصيص مظهر التطبيق، لون التمييز، ولغة الواجهة فوراً بدون إعادة تشغيل.",
        "set_sec_wallpaper_desc": "خلفية اختيارية للنافذة مع تحكم كامل في التعتيم والتمويه وعتامة اللوحات.",
        "set_sec_battery_desc": "ضبط وتيرة الاستعلام المباشر عن نسبة الشحن من الماوس.",
        "set_sec_icon_desc": "تخصيص أيقونة النافذة وشريط المهام واختصار سطح المكتب.",
        "set_theme_hdr": "مظهر التطبيق",
        "set_theme_desc": "اختر الوضع الداكن أو الفاتح أو اتبع إعدادات نظام ويندوز تلقائياً.",
        "set_theme_dark": "داكن",
        "set_theme_light": "فاتح",
        "set_theme_system": "النظام",
        "set_accent_hdr": "لون التمييز",
        "set_accent_desc": "يُطبّق على الأزرار النشطة والتحديدات (ألوان لمبة الـ DPI مستقلة).",
        "set_accent_pick": "لون مخصص",
        "set_lang_hdr": "لغة التطبيق",
        "set_lang_desc": "تبديل فوري بين العربية (من اليمين لليسار) والإنجليزية (من اليسار لليمين).",
        "set_bg_hdr": "التشغيل في الخلفية عند الإغلاق",
        "set_bg_hint": "عند الإيقاف (الافتراضي)، زر الإغلاق يخرج من البرنامج وشريط المهام نهائياً.",
        "set_bat_hdr": "مؤقت فحص البطارية التلقائي",
        "set_bat_desc": "يفحص البطارية مباشرة عبر الهاردوير بدون أي تقطيع؛ اختر «يدوي فقط» لإيقاف الفحص التلقائي.",
        "set_ico_desc": f"يدعم صيغ {ltr('.ico, .png, .jpg, .webp')} ويحدّث اختصار سطح المكتب تلقائياً.",
        "set_ico_active_default": f"الأيقونة الحالية: الافتراضية ({ltr('app_icon.ico')})",
        "set_ico_active_custom": "الأيقونة الحالية: مخصصة ({name})",
        "set_reset_section": "استعادة افتراضي هذا القسم",
        "set_reset_section_tip": "إرجاع إعدادات القسم المفتوح حالياً إلى القيم الافتراضية",
        "set_reset_done": "تمت استعادة الإعدادات الافتراضية لقسم «{section}»",
        "set_wp_hdr": "الخلفية (Wallpaper)",
        "set_wp_open": "فتح المجلد",
        "wp_mode_lbl": "الوضع:",
        "wp_mode_none": "بدون خلفية",
        "wp_mode_static": "صورة ثابتة",
        "wp_mode_slideshow": "عرض شرائح",
        "wp_mode_animated": "متحركة (GIF/WebP)",
        "wp_fit_lbl": "طريقة الملاءمة:",
        "wp_fit_smart_fill": "ملء ذكي (افتراضي)",
        "wp_fit_fit": "احتواء كامل (Fit)",
        "wp_fit_stretch": "تمديد (Stretch)",
        "wp_fit_center": "توسيط (Center)",
        "wp_fit_tile": "تكرار (Tile)",
        "wp_focus_lbl": "نقطة التركيز:",
        "wp_focus_top": "أعلى",
        "wp_focus_center": "وسط",
        "wp_focus_bottom": "أسفل",
        "wp_interval_lbl": "المدة:",
        "wp_shuffle_lbl": "ترتيب عشوائي",
        "wp_anim_lbl": "حركة الخلفية",
        "wp_dim_lbl": "تعتيم الخلفية:",
        "bat_style_hdr": "شكل مؤشر البطارية",
        "bat_style_desc": "اختر تصميم مؤشر البطارية المعروض في الشريط العلوي مع حركة سلسة وتنبيه مرئي.",
        "bat_style_classic": "بطارية أفقية",
        "bat_style_pill": "كبسولة دائرية",
        "bat_style_ring": "حلقة دائرية",
        "bat_style_vertical": "بطارية رأسية",
        "bat_style_segmented": "شرائح مقسّمة",
        "bat_tray_style_hdr": "استخدام نفس الشكل في أيقونة شريط المهام",
        "bat_tray_style_desc": "يعرض شكل مؤشر البطارية المختار داخل أيقونة البرنامج بجانب الساعة.",
        "bat_preview_hdr": "معاينة حية",
        "bat_preview_chg": "معاينة الشحن",
        "wp_blur_lbl": "تمويه الخلفية:",
        "wp_opacity_lbl": "عتامة اللوحات:",
        "wp_add_btn": "إضافة صور",
        "wp_remove_btn": "حذف المحددة",
        "wp_reload_btn": "إعادة تحميل",
        "wp_empty_grid": "لا توجد صور في مجلد wallpapers — اضغط «إضافة صور» لإضافة خلفياتك.",
        "wp_empty_anim": f"لا توجد ملفات {ltr('GIF')} أو {ltr('WebP')} متحركة في مجلد wallpapers.",
        "wp_remove_title": "حذف الخلفية",
        "wp_remove_body": "هل تريد حذف ملف الخلفية «{name}» من مجلد wallpapers؟",
        "wp_corrupt_skip": "تم تخطي ملف خلفية تالف أو غير مدعوم: {name}",
        "wp_added_toast": "تمت إضافة {count} صورة إلى الخلفيات",
        "wp_reloaded_toast": "تم تحديث قائمة الخلفيات ({count})",
        "wp_preview_none": "خلفية صلبة (الوضع الافتراضي)",
        "set_ico_hdr": "أيقونة البرنامج والاختصار",
        "set_ico_pick": "تغيير الأيقونة",
        "set_ico_reset": "استعادة الافتراضية",
        "set_ico_err_title": "خطأ في الأيقونة",
        "set_ico_err_body": "تعذر تحويل الصورة المختارة إلى ملف أيقونة.",
        "btn_close": "إغلاق",
        "btn_cancel": "إلغاء",
        # Running apps dialog
        "dlg_run_title": "التقاط لعبة أو برنامج من النوافذ المفتوحة",
        "dlg_run_sub": "افتح اللعبة أو البرنامج، اضغط تحديث إذا لزم الأمر، ثم اختره بضغطة واحدة:",
        "dlg_run_search": "ابحث بالاسم أو ملف التشغيل...",
        "dlg_run_refresh": "تحديث القائمة",
        "dlg_run_select": "اختيار هذا التطبيق",
        # Game editor dialog
        "dlg_gp_add_title": "إضافة وضع لعبة جديد",
        "dlg_gp_edit_title": "تعديل وضع اللعبة",
        "dlg_gp_icon_hint": f"أيقونة أو صورة اللعبة ({ltr('.png, .jpg, .webp, .ico')})",
        "dlg_gp_pick_img": "صورة مخصصة",
        "dlg_gp_extract_ico": f"استخراج أيقونة {ltr('.exe')}",
        "dlg_gp_name": "اسم اللعبة:",
        "dlg_gp_name_ph": f"مثال: {ltr('Valorant')} أو {ltr('Cyberpunk 2077')}",
        "dlg_gp_exe": f"ملف التشغيل ({ltr('.exe')}):",
        "dlg_gp_exe_ph": f"مثال: {ltr('game.exe')}",
        "dlg_gp_browse": "استعراض",
        "dlg_gp_dpi": f"درجة {ltr('DPI')}:",
        "dlg_gp_rate": "معدل الاستجابة:",
        "dlg_gp_enabled": "تفعيل هذا الوضع تلقائياً عند فتح اللعبة",
        "dlg_gp_save": "حفظ وضع اللعبة",
        "dlg_gp_missing_exe_title": "ملف التشغيل مطلوب",
        "dlg_gp_missing_exe_body": f"يرجى اختيار أو كتابة اسم ملف التشغيل ({ltr('.exe')}) الخاص باللعبة.",
        # Status / Toasts / Developer Log
        "status_ready": "جاهز — متصل بذاكرة الماوس الداخلية.",
        "toast_saved": "تم الحفظ في ذاكرة الماوس",
        "toast_read_ok": "تمت القراءة من ذاكرة الماوس",
        "toast_rate_ok": "تم تطبيق معدل الاستجابة {rate}",
        "toast_btns_restored": "تمت استعادة الأزرار الافتراضية",
        "toast_bat_ok": "البطارية: {pct}%",
        "toast_bat_sleep": "الماوس في وضع السكون — حرّكه للتحديث",
        "toast_bat_charging": "كابل الشحن متصل",
        "toast_hw_err": "تعذر الاتصال بالماوس — راجع سجل المطور للتفاصيل",
        "toast_bt_readonly": "التعديل يتطلب السلك أو دونجل 2.4G (البلوتوث يعمل بالإعدادات المحفوظة)",
        "status_reading": "جاري قراءة الإعدادات من الماوس...",
        "status_polling_bat": "جاري فحص حالة البطارية...",
        "status_applying_rate": "جاري تطبيق معدل الاستجابة {rate}...",
        "status_bg_on": "تم تفعيل التشغيل في الخلفية.",
        "status_bg_off": "تم إيقاف التشغيل في الخلفية (إغلاق نهائي عند الضغط على X).",
        "status_bat_manual": "تم ضبط فحص البطارية على الوضع اليدوي فقط.",
        "status_bat_interval": "تم ضبط الفحص التلقائي للبطارية: {label}.",
        "status_icon_ok": "تم تحديث أيقونة البرنامج بنجاح.",
        "status_icon_reset": "تمت استعادة الأيقونة الافتراضية.",
        "status_orig_closed": f"تم التأكد من إغلاق أي نسخة من {ltr('GamingMouse')}.",
        "status_hotplug_24g": f"تم فصل الكابل — الانتقال تلقائياً إلى {ltr('2.4G Dongle')}.",
        "status_hotplug_usb": f"تم توصيل الكابل — الانتقال تلقائياً إلى {ltr('USB Wired')}.",
        "conflict_title": f"تعارض منفذ {ltr('USB HID')}",
        "conflict_body": "برنامج الماوس الأصلي ({procs}) يعمل حالياً وقد يتعارض مع التحكم المباشر.\nهل تريد إغلاقه الآن؟",
        "devlog_title": "سجل المطور",
        "devlog_copy": "نسخ",
        "devlog_clear": "مسح",
        "devlog_copied": "تم نسخ السجل",
        # Tray
        "tray_open": f"فتح مركز التحكم ({ltr('Aigo GM80 Plus')})",
        "tray_poll": "تحديث البطارية والحالة",
        "tray_quit": "إغلاق البرنامج نهائياً",
        "tray_hidden_body": "البرنامج يعمل في الخلفية بجانب الساعة (فحص البطارية: {interval}).",
        "low_bat_title": f"تنبيه بطارية {ltr('Aigo GM80 Plus')}",
        "low_bat_body": "شحن الماوس منخفض ({pct}%) — يرجى توصيل الشاحن.",
        "gp_toast_title": "وضع اللعبة: {name}",
        "gp_toast_body": "تم تفعيل {name}: {dpi} • {rate}",
        "gp_default_title": "الوضع الافتراضي",
        "gp_default_body": "تمت العودة للوضع الافتراضي: {dpi} • {rate}",
    },
    "en": {
        "win_title": "Aigo GM80 Plus Control — Control Center",
        "product_title": "Aigo GM80 Plus",
        "product_sub": "YJX-CHIP  •  PAW3311 Sensor  •  Direct Onboard Memory",
        "btn_settings": "Settings",
        "btn_refresh": "Update Now",
        "btn_read_hw": "Read from Mouse",
        "btn_save_hw": "Save to Onboard Memory",
        "btn_saving_hw": "Saving to mouse...",
        "btn_restoring_btns": "Restoring buttons...",
        "tab_dpi": "DPI & Colors",
        "tab_perf": "Polling & Debounce",
        "tab_buttons": "Button Mapping",
        "tab_games": "Game Profiles",
        # Connection & Battery
        "conn_off": "Disconnected",
        "conn_bt": "Bluetooth • BT",
        "conn_wired_24g": "Wired + 2.4G • USB-C",
        "conn_wired": "Wired • USB-C",
        "conn_24g": "Wireless • 2.4G",
        "bat_checking": "Checking",
        "bat_offline": "Offline",
        "bat_charging": "Charging",
        "bat_discharging": "On Battery",
        "bat_low": "Low Battery",
        "bat_sleep": "Sleep",
        "bat_waiting": "Waiting",
        "bat_last_updated": "Updated: {time}",
        # DPI tab
        "dpi_section_title": "6 Fixed DPI Stages (800 – 12000 DPI)",
        "dpi_section_desc": "Click any stage card to select it. Bottom LED indicator colors stay independent from UI accent color.",
        "dpi_restore_btn": "Restore Catalog Defaults",
        "dpi_stage_n": "Stage {n}",
        "dpi_pick_title": "Pick Bottom LED Color for Stage {n}",
        "dpi_selected_status": "Selected Stage {n} ({dpi}) — Click 'Save to Onboard Memory' to apply.",
        # Perf tab
        "rate_title": "Polling Rate",
        "rate_desc": "USB/2.4G report rate — 500 Hz is recommended for optimal balance of responsiveness and battery life.",
        "perf_restore_btn": "Restore Default (500 Hz / 8 ms)",
        "deb_title": "Debounce Time",
        "deb_desc": "Adjust switch debounce delay in milliseconds to prevent unintended double-clicks (Default: 8 ms).",
        "fw_line": "Firmware: {fw}  •  Serial: {sn}",
        "fw_unread": "Unread",
        "btn_kill_orig": "Close Official GamingMouse App",
        # Buttons tab
        "btn_section_title": "7-Button Remapping",
        "btn_section_desc": "Only firmware-supported inputs — saved directly to mouse onboard flash memory.",
        "btn_restore_defaults": "Restore Defaults",
        "btn_lock_left": "Lock Left-Click",
        "btn_1": "Left-Click",
        "btn_2": "Right-Click",
        "btn_3": "Middle-Click (Wheel)",
        "btn_4": "Forward (Front Side)",
        "btn_5": "Backward (Rear Side)",
        "btn_6": "Scroll Up",
        "btn_7": "Scroll Down",
        "btn_viz_title": "Interactive Preview — Aigo GM80 Plus",
        "btn_viz_hint": "Press any mouse button or scroll the wheel to test live",
        "btn_viz_pressed": "Button {n} · {name}",
        "left_click_warn_title": "Left-Click Warning",
        "left_click_warn_body": "Remapping Left-Click may prevent normal clicking. Continue?",
        # Games tab
        "games_title": "Automatic Game Profiles",
        "games_add": "Add Game",
        "games_detect": "Detect Running App",
        "games_default_lbl": "Default profile on exit:",
        "games_delay_lbl": "Exit delay:",
        "games_delay_suffix": " s",
        "games_empty_title": "No Game Profiles Added Yet",
        "games_empty_desc": "Click 'Add Game' to pick an executable, or 'Detect Running App' to capture an open game in one click.",
        "games_banner_default": "Active: Default Profile ({dpi} • {rate})",
        "games_banner_active": "Active Game: {name} ({dpi} • {rate})",
        "games_banner_countdown": "Left {name} — Reverting to Default in {sec}s",
        "games_pill_active": "Active Now",
        "games_pill_countdown": "Reverting in {sec}s",
        "games_pill_paused": "Paused",
        "games_pill_ready": "Ready",
        "games_pause": "Pause",
        "games_resume": "Resume",
        "games_edit": "Edit",
        "games_delete_tip": "Delete Profile",
        "games_delete_title": "Delete Game Profile",
        "games_delete_body": "Delete profile for '{name}' ({exe})?",
        "games_saved_toast": "Saved game profile: {name}",
        # Settings dialog
        "dlg_settings_title": "Settings — Aigo GM80 Plus",
        "dlg_settings_hdr": "Application Settings",
        "set_nav_general": "General",
        "set_nav_appearance": "Appearance",
        "set_nav_wallpaper": "Wallpaper",
        "set_nav_battery": "Battery",
        "set_nav_icon": "App Icon",
        "set_sec_general_desc": "Window close behavior and background tray operation.",
        "set_sec_appearance_desc": "Customize theme mode, accent color, and interface language instantly with no restart.",
        "set_sec_wallpaper_desc": "Optional background wallpaper with dim, blur, fit mode, and panel opacity controls.",
        "set_sec_battery_desc": "Configure live hardware battery polling frequency.",
        "set_sec_icon_desc": "Customize window, system tray, and desktop shortcut icon.",
        "set_theme_hdr": "Theme Mode",
        "set_theme_desc": "Switch between Dark, Light, or automatically follow Windows system theme.",
        "set_theme_dark": "Dark",
        "set_theme_light": "Light",
        "set_theme_system": "System",
        "set_accent_hdr": "Accent Color",
        "set_accent_desc": "Used for primary actions and active selections (hardware DPI LED colors stay independent).",
        "set_accent_pick": "Custom Color",
        "set_lang_hdr": "Language",
        "set_lang_desc": "Switch instantly between Arabic (RTL) and English (LTR).",
        "set_bg_hdr": "Run in Background on Close",
        "set_bg_hint": "When off (default), clicking X exits the app and tray icon completely.",
        "set_bat_hdr": "Auto Battery Check Interval",
        "set_bat_desc": "Queries live mouse battery telemetry without stutter; choose Manual Only to disable automatic polling.",
        "set_ico_desc": "Supports .ico, .png, .jpg, and .webp images and updates your desktop shortcut icon automatically.",
        "set_ico_active_default": "Active icon: Default (app_icon.ico)",
        "set_ico_active_custom": "Active icon: Custom ({name})",
        "set_reset_section": "Reset section to defaults",
        "set_reset_section_tip": "Restore default values for the currently open settings section",
        "set_reset_done": "Restored defaults for '{section}'",
        "set_wp_hdr": "Wallpaper",
        "set_wp_open": "Open Folder",
        "wp_mode_lbl": "Mode:",
        "wp_mode_none": "None",
        "wp_mode_static": "Static Image",
        "wp_mode_slideshow": "Slideshow",
        "wp_mode_animated": "Animated (GIF/WebP)",
        "wp_fit_lbl": "Fit Mode:",
        "wp_fit_smart_fill": "Smart Fill (Default)",
        "wp_fit_fit": "Fit",
        "wp_fit_stretch": "Stretch",
        "wp_fit_center": "Center",
        "wp_fit_tile": "Tile",
        "wp_focus_lbl": "Focus Point:",
        "wp_focus_top": "Top",
        "wp_focus_center": "Center",
        "wp_focus_bottom": "Bottom",
        "wp_interval_lbl": "Interval:",
        "wp_shuffle_lbl": "Shuffle",
        "wp_anim_lbl": "Animation",
        "wp_dim_lbl": "Dim:",
        "bat_style_hdr": "Battery Indicator Style",
        "bat_style_desc": "Choose how the battery level is displayed in the header status bar with smooth fill animations.",
        "bat_style_classic": "Classic Horizontal",
        "bat_style_pill": "Rounded Pill",
        "bat_style_ring": "Circular Ring",
        "bat_style_vertical": "Vertical Battery",
        "bat_style_segmented": "Segmented Bars",
        "bat_tray_style_hdr": "Use selected style in System Tray icon",
        "bat_tray_style_desc": "Draws your chosen battery style directly inside the taskbar tray icon.",
        "bat_preview_hdr": "Live Preview",
        "bat_preview_chg": "Preview Charging",
        "wp_blur_lbl": "Blur:",
        "wp_opacity_lbl": "Panel Opacity:",
        "wp_add_btn": "Add Images",
        "wp_remove_btn": "Remove Selected",
        "wp_reload_btn": "Reload",
        "wp_empty_grid": "No images in wallpapers/ — click 'Add Images' to add wallpapers.",
        "wp_empty_anim": "No animated GIF or animated WebP files found in wallpapers/.",
        "wp_remove_title": "Remove Wallpaper",
        "wp_remove_body": "Delete wallpaper file '{name}' from wallpapers/?",
        "wp_corrupt_skip": "Skipped corrupt or unsupported wallpaper: {name}",
        "wp_added_toast": "Added {count} image(s) to wallpapers",
        "wp_reloaded_toast": "Reloaded wallpapers ({count} found)",
        "wp_preview_none": "Solid Theme Background (Default)",
        "set_ico_hdr": "App & Shortcut Icon",
        "set_ico_pick": "Change Icon",
        "set_ico_reset": "Restore Default",
        "set_ico_err_title": "Icon Error",
        "set_ico_err_body": "Failed to convert the selected image to an .ico file.",
        "btn_close": "Close",
        "btn_cancel": "Cancel",
        # Running apps dialog
        "dlg_run_title": "Detect Running Game / App",
        "dlg_run_sub": "Launch your game or app, click Refresh if needed, then select it:",
        "dlg_run_search": "Search by window title or .exe...",
        "dlg_run_refresh": "Refresh",
        "dlg_run_select": "Select App",
        # Game editor dialog
        "dlg_gp_add_title": "New Game Profile",
        "dlg_gp_edit_title": "Edit Game Profile",
        "dlg_gp_icon_hint": "Game Icon / Custom Artwork (.png, .jpg, .webp, .ico)",
        "dlg_gp_pick_img": "Custom Image",
        "dlg_gp_extract_ico": "Extract .exe Icon",
        "dlg_gp_name": "Display Name:",
        "dlg_gp_name_ph": "e.g. Valorant, CS2, Cyberpunk 2077",
        "dlg_gp_exe": "Executable (.exe):",
        "dlg_gp_exe_ph": "e.g. game.exe",
        "dlg_gp_browse": "Browse",
        "dlg_gp_dpi": "DPI Stage:",
        "dlg_gp_rate": "Polling Rate:",
        "dlg_gp_enabled": "Auto-activate when this game is in foreground",
        "dlg_gp_save": "Save Game Profile",
        "dlg_gp_missing_exe_title": "Executable Required",
        "dlg_gp_missing_exe_body": "Please select or enter the game's .exe filename.",
        # Status / Toasts / Developer Log
        "status_ready": "Ready — Direct mouse onboard memory control.",
        "toast_saved": "Saved to mouse",
        "toast_read_ok": "Read from mouse",
        "toast_rate_ok": "Applied {rate}",
        "toast_btns_restored": "Default buttons restored",
        "toast_bat_ok": "Battery: {pct}%",
        "toast_bat_sleep": "Mouse is sleeping — move it to refresh",
        "toast_bat_charging": "USB-C cable connected",
        "toast_hw_err": "Mouse communication failed — check Developer Log",
        "toast_bt_readonly": "Requires USB or 2.4G Dongle (Bluetooth uses saved onboard settings)",
        "status_reading": "Reading settings from mouse...",
        "status_polling_bat": "Checking battery status...",
        "status_applying_rate": "Applying {rate} polling rate...",
        "status_bg_on": "Run in background enabled.",
        "status_bg_off": "Run in background disabled (X exits cleanly).",
        "status_bat_manual": "Auto battery polling set to Manual Only.",
        "status_bat_interval": "Auto battery polling: {label}.",
        "status_icon_ok": "App icon updated.",
        "status_icon_reset": "Restored default app icon.",
        "status_orig_closed": "Checked and closed any running GamingMouse process.",
        "status_hotplug_24g": "USB cable unplugged — switched to 2.4G Dongle.",
        "status_hotplug_usb": "USB cable connected — switched to USB Wired.",
        "conflict_title": "USB HID Port Conflict",
        "conflict_body": "The official mouse driver ({procs}) is running and may conflict with HID access.\nClose it now?",
        "devlog_title": "Developer Log",
        "devlog_copy": "Copy",
        "devlog_clear": "Clear",
        "devlog_copied": "Log copied",
        # Tray
        "tray_open": "Open Control Center (Aigo GM80 Plus)",
        "tray_poll": "Refresh Battery & Status",
        "tray_quit": "Exit Application",
        "tray_hidden_body": "Running in the system tray (Battery polling: {interval}).",
        "low_bat_title": "Aigo GM80 Plus Low Battery",
        "low_bat_body": "Mouse battery is low ({pct}%) — please connect charger.",
        "gp_toast_title": "Game Profile: {name}",
        "gp_toast_body": "Activated {name}: {dpi} • {rate}",
        "gp_default_title": "Default Profile",
        "gp_default_body": "Reverted to Default Profile: {dpi} • {rate}",
    },
}


def tr(key: str, lang: str = "ar", **kwargs) -> str:
    table = STRINGS.get(lang, STRINGS["ar"])
    text = table.get(key, STRINGS["en"].get(key, key))
    if kwargs:
        try:
            return text.format(**kwargs)
        except Exception:
            return text
    return text


# ============================================================================
# DESIGN SYSTEM & CENTRAL THEME ENGINE (TOKENS, WCAG CONTRAST, QSS BUILDER)
# ============================================================================
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "xxl": 32}
RAD = {"sm": 6, "md": 8, "lg": 10, "xl": 12}
FONT = {"xs": 11, "sm": 12, "base": 13, "md": 14, "lg": 16, "xl": 18, "hero": 22}

ACCENT_PRESETS = [
    ("#3B82F6", "Blue"),
    ("#0EA5E9", "Sky"),
    ("#10B981", "Emerald"),
    ("#8B5CF6", "Violet"),
    ("#F43F5E", "Rose"),
    ("#F97316", "Orange"),
    ("#EAB308", "Amber"),
    ("#14B8A6", "Teal"),
]


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = (hex_color or "#3B82F6").strip().lstrip("#")
    if len(h) != 6:
        return (59, 130, 246)
    try:
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))
    except ValueError:
        return (59, 130, 246)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{max(0, min(255, r)):02X}{max(0, min(255, g)):02X}{max(0, min(255, b)):02X}"


def _relative_luminance(r: int, g: int, b: int) -> float:
    def _lin(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def contrast_ratio(hex_a: str, hex_b: str) -> float:
    la = _relative_luminance(*_hex_to_rgb(hex_a))
    lb = _relative_luminance(*_hex_to_rgb(hex_b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def pick_readable_fg(bg_hex: str) -> str:
    """Choose #FFFFFF or #0B1220 based on WCAG 2.1 contrast ratio against bg_hex."""
    return "#FFFFFF" if contrast_ratio(bg_hex, "#FFFFFF") >= contrast_ratio(bg_hex, "#0B1220") else "#0B1220"


def _mix_rgb(rgb: tuple[int, int, int], target: tuple[int, int, int], factor: float) -> str:
    r = int(round(rgb[0] + (target[0] - rgb[0]) * factor))
    g = int(round(rgb[1] + (target[1] - rgb[1]) * factor))
    b = int(round(rgb[2] + (target[2] - rgb[2]) * factor))
    return _rgb_to_hex(r, g, b)


def detect_system_theme_mode() -> str:
    """Read Windows AppsUseLightTheme registry key; fall back cleanly to 'dark'."""
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if int(val) == 1 else "dark"
    except Exception:
        return "dark"


def derive_accent_tokens(accent_hex: str, is_dark: bool) -> dict[str, str]:
    clean = accent_hex.strip().upper() if isinstance(accent_hex, str) else "#3B82F6"
    if not re.fullmatch(r"#[0-9A-F]{6}", clean):
        clean = "#3B82F6"
    rgb = _hex_to_rgb(clean)
    r, g, b = rgb
    hover = _mix_rgb(rgb, (255, 255, 255), 0.12) if is_dark else _mix_rgb(rgb, (0, 0, 0), 0.10)
    pressed = _mix_rgb(rgb, (0, 0, 0), 0.16) if is_dark else _mix_rgb(rgb, (0, 0, 0), 0.20)
    tint_alpha = 34 if is_dark else 24
    tint_strong_alpha = 56 if is_dark else 40
    return {
        "accent": clean,
        "accent_hover": hover,
        "accent_pressed": pressed,
        "accent_fg": pick_readable_fg(clean),
        "accent_tint": f"rgba({r}, {g}, {b}, {tint_alpha})",
        "accent_tint_strong": f"rgba({r}, {g}, {b}, {tint_strong_alpha})",
        "accent_border": f"rgba({r}, {g}, {b}, 200)",
        "accent_rgb": f"{r}, {g}, {b}",
    }


def build_theme(
    mode: str = "dark",
    accent_hex: str = "#3B82F6",
    ui_font: str = "Segoe UI",
    panel_opacity: int = 100,
    wallpaper_active: bool = False,
) -> dict[str, str]:
    resolved = detect_system_theme_mode() if mode == "system" else ("light" if mode == "light" else "dark")
    is_dark = (resolved == "dark")
    if is_dark:
        base = {
            "mode_setting": mode,
            "mode": "dark",
            "bg": "#0F1117",
            "surface": "#161A22",
            "surface_elevated": "#1D222D",
            "surface_hover": "#252B39",
            "surface_input": "#12161E",
            "border": "#2A3140",
            "border_strong": "#3B4559",
            "text": "#F1F5F9",
            "text_secondary": "#94A3B8",
            "text_muted": "#64748B",
            "success": "#22C55E",
            "success_bg": "rgba(34, 197, 94, 30)",
            "success_border": "rgba(34, 197, 94, 120)",
            "warning": "#F59E0B",
            "warning_bg": "rgba(245, 158, 11, 30)",
            "warning_border": "rgba(245, 158, 11, 125)",
            "danger": "#EF4444",
            "danger_bg": "rgba(239, 68, 68, 28)",
            "danger_hover": "rgba(239, 68, 68, 52)",
            "danger_border": "rgba(239, 68, 68, 130)",
            "neutral_bg": "rgba(148, 163, 184, 24)",
            "neutral_border": "rgba(148, 163, 184, 75)",
            "toast_bg": "#1F2633",
            "scroll_track": "#12161E",
            "scroll_thumb": "#334155",
            "scroll_thumb_hover": "#475569",
        }
    else:
        base = {
            "mode_setting": mode,
            "mode": "light",
            "bg": "#F3F5F9",
            "surface": "#FFFFFF",
            "surface_elevated": "#F8FAFC",
            "surface_hover": "#EEF2F7",
            "surface_input": "#FFFFFF",
            "border": "#DDE3EC",
            "border_strong": "#C0CBD9",
            "text": "#0F172A",
            "text_secondary": "#475569",
            "text_muted": "#64748B",
            "success": "#16A34A",
            "success_bg": "rgba(22, 163, 74, 22)",
            "success_border": "rgba(22, 163, 74, 110)",
            "warning": "#D97706",
            "warning_bg": "rgba(217, 119, 6, 22)",
            "warning_border": "rgba(217, 119, 6, 115)",
            "danger": "#DC2626",
            "danger_bg": "rgba(220, 38, 38, 18)",
            "danger_hover": "rgba(220, 38, 38, 38)",
            "danger_border": "rgba(220, 38, 38, 120)",
            "neutral_bg": "rgba(100, 116, 139, 18)",
            "neutral_border": "rgba(100, 116, 139, 70)",
            "toast_bg": "#FFFFFF",
            "scroll_track": "#EEF2F7",
            "scroll_thumb": "#CBD5E1",
            "scroll_thumb_hover": "#94A3B8",
        }
    if wallpaper_active:
        op = max(55, min(100, int(panel_opacity)))
        a_main = int(round(op * 2.55))
        a_elev = min(255, int(round(min(100, op + 4) * 2.55)))
        sr, sg, sb = _hex_to_rgb(base["surface"])
        er, eg, eb = _hex_to_rgb(base["surface_elevated"])
        base["surface_panel"] = f"rgba({sr}, {sg}, {sb}, {a_main})"
        base["surface_elevated_panel"] = f"rgba({er}, {eg}, {eb}, {a_elev})"
        base["root_bg"] = "transparent"
    else:
        base["surface_panel"] = base["surface"]
        base["surface_elevated_panel"] = base["surface_elevated"]
        base["root_bg"] = base["bg"]
    base.update(derive_accent_tokens(accent_hex, is_dark))
    base["ui_font"] = ui_font
    base["mono_font"] = MONO_FONT_FAMILY
    return base


def build_qss(t: dict[str, str]) -> str:
    """Single centralized stylesheet generator driven exclusively by design tokens."""
    return f"""
QMainWindow, QDialog {{
    background-color: {t["bg"]};
    color: {t["text"]};
    font-family: "{t["ui_font"]}", "Segoe UI", sans-serif;
    font-size: {FONT["base"]}px;
}}
QWidget#AppRoot {{
    background-color: {t["root_bg"]};
}}
QWidget {{
    color: {t["text"]};
    font-family: "{t["ui_font"]}", "Segoe UI", sans-serif;
}}
QLabel {{
    background: transparent;
}}
QFrame#Card, QFrame#HeaderCard, QFrame#FooterCard {{
    background-color: {t["surface_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["xl"]}px;
}}
QFrame#SubCard, QFrame#GlassRow {{
    background-color: {t["surface_elevated_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#DpiCard {{
    background-color: {t["surface_elevated_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#DpiCard:hover {{
    border: 1px solid {t["border_strong"]};
    background-color: {t["surface_hover"]};
}}
QFrame#DpiCard[selected="true"] {{
    background-color: {t["accent_tint"]};
    border: 2px solid {t["accent"]};
}}
QFrame#GameCard {{
    background-color: {t["surface_elevated_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#GameCard[state="active"] {{
    background-color: {t["accent_tint"]};
    border: 1px solid {t["accent"]};
}}
QFrame#GameCard[state="paused"] {{
    background-color: {t["surface_panel"]};
    border: 1px solid {t["border"]};
}}
QFrame#WpPreviewFrame {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#WpThumbTile {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["md"]}px;
}}
QFrame#WpThumbTile:hover {{
    border: 1px solid {t["border_strong"]};
    background-color: {t["surface_hover"]};
}}
QFrame#WpThumbTile[selected="true"] {{
    border: 2px solid {t["accent"]};
    background-color: {t["accent_tint"]};
}}
QLabel#TitleLabel {{
    font-size: {FONT["xl"]}px;
    font-weight: 700;
    color: {t["text"]};
}}
QLabel#SectionTitle {{
    font-size: {FONT["md"]}px;
    font-weight: 700;
    color: {t["text"]};
}}
QLabel#SubtitleLabel {{
    font-size: {FONT["sm"]}px;
    color: {t["text_secondary"]};
}}
QLabel#MutedLabel {{
    font-size: {FONT["xs"]}px;
    color: {t["text_muted"]};
}}
QLabel#MonoValue {{
    font-family: {t["mono_font"]};
    font-size: {FONT["md"]}px;
    font-weight: 700;
    color: {t["text"]};
}}
QLabel#MonoPill {{
    font-family: {t["mono_font"]};
    font-size: {FONT["md"]}px;
    font-weight: 700;
    color: {t["accent"]};
    background-color: {t["accent_tint"]};
    border: 1px solid {t["accent_border"]};
    border-radius: {RAD["md"]}px;
    padding: 4px 10px;
}}
QLabel#BatteryPct {{
    font-family: {t["mono_font"]};
    font-size: {FONT["md"]}px;
    font-weight: 700;
    color: {t["text"]};
}}
QLabel#BatteryPct[tone="success"] {{ color: {t["success"]}; }}
QLabel#BatteryPct[tone="warning"] {{ color: {t["warning"]}; }}
QLabel#BatteryPct[tone="danger"]  {{ color: {t["danger"]}; }}
QLabel#BatteryPct[tone="accent"]  {{ color: {t["accent"]}; }}
QLabel#BatteryPct[tone="neutral"] {{ color: {t["text_muted"]}; }}

QLabel#Badge {{
    font-size: {FONT["xs"]}px;
    font-weight: 600;
    border-radius: {RAD["sm"]}px;
    padding: 2px 8px;
}}
QLabel#Badge[mono="true"] {{
    font-family: {t["mono_font"]};
}}
QLabel#Badge[tone="accent"] {{
    color: {t["accent"]};
    background-color: {t["accent_tint"]};
    border: 1px solid {t["accent_border"]};
}}
QLabel#Badge[tone="success"] {{
    color: {t["success"]};
    background-color: {t["success_bg"]};
    border: 1px solid {t["success_border"]};
}}
QLabel#Badge[tone="warning"] {{
    color: {t["warning"]};
    background-color: {t["warning_bg"]};
    border: 1px solid {t["warning_border"]};
}}
QLabel#Badge[tone="danger"] {{
    color: {t["danger"]};
    background-color: {t["danger_bg"]};
    border: 1px solid {t["danger_border"]};
}}
QLabel#Badge[tone="neutral"] {{
    color: {t["text_secondary"]};
    background-color: {t["neutral_bg"]};
    border: 1px solid {t["neutral_border"]};
}}

QLabel#StatusDot {{
    min-width: 9px;
    max-width: 9px;
    min-height: 9px;
    max-height: 9px;
    border-radius: 4px;
}}
QLabel#StatusDot[tone="success"] {{ background-color: {t["success"]}; }}
QLabel#StatusDot[tone="accent"]  {{ background-color: {t["accent"]}; }}
QLabel#StatusDot[tone="warning"] {{ background-color: {t["warning"]}; }}
QLabel#StatusDot[tone="danger"]  {{ background-color: {t["danger"]}; }}
QLabel#StatusDot[tone="neutral"] {{ background-color: {t["text_muted"]}; }}

QLabel#StatusText {{
    font-size: {FONT["sm"]}px;
    font-weight: 600;
    color: {t["text_secondary"]};
}}
QLabel#StatusText[tone="success"] {{ color: {t["success"]}; }}
QLabel#StatusText[tone="warning"] {{ color: {t["warning"]}; }}
QLabel#StatusText[tone="danger"]  {{ color: {t["danger"]}; }}
QLabel#StatusText[tone="accent"]  {{ color: {t["accent"]}; }}

/* Buttons: Strictly One Primary Button per Screen */
QPushButton#SaveBtn, QPushButton#PrimaryBtn {{
    background-color: {t["accent"]};
    color: {t["accent_fg"]};
    border: 1px solid {t["accent"]};
    border-radius: {RAD["md"]}px;
    padding: 8px 16px;
    font-size: {FONT["base"]}px;
    font-weight: 700;
}}
QPushButton#SaveBtn:hover, QPushButton#PrimaryBtn:hover {{
    background-color: {t["accent_hover"]};
    border: 1px solid {t["accent_hover"]};
}}
QPushButton#SaveBtn:pressed, QPushButton#PrimaryBtn:pressed {{
    background-color: {t["accent_pressed"]};
}}
QPushButton#SaveBtn:disabled, QPushButton#PrimaryBtn:disabled {{
    background-color: {t["surface_hover"]};
    color: {t["text_muted"]};
    border: 1px solid {t["border"]};
}}

QPushButton#SecondaryBtn, QPushButton#GlassBtn {{
    background-color: {t["surface_elevated"]};
    color: {t["text"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["md"]}px;
    padding: 7px 14px;
    font-size: {FONT["sm"]}px;
    font-weight: 600;
}}
QPushButton#SecondaryBtn:hover, QPushButton#GlassBtn:hover {{
    background-color: {t["surface_hover"]};
    border: 1px solid {t["accent"]};
}}
QPushButton#SecondaryBtn:disabled, QPushButton#GlassBtn:disabled {{
    color: {t["text_muted"]};
    border: 1px solid {t["border"]};
}}

QPushButton#GhostBtn, QPushButton#MiniBtn {{
    background-color: transparent;
    color: {t["text_secondary"]};
    border: 1px solid transparent;
    border-radius: {RAD["md"]}px;
    padding: 6px 10px;
    font-size: {FONT["sm"]}px;
    font-weight: 600;
}}
QPushButton#GhostBtn:hover, QPushButton#MiniBtn:hover {{
    background-color: {t["surface_hover"]};
    color: {t["text"]};
    border: 1px solid {t["border"]};
}}
QPushButton#IconBtn {{
    background-color: {t["surface_input"]};
    color: {t["text_secondary"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["md"]}px;
    padding: 0px;
}}
QPushButton#IconBtn:hover {{
    background-color: {t["surface_hover"]};
    border: 1px solid {t["accent"]};
}}
QPushButton#IconBtn:disabled {{
    border: 1px solid {t["border"]};
}}
QFrame#TabStrip {{
    background-color: {t["surface_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#VertSep {{
    background-color: {t["border"]};
    min-width: 1px;
    max-width: 1px;
    min-height: 20px;
    max-height: 20px;
}}

QPushButton#DangerBtn {{
    background-color: {t["danger_bg"]};
    color: {t["danger"]};
    border: 1px solid {t["danger_border"]};
    border-radius: {RAD["md"]}px;
    padding: 6px 10px;
    font-size: {FONT["sm"]}px;
    font-weight: 600;
}}
QPushButton#DangerBtn:hover {{
    background-color: {t["danger_hover"]};
}}

/* Navigation Tabs */
QPushButton#TabBtn {{
    background-color: transparent;
    color: {t["text_secondary"]};
    border: 1px solid transparent;
    border-radius: {RAD["md"]}px;
    padding: 8px 14px;
    font-size: {FONT["base"]}px;
    font-weight: 600;
}}
QPushButton#TabBtn:hover {{
    background-color: {t["surface_hover"]};
    color: {t["text"]};
}}
QPushButton#TabBtn[active="true"] {{
    background-color: {t["accent_tint"]};
    color: {t["accent"]};
    border: 1px solid {t["accent_border"]};
    font-weight: 700;
}}

/* Segmented Rate & Theme Buttons */
QPushButton#RateBtn, QPushButton#SegmentBtn {{
    background-color: {t["surface"]};
    color: {t["text_secondary"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["md"]}px;
    padding: 10px 14px;
    font-family: {t["mono_font"]};
    font-size: {FONT["md"]}px;
    font-weight: 700;
}}
QPushButton#SegmentBtn {{
    font-family: "{t["ui_font"]}", "Segoe UI", sans-serif;
    font-size: {FONT["sm"]}px;
    padding: 7px 12px;
}}
QPushButton#RateBtn:hover, QPushButton#SegmentBtn:hover {{
    background-color: {t["surface_hover"]};
    color: {t["text"]};
    border: 1px solid {t["border_strong"]};
}}
QPushButton#RateBtn[active="true"], QPushButton#SegmentBtn[active="true"] {{
    background-color: {t["accent_tint"]};
    color: {t["accent"]};
    border: 2px solid {t["accent"]};
}}

/* Inputs, Combos, SpinBox, Sliders */
QLineEdit {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["md"]}px;
    padding: 7px 10px;
    color: {t["text"]};
    font-size: {FONT["base"]}px;
}}
QLineEdit:focus {{
    border: 1px solid {t["accent"]};
}}
QLineEdit#PathBox, QLineEdit#HexInput {{
    font-family: {t["mono_font"]};
    font-size: {FONT["sm"]}px;
}}
QComboBox {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["md"]}px;
    padding: 6px 12px;
    min-height: 22px;
    color: {t["text"]};
    font-size: {FONT["sm"]}px;
    font-weight: 600;
}}
QComboBox:hover, QComboBox:focus {{
    border: 1px solid {t["accent"]};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox QAbstractItemView {{
    background-color: {t["surface"]};
    color: {t["text"]};
    selection-background-color: {t["accent_tint_strong"]};
    selection-color: {t["text"]};
    border: 1px solid {t["border_strong"]};
    outline: none;
}}
QSpinBox, QDoubleSpinBox {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["md"]}px;
    padding: 4px 30px 4px 10px;
    min-width: 100px;
    min-height: 28px;
    color: {t["text"]};
    font-family: {t["mono_font"]};
    font-size: {FONT["base"]}px;
    font-weight: 700;
}}
QSpinBox:hover, QSpinBox:focus, QDoubleSpinBox:hover, QDoubleSpinBox:focus {{
    border: 1px solid {t["accent"]};
}}
QSpinBox::up-button, QDoubleSpinBox::up-button {{
    subcontrol-origin: border;
    subcontrol-position: top right;
    width: 26px;
    border-left: 1px solid {t["border"]};
    border-bottom: 1px solid {t["border"]};
    border-top-right-radius: {RAD["md"]}px;
    background-color: {t["surface_elevated"]};
}}
QSpinBox::down-button, QDoubleSpinBox::down-button {{
    subcontrol-origin: border;
    subcontrol-position: bottom right;
    width: 26px;
    border-left: 1px solid {t["border"]};
    border-bottom-right-radius: {RAD["md"]}px;
    background-color: {t["surface_elevated"]};
}}
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background-color: {t["surface_hover"]};
}}
QSpinBox::up-arrow, QSpinBox::down-arrow,
QDoubleSpinBox::up-arrow, QDoubleSpinBox::down-arrow {{
    width: 0px;
    height: 0px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {t["border"]};
    border-radius: 3px;
}}
QSlider::sub-page:horizontal {{
    background: {t["accent"]};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {t["accent"]};
    border: 2px solid {t["surface"]};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QRadioButton {{
    font-size: {FONT["base"]}px;
    font-weight: 700;
    spacing: 8px;
    color: {t["text"]};
}}
QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 8px;
    border: 2px solid {t["border_strong"]};
    background: {t["surface_input"]};
}}
QRadioButton::indicator:checked {{
    border: 5px solid {t["accent"]};
    background: {t["accent_fg"]};
}}

/* Battery Progress Bar */
QProgressBar#BatteryBar {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border"]};
    border-radius: 6px;
    padding: 1px;
}}
QProgressBar#BatteryBar::chunk {{
    background-color: {t["accent"]};
    border-radius: 4px;
}}
QProgressBar#BatteryBar[tone="success"]::chunk {{ background-color: {t["success"]}; }}
QProgressBar#BatteryBar[tone="warning"]::chunk {{ background-color: {t["warning"]}; }}
QProgressBar#BatteryBar[tone="danger"]::chunk  {{ background-color: {t["danger"]}; }}
QProgressBar#BatteryBar[tone="accent"]::chunk  {{ background-color: {t["accent"]}; }}
QProgressBar#BatteryBar[tone="neutral"]::chunk {{ background-color: {t["text_muted"]}; }}

/* Scroll Areas & Lists */
QScrollArea {{
    background: transparent;
    border: none;
}}
QScrollArea > QWidget > QWidget {{
    background: transparent;
}}
QScrollBar:vertical {{
    background: {t["scroll_track"]};
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {t["scroll_thumb"]};
    min-height: 28px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t["scroll_thumb_hover"]};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QListWidget {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
    padding: 6px;
    color: {t["text"]};
    font-size: {FONT["sm"]}px;
    outline: none;
}}
QListWidget::item {{
    padding: 8px 10px;
    border-radius: {RAD["md"]}px;
    margin-bottom: 3px;
}}
QListWidget::item:hover {{
    background-color: {t["surface_hover"]};
}}
QListWidget::item:selected {{
    background-color: {t["accent_tint"]};
    border: 1px solid {t["accent"]};
    color: {t["text"]};
}}

/* Collapsible Developer Log Drawer */
QFrame#DevLogDrawer {{
    background-color: {t["surface_panel"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["lg"]}px;
}}
QPlainTextEdit#DevLogText {{
    background-color: {t["surface_input"]};
    color: {t["text_secondary"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["md"]}px;
    font-family: {t["mono_font"]};
    font-size: {FONT["xs"]}px;
    padding: 6px;
}}

/* Non-Blocking Floating Toast Banner */
QFrame#ToastBanner {{
    background-color: {t["toast_bg"]};
    border: 1px solid {t["border_strong"]};
    border-radius: {RAD["lg"]}px;
}}
QFrame#ToastBanner[tone="success"] {{ border: 1px solid {t["success"]}; }}
QFrame#ToastBanner[tone="warning"] {{ border: 1px solid {t["warning"]}; }}
QFrame#ToastBanner[tone="danger"]  {{ border: 1px solid {t["danger"]}; }}
QFrame#ToastBanner[tone="accent"]  {{ border: 1px solid {t["accent"]}; }}

/* Icon Preview Box */
QLabel#IconPreviewBox {{
    background-color: {t["surface_input"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["md"]}px;
}}

/* Settings Sidebar Navigation */
QFrame#SettingsSidebar {{
    background-color: {t["surface"]};
    border: 1px solid {t["border"]};
    border-radius: {RAD["xl"]}px;
}}
QPushButton#NavItemBtn {{
    background-color: transparent;
    color: {t["text_secondary"]};
    border: 1px solid transparent;
    border-radius: {RAD["md"]}px;
    padding: 9px 12px;
    font-size: {FONT["base"]}px;
    font-weight: 600;
    text-align: left;
}}
QPushButton#NavItemBtn[dir="rtl"] {{
    text-align: right;
}}
QPushButton#NavItemBtn:hover {{
    background-color: {t["surface_hover"]};
    color: {t["text"]};
}}
QPushButton#NavItemBtn[active="true"] {{
    background-color: {t["accent_tint"]};
    color: {t["accent"]};
    border: 1px solid {t["accent_border"]};
    font-weight: 700;
}}
QFrame#DividerLine {{
    background-color: {t["border"]};
    min-height: 1px;
    max-height: 1px;
}}
"""


# ============================================================================
# OUTLINE SVG ICON SYSTEM (ZERO EMOJI ICONS, HIDPI CACHED)
# ============================================================================
SVG_PATHS: dict[str, str] = {
    "battery": '<rect x="2" y="7" width="16" height="10" rx="2"/><line x1="22" y1="11" x2="22" y2="13"/><line x1="6" y1="10" x2="6" y2="14"/><line x1="10" y1="10" x2="10" y2="14"/>',
    "dpi": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="4"/><line x1="12" y1="2" x2="12" y2="5"/><line x1="12" y1="19" x2="12" y2="22"/><line x1="2" y1="12" x2="5" y2="12"/><line x1="19" y1="12" x2="22" y2="12"/>',
    "bolt": '<polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/>',
    "mouse": '<rect x="6" y="3" width="12" height="18" rx="6"/><line x1="12" y1="7" x2="12" y2="11"/>',
    "gamepad": '<rect x="2" y="6" width="20" height="12" rx="4"/><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><circle cx="15.5" cy="11" r="1"/><circle cx="18" cy="13" r="1"/>',
    "settings": '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09a1.65 1.65 0 0 0-1-1.51 1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09a1.65 1.65 0 0 0 1.51-1 1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33h.01a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82v.01a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
    "refresh": '<polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/>',
    "download": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/>',
    "save": '<path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/>',
    "plus": '<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>',
    "radar": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><line x1="12" y1="12" x2="18.36" y2="5.64"/>',
    "edit": '<path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>',
    "trash": '<polyline points="3 6 5 6 21 6"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/><path d="M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
    "pause": '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
    "play": '<polygon points="6 4 20 12 6 20 6 4"/>',
    "folder": '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
    "rotate_ccw": '<polyline points="1 4 1 10 7 10"/><path d="M3.51 15a9 9 0 1 0 2.13-9.36L1 10"/>',
    "terminal": '<polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/>',
    "chevron_down": '<polyline points="6 9 12 15 18 9"/>',
    "chevron_up": '<polyline points="18 15 12 9 6 15"/>',
    "check": '<polyline points="20 6 9 17 4 12"/>',
    "check_circle": '<path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/>',
    "alert": '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/>',
    "info": '<circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/>',
    "copy": '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
    "palette": '<circle cx="13.5" cy="6.5" r=".8"/><circle cx="17.5" cy="10.5" r=".8"/><circle cx="8.5" cy="7.5" r=".8"/><circle cx="6.5" cy="12.5" r=".8"/><path d="M12 2C6.5 2 2 6.5 2 12s4.5 10 10 10c.9 0 1.7-.7 1.7-1.6 0-.4-.2-.8-.4-1.1-.3-.3-.4-.7-.4-1.1 0-.9.7-1.6 1.6-1.6H17c2.8 0 5-2.2 5-5 0-4.9-4.5-9.6-10-9.6z"/>',
    "sun": '<circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/>',
    "moon": '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
    "monitor": '<rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/>',
    "x_circle": '<circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/>',
}

_SVG_CACHE: dict[tuple[str, str, int], QPixmap] = {}


def svg_pixmap(name: str, color: str, size: int = 16) -> QPixmap:
    key = (name, color, size)
    cached = _SVG_CACHE.get(key)
    if cached is not None:
        return cached
    inner = SVG_PATHS.get(name, SVG_PATHS["info"])
    svg_xml = (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" '
        f'viewBox="0 0 24 24" fill="none" stroke="{color}" stroke-width="2" '
        f'stroke-linecap="round" stroke-linejoin="round">{inner}</svg>'
    )
    renderer = QSvgRenderer(QByteArray(svg_xml.encode("utf-8")))
    dpr = 2
    pm = QPixmap(size * dpr, size * dpr)
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing, True)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    _SVG_CACHE[key] = pm
    return pm


def svg_icon(name: str, color: str, size: int = 16) -> QIcon:
    return QIcon(svg_pixmap(name, color, size))


# ============================================================================
# REUSABLE CUSTOM CONTROLS: TOGGLE SWITCH, ACCENT PICKER, DPI CARD, TOAST, DEVLOG
# ============================================================================
class ToggleSwitch(QAbstractButton):
    """Smooth animated pill toggle switch replacing plain QCheckBox."""

    def __init__(self, parent=None, theme: dict[str, str] | None = None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(44, 24)
        self._thumb_pos = 0.0
        self._theme = theme or build_theme()
        self._anim = QPropertyAnimation(self, b"thumbPos", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate_to)

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme
        self.update()

    def _get_thumb_pos(self) -> float:
        return self._thumb_pos

    def _set_thumb_pos(self, val: float):
        self._thumb_pos = float(val)
        self.update()

    thumbPos = Property(float, _get_thumb_pos, _set_thumb_pos)

    def setChecked(self, checked: bool):
        super().setChecked(checked)
        self._thumb_pos = 1.0 if checked else 0.0
        self.update()

    def _animate_to(self, checked: bool):
        self._anim.stop()
        self._anim.setStartValue(self._thumb_pos)
        self._anim.setEndValue(1.0 if checked else 0.0)
        self._anim.start()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        r = h / 2.0
        track_col = QColor(self._theme["accent"] if self.isChecked() else self._theme["surface_input"])
        border_col = QColor(self._theme["accent"] if self.isChecked() else self._theme["border_strong"])
        p.setBrush(track_col)
        p.setPen(border_col)
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), r, r)

        margin = 3.0
        knob_d = h - 2.0 * margin
        travel = w - 2.0 * margin - knob_d
        pos = self._thumb_pos
        if self.layoutDirection() == Qt.RightToLeft:
            x = margin + (1.0 - pos) * travel
        else:
            x = margin + pos * travel
        knob_col = QColor(self._theme["accent_fg"] if self.isChecked() else self._theme["text_secondary"])
        p.setPen(Qt.NoPen)
        p.setBrush(knob_col)
        p.drawEllipse(QRectF(x, margin, knob_d, knob_d))
        p.end()


class StyledSpinBox(QSpinBox):
    """RTL-safe, HiDPI-crisp QSpinBox with >=26px up/down buttons and scalable SVG chevrons."""

    def __init__(self, parent=None, theme: dict[str, str] | None = None):
        super().__init__(parent)
        self._theme = theme or build_theme()
        self.setLayoutDirection(Qt.LeftToRight)
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumSize(116, 36)

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        opt = QStyleOptionSpinBox()
        self.initStyleOption(opt)
        up_rect = self.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxUp, self)
        dn_rect = self.style().subControlRect(QStyle.CC_SpinBox, opt, QStyle.SC_SpinBoxDown, self)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        col = self._theme["text_secondary"]
        ic_sz = max(10, min(14, min(up_rect.width(), up_rect.height()) - 2))
        up_pm = svg_pixmap("chevron_up", col, ic_sz)
        dn_pm = svg_pixmap("chevron_down", col, ic_sz)
        p.drawPixmap(
            up_rect.x() + (up_rect.width() - ic_sz) // 2,
            up_rect.y() + (up_rect.height() - ic_sz) // 2,
            ic_sz, ic_sz, up_pm,
        )
        p.drawPixmap(
            dn_rect.x() + (dn_rect.width() - ic_sz) // 2,
            dn_rect.y() + (dn_rect.height() - ic_sz) // 2,
            ic_sz, ic_sz, dn_pm,
        )
        p.end()


class BatteryIndicatorWidget(QWidget):
    """
    Animated semantic battery indicator supporting 5 styles:
      - classic:   Classic horizontal battery with terminal cap
      - pill:      Rounded pill capsule
      - ring:      Circular progress ring
      - vertical:  Vertical battery cell with top terminal cap
      - segmented: 8 segmented bars
    Uses semantic green/amber/red colors (independent of UI accent color), smooth level animation,
    gentle pulse when charging, subtle blink when < 15%, and zero-CPU pause when hidden/minimized.
    """

    def __init__(self, parent=None, theme: dict[str, str] | None = None, compact: bool = True):
        super().__init__(parent)
        self._theme = theme or build_theme()
        self._compact = compact
        self._style_name = "classic"
        self._level: int | None = None
        self._display_level = 0.0
        self._charging = False
        self._sleeping = False
        self._connected = False
        self._pulse_phase = 0.0
        self._paused = False

        self._fill_anim = QPropertyAnimation(self, b"displayLevel", self)
        self._fill_anim.setDuration(420)
        self._fill_anim.setEasingCurve(QEasingCurve.OutCubic)

        self._pulse_anim = QPropertyAnimation(self, b"pulsePhase", self)
        self._pulse_anim.setStartValue(0.0)
        self._pulse_anim.setKeyValueAt(0.5, 1.0)
        self._pulse_anim.setEndValue(0.0)
        self._pulse_anim.setLoopCount(-1)
        self._pulse_anim.setEasingCurve(QEasingCurve.InOutSine)

        self.setMinimumSize(112 if compact else 150, 28 if compact else 44)
        self.setFixedHeight(28 if compact else 44)

    def _get_display_level(self) -> float:
        return self._display_level

    def _set_display_level(self, val: float):
        self._display_level = max(0.0, min(100.0, float(val)))
        self.update()

    displayLevel = Property(float, _get_display_level, _set_display_level)

    def _get_pulse_phase(self) -> float:
        return self._pulse_phase

    def _set_pulse_phase(self, val: float):
        self._pulse_phase = max(0.0, min(1.0, float(val)))
        self.update()

    pulsePhase = Property(float, _get_pulse_phase, _set_pulse_phase)

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme
        self.update()

    def set_style_name(self, style_name: str):
        if style_name in BATTERY_STYLES:
            self._style_name = style_name
            self.update()

    def set_state(
        self,
        connected: bool,
        level: int | None,
        charging: bool = False,
        sleeping: bool = False,
        animate: bool = True,
    ):
        self._connected = bool(connected)
        self._level = max(0, min(100, int(level))) if level is not None else None
        self._charging = bool(charging)
        self._sleeping = bool(sleeping)

        target = float(self._level) if self._level is not None else (100.0 if (self._connected and self._charging) else 0.0)
        if animate and not self._paused and abs(target - self._display_level) > 0.5:
            self._fill_anim.stop()
            self._fill_anim.setStartValue(self._display_level)
            self._fill_anim.setEndValue(target)
            self._fill_anim.start()
        else:
            self._fill_anim.stop()
            self._display_level = target

        self._sync_pulse_animation()
        self.update()

    def _sync_pulse_animation(self):
        if self._paused or not self._connected:
            self._pulse_anim.stop()
            self._pulse_phase = 0.0
            return
        is_low = (self._level is not None and self._level < 15 and not self._charging)
        if self._charging:
            if self._pulse_anim.duration() != 1600 or self._pulse_anim.state() != QPropertyAnimation.Running:
                self._pulse_anim.stop()
                self._pulse_anim.setDuration(1600)
                self._pulse_anim.start()
        elif is_low:
            if self._pulse_anim.duration() != 1100 or self._pulse_anim.state() != QPropertyAnimation.Running:
                self._pulse_anim.stop()
                self._pulse_anim.setDuration(1100)
                self._pulse_anim.start()
        else:
            self._pulse_anim.stop()
            self._pulse_phase = 0.0

    def set_animations_paused(self, paused: bool):
        self._paused = bool(paused)
        if self._paused:
            self._fill_anim.stop()
            self._pulse_anim.stop()
            self._pulse_phase = 0.0
        else:
            self._sync_pulse_animation()

    def _semantic_color(self) -> QColor:
        if not self._connected:
            return QColor(self._theme["text_muted"])
        if self._sleeping and self._level is None:
            return QColor(self._theme["warning"])
        if self._charging:
            col = QColor(self._theme["success"])
            # Gentle charging breathing opacity (0.72..1.0)
            col.setAlphaF(0.72 + 0.28 * (1.0 - self._pulse_phase))
            return col
        if self._level is None:
            return QColor(self._theme["text_muted"])
        if self._level >= 40:
            return QColor(self._theme["success"])
        if self._level >= 15:
            return QColor(self._theme["warning"])
        # Low battery (<15%): subtle blink (0.48..1.0)
        col = QColor(self._theme["danger"])
        col.setAlphaF(0.48 + 0.52 * (1.0 - self._pulse_phase))
        return col

    def _pct_text(self) -> str:
        if not self._connected:
            return "--%"
        if self._level is not None:
            return f"{self._level}%"
        if self._charging:
            return "USB"
        return "--%"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        w, h = self.width(), self.height()
        fill_col = self._semantic_color()
        outline_col = QColor(self._theme["border_strong"])
        track_col = QColor(self._theme["surface_input"])
        text_col = QColor(self._theme["text"])
        frac = max(0.0, min(1.0, self._display_level / 100.0))

        # Reserve crisp space for percentage label on the right (always LTR numeric)
        txt = self._pct_text()
        pct_w = 40 if self._compact else 48
        gx = 2
        gw = max(36, w - pct_w - 6)
        st = self._style_name

        if st == "classic":
            bh = 16 if self._compact else 24
            by = (h - bh) / 2.0
            cap_w = 4
            body_w = gw - cap_w - 2
            body_rect = QRectF(gx, by, body_w, bh)
            p.setBrush(track_col)
            p.setPen(QPen(outline_col, 1.5))
            p.drawRoundedRect(body_rect, 4, 4)
            # Positive terminal cap
            cap_h = bh * 0.48
            p.setBrush(outline_col)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(gx + body_w + 1, by + (bh - cap_h) / 2.0, cap_w, cap_h), 1.5, 1.5)
            # Animated inner fill
            pad = 2.5
            inner_w = max(0.0, (body_w - 2 * pad) * frac)
            if inner_w > 0.5:
                p.setBrush(fill_col)
                p.drawRoundedRect(QRectF(gx + pad, by + pad, inner_w, bh - 2 * pad), 2.5, 2.5)
            if self._charging:
                bolt_sz = 11 if self._compact else 14
                bp = svg_pixmap("bolt", "#FFFFFF", bolt_sz)
                p.drawPixmap(int(gx + (body_w - bolt_sz) / 2), int(by + (bh - bolt_sz) / 2), bolt_sz, bolt_sz, bp)

        elif st == "pill":
            bh = 14 if self._compact else 20
            by = (h - bh) / 2.0
            rad = bh / 2.0
            p.setBrush(track_col)
            p.setPen(QPen(outline_col, 1.3))
            p.drawRoundedRect(QRectF(gx, by, gw, bh), rad, rad)
            pad = 2.0
            inner_w = max(0.0, (gw - 2 * pad) * frac)
            if inner_w > 1.0:
                p.setBrush(fill_col)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(gx + pad, by + pad, max(bh - 2 * pad, inner_w), bh - 2 * pad), rad - 1.5, rad - 1.5)

        elif st == "ring":
            d = min(h - 4, 24 if self._compact else 38)
            rx = gx + max(0.0, (gw - d) / 2.0)
            ry = (h - d) / 2.0
            pen_w = 3.2 if self._compact else 4.5
            ring_rect = QRectF(rx + pen_w / 2, ry + pen_w / 2, d - pen_w, d - pen_w)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(outline_col, pen_w, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(ring_rect)
            if frac > 0.005:
                p.setPen(QPen(fill_col, pen_w, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(ring_rect, 90 * 16, int(-360 * 16 * frac))
            if self._charging:
                bolt_sz = 10 if self._compact else 14
                bp = svg_pixmap("bolt", fill_col.name(), bolt_sz)
                p.drawPixmap(int(rx + (d - bolt_sz) / 2), int(ry + (d - bolt_sz) / 2), bolt_sz, bolt_sz, bp)

        elif st == "vertical":
            vw = 14 if self._compact else 20
            vh = h - 6
            vx = gx + max(0.0, (gw - vw) / 2.0)
            vy = 4.0
            cap_h = 3.0
            cap_w = vw * 0.46
            p.setBrush(outline_col)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(vx + (vw - cap_w) / 2.0, vy - 1.5, cap_w, cap_h), 1.2, 1.2)
            body_rect = QRectF(vx, vy + cap_h - 0.5, vw, vh - cap_h)
            p.setBrush(track_col)
            p.setPen(QPen(outline_col, 1.4))
            p.drawRoundedRect(body_rect, 3.5, 3.5)
            pad = 2.2
            avail_h = max(0.0, body_rect.height() - 2 * pad)
            fill_h = avail_h * frac
            if fill_h > 0.5:
                p.setBrush(fill_col)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(
                    QRectF(body_rect.x() + pad, body_rect.bottom() - pad - fill_h, vw - 2 * pad, fill_h),
                    2.0, 2.0,
                )

        else:  # segmented (8 crisp segments)
            segs = 8
            gap = 3.0
            sh = 14 if self._compact else 20
            sy = (h - sh) / 2.0
            seg_w = max(4.0, (gw - gap * (segs - 1)) / segs)
            exact_lit = frac * segs
            for idx in range(segs):
                sx = gx + idx * (seg_w + gap)
                rect = QRectF(sx, sy, seg_w, sh)
                p.setBrush(track_col)
                p.setPen(QPen(outline_col, 1.0))
                p.drawRoundedRect(rect, 2.5, 2.5)
                seg_fill = max(0.0, min(1.0, exact_lit - idx))
                if seg_fill > 0.05:
                    col = QColor(fill_col)
                    col.setAlphaF(col.alphaF() * (0.35 + 0.65 * seg_fill))
                    p.setBrush(col)
                    p.setPen(Qt.NoPen)
                    p.drawRoundedRect(QRectF(sx + 1, sy + 1, seg_w - 2, sh - 2), 2.0, 2.0)

        # Crisp Monospace Percentage Text
        font = QFont("Consolas", 10 if self._compact else 12, QFont.Bold)
        p.setFont(font)
        p.setPen(fill_col if (self._connected and (self._level is not None or self._charging)) else text_col)
        p.drawText(QRectF(gx + gw + 4, 0, pct_w, h), Qt.AlignVCenter | Qt.AlignRight, txt)
        p.end()


class ClickableDpiCard(QFrame):
    """DPI stage card that highlights border + accent tint when selected and clicks anywhere."""
    clicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("DpiCard")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)

    def set_selected(self, selected: bool):
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class AccentColorPickerWidget(QWidget):
    """User-chosen accent color control: 8 preset swatches + hex input + custom QColorDialog."""
    accent_changed = Signal(str)

    def __init__(self, initial_hex: str, theme: dict[str, str], lang: str = "ar", parent=None):
        super().__init__(parent)
        self._hex = initial_hex.upper()
        self._theme = theme
        self._lang = lang
        self._swatch_btns: list[tuple[str, QPushButton]] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(SP["sm"])

        sw_row = QHBoxLayout()
        sw_row.setSpacing(SP["sm"])
        for hx, name in ACCENT_PRESETS:
            b = QPushButton()
            b.setFixedSize(28, 28)
            b.setCursor(Qt.PointingHandCursor)
            b.setToolTip(f"{name} ({hx})")
            b.clicked.connect(lambda checked=False, c=hx: self._select_hex(c))
            sw_row.addWidget(b)
            self._swatch_btns.append((hx, b))
        sw_row.addStretch()
        root.addLayout(sw_row)

        custom_row = QHBoxLayout()
        custom_row.setSpacing(SP["sm"])
        self.txt_hex = QLineEdit(self._hex)
        self.txt_hex.setObjectName("HexInput")
        self.txt_hex.setFixedWidth(104)
        self.txt_hex.setMaxLength(7)
        self.txt_hex.setLayoutDirection(Qt.LeftToRight)
        self.txt_hex.editingFinished.connect(self._on_hex_edited)
        custom_row.addWidget(self.txt_hex)

        self.btn_custom = QPushButton()
        self.btn_custom.setObjectName("SecondaryBtn")
        self.btn_custom.clicked.connect(self._open_color_dialog)
        custom_row.addWidget(self.btn_custom)
        custom_row.addStretch()
        root.addLayout(custom_row)

        self.refresh(self._hex, self._theme, self._lang)

    def refresh(self, accent_hex: str, theme: dict[str, str], lang: str):
        self._hex = accent_hex.upper()
        self._theme = theme
        self._lang = lang
        self.txt_hex.blockSignals(True)
        self.txt_hex.setText(self._hex)
        self.txt_hex.blockSignals(False)
        self.btn_custom.setText(tr("set_accent_pick", lang))
        self.btn_custom.setIcon(svg_icon("palette", theme["text"], 14))

        for hx, b in self._swatch_btns:
            is_sel = (hx.upper() == self._hex)
            ring = theme["text"] if is_sel else theme["border_strong"]
            bw = 2 if is_sel else 1
            b.setStyleSheet(
                f"QPushButton {{ background-color: {hx}; border: {bw}px solid {ring}; border-radius: 14px; }}"
            )
            if is_sel:
                b.setIcon(svg_icon("check", pick_readable_fg(hx), 14))
            else:
                b.setIcon(QIcon())

    def _select_hex(self, hx: str):
        clean = hx.strip().upper()
        if re.fullmatch(r"#[0-9A-F]{6}", clean) and clean != self._hex:
            self._hex = clean
            self.accent_changed.emit(clean)

    def _on_hex_edited(self):
        raw = self.txt_hex.text().strip().upper()
        if raw and not raw.startswith("#"):
            raw = "#" + raw
        if re.fullmatch(r"#[0-9A-F]{6}", raw):
            self._select_hex(raw)
        else:
            self.txt_hex.setText(self._hex)

    def _open_color_dialog(self):
        col = QColorDialog.getColor(QColor(self._hex), self, tr("set_accent_pick", self._lang))
        if col.isValid():
            self._select_hex(col.name().upper())


class ToastBanner(QFrame):
    """Non-blocking floating toast notification inside the main window."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("ToastBanner")
        self.setProperty("tone", "accent")
        self.hide()

        lay = QHBoxLayout(self)
        lay.setContentsMargins(SP["md"], SP["sm"], SP["md"], SP["sm"])
        lay.setSpacing(SP["sm"])

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(16, 16)
        lay.addWidget(self.lbl_icon)

        self.lbl_text = QLabel()
        self.lbl_text.setObjectName("StatusText")
        lay.addWidget(self.lbl_text)

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self.hide)

    def show_toast(self, text: str, tone: str, theme: dict[str, str], duration_ms: int = 3000):
        self.setProperty("tone", tone)
        self.style().unpolish(self)
        self.style().polish(self)

        icon_name = "check_circle" if tone == "success" else ("alert" if tone in ("warning", "danger") else "info")
        col_key = tone if tone in ("success", "warning", "danger", "accent") else "text"
        self.lbl_icon.setPixmap(svg_pixmap(icon_name, theme[col_key], 16))
        self.lbl_text.setText(text)
        self.lbl_text.setProperty("tone", tone)
        self.lbl_text.style().unpolish(self.lbl_text)
        self.lbl_text.style().polish(self.lbl_text)

        self.adjustSize()
        self.reposition()
        self.raise_()
        self.show()
        self._hide_timer.start(duration_ms)

    def reposition(self):
        p = self.parentWidget()
        if not p:
            return
        x = max(SP["lg"], (p.width() - self.width()) // 2)
        y = max(SP["lg"], p.height() - self.height() - 64)
        self.move(x, y)


class DeveloperLogDrawer(QFrame):
    """Collapsible Developer Log (collapsed by default) holding raw HID hex & diagnostic logs."""

    def __init__(self, theme: dict[str, str], lang: str = "ar", parent=None):
        super().__init__(parent)
        self.setObjectName("DevLogDrawer")
        self._theme = theme
        self._lang = lang
        self._expanded = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["md"], 6, SP["md"], 6)
        lay.setSpacing(SP["sm"])

        bar = QHBoxLayout()
        bar.setSpacing(SP["sm"])

        self.btn_toggle = QPushButton()
        self.btn_toggle.setObjectName("GhostBtn")
        self.btn_toggle.clicked.connect(self.toggle_expanded)
        bar.addWidget(self.btn_toggle)

        self.lbl_count = QLabel("0")
        self.lbl_count.setObjectName("Badge")
        self.lbl_count.setProperty("tone", "neutral")
        self.lbl_count.setProperty("mono", "true")
        bar.addWidget(self.lbl_count)
        bar.addStretch()

        self.btn_copy = QPushButton()
        self.btn_copy.setObjectName("GhostBtn")
        self.btn_copy.clicked.connect(self._copy_all)
        self.btn_copy.setVisible(False)
        bar.addWidget(self.btn_copy)

        self.btn_clear = QPushButton()
        self.btn_clear.setObjectName("GhostBtn")
        self.btn_clear.clicked.connect(self._clear_all)
        self.btn_clear.setVisible(False)
        bar.addWidget(self.btn_clear)

        lay.addLayout(bar)

        self.txt_log = QPlainTextEdit()
        self.txt_log.setObjectName("DevLogText")
        self.txt_log.setReadOnly(True)
        self.txt_log.setMaximumBlockCount(400)
        self.txt_log.setFixedHeight(130)
        self.txt_log.setLayoutDirection(Qt.LeftToRight)
        self.txt_log.setVisible(False)
        lay.addWidget(self.txt_log)

        for existing in APP_LOG.snapshot():
            self.txt_log.appendPlainText(existing)
        self._update_count()
        APP_LOG.entry_added.connect(self.append_line)
        self.refresh_theme_and_lang(theme, lang)

    def append_line(self, line: str):
        self.txt_log.appendPlainText(line)
        self._update_count()

    def _update_count(self):
        n = self.txt_log.blockCount() if self.txt_log.toPlainText().strip() else 0
        self.lbl_count.setText(str(n))

    def toggle_expanded(self):
        self._expanded = not self._expanded
        self.txt_log.setVisible(self._expanded)
        self.btn_copy.setVisible(self._expanded)
        self.btn_clear.setVisible(self._expanded)
        self._refresh_toggle_icon()

    def _refresh_toggle_icon(self):
        ic = "chevron_up" if self._expanded else "chevron_down"
        self.btn_toggle.setIcon(svg_icon(ic, self._theme["text_secondary"], 14))

    def refresh_theme_and_lang(self, theme: dict[str, str], lang: str):
        self._theme = theme
        self._lang = lang
        self.btn_toggle.setText(tr("devlog_title", lang))
        self.btn_copy.setText(tr("devlog_copy", lang))
        self.btn_copy.setIcon(svg_icon("copy", theme["text_secondary"], 13))
        self.btn_clear.setText(tr("devlog_clear", lang))
        self.btn_clear.setIcon(svg_icon("trash", theme["text_secondary"], 13))
        self._refresh_toggle_icon()

    def _copy_all(self):
        cb = QApplication.clipboard()
        if cb:
            cb.setText(self.txt_log.toPlainText())
            self.btn_copy.setText(tr("devlog_copied", self._lang))
            QTimer.singleShot(1400, lambda: self.btn_copy.setText(tr("devlog_copy", self._lang)))

    def _clear_all(self):
        APP_LOG.clear()
        self.txt_log.clear()
        self._update_count()


class GM80InteractiveMouseWidget(QWidget):
    """
    High-DPI animated top-down silhouette of the Aigo GM80 Plus mouse.
    Modeled directly on official GM80 Plus proportions (split paddles, angled V-notch seam,
    center DPI LED, ribbed scroll wheel with silver side rims, and left-flank side buttons).
    Responds live to physical mouse presses/scrolls and hover/click interaction with zero idle CPU.

    Button indices (matching official 7 remappable inputs 1..7):
      0: Left-Click   1: Right-Click   2: Middle-Click
      3: Forward (upper/front side)    4: Backward (lower/rear side)
      5: Scroll Up                     6: Scroll Down
    """
    button_clicked = Signal(int)
    button_hovered = Signal(int)  # -1 when no button hovered

    _CANVAS_W = 264.0
    _CANVAS_H = 340.0

    def __init__(self, theme: dict[str, str], dpi_led_hex: str = "#22C55E", parent=None):
        super().__init__(parent)
        self._theme = theme
        self._dpi_led_hex = dpi_led_hex
        self._hover_idx: int = -1
        self._external_hover_idx: int = -1
        self._held: list[bool] = [False] * 7
        self._intensity: list[float] = [0.0] * 7
        self._ripple: list[float] = [0.0] * 7
        self._wheel_phase: float = 0.0
        self._wheel_vel: float = 0.0
        self._paused: bool = False

        self.setMouseTracking(True)
        self.setMinimumSize(244, 316)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setLayoutDirection(Qt.LeftToRight)

        self._anim_timer = QTimer(self)
        self._anim_timer.setInterval(16)
        self._anim_timer.timeout.connect(self._tick_animation)

    def set_theme(self, theme: dict[str, str]):
        self._theme = theme
        self.update()

    def set_dpi_led_color(self, hex_color: str):
        self._dpi_led_hex = hex_color or "#22C55E"
        self.update()

    def set_external_hover(self, idx: int):
        if self._external_hover_idx != idx:
            self._external_hover_idx = idx
            self.update()

    def set_animations_paused(self, paused: bool):
        self._paused = bool(paused)
        if paused:
            self._anim_timer.stop()
            for i in range(7):
                self._held[i] = False
                self._intensity[i] = 0.0
                self._ripple[i] = 0.0
            self._wheel_vel = 0.0
            self.update()

    def trigger_press(self, idx: int, hold: bool = False):
        """Animate button index (0..6) with press glow + ripple; auto-decays when released."""
        if not (0 <= idx < 7) or self._paused:
            return
        self._intensity[idx] = 1.0
        self._ripple[idx] = 0.08
        if hold:
            self._held[idx] = True
        if idx == 5:
            self._wheel_vel = -2.8
        elif idx == 6:
            self._wheel_vel = 2.8
        if not self._anim_timer.isActive():
            self._anim_timer.start()
        self.update()

    def trigger_release(self, idx: int):
        if 0 <= idx < 7:
            self._held[idx] = False
            if not self._anim_timer.isActive() and (self._intensity[idx] > 0.001 or self._ripple[idx] > 0.001):
                self._anim_timer.start()

    def _tick_animation(self):
        if self._paused:
            self._anim_timer.stop()
            return
        any_active = False
        for i in range(7):
            if self._held[i]:
                self._intensity[i] = min(1.0, self._intensity[i] + 0.25)
                any_active = True
            elif self._intensity[i] > 0.01:
                self._intensity[i] *= 0.84
                if self._intensity[i] <= 0.01:
                    self._intensity[i] = 0.0
                else:
                    any_active = True

            if self._ripple[i] > 0.001:
                self._ripple[i] += 0.085
                if self._ripple[i] >= 1.0:
                    self._ripple[i] = 0.0
                else:
                    any_active = True

        if abs(self._wheel_vel) > 0.05:
            self._wheel_phase = (self._wheel_phase + self._wheel_vel) % 10.0
            self._wheel_vel *= 0.86
            any_active = True
        else:
            self._wheel_vel = 0.0

        self.update()
        if not any_active:
            self._anim_timer.stop()

    def _canvas_transform(self) -> tuple[float, float, float]:
        scale = min(self.width() / self._CANVAS_W, self.height() / self._CANVAS_H)
        ox = (self.width() - self._CANVAS_W * scale) * 0.5
        oy = (self.height() - self._CANVAS_H * scale) * 0.5
        return scale, ox, oy

    def _to_canvas(self, pos: QPointF) -> QPointF:
        scale, ox, oy = self._canvas_transform()
        if scale <= 0.001:
            return QPointF(-100, -100)
        return QPointF((pos.x() - ox) / scale, (pos.y() - oy) / scale)

    @staticmethod
    def _body_path() -> QPainterPath:
        """Exact Aigo GM80 Plus symmetrical lightweight shell silhouette."""
        p = QPainterPath()
        # Top center nose (cx=132)
        p.moveTo(132.0, 46.0)
        # Front-right crown -> right cheek -> waist -> rounded palm heel
        p.cubicTo(166.0, 46.0, 192.0, 62.0, 198.0, 98.0)
        p.cubicTo(203.0, 130.0, 204.0, 166.0, 200.0, 206.0)
        p.cubicTo(195.0, 250.0, 174.0, 294.0, 132.0, 294.0)
        # Mirror left side back to top center
        p.cubicTo(90.0, 294.0, 69.0, 250.0, 64.0, 206.0)
        p.cubicTo(60.0, 166.0, 61.0, 130.0, 66.0, 98.0)
        p.cubicTo(72.0, 62.0, 98.0, 46.0, 132.0, 46.0)
        p.closeSubpath()
        return p

    @staticmethod
    def _left_paddle_path() -> QPainterPath:
        """Left-Click paddle bounded by center split, wheel well, and angled GM80 Plus V-seam."""
        p = QPainterPath()
        p.moveTo(129.0, 46.5)
        p.cubicTo(98.0, 46.5, 73.0, 62.5, 67.2, 98.0)
        p.cubicTo(63.6, 120.0, 62.5, 141.0, 62.5, 159.5)
        # Signature GM80 Plus angled notch seam heading toward center DPI LED
        p.lineTo(100.0, 159.5)
        p.lineTo(108.0, 151.5)
        p.lineTo(130.0, 151.5)
        p.lineTo(130.0, 118.0)
        # Cut around left side of recessed scroll well
        p.cubicTo(120.0, 118.0, 118.0, 113.0, 118.0, 105.0)
        p.lineTo(118.0, 77.0)
        p.cubicTo(118.0, 69.0, 121.0, 65.0, 129.0, 65.0)
        p.closeSubpath()
        return p

    @staticmethod
    def _right_paddle_path() -> QPainterPath:
        """Right-Click paddle (mirror of left paddle)."""
        p = QPainterPath()
        p.moveTo(135.0, 46.5)
        p.cubicTo(166.0, 46.5, 191.0, 62.5, 196.8, 98.0)
        p.cubicTo(200.4, 120.0, 201.5, 141.0, 201.5, 159.5)
        p.lineTo(164.0, 159.5)
        p.lineTo(156.0, 151.5)
        p.lineTo(134.0, 151.5)
        p.lineTo(134.0, 118.0)
        p.cubicTo(144.0, 118.0, 146.0, 113.0, 146.0, 105.0)
        p.lineTo(146.0, 77.0)
        p.cubicTo(146.0, 69.0, 143.0, 65.0, 135.0, 65.0)
        p.closeSubpath()
        return p

    @staticmethod
    def _wheel_rect() -> QRectF:
        return QRectF(122.0, 70.0, 20.0, 43.0)

    @staticmethod
    def _side_forward_rect(press_amt: float = 0.0) -> QRectF:
        return QRectF(54.0 + press_amt * 2.8, 123.0, 8.5, 34.0)

    @staticmethod
    def _side_backward_rect(press_amt: float = 0.0) -> QRectF:
        return QRectF(53.5 + press_amt * 2.8, 164.0, 8.5, 34.0)

    @staticmethod
    def _badge_specs() -> list[tuple[int, QPointF, QPointF]]:
        """(button_idx, badge_center, anchor_point_on_mouse)."""
        return [
            (0, QPointF(30.0, 80.0),  QPointF(86.0, 96.0)),   # 1: Left-Click
            (1, QPointF(234.0, 80.0), QPointF(178.0, 96.0)),  # 2: Right-Click
            (2, QPointF(234.0, 126.0), QPointF(142.0, 92.0)), # 3: Middle-Click
            (3, QPointF(26.0, 140.0), QPointF(54.0, 140.0)),  # 4: Forward (Front Side)
            (4, QPointF(26.0, 181.0), QPointF(54.0, 181.0)),  # 5: Backward (Rear Side)
            (5, QPointF(132.0, 18.0), QPointF(132.0, 42.0)),  # 6: Scroll Up
            (6, QPointF(234.0, 174.0), QPointF(138.0, 124.0)),# 7: Scroll Down
        ]

    def _hit_test(self, pt: QPointF) -> int:
        # Check badges first
        for idx, bpos, _ in self._badge_specs():
            if (pt.x() - bpos.x()) ** 2 + (pt.y() - bpos.y()) ** 2 <= 14.5 ** 2:
                return idx
        # Check scroll up/down zones near wheel
        if QRectF(116.0, 34.0, 32.0, 32.0).contains(pt):
            return 5
        if QRectF(116.0, 114.0, 32.0, 26.0).contains(pt):
            return 6
        if self._wheel_rect().adjusted(-3, -2, 3, 2).contains(pt):
            return 2
        if self._side_forward_rect().adjusted(-5, -3, 4, 3).contains(pt):
            return 3
        if self._side_backward_rect().adjusted(-5, -3, 4, 3).contains(pt):
            return 4
        if self._left_paddle_path().contains(pt):
            return 0
        if self._right_paddle_path().contains(pt):
            return 1
        return -1

    def mouseMoveEvent(self, event):
        idx = self._hit_test(self._to_canvas(event.position()))
        if idx != self._hover_idx:
            self._hover_idx = idx
            self.setCursor(Qt.PointingHandCursor if idx >= 0 else Qt.ArrowCursor)
            self.button_hovered.emit(idx)
            self.update()
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        if self._hover_idx != -1:
            self._hover_idx = -1
            self.button_hovered.emit(-1)
            self.update()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        b = event.button()
        hit = self._hit_test(self._to_canvas(event.position()))
        if b == Qt.LeftButton and hit >= 0:
            self.trigger_press(hit, hold=(hit not in (5, 6)))
            self.button_clicked.emit(hit)
            event.accept()
            return
        btn_map = {
            Qt.LeftButton: 0,
            Qt.RightButton: 1,
            Qt.MiddleButton: 2,
            Qt.ForwardButton: 3,
            Qt.BackButton: 4,
        }
        if b in btn_map:
            bi = btn_map[b]
            self.trigger_press(bi, hold=True)
            self.button_clicked.emit(bi)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        for i in range(5):
            if self._held[i]:
                self.trigger_release(i)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        dy = event.angleDelta().y()
        if dy > 0:
            self.trigger_press(5, hold=False)
            self.button_clicked.emit(5)
            event.accept()
            return
        if dy < 0:
            self.trigger_press(6, hold=False)
            self.button_clicked.emit(6)
            event.accept()
            return
        super().wheelEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        scale, ox, oy = self._canvas_transform()
        p.translate(ox, oy)
        p.scale(scale, scale)

        t = self._theme
        is_dark = (t["mode"] == "dark")
        accent = QColor(t["accent"])
        active_hover = self._hover_idx if self._hover_idx >= 0 else self._external_hover_idx

        # ── 1. Soft Ambient Shadow under Mouse Body ──
        body = self._body_path()
        p.save()
        p.translate(0.0, 5.0)
        p.fillPath(body, QColor(0, 0, 0, 76 if is_dark else 34))
        p.restore()

        # Subtle outer accent halo when any button is pressed
        max_int = max(self._intensity)
        if max_int > 0.02:
            halo = QColor(accent)
            halo.setAlpha(int(round(48 * max_int)))
            p.setPen(QPen(halo, 6.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(body)

        # ── 2. Main Contoured Shell (Matte Graphite / Frost Slate) ──
        shell_grad = QLinearGradient(64.0, 46.0, 200.0, 294.0)
        if is_dark:
            shell_grad.setColorAt(0.0, QColor("#3A404B"))
            shell_grad.setColorAt(0.45, QColor("#272C35"))
            shell_grad.setColorAt(1.0, QColor("#1A1D24"))
            shell_border = QColor("#4A5262")
        else:
            shell_grad.setColorAt(0.0, QColor("#F3F6FA"))
            shell_grad.setColorAt(0.48, QColor("#DDE5EF"))
            shell_grad.setColorAt(1.0, QColor("#C6D2E1"))
            shell_border = QColor("#94A3B8")

        p.setBrush(shell_grad)
        p.setPen(QPen(shell_border, 1.5))
        p.drawPath(body)

        # Subtle rear palm highlight sheen
        sheen = QRadialGradient(132.0, 218.0, 62.0)
        sheen.setColorAt(0.0, QColor(255, 255, 255, 18 if is_dark else 65))
        sheen.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setClipPath(body)
        p.fillRect(QRectF(60.0, 155.0, 144.0, 142.0), sheen)
        p.setClipping(False)

        # ── 3. Split Left & Right Paddles with Interactive Press Glow + Ripple ──
        paddles = [
            (0, self._left_paddle_path(), QPointF(94.0, 102.0)),
            (1, self._right_paddle_path(), QPointF(170.0, 102.0)),
        ]
        for idx, ppath, center_pt in paddles:
            inten = self._intensity[idx]
            hov = (active_hover == idx)
            p_grad = QLinearGradient(center_pt.x(), 46.0, center_pt.x(), 160.0)
            if is_dark:
                top_c = QColor("#454C59" if hov else "#3F4652")
                bot_c = QColor("#2E343F" if hov else "#292E38")
            else:
                top_c = QColor("#FFFFFF" if hov else "#F5F8FC")
                bot_c = QColor("#E2E9F2" if hov else "#DCE4EF")
            if inten > 0.01:
                top_c = QColor(
                    int(top_c.red() * (1 - 0.55 * inten) + accent.red() * (0.55 * inten)),
                    int(top_c.green() * (1 - 0.55 * inten) + accent.green() * (0.55 * inten)),
                    int(top_c.blue() * (1 - 0.55 * inten) + accent.blue() * (0.55 * inten)),
                )
                bot_c = QColor(
                    int(bot_c.red() * (1 - 0.38 * inten) + accent.red() * (0.38 * inten)),
                    int(bot_c.green() * (1 - 0.38 * inten) + accent.green() * (0.38 * inten)),
                    int(bot_c.blue() * (1 - 0.38 * inten) + accent.blue() * (0.38 * inten)),
                )
            p_grad.setColorAt(0.0, top_c)
            p_grad.setColorAt(1.0, bot_c)

            border_c = QColor(accent) if (inten > 0.05 or hov) else QColor("#15181E" if is_dark else "#9AA8BA")
            if hov and inten <= 0.05:
                border_c.setAlpha(185)
            p.setBrush(p_grad)
            p.setPen(QPen(border_c, 1.8 if (inten > 0.05 or hov) else 1.2))
            p.drawPath(ppath)

            # Expanding press ripple inside paddle
            rip = self._ripple[idx]
            if rip > 0.01:
                p.save()
                p.setClipPath(ppath)
                rad = 10.0 + rip * 44.0
                rc = QColor(accent)
                rc.setAlpha(int(round(170 * (1.0 - rip))))
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(rc, 2.2))
                p.drawEllipse(center_pt, rad, rad)
                p.restore()

        # ── 4. Center Vertical Gap & Signature Angled V-Notch Seam ──
        seam_col = QColor("#0E1015" if is_dark else "#8B99AC")
        p.setPen(QPen(seam_col, 2.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawLine(QPointF(132.0, 118.0), QPointF(132.0, 150.0))
        seam = QPainterPath()
        seam.moveTo(63.0, 160.0)
        seam.lineTo(100.0, 160.0)
        seam.lineTo(108.0, 152.0)
        seam.lineTo(156.0, 152.0)
        seam.lineTo(164.0, 160.0)
        seam.lineTo(201.0, 160.0)
        p.setBrush(Qt.NoBrush)
        p.drawPath(seam)

        # ── 5. Signature Centered DPI Status LED (synced to active DPI color!) ──
        led_col = QColor(self._dpi_led_hex)
        led_glow = QRadialGradient(132.0, 154.0, 14.0)
        gc0 = QColor(led_col)
        gc0.setAlpha(130)
        gc1 = QColor(led_col)
        gc1.setAlpha(0)
        led_glow.setColorAt(0.0, gc0)
        led_glow.setColorAt(1.0, gc1)
        p.setPen(Qt.NoPen)
        p.setBrush(led_glow)
        p.drawEllipse(QPointF(132.0, 154.0), 14.0, 8.0)
        p.setBrush(led_col)
        p.drawRoundedRect(QRectF(124.5, 151.8, 15.0, 4.4), 2.2, 2.2)

        # ── 6. Recessed Scroll Well + Ribbed Wheel with Silver Side Rims ──
        well_rect = QRectF(119.0, 66.0, 26.0, 51.0)
        p.setBrush(QColor("#0F1218" if is_dark else "#526071"))
        p.setPen(QPen(QColor("#202530" if is_dark else "#7D8B9D"), 1.0))
        p.drawRoundedRect(well_rect, 8.0, 8.0)

        w_rect = self._wheel_rect()
        mid_int = self._intensity[2]
        mid_hov = (active_hover == 2)
        scroll_glow = max(self._intensity[5], self._intensity[6])

        # Silver/white side rims (signature Aigo GM80 Plus wheel detail)
        rim_col = accent if (mid_int > 0.05 or mid_hov) else QColor("#E2E8F0")
        p.setBrush(rim_col)
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(w_rect, 6.5, 6.5)

        # Dark ribbed rubber center tire
        tire_rect = w_rect.adjusted(2.8, 1.5, -2.8, -1.5)
        tire_col = QColor("#1F242D" if is_dark else "#334155")
        if mid_int > 0.02:
            tire_col = QColor(
                int(tire_col.red() * (1 - 0.6 * mid_int) + accent.red() * (0.6 * mid_int)),
                int(tire_col.green() * (1 - 0.6 * mid_int) + accent.green() * (0.6 * mid_int)),
                int(tire_col.blue() * (1 - 0.6 * mid_int) + accent.blue() * (0.6 * mid_int)),
            )
        p.setBrush(tire_col)
        p.drawRoundedRect(tire_rect, 4.5, 4.5)

        # Animated horizontal tread ribs
        p.save()
        rib_clip = QPainterPath()
        rib_clip.addRoundedRect(tire_rect, 4.5, 4.5)
        p.setClipPath(rib_clip)
        rib_c = QColor(accent) if (scroll_glow > 0.05 or mid_int > 0.05) else QColor("#4A5568" if is_dark else "#64748B")
        if scroll_glow > 0.05:
            rib_c.setAlpha(int(round(140 + 115 * scroll_glow)))
        p.setPen(QPen(rib_c, 1.4))
        step = 5.0
        y_start = tire_rect.top() - step + (self._wheel_phase % step)
        y = y_start
        while y <= tire_rect.bottom() + step:
            p.drawLine(QPointF(tire_rect.left() + 1.5, y), QPointF(tire_rect.right() - 1.5, y))
            y += step
        p.restore()

        if mid_int > 0.05 or mid_hov:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(accent, 1.8))
            p.drawRoundedRect(w_rect.adjusted(-1.0, -1.0, 1.0, 1.0), 7.0, 7.0)

        # ── 7. Animated Scroll Up (▲) & Scroll Down (▼) Chevrons ──
        for s_idx, cy, dy_dir in ((5, 57.5, -1.0), (6, 127.5, 1.0)):
            si = self._intensity[s_idx]
            sh = (active_hover == s_idx)
            c = QColor(accent) if (si > 0.04 or sh) else QColor(t["text_muted"])
            c.setAlpha(255 if si > 0.04 else (210 if sh else 125))
            shift = dy_dir * si * 3.2
            chev = QPainterPath()
            chev.moveTo(126.5, cy - dy_dir * 2.5 + shift)
            chev.lineTo(132.0, cy + dy_dir * 3.0 + shift)
            chev.lineTo(137.5, cy - dy_dir * 2.5 + shift)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(c, 2.2 if (si > 0.04 or sh) else 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawPath(chev)

        # ── 8. Left-Flank Side Buttons (#4 Forward & #5 Backward) ──
        for s_idx, rect_fn in ((3, self._side_forward_rect), (4, self._side_backward_rect)):
            si = self._intensity[s_idx]
            sh = (active_hover == s_idx)
            sr = rect_fn(si)
            if si > 0.04:
                glow = QColor(accent)
                glow.setAlpha(int(round(115 * si)))
                p.setBrush(glow)
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(sr.adjusted(-3.0, -3.0, 3.0, 3.0), 5.0, 5.0)
            fill_c = QColor(accent) if si > 0.04 else (
                QColor(accent).darker(120) if sh else QColor("#4A515E" if is_dark else "#94A3B8")
            )
            p.setBrush(fill_c)
            p.setPen(QPen(QColor("#14171E" if is_dark else "#64748B"), 1.0))
            p.drawRoundedRect(sr, 4.0, 4.0)

        # ── 9. Subtle Aigo GM80 Plus Tail Mark ──
        f_logo = QFont(t["ui_font"], 7)
        f_logo.setBold(True)
        p.setFont(f_logo)
        logo_c = QColor(t["text_muted"])
        logo_c.setAlpha(95 if is_dark else 135)
        p.setPen(logo_c)
        p.drawText(QRectF(82.0, 248.0, 100.0, 18.0), Qt.AlignCenter, "GM80 PLUS")

        # ── 10. Numbered Callout Badges (1..7) + Leader Lines ──
        f_badge = QFont(t["ui_font"], 8)
        f_badge.setBold(True)
        p.setFont(f_badge)
        for idx, bpos, anchor in self._badge_specs():
            bi = self._intensity[idx]
            bh = (active_hover == idx)
            active = (bi > 0.05 or bh)

            line_c = QColor(accent) if active else QColor(t["border_strong"])
            line_c.setAlpha(235 if active else 145)
            p.setPen(QPen(line_c, 1.5 if active else 1.0, Qt.SolidLine if active else Qt.DashLine))
            p.drawLine(bpos, anchor)

            rad = 11.5 + bi * 2.2
            if active:
                bg_c = QColor(accent)
                txt_c = QColor(t["accent_fg"])
                bd_c = QColor(accent).lighter(125)
            else:
                bg_c = QColor(t["surface_elevated"])
                txt_c = QColor(t["text_secondary"])
                bd_c = QColor(t["border_strong"])

            p.setBrush(bg_c)
            p.setPen(QPen(bd_c, 1.4))
            p.drawEllipse(bpos, rad, rad)

            p.setPen(txt_c)
            p.drawText(QRectF(bpos.x() - rad, bpos.y() - rad, rad * 2, rad * 2), Qt.AlignCenter, str(idx + 1))

        p.end()


# ============================================================================
# HELPER: CLEAN QPAINTER TRAY ICON & ROUNDED GAME ICON (ZERO FILE LEAKS)
# ============================================================================
def build_tray_qicon(
    driver: YJXGM80PlusDriver,
    custom_icon_path: str = "",
    theme: dict[str, str] | None = None,
    battery_style: str = "classic",
    use_battery_style: bool = True,
) -> QIcon:
    """Build System Tray icon via QPainter with optional semantic battery indicator style."""
    size = 64
    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    p.setRenderHint(QPainter.Antialiasing, True)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)

    ico_loaded = False
    candidates = []
    if custom_icon_path and os.path.exists(custom_icon_path):
        candidates.append(custom_icon_path)
    default_ico = get_resource_path("app_icon.ico")
    if os.path.exists(default_ico):
        candidates.append(default_ico)

    for cand in candidates:
        qico = QIcon(cand)
        pm = qico.pixmap(size, size)
        if not pm.isNull():
            p.drawPixmap(0, 0, size, size, pm)
            ico_loaded = True
            break
    if not ico_loaded:
        p.setBrush(QColor("#161A22"))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(0, 0, size, size, 12, 12)

    accent_hex = (theme or {}).get("accent", "#3B82F6")
    p.setBrush(QColor(15, 17, 23, 238))
    p.setPen(QColor(accent_hex))
    p.drawRoundedRect(QRectF(2, 32, 60, 30), 7, 7)

    if not driver.connected:
        txt, fg = "OFF", "#EF4444"
        frac = 0.0
    elif driver.battery_percent is not None:
        pct = max(0, min(100, int(driver.battery_percent)))
        fg = "#EF4444" if pct < 15 else ("#F59E0B" if pct < 40 else "#22C55E")
        txt = f"{pct}%" if pct < 100 else "100"
        frac = pct / 100.0
    elif driver.is_bluetooth:
        txt, fg, frac = "BT", "#60A5FA", 0.0
    elif driver.is_wired:
        txt, fg, frac = "USB", "#22C55E", 1.0
    else:
        txt, fg, frac = "2.4G", "#22C55E", 0.0

    if use_battery_style and driver.connected and (driver.battery_percent is not None or driver.is_wired):
        # Draw crisp mini semantic bar/ring/segments above the numeric readout inside the tray pill
        bar_col = QColor(fg)
        if battery_style == "segmented":
            segs = 6
            for i in range(segs):
                sx = 7 + i * 8.5
                filled = (i + 1) / segs <= frac + 0.08
                p.setBrush(bar_col if filled else QColor(60, 70, 90))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(QRectF(sx, 35, 6.5, 5), 1.5, 1.5)
        elif battery_style == "ring":
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(60, 70, 90), 2.5))
            p.drawEllipse(QRectF(6, 36, 18, 18))
            p.setPen(QPen(bar_col, 2.5, Qt.SolidLine, Qt.RoundCap))
            p.drawArc(QRectF(6, 36, 18, 18), 90 * 16, int(-360 * 16 * frac))
            p.setFont(QFont("Consolas", 11, QFont.Bold))
            p.setPen(bar_col)
            p.drawText(QRectF(25, 34, 35, 26), Qt.AlignCenter, txt)
            p.end()
            return QIcon(canvas)
        else:  # classic / pill / vertical compact bar
            p.setBrush(QColor(45, 55, 72))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(QRectF(7, 35, 50, 5), 2.5, 2.5)
            p.setBrush(bar_col)
            p.drawRoundedRect(QRectF(7, 35, max(3.0, 50.0 * frac), 5), 2.5, 2.5)
        p.setFont(QFont("Consolas", 12, QFont.Bold))
        p.setPen(bar_col)
        p.drawText(QRectF(2, 41, 60, 20), Qt.AlignCenter, txt)
    else:
        p.setFont(QFont("Consolas", 13, QFont.Bold))
        p.setPen(QColor(fg))
        p.drawText(QRectF(2, 34, 60, 26), Qt.AlignCenter, txt)

    p.end()
    return QIcon(canvas)


def load_game_icon_pixmap(icon_file: str, theme: dict[str, str], size: int = 52) -> QPixmap:
    """Load a game profile icon/artwork into a crisp rounded QPixmap with a clean SVG fallback."""
    pix = None
    if icon_file:
        path = icon_file if os.path.isabs(icon_file) else os.path.join(get_game_icons_dir(), icon_file)
        if os.path.exists(path):
            loaded = QPixmap(path)
            if not loaded.isNull():
                pix = loaded

    canvas = QPixmap(size, size)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    clip = QPainterPath()
    clip.addRoundedRect(1, 1, size - 2, size - 2, 10, 10)
    painter.setClipPath(clip)

    if pix is not None:
        scaled = pix.scaled(size - 2, size - 2, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        sx = max(0, (scaled.width() - (size - 2)) // 2)
        sy = max(0, (scaled.height() - (size - 2)) // 2)
        painter.drawPixmap(1, 1, scaled, sx, sy, size - 2, size - 2)
    else:
        painter.fillRect(0, 0, size, size, QColor(theme["surface_input"]))
        ic_sz = max(20, size // 2)
        ic_pm = svg_pixmap("gamepad", theme["accent"], ic_sz)
        painter.drawPixmap((size - ic_sz) // 2, (size - ic_sz) // 2, ic_sz, ic_sz, ic_pm)

    painter.setClipping(False)
    painter.setPen(QColor(theme["border_strong"]))
    painter.drawRoundedRect(1, 1, size - 2, size - 2, 10, 10)
    painter.end()
    return canvas


# ============================================================================
# WALLPAPER ENGINE (DEDICATED BACKGROUND WIDGET, SMART FILL, HIDPI, QMOVIE)
# ============================================================================
def load_wallpaper_pil(path: str) -> Image.Image | None:
    """Load an image with EXIF transpose and max 3840px downscale; returns None on corrupt/unsupported."""
    if not path or not os.path.exists(path):
        return None
    try:
        with Image.open(path) as raw:
            im = ImageOps.exif_transpose(raw)
            if im.mode != "RGB":
                im = im.convert("RGB")
            if max(im.size) > WALLPAPER_MAX_DIMENSION:
                im.thumbnail((WALLPAPER_MAX_DIMENSION, WALLPAPER_MAX_DIMENSION), Image.LANCZOS)
            return im.copy()
    except Exception as ex:
        APP_LOG.warn(f"Wallpaper load failed ({os.path.basename(path)}): {ex}")
        return None


def _pil_rgb_to_qimage(img: Image.Image) -> QImage:
    rgb = img if img.mode == "RGB" else img.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes("raw", "RGB")
    return QImage(data, w, h, w * 3, QImage.Format_RGB888).copy()


def _pil_rgb_to_qpixmap(img: Image.Image, dpr: float = 1.0) -> QPixmap:
    pm = QPixmap.fromImage(_pil_rgb_to_qimage(img))
    pm.setDevicePixelRatio(max(1.0, float(dpr)))
    return pm


def _focus_anchor(focus: str, is_portrait: bool, vertical: bool) -> float:
    """Return normalized crop anchor in [0..1] (slight upward bias for portraits in Center mode)."""
    f = focus if focus in WALLPAPER_FOCUS_MODES else "center"
    if vertical:
        if f == "top":
            return 0.10
        if f == "bottom":
            return 0.90
        return 0.34 if is_portrait else 0.50
    if f == "top":
        return 0.15
    if f == "bottom":
        return 0.85
    return 0.50


def _cover_crop_pil(src: Image.Image, tw: int, th: int, focus: str = "center") -> Image.Image:
    iw, ih = src.size
    target_ratio = tw / float(max(1, th))
    img_ratio = iw / float(max(1, ih))
    is_portrait = ih > iw
    if img_ratio > target_ratio:
        new_w = max(1, int(round(ih * target_ratio)))
        anchor = _focus_anchor(focus, is_portrait, vertical=False)
        left = max(0, min(iw - new_w, int(round((iw - new_w) * anchor))))
        cropped = src.crop((left, 0, left + new_w, ih))
    else:
        new_h = max(1, int(round(iw / target_ratio)))
        anchor = _focus_anchor(focus, is_portrait, vertical=True)
        top = max(0, min(ih - new_h, int(round((ih - new_h) * anchor))))
        cropped = src.crop((0, top, iw, top + new_h))
    return cropped.resize((tw, th), Image.LANCZOS)


def _cover_area_loss(iw: int, ih: int, tw: int, th: int) -> float:
    """Fraction of image area [0..1] that would be cut off by cover-cropping onto (tw, th)."""
    img_ratio = iw / float(max(1, ih))
    win_ratio = tw / float(max(1, th))
    kept = min(img_ratio, win_ratio) / max(img_ratio, win_ratio)
    return 1.0 - kept


def _fit_contain_pil(src: Image.Image, tw: int, th: int, max_upscale: float = 2.0) -> Image.Image:
    """Scale src to fit inside (tw, th) preserving aspect ratio without stretching or ugly over-upscaling."""
    iw, ih = src.size
    scale = min(tw / float(max(1, iw)), th / float(max(1, ih)))
    if max_upscale > 0 and scale > max_upscale:
        scale = max_upscale
    nw = max(1, min(tw, int(round(iw * scale))))
    nh = max(1, min(th, int(round(ih * scale))))
    if (nw, nh) == (iw, ih):
        return src.copy()
    return src.resize((nw, nh), Image.LANCZOS)


def render_wallpaper_canvas(
    src_pil: Image.Image,
    target_w: int,
    target_h: int,
    fit_mode: str = "smart_fill",
    blur_radius: int = 0,
    dim_pct: int = 30,
    bg_rgb: tuple[int, int, int] = (15, 17, 23),
    focus: str = "center",
) -> Image.Image:
    """
    Render src_pil onto target_w x target_h with exact Smart Fill area-loss guard (>20% -> Fit over
    blurred enlarged backdrop), Focus point (Top/Center/Bottom), optional blur, and dim overlay.
    """
    tw = max(16, int(target_w))
    th = max(16, int(target_h))
    iw, ih = src_pil.size
    fit = fit_mode if fit_mode in WALLPAPER_FIT_MODES else "smart_fill"

    if fit == "smart_fill":
        loss = _cover_area_loss(iw, ih, tw, th)
        tiny_img = (iw < tw * 0.65 and ih < th * 0.65)
        if loss > 0.20 or tiny_img:
            # More than 20% of image would be cropped (or image is tiny):
            # Fit sharp foreground centered over a blurred, darkened enlarged cover copy (never stretch).
            backdrop = _cover_crop_pil(src_pil, tw, th, focus=focus)
            # Fast, smooth blur: blur on half-res copy then resize back for buttery speed on large windows
            half_w, half_h = max(16, tw // 2), max(16, th // 2)
            backdrop = backdrop.resize((half_w, half_h), Image.BILINEAR)
            backdrop = backdrop.filter(ImageFilter.GaussianBlur(radius=max(12, int(blur_radius) + 10)))
            backdrop = backdrop.resize((tw, th), Image.BILINEAR)
            backdrop = Image.blend(backdrop, Image.new("RGB", (tw, th), (0, 0, 0)), 0.32)

            fg = _fit_contain_pil(src_pil, tw, th, max_upscale=2.0)
            if blur_radius > 0:
                fg = fg.filter(ImageFilter.GaussianBlur(radius=min(20, int(blur_radius))))
            canvas = backdrop
            canvas.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
            apply_post_blur = False
        else:
            canvas = _cover_crop_pil(src_pil, tw, th, focus=focus)
            apply_post_blur = True
    elif fit == "fit":
        canvas = Image.new("RGB", (tw, th), bg_rgb)
        fg = _fit_contain_pil(src_pil, tw, th, max_upscale=4.0)
        canvas.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
        apply_post_blur = True
    elif fit == "stretch":
        canvas = src_pil.resize((tw, th), Image.LANCZOS)
        apply_post_blur = True
    elif fit == "center":
        canvas = Image.new("RGB", (tw, th), bg_rgb)
        fg = _fit_contain_pil(src_pil, tw, th, max_upscale=1.0)
        canvas.paste(fg, ((tw - fg.width) // 2, (th - fg.height) // 2))
        apply_post_blur = True
    else:  # tile
        canvas = Image.new("RGB", (tw, th), bg_rgb)
        tile_img = src_pil
        if tile_img.width > tw or tile_img.height > th:
            tile_img = src_pil.copy()
            tile_img.thumbnail((max(128, tw // 2), max(128, th // 2)), Image.LANCZOS)
        for y in range(0, th, max(1, tile_img.height)):
            for x in range(0, tw, max(1, tile_img.width)):
                canvas.paste(tile_img, (x, y))
        apply_post_blur = True

    if apply_post_blur and blur_radius > 0:
        canvas = canvas.filter(ImageFilter.GaussianBlur(radius=min(20, int(blur_radius))))

    dim = max(0, min(80, int(dim_pct)))
    if dim > 0:
        canvas = Image.blend(canvas, Image.new("RGB", (tw, th), (0, 0, 0)), dim / 100.0)
    return canvas


def make_wallpaper_thumbnail(
    path: str,
    w: int,
    h: int,
    theme: dict[str, str],
    fit_mode: str = "smart_fill",
    focus: str = "center",
) -> QPixmap:
    """Create a crisp rounded EXIF-corrected thumbnail using the exact same Smart Fill / Focus logic."""
    canvas = QPixmap(w, h)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

    clip = QPainterPath()
    clip.addRoundedRect(0, 0, w, h, 7, 7)
    painter.setClipPath(clip)

    pil_im = load_wallpaper_pil(path)
    if pil_im is not None:
        rendered = render_wallpaper_canvas(
            pil_im, w * 2, h * 2,
            fit_mode=fit_mode,
            blur_radius=0,
            dim_pct=0,
            bg_rgb=_hex_to_rgb(theme["bg"]),
            focus=focus,
        )
        pm = _pil_rgb_to_qpixmap(rendered, dpr=2.0)
        painter.drawPixmap(0, 0, w, h, pm)
    else:
        painter.fillRect(0, 0, w, h, QColor(theme["surface_input"]))
        ic = svg_pixmap("alert", theme["warning"], 20)
        painter.drawPixmap((w - 20) // 2, (h - 20) // 2, 20, 20, ic)

    if is_animated_image_file(path):
        badge_rect = QRectF(w - 38, 4, 34, 16)
        painter.setBrush(QColor(15, 17, 23, 210))
        painter.setPen(QColor(theme["accent"]))
        painter.drawRoundedRect(badge_rect, 4, 4)
        painter.setFont(QFont("Consolas", 8, QFont.Bold))
        painter.setPen(QColor("#FFFFFF"))
        ext_lbl = "GIF" if path.lower().endswith(".gif") else "ANIM"
        painter.drawText(badge_rect, Qt.AlignCenter, ext_lbl)

    painter.end()
    return canvas


class WallpaperBackgroundWidget(QWidget):
    """
    Smooth 60fps Wallpaper Engine rendered via custom paintEvent (zero PIL work on UI thread during frames).
    - Worker thread renders (image, size, fit, focus, blur, dim) once -> LRU QPixmap cache.
    - Slideshow transitions blend ONLY two cached QPixmaps via QPropertyAnimation (500ms InOutCubic).
    - Animated GIF / WebP frames are scaled once per size and cached in _movie_frame_cache.
    - Automatically pauses animations & timers when hidden, minimized, or in tray.
    """
    error_occurred = Signal(str)
    _render_ready = Signal(int, object, QImage, float, bool)
    _render_failed = Signal(int, str, bool)

    def __init__(self, parent=None, is_preview: bool = False):
        super().__init__(parent)
        self._is_preview = is_preview
        self._config = {
            "mode": "none",
            "file": "",
            "fit": "smart_fill",
            "focus": "center",
            "dim": 30,
            "blur": 0,
            "interval_sec": 60,
            "shuffle": False,
            "animation": True,
        }
        self._bg_hex = "#0F1117"
        self._active_path = ""
        self._current_pixmap: QPixmap | None = None
        self._prev_pixmap: QPixmap | None = None
        self._fade_opacity = 1.0
        self._pixmap_cache: dict[tuple, QPixmap] = {}
        self._source_pil_cache: dict[str, Image.Image] = {}
        self._pil_lock = threading.Lock()
        self._render_gen = 0

        self._fade_anim = QPropertyAnimation(self, b"fadeOpacity", self)
        self._fade_anim.setDuration(480)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._fade_anim.finished.connect(self._on_fade_finished)

        self._movie: QMovie | None = None
        self._movie_path = ""
        self._movie_frame_cache: dict[int, QPixmap] = {}
        self._movie_cache_sig = None
        self._visibility_paused = False

        self._slideshow_files: list[str] = []
        self._slideshow_idx = 0

        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(WALLPAPER_RESIZE_DEBOUNCE_MS)
        self._resize_timer.timeout.connect(self._on_resize_debounced)

        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.timeout.connect(self._advance_slideshow)

        self._render_ready.connect(self._on_render_ready)
        self._render_failed.connect(self._on_render_failed)

    def _get_fade_opacity(self) -> float:
        return self._fade_opacity

    def _set_fade_opacity(self, val: float):
        self._fade_opacity = max(0.0, min(1.0, float(val)))
        self.update()

    fadeOpacity = Property(float, _get_fade_opacity, _set_fade_opacity)

    def _on_fade_finished(self):
        self._prev_pixmap = None
        self._fade_opacity = 1.0
        self.update()

    def apply_config(self, config: dict, bg_hex: str | None = None):
        if bg_hex:
            self._bg_hex = bg_hex
        prev_mode = self._config.get("mode")
        prev_file = self._config.get("file")
        prev_shuffle = self._config.get("shuffle")
        prev_interval = self._config.get("interval_sec")

        self._config.update({
            "mode": config.get("mode", "none") if config.get("mode") in WALLPAPER_MODES else "none",
            "file": str(config.get("file", "")),
            "fit": config.get("fit", "smart_fill") if config.get("fit") in WALLPAPER_FIT_MODES else "smart_fill",
            "focus": config.get("focus", "center") if config.get("focus") in WALLPAPER_FOCUS_MODES else "center",
            "dim": max(0, min(80, int(config.get("dim", 30)))),
            "blur": max(0, min(20, int(config.get("blur", 0)))),
            "interval_sec": max(10, min(1800, int(config.get("interval_sec", 60)))),
            "shuffle": bool(config.get("shuffle", False)),
            "animation": bool(config.get("animation", True)),
        })
        mode = self._config["mode"]

        if mode == "none":
            self._fade_anim.stop()
            self._slideshow_timer.stop()
            self._stop_movie()
            self._active_path = ""
            self._current_pixmap = None
            self._prev_pixmap = None
            self.update()
            return

        if mode == "animated":
            self._fade_anim.stop()
            self._slideshow_timer.stop()
            self._active_path = ""
            self._current_pixmap = None
            self._prev_pixmap = None
            self._invalidate_movie_cache()
            target = resolve_wallpaper_path(self._config["file"])
            if not target or not is_animated_image_file(target):
                anims = list_wallpaper_files(only_animated=True)
                target = anims[0] if anims else ""
            if target:
                self._start_movie(target)
            else:
                self._stop_movie()
            self.update()
            return

        # Static or Slideshow
        self._stop_movie()
        if mode == "static":
            self._slideshow_timer.stop()
            target = resolve_wallpaper_path(self._config["file"])
            if not target:
                all_files = list_wallpaper_files(only_animated=False)
                target = all_files[0] if all_files else ""
            if target:
                changed_file = (target != self._active_path)
                self._request_render(target, animate_transition=(changed_file and self._current_pixmap is not None))
            else:
                self._active_path = ""
                self._current_pixmap = None
                self._prev_pixmap = None
                self.update()
            return

        # Slideshow mode
        if prev_mode != "slideshow" or prev_shuffle != self._config["shuffle"] or not self._slideshow_files:
            self._reload_slideshow_queue(prefer_file=self._config["file"])
        elif prev_file != self._config["file"] and self._config["file"]:
            p = resolve_wallpaper_path(self._config["file"])
            if p and p in self._slideshow_files:
                self._slideshow_idx = self._slideshow_files.index(p)
                self._request_render(p, animate_transition=True)

        if self._slideshow_files:
            target = self._slideshow_files[self._slideshow_idx % len(self._slideshow_files)]
            self._request_render(target, animate_transition=False)
        else:
            self._current_pixmap = None
            self._prev_pixmap = None
            self.update()

        if not self._is_preview and len(self._slideshow_files) >= 2 and not self._visibility_paused:
            interval_ms = self._config["interval_sec"] * 1000
            if not self._slideshow_timer.isActive() or prev_interval != self._config["interval_sec"]:
                self._slideshow_timer.start(interval_ms)
        else:
            self._slideshow_timer.stop()

    def reload_folder(self):
        self._pixmap_cache.clear()
        with self._pil_lock:
            self._source_pil_cache.clear()
        mode = self._config["mode"]
        if mode == "slideshow":
            self._reload_slideshow_queue(prefer_file=self._config["file"])
            if self._slideshow_files:
                self._request_render(self._slideshow_files[0], animate_transition=False)
        elif mode == "static":
            self._active_path = ""
            self.apply_config(self._config)
        elif mode == "animated":
            self._movie_path = ""
            self.apply_config(self._config)

    def _reload_slideshow_queue(self, prefer_file: str = ""):
        files = list_wallpaper_files(only_animated=False)
        if self._config["shuffle"] and len(files) > 1:
            random.shuffle(files)
        self._slideshow_files = files
        self._slideshow_idx = 0
        if prefer_file:
            resolved = resolve_wallpaper_path(prefer_file)
            if resolved in self._slideshow_files:
                self._slideshow_idx = self._slideshow_files.index(resolved)

    def _advance_slideshow(self):
        if self._visibility_paused or self._config["mode"] != "slideshow" or len(self._slideshow_files) < 2:
            return
        self._slideshow_idx = (self._slideshow_idx + 1) % len(self._slideshow_files)
        nxt = self._slideshow_files[self._slideshow_idx]
        self._request_render(nxt, animate_transition=True)

    def _make_cache_key(self, path: str, w: int, h: int, dpr: float) -> tuple:
        return (
            path, w, h, round(dpr, 2),
            self._config["fit"], self._config["focus"],
            self._config["blur"], self._config["dim"], self._bg_hex,
        )

    def _request_render(self, path: str, animate_transition: bool):
        w = max(16, self.width())
        h = max(16, self.height())
        dpr = max(1.0, float(self.devicePixelRatioF()))
        key = self._make_cache_key(path, w, h, dpr)
        self._active_path = path

        # Instant cache hit -> zero thread overhead, immediate 60fps crossfade!
        cached = self._pixmap_cache.get(key)
        if cached is not None:
            self._apply_rendered_pixmap(cached, animate_transition)
            return

        self._render_gen += 1
        gen = self._render_gen
        pw, ph = int(round(w * dpr)), int(round(h * dpr))
        fit = self._config["fit"]
        focus = self._config["focus"]
        blur = self._config["blur"]
        dim = self._config["dim"]
        bg_rgb = _hex_to_rgb(self._bg_hex)
        is_slide = (self._config["mode"] == "slideshow")

        threading.Thread(
            target=self._render_worker,
            args=(gen, key, path, pw, ph, dpr, fit, focus, blur, dim, bg_rgb, animate_transition, is_slide),
            daemon=True,
        ).start()

    def _render_worker(
        self,
        gen: int,
        key: tuple,
        path: str,
        pw: int,
        ph: int,
        dpr: float,
        fit: str,
        focus: str,
        blur: int,
        dim: int,
        bg_rgb: tuple[int, int, int],
        animate_transition: bool,
        is_slide: bool,
    ):
        try:
            with self._pil_lock:
                src = self._source_pil_cache.get(path)
            if src is None:
                src = load_wallpaper_pil(path)
                if src is None:
                    try:
                        self._render_failed.emit(gen, path, is_slide)
                    except RuntimeError:
                        pass
                    return
                with self._pil_lock:
                    if len(self._source_pil_cache) >= 6:
                        self._source_pil_cache.pop(next(iter(self._source_pil_cache)))
                    self._source_pil_cache[path] = src

            rendered = render_wallpaper_canvas(
                src, pw, ph,
                fit_mode=fit,
                blur_radius=blur,
                dim_pct=dim,
                bg_rgb=bg_rgb,
                focus=focus,
            )
            qimg = _pil_rgb_to_qimage(rendered)
            try:
                self._render_ready.emit(gen, key, qimg, dpr, animate_transition)
            except RuntimeError:
                pass
        except Exception as ex:
            APP_LOG.warn(f"Wallpaper worker render error ({os.path.basename(path)}): {ex}")
            try:
                self._render_failed.emit(gen, path, is_slide)
            except RuntimeError:
                pass

    def _on_render_ready(self, gen: int, key: tuple, qimg: QImage, dpr: float, animate_transition: bool):
        pm = QPixmap.fromImage(qimg)
        pm.setDevicePixelRatio(max(1.0, float(dpr)))
        if len(self._pixmap_cache) >= WALLPAPER_CACHE_LIMIT:
            self._pixmap_cache.pop(next(iter(self._pixmap_cache)))
        self._pixmap_cache[key] = pm
        if gen != self._render_gen:
            return
        self._apply_rendered_pixmap(pm, animate_transition)

    def _on_render_failed(self, gen: int, path: str, is_slide: bool):
        self.error_occurred.emit(os.path.basename(path))
        if gen != self._render_gen:
            return
        if is_slide and path in self._slideshow_files:
            self._slideshow_files = [p for p in self._slideshow_files if p != path]
            if self._slideshow_files:
                self._slideshow_idx %= len(self._slideshow_files)
                self._request_render(self._slideshow_files[self._slideshow_idx], animate_transition=False)

    def _apply_rendered_pixmap(self, pm: QPixmap, animate_transition: bool):
        if (
            animate_transition
            and self._config["animation"]
            and not self._visibility_paused
            and self._current_pixmap is not None
        ):
            self._fade_anim.stop()
            self._prev_pixmap = self._current_pixmap
            self._current_pixmap = pm
            self._fade_opacity = 0.0
            self._fade_anim.setStartValue(0.0)
            self._fade_anim.setEndValue(1.0)
            self._fade_anim.start()
        else:
            self._fade_anim.stop()
            self._prev_pixmap = None
            self._current_pixmap = pm
            self._fade_opacity = 1.0
            self.update()

    def _on_resize_debounced(self):
        if self._config["mode"] in ("static", "slideshow") and self._active_path:
            self._request_render(self._active_path, animate_transition=False)
        elif self._config["mode"] == "animated":
            self._invalidate_movie_cache()
            self.update()

    def _invalidate_movie_cache(self):
        self._movie_frame_cache.clear()
        self._movie_cache_sig = None

    def _start_movie(self, path: str):
        if self._movie is not None and self._movie_path == path:
            should_run = (not self._visibility_paused and self._config["animation"])
            self._movie.setPaused(not should_run)
            if should_run and self._movie.state() != QMovie.Running:
                self._movie.start()
            return
        self._stop_movie()
        movie = QMovie(path, QByteArray(), self)
        movie.setCacheMode(QMovie.CacheNone)
        if not movie.isValid():
            movie.deleteLater()
            APP_LOG.warn(f"Invalid animated wallpaper file: {os.path.basename(path)}")
            self.error_occurred.emit(os.path.basename(path))
            return
        self._movie = movie
        self._movie_path = path
        self._invalidate_movie_cache()
        movie.frameChanged.connect(self.update)
        movie.jumpToFrame(0)
        if not self._visibility_paused and self._config["animation"]:
            movie.start()
        else:
            movie.setPaused(True)

    def _stop_movie(self):
        if self._movie is not None:
            try:
                self._movie.frameChanged.disconnect(self.update)
            except (RuntimeError, TypeError) as ex:
                APP_LOG.warn(f"Movie disconnect skipped: {ex}")
            self._movie.stop()
            self._movie.setFileName("")
            self._movie.deleteLater()
            self._movie = None
            self._movie_path = ""
        self._invalidate_movie_cache()

    def set_paused_for_visibility(self, paused: bool):
        self._visibility_paused = bool(paused)
        if self._visibility_paused:
            self._fade_anim.stop()
            self._prev_pixmap = None
            self._fade_opacity = 1.0
        if self._movie is not None:
            self._movie.setPaused(self._visibility_paused or not self._config["animation"])
        if self._config["mode"] == "slideshow" and not self._is_preview:
            if self._visibility_paused:
                self._slideshow_timer.stop()
            elif len(self._slideshow_files) >= 2:
                self._slideshow_timer.start(self._config["interval_sec"] * 1000)

    def cleanup(self):
        self._fade_anim.stop()
        self._resize_timer.stop()
        self._slideshow_timer.stop()
        self._stop_movie()
        self._pixmap_cache.clear()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._config["mode"] in ("static", "slideshow", "animated"):
            self._resize_timer.start()

    def _get_cached_movie_frame(self) -> QPixmap | None:
        if self._movie is None:
            return None
        w, h = max(16, self.width()), max(16, self.height())
        sig = (self._movie_path, w, h, self._config["fit"], self._config["focus"], self._config["dim"], self._bg_hex)
        if sig != self._movie_cache_sig:
            self._movie_frame_cache.clear()
            self._movie_cache_sig = sig
        fnum = self._movie.currentFrameNumber()
        cached = self._movie_frame_cache.get(fnum)
        if cached is not None:
            return cached

        raw = self._movie.currentPixmap()
        if raw.isNull():
            return None

        out = QPixmap(w, h)
        out.fill(QColor(self._bg_hex))
        p = QPainter(out)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        pw, ph = max(1, raw.width()), max(1, raw.height())
        fit = self._config["fit"]
        focus = self._config["focus"]

        if fit == "stretch":
            p.drawPixmap(0, 0, w, h, raw)
        elif fit == "fit":
            sc = raw.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((w - sc.width()) // 2, (h - sc.height()) // 2, sc)
        elif fit == "center":
            sc = raw.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation) if (pw > w or ph > h) else raw
            p.drawPixmap((w - sc.width()) // 2, (h - sc.height()) // 2, sc)
        elif fit == "tile":
            for y in range(0, h, ph):
                for x in range(0, w, pw):
                    p.drawPixmap(x, y, raw)
        else:  # smart_fill with >20% area-loss guard + focus point
            loss = _cover_area_loss(pw, ph, w, h)
            if loss > 0.20:
                bg = raw.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                p.drawPixmap(0, 0, bg, (bg.width() - w) // 2, (bg.height() - h) // 2, w, h)
                p.fillRect(0, 0, w, h, QColor(0, 0, 0, 140))
                fg = raw.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap((w - fg.width()) // 2, (h - fg.height()) // 2, fg)
            else:
                sc = raw.scaled(w, h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                ay = _focus_anchor(focus, ph > pw, vertical=True)
                ax = _focus_anchor(focus, ph > pw, vertical=False)
                sx = int(round((sc.width() - w) * ax))
                sy = int(round((sc.height() - h) * ay))
                p.drawPixmap(0, 0, sc, max(0, sx), max(0, sy), w, h)

        dim = self._config["dim"]
        if dim > 0:
            p.fillRect(0, 0, w, h, QColor(0, 0, 0, int(round(dim * 2.55))))
        p.end()

        if len(self._movie_frame_cache) < WALLPAPER_MOVIE_CACHE_LIMIT:
            self._movie_frame_cache[fnum] = out
        return out

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(self._bg_hex))
        mode = self._config["mode"]
        if mode == "animated" and self._movie is not None:
            frame = self._get_cached_movie_frame()
            if frame is not None:
                painter.drawPixmap(self.rect(), frame)
        elif mode in ("static", "slideshow"):
            if self._prev_pixmap is not None:
                same_sz = (self._prev_pixmap.deviceIndependentSize().toSize() == self.size())
                painter.setRenderHint(QPainter.SmoothPixmapTransform, not same_sz)
                painter.drawPixmap(self.rect(), self._prev_pixmap)
            if self._current_pixmap is not None:
                same_sz = (self._current_pixmap.deviceIndependentSize().toSize() == self.size())
                painter.setRenderHint(QPainter.SmoothPixmapTransform, not same_sz)
                if self._prev_pixmap is not None and self._fade_opacity < 0.999:
                    painter.setOpacity(self._fade_opacity)
                painter.drawPixmap(self.rect(), self._current_pixmap)
        painter.end()


class WallpaperThumbTile(QFrame):
    """Clickable thumbnail card for selecting a wallpaper inside Settings."""
    selected = Signal(str)

    def __init__(self, file_path: str, pixmap: QPixmap, parent=None):
        super().__init__(parent)
        self.file_path = file_path
        self.file_name = os.path.basename(file_path)
        self.setObjectName("WpThumbTile")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(166, 112)
        self.setToolTip(self.file_name)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(5, 5, 5, 5)
        lay.setSpacing(4)

        lbl_img = QLabel()
        lbl_img.setAlignment(Qt.AlignCenter)
        lbl_img.setPixmap(pixmap)
        lay.addWidget(lbl_img, 1)

        short = self.file_name if len(self.file_name) <= 20 else (self.file_name[:17] + "...")
        lbl_name = QLabel(ltr(short))
        lbl_name.setObjectName("MutedLabel")
        lbl_name.setAlignment(Qt.AlignCenter)
        lay.addWidget(lbl_name)

    def set_selected(self, is_sel: bool):
        self.setProperty("selected", "true" if is_sel else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.selected.emit(self.file_name)
        super().mousePressEvent(event)


class WallpaperSettingsWidget(QWidget):
    """Full Wallpaper manager: live preview, modes, fit modes, sliders, add/remove/reload, thumbnail grid."""

    def __init__(self, main_win: "GM80PlusGlassWindow", parent=None):
        super().__init__(parent)
        self.win = main_win
        self._tiles: list[WallpaperThumbTile] = []
        self._build_ui()
        self.refresh_theme_and_texts()
        self.reload_grid()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP["md"])

        # ── Card 1: Live Preview + Mode Grid + Animation Toggle ──
        hero_card = QFrame()
        hero_card.setObjectName("SubCard")
        hero_row = QHBoxLayout(hero_card)
        hero_row.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        hero_row.setSpacing(SP["lg"])

        prev_frame = QFrame()
        prev_frame.setObjectName("WpPreviewFrame")
        prev_frame.setFixedSize(222, 126)
        pf_lay = QVBoxLayout(prev_frame)
        pf_lay.setContentsMargins(3, 3, 3, 3)
        self.preview_canvas = WallpaperBackgroundWidget(prev_frame, is_preview=True)
        self.lbl_prev_none = QLabel(self.preview_canvas)
        self.lbl_prev_none.setObjectName("MutedLabel")
        self.lbl_prev_none.setAlignment(Qt.AlignCenter)
        p_in_lay = QVBoxLayout(self.preview_canvas)
        p_in_lay.addWidget(self.lbl_prev_none)
        pf_lay.addWidget(self.preview_canvas)
        hero_row.addWidget(prev_frame, 0, Qt.AlignVCenter)

        ctrl_col = QVBoxLayout()
        ctrl_col.setSpacing(SP["sm"])

        # Mode segmented buttons in a clean 2x2 grid so nothing ever clips horizontally
        mode_grid = QGridLayout()
        mode_grid.setContentsMargins(0, 0, 0, 0)
        mode_grid.setHorizontalSpacing(6)
        mode_grid.setVerticalSpacing(6)
        self.mode_btns: dict[str, QPushButton] = {}
        for idx, m in enumerate(WALLPAPER_MODES):
            b = QPushButton()
            b.setObjectName("SegmentBtn")
            b.setProperty("active", "false")
            b.setCursor(Qt.PointingHandCursor)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.setMinimumHeight(34)
            b.clicked.connect(lambda checked=False, mode=m: self._on_mode_clicked(mode))
            mode_grid.addWidget(b, idx // 2, idx % 2)
            self.mode_btns[m] = b
        mode_grid.setColumnStretch(0, 1)
        mode_grid.setColumnStretch(1, 1)
        ctrl_col.addLayout(mode_grid)

        # Animation toggle cleanly placed under mode grid
        anim_row = QHBoxLayout()
        anim_row.setContentsMargins(2, 4, 2, 0)
        anim_row.setSpacing(SP["sm"])
        self.lbl_anim = QLabel()
        self.lbl_anim.setObjectName("SubtitleLabel")
        anim_row.addWidget(self.lbl_anim)
        anim_row.addStretch()
        self.chk_anim = ToggleSwitch(self, self.win.theme)
        self.chk_anim.setChecked(self.win.wp_config["animation"])
        self.chk_anim.toggled.connect(self._on_anim_toggled)
        anim_row.addWidget(self.chk_anim)
        ctrl_col.addLayout(anim_row)
        ctrl_col.addStretch()

        hero_row.addLayout(ctrl_col, 1)
        lay.addWidget(hero_card)

        # ── Card 2: Fit Mode, Focus Point & Slideshow Options ──
        opts_card = QFrame()
        opts_card.setObjectName("SubCard")
        opts_lay = QVBoxLayout(opts_card)
        opts_lay.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        opts_lay.setSpacing(SP["sm"])

        fit_grid = QGridLayout()
        fit_grid.setContentsMargins(0, 0, 0, 0)
        fit_grid.setHorizontalSpacing(SP["md"])
        fit_grid.setVerticalSpacing(SP["sm"])
        fit_grid.setColumnStretch(1, 1)

        self.lbl_fit = QLabel()
        self.lbl_fit.setObjectName("SubtitleLabel")
        self.lbl_fit.setMinimumWidth(104)
        fit_grid.addWidget(self.lbl_fit, 0, 0, Qt.AlignVCenter)

        self.cmb_fit = QComboBox()
        self.cmb_fit.setMinimumWidth(180)
        self.cmb_fit.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.cmb_fit.currentIndexChanged.connect(self._on_fit_changed)
        fit_grid.addWidget(self.cmb_fit, 0, 1)

        self.lbl_focus = QLabel()
        self.lbl_focus.setObjectName("SubtitleLabel")
        self.lbl_focus.setMinimumWidth(104)
        fit_grid.addWidget(self.lbl_focus, 1, 0, Qt.AlignVCenter)

        focus_row = QHBoxLayout()
        focus_row.setContentsMargins(0, 0, 0, 0)
        focus_row.setSpacing(6)
        self.focus_btns: dict[str, QPushButton] = {}
        for fkey in WALLPAPER_FOCUS_MODES:
            fb = QPushButton()
            fb.setObjectName("SegmentBtn")
            fb.setProperty("active", "false")
            fb.setCursor(Qt.PointingHandCursor)
            fb.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            fb.setMinimumHeight(32)
            fb.clicked.connect(lambda checked=False, fk=fkey: self._on_focus_clicked(fk))
            focus_row.addWidget(fb, 1)
            self.focus_btns[fkey] = fb
        fit_grid.addLayout(focus_row, 1, 1)
        opts_lay.addLayout(fit_grid)

        # Slideshow Interval & Shuffle (full width row inside options card)
        self.slide_row_widget = QWidget()
        sr_lay = QHBoxLayout(self.slide_row_widget)
        sr_lay.setContentsMargins(0, 4, 0, 0)
        sr_lay.setSpacing(SP["md"])

        self.lbl_interval = QLabel()
        self.lbl_interval.setObjectName("SubtitleLabel")
        self.lbl_interval.setMinimumWidth(104)
        sr_lay.addWidget(self.lbl_interval)

        self.cmb_interval = QComboBox()
        self.cmb_interval.setMinimumWidth(148)
        self.cmb_interval.currentIndexChanged.connect(self._on_interval_changed)
        sr_lay.addWidget(self.cmb_interval)

        sr_lay.addStretch()

        self.lbl_shuffle = QLabel()
        self.lbl_shuffle.setObjectName("SubtitleLabel")
        sr_lay.addWidget(self.lbl_shuffle)
        self.chk_shuffle = ToggleSwitch(self, self.win.theme)
        self.chk_shuffle.setChecked(self.win.wp_config["shuffle"])
        self.chk_shuffle.toggled.connect(self._on_shuffle_toggled)
        sr_lay.addWidget(self.chk_shuffle)
        opts_lay.addWidget(self.slide_row_widget)

        lay.addWidget(opts_card)

        # ── Card 3: Sliders Grid: Dim (0-80%), Blur (0-20), Panel Opacity (55-100%) ──
        sl_card = QFrame()
        sl_card.setObjectName("SubCard")
        sl_grid = QGridLayout(sl_card)
        sl_grid.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        sl_grid.setHorizontalSpacing(SP["md"])
        sl_grid.setVerticalSpacing(8)
        sl_grid.setColumnStretch(1, 1)

        self.lbl_dim = QLabel()
        self.lbl_dim.setObjectName("SubtitleLabel")
        self.lbl_dim.setMinimumWidth(104)
        self.sl_dim = QSlider(Qt.Horizontal)
        self.sl_dim.setLayoutDirection(Qt.LeftToRight)
        self.sl_dim.setRange(0, 80)
        self.sl_dim.setValue(self.win.wp_config["dim"])
        self.sl_dim.valueChanged.connect(self._on_dim_changed)
        self.lbl_dim_val = QLabel()
        self.lbl_dim_val.setObjectName("MonoValue")
        self.lbl_dim_val.setFixedWidth(48)
        self.lbl_dim_val.setAlignment(Qt.AlignCenter)
        sl_grid.addWidget(self.lbl_dim, 0, 0)
        sl_grid.addWidget(self.sl_dim, 0, 1)
        sl_grid.addWidget(self.lbl_dim_val, 0, 2)

        self.lbl_blur = QLabel()
        self.lbl_blur.setObjectName("SubtitleLabel")
        self.lbl_blur.setMinimumWidth(104)
        self.sl_blur = QSlider(Qt.Horizontal)
        self.sl_blur.setLayoutDirection(Qt.LeftToRight)
        self.sl_blur.setRange(0, 20)
        self.sl_blur.setValue(self.win.wp_config["blur"])
        self.sl_blur.valueChanged.connect(self._on_blur_changed)
        self.lbl_blur_val = QLabel()
        self.lbl_blur_val.setObjectName("MonoValue")
        self.lbl_blur_val.setFixedWidth(48)
        self.lbl_blur_val.setAlignment(Qt.AlignCenter)
        sl_grid.addWidget(self.lbl_blur, 1, 0)
        sl_grid.addWidget(self.sl_blur, 1, 1)
        sl_grid.addWidget(self.lbl_blur_val, 1, 2)

        self.lbl_opacity = QLabel()
        self.lbl_opacity.setObjectName("SubtitleLabel")
        self.lbl_opacity.setMinimumWidth(104)
        self.sl_opacity = QSlider(Qt.Horizontal)
        self.sl_opacity.setLayoutDirection(Qt.LeftToRight)
        self.sl_opacity.setRange(55, 100)
        self.sl_opacity.setValue(self.win.wp_panel_opacity)
        self.sl_opacity.valueChanged.connect(self._on_opacity_changed)
        self.lbl_opacity_val = QLabel()
        self.lbl_opacity_val.setObjectName("MonoValue")
        self.lbl_opacity_val.setFixedWidth(48)
        self.lbl_opacity_val.setAlignment(Qt.AlignCenter)
        sl_grid.addWidget(self.lbl_opacity, 2, 0)
        sl_grid.addWidget(self.sl_opacity, 2, 1)
        sl_grid.addWidget(self.lbl_opacity_val, 2, 2)
        lay.addWidget(sl_card)

        # ── Toolbar: Add, Remove, Open Folder, Reload ──
        tb = QHBoxLayout()
        tb.setContentsMargins(0, 2, 0, 0)
        tb.setSpacing(SP["sm"])
        self.btn_add = QPushButton()
        self.btn_add.setObjectName("SecondaryBtn")
        self.btn_add.clicked.connect(self._add_images)
        tb.addWidget(self.btn_add)

        self.btn_remove = QPushButton()
        self.btn_remove.setObjectName("DangerBtn")
        self.btn_remove.clicked.connect(self._remove_selected)
        tb.addWidget(self.btn_remove)

        tb.addStretch()

        self.btn_open = QPushButton()
        self.btn_open.setObjectName("GhostBtn")
        self.btn_open.clicked.connect(self._open_folder)
        tb.addWidget(self.btn_open)

        self.btn_reload = QPushButton()
        self.btn_reload.setObjectName("GhostBtn")
        self.btn_reload.clicked.connect(self._reload_clicked)
        tb.addWidget(self.btn_reload)
        lay.addLayout(tb)

        # ── Thumbnail Grid (directly inside outer scroll area — no nested double-scroll) ──
        self.grid_host = QWidget()
        self.thumb_grid = QGridLayout(self.grid_host)
        self.thumb_grid.setContentsMargins(2, 4, 2, 4)
        self.thumb_grid.setHorizontalSpacing(10)
        self.thumb_grid.setVerticalSpacing(10)
        lay.addWidget(self.grid_host)

    def refresh_theme_and_texts(self):
        lg = self.win.lang
        en = (lg == "en")
        t = self.win.theme
        cfg = self.win.wp_config

        mode_keys = {
            "none": "wp_mode_none",
            "static": "wp_mode_static",
            "slideshow": "wp_mode_slideshow",
            "animated": "wp_mode_animated",
        }
        for m, tk in mode_keys.items():
            b = self.mode_btns[m]
            is_act = (cfg["mode"] == m)
            b.setText(tr(tk, lg))
            b.setProperty("active", "true" if is_act else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        self.lbl_fit.setText(tr("wp_fit_lbl", lg))
        fit_keys = ("wp_fit_smart_fill", "wp_fit_fit", "wp_fit_stretch", "wp_fit_center", "wp_fit_tile")
        self.cmb_fit.blockSignals(True)
        self.cmb_fit.clear()
        for fk in fit_keys:
            self.cmb_fit.addItem(tr(fk, lg))
        self.cmb_fit.setCurrentIndex(WALLPAPER_FIT_MODES.index(cfg["fit"]) if cfg["fit"] in WALLPAPER_FIT_MODES else 0)
        self.cmb_fit.blockSignals(False)

        self.lbl_focus.setText(tr("wp_focus_lbl", lg))
        focus_keys = {"top": "wp_focus_top", "center": "wp_focus_center", "bottom": "wp_focus_bottom"}
        for fk, tk in focus_keys.items():
            fb = self.focus_btns[fk]
            fb.setText(tr(tk, lg))
            fb.setProperty("active", "true" if cfg.get("focus", "center") == fk else "false")
            fb.style().unpolish(fb)
            fb.style().polish(fb)

        self.lbl_anim.setText(tr("wp_anim_lbl", lg))
        self.chk_anim.set_theme(t)
        self.chk_anim.blockSignals(True)
        self.chk_anim.setChecked(bool(cfg.get("animation", True)))
        self.chk_anim.blockSignals(False)

        self.lbl_interval.setText(tr("wp_interval_lbl", lg))
        self.cmb_interval.blockSignals(True)
        self.cmb_interval.clear()
        for _, ar_lbl, en_lbl in WALLPAPER_INTERVAL_OPTIONS:
            self.cmb_interval.addItem(en_lbl if en else ar_lbl)
        iv_idx = next((i for i, opt in enumerate(WALLPAPER_INTERVAL_OPTIONS) if opt[0] == cfg["interval_sec"]), 2)
        self.cmb_interval.setCurrentIndex(iv_idx)
        self.cmb_interval.blockSignals(False)

        self.lbl_shuffle.setText(tr("wp_shuffle_lbl", lg))
        self.chk_shuffle.set_theme(t)
        self.chk_shuffle.blockSignals(True)
        self.chk_shuffle.setChecked(cfg["shuffle"])
        self.chk_shuffle.blockSignals(False)
        self.slide_row_widget.setVisible(cfg["mode"] == "slideshow")

        self.lbl_dim.setText(tr("wp_dim_lbl", lg))
        self.sl_dim.blockSignals(True)
        self.sl_dim.setValue(cfg["dim"])
        self.sl_dim.blockSignals(False)
        self.lbl_dim_val.setText(f"{cfg['dim']}%")

        self.lbl_blur.setText(tr("wp_blur_lbl", lg))
        self.sl_blur.blockSignals(True)
        self.sl_blur.setValue(cfg["blur"])
        self.sl_blur.blockSignals(False)
        self.lbl_blur_val.setText(str(cfg["blur"]))

        self.lbl_opacity.setText(tr("wp_opacity_lbl", lg))
        self.sl_opacity.blockSignals(True)
        self.sl_opacity.setValue(self.win.wp_panel_opacity)
        self.sl_opacity.blockSignals(False)
        self.lbl_opacity_val.setText(f"{self.win.wp_panel_opacity}%")

        is_active = (cfg["mode"] != "none")
        self.sl_dim.setEnabled(is_active)
        self.sl_blur.setEnabled(is_active and cfg["mode"] != "animated")
        self.sl_opacity.setEnabled(is_active)
        self.cmb_fit.setEnabled(is_active)
        self.chk_anim.setEnabled(is_active)
        for fb in self.focus_btns.values():
            fb.setEnabled(is_active and cfg["fit"] == "smart_fill")

        self.btn_add.setText(tr("wp_add_btn", lg))
        self.btn_add.setIcon(svg_icon("plus", t["text"], 14))
        self.btn_remove.setText(tr("wp_remove_btn", lg))
        self.btn_remove.setIcon(svg_icon("trash", t["danger"], 14))
        self.btn_remove.setEnabled(bool(cfg["file"]))
        self.btn_open.setText(tr("set_wp_open", lg))
        self.btn_open.setIcon(svg_icon("folder", t["text_secondary"], 14))
        self.btn_reload.setText(tr("wp_reload_btn", lg))
        self.btn_reload.setIcon(svg_icon("refresh", t["text_secondary"], 14))

        self.lbl_prev_none.setText(tr("wp_preview_none", lg))
        self.lbl_prev_none.setVisible(cfg["mode"] == "none")
        self.preview_canvas.apply_config(cfg, bg_hex=t["bg"])

    def reload_grid(self):
        self._tiles.clear()
        while self.thumb_grid.count():
            item = self.thumb_grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        only_anim = (self.win.wp_config["mode"] == "animated")
        files = list_wallpaper_files(only_animated=only_anim)
        if not files:
            lbl = QLabel(tr("wp_empty_anim" if only_anim else "wp_empty_grid", self.win.lang))
            lbl.setObjectName("SubtitleLabel")
            lbl.setAlignment(Qt.AlignCenter)
            lbl.setWordWrap(True)
            self.thumb_grid.addWidget(lbl, 0, 0, 1, 4)
            return

        cur_file = os.path.basename(self.win.wp_config.get("file", "")).lower()
        fit_m = self.win.wp_config.get("fit", "smart_fill")
        focus_m = self.win.wp_config.get("focus", "center")
        cols = 3
        for idx, path in enumerate(files):
            pm = make_wallpaper_thumbnail(path, 154, 82, self.win.theme, fit_mode=fit_m, focus=focus_m)
            tile = WallpaperThumbTile(path, pm, self.grid_host)
            tile.set_selected(os.path.basename(path).lower() == cur_file)
            tile.selected.connect(self._on_tile_selected)
            self.thumb_grid.addWidget(tile, idx // cols, idx % cols, Qt.AlignCenter)
            self._tiles.append(tile)

    def _sync_tile_selection(self):
        cur_file = os.path.basename(self.win.wp_config.get("file", "")).lower()
        for tile in self._tiles:
            tile.set_selected(tile.file_name.lower() == cur_file)

    def _on_mode_clicked(self, mode: str):
        prev_only_anim = (self.win.wp_config["mode"] == "animated")
        self.win.update_wallpaper_settings(mode=mode)
        self.refresh_theme_and_texts()
        if prev_only_anim != (mode == "animated"):
            self.reload_grid()
        else:
            self._sync_tile_selection()

    def _on_tile_selected(self, filename: str):
        updates = {"file": filename}
        full = resolve_wallpaper_path(filename)
        if self.win.wp_config["mode"] == "none":
            updates["mode"] = "animated" if is_animated_image_file(full) else "static"
        self.win.update_wallpaper_settings(**updates)
        self.refresh_theme_and_texts()
        self._sync_tile_selection()

    def _on_fit_changed(self, idx: int):
        if 0 <= idx < len(WALLPAPER_FIT_MODES):
            self.win.update_wallpaper_settings(fit=WALLPAPER_FIT_MODES[idx])
            self.refresh_theme_and_texts()
            self.reload_grid()

    def _on_focus_clicked(self, focus: str):
        self.win.update_wallpaper_settings(focus=focus)
        self.refresh_theme_and_texts()
        self.reload_grid()

    def _on_anim_toggled(self, checked: bool):
        self.win.update_wallpaper_settings(animation=checked)
        self.preview_canvas.apply_config(self.win.wp_config, bg_hex=self.win.theme["bg"])

    def _on_interval_changed(self, idx: int):
        if 0 <= idx < len(WALLPAPER_INTERVAL_OPTIONS):
            self.win.update_wallpaper_settings(interval_sec=WALLPAPER_INTERVAL_OPTIONS[idx][0])

    def _on_shuffle_toggled(self, checked: bool):
        self.win.update_wallpaper_settings(shuffle=checked)

    def _on_dim_changed(self, val: int):
        self.lbl_dim_val.setText(f"{val}%")
        self.win.update_wallpaper_settings(dim=val)
        self.preview_canvas.apply_config(self.win.wp_config, bg_hex=self.win.theme["bg"])

    def _on_blur_changed(self, val: int):
        self.lbl_blur_val.setText(str(val))
        self.win.update_wallpaper_settings(blur=val)
        self.preview_canvas.apply_config(self.win.wp_config, bg_hex=self.win.theme["bg"])

    def _on_opacity_changed(self, val: int):
        self.lbl_opacity_val.setText(f"{val}%")
        self.win.update_wallpaper_settings(panel_opacity=val)

    def _add_images(self):
        files, _ = QFileDialog.getOpenFileNames(
            self,
            tr("wp_add_btn", self.win.lang),
            "",
            "Wallpapers (*.jpg *.jpeg *.png *.webp *.bmp *.gif)",
        )
        if not files:
            return
        wp_dir = get_wallpapers_dir()
        copied = []
        for src in files:
            base = os.path.basename(src)
            dest = os.path.join(wp_dir, base)
            if os.path.exists(dest) and os.path.abspath(src) != os.path.abspath(dest):
                stem, ext = os.path.splitext(base)
                dest = os.path.join(wp_dir, f"{stem}_{uuid.uuid4().hex[:6]}{ext}")
            try:
                if os.path.abspath(src) != os.path.abspath(dest):
                    shutil.copy2(src, dest)
                copied.append(os.path.basename(dest))
            except Exception as ex:
                APP_LOG.warn(f"Failed to copy wallpaper {base}: {ex}")
        if copied:
            first = copied[0]
            full = resolve_wallpaper_path(first)
            updates = {"file": first}
            if self.win.wp_config["mode"] == "none":
                updates["mode"] = "animated" if is_animated_image_file(full) else "static"
            self.win.update_wallpaper_settings(**updates)
            self.reload_grid()
            self.refresh_theme_and_texts()
            self.win.toast.show_toast(tr("wp_added_toast", self.win.lang, count=len(copied)), "success", self.win.theme)

    def _remove_selected(self):
        fname = os.path.basename(self.win.wp_config.get("file", ""))
        if not fname:
            return
        ans = QMessageBox.question(
            self,
            tr("wp_remove_title", self.win.lang),
            tr("wp_remove_body", self.win.lang, name=ltr(fname)),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return
        full = os.path.join(get_wallpapers_dir(), fname)
        # Release any active QMovie file handle before deleting on Windows
        self.win.wp_background._stop_movie()
        self.preview_canvas._stop_movie()
        try:
            if os.path.exists(full):
                os.remove(full)
        except Exception as ex:
            APP_LOG.warn(f"Failed to remove wallpaper {fname}: {ex}")
        remaining = list_wallpaper_files(only_animated=(self.win.wp_config["mode"] == "animated"))
        next_file = os.path.basename(remaining[0]) if remaining else ""
        self.win.update_wallpaper_settings(file=next_file)
        self.win.wp_background.reload_folder()
        self.reload_grid()
        self.refresh_theme_and_texts()

    def _open_folder(self):
        wp_dir = get_wallpapers_dir()
        try:
            os.startfile(wp_dir)
        except Exception as ex:
            APP_LOG.warn(f"Failed to open wallpapers folder: {ex}")
            QMessageBox.warning(self, "Error", str(ex))

    def _reload_clicked(self):
        self.win.wp_background.reload_folder()
        self.reload_grid()
        self.refresh_theme_and_texts()
        cnt = len(list_wallpaper_files(only_animated=(self.win.wp_config["mode"] == "animated")))
        self.win.toast.show_toast(tr("wp_reloaded_toast", self.win.lang, count=cnt), "accent", self.win.theme)

    def cleanup(self):
        self.preview_canvas.cleanup()


# ============================================================================
# SETTINGS DIALOG (PHASE 3: SIDEBAR NAVIGATION, OPTION CARDS, PER-SECTION RESET)
# ============================================================================
class SettingsDialog(QDialog):
    """
    Sidebar-navigated Settings dialog with 5 sections:
      0: General      1: Appearance      2: Wallpaper      3: Battery      4: App Icon
    Instant visual apply, RTL/LTR mirroring, keyboard focus order, tooltips, and per-section reset.
    """
    SECTIONS = (
        ("general",    "set_nav_general",    "set_sec_general_desc",    "settings"),
        ("appearance", "set_nav_appearance", "set_sec_appearance_desc", "palette"),
        ("wallpaper",  "set_nav_wallpaper",  "set_sec_wallpaper_desc",  "image"),
        ("battery",    "set_nav_battery",    "set_sec_battery_desc",    "battery"),
        ("icon",       "set_nav_icon",       "set_sec_icon_desc",       "mouse"),
    )

    def __init__(self, parent_win: "GM80PlusGlassWindow", initial_section: int = 0):
        super().__init__(parent_win)
        self.win = parent_win
        self.setObjectName("SettingsDialog")
        self.setModal(True)
        self.resize(880, 660)
        self.setMinimumSize(800, 560)
        self._nav_btns: list[QPushButton] = []
        self._sec_headers: list[tuple[QLabel, QLabel]] = []
        self._build_dialog_ui()
        self._switch_section(max(0, min(len(self.SECTIONS) - 1, initial_section)))
        self._refresh_theme_and_texts()

    def _make_section_page(self) -> tuple[QWidget, QVBoxLayout, QLabel, QLabel]:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 4, 0)
        lay.setSpacing(SP["md"])

        lbl_title = QLabel()
        lbl_title.setObjectName("TitleLabel")
        lbl_desc = QLabel()
        lbl_desc.setObjectName("SubtitleLabel")
        lbl_desc.setWordWrap(True)

        hdr_box = QVBoxLayout()
        hdr_box.setSpacing(2)
        hdr_box.addWidget(lbl_title)
        hdr_box.addWidget(lbl_desc)
        lay.addLayout(hdr_box)

        div = QFrame()
        div.setObjectName("DividerLine")
        lay.addWidget(div)

        self._sec_headers.append((lbl_title, lbl_desc))
        return page, lay, lbl_title, lbl_desc

    def _make_option_card(self, control: QWidget | None = None) -> tuple[QFrame, QLabel, QLabel, QHBoxLayout]:
        card = QFrame()
        card.setObjectName("SubCard")
        row = QHBoxLayout(card)
        row.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        row.setSpacing(SP["lg"])

        txt_col = QVBoxLayout()
        txt_col.setSpacing(3)
        lbl_t = QLabel()
        lbl_t.setObjectName("SectionTitle")
        lbl_d = QLabel()
        lbl_d.setObjectName("SubtitleLabel")
        lbl_d.setWordWrap(True)
        txt_col.addWidget(lbl_t)
        txt_col.addWidget(lbl_d)
        row.addLayout(txt_col, 1)

        if control is not None:
            row.addWidget(control, 0, Qt.AlignVCenter)
        return card, lbl_t, lbl_d, row

    def _build_dialog_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        root.setSpacing(SP["md"])

        # Main split: Sidebar (auto-mirrors in RTL) + Stacked Content Area
        body_row = QHBoxLayout()
        body_row.setSpacing(SP["lg"])

        sidebar = QFrame()
        sidebar.setObjectName("SettingsSidebar")
        sidebar.setFixedWidth(196)
        sb_lay = QVBoxLayout(sidebar)
        sb_lay.setContentsMargins(SP["sm"], SP["md"], SP["sm"], SP["md"])
        sb_lay.setSpacing(SP["xs"])

        self.lbl_dlg_title = QLabel()
        self.lbl_dlg_title.setObjectName("SectionTitle")
        self.lbl_dlg_title.setContentsMargins(SP["sm"], 2, SP["sm"], SP["sm"])
        sb_lay.addWidget(self.lbl_dlg_title)

        for idx in range(len(self.SECTIONS)):
            btn = QPushButton()
            btn.setObjectName("NavItemBtn")
            btn.setProperty("active", "false")
            btn.setIconSize(QSize(15, 15))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFocusPolicy(Qt.StrongFocus)
            btn.clicked.connect(lambda checked=False, i=idx: self._switch_section(i))
            sb_lay.addWidget(btn)
            self._nav_btns.append(btn)
        sb_lay.addStretch()
        body_row.addWidget(sidebar)

        # Content Stack wrapped cleanly inside a Card
        content_card = QFrame()
        content_card.setObjectName("Card")
        cc_lay = QVBoxLayout(content_card)
        cc_lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])

        self.pages_stack = QStackedWidget()
        self.pages_stack.addWidget(self._build_general_page())
        self.pages_stack.addWidget(self._build_appearance_page())
        self.pages_stack.addWidget(self._build_wallpaper_page())
        self.pages_stack.addWidget(self._build_battery_page())
        self.pages_stack.addWidget(self._build_icon_page())
        cc_lay.addWidget(self.pages_stack, 1)
        body_row.addWidget(content_card, 1)
        root.addLayout(body_row, 1)

        # Footer: Reset active section (start) + feedback note + Close (end)
        foot = QHBoxLayout()
        foot.setSpacing(SP["sm"])

        self.btn_reset_sec = QPushButton()
        self.btn_reset_sec.setObjectName("GhostBtn")
        self.btn_reset_sec.clicked.connect(self._reset_current_section)
        foot.addWidget(self.btn_reset_sec)

        self.lbl_reset_feedback = QLabel("")
        self.lbl_reset_feedback.setObjectName("StatusText")
        self.lbl_reset_feedback.setProperty("tone", "success")
        foot.addWidget(self.lbl_reset_feedback, 1)

        self.btn_dlg_close = QPushButton()
        self.btn_dlg_close.setObjectName("PrimaryBtn")
        self.btn_dlg_close.clicked.connect(self.accept)
        foot.addWidget(self.btn_dlg_close)
        root.addLayout(foot)

        # Explicit keyboard focus order across sidebar buttons -> footer
        for i in range(len(self._nav_btns) - 1):
            self.setTabOrder(self._nav_btns[i], self._nav_btns[i + 1])
        self.setTabOrder(self._nav_btns[-1], self.btn_reset_sec)
        self.setTabOrder(self.btn_reset_sec, self.btn_dlg_close)

    def _build_general_page(self) -> QWidget:
        page, lay, _, _ = self._make_section_page()

        self.chk_bg = ToggleSwitch(self, self.win.theme)
        self.chk_bg.setChecked(self.win.run_in_background)
        self.chk_bg.toggled.connect(self._on_bg_toggled)
        c_bg, self.lbl_bg_hdr, self.lbl_bg_hint, _ = self._make_option_card(self.chk_bg)
        lay.addWidget(c_bg)

        lay.addStretch()
        return page

    def _build_appearance_page(self) -> QWidget:
        page, lay, _, _ = self._make_section_page()

        # Theme Mode card
        mode_wrap = QWidget()
        m_row = QHBoxLayout(mode_wrap)
        m_row.setContentsMargins(0, 0, 0, 0)
        m_row.setSpacing(6)
        self.theme_btns: dict[str, QPushButton] = {}
        for key in ("dark", "light", "system"):
            b = QPushButton()
            b.setObjectName("SegmentBtn")
            b.setProperty("active", "false")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, m=key: self._on_theme_mode(m))
            m_row.addWidget(b)
            self.theme_btns[key] = b
        c_theme, self.lbl_theme_hdr, self.lbl_theme_desc, _ = self._make_option_card(mode_wrap)
        lay.addWidget(c_theme)

        # Accent Color card (stacked vertical for swatches + hex/picker)
        c_acc = QFrame()
        c_acc.setObjectName("SubCard")
        acc_lay = QVBoxLayout(c_acc)
        acc_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        acc_lay.setSpacing(SP["sm"])
        self.lbl_accent_hdr = QLabel()
        self.lbl_accent_hdr.setObjectName("SectionTitle")
        self.lbl_accent_desc = QLabel()
        self.lbl_accent_desc.setObjectName("SubtitleLabel")
        self.lbl_accent_desc.setWordWrap(True)
        acc_lay.addWidget(self.lbl_accent_hdr)
        acc_lay.addWidget(self.lbl_accent_desc)

        self.accent_picker = AccentColorPickerWidget(
            self.win.accent_color, self.win.theme, self.win.lang, self
        )
        self.accent_picker.accent_changed.connect(self._on_accent_changed)
        acc_lay.addWidget(self.accent_picker)
        lay.addWidget(c_acc)

        # Language card
        self.cmb_lang = QComboBox()
        self.cmb_lang.setMinimumWidth(186)
        self.cmb_lang.addItems([f"العربية {ltr('(Arabic)')}", "English"])
        self.cmb_lang.setCurrentIndex(1 if self.win.lang == "en" else 0)
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_combo)
        c_lang, self.lbl_lang_hdr, self.lbl_lang_desc, _ = self._make_option_card(self.cmb_lang)
        lay.addWidget(c_lang)

        lay.addStretch()
        return page

    def _build_wallpaper_page(self) -> QWidget:
        page, lay, _, _ = self._make_section_page()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        holder = QWidget()
        h_lay = QVBoxLayout(holder)
        h_lay.setContentsMargins(6, 0, 6, 0)
        self.wp_panel = WallpaperSettingsWidget(self.win, self)
        h_lay.addWidget(self.wp_panel)
        h_lay.addStretch()
        scroll.setWidget(holder)
        lay.addWidget(scroll, 1)
        return page

    def _build_battery_page(self) -> QWidget:
        page, lay, _, _ = self._make_section_page()

        # 1. Auto Battery Poll Interval
        self.cmb_dlg_bat = QComboBox()
        self.cmb_dlg_bat.setMinimumWidth(186)
        self.cmb_dlg_bat.currentIndexChanged.connect(self._on_bat_combo)
        c_bat, self.lbl_bat_hdr, self.lbl_bat_desc, _ = self._make_option_card(self.cmb_dlg_bat)
        lay.addWidget(c_bat)

        # 2. Battery Indicator Style + Interactive Live Preview
        c_style = QFrame()
        c_style.setObjectName("SubCard")
        st_lay = QVBoxLayout(c_style)
        st_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        st_lay.setSpacing(SP["md"])

        self.lbl_bat_style_hdr = QLabel()
        self.lbl_bat_style_hdr.setObjectName("SectionTitle")
        self.lbl_bat_style_desc = QLabel()
        self.lbl_bat_style_desc.setObjectName("SubtitleLabel")
        self.lbl_bat_style_desc.setWordWrap(True)
        st_lay.addWidget(self.lbl_bat_style_hdr)
        st_lay.addWidget(self.lbl_bat_style_desc)

        btn_grid = QGridLayout()
        btn_grid.setSpacing(SP["sm"])
        self.bat_style_btns: dict[str, QPushButton] = {}
        for idx, skey in enumerate(BATTERY_STYLES):
            b = QPushButton()
            b.setObjectName("SegmentBtn")
            b.setProperty("active", "false")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, s=skey: self._on_bat_style_clicked(s))
            btn_grid.addWidget(b, idx // 3, idx % 3)
            self.bat_style_btns[skey] = b
        st_lay.addLayout(btn_grid)

        # Live Preview Strip (level slider + charging toggle)
        prev_row = QHBoxLayout()
        prev_row.setSpacing(SP["md"])
        self.lbl_bat_prev = QLabel()
        self.lbl_bat_prev.setObjectName("SubtitleLabel")
        prev_row.addWidget(self.lbl_bat_prev)

        self.bat_preview_widget = BatteryIndicatorWidget(self, self.win.theme, compact=False)
        self.bat_preview_widget.set_style_name(self.win.battery_style)
        init_pct = self.win.driver.battery_percent if self.win.driver.battery_percent is not None else 72
        self.bat_preview_widget.set_state(True, init_pct, charging=bool(self.win.driver.battery_charging), animate=False)
        prev_row.addWidget(self.bat_preview_widget)

        self.sl_bat_prev = QSlider(Qt.Horizontal)
        self.sl_bat_prev.setRange(5, 100)
        self.sl_bat_prev.setValue(init_pct)
        self.sl_bat_prev.setMinimumWidth(90)
        self.sl_bat_prev.valueChanged.connect(self._on_bat_preview_changed)
        prev_row.addWidget(self.sl_bat_prev, 1)

        self.lbl_bat_prev_chg = QLabel()
        self.lbl_bat_prev_chg.setObjectName("SubtitleLabel")
        prev_row.addWidget(self.lbl_bat_prev_chg)
        self.chk_bat_prev_chg = ToggleSwitch(self, self.win.theme)
        self.chk_bat_prev_chg.setChecked(bool(self.win.driver.battery_charging))
        self.chk_bat_prev_chg.toggled.connect(self._on_bat_preview_changed)
        prev_row.addWidget(self.chk_bat_prev_chg)
        st_lay.addLayout(prev_row)
        lay.addWidget(c_style)

        # 3. Optional System Tray Style Toggle
        self.chk_bat_tray = ToggleSwitch(self, self.win.theme)
        self.chk_bat_tray.setChecked(self.win.battery_tray_style)
        self.chk_bat_tray.toggled.connect(self._on_bat_tray_toggled)
        c_tray, self.lbl_bat_tray_hdr, self.lbl_bat_tray_desc, _ = self._make_option_card(self.chk_bat_tray)
        lay.addWidget(c_tray)

        lay.addStretch()
        return page

    def _build_icon_page(self) -> QWidget:
        page, lay, _, _ = self._make_section_page()

        c_ico = QFrame()
        c_ico.setObjectName("SubCard")
        ico_lay = QVBoxLayout(c_ico)
        ico_lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        ico_lay.setSpacing(SP["md"])

        top_row = QHBoxLayout()
        top_row.setSpacing(SP["md"])
        self.lbl_ico_preview = QLabel()
        self.lbl_ico_preview.setObjectName("IconPreviewBox")
        self.lbl_ico_preview.setFixedSize(56, 56)
        self.lbl_ico_preview.setAlignment(Qt.AlignCenter)
        top_row.addWidget(self.lbl_ico_preview)

        info_col = QVBoxLayout()
        info_col.setSpacing(3)
        self.lbl_ico_hdr = QLabel()
        self.lbl_ico_hdr.setObjectName("SectionTitle")
        self.lbl_ico_desc = QLabel()
        self.lbl_ico_desc.setObjectName("SubtitleLabel")
        self.lbl_ico_desc.setWordWrap(True)
        self.lbl_ico_active = QLabel()
        self.lbl_ico_active.setObjectName("MutedLabel")
        info_col.addWidget(self.lbl_ico_hdr)
        info_col.addWidget(self.lbl_ico_desc)
        info_col.addWidget(self.lbl_ico_active)
        top_row.addLayout(info_col, 1)
        ico_lay.addLayout(top_row)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SP["sm"])
        self.btn_pick_ico = QPushButton()
        self.btn_pick_ico.setObjectName("SecondaryBtn")
        self.btn_pick_ico.clicked.connect(self._pick_custom_icon)
        btn_row.addWidget(self.btn_pick_ico)

        self.btn_reset_ico = QPushButton()
        self.btn_reset_ico.setObjectName("GhostBtn")
        self.btn_reset_ico.clicked.connect(self._reset_default_icon)
        btn_row.addWidget(self.btn_reset_ico)
        btn_row.addStretch()
        ico_lay.addLayout(btn_row)

        lay.addWidget(c_ico)
        lay.addStretch()
        return page

    def _switch_section(self, idx: int):
        self.pages_stack.setCurrentIndex(idx)
        self.lbl_reset_feedback.setText("")
        t = self.win.theme
        for i, (btn, (_, _, _, ic)) in enumerate(zip(self._nav_btns, self.SECTIONS, strict=True)):
            is_act = (i == idx)
            btn.setProperty("active", "true" if is_act else "false")
            btn.setIcon(svg_icon(ic, t["accent"] if is_act else t["text_secondary"], 15))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _refresh_theme_and_texts(self):
        lg = self.win.lang
        en = (lg == "en")
        solid_t = build_theme(self.win.theme_mode, self.win.accent_color, self.win.ui_font)
        self.setLayoutDirection(Qt.LeftToRight if en else Qt.RightToLeft)
        self.setStyleSheet(build_qss(solid_t))

        self.setWindowTitle(tr("dlg_settings_title", lg))
        self.lbl_dlg_title.setText(tr("dlg_settings_hdr", lg))

        # Sidebar buttons + section page headers
        cur_idx = self.pages_stack.currentIndex()
        dir_prop = "ltr" if en else "rtl"
        for i, ((_, nav_key, desc_key, ic), btn, (lbl_t, lbl_d)) in enumerate(
            zip(self.SECTIONS, self._nav_btns, self._sec_headers, strict=True)
        ):
            title_txt = tr(nav_key, lg)
            desc_txt = tr(desc_key, lg)
            is_act = (i == cur_idx)
            btn.setText(title_txt)
            btn.setToolTip(desc_txt)
            btn.setProperty("dir", dir_prop)
            btn.setProperty("active", "true" if is_act else "false")
            btn.setIcon(svg_icon(ic, solid_t["accent"] if is_act else solid_t["text_secondary"], 15))
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            lbl_t.setText(title_txt)
            lbl_d.setText(desc_txt)

        # General
        self.lbl_bg_hdr.setText(tr("set_bg_hdr", lg))
        self.lbl_bg_hint.setText(tr("set_bg_hint", lg))
        self.chk_bg.set_theme(solid_t)
        self.chk_bg.blockSignals(True)
        self.chk_bg.setChecked(self.win.run_in_background)
        self.chk_bg.blockSignals(False)

        # Appearance
        self.lbl_theme_hdr.setText(tr("set_theme_hdr", lg))
        self.lbl_theme_desc.setText(tr("set_theme_desc", lg))
        self.lbl_accent_hdr.setText(tr("set_accent_hdr", lg))
        self.lbl_accent_desc.setText(tr("set_accent_desc", lg))
        self.lbl_lang_hdr.setText(tr("set_lang_hdr", lg))
        self.lbl_lang_desc.setText(tr("set_lang_desc", lg))

        mode_meta = {
            "dark": ("set_theme_dark", "moon"),
            "light": ("set_theme_light", "sun"),
            "system": ("set_theme_system", "monitor"),
        }
        for key, (tk, ic) in mode_meta.items():
            b = self.theme_btns[key]
            is_act = (self.win.theme_mode == key)
            b.setText(tr(tk, lg))
            b.setIcon(svg_icon(ic, solid_t["accent"] if is_act else solid_t["text_secondary"], 14))
            b.setProperty("active", "true" if is_act else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        self.accent_picker.refresh(self.win.accent_color, solid_t, lg)
        self.cmb_lang.blockSignals(True)
        self.cmb_lang.setCurrentIndex(1 if en else 0)
        self.cmb_lang.blockSignals(False)

        # Wallpaper
        self.wp_panel.refresh_theme_and_texts()

        # Battery
        self.lbl_bat_hdr.setText(tr("set_bat_hdr", lg))
        self.lbl_bat_desc.setText(tr("set_bat_desc", lg))
        self.cmb_dlg_bat.blockSignals(True)
        self.cmb_dlg_bat.clear()
        self.cmb_dlg_bat.addItems([opt[2 if en else 1] for opt in BAT_POLL_OPTIONS])
        self.cmb_dlg_bat.setCurrentIndex(self.win.get_battery_interval_index())
        self.cmb_dlg_bat.blockSignals(False)

        self.lbl_bat_style_hdr.setText(tr("bat_style_hdr", lg))
        self.lbl_bat_style_desc.setText(tr("bat_style_desc", lg))
        style_keys = {
            "classic": "bat_style_classic",
            "pill": "bat_style_pill",
            "ring": "bat_style_ring",
            "vertical": "bat_style_vertical",
            "segmented": "bat_style_segmented",
        }
        for skey, tk in style_keys.items():
            b = self.bat_style_btns[skey]
            b.setText(tr(tk, lg))
            b.setProperty("active", "true" if self.win.battery_style == skey else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        self.lbl_bat_prev.setText(tr("bat_preview_hdr", lg))
        self.lbl_bat_prev_chg.setText(tr("bat_preview_chg", lg))
        self.bat_preview_widget.set_theme(solid_t)
        self.bat_preview_widget.set_style_name(self.win.battery_style)
        self.chk_bat_prev_chg.set_theme(solid_t)
        self.lbl_bat_tray_hdr.setText(tr("bat_tray_style_hdr", lg))
        self.lbl_bat_tray_desc.setText(tr("bat_tray_style_desc", lg))
        self.chk_bat_tray.set_theme(solid_t)
        self.chk_bat_tray.blockSignals(True)
        self.chk_bat_tray.setChecked(self.win.battery_tray_style)
        self.chk_bat_tray.blockSignals(False)

        # App Icon
        self.lbl_ico_hdr.setText(tr("set_ico_hdr", lg))
        self.lbl_ico_desc.setText(tr("set_ico_desc", lg))
        custom_name = self.win.settings.get("custom_icon", "")
        if custom_name:
            self.lbl_ico_active.setText(tr("set_ico_active_custom", lg, name=ltr(os.path.basename(custom_name))))
        else:
            self.lbl_ico_active.setText(tr("set_ico_active_default", lg))
        self.btn_pick_ico.setText(tr("set_ico_pick", lg))
        self.btn_pick_ico.setIcon(svg_icon("image", solid_t["text"], 14))
        self.btn_reset_ico.setText(tr("set_ico_reset", lg))
        self.btn_reset_ico.setIcon(svg_icon("rotate_ccw", solid_t["text_secondary"], 14))
        ico_p = get_active_icon_path(custom_name)
        if ico_p and os.path.exists(ico_p):
            self.lbl_ico_preview.setPixmap(QIcon(ico_p).pixmap(44, 44))

        # Footer
        self.btn_reset_sec.setText(tr("set_reset_section", lg))
        self.btn_reset_sec.setToolTip(tr("set_reset_section_tip", lg))
        self.btn_reset_sec.setIcon(svg_icon("rotate_ccw", solid_t["text_secondary"], 14))
        self.btn_dlg_close.setText(tr("btn_close", lg))

    def _reset_current_section(self):
        idx = self.pages_stack.currentIndex()
        sec_id, nav_key, _, _ = self.SECTIONS[idx]
        if sec_id == "general":
            self.win.set_run_in_background(DEFAULT_SETTINGS["run_in_background"])
        elif sec_id == "appearance":
            self.win.theme_mode = DEFAULT_SETTINGS["theme_mode"]
            self.win.accent_color = DEFAULT_SETTINGS["accent_color"]
            self.win._save_current_settings()
            self.win._apply_theme()
            if self.win.lang != DEFAULT_SETTINGS["language"]:
                self.win.set_language(DEFAULT_SETTINGS["language"])
        elif sec_id == "wallpaper":
            self.win.update_wallpaper_settings(
                mode=DEFAULT_SETTINGS["wallpaper_mode"],
                file=DEFAULT_SETTINGS["wallpaper_file"],
                fit=DEFAULT_SETTINGS["wallpaper_fit"],
                focus=DEFAULT_SETTINGS["wallpaper_focus"],
                dim=DEFAULT_SETTINGS["wallpaper_dim"],
                blur=DEFAULT_SETTINGS["wallpaper_blur"],
                panel_opacity=DEFAULT_SETTINGS["wallpaper_panel_opacity"],
                interval_sec=DEFAULT_SETTINGS["wallpaper_interval_sec"],
                shuffle=DEFAULT_SETTINGS["wallpaper_shuffle"],
                animation=DEFAULT_SETTINGS["wallpaper_animation"],
            )
            self.wp_panel.reload_grid()
        elif sec_id == "battery":
            def_idx = next(
                (i for i, opt in enumerate(BAT_POLL_OPTIONS) if opt[0] == DEFAULT_SETTINGS["battery_poll_seconds"]),
                4,
            )
            self.win._on_bat_interval_changed(def_idx)
            self.win.set_battery_style(DEFAULT_SETTINGS["battery_style"])
            self.win.set_battery_tray_style(DEFAULT_SETTINGS["battery_tray_style"])
        elif sec_id == "icon":
            self.win.apply_custom_icon("")

        self._refresh_theme_and_texts()
        msg = tr("set_reset_done", self.win.lang, section=tr(nav_key, self.win.lang))
        self.lbl_reset_feedback.setText(msg)
        self.win.toast.show_toast(msg, "success", self.win.theme)

    def done(self, result: int):
        try:
            self.wp_panel.cleanup()
            self.bat_preview_widget.set_animations_paused(True)
        except Exception as ex:
            APP_LOG.warn(f"Settings cleanup warning: {ex}")
        super().done(result)

    def _on_bat_style_clicked(self, style_name: str):
        self.win.set_battery_style(style_name)
        self._refresh_theme_and_texts()

    def _on_bat_preview_changed(self, *_args):
        self.bat_preview_widget.set_state(
            True,
            self.sl_bat_prev.value(),
            charging=self.chk_bat_prev_chg.isChecked(),
            animate=True,
        )

    def _on_bat_tray_toggled(self, checked: bool):
        self.win.set_battery_tray_style(checked)

    def _on_theme_mode(self, mode: str):
        self.win.set_theme_mode(mode)
        self._refresh_theme_and_texts()

    def _on_accent_changed(self, hex_color: str):
        self.win.set_accent_color(hex_color)
        self._refresh_theme_and_texts()

    def _on_lang_combo(self, idx: int):
        target = "en" if idx == 1 else "ar"
        if target != self.win.lang:
            self.win.set_language(target)
            self._refresh_theme_and_texts()

    def _on_bg_toggled(self, checked: bool):
        self.win.set_run_in_background(checked)

    def _on_bat_combo(self, idx: int):
        if 0 <= idx < len(BAT_POLL_OPTIONS):
            self.win._on_bat_interval_changed(idx)

    def _pick_custom_icon(self):
        lg = self.win.lang
        src, _ = QFileDialog.getOpenFileName(
            self,
            tr("set_ico_pick", lg),
            get_data_dir(),
            "Images (*.ico *.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not src:
            return
        dest = os.path.join(get_data_dir(), "custom_icon.ico")
        if convert_image_to_custom_ico(src, dest):
            self.win.apply_custom_icon("custom_icon.ico")
            self._refresh_theme_and_texts()
        else:
            APP_LOG.error(f"Failed to convert custom app icon: {os.path.basename(src)}")
            QMessageBox.warning(self, tr("set_ico_err_title", lg), tr("set_ico_err_body", lg))

    def _reset_default_icon(self):
        self.win.apply_custom_icon("")
        self._refresh_theme_and_texts()


# ============================================================================
# RUNNING APPS PICKER & GAME PROFILE EDITOR DIALOGS
# ============================================================================
class RunningAppsDialog(QDialog):
    """Picker dialog listing currently open visible Windows applications for 1-click game capture."""

    def __init__(self, parent_win: "GM80PlusGlassWindow"):
        super().__init__(parent_win)
        self.win = parent_win
        self.lg = parent_win.lang
        self.t = parent_win.theme
        self.selected_app = None
        self._apps = []
        self._icon_provider = QFileIconProvider()

        self.setObjectName("GameDialog")
        self.setModal(True)
        self.setMinimumSize(640, 480)
        self.setLayoutDirection(Qt.LeftToRight if self.lg == "en" else Qt.RightToLeft)
        self.setWindowTitle(tr("dlg_run_title", self.lg))
        self.setStyleSheet(build_qss(self.t))
        self._build_ui()
        self._populate_list()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["xl"], SP["lg"], SP["xl"], SP["lg"])
        lay.setSpacing(SP["md"])

        lbl_hdr = QLabel(tr("dlg_run_title", self.lg))
        lbl_hdr.setObjectName("TitleLabel")
        lay.addWidget(lbl_hdr)

        lbl_sub = QLabel(tr("dlg_run_sub", self.lg))
        lbl_sub.setObjectName("SubtitleLabel")
        lay.addWidget(lbl_sub)

        top_bar = QHBoxLayout()
        top_bar.setSpacing(SP["sm"])
        self.txt_filter = QLineEdit()
        self.txt_filter.setPlaceholderText(tr("dlg_run_search", self.lg))
        self.txt_filter.textChanged.connect(self._apply_filter)
        top_bar.addWidget(self.txt_filter, 1)

        btn_ref = QPushButton(tr("dlg_run_refresh", self.lg))
        btn_ref.setObjectName("SecondaryBtn")
        btn_ref.setIcon(svg_icon("refresh", self.t["text"], 14))
        btn_ref.clicked.connect(self._populate_list)
        top_bar.addWidget(btn_ref)
        lay.addLayout(top_bar)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(32, 32))
        self.list_widget.itemDoubleClicked.connect(self._accept_selected)
        lay.addWidget(self.list_widget, 1)

        foot = QHBoxLayout()
        foot.addStretch()
        btn_cancel = QPushButton(tr("btn_cancel", self.lg))
        btn_cancel.setObjectName("SecondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)

        btn_ok = QPushButton(tr("dlg_run_select", self.lg))
        btn_ok.setObjectName("PrimaryBtn")
        btn_ok.setIcon(svg_icon("check", self.t["accent_fg"], 14))
        btn_ok.clicked.connect(self._accept_selected)
        foot.addWidget(btn_ok)
        lay.addLayout(foot)

    def _populate_list(self):
        self._apps = enumerate_running_windows()
        self._apply_filter()

    def _apply_filter(self):
        q = self.txt_filter.text().strip().lower()
        self.list_widget.clear()
        for app in self._apps:
            title = app.get("title", "")
            exe_name = app.get("exe_name", "")
            exe_path = app.get("exe_path", "")
            if q and (q not in title.lower()) and (q not in exe_name.lower()):
                continue
            item = QListWidgetItem(f"{title}\n{ltr(exe_name)}  •  {ltr(exe_path)}")
            item.setData(Qt.UserRole, app)
            if exe_path and os.path.exists(exe_path):
                item.setIcon(self._icon_provider.icon(QFileInfo(exe_path)))
            self.list_widget.addItem(item)
        if self.list_widget.count() > 0:
            self.list_widget.setCurrentRow(0)

    def _accept_selected(self):
        cur = self.list_widget.currentItem()
        if not cur:
            return
        self.selected_app = cur.data(Qt.UserRole)
        self.accept()


class GameProfileEditorDialog(QDialog):
    """Add / Edit dialog for a Game Profile with async high-res icon extraction and custom artwork."""
    _preview_ready = Signal(int, QPixmap)

    def __init__(
        self,
        parent_win: "GM80PlusGlassWindow",
        profile: dict | None = None,
        initial_exe_path: str = "",
        initial_name: str = "",
    ):
        super().__init__(parent_win)
        self.win = parent_win
        self.lg = parent_win.lang
        self.t = parent_win.theme
        self.is_edit = profile is not None
        self.profile_id = profile["id"] if self.is_edit else f"gp_{uuid.uuid4().hex[:10]}"
        self.existing_icon_file = profile.get("icon_file", "") if self.is_edit else ""
        self.exe_path = (profile.get("exe_path", "") if self.is_edit else initial_exe_path) or ""
        self.custom_image_src = ""
        self.force_reextract_exe_icon = False
        self.result_profile = None
        self._preview_gen = 0
        self._preview_ready.connect(self._apply_async_preview)

        init_exe_name = (
            profile.get("exe_name", "") if self.is_edit
            else (os.path.basename(initial_exe_path).lower() if initial_exe_path else "")
        )
        default_display = initial_name or (os.path.splitext(os.path.basename(initial_exe_path))[0] if initial_exe_path else "")
        init_display_name = (profile.get("name", "") if self.is_edit else default_display) or ""
        init_dpi_stage = int(profile.get("dpi_stage", 2)) if self.is_edit else 2
        init_rate = profile.get("polling_rate", "1000 Hz") if self.is_edit else "1000 Hz"
        init_enabled = bool(profile.get("enabled", True)) if self.is_edit else True

        self.setObjectName("GameDialog")
        self.setModal(True)
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.LeftToRight if self.lg == "en" else Qt.RightToLeft)
        self.setWindowTitle(tr("dlg_gp_edit_title" if self.is_edit else "dlg_gp_add_title", self.lg))
        self.setStyleSheet(build_qss(self.t))

        self._build_ui(init_display_name, init_exe_name, init_dpi_stage, init_rate, init_enabled)
        self._refresh_icon_preview()

    def _build_ui(self, init_name: str, init_exe: str, init_stage: int, init_rate: str, init_enabled: bool):
        lg, t = self.lg, self.t
        lay = QVBoxLayout(self)
        lay.setContentsMargins(SP["xl"], SP["lg"], SP["xl"], SP["lg"])
        lay.setSpacing(SP["md"])

        lbl_title = QLabel(tr("dlg_gp_edit_title" if self.is_edit else "dlg_gp_add_title", lg))
        lbl_title.setObjectName("TitleLabel")
        lay.addWidget(lbl_title)

        ico_card = QFrame()
        ico_card.setObjectName("SubCard")
        ic_lay = QHBoxLayout(ico_card)
        ic_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        ic_lay.setSpacing(SP["md"])

        self.lbl_preview = QLabel()
        self.lbl_preview.setFixedSize(64, 64)
        self.lbl_preview.setAlignment(Qt.AlignCenter)
        ic_lay.addWidget(self.lbl_preview)

        ic_btns_col = QVBoxLayout()
        ic_btns_col.setSpacing(SP["sm"])
        lbl_ic_hint = QLabel(tr("dlg_gp_icon_hint", lg))
        lbl_ic_hint.setObjectName("SubtitleLabel")
        ic_btns_col.addWidget(lbl_ic_hint)

        ic_row = QHBoxLayout()
        ic_row.setSpacing(SP["sm"])
        btn_custom_img = QPushButton(tr("dlg_gp_pick_img", lg))
        btn_custom_img.setObjectName("SecondaryBtn")
        btn_custom_img.setIcon(svg_icon("image", t["text"], 14))
        btn_custom_img.clicked.connect(self._pick_custom_image)
        ic_row.addWidget(btn_custom_img)

        btn_reextract = QPushButton(tr("dlg_gp_extract_ico", lg))
        btn_reextract.setObjectName("GhostBtn")
        btn_reextract.setIcon(svg_icon("refresh", t["text_secondary"], 14))
        btn_reextract.clicked.connect(self._reextract_icon)
        ic_row.addWidget(btn_reextract)
        ic_row.addStretch()
        ic_btns_col.addLayout(ic_row)
        ic_lay.addLayout(ic_btns_col, 1)
        lay.addWidget(ico_card)

        form_card = QFrame()
        form_card.setObjectName("SubCard")
        f_lay = QGridLayout(form_card)
        f_lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        f_lay.setHorizontalSpacing(SP["md"])
        f_lay.setVerticalSpacing(SP["md"])

        lbl_name = QLabel(tr("dlg_gp_name", lg))
        lbl_name.setObjectName("SectionTitle")
        self.txt_name = QLineEdit(init_name)
        self.txt_name.setPlaceholderText(tr("dlg_gp_name_ph", lg))
        f_lay.addWidget(lbl_name, 0, 0)
        f_lay.addWidget(self.txt_name, 0, 1, 1, 2)

        lbl_exe = QLabel(tr("dlg_gp_exe", lg))
        lbl_exe.setObjectName("SectionTitle")
        self.txt_exe = QLineEdit(init_exe)
        self.txt_exe.setObjectName("PathBox")
        self.txt_exe.setLayoutDirection(Qt.LeftToRight)
        self.txt_exe.setPlaceholderText(tr("dlg_gp_exe_ph", lg))
        btn_browse_exe = QPushButton(tr("dlg_gp_browse", lg))
        btn_browse_exe.setObjectName("SecondaryBtn")
        btn_browse_exe.setIcon(svg_icon("folder", t["text"], 14))
        btn_browse_exe.clicked.connect(self._browse_exe)
        f_lay.addWidget(lbl_exe, 1, 0)
        f_lay.addWidget(self.txt_exe, 1, 1)
        f_lay.addWidget(btn_browse_exe, 1, 2)

        lbl_dpi = QLabel(tr("dlg_gp_dpi", lg))
        lbl_dpi.setObjectName("SectionTitle")
        self.cmb_dpi = QComboBox()
        for idx, val in enumerate(DEFAULT_DPI_VALUES):
            self.cmb_dpi.addItem(f"{tr('dpi_stage_n', lg, n=idx + 1)} — {ltr(f'{val} DPI')}", idx)
        self.cmb_dpi.setCurrentIndex(max(0, min(5, init_stage)))
        f_lay.addWidget(lbl_dpi, 2, 0)
        f_lay.addWidget(self.cmb_dpi, 2, 1, 1, 2)

        lbl_rate = QLabel(tr("dlg_gp_rate", lg))
        lbl_rate.setObjectName("SectionTitle")
        self.cmb_rate = QComboBox()
        for rn in ("125 Hz", "250 Hz", "500 Hz", "1000 Hz"):
            self.cmb_rate.addItem(rn)
        r_idx = self.cmb_rate.findText(init_rate)
        self.cmb_rate.setCurrentIndex(r_idx if r_idx >= 0 else 3)
        f_lay.addWidget(lbl_rate, 3, 0)
        f_lay.addWidget(self.cmb_rate, 3, 1, 1, 2)

        en_row = QHBoxLayout()
        lbl_en = QLabel(tr("dlg_gp_enabled", lg))
        lbl_en.setObjectName("SectionTitle")
        self.chk_enabled = ToggleSwitch(self, t)
        self.chk_enabled.setChecked(init_enabled)
        en_row.addWidget(lbl_en, 1)
        en_row.addWidget(self.chk_enabled)
        f_lay.addLayout(en_row, 4, 0, 1, 3)

        lay.addWidget(form_card)

        foot = QHBoxLayout()
        foot.addStretch()
        btn_cancel = QPushButton(tr("btn_cancel", lg))
        btn_cancel.setObjectName("SecondaryBtn")
        btn_cancel.clicked.connect(self.reject)
        foot.addWidget(btn_cancel)

        btn_save = QPushButton(tr("dlg_gp_save", lg))
        btn_save.setObjectName("PrimaryBtn")
        btn_save.setIcon(svg_icon("save", t["accent_fg"], 14))
        btn_save.clicked.connect(self._on_save)
        foot.addWidget(btn_save)
        lay.addLayout(foot)

    def _browse_exe(self):
        src, _ = QFileDialog.getOpenFileName(
            self,
            tr("dlg_gp_exe", self.lg),
            os.path.dirname(self.exe_path) if self.exe_path else "",
            "Executables (*.exe)",
        )
        if not src:
            return
        self.exe_path = src
        exe_base = os.path.basename(src).lower()
        self.txt_exe.setText(exe_base)
        if not self.txt_name.text().strip():
            self.txt_name.setText(os.path.splitext(os.path.basename(src))[0])
        if not self.custom_image_src:
            self.force_reextract_exe_icon = True
        self._refresh_icon_preview()

    def _pick_custom_image(self):
        src, _ = QFileDialog.getOpenFileName(
            self,
            tr("dlg_gp_pick_img", self.lg),
            "",
            "Images (*.png *.jpg *.jpeg *.webp *.ico *.bmp)",
        )
        if not src:
            return
        self.custom_image_src = src
        self.force_reextract_exe_icon = False
        self._refresh_icon_preview()

    def _reextract_icon(self):
        self.custom_image_src = ""
        self.force_reextract_exe_icon = True
        self._refresh_icon_preview()

    def _refresh_icon_preview(self):
        self._preview_gen += 1
        gen = self._preview_gen
        if self.custom_image_src and os.path.exists(self.custom_image_src):
            self.lbl_preview.setPixmap(load_game_icon_pixmap(self.custom_image_src, self.t, 64))
            return
        if not self.force_reextract_exe_icon and self.existing_icon_file:
            p = os.path.join(get_game_icons_dir(), self.existing_icon_file)
            if os.path.exists(p):
                self.lbl_preview.setPixmap(load_game_icon_pixmap(p, self.t, 64))
                return
        self.lbl_preview.setPixmap(load_game_icon_pixmap("", self.t, 64))
        if self.exe_path and os.path.exists(self.exe_path):
            exe_p = self.exe_path
            theme_snap = dict(self.t)
            threading.Thread(
                target=self._extract_preview_worker,
                args=(gen, exe_p, theme_snap),
                daemon=True,
            ).start()

    def _extract_preview_worker(self, gen: int, exe_p: str, theme_snap: dict):
        tmp_png = os.path.join(tempfile.gettempdir(), f"_gm80_prev_{self.profile_id}_{gen}.png")
        try:
            if extract_exe_icon_to_png(exe_p, tmp_png):
                pm = load_game_icon_pixmap(tmp_png, theme_snap, 64)
                self._preview_ready.emit(gen, pm)
        except Exception as ex:
            APP_LOG.warn(f"Async icon preview failed: {ex}")
        finally:
            try:
                if os.path.exists(tmp_png):
                    os.remove(tmp_png)
            except Exception as ex2:
                APP_LOG.warn(f"Failed removing temp preview icon: {ex2}")

    def _apply_async_preview(self, gen: int, pm: QPixmap):
        if gen == self._preview_gen and not pm.isNull():
            self.lbl_preview.setPixmap(pm)

    def _on_save(self):
        exe_text = self.txt_exe.text().strip()
        if not exe_text:
            QMessageBox.warning(
                self,
                tr("dlg_gp_missing_exe_title", self.lg),
                tr("dlg_gp_missing_exe_body", self.lg),
            )
            return
        exe_name = os.path.basename(exe_text).lower()
        if not exe_name.endswith(".exe"):
            exe_name += ".exe"

        display_name = self.txt_name.text().strip() or os.path.splitext(exe_name)[0]
        icon_filename = f"{self.profile_id}.png"
        dest_png = os.path.join(get_game_icons_dir(), icon_filename)

        final_icon_file = self.existing_icon_file
        if self.custom_image_src and os.path.exists(self.custom_image_src):
            if save_custom_game_image(self.custom_image_src, dest_png):
                final_icon_file = icon_filename
        elif self.force_reextract_exe_icon or not final_icon_file:
            if self.exe_path and os.path.exists(self.exe_path):
                if extract_exe_icon_to_png(self.exe_path, dest_png):
                    final_icon_file = icon_filename

        self.result_profile = {
            "id": self.profile_id,
            "name": display_name,
            "exe_name": exe_name,
            "exe_path": self.exe_path,
            "dpi_stage": int(self.cmb_dpi.currentIndex()),
            "polling_rate": self.cmb_rate.currentText(),
            "enabled": bool(self.chk_enabled.isChecked()),
            "icon_file": final_icon_file,
        }
        self.accept()


# ============================================================================
# MAIN WINDOW (PHASE 1: CLEAN DESIGN SYSTEM, SOLID THEME, SVG ICONS, DEV LOG)
# ============================================================================
class GM80PlusGlassWindow(QMainWindow):
    def __init__(self, driver: YJXGM80PlusDriver, ui_font: str = "Segoe UI"):
        super().__init__()
        self.driver = driver
        self.ui_font = ui_font
        self.settings = load_settings()
        self.lang = self.settings.get("language", "ar")
        self.theme_mode = self.settings.get("theme_mode", "dark")
        self.accent_color = self.settings.get("accent_color", "#3B82F6")
        self.wp_config = {
            "mode": self.settings.get("wallpaper_mode", "none"),
            "file": self.settings.get("wallpaper_file", ""),
            "fit": self.settings.get("wallpaper_fit", "smart_fill"),
            "focus": self.settings.get("wallpaper_focus", "center"),
            "dim": int(self.settings.get("wallpaper_dim", 30)),
            "blur": int(self.settings.get("wallpaper_blur", 0)),
            "interval_sec": int(self.settings.get("wallpaper_interval_sec", 60)),
            "shuffle": bool(self.settings.get("wallpaper_shuffle", False)),
            "animation": bool(self.settings.get("wallpaper_animation", True)),
        }
        self.wp_panel_opacity = int(self.settings.get("wallpaper_panel_opacity", 90))
        self.battery_style = self.settings.get("battery_style", "classic")
        self.battery_tray_style = bool(self.settings.get("battery_tray_style", True))
        self.theme = build_theme(
            self.theme_mode,
            self.accent_color,
            self.ui_font,
            panel_opacity=self.wp_panel_opacity,
            wallpaper_active=(self.wp_config["mode"] != "none"),
        )
        self.driver.lang = self.lang

        self.run_in_background = bool(self.settings.get("run_in_background", False))
        self.bat_poll_seconds = int(self.settings.get("battery_poll_seconds", 180))
        self._manual_poll_pending = False

        # Game Profiles state
        self.game_profiles = [dict(p) for p in self.settings.get("game_profiles", [])]
        dp_raw = self.settings.get("default_profile", {})
        self.default_profile = {
            "dpi_stage": max(0, min(5, int(dp_raw.get("dpi_stage", 2)))),
            "polling_rate": dp_raw.get("polling_rate", "500 Hz") if dp_raw.get("polling_rate") in POLLING_RATES else "500 Hz",
        }
        self.game_exit_delay_sec = max(0, min(300, int(self.settings.get("game_exit_delay_sec", 30))))
        self.active_game_profile_id = None
        self.exit_countdown_sec = 0
        self._last_applied_hw_tuple = None
        self._game_hw_busy = False
        self._poll_busy = False
        self._hw_read_busy = False
        self._hw_apply_busy = False
        self._hotplug_busy = False
        self._conflict_busy = False
        self._closing = False
        self._game_card_status_lbls = {}
        self._last_device_signature = None

        try:
            self._show_msg_id = ctypes.windll.user32.RegisterWindowMessageW(SHOW_WINDOW_MSG_NAME)
        except Exception as ex:
            APP_LOG.warn(f"RegisterWindowMessageW failed: {ex}")
            self._show_msg_id = 0

        self.signals = WorkerSignals()
        self.signals.poll_done.connect(self._on_poll_done)
        self.signals.apply_done.connect(self._on_apply_done)
        self.signals.init_read_done.connect(self._on_init_read_done)
        self.signals.game_profile_done.connect(self._on_game_profile_done)
        self.signals.hotplug_changed.connect(self._on_hotplug_changed)
        self.signals.conflict_found.connect(self._on_conflict_found)
        self.signals.conflict_closed.connect(self._on_conflict_closed)
        self.signals.shortcut_icon_done.connect(self._on_shortcut_icon_done)

        self.resize(1000, 680)
        self.setMinimumSize(860, 600)
        self.setLayoutDirection(Qt.LeftToRight if self.lang == "en" else Qt.RightToLeft)
        self._apply_window_and_app_icon()

        self._build_ui()
        self._setup_tray()
        self.toast = ToastBanner(self)

        self._apply_theme()
        self._apply_language()
        self._sync_ui_from_driver()

        # Timers
        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(lambda: self.trigger_battery_poll(manual=False))
        if self.bat_poll_seconds > 0:
            self.battery_timer.start(self.bat_poll_seconds * 1000)

        self.hotplug_timer = QTimer(self)
        self.hotplug_timer.timeout.connect(self._check_hotplug_transition)
        self.hotplug_timer.start(HOTPLUG_CHECK_INTERVAL_MS)

        self.game_monitor_timer = QTimer(self)
        self.game_monitor_timer.timeout.connect(self._poll_foreground_game)
        self.game_monitor_timer.start(GAME_POLL_INTERVAL_MS)

        self.game_countdown_timer = QTimer(self)
        self.game_countdown_timer.timeout.connect(self._tick_game_exit_countdown)

        # Startup checks
        self.left_btn_locked = True
        self._app_filter_installed = False
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.installEventFilter(self)
            self._app_filter_installed = True

        QTimer.singleShot(300, self._check_driver_conflict)
        QTimer.singleShot(450, self._trigger_initial_hw_read)
        QTimer.singleShot(850, lambda: self.trigger_battery_poll(manual=False))

    def eventFilter(self, obj, event):
        """Live physical mouse button & scroll feedback on the GM80 Plus diagram when Buttons tab is active."""
        if not self._closing and hasattr(self, "mouse_viz") and hasattr(self, "stack"):
            if self.isVisible() and self.isActiveWindow() and self.stack.currentIndex() == 2:
                et = event.type()
                if et in (QEvent.MouseButtonPress, QEvent.MouseButtonDblClick):
                    # Avoid double-triggering when clicking directly inside mouse_viz (which handles its own hit-test)
                    if obj is not self.mouse_viz:
                        bmap = {
                            Qt.LeftButton: 0,
                            Qt.RightButton: 1,
                            Qt.MiddleButton: 2,
                            Qt.ForwardButton: 3,
                            Qt.BackButton: 4,
                        }
                        bi = bmap.get(event.button())
                        if bi is not None:
                            self.mouse_viz.trigger_press(bi, hold=True)
                            self._show_mouse_viz_feedback(bi)
                elif et == QEvent.MouseButtonRelease:
                    bmap = {
                        Qt.LeftButton: 0,
                        Qt.RightButton: 1,
                        Qt.MiddleButton: 2,
                        Qt.ForwardButton: 3,
                        Qt.BackButton: 4,
                    }
                    bi = bmap.get(event.button())
                    if bi is not None:
                        self.mouse_viz.trigger_release(bi)
                elif et == QEvent.Wheel and obj is not self.mouse_viz:
                    dy = event.angleDelta().y()
                    if dy > 0:
                        self.mouse_viz.trigger_press(5, hold=False)
                        self._show_mouse_viz_feedback(5)
                    elif dy < 0:
                        self.mouse_viz.trigger_press(6, hold=False)
                        self._show_mouse_viz_feedback(6)
        return super().eventFilter(obj, event)

    def nativeEvent(self, eventType, message):
        try:
            if self._show_msg_id:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self._show_msg_id:
                    QTimer.singleShot(0, self.restore_from_tray)
                    return True, 0
        except Exception as ex:
            APP_LOG.warn(f"nativeEvent parse warning: {ex}")
        return super().nativeEvent(eventType, message)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.reposition()

    def _apply_window_and_app_icon(self):
        ico_path = get_active_icon_path(self.settings.get("custom_icon", ""))
        if ico_path and os.path.exists(ico_path):
            qico = QIcon(ico_path)
            self.setWindowIcon(qico)
            app_inst = QApplication.instance()
            if app_inst:
                app_inst.setWindowIcon(qico)

    def _save_current_settings(self):
        self.settings["language"] = self.lang
        self.settings["theme_mode"] = self.theme_mode
        self.settings["accent_color"] = self.accent_color
        self.settings["wallpaper_mode"] = self.wp_config["mode"]
        self.settings["wallpaper_file"] = self.wp_config["file"]
        self.settings["wallpaper_fit"] = self.wp_config["fit"]
        self.settings["wallpaper_focus"] = self.wp_config["focus"]
        self.settings["wallpaper_dim"] = self.wp_config["dim"]
        self.settings["wallpaper_blur"] = self.wp_config["blur"]
        self.settings["wallpaper_panel_opacity"] = self.wp_panel_opacity
        self.settings["wallpaper_interval_sec"] = self.wp_config["interval_sec"]
        self.settings["wallpaper_shuffle"] = self.wp_config["shuffle"]
        self.settings["wallpaper_animation"] = self.wp_config["animation"]
        self.settings["run_in_background"] = self.run_in_background
        self.settings["battery_poll_seconds"] = self.bat_poll_seconds
        self.settings["battery_style"] = self.battery_style
        self.settings["battery_tray_style"] = self.battery_tray_style
        self.settings["game_exit_delay_sec"] = self.game_exit_delay_sec
        self.settings["default_profile"] = dict(self.default_profile)
        self.settings["game_profiles"] = list(self.game_profiles)
        save_settings(self.settings)

    def set_battery_style(self, style_name: str):
        if style_name not in BATTERY_STYLES:
            return
        self.battery_style = style_name
        self._save_current_settings()
        if hasattr(self, "bat_indicator"):
            self.bat_indicator.set_style_name(style_name)
        self._refresh_tray()

    def set_battery_tray_style(self, enabled: bool):
        self.battery_tray_style = bool(enabled)
        self._save_current_settings()
        self._refresh_tray()

    def update_wallpaper_settings(self, **kwargs):
        """Apply wallpaper mode/file/fit/focus/dim/blur/opacity/interval/shuffle/animation immediately."""
        prev_active = (self.wp_config["mode"] != "none")
        prev_opacity = self.wp_panel_opacity

        for k in ("mode", "file", "fit", "focus", "dim", "blur", "interval_sec", "shuffle", "animation"):
            if k in kwargs:
                self.wp_config[k] = kwargs[k]
        if "panel_opacity" in kwargs:
            self.wp_panel_opacity = max(55, min(100, int(kwargs["panel_opacity"])))

        self._save_current_settings()
        now_active = (self.wp_config["mode"] != "none")
        if prev_active != now_active or (now_active and prev_opacity != self.wp_panel_opacity):
            self._apply_theme()
        else:
            self.wp_background.apply_config(self.wp_config, bg_hex=self.theme["bg"])

    def _on_wallpaper_error(self, filename: str):
        msg = tr("wp_corrupt_skip", self.lang, name=ltr(filename))
        self._set_status(msg, "warning")
        self.toast.show_toast(msg, "warning", self.theme)

    def _set_status(self, text: str, tone: str = "neutral"):
        self.lbl_status.setText(text)
        self.lbl_status.setProperty("tone", tone)
        self.lbl_status.style().unpolish(self.lbl_status)
        self.lbl_status.style().polish(self.lbl_status)

    def _apply_theme(self):
        self.theme = build_theme(
            self.theme_mode,
            self.accent_color,
            self.ui_font,
            panel_opacity=self.wp_panel_opacity,
            wallpaper_active=(self.wp_config["mode"] != "none"),
        )
        t = self.theme
        self.setStyleSheet(build_qss(t))
        if hasattr(self, "wp_background"):
            self.wp_background.apply_config(self.wp_config, bg_hex=t["bg"])

        # Refresh all SVG icons to match active theme colors
        self.btn_settings.setIcon(svg_icon("settings", t["text"], 15))
        self.btn_refresh_bat.setIcon(svg_icon("refresh", t["text"], 14))
        self.btn_read_hw.setIcon(svg_icon("download", t["text"], 15))
        self.btn_save_hw.setIcon(svg_icon("save", t["accent_fg"], 15))
        self.btn_reset_dpi.setIcon(svg_icon("rotate_ccw", t["text_secondary"], 14))
        self.btn_reset_perf.setIcon(svg_icon("rotate_ccw", t["text_secondary"], 14))
        self.btn_reset_btns.setIcon(svg_icon("rotate_ccw", t["text_secondary"], 14))
        self.btn_kill_orig.setIcon(svg_icon("x_circle", t["text_secondary"], 14))
        self.btn_add_game.setIcon(svg_icon("plus", t["text"], 14))
        self.btn_detect_game.setIcon(svg_icon("radar", t["text_secondary"], 14))

        self._refresh_tab_icons()
        if hasattr(self, "bat_indicator"):
            self.bat_indicator.set_theme(t)
        if hasattr(self, "spn_exit_delay"):
            self.spn_exit_delay.set_theme(t)
        if hasattr(self, "chk_lock_left"):
            self.chk_lock_left.set_theme(t)
        if hasattr(self, "mouse_viz"):
            self.mouse_viz.set_theme(t)
            self._update_mouse_viz_dpi_led()
        self.dev_log.refresh_theme_and_lang(t, self.lang)
        self._rebuild_game_cards()
        self._update_battery_header()
        self._refresh_tray()

    def _refresh_tab_icons(self):
        t = self.theme
        tab_icons = ("dpi", "bolt", "mouse", "gamepad")
        cur_idx = self.stack.currentIndex()
        for i, (b, ic) in enumerate(zip(self.tab_buttons, tab_icons, strict=True)):
            col = t["accent"] if i == cur_idx else t["text_secondary"]
            b.setIcon(svg_icon(ic, col, 15))

    def set_theme_mode(self, mode: str):
        if mode not in ("dark", "light", "system"):
            return
        self.theme_mode = mode
        self._save_current_settings()
        self._apply_theme()

    def set_accent_color(self, hex_color: str):
        clean = (hex_color or "").strip().upper()
        if not re.fullmatch(r"#[0-9A-F]{6}", clean):
            return
        self.accent_color = clean
        self._save_current_settings()
        self._apply_theme()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self)
        dlg.exec()
        dlg.deleteLater()

    def set_language(self, lang: str):
        if lang not in ("ar", "en"):
            return
        self.lang = lang
        self.driver.lang = self.lang
        self.setLayoutDirection(Qt.LeftToRight if self.lang == "en" else Qt.RightToLeft)
        self._save_current_settings()
        self._apply_language()

    def set_run_in_background(self, enabled: bool):
        self.run_in_background = bool(enabled)
        self._save_current_settings()
        self._set_status(tr("status_bg_on" if self.run_in_background else "status_bg_off", self.lang), "accent")

    def apply_custom_icon(self, custom_icon_name: str):
        self.settings["custom_icon"] = custom_icon_name
        self._save_current_settings()
        self._apply_window_and_app_icon()
        self._refresh_tray()
        ico_p = get_active_icon_path(custom_icon_name)
        is_custom = bool(custom_icon_name)
        threading.Thread(
            target=self._shortcut_icon_worker,
            args=(ico_p, is_custom),
            daemon=True,
        ).start()
        msg = tr("status_icon_ok" if is_custom else "status_icon_reset", self.lang)
        self._set_status(msg, "success")
        self.toast.show_toast(msg, "success", self.theme)

    def _shortcut_icon_worker(self, ico_p: str, is_custom: bool):
        ok = update_desktop_shortcut_icon(ico_p)
        self.signals.shortcut_icon_done.emit(is_custom, ok)

    def _on_shortcut_icon_done(self, is_custom: bool, ok: bool):
        APP_LOG.info(f"Desktop shortcut icon updated={ok} (custom={is_custom})")

    # ---------------- Off-UI-Thread Hot-Plug Monitor ----------------

    def _check_hotplug_transition(self):
        """Schedule USB HID hot-plug check off the UI thread (single-flight guarded)."""
        if self._hotplug_busy:
            return
        self._hotplug_busy = True
        threading.Thread(target=self._hotplug_worker, daemon=True).start()

    def _hotplug_worker(self):
        try:
            has_wired = False
            has_wireless = False
            for d in hid.enumerate():
                vid = d.get("vendor_id", 0)
                pid = d.get("product_id", 0)
                if pid in VALID_PIDS and d.get("usage_page") == VENDOR_USAGE_PAGE and d.get("usage") == VENDOR_USAGE:
                    if vid == VID_WIRED:
                        has_wired = True
                    elif vid == VID_WIRELESS:
                        has_wireless = True
            sig = (has_wired, has_wireless)
            if self._last_device_signature is None:
                self._last_device_signature = sig
                return
            if sig != self._last_device_signature:
                prev_wired, _ = self._last_device_signature
                self._last_device_signature = sig
                with self.driver.lock:
                    self.driver.enumerate_devices()
                self.signals.hotplug_changed.emit(prev_wired, has_wired, has_wireless)
        except Exception as ex:
            APP_LOG.warn(f"Hot-plug check error: {ex}")
        finally:
            self._hotplug_busy = False

    def _on_hotplug_changed(self, prev_wired: bool, has_wired: bool, has_wireless: bool):
        self._update_battery_header()
        self._refresh_tray()
        if prev_wired and not has_wired and has_wireless:
            self._set_status(tr("status_hotplug_24g", self.lang), "accent")
            APP_LOG.info("Hot-plug: USB cable unplugged -> switched to 2.4G Dongle")
            QTimer.singleShot(600, self.trigger_battery_poll)
            QTimer.singleShot(900, self._trigger_initial_hw_read)
        elif not prev_wired and has_wired:
            self._set_status(tr("status_hotplug_usb", self.lang), "success")
            APP_LOG.info("Hot-plug: USB cable connected -> switched to USB Wired")
            QTimer.singleShot(600, self._trigger_initial_hw_read)
            QTimer.singleShot(900, self.trigger_battery_poll)
        elif has_wired or has_wireless:
            QTimer.singleShot(500, self._trigger_initial_hw_read)
            QTimer.singleShot(800, self.trigger_battery_poll)

    # ---------------- UI Construction (Clean 8px Grid, Solid Theme, SVG Icons) ----------------

    def _build_ui(self):
        self.wp_background = WallpaperBackgroundWidget(self, is_preview=False)
        self.wp_background.setObjectName("AppRoot")
        self.wp_background.error_occurred.connect(self._on_wallpaper_error)
        self.setCentralWidget(self.wp_background)

        root_layout = QVBoxLayout(self.wp_background)
        root_layout.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["md"])
        root_layout.setSpacing(SP["md"])

        # 1. Compact Header Status Bar: Product + Connection + Battery + Small Refresh Icon + Settings
        header_card = QFrame()
        header_card.setObjectName("HeaderCard")
        header_lay = QHBoxLayout(header_card)
        header_lay.setContentsMargins(SP["lg"], SP["sm"], SP["lg"], SP["sm"])
        header_lay.setSpacing(SP["md"])

        brand_col = QVBoxLayout()
        brand_col.setSpacing(1)
        self.lbl_title = QLabel()
        self.lbl_title.setObjectName("TitleLabel")
        self.lbl_sub = QLabel()
        self.lbl_sub.setObjectName("MutedLabel")
        brand_col.addWidget(self.lbl_title)
        brand_col.addWidget(self.lbl_sub)
        header_lay.addLayout(brand_col)

        sep1 = QFrame()
        sep1.setObjectName("VertSep")
        header_lay.addWidget(sep1, 0, Qt.AlignVCenter)

        # Compact inline connection status
        conn_wrap = QHBoxLayout()
        conn_wrap.setSpacing(6)
        self.lbl_conn_dot = QLabel()
        self.lbl_conn_dot.setObjectName("StatusDot")
        self.lbl_conn_dot.setProperty("tone", "neutral")
        conn_wrap.addWidget(self.lbl_conn_dot, 0, Qt.AlignVCenter)

        self.lbl_conn = QLabel()
        self.lbl_conn.setObjectName("SubtitleLabel")
        conn_wrap.addWidget(self.lbl_conn, 0, Qt.AlignVCenter)
        header_lay.addLayout(conn_wrap)

        header_lay.addStretch(1)

        # Compact inline animated battery indicator + badge + timestamp + small icon-only Update Now button
        bat_strip = QFrame()
        bat_strip.setObjectName("SubCard")
        bat_lay = QHBoxLayout(bat_strip)
        bat_lay.setContentsMargins(SP["md"], 5, 6, 5)
        bat_lay.setSpacing(SP["sm"])

        self.bat_indicator = BatteryIndicatorWidget(self, self.theme, compact=True)
        self.bat_indicator.set_style_name(self.battery_style)
        bat_lay.addWidget(self.bat_indicator, 0, Qt.AlignVCenter)

        self.lbl_bat_badge = QLabel()
        self.lbl_bat_badge.setObjectName("Badge")
        self.lbl_bat_badge.setProperty("tone", "neutral")
        bat_lay.addWidget(self.lbl_bat_badge, 0, Qt.AlignVCenter)

        self.lbl_poll_time = QLabel()
        self.lbl_poll_time.setObjectName("MutedLabel")
        bat_lay.addWidget(self.lbl_poll_time, 0, Qt.AlignVCenter)

        self.btn_refresh_bat = QPushButton()
        self.btn_refresh_bat.setObjectName("IconBtn")
        self.btn_refresh_bat.setFixedSize(30, 30)
        self.btn_refresh_bat.setIconSize(QSize(14, 14))
        self.btn_refresh_bat.setCursor(Qt.PointingHandCursor)
        self.btn_refresh_bat.clicked.connect(lambda: self.trigger_battery_poll(manual=True))
        bat_lay.addWidget(self.btn_refresh_bat, 0, Qt.AlignVCenter)
        header_lay.addWidget(bat_strip, 0, Qt.AlignVCenter)

        self.btn_settings = QPushButton()
        self.btn_settings.setObjectName("SecondaryBtn")
        self.btn_settings.setFixedHeight(36)
        self.btn_settings.setCursor(Qt.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        header_lay.addWidget(self.btn_settings, 0, Qt.AlignVCenter)

        root_layout.addWidget(header_card)

        # 2. Navigation Tab Strip + Read (Secondary) + Save (Sole Primary Button)
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(SP["sm"])

        tab_strip = QFrame()
        tab_strip.setObjectName("TabStrip")
        ts_lay = QHBoxLayout(tab_strip)
        ts_lay.setContentsMargins(4, 4, 4, 4)
        ts_lay.setSpacing(4)

        self.tab_buttons: list[QPushButton] = []
        for idx in range(4):
            b = QPushButton()
            b.setObjectName("TabBtn")
            b.setProperty("active", "true" if idx == 0 else "false")
            b.setIconSize(QSize(15, 15))
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, i=idx: self.switch_tab(i))
            ts_lay.addWidget(b)
            self.tab_buttons.append(b)
        nav_bar.addWidget(tab_strip)

        nav_bar.addStretch()

        self.btn_read_hw = QPushButton()
        self.btn_read_hw.setObjectName("SecondaryBtn")
        self.btn_read_hw.setFixedHeight(38)
        self.btn_read_hw.setCursor(Qt.PointingHandCursor)
        self.btn_read_hw.clicked.connect(self._trigger_initial_hw_read)
        nav_bar.addWidget(self.btn_read_hw)

        self.btn_save_hw = QPushButton()
        self.btn_save_hw.setObjectName("SaveBtn")
        self.btn_save_hw.setFixedHeight(38)
        self.btn_save_hw.setCursor(Qt.PointingHandCursor)
        self.btn_save_hw.clicked.connect(self.trigger_apply_to_hardware)
        nav_bar.addWidget(self.btn_save_hw)

        root_layout.addLayout(nav_bar)

        # 3. Main Content Card Stack
        self.stack_card = QFrame()
        self.stack_card.setObjectName("Card")
        stack_wrap = QVBoxLayout(self.stack_card)
        stack_wrap.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])

        self.stack = QStackedWidget()
        self.stack.addWidget(self._create_dpi_page())
        self.stack.addWidget(self._create_perf_page())
        self.stack.addWidget(self._create_buttons_page())
        self.stack.addWidget(self._create_games_page())
        stack_wrap.addWidget(self.stack)

        root_layout.addWidget(self.stack_card, 1)

        # 4. Compact Status Strip + Collapsible Developer Log (Collapsed by Default)
        footer_card = QFrame()
        footer_card.setObjectName("FooterCard")
        foot_lay = QHBoxLayout(footer_card)
        foot_lay.setContentsMargins(SP["lg"], SP["sm"], SP["lg"], SP["sm"])

        self.lbl_status = QLabel()
        self.lbl_status.setObjectName("StatusText")
        self.lbl_status.setProperty("tone", "neutral")
        foot_lay.addWidget(self.lbl_status, 1)
        root_layout.addWidget(footer_card)

        self.dev_log = DeveloperLogDrawer(self.theme, self.lang, self)
        root_layout.addWidget(self.dev_log)

    def _create_dpi_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP["lg"])

        top_row = QHBoxLayout()
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        self.lbl_dpi_hdr = QLabel()
        self.lbl_dpi_hdr.setObjectName("SectionTitle")
        self.lbl_dpi_desc = QLabel()
        self.lbl_dpi_desc.setObjectName("SubtitleLabel")
        self.lbl_dpi_desc.setWordWrap(True)
        hdr_col.addWidget(self.lbl_dpi_hdr)
        hdr_col.addWidget(self.lbl_dpi_desc)
        top_row.addLayout(hdr_col, 1)

        self.btn_reset_dpi = QPushButton()
        self.btn_reset_dpi.setObjectName("GhostBtn")
        self.btn_reset_dpi.clicked.connect(self.restore_default_dpis)
        top_row.addWidget(self.btn_reset_dpi)
        lay.addLayout(top_row)

        self.dpi_radio_group = QButtonGroup(self)
        self.dpi_cards: list[ClickableDpiCard] = []
        self.dpi_radios: list[QRadioButton] = []
        self.dpi_color_btns: list[QPushButton] = []
        self.dpi_value_lbls: list[QLabel] = []

        grid = QGridLayout()
        grid.setSpacing(SP["md"])
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)

        for i in range(6):
            card = ClickableDpiCard()
            card.clicked.connect(lambda idx=i: self._on_dpi_stage_selected(idx))
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
            c_lay.setSpacing(SP["sm"])

            rb = QRadioButton()
            rb.setMinimumWidth(82)
            self.dpi_radio_group.addButton(rb, i)
            rb.clicked.connect(lambda checked=False, idx=i: self._on_dpi_stage_selected(idx))
            c_lay.addWidget(rb)
            self.dpi_radios.append(rb)

            vlbl = QLabel(ltr(f"{DEFAULT_DPI_VALUES[i]} DPI"))
            vlbl.setObjectName("MonoPill")
            vlbl.setMinimumWidth(104)
            vlbl.setAlignment(Qt.AlignCenter)
            c_lay.addWidget(vlbl)
            self.dpi_value_lbls.append(vlbl)

            c_lay.addStretch()

            cbtn = QPushButton()
            cbtn.setMinimumWidth(118)
            cbtn.setFixedHeight(32)
            cbtn.setCursor(Qt.PointingHandCursor)
            cbtn.clicked.connect(lambda checked=False, idx=i: self._pick_dpi_color(idx))
            c_lay.addWidget(cbtn)
            self.dpi_color_btns.append(cbtn)

            self.dpi_cards.append(card)
            grid.addWidget(card, i // 2, i % 2)

        lay.addLayout(grid)
        lay.addStretch()
        return page

    def _create_perf_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP["lg"])

        # Polling Rate Card
        rate_card = QFrame()
        rate_card.setObjectName("SubCard")
        r_lay = QVBoxLayout(rate_card)
        r_lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        r_lay.setSpacing(SP["md"])

        t1_row = QHBoxLayout()
        self.lbl_rate_title = QLabel()
        self.lbl_rate_title.setObjectName("SectionTitle")
        t1_row.addWidget(self.lbl_rate_title)
        t1_row.addStretch()

        self.btn_reset_perf = QPushButton()
        self.btn_reset_perf.setObjectName("GhostBtn")
        self.btn_reset_perf.clicked.connect(self.restore_default_perf)
        t1_row.addWidget(self.btn_reset_perf)
        r_lay.addLayout(t1_row)

        self.lbl_rate_desc = QLabel()
        self.lbl_rate_desc.setObjectName("SubtitleLabel")
        self.lbl_rate_desc.setWordWrap(True)
        r_lay.addWidget(self.lbl_rate_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(SP["md"])
        self.rate_buttons: dict[str, QPushButton] = {}
        for rate_name in ("125 Hz", "250 Hz", "500 Hz", "1000 Hz"):
            b = QPushButton(rate_name)
            b.setObjectName("RateBtn")
            b.setProperty("active", "false")
            b.setCursor(Qt.PointingHandCursor)
            b.clicked.connect(lambda checked=False, rn=rate_name: self._on_rate_selected(rn))
            btn_row.addWidget(b, 1)
            self.rate_buttons[rate_name] = b
        r_lay.addLayout(btn_row)
        lay.addWidget(rate_card)

        # Debounce Card
        deb_card = QFrame()
        deb_card.setObjectName("SubCard")
        d_lay = QVBoxLayout(deb_card)
        d_lay.setContentsMargins(SP["lg"], SP["lg"], SP["lg"], SP["lg"])
        d_lay.setSpacing(SP["md"])

        self.lbl_deb_title = QLabel()
        self.lbl_deb_title.setObjectName("SectionTitle")
        self.lbl_deb_desc = QLabel()
        self.lbl_deb_desc.setObjectName("SubtitleLabel")
        self.lbl_deb_desc.setWordWrap(True)
        d_lay.addWidget(self.lbl_deb_title)
        d_lay.addWidget(self.lbl_deb_desc)

        sl_row = QHBoxLayout()
        sl_row.setSpacing(SP["md"])
        self.deb_slider = QSlider(Qt.Horizontal)
        self.deb_slider.setRange(1, 20)
        self.deb_slider.setValue(8)
        self.deb_slider.valueChanged.connect(self._on_debounce_changed)
        sl_row.addWidget(self.deb_slider, 1)

        self.lbl_deb_val = QLabel(ltr("8 ms"))
        self.lbl_deb_val.setObjectName("MonoPill")
        self.lbl_deb_val.setFixedWidth(84)
        self.lbl_deb_val.setAlignment(Qt.AlignCenter)
        sl_row.addWidget(self.lbl_deb_val)
        d_lay.addLayout(sl_row)
        lay.addWidget(deb_card)

        # Diagnostics / Conflict Cleanup Strip
        diag_card = QFrame()
        diag_card.setObjectName("SubCard")
        dg_lay = QHBoxLayout(diag_card)
        dg_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        self.lbl_fw_info = QLabel()
        self.lbl_fw_info.setObjectName("SubtitleLabel")
        dg_lay.addWidget(self.lbl_fw_info, 1)

        self.btn_kill_orig = QPushButton()
        self.btn_kill_orig.setObjectName("GhostBtn")
        self.btn_kill_orig.clicked.connect(self._kill_orig_manual)
        dg_lay.addWidget(self.btn_kill_orig)
        lay.addWidget(diag_card)

        lay.addStretch()
        return page

    def _create_buttons_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP["md"])

        top = QHBoxLayout()
        top.setSpacing(SP["md"])
        hdr_col = QVBoxLayout()
        hdr_col.setSpacing(2)
        self.lbl_btn_hdr = QLabel()
        self.lbl_btn_hdr.setObjectName("SectionTitle")
        self.lbl_btn_desc = QLabel()
        self.lbl_btn_desc.setObjectName("SubtitleLabel")
        self.lbl_btn_desc.setWordWrap(True)
        hdr_col.addWidget(self.lbl_btn_hdr)
        hdr_col.addWidget(self.lbl_btn_desc)
        top.addLayout(hdr_col, 1)

        # Left-Click Lock Toggle (matches official software protection)
        lock_box = QHBoxLayout()
        lock_box.setSpacing(6)
        self.lbl_lock_left = QLabel()
        self.lbl_lock_left.setObjectName("SubtitleLabel")
        lock_box.addWidget(self.lbl_lock_left)
        self.chk_lock_left = ToggleSwitch(self, self.theme)
        self.chk_lock_left.setChecked(True)
        self.chk_lock_left.toggled.connect(self._on_lock_left_toggled)
        lock_box.addWidget(self.chk_lock_left)
        top.addLayout(lock_box)

        self.btn_reset_btns = QPushButton()
        self.btn_reset_btns.setObjectName("GhostBtn")
        self.btn_reset_btns.clicked.connect(self.restore_default_buttons)
        top.addWidget(self.btn_reset_btns)
        lay.addLayout(top)

        # 2-Column Split: 7 Official Remappable Rows + Interactive Aigo GM80 Plus Visual Card
        split = QHBoxLayout()
        split.setSpacing(SP["lg"])

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.NoFrame)

        rows_host = QWidget()
        rows_lay = QVBoxLayout(rows_host)
        rows_lay.setContentsMargins(2, 0, 6, 0)
        rows_lay.setSpacing(4)

        self.btn_row_cards: list[QFrame] = []
        self.btn_row_badges: list[QLabel] = []
        self.btn_row_lbls: list[QLabel] = []
        self.btn_combos: list[QComboBox] = []

        for idx in range(len(UI_BUTTON_HW_SLOTS)):
            row = QFrame()
            row.setObjectName("SubCard")
            row.setProperty("selected", "false")
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(SP["md"], 4, SP["md"], 4)
            r_lay.setSpacing(SP["sm"])

            badge = QLabel(str(idx + 1))
            badge.setObjectName("MonoValue")
            badge.setFixedSize(24, 24)
            badge.setAlignment(Qt.AlignCenter)
            badge.setStyleSheet(
                f"border-radius: 12px; background: {self.theme['surface_elevated']}; "
                f"border: 1px solid {self.theme['border_strong']}; font-weight: 700;"
            )
            r_lay.addWidget(badge)
            self.btn_row_badges.append(badge)

            l = QLabel()
            l.setObjectName("SectionTitle")
            r_lay.addWidget(l, 1)
            self.btn_row_lbls.append(l)

            cmb = QComboBox()
            cmb.setMinimumWidth(210)
            cmb.setMaximumWidth(268)
            cmb.setFixedHeight(32)
            cmb.currentIndexChanged.connect(lambda cidx, i=idx: self._on_button_combo_changed(i, cidx))
            r_lay.addWidget(cmb)
            self.btn_combos.append(cmb)

            row.enterEvent = lambda ev, i=idx: self._on_btn_row_hover(i)
            row.leaveEvent = lambda ev: self._on_btn_row_hover(-1)
            rows_lay.addWidget(row)
            self.btn_row_cards.append(row)

        rows_lay.addStretch()
        scroll.setWidget(rows_host)
        split.addWidget(scroll, 3)

        # Interactive Aigo GM80 Plus Visual Preview Card
        viz_card = QFrame()
        viz_card.setObjectName("SubCard")
        viz_card.setMinimumWidth(272)
        viz_card.setMaximumWidth(332)
        v_lay = QVBoxLayout(viz_card)
        v_lay.setContentsMargins(SP["md"], SP["md"], SP["md"], SP["md"])
        v_lay.setSpacing(6)

        self.lbl_viz_title = QLabel()
        self.lbl_viz_title.setObjectName("SectionTitle")
        self.lbl_viz_title.setAlignment(Qt.AlignCenter)
        v_lay.addWidget(self.lbl_viz_title)

        init_led = self.driver.dpi_colors[max(0, min(5, self.driver.active_dpi_stage))]
        self.mouse_viz = GM80InteractiveMouseWidget(self.theme, dpi_led_hex=init_led, parent=viz_card)
        self.mouse_viz.button_clicked.connect(self._on_mouse_viz_clicked)
        self.mouse_viz.button_hovered.connect(self._highlight_button_row)
        v_lay.addWidget(self.mouse_viz, 1)

        self.lbl_viz_status = QLabel()
        self.lbl_viz_status.setObjectName("SubtitleLabel")
        self.lbl_viz_status.setAlignment(Qt.AlignCenter)
        self.lbl_viz_status.setWordWrap(True)
        v_lay.addWidget(self.lbl_viz_status)

        split.addWidget(viz_card, 2)
        lay.addLayout(split, 1)
        return page

    def _on_lock_left_toggled(self, locked: bool):
        self.left_btn_locked = bool(locked)
        if self.btn_combos:
            self.btn_combos[0].setEnabled(not self.left_btn_locked)

    def _on_btn_row_hover(self, idx: int):
        if hasattr(self, "mouse_viz"):
            self.mouse_viz.set_external_hover(idx)
        self._highlight_button_row(idx)

    def _highlight_button_row(self, active_idx: int):
        t = self.theme
        for i, badge in enumerate(getattr(self, "btn_row_badges", [])):
            if i == active_idx:
                badge.setStyleSheet(
                    f"border-radius: 12px; background: {t['accent']}; color: {t['accent_fg']}; "
                    f"border: 1px solid {t['accent']}; font-weight: 700;"
                )
            else:
                badge.setStyleSheet(
                    f"border-radius: 12px; background: {t['surface_elevated']}; color: {t['text_secondary']}; "
                    f"border: 1px solid {t['border_strong']}; font-weight: 700;"
                )

    def _on_mouse_viz_clicked(self, idx: int):
        self._highlight_button_row(idx)
        self._show_mouse_viz_feedback(idx)
        if 0 <= idx < len(self.btn_combos) and self.btn_combos[idx].isEnabled():
            self.btn_combos[idx].setFocus()

    def _show_mouse_viz_feedback(self, idx: int):
        if not (0 <= idx < len(UI_BUTTON_HW_SLOTS)) or not hasattr(self, "lbl_viz_status"):
            return
        hw_slot = UI_BUTTON_HW_SLOTS[idx]
        code = self.driver.button_codes[hw_slot] if hw_slot < len(self.driver.button_codes) else DEFAULT_BUTTON_CODES[hw_slot]
        p_idx = preset_index_for_hw_code(code, idx)
        action_txt = format_button_preset(p_idx, self.lang)
        self.lbl_viz_status.setText(tr("btn_viz_pressed", self.lang, n=idx + 1, name=action_txt))
        self._highlight_button_row(idx)

    def _update_mouse_viz_dpi_led(self):
        if hasattr(self, "mouse_viz"):
            st = max(0, min(5, self.driver.active_dpi_stage))
            self.mouse_viz.set_dpi_led_color(self.driver.dpi_colors[st])

    def _create_games_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(SP["md"])

        top_card = QFrame()
        top_card.setObjectName("SubCard")
        t_lay = QHBoxLayout(top_card)
        t_lay.setContentsMargins(SP["lg"], SP["md"], SP["lg"], SP["md"])
        t_lay.setSpacing(SP["sm"])

        title_col = QVBoxLayout()
        title_col.setSpacing(2)
        self.lbl_games_hdr = QLabel()
        self.lbl_games_hdr.setObjectName("SectionTitle")
        title_col.addWidget(self.lbl_games_hdr)

        self.lbl_games_live = QLabel()
        self.lbl_games_live.setObjectName("StatusText")
        self.lbl_games_live.setProperty("tone", "neutral")
        title_col.addWidget(self.lbl_games_live)
        t_lay.addLayout(title_col, 1)

        self.btn_add_game = QPushButton()
        self.btn_add_game.setObjectName("SecondaryBtn")
        self.btn_add_game.clicked.connect(self._on_add_game_browse)
        t_lay.addWidget(self.btn_add_game)

        self.btn_detect_game = QPushButton()
        self.btn_detect_game.setObjectName("GhostBtn")
        self.btn_detect_game.clicked.connect(self._on_detect_running_app)
        t_lay.addWidget(self.btn_detect_game)
        lay.addWidget(top_card)

        def_card = QFrame()
        def_card.setObjectName("SubCard")
        d_lay = QHBoxLayout(def_card)
        d_lay.setContentsMargins(SP["lg"], SP["sm"], SP["lg"], SP["sm"])
        d_lay.setSpacing(SP["sm"])

        self.lbl_def_profile = QLabel()
        self.lbl_def_profile.setObjectName("SubtitleLabel")
        d_lay.addWidget(self.lbl_def_profile)

        self.cmb_def_dpi = QComboBox()
        self.cmb_def_dpi.setMinimumWidth(180)
        self.cmb_def_dpi.currentIndexChanged.connect(self._on_default_profile_changed)
        d_lay.addWidget(self.cmb_def_dpi)

        self.cmb_def_rate = QComboBox()
        self.cmb_def_rate.setMinimumWidth(112)
        for rn in ("125 Hz", "250 Hz", "500 Hz", "1000 Hz"):
            self.cmb_def_rate.addItem(rn)
        r_idx = self.cmb_def_rate.findText(self.default_profile["polling_rate"])
        self.cmb_def_rate.setCurrentIndex(r_idx if r_idx >= 0 else 2)
        self.cmb_def_rate.currentIndexChanged.connect(self._on_default_profile_changed)
        d_lay.addWidget(self.cmb_def_rate)

        d_lay.addStretch()

        self.lbl_exit_delay = QLabel()
        self.lbl_exit_delay.setObjectName("SubtitleLabel")
        d_lay.addWidget(self.lbl_exit_delay)

        self.spn_exit_delay = StyledSpinBox(self, self.theme)
        self.spn_exit_delay.setRange(0, 300)
        self.spn_exit_delay.setSingleStep(5)
        self.spn_exit_delay.setValue(self.game_exit_delay_sec)
        self.spn_exit_delay.setMinimumWidth(116)
        self.spn_exit_delay.setMaximumWidth(148)
        self.spn_exit_delay.setMinimumHeight(36)
        self.spn_exit_delay.valueChanged.connect(self._on_exit_delay_changed)
        d_lay.addWidget(self.spn_exit_delay)
        lay.addWidget(def_card)

        self.games_scroll = QScrollArea()
        self.games_scroll.setWidgetResizable(True)
        self.games_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.games_scroll.setFrameShape(QFrame.NoFrame)

        self.games_container = QWidget()
        self.games_list_layout = QVBoxLayout(self.games_container)
        self.games_list_layout.setContentsMargins(0, 2, 4, 2)
        self.games_list_layout.setSpacing(SP["sm"])

        self.games_scroll.setWidget(self.games_container)
        lay.addWidget(self.games_scroll, 1)
        return page

    # ---------------- Game Profiles Management ----------------

    def _get_game_profile_by_id(self, profile_id: str | None) -> dict | None:
        if not profile_id:
            return None
        for p in self.game_profiles:
            if p.get("id") == profile_id:
                return p
        return None

    def _profile_pill_data(self, profile: dict) -> tuple[str, str]:
        lg = self.lang
        pid = profile.get("id")
        if not profile.get("enabled", True):
            return (tr("games_pill_paused", lg), "neutral")
        if pid == self.active_game_profile_id:
            if self.exit_countdown_sec > 0:
                return (tr("games_pill_countdown", lg, sec=self.exit_countdown_sec), "warning")
            return (tr("games_pill_active", lg), "success")
        return (tr("games_pill_ready", lg), "neutral")

    def _update_games_live_banner(self):
        if not hasattr(self, "lbl_games_live"):
            return
        lg = self.lang
        active_p = self._get_game_profile_by_id(self.active_game_profile_id)
        if active_p is not None:
            if self.exit_countdown_sec > 0:
                txt = tr("games_banner_countdown", lg, name=active_p["name"], sec=self.exit_countdown_sec)
                tone = "warning"
            else:
                dpi_txt = ltr(f"{DEFAULT_DPI_VALUES[active_p['dpi_stage']]} DPI")
                txt = tr("games_banner_active", lg, name=active_p["name"], dpi=dpi_txt, rate=ltr(active_p["polling_rate"]))
                tone = "success"
        else:
            dpi_txt = ltr(f"{DEFAULT_DPI_VALUES[self.default_profile['dpi_stage']]} DPI")
            txt = tr("games_banner_default", lg, dpi=dpi_txt, rate=ltr(self.default_profile["polling_rate"]))
            tone = "neutral"

        self.lbl_games_live.setText(txt)
        self.lbl_games_live.setProperty("tone", tone)
        self.lbl_games_live.style().unpolish(self.lbl_games_live)
        self.lbl_games_live.style().polish(self.lbl_games_live)

    def _refresh_game_card_statuses(self):
        for p in self.game_profiles:
            lbl = self._game_card_status_lbls.get(p.get("id"))
            if lbl is not None:
                txt, tone = self._profile_pill_data(p)
                lbl.setText(txt)
                lbl.setProperty("tone", tone)
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)
        self._update_games_live_banner()

    def _rebuild_game_cards(self):
        if not hasattr(self, "games_list_layout"):
            return
        self._game_card_status_lbls.clear()
        while self.games_list_layout.count():
            item = self.games_list_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

        lg, t = self.lang, self.theme
        if not self.game_profiles:
            empty_card = QFrame()
            empty_card.setObjectName("SubCard")
            e_lay = QVBoxLayout(empty_card)
            e_lay.setContentsMargins(SP["xl"], SP["xxl"], SP["xl"], SP["xxl"])
            e_lay.setSpacing(SP["sm"])

            lbl_ic = QLabel()
            lbl_ic.setAlignment(Qt.AlignCenter)
            lbl_ic.setPixmap(svg_pixmap("gamepad", t["text_muted"], 28))
            e_lay.addWidget(lbl_ic)

            lbl_e1 = QLabel(tr("games_empty_title", lg))
            lbl_e1.setObjectName("SectionTitle")
            lbl_e1.setAlignment(Qt.AlignCenter)
            lbl_e2 = QLabel(tr("games_empty_desc", lg))
            lbl_e2.setObjectName("SubtitleLabel")
            lbl_e2.setAlignment(Qt.AlignCenter)
            lbl_e2.setWordWrap(True)
            e_lay.addWidget(lbl_e1)
            e_lay.addWidget(lbl_e2)
            self.games_list_layout.addWidget(empty_card)
            self.games_list_layout.addStretch()
            return

        for prof in self.game_profiles:
            pid = prof["id"]
            is_enabled = bool(prof.get("enabled", True))
            dpi_val = DEFAULT_DPI_VALUES[max(0, min(5, int(prof.get("dpi_stage", 2))))]
            rate_str = prof.get("polling_rate", "500 Hz")

            card = QFrame()
            card.setObjectName("GameCard")
            card.setProperty("state", "active" if pid == self.active_game_profile_id else ("idle" if is_enabled else "paused"))

            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(SP["md"], SP["sm"], SP["md"], SP["sm"])
            c_lay.setSpacing(SP["md"])

            lbl_ico = QLabel()
            lbl_ico.setFixedSize(48, 48)
            lbl_ico.setAlignment(Qt.AlignCenter)
            lbl_ico.setPixmap(load_game_icon_pixmap(prof.get("icon_file", ""), t, 48))
            c_lay.addWidget(lbl_ico)

            info_col = QVBoxLayout()
            info_col.setSpacing(4)

            name_row = QHBoxLayout()
            name_row.setSpacing(SP["sm"])
            lbl_name = QLabel(prof.get("name", prof.get("exe_name", "")))
            lbl_name.setObjectName("SectionTitle" if is_enabled else "SubtitleLabel")
            name_row.addWidget(lbl_name)

            lbl_exe = QLabel(ltr(prof.get("exe_name", "")))
            lbl_exe.setObjectName("MutedLabel")
            name_row.addWidget(lbl_exe)
            name_row.addStretch()
            info_col.addLayout(name_row)

            badges_row = QHBoxLayout()
            badges_row.setSpacing(6)

            lbl_dpi_b = QLabel(ltr(f"{dpi_val} DPI"))
            lbl_dpi_b.setObjectName("Badge")
            lbl_dpi_b.setProperty("tone", "accent")
            lbl_dpi_b.setProperty("mono", "true")
            badges_row.addWidget(lbl_dpi_b)

            lbl_rate_b = QLabel(ltr(rate_str))
            lbl_rate_b.setObjectName("Badge")
            lbl_rate_b.setProperty("tone", "neutral")
            lbl_rate_b.setProperty("mono", "true")
            badges_row.addWidget(lbl_rate_b)

            st_txt, st_tone = self._profile_pill_data(prof)
            lbl_st = QLabel(st_txt)
            lbl_st.setObjectName("Badge")
            lbl_st.setProperty("tone", st_tone)
            self._game_card_status_lbls[pid] = lbl_st
            badges_row.addWidget(lbl_st)
            badges_row.addStretch()

            info_col.addLayout(badges_row)
            c_lay.addLayout(info_col, 1)

            btn_toggle = QPushButton(tr("games_pause" if is_enabled else "games_resume", lg))
            btn_toggle.setObjectName("GhostBtn")
            btn_toggle.setIcon(svg_icon("pause" if is_enabled else "play", t["text_secondary"], 13))
            btn_toggle.clicked.connect(lambda checked=False, p_id=pid: self._toggle_game_profile(p_id))
            c_lay.addWidget(btn_toggle)

            btn_edit = QPushButton(tr("games_edit", lg))
            btn_edit.setObjectName("GhostBtn")
            btn_edit.setIcon(svg_icon("edit", t["text_secondary"], 13))
            btn_edit.clicked.connect(lambda checked=False, p_id=pid: self._edit_game_profile(p_id))
            c_lay.addWidget(btn_edit)

            btn_del = QPushButton()
            btn_del.setObjectName("DangerBtn")
            btn_del.setIcon(svg_icon("trash", t["danger"], 14))
            btn_del.setToolTip(tr("games_delete_tip", lg))
            btn_del.clicked.connect(lambda checked=False, p_id=pid: self._delete_game_profile(p_id))
            c_lay.addWidget(btn_del)

            self.games_list_layout.addWidget(card)

        self.games_list_layout.addStretch()

    def _on_add_game_browse(self):
        src, _ = QFileDialog.getOpenFileName(
            self, tr("dlg_gp_exe", self.lang), "", "Executables (*.exe)"
        )
        if not src:
            return
        stem = os.path.splitext(os.path.basename(src))[0]
        dlg = GameProfileEditorDialog(self, profile=None, initial_exe_path=src, initial_name=stem)
        if dlg.exec() == QDialog.Accepted and dlg.result_profile:
            self._upsert_game_profile(dlg.result_profile)
        dlg.deleteLater()

    def _on_detect_running_app(self):
        picker = RunningAppsDialog(self)
        ok = (picker.exec() == QDialog.Accepted and picker.selected_app is not None)
        app_info = picker.selected_app
        picker.deleteLater()
        if not ok:
            return
        exe_path = app_info.get("exe_path", "")
        title = app_info.get("title", "")
        clean_name = title.split(" - ")[0].strip() if title else os.path.splitext(app_info.get("exe_name", ""))[0]
        dlg = GameProfileEditorDialog(self, profile=None, initial_exe_path=exe_path, initial_name=clean_name)
        if dlg.exec() == QDialog.Accepted and dlg.result_profile:
            self._upsert_game_profile(dlg.result_profile)
        dlg.deleteLater()

    def _upsert_game_profile(self, new_prof: dict):
        replaced = False
        for idx, existing in enumerate(self.game_profiles):
            if existing["id"] == new_prof["id"] or existing["exe_name"].lower() == new_prof["exe_name"].lower():
                new_prof["id"] = existing["id"]
                self.game_profiles[idx] = new_prof
                replaced = True
                break
        if not replaced:
            self.game_profiles.append(new_prof)

        self._save_current_settings()
        self._rebuild_game_cards()
        self._update_games_live_banner()
        msg = tr("games_saved_toast", self.lang, name=new_prof["name"])
        self._set_status(msg, "success")
        self.toast.show_toast(msg, "success", self.theme)

    def _edit_game_profile(self, profile_id: str):
        prof = self._get_game_profile_by_id(profile_id)
        if not prof:
            return
        dlg = GameProfileEditorDialog(self, profile=prof)
        if dlg.exec() == QDialog.Accepted and dlg.result_profile:
            for idx, p in enumerate(self.game_profiles):
                if p["id"] == profile_id:
                    self.game_profiles[idx] = dlg.result_profile
                    break
            self._save_current_settings()
            self._rebuild_game_cards()
            self._update_games_live_banner()
            if self.active_game_profile_id == profile_id:
                updated = dlg.result_profile
                if not updated.get("enabled", True):
                    self._revert_to_default_profile_now()
                else:
                    self._apply_game_or_default_async(
                        updated["dpi_stage"], updated["polling_rate"],
                        profile_name=updated["name"], is_default=False, force=True,
                    )
        dlg.deleteLater()

    def _toggle_game_profile(self, profile_id: str):
        prof = self._get_game_profile_by_id(profile_id)
        if not prof:
            return
        prof["enabled"] = not bool(prof.get("enabled", True))
        self._save_current_settings()
        if not prof["enabled"] and self.active_game_profile_id == profile_id:
            self._revert_to_default_profile_now()
        else:
            self._rebuild_game_cards()
            self._update_games_live_banner()

    def _delete_game_profile(self, profile_id: str):
        prof = self._get_game_profile_by_id(profile_id)
        if not prof:
            return
        ans = QMessageBox.question(
            self,
            tr("games_delete_title", self.lang),
            tr("games_delete_body", self.lang, name=prof["name"], exe=ltr(prof["exe_name"])),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans != QMessageBox.Yes:
            return

        icon_f = prof.get("icon_file", "")
        if icon_f:
            try:
                p_ico = os.path.join(get_game_icons_dir(), icon_f)
                if os.path.exists(p_ico):
                    os.remove(p_ico)
            except Exception as ex:
                APP_LOG.warn(f"Failed to delete game icon {icon_f}: {ex}")

        self.game_profiles = [p for p in self.game_profiles if p["id"] != profile_id]
        self._save_current_settings()
        if self.active_game_profile_id == profile_id:
            self._revert_to_default_profile_now()
        else:
            self._rebuild_game_cards()
            self._update_games_live_banner()

    def _on_default_profile_changed(self):
        self.default_profile["dpi_stage"] = max(0, min(5, self.cmb_def_dpi.currentIndex()))
        self.default_profile["polling_rate"] = self.cmb_def_rate.currentText()
        self._save_current_settings()
        self._update_games_live_banner()

    def _on_exit_delay_changed(self, val: int):
        self.game_exit_delay_sec = max(0, min(300, int(val)))
        self._save_current_settings()

    def _poll_foreground_game(self):
        if not self.game_profiles and self.active_game_profile_id is None:
            return
        if not any(p.get("enabled", True) for p in self.game_profiles) and self.active_game_profile_id is None:
            return

        exe_name, _ = get_foreground_exe_info()
        matched = None
        if exe_name:
            for p in self.game_profiles:
                if p.get("enabled", True) and p.get("exe_name", "").lower() == exe_name:
                    matched = p
                    break

        if matched is not None:
            pid = matched["id"]
            if self.active_game_profile_id == pid:
                if self.exit_countdown_sec > 0 or self.game_countdown_timer.isActive():
                    self.game_countdown_timer.stop()
                    self.exit_countdown_sec = 0
                    self._refresh_game_card_statuses()
                return

            self.game_countdown_timer.stop()
            self.exit_countdown_sec = 0
            self.active_game_profile_id = pid
            self._rebuild_game_cards()
            self._update_games_live_banner()
            self._apply_game_or_default_async(
                matched["dpi_stage"], matched["polling_rate"],
                profile_name=matched["name"], is_default=False,
            )
            return

        if self.active_game_profile_id is not None:
            active_p = self._get_game_profile_by_id(self.active_game_profile_id)
            if active_p is None or not active_p.get("enabled", True) or self.game_exit_delay_sec <= 0:
                self._revert_to_default_profile_now()
            elif not self.game_countdown_timer.isActive():
                self.exit_countdown_sec = self.game_exit_delay_sec
                self.game_countdown_timer.start(1000)
                self._refresh_game_card_statuses()

    def _tick_game_exit_countdown(self):
        if self.active_game_profile_id is None:
            self.game_countdown_timer.stop()
            self.exit_countdown_sec = 0
            return
        self.exit_countdown_sec -= 1
        if self.exit_countdown_sec <= 0:
            self._revert_to_default_profile_now()
        else:
            self._refresh_game_card_statuses()

    def _revert_to_default_profile_now(self):
        self.game_countdown_timer.stop()
        self.exit_countdown_sec = 0
        self.active_game_profile_id = None
        self._rebuild_game_cards()
        self._update_games_live_banner()
        self._apply_game_or_default_async(
            self.default_profile["dpi_stage"],
            self.default_profile["polling_rate"],
            profile_name="",
            is_default=True,
        )

    def _apply_game_or_default_async(
        self,
        dpi_stage: int,
        polling_rate: str,
        profile_name: str = "",
        is_default: bool = False,
        force: bool = False,
    ):
        target_tuple = (int(dpi_stage), str(polling_rate))
        if not force and self._last_applied_hw_tuple == target_tuple:
            return
        if self._game_hw_busy:
            return
        self._game_hw_busy = True
        lang_snap = self.lang
        threading.Thread(
            target=self._game_profile_hw_worker,
            args=(int(dpi_stage), str(polling_rate), profile_name, is_default, lang_snap),
            daemon=True,
        ).start()

    def _game_profile_hw_worker(self, dpi_stage: int, polling_rate: str, profile_name: str, is_default: bool, lang_snap: str):
        ok, msg = self.driver.apply_profile_to_hardware(dpi_stage, polling_rate, profile_name=profile_name)
        dpi_txt = ltr(f"{DEFAULT_DPI_VALUES[max(0, min(5, dpi_stage))]} DPI")
        if ok:
            if is_default:
                t_title = tr("gp_default_title", lang_snap)
                t_body = tr("gp_default_body", lang_snap, dpi=dpi_txt, rate=ltr(polling_rate))
            else:
                t_title = tr("gp_toast_title", lang_snap, name=profile_name)
                t_body = tr("gp_toast_body", lang_snap, name=profile_name, dpi=dpi_txt, rate=ltr(polling_rate))
            self.signals.game_profile_done.emit(True, msg, t_title, t_body, True)
        else:
            self.signals.game_profile_done.emit(False, msg, "", "", False)

    def _on_game_profile_done(self, ok: bool, msg: str, toast_title: str, toast_body: str, show_toast: bool):
        self._game_hw_busy = False
        APP_LOG.hid(msg)
        if ok:
            self._last_applied_hw_tuple = (self.driver.active_dpi_stage, self.driver.polling_rate)
        self._sync_ui_from_driver()
        self._refresh_tray()
        self._refresh_game_card_statuses()

        short_msg = toast_body if (ok and toast_body) else tr("toast_hw_err", self.lang)
        tone = "success" if ok else "warning"
        self._set_status(short_msg, tone)
        if ok and toast_body:
            self.toast.show_toast(toast_body, "success", self.theme)
        if show_toast and toast_title:
            try:
                self.tray.showMessage(toast_title, toast_body, QSystemTrayIcon.Information, 3500)
            except Exception as ex:
                APP_LOG.warn(f"Tray toast warning: {ex}")

    # ---------------- Language Switch (AR RTL / EN LTR) & Battery Interval ----------------

    def get_battery_interval_index(self) -> int:
        return next((i for i, opt in enumerate(BAT_POLL_OPTIONS) if opt[0] == self.bat_poll_seconds), 4)

    def _current_interval_label(self) -> str:
        idx = self.get_battery_interval_index()
        if 0 <= idx < len(BAT_POLL_OPTIONS):
            return BAT_POLL_OPTIONS[idx][2 if self.lang == "en" else 1]
        return "Every 3 min" if self.lang == "en" else "كل 3 دقائق"

    def _on_bat_interval_changed(self, idx: int):
        if not (0 <= idx < len(BAT_POLL_OPTIONS)):
            return
        secs = BAT_POLL_OPTIONS[idx][0]
        self.bat_poll_seconds = secs
        self._save_current_settings()
        if secs == 0:
            self.battery_timer.stop()
        else:
            self.battery_timer.start(secs * 1000)
        self._update_battery_header()
        lbl = self._current_interval_label()
        msg = tr("status_bat_manual", self.lang) if secs == 0 else tr("status_bat_interval", self.lang, label=lbl)
        self._set_status(msg, "accent")

    def _apply_language(self):
        lg = self.lang
        self.setWindowTitle(tr("win_title", lg))
        self.lbl_title.setText(tr("product_title", lg))
        self.lbl_sub.setText(tr("product_sub", lg))
        self.btn_settings.setText(tr("btn_settings", lg))
        self.btn_refresh_bat.setText("")
        self.btn_refresh_bat.setToolTip(tr("btn_refresh", lg))
        self.btn_read_hw.setText(tr("btn_read_hw", lg))
        if self.btn_save_hw.isEnabled():
            self.btn_save_hw.setText(tr("btn_save_hw", lg))

        tab_keys = ("tab_dpi", "tab_perf", "tab_buttons", "tab_games")
        for b, k in zip(self.tab_buttons, tab_keys, strict=True):
            b.setText(tr(k, lg))

        # DPI Tab
        self.lbl_dpi_hdr.setText(tr("dpi_section_title", lg))
        self.lbl_dpi_desc.setText(tr("dpi_section_desc", lg))
        self.btn_reset_dpi.setText(tr("dpi_restore_btn", lg))
        for i in range(6):
            self.dpi_radios[i].setText(tr("dpi_stage_n", lg, n=i + 1))
            self.dpi_color_btns[i].setText(format_dpi_color_label(self.driver.dpi_colors[i], i, lg))

        # Performance Tab
        self.lbl_rate_title.setText(tr("rate_title", lg))
        self.lbl_rate_desc.setText(tr("rate_desc", lg))
        self.btn_reset_perf.setText(tr("perf_restore_btn", lg))
        self.lbl_deb_title.setText(tr("deb_title", lg))
        self.lbl_deb_desc.setText(tr("deb_desc", lg))
        self.btn_kill_orig.setText(tr("btn_kill_orig", lg))

        # Buttons Tab (7 official remappable inputs + interactive GM80 Plus preview)
        self.lbl_btn_hdr.setText(tr("btn_section_title", lg))
        self.lbl_btn_desc.setText(tr("btn_section_desc", lg))
        self.btn_reset_btns.setText(tr("btn_restore_defaults", lg))
        self.lbl_lock_left.setText(tr("btn_lock_left", lg))
        self.lbl_viz_title.setText(tr("btn_viz_title", lg))
        self.lbl_viz_status.setText(tr("btn_viz_hint", lg))
        preset_items = [format_button_preset(i, lg) for i in range(len(BUTTON_PRESETS))]
        for idx, hw_slot in enumerate(UI_BUTTON_HW_SLOTS):
            self.btn_row_lbls[idx].setText(tr(f"btn_{idx + 1}", lg))
            cmb = self.btn_combos[idx]
            code = self.driver.button_codes[hw_slot] if hw_slot < len(self.driver.button_codes) else DEFAULT_BUTTON_CODES[hw_slot]
            cur_idx = preset_index_for_hw_code(code, idx)
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItems(preset_items)
            cmb.setCurrentIndex(cur_idx)
            cmb.blockSignals(False)
        if self.btn_combos:
            self.btn_combos[0].setEnabled(not getattr(self, "left_btn_locked", True))
        self._highlight_button_row(-1)

        # Games Tab
        self.lbl_games_hdr.setText(tr("games_title", lg))
        self.btn_add_game.setText(tr("games_add", lg))
        self.btn_detect_game.setText(tr("games_detect", lg))
        self.lbl_def_profile.setText(tr("games_default_lbl", lg))
        self.lbl_exit_delay.setText(tr("games_delay_lbl", lg))
        self.spn_exit_delay.setSuffix(tr("games_delay_suffix", lg))

        cur_def_dpi = self.default_profile["dpi_stage"]
        self.cmb_def_dpi.blockSignals(True)
        self.cmb_def_dpi.clear()
        for idx, val in enumerate(DEFAULT_DPI_VALUES):
            self.cmb_def_dpi.addItem(f"{tr('dpi_stage_n', lg, n=idx + 1)} — {ltr(f'{val} DPI')}", idx)
        self.cmb_def_dpi.setCurrentIndex(max(0, min(5, cur_def_dpi)))
        self.cmb_def_dpi.blockSignals(False)

        self._rebuild_game_cards()
        self._update_games_live_banner()
        self.dev_log.refresh_theme_and_lang(self.theme, lg)

        # Tray & Firmware
        self.act_open.setText(tr("tray_open", lg))
        self.act_poll.setText(tr("tray_poll", lg))
        self.act_quit.setText(tr("tray_quit", lg))

        fw_txt = ltr(self.driver.firmware_info) if self.driver.firmware_info else tr("fw_unread", lg)
        sn_txt = ltr(self.driver.serial_number or "N/A")
        self.lbl_fw_info.setText(tr("fw_line", lg, fw=fw_txt, sn=sn_txt))
        self._update_battery_header()
        self._refresh_tray()
        self._set_status(tr("status_ready", lg), "neutral")

    # ---------------- UI State Sync & Event Handlers ----------------

    def switch_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.tab_buttons):
            b.setProperty("active", "true" if i == idx else "false")
            b.style().unpolish(b)
            b.style().polish(b)
        self._refresh_tab_icons()
        if hasattr(self, "mouse_viz"):
            self.mouse_viz.set_animations_paused(idx != 2 or not self.isVisible())

    def _style_dpi_color_btn(self, idx: int):
        """Hardware DPI LED color swatch button (independent from UI accent color)."""
        hx = self.driver.dpi_colors[idx].upper()
        fg = pick_readable_fg(hx)
        self.dpi_color_btns[idx].setText(format_dpi_color_label(hx, idx, self.lang))
        self.dpi_color_btns[idx].setStyleSheet(
            f"QPushButton {{ background-color: {hx}; color: {fg}; "
            f"border: 1px solid {self.theme['border_strong']}; border-radius: {RAD['md']}px; "
            f"font-weight: 700; font-size: {FONT['sm']}px; padding: 0 10px; }}"
        )

    def _sync_ui_from_driver(self):
        lg = self.lang
        active_st = max(0, min(5, self.driver.active_dpi_stage))
        self.dpi_radios[active_st].setChecked(True)
        for i in range(6):
            self.dpi_cards[i].set_selected(i == active_st)
            self.dpi_value_lbls[i].setText(ltr(f"{self.driver.dpi_values[i]} DPI"))
            self._style_dpi_color_btn(i)

        for rn, b in self.rate_buttons.items():
            b.setProperty("active", "true" if rn == self.driver.polling_rate else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        self.deb_slider.blockSignals(True)
        self.deb_slider.setValue(self.driver.debounce_ms)
        self.deb_slider.blockSignals(False)
        self.lbl_deb_val.setText(ltr(f"{self.driver.debounce_ms} ms"))

        for i, hw_slot in enumerate(UI_BUTTON_HW_SLOTS):
            code = self.driver.button_codes[hw_slot] if hw_slot < len(self.driver.button_codes) else DEFAULT_BUTTON_CODES[hw_slot]
            pos = preset_index_for_hw_code(code, i)
            self.btn_combos[i].blockSignals(True)
            if 0 <= pos < self.btn_combos[i].count():
                self.btn_combos[i].setCurrentIndex(pos)
            self.btn_combos[i].blockSignals(False)
        self._update_mouse_viz_dpi_led()

        fw_txt = ltr(self.driver.firmware_info) if self.driver.firmware_info else tr("fw_unread", lg)
        sn_txt = ltr(self.driver.serial_number or "N/A")
        self.lbl_fw_info.setText(tr("fw_line", lg, fw=fw_txt, sn=sn_txt))
        self._update_battery_header()

    def _on_dpi_stage_selected(self, idx: int):
        with self.driver.lock:
            self.driver.active_dpi_stage = idx
            dpi_val = self.driver.dpi_values[idx]
        self.dpi_radios[idx].setChecked(True)
        for i, card in enumerate(self.dpi_cards):
            card.set_selected(i == idx)
        self._update_mouse_viz_dpi_led()
        self._set_status(
            tr("dpi_selected_status", self.lang, n=idx + 1, dpi=ltr(f"{dpi_val} DPI")),
            "accent",
        )

    def _pick_dpi_color(self, idx: int):
        col = QColorDialog.getColor(
            QColor(self.driver.dpi_colors[idx]),
            self,
            tr("dpi_pick_title", self.lang, n=idx + 1),
        )
        if col.isValid():
            with self.driver.lock:
                self.driver.dpi_colors[idx] = col.name().upper()
            self._style_dpi_color_btn(idx)
            self._update_mouse_viz_dpi_led()

    def restore_default_dpis(self):
        with self.driver.lock:
            self.driver.dpi_values = list(DEFAULT_DPI_VALUES)
            self.driver.dpi_colors = list(DEFAULT_DPI_COLORS)
            self.driver.active_dpi_stage = 2
        self._sync_ui_from_driver()
        self.trigger_apply_to_hardware()

    def restore_default_perf(self):
        with self.driver.lock:
            self.driver.polling_rate = "500 Hz"
            self.driver.debounce_ms = 8
        self._sync_ui_from_driver()
        self.trigger_apply_to_hardware()

    def _on_rate_selected(self, rate_name: str):
        with self.driver.lock:
            self.driver.polling_rate = rate_name
        for rn, b in self.rate_buttons.items():
            b.setProperty("active", "true" if rn == rate_name else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        if self.driver.is_bluetooth and not self.driver.wired_path and not self.driver.wireless_path:
            msg = tr("toast_bt_readonly", self.lang)
            self._set_status(msg, "warning")
            self.toast.show_toast(msg, "warning", self.theme)
            return

        if self._hw_apply_busy:
            return
        self._hw_apply_busy = True
        self._set_status(tr("status_applying_rate", self.lang, rate=ltr(rate_name)), "accent")
        threading.Thread(target=self._apply_rate_worker, daemon=True).start()

    def _apply_rate_worker(self):
        ok, msg = self.driver.apply_polling_rate_to_hardware()
        self.signals.apply_done.emit(ok, msg)

    def _on_debounce_changed(self, val: int):
        with self.driver.lock:
            self.driver.debounce_ms = val
        self.lbl_deb_val.setText(ltr(f"{val} ms"))

    def _on_button_combo_changed(self, idx: int, combo_idx: int):
        if not (0 <= idx < len(UI_BUTTON_HW_SLOTS)) or not (0 <= combo_idx < len(BUTTON_PRESETS)):
            return
        if idx == 0 and combo_idx != 0:
            ans = QMessageBox.question(
                self,
                tr("left_click_warn_title", self.lang),
                tr("left_click_warn_body", self.lang),
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                self.btn_combos[0].blockSignals(True)
                self.btn_combos[0].setCurrentIndex(0)
                self.btn_combos[0].blockSignals(False)
                return
        hw_slot = UI_BUTTON_HW_SLOTS[idx]
        code = (
            DISABLED_CODE_BY_HW_SLOT.get(hw_slot, (0x00, 0x00, 0x00, 0x00))
            if combo_idx == BUTTON_DISABLED_INDEX
            else BUTTON_PRESETS[combo_idx][1]
        )
        with self.driver.lock:
            while len(self.driver.button_codes) < 8:
                self.driver.button_codes.append(DEFAULT_BUTTON_CODES[len(self.driver.button_codes)])
            self.driver.button_codes[hw_slot] = code
        if hasattr(self, "mouse_viz"):
            self.mouse_viz.trigger_press(idx, hold=False)
            self._show_mouse_viz_feedback(idx)

    def restore_default_buttons(self):
        if self._hw_apply_busy:
            return
        self._hw_apply_busy = True
        with self.driver.lock:
            self.driver.button_codes = list(DEFAULT_BUTTON_CODES)
        self._sync_ui_from_driver()
        self.btn_save_hw.setEnabled(False)
        self.btn_save_hw.setText(tr("btn_restoring_btns", self.lang))
        threading.Thread(target=self._reset_buttons_worker, daemon=True).start()

    def _reset_buttons_worker(self):
        ok, msg = self.driver.reset_factory_buttons_on_hardware()
        self.signals.apply_done.emit(ok, msg)

    # ---------------- Hardware & Process Async Operations (Single-Flight Guarded) ----------------

    def _check_driver_conflict(self):
        if self._conflict_busy:
            return
        self._conflict_busy = True
        threading.Thread(target=self._conflict_scan_worker, daemon=True).start()

    def _conflict_scan_worker(self):
        try:
            procs = detect_conflicting_processes()
            if procs:
                self.signals.conflict_found.emit(procs)
        finally:
            self._conflict_busy = False

    def _on_conflict_found(self, procs: list):
        ans = QMessageBox.question(
            self,
            tr("conflict_title", self.lang),
            tr("conflict_body", self.lang, procs=ltr(", ".join(procs))),
            QMessageBox.Yes | QMessageBox.No,
        )
        if ans == QMessageBox.Yes:
            threading.Thread(target=self._conflict_close_worker, daemon=True).start()

    def _kill_orig_manual(self):
        threading.Thread(target=self._conflict_close_worker, daemon=True).start()

    def _conflict_close_worker(self):
        close_conflicting_processes()
        self.signals.conflict_closed.emit()

    def _on_conflict_closed(self):
        msg = tr("status_orig_closed", self.lang)
        self._set_status(msg, "accent")
        self.toast.show_toast(msg, "accent", self.theme)

    def _trigger_initial_hw_read(self):
        if self._hw_read_busy:
            return
        self._hw_read_busy = True
        self._set_status(tr("status_reading", self.lang), "accent")
        threading.Thread(target=self._init_read_worker, daemon=True).start()

    def _init_read_worker(self):
        ok, msg = self.driver.read_hardware_state()
        self.signals.init_read_done.emit(ok, msg)

    def _on_init_read_done(self, ok: bool, msg: str):
        self._hw_read_busy = False
        if self._closing:
            return
        APP_LOG.hid(msg)
        self._sync_ui_from_driver()
        if ok:
            self._last_applied_hw_tuple = (self.driver.active_dpi_stage, self.driver.polling_rate)
            short = tr("toast_read_ok", self.lang)
            self._set_status(short, "success")
            self.toast.show_toast(short, "success", self.theme)
        else:
            short = tr("toast_hw_err", self.lang)
            self._set_status(short, "warning")
        self._refresh_tray()

    def trigger_battery_poll(self, manual: bool = False):
        if self._poll_busy:
            return
        self._poll_busy = True
        if manual:
            self._manual_poll_pending = True
            self.btn_refresh_bat.setEnabled(False)
            self._set_status(tr("status_polling_bat", self.lang), "accent")
        threading.Thread(target=self._poll_worker, daemon=True).start()

    def _poll_worker(self):
        ok, msg = self.driver.poll_battery_status()
        self.signals.poll_done.emit(ok, msg)

    def _on_poll_done(self, ok: bool, msg: str):
        self._poll_busy = False
        if self._closing:
            return
        APP_LOG.hid(msg)
        self.btn_refresh_bat.setEnabled(True)
        self._update_battery_header()
        self._refresh_tray()

        if self._manual_poll_pending:
            self._manual_poll_pending = False
            if self.driver.battery_percent is not None:
                short = tr("toast_bat_ok", self.lang, pct=self.driver.battery_percent)
                self._set_status(short, "success")
                self.toast.show_toast(short, "success", self.theme)
            elif self.driver.battery_sleeping:
                short = tr("toast_bat_sleep", self.lang)
                self._set_status(short, "warning")
                self.toast.show_toast(short, "warning", self.theme)
            elif self.driver.is_wired:
                short = tr("toast_bat_charging", self.lang)
                self._set_status(short, "accent")
                self.toast.show_toast(short, "accent", self.theme)
            else:
                self._set_status(tr("toast_hw_err", self.lang), "warning")

        if (
            self.driver.battery_percent is not None
            and self.driver.battery_percent < 20
            and not self.driver.is_wired
            and not self.driver.low_battery_warned
        ):
            self.driver.low_battery_warned = True
            self.tray.showMessage(
                tr("low_bat_title", self.lang),
                tr("low_bat_body", self.lang, pct=self.driver.battery_percent),
                QSystemTrayIcon.Warning,
                5000,
            )

    def _set_prop(self, widget: QWidget, name: str, val: str):
        widget.setProperty(name, val)
        widget.style().unpolish(widget)
        widget.style().polish(widget)

    def _update_battery_header(self):
        lg = self.lang
        if not self.driver.connected:
            dot_tone, conn_txt = "danger", tr("conn_off", lg)
        elif self.driver.is_bluetooth:
            dot_tone, conn_txt = "accent", tr("conn_bt", lg)
        elif self.driver.is_wired and self.driver.is_wireless:
            dot_tone, conn_txt = "accent", tr("conn_wired_24g", lg)
        elif self.driver.is_wired:
            dot_tone, conn_txt = "accent", tr("conn_wired", lg)
        else:
            dot_tone, conn_txt = "success", tr("conn_24g", lg)

        self._set_prop(self.lbl_conn_dot, "tone", dot_tone)
        self.lbl_conn.setText(conn_txt)

        if not self.driver.connected:
            self.bat_indicator.set_state(False, None, charging=False, sleeping=False)
            self.lbl_bat_badge.setText(tr("bat_offline", lg))
            self._set_prop(self.lbl_bat_badge, "tone", "neutral")
        elif self.driver.battery_percent is not None:
            pct = max(0, min(100, int(self.driver.battery_percent)))
            is_chg = bool(self.driver.battery_charging)
            self.bat_indicator.set_state(True, pct, charging=is_chg, sleeping=False)
            if is_chg:
                tone, badge_txt = "success", tr("bat_charging", lg)
            elif pct >= 40:
                tone, badge_txt = "success", tr("bat_discharging", lg)
            elif pct >= 15:
                tone, badge_txt = "warning", tr("bat_discharging", lg)
            else:
                tone, badge_txt = "danger", tr("bat_low", lg)
            self.lbl_bat_badge.setText(badge_txt)
            self._set_prop(self.lbl_bat_badge, "tone", tone)
        elif self.driver.battery_sleeping:
            self.bat_indicator.set_state(True, None, charging=False, sleeping=True)
            self.lbl_bat_badge.setText(tr("bat_sleep", lg))
            self._set_prop(self.lbl_bat_badge, "tone", "warning")
        elif self.driver.is_wired:
            self.bat_indicator.set_state(True, None, charging=True, sleeping=False)
            self.lbl_bat_badge.setText(tr("bat_charging", lg))
            self._set_prop(self.lbl_bat_badge, "tone", "success")
        else:
            self.bat_indicator.set_state(True, None, charging=False, sleeping=False)
            self.lbl_bat_badge.setText(tr("bat_waiting", lg))
            self._set_prop(self.lbl_bat_badge, "tone", "neutral")

        last_str = ltr(self.driver.last_poll_str or "--:--:--")
        self.lbl_poll_time.setText(last_str)
        updated_tip = tr("bat_last_updated", lg, time=last_str)
        self.lbl_poll_time.setToolTip(updated_tip)
        self.btn_refresh_bat.setToolTip(f"{tr('btn_refresh', lg)} — {updated_tip}")

    def trigger_apply_to_hardware(self):
        if self._hw_apply_busy:
            return
        if self.driver.is_bluetooth and not self.driver.wired_path and not self.driver.wireless_path:
            msg = tr("toast_bt_readonly", self.lang)
            self._set_status(msg, "warning")
            self.toast.show_toast(msg, "warning", self.theme)
            return
        self._hw_apply_busy = True
        self.btn_save_hw.setEnabled(False)
        self.btn_save_hw.setText(tr("btn_saving_hw", self.lang))
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self):
        ok, msg = self.driver.apply_to_hardware(apply_buttons=True)
        self.signals.apply_done.emit(ok, msg)

    def _on_apply_done(self, ok: bool, msg: str):
        self._hw_apply_busy = False
        if self._closing:
            return
        APP_LOG.hid(msg)
        self.btn_save_hw.setEnabled(True)
        self.btn_save_hw.setText(tr("btn_save_hw", self.lang))
        if ok:
            self._last_applied_hw_tuple = (self.driver.active_dpi_stage, self.driver.polling_rate)
            short = tr("toast_saved", self.lang)
            self._set_status(short, "success")
            self.toast.show_toast(short, "success", self.theme)
        else:
            short = tr("toast_hw_err", self.lang)
            self._set_status(short, "danger")
            self.toast.show_toast(short, "danger", self.theme)
        self._update_battery_header()
        self._refresh_tray()

    # ---------------- System Tray Integration ----------------

    def _setup_tray(self):
        ico_p = get_active_icon_path(self.settings.get("custom_icon", ""))
        self.tray = QSystemTrayIcon(
            build_tray_qicon(self.driver, ico_p, self.theme, self.battery_style, self.battery_tray_style),
            self,
        )
        menu = QMenu(self)
        self.act_open = QAction(tr("tray_open", self.lang), self)
        self.act_open.triggered.connect(self.restore_from_tray)
        self.act_poll = QAction(tr("tray_poll", self.lang), self)
        self.act_poll.triggered.connect(lambda: self.trigger_battery_poll(manual=True))
        self.act_quit = QAction(tr("tray_quit", self.lang), self)
        self.act_quit.triggered.connect(self.quit_app)

        menu.addAction(self.act_open)
        menu.addAction(self.act_poll)
        menu.addSeparator()
        menu.addAction(self.act_quit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()
        self._refresh_tray()

    def _refresh_tray(self):
        if self._closing or not hasattr(self, "tray"):
            return
        en = (self.lang == "en")
        ico_p = get_active_icon_path(self.settings.get("custom_icon", ""))
        self.tray.setIcon(
            build_tray_qicon(self.driver, ico_p, self.theme, self.battery_style, self.battery_tray_style)
        )
        if not self.driver.connected:
            tip = "Aigo GM80 Plus — Disconnected" if en else "Aigo GM80 Plus — غير متصل"
        elif self.driver.battery_percent is not None:
            volt = f" ({self.driver.battery_voltage:.2f}V)" if self.driver.battery_voltage is not None else ""
            bat_lbl = "Battery" if en else "الشحن"
            tip = f"Aigo GM80 Plus — {bat_lbl}: {self.driver.battery_percent}%{volt} | {self.driver.dpi_values[self.driver.active_dpi_stage]} DPI @ {self.driver.polling_rate}"
        else:
            mode = "USB Wired" if self.driver.is_wired else ("Bluetooth" if self.driver.is_bluetooth else "2.4G Wireless")
            tip = f"Aigo GM80 Plus ({mode}) | {self.driver.dpi_values[self.driver.active_dpi_stage]} DPI @ {self.driver.polling_rate}"
        self.tray.setToolTip(tip)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore_from_tray()

    def _set_visual_animations_paused(self, paused: bool):
        if hasattr(self, "wp_background"):
            self.wp_background.set_paused_for_visibility(paused)
        if hasattr(self, "bat_indicator"):
            self.bat_indicator.set_animations_paused(paused)
        if hasattr(self, "mouse_viz"):
            in_btn_tab = hasattr(self, "stack") and self.stack.currentIndex() == 2
            self.mouse_viz.set_animations_paused(paused or not in_btn_tab)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange:
            self._set_visual_animations_paused(bool(self.windowState() & Qt.WindowMinimized))

    def hideEvent(self, event):
        super().hideEvent(event)
        self._set_visual_animations_paused(True)

    def showEvent(self, event):
        super().showEvent(event)
        self._set_visual_animations_paused(bool(self.windowState() & Qt.WindowMinimized))

    def hide_to_tray(self):
        self.hide()
        self._set_visual_animations_paused(True)
        self.tray.showMessage(
            "Aigo GM80 Plus Control",
            tr("tray_hidden_body", self.lang, interval=self._current_interval_label()),
            QSystemTrayIcon.Information,
            2500,
        )

    def restore_from_tray(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._set_visual_animations_paused(False)
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception as ex:
            APP_LOG.warn(f"SetForegroundWindow skipped: {ex}")

    def closeEvent(self, event):
        if self.run_in_background:
            event.ignore()
            self.hide_to_tray()
        else:
            event.accept()
            self.quit_app()

    def quit_app(self):
        self._closing = True
        self._set_visual_animations_paused(True)
        if getattr(self, "_app_filter_installed", False):
            app_inst = QApplication.instance()
            if app_inst is not None:
                app_inst.removeEventFilter(self)
            self._app_filter_installed = False
        for t in (self.battery_timer, self.hotplug_timer, self.game_monitor_timer, self.game_countdown_timer):
            try:
                t.stop()
            except Exception as ex:
                APP_LOG.warn(f"Timer stop warning: {ex}")
        if hasattr(self, "wp_background"):
            try:
                self.wp_background.cleanup()
            except Exception as ex:
                APP_LOG.warn(f"Wallpaper cleanup warning: {ex}")
        try:
            self.tray.hide()
            self.tray.deleteLater()
        except Exception as ex:
            APP_LOG.warn(f"Tray cleanup warning: {ex}")
        QApplication.instance().quit()


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    drv = YJXGM80PlusDriver()

    if "--verify-hw" in sys.argv:
        ok_r, msg_r = drv.read_hardware_state()
        ok_b, msg_b = drv.poll_battery_status()
        ok_w, msg_w = drv.apply_to_hardware(apply_buttons=True)
        if sys.stdout is not None:
            print("READ HW :", ok_r, "|", msg_r)
            print("BATTERY :", ok_b, "|", msg_b)
            print("WRITE HW:", ok_w, "|", msg_w)
        sys.exit(0 if (ok_r and ok_w) else 1)

    _single_mutex = acquire_single_instance_or_activate()
    if _single_mutex is None:
        sys.exit(0)

    try:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "Aigo.GM80Plus.ControlCenter.v2"
            )
        except Exception as ex:
            _log_warn(f"AppUserModelID warning: {ex}")
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        ui_font = load_bundled_fonts()
        app.setFont(QFont(ui_font, FONT["base"]))
        win = GM80PlusGlassWindow(drv, ui_font=ui_font)
        win.show()
        sys.exit(app.exec())
    finally:
        try:
            ctypes.windll.kernel32.CloseHandle(_single_mutex)
        except Exception as ex:
            _log_warn(f"Mutex CloseHandle warning: {ex}")
