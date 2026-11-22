# -*- coding: utf-8 -*-
"""
Aigo GM80 Plus Control Center — Real YJX-CHIP Hardware & Glass UI Edition
=========================================================================
Reverse-engineered & verified LIVE on hardware (Aigo GM80 Plus, YJX-CHIP, PAW3311):
  - Supported USB HID Devices (Vendor Interface MI_02, UsagePage=0xFF01, Usage=0x0010):
      * Wired Mode:    VID_A8A4 & PID_2255 (or PID_2256)
      * 2.4G Wireless: VID_A8A5 & PID_2255
  - Real 65-Byte HID Output / Input Protocol (from DeviceDriver.exe @ 0x439220):
      * TX[0] = 0x00 (Report ID)
      * TX[1] = 0x55 (Start Magic)
      * TX[2] = Command Opcode
      * TX[3] = Direction / Mode (0xA5 Read / Button Write, 0xAE Config/Live Write)
      * TX[4] = Checksum = sum(TX[5..64]) & 0xFF
      * RX[0] = 0xAA (Hardware ACK)
  - Verified Commands:
      * 0x03 (Read):  Firmware identity & build date ("YJX.co.mouse ...")
      * 0x0E (Read):  46-byte Onboard Config (Polling Rate, 6x uint16 LE DPIs, Active Stage, Debounce ms)
      * 0x0F (Write): Commit 46-byte Onboard Config to Flash (ACK: 0xAA 0x0F 0xAE)
      * 0x22 (Write): Instant Live DPI Stage & Value Switch (changes bottom LED immediately!)
      * 0x23 (Write): Instant Live Polling Rate Switch (125/250/500/1000 Hz)
      * 0x08 (Read):  Read 8x 4-byte Button Map from Bank 0 (ACK: 0xAA 0x08 0xA5)
      * 0x09 (Write): Write 8x 4-byte Button Map to Bank 0 (ACK: 0xAA 0x09 0xA5)
      * 0x30 (Read):  Dongle/Battery Telemetry check (2.4G returns byte[8]=0x50 -> 80% / ~4.05V)

UI Features (PySide6):
  - True Glassmorphism translucent cards & buttons (25%-35% opacity with glowing thin borders)
  - Full-bleed Wallpaper Slideshow from wallpapers/ with Aspect-Ratio Center Crop & 20% light dim
  - Smooth 20-frame Alpha Crossfade transition (~0.7s) every 10 seconds
  - Eye Toggle Button (👁) to hide all cards and view full wallpaper
  - Clean Arabic RTL layout with ONLY genuine GM80 Plus PAW3311 features (Zero fake settings!)
  - Real System Tray Icon using app_icon.ico + 3-minute zero-stutter battery/status monitor
"""

import os
import sys
import glob
import json
import time
import shutil
import ctypes
import sqlite3
import subprocess
import threading
from ctypes import wintypes

import hid
from PIL import Image, ImageDraw, ImageFont

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QSize
from PySide6.QtGui import (
    QIcon, QPixmap, QImage, QPainter, QColor, QFont, QAction, QCursor
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QSlider, QComboBox, QRadioButton, QButtonGroup,
    QStackedWidget, QFrame, QSystemTrayIcon, QMenu, QColorDialog, QMessageBox,
    QSizePolicy, QDialog, QFileDialog, QCheckBox, QLineEdit, QProgressBar
)

# ============================================================================
# HARDWARE CONSTANTS (VERIFIED LIVE ON AIGO GM80 PLUS)
# ============================================================================
VID_WIRED = 0xA8A4
VID_WIRELESS = 0xA8A5
VALID_PIDS = (0x2255, 0x2256)
VENDOR_USAGE_PAGE = 0xFF01
VENDOR_USAGE = 0x0010

# Smart Battery Poll Interval: 3 minutes (180 seconds) -> Zero stutter at 500Hz
BATTERY_POLL_INTERVAL_MS = 180_000
SLIDESHOW_HOLD_MS = 10_000       # 10 seconds between wallpaper transitions
CROSSFADE_FRAMES = 20            # 20 smooth frames
CROSSFADE_STEP_MS = 35           # 20 * 35ms = 0.70 seconds total crossfade

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
DEFAULT_SETTINGS = {
    "language": "ar",
    "run_in_background": False,
    "battery_poll_seconds": 180,
    "custom_icon": "",
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

# Verified YJX-CHIP 4-byte Button Codes (from 0x410f90 & 0x42b708)
BUTTON_PRESETS = [
    ("كليك شمال (Left Click)",          (0x20, 0x01, 0x00, 0x00)),
    ("كليك يمين (Right Click)",         (0x20, 0x02, 0x00, 0x00)),
    ("كليك البكرة (Middle Click)",       (0x20, 0x04, 0x00, 0x00)),
    ("رجوع للخلف (Backward)",           (0x20, 0x08, 0x00, 0x00)),
    ("تقدم للأمام (Forward)",            (0x20, 0x10, 0x00, 0x00)),
    ("تبديل الـ DPI (DPI Loop)",         (0x21, 0x55, 0x00, 0x00)),
    ("زيادة الـ DPI (DPI +)",            (0xF0, 0x01, 0x01, 0x00)),
    ("تقليل الـ DPI (DPI -)",            (0xF0, 0x01, 0x02, 0x00)),
    ("دورة الـ DPI (DPI Cycle)",         (0xF0, 0x01, 0x03, 0x00)),
    ("دبل كليك يسار (Double Click)",     (0x20, 0x01, 0x02, 0x00)),
    ("تبديل الهرتز (Polling Loop)",      (0xF0, 0x02, 0x03, 0x00)),
    ("تشغيل / إيقاف (Play/Pause)",       (0x30, 0xCD, 0x00, 0x00)),
    ("رفع الصوت (Volume +)",             (0x30, 0xE9, 0x00, 0x00)),
    ("خفض الصوت (Volume -)",             (0x30, 0xEA, 0x00, 0x00)),
    ("كتم الصوت (Mute)",                 (0x30, 0xE2, 0x00, 0x00)),
    ("نسخ (Ctrl + C)",                   (0x10, 0x01, 0x06, 0x00)),
    ("لصق (Ctrl + V)",                   (0x10, 0x01, 0x19, 0x00)),
    ("إظهار سطح المكتب (Win + D)",       (0x10, 0x08, 0x07, 0x00)),
    ("تعطيل الزر (Disabled)",            (0x00, 0x00, 0x00, 0x00)),
]
BUTTON_PRESETS_EN = [
    "Left Click",
    "Right Click",
    "Middle Click",
    "Backward",
    "Forward",
    "DPI Loop",
    "DPI +",
    "DPI -",
    "DPI Cycle",
    "Double Click",
    "Polling Rate Loop",
    "Play / Pause",
    "Volume +",
    "Volume -",
    "Mute",
    "Copy (Ctrl + C)",
    "Paste (Ctrl + V)",
    "Show Desktop (Win + D)",
    "Disabled",
]
BUTTON_NAME_BY_CODE = {code: name for name, code in BUTTON_PRESETS}
BUTTON_CODE_BY_NAME = {name: code for name, code in BUTTON_PRESETS}
BUTTON_INDEX_BY_CODE = {code: idx for idx, (_, code) in enumerate(BUTTON_PRESETS)}

# Default 6-button map matching factory Bank 0 readback
DEFAULT_BUTTON_CODES = [
    (0x20, 0x01, 0x00, 0x00),  # Key 1: Left Click
    (0x20, 0x02, 0x00, 0x00),  # Key 2: Right Click
    (0x20, 0x04, 0x00, 0x00),  # Key 3: Middle Click
    (0x20, 0x08, 0x00, 0x00),  # Key 4: Backward
    (0x20, 0x10, 0x00, 0x00),  # Key 5: Forward
    (0x21, 0x55, 0x00, 0x00),  # Key 6: DPI Loop
]


def get_base_dir() -> str:
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def get_resource_path(rel_path: str) -> str:
    ext = os.path.join(get_base_dir(), rel_path)
    if os.path.exists(ext):
        return ext
    if hasattr(sys, "_MEIPASS"):
        bundled = os.path.join(sys._MEIPASS, rel_path)
        if os.path.exists(bundled):
            return bundled
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
    except Exception:
        pass
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
        except Exception:
            pass


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
    return os.path.join(get_base_dir(), "settings.json")


def load_settings() -> dict:
    cfg = dict(DEFAULT_SETTINGS)
    p = get_settings_path()
    if os.path.exists(p):
        try:
            with open(p, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                if loaded.get("language") in ("ar", "en"):
                    cfg["language"] = loaded["language"]
                if isinstance(loaded.get("run_in_background"), bool):
                    cfg["run_in_background"] = loaded["run_in_background"]
                if isinstance(loaded.get("battery_poll_seconds"), int) and loaded["battery_poll_seconds"] >= 0:
                    cfg["battery_poll_seconds"] = loaded["battery_poll_seconds"]
                if isinstance(loaded.get("custom_icon"), str):
                    cfg["custom_icon"] = loaded["custom_icon"]
        except Exception:
            pass
    return cfg


def save_settings(cfg: dict):
    try:
        with open(get_settings_path(), "w", encoding="utf-8") as fh:
            json.dump(cfg, fh, ensure_ascii=False, indent=2)
    except Exception:
        pass


def get_active_icon_path(custom_icon_name: str = "") -> str:
    if custom_icon_name:
        cand = custom_icon_name if os.path.isabs(custom_icon_name) else os.path.join(get_base_dir(), custom_icon_name)
        if os.path.exists(cand):
            return cand
    custom_default = os.path.join(get_base_dir(), "custom_icon.ico")
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
        res = subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            text=True,
            timeout=5,
            env=env,
        )
        # Notify Windows Shell to refresh desktop icons immediately (SHCNE_ASSOCCHANGED = 0x08000000)
        try:
            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0x0000, None, None)
        except Exception:
            pass
        return "SHORTCUT_UPDATED" in (res.stdout or "")
    except Exception:
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
        except Exception:
            pass
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
        except Exception:
            pass
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
                if r_btn and len(r_btn) >= 32:
                    parsed = []
                    valid_any = False
                    for idx in range(6):
                        off = 8 + idx * 4
                        code = (r_btn[off], r_btn[off + 1], r_btn[off + 2], r_btn[off + 3])
                        if code != (0xFF, 0xFF, 0xFF, 0xFF) and code != (0x00, 0x00, 0x00, 0x00):
                            valid_any = True
                        parsed.append(code)
                    if valid_any:
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
                for idx in range(6):
                    p[9 + idx * 4: 13 + idx * 4] = list(self.button_codes[idx])
                p[33:37] = [0x21, 0x38, 0x01, 0x00]  # Scroll Up
                p[37:41] = [0x21, 0x38, 0xFF, 0x00]  # Scroll Down
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
                        if rb_chk and len(rb_chk) >= 32:
                            for idx in range(6):
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
# WORKER SIGNALS FOR THREAD-SAFE UI UPDATES
# ============================================================================
class WorkerSignals(QObject):
    poll_done = Signal(bool, str)
    apply_done = Signal(bool, str)
    init_read_done = Signal(bool, str)


# ============================================================================
# HELPER: PIL IMAGE -> QPIXMAP & DYNAMIC TRAY ICON (WITH app_icon.ico)
# ============================================================================
def pil_to_qpixmap(pil_img: Image.Image) -> QPixmap:
    rgb = pil_img.convert("RGBA")
    data = rgb.tobytes("raw", "RGBA")
    qimg = QImage(data, rgb.width, rgb.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(qimg.copy())


def crop_cover(pil_img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Aspect-Ratio Center Crop (zero stretching) + 20% light dark overlay."""
    iw, ih = pil_img.size
    target_ratio = target_w / float(max(1, target_h))
    img_ratio = iw / float(max(1, ih))
    if img_ratio > target_ratio:
        new_w = int(ih * target_ratio)
        left = (iw - new_w) // 2
        cropped = pil_img.crop((left, 0, left + new_w, ih))
    else:
        new_h = int(iw / target_ratio)
        top = (ih - new_h) // 2
        cropped = pil_img.crop((0, top, iw, top + new_h))
    resized = cropped.resize((target_w, target_h), Image.LANCZOS).convert("RGB")
    # 20% gentle dim overlay so wallpaper shines vividly behind glass cards
    dark = Image.new("RGB", (target_w, target_h), (8, 12, 22))
    return Image.blend(resized, dark, alpha=0.20)


def build_tray_qicon(driver: YJXGM80PlusDriver, custom_icon_path: str = "") -> QIcon:
    """Build System Tray icon using custom or app_icon.ico + crisp numeric battery / mode badge."""
    base = None
    candidates = []
    if custom_icon_path and os.path.exists(custom_icon_path):
        candidates.append(custom_icon_path)
    default_ico = get_resource_path("app_icon.ico")
    if os.path.exists(default_ico):
        candidates.append(default_ico)

    for p in candidates:
        try:
            im = Image.open(p).convert("RGBA")
            w, h = im.size
            s = min(w, h)
            base = im.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2)).resize((64, 64), Image.LANCZOS)
            break
        except Exception:
            pass
    if base is None:
        base = Image.new("RGBA", (64, 64), (15, 23, 42, 255))

    draw = ImageDraw.Draw(base)
    try:
        font_num = ImageFont.truetype("arialbd.ttf", 19)
        font_tag = ImageFont.truetype("arialbd.ttf", 14)
    except Exception:
        font_num = ImageFont.load_default()
        font_tag = ImageFont.load_default()

    # Crisp dark pill at bottom of tray icon
    draw.rounded_rectangle((2, 34, 62, 62), radius=8, fill=(8, 12, 22, 235), outline=(56, 189, 248, 255), width=2)
    if not driver.connected:
        draw.text((13, 38), "OFF", fill=(248, 113, 113, 255), font=font_num)
    elif driver.battery_percent is not None:
        pct = driver.battery_percent
        col = (248, 113, 113, 255) if pct < 20 else ((251, 191, 36, 255) if pct <= 50 else (52, 211, 153, 255))
        txt = f"{pct}%" if pct < 100 else "100"
        draw.text((10, 38), txt, fill=col, font=font_num)
    elif driver.is_bluetooth:
        draw.text((20, 40), "BT", fill=(96, 165, 250, 255), font=font_tag)
    elif driver.is_wired:
        draw.text((16, 40), "USB", fill=(96, 165, 250, 255), font=font_tag)
    else:
        draw.text((14, 40), "2.4G", fill=(52, 211, 153, 255), font=font_tag)

    return QIcon(pil_to_qpixmap(base))


# ============================================================================
# MAIN GLASSMORPHISM WINDOW WITH SMOOTH 20-FRAME CROSSFADE WALLPAPER ENGINE
# ============================================================================
GLASS_STYLESHEET = """
QMainWindow {
    background-color: #080C16;
}
QWidget {
    color: #F8FAFC;
    font-family: "Segoe UI", "Tahoma", sans-serif;
}
QFrame#GlassCard {
    background-color: rgba(12, 18, 32, 84);
    border: 1px solid rgba(148, 197, 255, 78);
    border-radius: 16px;
}
QFrame#GlassRow {
    background-color: rgba(15, 23, 42, 74);
    border: 1px solid rgba(148, 197, 255, 58);
    border-radius: 12px;
}
QFrame#BatteryCard {
    background-color: rgba(12, 22, 42, 92);
    border: 1px solid rgba(56, 189, 248, 130);
    border-radius: 14px;
}
QPushButton#GlassBtn {
    background-color: rgba(30, 41, 59, 86);
    border: 1px solid rgba(148, 197, 255, 85);
    border-radius: 10px;
    padding: 7px 14px;
    font-weight: bold;
    color: #F8FAFC;
}
QPushButton#GlassBtn:hover {
    background-color: rgba(56, 189, 248, 105);
    border: 1px solid rgba(186, 230, 253, 180);
}
QPushButton#TabBtn {
    background-color: rgba(15, 23, 42, 76);
    border: 1px solid rgba(148, 197, 255, 65);
    border-radius: 11px;
    padding: 9px 18px;
    font-size: 13px;
    font-weight: bold;
    color: #E2E8F0;
}
QPushButton#TabBtn:hover {
    background-color: rgba(37, 99, 235, 95);
}
QPushButton#TabBtn[active="true"] {
    background-color: rgba(37, 99, 235, 135);
    border: 1px solid rgba(147, 197, 253, 210);
    color: #FFFFFF;
}
QPushButton#SaveBtn {
    background-color: rgba(5, 150, 105, 145);
    border: 1px solid rgba(110, 231, 183, 190);
    border-radius: 11px;
    padding: 9px 22px;
    font-size: 13px;
    font-weight: bold;
    color: #FFFFFF;
}
QPushButton#SaveBtn:hover {
    background-color: rgba(16, 185, 129, 185);
}
QPushButton#RateBtn {
    background-color: rgba(15, 23, 42, 78);
    border: 1px solid rgba(148, 197, 255, 70);
    border-radius: 11px;
    padding: 12px 16px;
    font-size: 15px;
    font-weight: bold;
    color: #E2E8F0;
}
QPushButton#RateBtn[active="true"] {
    background-color: rgba(37, 99, 235, 145);
    border: 1px solid rgba(147, 197, 253, 220);
    color: #FFFFFF;
}
QComboBox {
    background-color: rgba(15, 23, 42, 115);
    border: 1px solid rgba(148, 197, 255, 95);
    border-radius: 9px;
    padding: 6px 12px;
    font-size: 13px;
    font-weight: bold;
    color: #F8FAFC;
}
QComboBox QAbstractItemView {
    background-color: #0F172A;
    border: 1px solid #38BDF8;
    selection-background-color: #2563EB;
    color: #F8FAFC;
}
QSlider::groove:horizontal {
    height: 7px;
    background: rgba(148, 163, 184, 90);
    border-radius: 4px;
}
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38BDF8, stop:1 #2563EB);
    border-radius: 4px;
}
QSlider::handle:horizontal {
    background: #FFFFFF;
    border: 2px solid #38BDF8;
    width: 18px;
    height: 18px;
    margin: -6px 0;
    border-radius: 9px;
}
QRadioButton {
    font-size: 13px;
    font-weight: bold;
    spacing: 8px;
}
QRadioButton::indicator {
    width: 17px;
    height: 17px;
    border-radius: 9px;
    border: 2px solid rgba(148, 197, 255, 170);
    background: rgba(15, 23, 42, 90);
}
QRadioButton::indicator:checked {
    border: 2px solid #38BDF8;
    background: #38BDF8;
}
QDialog#SettingsDialog {
    background-color: #0B1221;
    border: 1px solid rgba(56, 189, 248, 160);
    border-radius: 14px;
}
QLineEdit#PathBox {
    background-color: rgba(15, 23, 42, 175);
    border: 1px solid rgba(148, 197, 255, 85);
    border-radius: 8px;
    padding: 6px 10px;
    color: #CBD5E1;
    font-family: Consolas;
    font-size: 12px;
}
QCheckBox {
    font-size: 13px;
    font-weight: bold;
    spacing: 10px;
    color: #F8FAFC;
}
QCheckBox::indicator {
    width: 20px;
    height: 20px;
    border-radius: 6px;
    border: 2px solid rgba(148, 197, 255, 170);
    background: rgba(15, 23, 42, 140);
}
QCheckBox::indicator:checked {
    border: 2px solid #34D399;
    background: #10B981;
}
"""


class SettingsDialog(QDialog):
    """Organized Settings Modal saving preferences to settings.json."""

    def __init__(self, parent_win: "GM80PlusGlassWindow"):
        super().__init__(parent_win)
        self.win = parent_win
        self.setObjectName("SettingsDialog")
        self.setModal(True)
        self.setMinimumWidth(620)
        self.setStyleSheet(GLASS_STYLESHEET)
        self._build_dialog_ui()
        self._refresh_texts()

    def _build_dialog_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(12)

        self.lbl_dlg_title = QLabel()
        self.lbl_dlg_title.setStyleSheet("font-size: 18px; font-weight: bold; color: #38BDF8; background: transparent;")
        lay.addWidget(self.lbl_dlg_title)

        # 1. Language Setting
        c_lang = QFrame()
        c_lang.setObjectName("GlassRow")
        l_lay = QHBoxLayout(c_lang)
        l_lay.setContentsMargins(14, 12, 14, 12)
        self.lbl_lang_hdr = QLabel()
        self.lbl_lang_hdr.setStyleSheet("font-size: 13px; font-weight: bold; background: transparent;")
        l_lay.addWidget(self.lbl_lang_hdr)
        l_lay.addStretch()

        self.cmb_lang = QComboBox()
        self.cmb_lang.setFixedWidth(180)
        self.cmb_lang.addItems(["العربية (Arabic)", "English"])
        self.cmb_lang.setCurrentIndex(1 if self.win.lang == "en" else 0)
        self.cmb_lang.currentIndexChanged.connect(self._on_lang_combo)
        l_lay.addWidget(self.cmb_lang)
        lay.addWidget(c_lang)

        # 2. Run in Background (Minimize to Tray on Close X)
        c_bg = QFrame()
        c_bg.setObjectName("GlassRow")
        bg_lay = QVBoxLayout(c_bg)
        bg_lay.setContentsMargins(14, 12, 14, 12)
        bg_lay.setSpacing(6)
        self.chk_bg = QCheckBox()
        self.chk_bg.setChecked(self.win.run_in_background)
        self.chk_bg.toggled.connect(self._on_bg_toggled)
        bg_lay.addWidget(self.chk_bg)
        self.lbl_bg_hint = QLabel()
        self.lbl_bg_hint.setStyleSheet("font-size: 11px; color: #94A3B8; background: transparent;")
        bg_lay.addWidget(self.lbl_bg_hint)
        lay.addWidget(c_bg)

        # 3. Auto Battery Check Interval
        c_bat = QFrame()
        c_bat.setObjectName("GlassRow")
        b_lay = QHBoxLayout(c_bat)
        b_lay.setContentsMargins(14, 12, 14, 12)
        self.lbl_bat_hdr = QLabel()
        self.lbl_bat_hdr.setStyleSheet("font-size: 13px; font-weight: bold; background: transparent;")
        b_lay.addWidget(self.lbl_bat_hdr)
        b_lay.addStretch()

        self.cmb_dlg_bat = QComboBox()
        self.cmb_dlg_bat.setFixedWidth(180)
        self.cmb_dlg_bat.currentIndexChanged.connect(self._on_bat_combo)
        b_lay.addWidget(self.cmb_dlg_bat)
        lay.addWidget(c_bat)

        # 4. Wallpapers Folder
        c_wp = QFrame()
        c_wp.setObjectName("GlassRow")
        wp_lay = QVBoxLayout(c_wp)
        wp_lay.setContentsMargins(14, 12, 14, 12)
        wp_lay.setSpacing(8)
        self.lbl_wp_hdr = QLabel()
        self.lbl_wp_hdr.setStyleSheet("font-size: 13px; font-weight: bold; background: transparent;")
        wp_lay.addWidget(self.lbl_wp_hdr)

        wp_row = QHBoxLayout()
        wp_row.setSpacing(8)
        self.txt_wp_path = QLineEdit(os.path.join(get_base_dir(), "wallpapers"))
        self.txt_wp_path.setObjectName("PathBox")
        self.txt_wp_path.setReadOnly(True)
        wp_row.addWidget(self.txt_wp_path, 1)

        self.btn_open_wp = QPushButton()
        self.btn_open_wp.setObjectName("GlassBtn")
        self.btn_open_wp.clicked.connect(self._open_wallpapers_folder)
        wp_row.addWidget(self.btn_open_wp)

        self.btn_reload_wp = QPushButton()
        self.btn_reload_wp.setObjectName("GlassBtn")
        self.btn_reload_wp.clicked.connect(self._reload_wallpapers)
        wp_row.addWidget(self.btn_reload_wp)
        wp_lay.addLayout(wp_row)
        lay.addWidget(c_wp)

        # 5. Custom App Icon
        c_ico = QFrame()
        c_ico.setObjectName("GlassRow")
        ico_lay = QVBoxLayout(c_ico)
        ico_lay.setContentsMargins(14, 12, 14, 12)
        ico_lay.setSpacing(8)

        ico_top = QHBoxLayout()
        ico_top.setSpacing(12)
        self.lbl_ico_preview = QLabel()
        self.lbl_ico_preview.setFixedSize(44, 44)
        self.lbl_ico_preview.setAlignment(Qt.AlignCenter)
        self.lbl_ico_preview.setStyleSheet("background: rgba(15,23,42,160); border: 1px solid rgba(148,197,255,95); border-radius: 9px;")
        ico_top.addWidget(self.lbl_ico_preview)

        self.lbl_ico_hdr = QLabel()
        self.lbl_ico_hdr.setStyleSheet("font-size: 13px; font-weight: bold; background: transparent;")
        ico_top.addWidget(self.lbl_ico_hdr, 1)
        ico_lay.addLayout(ico_top)

        ico_btns = QHBoxLayout()
        ico_btns.setSpacing(10)
        self.btn_pick_ico = QPushButton()
        self.btn_pick_ico.setObjectName("GlassBtn")
        self.btn_pick_ico.clicked.connect(self._pick_custom_icon)
        ico_btns.addWidget(self.btn_pick_ico)

        self.btn_reset_ico = QPushButton()
        self.btn_reset_ico.setObjectName("GlassBtn")
        self.btn_reset_ico.clicked.connect(self._reset_default_icon)
        ico_btns.addWidget(self.btn_reset_ico)
        ico_lay.addLayout(ico_btns)
        lay.addWidget(c_ico)

        # Close Footer
        foot = QHBoxLayout()
        foot.addStretch()
        self.btn_dlg_close = QPushButton()
        self.btn_dlg_close.setObjectName("SaveBtn")
        self.btn_dlg_close.clicked.connect(self.accept)
        foot.addWidget(self.btn_dlg_close)
        lay.addLayout(foot)

    def _refresh_texts(self):
        en = (self.win.lang == "en")
        self.setLayoutDirection(Qt.LeftToRight if en else Qt.RightToLeft)
        self.setWindowTitle("Settings — Aigo GM80 Plus" if en else "الإعدادات — Aigo GM80 Plus")
        self.lbl_dlg_title.setText("⚙️ Application Settings" if en else "⚙️ إعدادات البرنامج")
        self.lbl_lang_hdr.setText("🌐 App Language:" if en else "🌐 لغة التطبيق:")
        self.chk_bg.setText(
            "Run in Background (Minimize to Tray on X)" if en
            else "التشغيل في الخلفية (تصغير بجانب الساعة عند الضغط على X)"
        )
        self.lbl_bg_hint.setText(
            "When OFF (default), clicking X exits the program and tray icon completely." if en
            else "عند الإيقاف (الافتراضي)، الضغط على زر الإغلاق X يغلق البرنامج والأيقونة نهائياً من الذاكرة."
        )
        self.lbl_bat_hdr.setText("🔋 Auto Battery Check Interval:" if en else "🔋 مؤقت فحص صحة البطارية التلقائي:")

        self.cmb_dlg_bat.blockSignals(True)
        self.cmb_dlg_bat.clear()
        self.cmb_dlg_bat.addItems([opt[2 if en else 1] for opt in BAT_POLL_OPTIONS])
        self.cmb_dlg_bat.setCurrentIndex(self.win.get_battery_interval_index())
        self.cmb_dlg_bat.blockSignals(False)

        self.lbl_wp_hdr.setText(
            "🖼️ Wallpapers Folder (Add JPG/PNG/WEBP images here):" if en
            else "🖼️ مجلد الخلفيات (ضع صورك بصيغة JPG/PNG/WEBP هنا):"
        )
        self.btn_open_wp.setText("📂 Open Wallpapers Folder" if en else "📂 فتح مجلد الخلفيات")
        self.btn_reload_wp.setText("↻ Reload" if en else "↻ إعادة تحميل")

        self.lbl_ico_hdr.setText(
            "🎨 Custom App & Shortcut Icon (.ico / .png / .jpg):" if en
            else "🎨 أيقونة البرنامج والاختصار (.ico / .png / .jpg):"
        )
        self.btn_pick_ico.setText("🖼️ Change App Icon" if en else "🖼️ تغيير أيقونة البرنامج")
        self.btn_reset_ico.setText("↩️ Restore Default Icon" if en else "↩️ استعادة الأيقونة الافتراضية")
        self.btn_dlg_close.setText("Done" if en else "إغلاق")

        ico_p = get_active_icon_path(self.win.settings.get("custom_icon", ""))
        if ico_p and os.path.exists(ico_p):
            self.lbl_ico_preview.setPixmap(QIcon(ico_p).pixmap(36, 36))

    def _on_lang_combo(self, idx: int):
        target = "en" if idx == 1 else "ar"
        if target != self.win.lang:
            self.win.set_language(target)
            self._refresh_texts()

    def _on_bg_toggled(self, checked: bool):
        self.win.set_run_in_background(checked)

    def _on_bat_combo(self, idx: int):
        if 0 <= idx < len(BAT_POLL_OPTIONS):
            self.win._on_bat_interval_changed(idx)

    def _open_wallpapers_folder(self):
        wp_dir = os.path.join(get_base_dir(), "wallpapers")
        os.makedirs(wp_dir, exist_ok=True)
        try:
            os.startfile(wp_dir)
        except Exception as ex:
            QMessageBox.warning(self, "Error", str(ex))

    def _reload_wallpapers(self):
        self.win.reload_wallpapers()

    def _pick_custom_icon(self):
        en = (self.win.lang == "en")
        src, _ = QFileDialog.getOpenFileName(
            self,
            "Select App Icon Image" if en else "اختر صورة لأيقونة البرنامج",
            get_base_dir(),
            "Images (*.ico *.png *.jpg *.jpeg *.bmp *.webp)",
        )
        if not src:
            return
        dest = os.path.join(get_base_dir(), "custom_icon.ico")
        if convert_image_to_custom_ico(src, dest):
            self.win.apply_custom_icon("custom_icon.ico")
            self._refresh_texts()
        else:
            QMessageBox.warning(
                self,
                "Icon Error" if en else "خطأ في الأيقونة",
                "Failed to convert selected image to .ico." if en else "تعذر تحويل الصورة المختارة إلى أيقونة.",
            )

    def _reset_default_icon(self):
        self.win.apply_custom_icon("")
        self._refresh_texts()



class GM80PlusGlassWindow(QMainWindow):
    def __init__(self, driver: YJXGM80PlusDriver):
        super().__init__()
        self.driver = driver
        self.settings = load_settings()
        self.lang = self.settings.get("language", "ar")
        self.driver.lang = self.lang
        self.run_in_background = bool(self.settings.get("run_in_background", False))
        self.bat_poll_seconds = int(self.settings.get("battery_poll_seconds", 180))
        self._manual_poll_pending = False

        try:
            self._show_msg_id = ctypes.windll.user32.RegisterWindowMessageW(SHOW_WINDOW_MSG_NAME)
        except Exception:
            self._show_msg_id = 0

        self.signals = WorkerSignals()
        self.signals.poll_done.connect(self._on_poll_done)
        self.signals.apply_done.connect(self._on_apply_done)
        self.signals.init_read_done.connect(self._on_init_read_done)

        self.setWindowTitle("Aigo GM80 Plus Control — مركز التحكم الاحترافي")
        self.resize(1060, 720)
        self.setMinimumSize(940, 650)
        self.setLayoutDirection(Qt.LeftToRight if self.lang == "en" else Qt.RightToLeft)
        self.setStyleSheet(GLASS_STYLESHEET)

        # Window Icon (supports custom_icon.ico + app_icon.ico fallback)
        self._apply_window_and_app_icon()

        # Wallpaper Crossfade Engine state
        self.wallpaper_paths = self._load_wallpaper_list()
        self.wp_index = 0
        self.slideshow_paused = False
        self.cards_hidden = False
        self._current_pil = None
        self._next_pil = None
        self._display_pixmap = None
        self._fade_step = 0
        self._fading = False

        # Track USB hot-plug state (wired vs 2.4G dongle) without sending HID traffic
        self._last_device_signature = None

        # Build UI overlay container
        self._build_ui()
        self._setup_tray()

        # Apply persisted language / interval state on startup
        if self.lang == "en":
            self._apply_language()

        # Timers
        self.slideshow_timer = QTimer(self)
        self.slideshow_timer.timeout.connect(self._start_crossfade_next)
        self.slideshow_timer.start(SLIDESHOW_HOLD_MS)

        self.fade_timer = QTimer(self)
        self.fade_timer.timeout.connect(self._advance_crossfade)

        self.battery_timer = QTimer(self)
        self.battery_timer.timeout.connect(lambda: self.trigger_battery_poll(manual=False))
        if self.bat_poll_seconds > 0:
            self.battery_timer.start(self.bat_poll_seconds * 1000)

        # Smart Hot-Plug Timer (checks USB enumeration every 2.5s; zero HID packets unless mode changed!)
        self.hotplug_timer = QTimer(self)
        self.hotplug_timer.timeout.connect(self._check_hotplug_transition)
        self.hotplug_timer.start(HOTPLUG_CHECK_INTERVAL_MS)

        # Render initial wallpaper
        self._prepare_current_wallpaper()

        # Startup checks: conflict check, real hardware read, battery poll
        QTimer.singleShot(300, self._check_driver_conflict)
        QTimer.singleShot(450, self._trigger_initial_hw_read)
        QTimer.singleShot(850, lambda: self.trigger_battery_poll(manual=False))

    def nativeEvent(self, eventType, message):
        """Listen for Win32 Single-Instance show-window broadcast to restore hidden/tray window."""
        try:
            if self._show_msg_id:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == self._show_msg_id:
                    QTimer.singleShot(0, self.restore_from_tray)
                    return True, 0
        except Exception:
            pass
        return super().nativeEvent(eventType, message)

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
        self.settings["run_in_background"] = self.run_in_background
        self.settings["battery_poll_seconds"] = self.bat_poll_seconds
        save_settings(self.settings)

    def open_settings_dialog(self):
        dlg = SettingsDialog(self)
        dlg.exec()

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
        en = (self.lang == "en")
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
        if en:
            self.lbl_status.setText(
                "⚙️ Run in Background enabled (X minimizes to tray)." if self.run_in_background
                else "⚙️ Run in Background disabled (X exits app completely)."
            )
        else:
            self.lbl_status.setText(
                "⚙️ تم تفعيل التشغيل في الخلفية (زر X يصغّر البرنامج بجانب الساعة)." if self.run_in_background
                else "⚙️ تم إيقاف التشغيل في الخلفية (زر X يغلق البرنامج نهائياً)."
            )

    def apply_custom_icon(self, custom_icon_name: str):
        self.settings["custom_icon"] = custom_icon_name
        self._save_current_settings()
        self._apply_window_and_app_icon()
        self._refresh_tray()
        ico_p = get_active_icon_path(custom_icon_name)
        shortcut_ok = update_desktop_shortcut_icon(ico_p)
        en = (self.lang == "en")
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #34D399; background: transparent;")
        if custom_icon_name:
            if en:
                self.lbl_status.setText(
                    f"✅ Custom icon applied to window, tray{' & desktop shortcut' if shortcut_ok else ''}!"
                )
            else:
                self.lbl_status.setText(
                    f"✅ تم تطبيق الأيقونة الجديدة على البرنامج{' واختصار سطح المكتب' if shortcut_ok else ''}!"
                )
        else:
            if en:
                self.lbl_status.setText("✅ Restored default Aigo GM80 Plus icon.")
            else:
                self.lbl_status.setText("✅ تم استعادة الأيقونة الافتراضية للبرنامج.")

    def reload_wallpapers(self):
        self.fade_timer.stop()
        self._fading = False
        self.wallpaper_paths = self._load_wallpaper_list()
        self.wp_index = 0
        self._prepare_current_wallpaper()
        self.update()
        en = (self.lang == "en")
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
        self.lbl_status.setText(
            f"🖼️ Reloaded wallpapers folder ({len(self.wallpaper_paths)} images found)." if en
            else f"🖼️ تم إعادة تحميل مجلد الخلفيات (تم العثور على {len(self.wallpaper_paths)} صورة)."
        )

    def _check_hotplug_transition(self):
        """
        Zero-stutter smart auto-switch between Wired (VID_A8A4) and 2.4G Dongle (VID_A8A5).
        Only enumerates OS USB HID descriptors (sends ZERO packets to the mouse!).
        If cable is plugged in or unplugged, immediately switches active channel and refreshes battery (CMD 0x30).
        """
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
                prev_wired, prev_wireless = self._last_device_signature
                self._last_device_signature = sig
                # Re-enumerate driver paths and trigger immediate battery & state refresh
                self.driver.enumerate_devices()
                self._update_battery_header()
                self._refresh_tray()
                en = (self.lang == "en")
                if prev_wired and not has_wired and has_wireless:
                    # Cable unplugged -> seamlessly switched to 2.4G Dongle! Immediately read CMD 0x30 battery!
                    self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
                    self.lbl_status.setText(
                        "🔄 USB cable unplugged — Automatically switched to 2.4G Dongle & polling battery..." if en
                        else "🔄 تم فصل الكابل — الانتقال تلقائياً إلى وضع 2.4G Dongle وتفعيل قراءة البطارية..."
                    )
                    QTimer.singleShot(600, self.trigger_battery_poll)
                    QTimer.singleShot(900, self._trigger_initial_hw_read)
                elif not prev_wired and has_wired:
                    # Cable plugged in -> switched to Wired USB!
                    self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #34D399; background: transparent;")
                    self.lbl_status.setText(
                        "🔌 USB cable connected — Automatically switched to USB Wired mode..." if en
                        else "🔌 تم توصيل الكابل — الانتقال تلقائياً إلى وضع السلك (USB Wired)..."
                    )
                    QTimer.singleShot(600, self._trigger_initial_hw_read)
                    QTimer.singleShot(900, self.trigger_battery_poll)
                elif has_wired or has_wireless:
                    QTimer.singleShot(500, self._trigger_initial_hw_read)
                    QTimer.singleShot(800, self.trigger_battery_poll)
        except Exception:
            pass

    # ---------------- Wallpaper Slideshow + 20-Frame Smooth Crossfade ----------------

    def _load_wallpaper_list(self) -> list[str]:
        wp_dir = get_resource_path("wallpapers")
        if not os.path.isdir(wp_dir):
            return []
        files = []
        for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp", "*.bmp"):
            files.extend(glob.glob(os.path.join(wp_dir, ext)))
        return sorted(files)

    def _load_fitted_wallpaper(self, idx: int) -> Image.Image | None:
        if not self.wallpaper_paths:
            return None
        path = self.wallpaper_paths[idx % len(self.wallpaper_paths)]
        try:
            with Image.open(path) as im:
                return crop_cover(im, max(self.width(), 960), max(self.height(), 660))
        except Exception:
            return None

    def _prepare_current_wallpaper(self):
        img = self._load_fitted_wallpaper(self.wp_index)
        if img is not None:
            self._current_pil = img
            self._display_pixmap = pil_to_qpixmap(img)
            self.update()

    def _start_crossfade_next(self):
        if self.slideshow_paused or len(self.wallpaper_paths) < 2 or self._fading:
            return
        next_idx = (self.wp_index + 1) % len(self.wallpaper_paths)
        nxt = self._load_fitted_wallpaper(next_idx)
        if nxt is None or self._current_pil is None:
            return
        if nxt.size != self._current_pil.size:
            self._current_pil = self._current_pil.resize(nxt.size, Image.LANCZOS)
        self.wp_index = next_idx
        self._next_pil = nxt
        self._fade_step = 0
        self._fading = True
        self.fade_timer.start(CROSSFADE_STEP_MS)

    def _advance_crossfade(self):
        self._fade_step += 1
        alpha = min(1.0, self._fade_step / float(CROSSFADE_FRAMES))
        # Smooth ease-in-out curve
        eased = alpha * alpha * (3.0 - 2.0 * alpha)
        blended = Image.blend(self._current_pil, self._next_pil, eased)
        self._display_pixmap = pil_to_qpixmap(blended)
        self.update()
        if self._fade_step >= CROSSFADE_FRAMES:
            self.fade_timer.stop()
            self._current_pil = self._next_pil
            self._next_pil = None
            self._fading = False

    def manual_next_wallpaper(self):
        if len(self.wallpaper_paths) >= 2:
            self.fade_timer.stop()
            self._fading = False
            self._start_crossfade_next()

    def toggle_slideshow_pause(self):
        self.slideshow_paused = not self.slideshow_paused
        if self.lang == "en":
            self.btn_wp_pause.setText("▶ Resume Wallpaper" if self.slideshow_paused else "⏸ Pause Wallpaper")
        else:
            self.btn_wp_pause.setText("▶ استئناف الخلفية" if self.slideshow_paused else "⏸ إيقاف الخلفية")

    def toggle_eye_mode(self):
        """Hide/show all glass cards so user can enjoy full unobstructed animated wallpaper."""
        self.cards_hidden = not self.cards_hidden
        self.main_content_widget.setVisible(not self.cards_hidden)
        if self.lang == "en":
            self.btn_eye.setText("👁️ Show UI" if self.cards_hidden else "👁️")
            self.btn_eye.setToolTip("Show cards" if self.cards_hidden else "Hide cards to view full wallpaper")
        else:
            self.btn_eye.setText("👁️ إظهار الواجهة" if self.cards_hidden else "👁️")
            self.btn_eye.setToolTip("إظهار الكروت" if self.cards_hidden else "إخفاء الكروت للاستمتاع بالخلفية")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if not self._fading:
            self._prepare_current_wallpaper()

    def paintEvent(self, event):
        painter = QPainter(self)
        if self._display_pixmap:
            painter.drawPixmap(self.rect(), self._display_pixmap)
        else:
            painter.fillRect(self.rect(), QColor(8, 12, 22))
        painter.end()

    # ---------------- UI Layout (Clean RTL/LTR Glassmorphism, Zero Fake Settings) ----------------

    def _build_ui(self):
        central = QWidget(self)
        central.setAttribute(Qt.WA_TranslucentBackground)
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(18, 14, 18, 14)
        root_layout.setSpacing(10)

        # ---- Top Micro Floating Bar (Clean 4 buttons only — always visible even in Eye-Hidden mode!) ----
        top_strip = QHBoxLayout()
        top_strip.setSpacing(8)

        self.btn_eye = QPushButton("👁️")
        self.btn_eye.setObjectName("GlassBtn")
        self.btn_eye.setFixedHeight(34)
        self.btn_eye.setToolTip("إخفاء الكروت مؤقتاً للاستمتاع بالخلفية كاملة")
        self.btn_eye.clicked.connect(self.toggle_eye_mode)
        top_strip.addWidget(self.btn_eye)

        self.btn_wp_next = QPushButton("🖼️ خلفية تالية")
        self.btn_wp_next.setObjectName("GlassBtn")
        self.btn_wp_next.setFixedHeight(34)
        self.btn_wp_next.clicked.connect(self.manual_next_wallpaper)
        top_strip.addWidget(self.btn_wp_next)

        self.btn_wp_pause = QPushButton("⏸ إيقاف الخلفية")
        self.btn_wp_pause.setObjectName("GlassBtn")
        self.btn_wp_pause.setFixedHeight(34)
        self.btn_wp_pause.clicked.connect(self.toggle_slideshow_pause)
        top_strip.addWidget(self.btn_wp_pause)

        self.btn_settings = QPushButton("⚙️ الإعدادات")
        self.btn_settings.setObjectName("GlassBtn")
        self.btn_settings.setFixedHeight(34)
        self.btn_settings.clicked.connect(self.open_settings_dialog)
        top_strip.addWidget(self.btn_settings)

        top_strip.addStretch()

        root_layout.addLayout(top_strip)

        # ---- Main Content Wrapper (hidden when user clicks 👁️) ----
        self.main_content_widget = QWidget()
        self.main_content_widget.setAttribute(Qt.WA_TranslucentBackground)
        content_layout = QVBoxLayout(self.main_content_widget)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(10)

        # 1. Header Card + Clean Pro Battery Card
        header_card = QFrame()
        header_card.setObjectName("GlassCard")
        header_lay = QHBoxLayout(header_card)
        header_lay.setContentsMargins(18, 12, 18, 12)
        header_lay.setSpacing(16)

        title_col = QVBoxLayout()
        self.lbl_title = QLabel("AIGO GM80 PLUS  •  مركز التحكم الحقيقي")
        self.lbl_title.setStyleSheet("font-size: 21px; font-weight: bold; color: #FFFFFF; background: transparent;")
        self.lbl_sub = QLabel("شريحة YJX-CHIP  •  سنسور PAW3311  •  تحكم مباشر بذاكرة الماوس الداخلية (Onboard Memory)")
        self.lbl_sub.setStyleSheet("font-size: 12px; color: #CBD5E1; background: transparent;")
        title_col.addWidget(self.lbl_title)
        title_col.addWidget(self.lbl_sub)
        header_lay.addLayout(title_col, 1)

        # Clean Pro Battery & Connection Card
        bat_card = QFrame()
        bat_card.setObjectName("BatteryCard")
        bat_card.setMinimumWidth(410)
        bat_lay = QHBoxLayout(bat_card)
        bat_lay.setContentsMargins(16, 11, 16, 11)
        bat_lay.setSpacing(16)

        # Right side (RTL): Connection status + Modern Battery Bar & % + Last update time
        bat_info_col = QVBoxLayout()
        bat_info_col.setSpacing(6)

        conn_row = QHBoxLayout()
        conn_row.setSpacing(6)
        self.lbl_conn_dot = QLabel("●")
        self.lbl_conn_dot.setStyleSheet("font-size: 11px; color: #34D399; background: transparent;")
        self.lbl_conn = QLabel("جاري فحص الاتصال...")
        self.lbl_conn.setStyleSheet("font-size: 12px; font-weight: bold; color: #E2E8F0; background: transparent;")
        conn_row.addWidget(self.lbl_conn_dot)
        conn_row.addWidget(self.lbl_conn)
        conn_row.addStretch()
        bat_info_col.addLayout(conn_row)

        bar_row = QHBoxLayout()
        bar_row.setSpacing(10)

        self.bat_progress = QProgressBar()
        self.bat_progress.setRange(0, 100)
        self.bat_progress.setValue(0)
        self.bat_progress.setTextVisible(False)
        self.bat_progress.setFixedHeight(14)
        self.bat_progress.setMinimumWidth(120)
        bar_row.addWidget(self.bat_progress, 1)

        self.lbl_bat_pct = QLabel("--%")
        self.lbl_bat_pct.setStyleSheet("font-family: Consolas; font-size: 20px; font-weight: bold; color: #34D399; background: transparent;")
        bar_row.addWidget(self.lbl_bat_pct)

        self.lbl_bat_badge = QLabel("جاري الفحص")
        self.lbl_bat_badge.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: #38BDF8; "
            "background: rgba(56, 189, 248, 28); border: 1px solid rgba(56, 189, 248, 110); "
            "border-radius: 7px; padding: 2px 8px;"
        )
        bar_row.addWidget(self.lbl_bat_badge)
        bat_info_col.addLayout(bar_row)

        self.lbl_poll_time = QLabel("آخر تحديث: --:--:--")
        self.lbl_poll_time.setStyleSheet("font-size: 11px; color: #94A3B8; background: transparent;")
        bat_info_col.addWidget(self.lbl_poll_time)

        bat_lay.addLayout(bat_info_col, 1)

        # Left side (RTL): Single vertically centered Refresh button
        self.btn_refresh_bat = QPushButton("🔄 تحديث الآن")
        self.btn_refresh_bat.setObjectName("GlassBtn")
        self.btn_refresh_bat.setFixedHeight(38)
        self.btn_refresh_bat.clicked.connect(lambda: self.trigger_battery_poll(manual=True))
        bat_lay.addWidget(self.btn_refresh_bat, 0, Qt.AlignVCenter)

        header_lay.addWidget(bat_card)
        content_layout.addWidget(header_card)

        # 2. Navigation Tabs + Save to Onboard Memory Button
        nav_bar = QHBoxLayout()
        nav_bar.setSpacing(8)

        self.tab_buttons = []
        for idx, title in enumerate([
            "🎯 درجات الـ DPI والألوان",
            "⚡ معدل الاستجابة و Debounce",
            "🖱️ برمجة الأزرار",
        ]):
            b = QPushButton(title)
            b.setObjectName("TabBtn")
            b.setProperty("active", "true" if idx == 0 else "false")
            b.clicked.connect(lambda checked=False, i=idx: self.switch_tab(i))
            nav_bar.addWidget(b)
            self.tab_buttons.append(b)

        nav_bar.addStretch()

        self.btn_read_hw = QPushButton("📥 قراءة من الماوس")
        self.btn_read_hw.setObjectName("GlassBtn")
        self.btn_read_hw.setFixedHeight(40)
        self.btn_read_hw.clicked.connect(self._trigger_initial_hw_read)
        nav_bar.addWidget(self.btn_read_hw)

        self.btn_save_hw = QPushButton("💾 حفظ وتطبيق في ذاكرة الماوس")
        self.btn_save_hw.setObjectName("SaveBtn")
        self.btn_save_hw.setFixedHeight(40)
        self.btn_save_hw.clicked.connect(self.trigger_apply_to_hardware)
        nav_bar.addWidget(self.btn_save_hw)

        content_layout.addLayout(nav_bar)

        # 3. Main Glass Stack Container
        self.stack_card = QFrame()
        self.stack_card.setObjectName("GlassCard")
        stack_wrap = QVBoxLayout(self.stack_card)
        stack_wrap.setContentsMargins(16, 14, 16, 14)

        self.stack = QStackedWidget()
        self.stack.setAttribute(Qt.WA_TranslucentBackground)
        self.stack.addWidget(self._create_dpi_page())
        self.stack.addWidget(self._create_perf_page())
        self.stack.addWidget(self._create_buttons_page())
        stack_wrap.addWidget(self.stack)

        content_layout.addWidget(self.stack_card, 1)

        # 4. Real Hardware ACK Status Footer
        footer_card = QFrame()
        footer_card.setObjectName("GlassCard")
        foot_lay = QHBoxLayout(footer_card)
        foot_lay.setContentsMargins(16, 8, 16, 8)

        self.lbl_status = QLabel("جاهز — الاتصال المباشر بالماوس عبر بروتوكول YJX-CHIP (0x55 -> ACK 0xAA).")
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #E2E8F0; background: transparent;")
        foot_lay.addWidget(self.lbl_status, 1)

        content_layout.addWidget(footer_card)
        root_layout.addWidget(self.main_content_widget, 1)

    def _create_dpi_page(self) -> QWidget:
        page = QWidget()
        page.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(page)
        lay.setSpacing(14)

        top_row = QHBoxLayout()
        self.lbl_dpi_hdr = QLabel("درجات الـ DPI الستة الثابتة (800 إلى 12000 DPI) وتخصيص ألوان اللمبة السفلية:")
        self.lbl_dpi_hdr.setStyleSheet("font-size: 13px; font-weight: bold; color: #F1F5F9; background: transparent;")
        top_row.addWidget(self.lbl_dpi_hdr)
        top_row.addStretch()

        self.btn_reset_dpi = QPushButton("استعادة درجات وألوان الكتالوج")
        self.btn_reset_dpi.setObjectName("GlassBtn")
        self.btn_reset_dpi.clicked.connect(self.restore_default_dpis)
        top_row.addWidget(self.btn_reset_dpi)
        lay.addLayout(top_row)

        self.dpi_radio_group = QButtonGroup(self)
        self.dpi_radios = []
        self.dpi_color_btns = []
        self.dpi_value_lbls = []

        grid = QGridLayout()
        grid.setSpacing(14)

        for i in range(6):
            card = QFrame()
            card.setObjectName("GlassRow")
            c_lay = QHBoxLayout(card)
            c_lay.setContentsMargins(18, 16, 18, 16)
            c_lay.setSpacing(12)

            rb = QRadioButton(f"الدرجة {i + 1}")
            rb.setFixedWidth(96)
            self.dpi_radio_group.addButton(rb, i)
            rb.clicked.connect(lambda checked=False, idx=i: self._on_dpi_stage_selected(idx))
            c_lay.addWidget(rb)
            self.dpi_radios.append(rb)

            vlbl = QLabel(f"{DEFAULT_DPI_VALUES[i]} DPI")
            vlbl.setFixedWidth(112)
            vlbl.setAlignment(Qt.AlignCenter)
            vlbl.setStyleSheet(
                "font-family: Consolas; font-size: 16px; font-weight: bold; color: #38BDF8; "
                "background: rgba(15, 23, 42, 110); border: 1px solid rgba(56, 189, 248, 85); "
                "border-radius: 9px; padding: 6px 10px;"
            )
            c_lay.addWidget(vlbl)
            self.dpi_value_lbls.append(vlbl)

            c_lay.addStretch()

            # Bottom LED Color Swatch Button
            cbtn = QPushButton(f"لون اللمبة ({DPI_COLOR_NAMES_AR[i]})")
            cbtn.setFixedWidth(155)
            cbtn.setFixedHeight(36)
            cbtn.clicked.connect(lambda checked=False, idx=i: self._pick_dpi_color(idx))
            c_lay.addWidget(cbtn)
            self.dpi_color_btns.append(cbtn)

            grid.addWidget(card, i // 2, i % 2)

        lay.addLayout(grid)
        lay.addStretch()
        return page

    def _create_perf_page(self) -> QWidget:
        """ONLY genuine GM80 Plus PAW3311 performance controls: Polling Rate & Debounce Time."""
        page = QWidget()
        page.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(page)
        lay.setSpacing(18)

        # Polling Rate Card
        rate_card = QFrame()
        rate_card.setObjectName("GlassRow")
        r_lay = QVBoxLayout(rate_card)
        r_lay.setContentsMargins(20, 18, 20, 18)
        r_lay.setSpacing(12)

        t1_row = QHBoxLayout()
        self.lbl_rate_title = QLabel("⚡ معدل الاستجابة (Polling Rate)")
        self.lbl_rate_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #FFFFFF; background: transparent;")
        t1_row.addWidget(self.lbl_rate_title)
        t1_row.addStretch()

        self.btn_reset_perf = QPushButton("استعادة الإعداد الافتراضي (500Hz / 8ms)")
        self.btn_reset_perf.setObjectName("GlassBtn")
        self.btn_reset_perf.clicked.connect(self.restore_default_perf)
        t1_row.addWidget(self.btn_reset_perf)
        r_lay.addLayout(t1_row)

        self.lbl_rate_desc = QLabel("تردد إرسال بيانات الحركة للكمبيوتر — الافتراضي الموصى به 500 Hz لأفضل توازن بين الأداء وعمر البطارية:")
        self.lbl_rate_desc.setStyleSheet("font-size: 12px; color: #CBD5E1; background: transparent;")
        r_lay.addWidget(self.lbl_rate_desc)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)
        self.rate_buttons = {}
        for rate_name in ("125 Hz", "250 Hz", "500 Hz", "1000 Hz"):
            b = QPushButton(rate_name)
            b.setObjectName("RateBtn")
            b.setProperty("active", "false")
            b.clicked.connect(lambda checked=False, rn=rate_name: self._on_rate_selected(rn))
            btn_row.addWidget(b)
            self.rate_buttons[rate_name] = b
        r_lay.addLayout(btn_row)
        lay.addWidget(rate_card)

        # Debounce Time Card
        deb_card = QFrame()
        deb_card.setObjectName("GlassRow")
        d_lay = QVBoxLayout(deb_card)
        d_lay.setContentsMargins(20, 18, 20, 18)
        d_lay.setSpacing(12)

        self.lbl_deb_title = QLabel("⏱️ زمن منع الدبل كليك (Debounce Time)")
        self.lbl_deb_title.setStyleSheet("font-size: 17px; font-weight: bold; color: #FFFFFF; background: transparent;")
        self.lbl_deb_desc = QLabel("تعديل زمن استجابة مفاتيح الماوس بالمللي ثانية لمنع الدبل كليك الوهمي (الافتراضي: 8 ms):")
        self.lbl_deb_desc.setStyleSheet("font-size: 12px; color: #CBD5E1; background: transparent;")
        d_lay.addWidget(self.lbl_deb_title)
        d_lay.addWidget(self.lbl_deb_desc)

        sl_row = QHBoxLayout()
        sl_row.setSpacing(14)

        self.deb_slider = QSlider(Qt.Horizontal)
        self.deb_slider.setRange(1, 20)
        self.deb_slider.setValue(8)
        self.deb_slider.valueChanged.connect(self._on_debounce_changed)
        sl_row.addWidget(self.deb_slider, 1)

        self.lbl_deb_val = QLabel("8 ms")
        self.lbl_deb_val.setFixedWidth(85)
        self.lbl_deb_val.setAlignment(Qt.AlignCenter)
        self.lbl_deb_val.setStyleSheet("font-family: Consolas; font-size: 18px; font-weight: bold; color: #34D399; background: transparent;")
        sl_row.addWidget(self.lbl_deb_val)

        d_lay.addLayout(sl_row)
        lay.addWidget(deb_card)

        # Hardware Diagnostics / Conflict Cleanup Strip
        diag_card = QFrame()
        diag_card.setObjectName("GlassRow")
        dg_lay = QHBoxLayout(diag_card)
        dg_lay.setContentsMargins(18, 12, 18, 12)
        self.lbl_fw_info = QLabel("الفيرموير: جاري القراءة من الهاردوير...")
        self.lbl_fw_info.setStyleSheet("font-size: 12px; color: #CBD5E1; background: transparent;")
        dg_lay.addWidget(self.lbl_fw_info, 1)

        self.btn_kill_orig = QPushButton("إغلاق برنامج GamingMouse الأصلي (لمنع تعارض المنفذ)")
        self.btn_kill_orig.setObjectName("GlassBtn")
        self.btn_kill_orig.clicked.connect(self._kill_orig_manual)
        dg_lay.addWidget(self.btn_kill_orig)
        lay.addWidget(diag_card)

        lay.addStretch()
        return page

    def _create_buttons_page(self) -> QWidget:
        page = QWidget()
        page.setAttribute(Qt.WA_TranslucentBackground)
        lay = QVBoxLayout(page)
        lay.setSpacing(9)

        top = QHBoxLayout()
        self.lbl_btn_hdr = QLabel("تخصيص أزرار ماوس Aigo GM80 Plus الستة وحفظها مباشرة في ذاكرة الماوس (Bank 0 - CMD 0x09):")
        self.lbl_btn_hdr.setStyleSheet("font-size: 13px; font-weight: bold; color: #F1F5F9; background: transparent;")
        top.addWidget(self.lbl_btn_hdr)
        top.addStretch()

        self.btn_reset_btns = QPushButton("استعادة الأزرار الافتراضية")
        self.btn_reset_btns.setObjectName("GlassBtn")
        self.btn_reset_btns.clicked.connect(self.restore_default_buttons)
        top.addWidget(self.btn_reset_btns)
        lay.addLayout(top)

        button_titles = [
            "الزر 1 — الزر الأيسر (Left Click)",
            "الزر 2 — الزر الأيمن (Right Click)",
            "الزر 3 — زر البكرة الأوسط (Middle Click)",
            "الزر 4 — الزر الجانبي الخلفي (Backward)",
            "الزر 5 — الزر الجانبي الأمامي (Forward)",
            "الزر 6 — زر الـ DPI السفلي (DPI Button)",
        ]
        preset_names = [p[0] for p in BUTTON_PRESETS]
        self.btn_row_lbls = []
        self.btn_combos = []

        for idx, title in enumerate(button_titles):
            row = QFrame()
            row.setObjectName("GlassRow")
            r_lay = QHBoxLayout(row)
            r_lay.setContentsMargins(16, 10, 16, 10)

            l = QLabel(title)
            l.setStyleSheet("font-size: 13px; font-weight: bold; color: #FFFFFF; background: transparent;")
            r_lay.addWidget(l)
            self.btn_row_lbls.append(l)
            r_lay.addStretch()

            cmb = QComboBox()
            cmb.addItems(preset_names)
            cmb.setFixedWidth(300)
            cmb.currentIndexChanged.connect(lambda cidx, i=idx: self._on_button_combo_changed(i, cidx))
            r_lay.addWidget(cmb)
            self.btn_combos.append(cmb)

            lay.addWidget(row)

        lay.addStretch()
        return page

    # ---------------- Language Switch (AR / EN) & Auto Battery Poll Timer ----------------

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
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
        if self.lang == "en":
            self.lbl_status.setText(
                "🔋 Auto battery polling disabled (Manual Only)." if secs == 0
                else f"🔋 Auto battery polling interval set to: {lbl}."
            )
        else:
            self.lbl_status.setText(
                "🔋 تم إيقاف الفحص التلقائي للبطارية (يدوي فقط)." if secs == 0
                else f"🔋 تم ضبط الفحص التلقائي للبطارية: {lbl}."
            )

    def toggle_language(self):
        self.set_language("en" if self.lang == "ar" else "ar")

    def _apply_language(self):
        en = (self.lang == "en")

        # Window & Top Strip (4 clean buttons only)
        self.setWindowTitle(
            "Aigo GM80 Plus Control — Pro Control Center" if en
            else "Aigo GM80 Plus Control — مركز التحكم الاحترافي"
        )
        self.btn_settings.setText("⚙️ Settings" if en else "⚙️ الإعدادات")
        self.btn_eye.setText(("👁️ Show UI" if en else "👁️ إظهار الواجهة") if self.cards_hidden else "👁️")
        self.btn_eye.setToolTip(
            ("Show cards" if self.cards_hidden else "Hide cards to view full wallpaper") if en
            else ("إظهار الكروت" if self.cards_hidden else "إخفاء الكروت للاستمتاع بالخلفية")
        )
        self.btn_wp_next.setText("🖼️ Next Wallpaper" if en else "🖼️ خلفية تالية")
        self.btn_wp_pause.setText(
            ("▶ Resume Wallpaper" if self.slideshow_paused else "⏸ Pause Wallpaper") if en
            else ("▶ استئناف الخلفية" if self.slideshow_paused else "⏸ إيقاف الخلفية")
        )

        # Header & Battery Card Controls
        self.lbl_title.setText(
            "AIGO GM80 PLUS  •  Control Center" if en
            else "AIGO GM80 PLUS  •  مركز التحكم الحقيقي"
        )
        self.lbl_sub.setText(
            "YJX-CHIP  •  PAW3311 Sensor  •  Direct Onboard Memory Control" if en
            else "شريحة YJX-CHIP  •  سنسور PAW3311  •  تحكم مباشر بذاكرة الماوس الداخلية (Onboard Memory)"
        )
        self.btn_refresh_bat.setText("🔄 Refresh Now" if en else "🔄 تحديث الآن")

        # Navigation Tabs & Action Buttons
        tab_labels = (
            ["🎯 DPI Stages & Colors", "⚡ Polling Rate & Debounce", "🖱️ Button Remapping"] if en
            else ["🎯 درجات الـ DPI والألوان", "⚡ معدل الاستجابة و Debounce", "🖱️ برمجة الأزرار"]
        )
        for b, txt in zip(self.tab_buttons, tab_labels):
            b.setText(txt)
        self.btn_read_hw.setText("📥 Read from Mouse" if en else "📥 قراءة من الماوس")
        if self.btn_save_hw.isEnabled():
            self.btn_save_hw.setText("💾 Save to Onboard Memory" if en else "💾 حفظ وتطبيق في ذاكرة الماوس")

        # DPI Tab
        self.lbl_dpi_hdr.setText(
            "6 Fixed DPI Stages (800 to 12000 DPI) and bottom LED indicator colors:" if en
            else "درجات الـ DPI الستة الثابتة (800 إلى 12000 DPI) وتخصيص ألوان اللمبة السفلية:"
        )
        self.btn_reset_dpi.setText("Restore Catalog Defaults" if en else "استعادة درجات وألوان الكتالوج")
        color_names = DPI_COLOR_NAMES_EN if en else DPI_COLOR_NAMES_AR
        for i in range(6):
            self.dpi_radios[i].setText(f"Stage {i + 1}" if en else f"الدرجة {i + 1}")
            self.dpi_color_btns[i].setText(
                f"LED ({color_names[i]})" if en else f"لون اللمبة ({color_names[i]})"
            )

        # Performance Tab
        self.lbl_rate_title.setText("⚡ Polling Rate" if en else "⚡ معدل الاستجابة (Polling Rate)")
        self.btn_reset_perf.setText(
            "Restore Default (500Hz / 8ms)" if en else "استعادة الإعداد الافتراضي (500Hz / 8ms)"
        )
        self.lbl_rate_desc.setText(
            "USB/2.4G report rate — 500 Hz recommended for optimal balance of speed and battery life:" if en
            else "تردد إرسال بيانات الحركة للكمبيوتر — الافتراضي الموصى به 500 Hz لأفضل توازن بين الأداء وعمر البطارية:"
        )
        self.lbl_deb_title.setText("⏱️ Debounce Time" if en else "⏱️ زمن منع الدبل كليك (Debounce Time)")
        self.lbl_deb_desc.setText(
            "Adjust switch debounce delay in milliseconds to prevent unintended double-clicks (Default: 8 ms):" if en
            else "تعديل زمن استجابة مفاتيح الماوس بالمللي ثانية لمنع الدبل كليك الوهمي (الافتراضي: 8 ms):"
        )
        self.btn_kill_orig.setText(
            "Close Official GamingMouse App (Prevent HID Conflict)" if en
            else "إغلاق برنامج GamingMouse الأصلي (لمنع تعارض المنفذ)"
        )

        # Buttons Tab
        self.lbl_btn_hdr.setText(
            "Customize all 6 Aigo GM80 Plus buttons and save directly to onboard flash (Bank 0 - CMD 0x09):" if en
            else "تخصيص أزرار ماوس Aigo GM80 Plus الستة وحفظها مباشرة في ذاكرة الماوس (Bank 0 - CMD 0x09):"
        )
        self.btn_reset_btns.setText("Restore Default Buttons" if en else "استعادة الأزرار الافتراضية")

        btn_titles = (
            [
                "Button 1 — Left Click",
                "Button 2 — Right Click",
                "Button 3 — Middle Click (Scroll)",
                "Button 4 — Side Back (Backward)",
                "Button 5 — Side Forward (Forward)",
                "Button 6 — Bottom DPI Button",
            ] if en else [
                "الزر 1 — الزر الأيسر (Left Click)",
                "الزر 2 — الزر الأيمن (Right Click)",
                "الزر 3 — زر البكرة الأوسط (Middle Click)",
                "الزر 4 — الزر الجانبي الخلفي (Backward)",
                "الزر 5 — الزر الجانبي الأمامي (Forward)",
                "الزر 6 — زر الـ DPI السفلي (DPI Button)",
            ]
        )
        preset_items = BUTTON_PRESETS_EN if en else [p[0] for p in BUTTON_PRESETS]
        for idx in range(6):
            self.btn_row_lbls[idx].setText(btn_titles[idx])
            cmb = self.btn_combos[idx]
            cur_idx = BUTTON_INDEX_BY_CODE.get(self.driver.button_codes[idx], idx)
            cmb.blockSignals(True)
            cmb.clear()
            cmb.addItems(preset_items)
            cmb.setCurrentIndex(cur_idx)
            cmb.blockSignals(False)

        # Tray Menu
        self.act_open.setText("Open Control Center (Aigo GM80 Plus)" if en else "فتح مركز التحكم (Aigo GM80 Plus)")
        self.act_poll.setText("Refresh Battery & Status Now" if en else "تحديث البطارية والحالة الآن")
        self.act_quit.setText("Exit Application" if en else "إغلاق البرنامج نهائياً")

        # Refresh dynamic headers, firmware line, status, and tray tooltip
        fw_txt = self.driver.firmware_info or ("Unread" if en else "غير مقروء")
        self.lbl_fw_info.setText(
            f"Firmware: {fw_txt}  |  Serial: {self.driver.serial_number or 'N/A'}" if en
            else f"الفيرموير: {fw_txt}  |  السيريال: {self.driver.serial_number or 'N/A'}"
        )
        self._update_battery_header()
        self._refresh_tray()
        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #E2E8F0; background: transparent;")
        self.lbl_status.setText(
            "Ready — Direct YJX-CHIP hardware connection (0x55 -> ACK 0xAA)." if en
            else "جاهز — الاتصال المباشر بالماوس عبر بروتوكول YJX-CHIP (0x55 -> ACK 0xAA)."
        )

    # ---------------- UI State Sync & Event Handlers ----------------

    def switch_tab(self, idx: int):
        self.stack.setCurrentIndex(idx)
        for i, b in enumerate(self.tab_buttons):
            b.setProperty("active", "true" if i == idx else "false")
            b.style().unpolish(b)
            b.style().polish(b)

    def _style_color_btn(self, idx: int):
        hx = self.driver.dpi_colors[idx].upper()
        txt_col = "#000000" if hx in ("#00FF00", "#FFFF00", "#00FFFF", "#FFFFFF") else "#FFFFFF"
        self.dpi_color_btns[idx].setStyleSheet(
            f"background-color: {hx}; color: {txt_col}; border: 2px solid rgba(255,255,255,190); "
            f"border-radius: 9px; font-weight: bold; font-size: 12px;"
        )

    def _sync_ui_from_driver(self):
        en = (self.lang == "en")
        # DPI stage & fixed labels (no sliders)
        self.dpi_radios[self.driver.active_dpi_stage].setChecked(True)
        for i in range(6):
            self.dpi_value_lbls[i].setText(f"{self.driver.dpi_values[i]} DPI")
            self._style_color_btn(i)

        # Polling rate buttons
        for rn, b in self.rate_buttons.items():
            b.setProperty("active", "true" if rn == self.driver.polling_rate else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        # Debounce slider
        self.deb_slider.blockSignals(True)
        self.deb_slider.setValue(self.driver.debounce_ms)
        self.deb_slider.blockSignals(False)
        self.lbl_deb_val.setText(f"{self.driver.debounce_ms} ms")

        # Button combos (index-mapped by 4-byte hardware code -> works in both AR & EN!)
        for i in range(6):
            code = self.driver.button_codes[i]
            pos = BUTTON_INDEX_BY_CODE.get(code, i)
            self.btn_combos[i].blockSignals(True)
            if 0 <= pos < self.btn_combos[i].count():
                self.btn_combos[i].setCurrentIndex(pos)
            self.btn_combos[i].blockSignals(False)

        fw_txt = self.driver.firmware_info or ("Unread" if en else "غير مقروء")
        self.lbl_fw_info.setText(
            f"Firmware: {fw_txt}  |  Serial: {self.driver.serial_number or 'N/A'}" if en
            else f"الفيرموير: {fw_txt}  |  السيريال: {self.driver.serial_number or 'N/A'}"
        )
        self._update_battery_header()

    def _on_dpi_stage_selected(self, idx: int):
        self.driver.active_dpi_stage = idx
        if self.lang == "en":
            self.lbl_status.setText(f"Selected Stage {idx + 1} ({self.driver.dpi_values[idx]} DPI) — Click 'Save to Onboard Memory' to apply immediately.")
        else:
            self.lbl_status.setText(f"تم اختيار الدرجة {idx + 1} ({self.driver.dpi_values[idx]} DPI) — اضغط «حفظ وتطبيق» لتغيير اللمبة والسرعة فوراً.")

    def _pick_dpi_color(self, idx: int):
        title = f"Pick LED Color for Stage {idx + 1}" if self.lang == "en" else f"اختر لون الدرجة {idx + 1}"
        col = QColorDialog.getColor(QColor(self.driver.dpi_colors[idx]), self, title)
        if col.isValid():
            self.driver.dpi_colors[idx] = col.name().upper()
            self._style_color_btn(idx)

    def restore_default_dpis(self):
        self.driver.dpi_values = list(DEFAULT_DPI_VALUES)
        self.driver.dpi_colors = list(DEFAULT_DPI_COLORS)
        self.driver.active_dpi_stage = 2
        self._sync_ui_from_driver()
        self.lbl_status.setText(
            "Restoring factory DPI stages & colors to mouse onboard memory..." if self.lang == "en"
            else "جاري استعادة درجات وألوان الكتالوج الرسمية وحفظها في ذاكرة الماوس..."
        )
        self.trigger_apply_to_hardware()

    def restore_default_perf(self):
        """Restore Polling Rate to 500 Hz and Debounce Time to 8 ms and commit immediately to mouse onboard memory."""
        self.driver.polling_rate = "500 Hz"
        self.driver.debounce_ms = 8
        self._sync_ui_from_driver()
        self.lbl_status.setText(
            "Restoring default settings (500Hz / 8ms) to mouse onboard memory..." if self.lang == "en"
            else "جاري استعادة الإعداد الافتراضي (500Hz / 8ms) وحفظه في ذاكرة الماوس..."
        )
        self.trigger_apply_to_hardware()

    def _on_rate_selected(self, rate_name: str):
        self.driver.polling_rate = rate_name
        for rn, b in self.rate_buttons.items():
            b.setProperty("active", "true" if rn == rate_name else "false")
            b.style().unpolish(b)
            b.style().polish(b)

        if self.driver.is_bluetooth and not self.driver.wired_path and not self.driver.wireless_path:
            bt_warn = (
                "Changing polling rate requires USB or 2.4G Dongle (Bluetooth runs at 125Hz)" if self.lang == "en"
                else "تعديل معدل الاستجابة يتطلب توصيل السلك أو الدونجل 2.4G (البلوتوث يعمل على 125Hz)"
            )
            self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #FBBF24; background: transparent;")
            self.lbl_status.setText("⚠️ " + bt_warn)
            return

        self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
        self.lbl_status.setText(
            f"Applying {rate_name} polling rate to mouse onboard memory (CMD 0x23 + 0x0F)..." if self.lang == "en"
            else f"جاري تطبيق معدل الاستجابة {rate_name} وحفظه في ذاكرة الماوس (CMD 0x23 + 0x0F)..."
        )
        threading.Thread(target=self._apply_rate_worker, daemon=True).start()

    def _apply_rate_worker(self):
        ok, msg = self.driver.apply_polling_rate_to_hardware()
        self.signals.apply_done.emit(ok, msg)

    def _on_debounce_changed(self, val: int):
        self.driver.debounce_ms = val
        self.lbl_deb_val.setText(f"{val} ms")

    def _on_button_combo_changed(self, idx: int, combo_idx: int):
        if not (0 <= combo_idx < len(BUTTON_PRESETS)):
            return
        if idx == 0 and combo_idx != 0:
            en = (self.lang == "en")
            ans = QMessageBox.question(
                self,
                "Left Click Warning" if en else "تحذير الزر الأيسر",
                (
                    "Remapping Left Click may prevent normal clicking. Continue?" if en
                    else "تغيير وظيفة الزر الأيسر قد يمنعك من النقر العادي. هل تريد المتابعة؟"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans != QMessageBox.Yes:
                self.btn_combos[0].blockSignals(True)
                self.btn_combos[0].setCurrentIndex(0)
                self.btn_combos[0].blockSignals(False)
                return
        self.driver.button_codes[idx] = BUTTON_PRESETS[combo_idx][1]

    def restore_default_buttons(self):
        """
        Reset all 6 button dropdowns to factory defaults (Left, Right, Middle, Backward, Forward, DPI Loop)
        AND immediately write the factory button packet (0x42b870 CMD 0x09 + CMD 0x0F) to onboard flash memory
        with CMD 0x08 / 0x0E readback verification!
        """
        en = (self.lang == "en")
        self.driver.button_codes = list(DEFAULT_BUTTON_CODES)
        self._sync_ui_from_driver()
        self.btn_save_hw.setEnabled(False)
        self.btn_save_hw.setText("Restoring factory buttons..." if en else "جاري استعادة أزرار المصنع في الماوس...")
        self.lbl_status.setText(
            "Sending factory default button packet (CMD 0x09 + CMD 0x0F) to onboard memory..." if en
            else "جاري إرسال حزمة استعادة الأزرار الافتراضية (CMD 0x09 + CMD 0x0F) إلى ذاكرة الماوس..."
        )
        threading.Thread(target=self._reset_buttons_worker, daemon=True).start()

    def _reset_buttons_worker(self):
        ok, msg = self.driver.reset_factory_buttons_on_hardware()
        self.signals.apply_done.emit(ok, msg)

    # ---------------- Hardware Async Operations ----------------

    def _check_driver_conflict(self):
        procs = detect_conflicting_processes()
        if procs:
            en = (self.lang == "en")
            ans = QMessageBox.question(
                self,
                "USB HID Port Conflict" if en else "تعارض في منفذ USB HID",
                (
                    f"The official mouse driver ({', '.join(procs)}) is running and may conflict with the HID port.\nClose it now?" if en
                    else f"برنامج الماوس الأصلي ({', '.join(procs)}) يعمل حالياً وقد يتعارض مع منفذ الـ HID.\nهل تريد إغلاقه الآن؟"
                ),
                QMessageBox.Yes | QMessageBox.No,
            )
            if ans == QMessageBox.Yes:
                close_conflicting_processes()

    def _kill_orig_manual(self):
        close_conflicting_processes()
        self.lbl_status.setText(
            "Verified that any running DeviceDriver.exe / GamingMS.exe instance is closed." if self.lang == "en"
            else "تم التأكد من إغلاق أي نسخة من DeviceDriver.exe / GamingMS.exe."
        )

    def _trigger_initial_hw_read(self):
        self.lbl_status.setText(
            "Reading live settings from mouse onboard memory (CMD 0x0E + 0x08)..." if self.lang == "en"
            else "جاري قراءة الإعدادات الفعلية من ذاكرة الماوس الداخلية (CMD 0x0E + 0x08)..."
        )
        threading.Thread(target=self._init_read_worker, daemon=True).start()

    def _init_read_worker(self):
        ok, msg = self.driver.read_hardware_state()
        self.signals.init_read_done.emit(ok, msg)

    def _on_init_read_done(self, ok: bool, msg: str):
        self._sync_ui_from_driver()
        col = "#34D399" if ok else "#FBBF24"
        self.lbl_status.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {col}; background: transparent;")
        self.lbl_status.setText(msg)
        self._refresh_tray()

    def trigger_battery_poll(self, manual: bool = False):
        if manual:
            self._manual_poll_pending = True
            self.btn_refresh_bat.setEnabled(False)
            self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #38BDF8; background: transparent;")
            self.lbl_status.setText(
                "🔄 Querying live battery telemetry from mouse hardware (CMD 0x30)..." if self.lang == "en"
                else "🔄 جاري فحص البطارية مباشرة من الهاردوير (CMD 0x30)..."
            )
        threading.Thread(target=self._poll_worker, daemon=True).start()

    def _poll_worker(self):
        ok, msg = self.driver.poll_battery_status()
        self.signals.poll_done.emit(ok, msg)

    def _on_poll_done(self, ok: bool, msg: str):
        self.btn_refresh_bat.setEnabled(True)
        self._update_battery_header()
        self._refresh_tray()
        if self._manual_poll_pending or self.driver.battery_percent is not None or self.driver.battery_sleeping:
            self._manual_poll_pending = False
            col = "#34D399" if ok else "#FBBF24"
            self.lbl_status.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {col}; background: transparent;")
            self.lbl_status.setText(msg)
        if (
            self.driver.battery_percent is not None
            and self.driver.battery_percent < 20
            and not self.driver.is_wired
            and not self.driver.low_battery_warned
        ):
            self.driver.low_battery_warned = True
            en = (self.lang == "en")
            self.tray.showMessage(
                "Aigo GM80 Plus Low Battery" if en else "تنبيه بطارية Aigo GM80 Plus",
                (
                    f"Mouse battery is low ({self.driver.battery_percent}% / {self.driver.battery_voltage:.2f}V) — Please connect charger." if en
                    else f"شحن الماوس منخفض ({self.driver.battery_percent}% / {self.driver.battery_voltage:.2f}V) — يرجى توصيل الشاحن."
                ),
                QSystemTrayIcon.Warning,
                5000,
            )

    def _set_battery_bar_style(self, chunk_css: str):
        self.bat_progress.setStyleSheet(
            "QProgressBar { background-color: rgba(15, 23, 42, 165); "
            "border: 1px solid rgba(148, 197, 255, 75); border-radius: 7px; padding: 1px; }"
            f"QProgressBar::chunk {{ background: {chunk_css}; border-radius: 5px; }}"
        )

    def _set_battery_badge(self, text: str, fg: str, bg_rgba: str, border_rgba: str):
        self.lbl_bat_badge.setText(text)
        self.lbl_bat_badge.setStyleSheet(
            f"font-size: 11px; font-weight: bold; color: {fg}; "
            f"background: {bg_rgba}; border: 1px solid {border_rgba}; "
            f"border-radius: 7px; padding: 2px 8px;"
        )

    def _update_battery_header(self):
        en = (self.lang == "en")

        # 1. Clean concise connection line with glowing status dot (no VID/PID clutter)
        if not self.driver.connected:
            dot_col = "#F87171"
            conn_txt = "Disconnected" if en else "غير متصل"
        elif self.driver.is_bluetooth:
            dot_col = "#60A5FA"
            conn_txt = "Bluetooth • BT" if en else "متصل بلوتوث • BT"
        elif self.driver.is_wired and self.driver.is_wireless:
            dot_col = "#38BDF8"
            conn_txt = "Wired + 2.4G • USB-C" if en else "متصل سلكياً + 2.4G • USB-C"
        elif self.driver.is_wired:
            dot_col = "#38BDF8"
            conn_txt = "Wired • USB-C" if en else "متصل سلكياً • USB-C"
        else:
            dot_col = "#34D399"
            conn_txt = "Wireless • 2.4G" if en else "متصل وايرلس • 2.4G"

        self.lbl_conn_dot.setStyleSheet(f"font-size: 11px; color: {dot_col}; background: transparent;")
        self.lbl_conn.setText(conn_txt)
        self.lbl_conn.setStyleSheet(f"font-size: 12px; font-weight: bold; color: #F1F5F9; background: transparent;")

        # 2. Modern Battery Progress Bar + Crisp Percentage + Status Badge (no voltage/duplicate icon clutter)
        if not self.driver.connected:
            self.bat_progress.setValue(0)
            self._set_battery_bar_style("#475569")
            self.lbl_bat_pct.setText("--%")
            self.lbl_bat_pct.setStyleSheet("font-family: Consolas; font-size: 20px; font-weight: bold; color: #94A3B8; background: transparent;")
            self._set_battery_badge("Offline" if en else "غير متصل", "#94A3B8", "rgba(148,163,184,25)", "rgba(148,163,184,90)")
        elif self.driver.battery_percent is not None:
            pct = max(0, min(100, int(self.driver.battery_percent)))
            self.bat_progress.setValue(pct)
            is_chg = bool(self.driver.battery_charging)
            if is_chg:
                bar_css = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #38BDF8, stop:1 #10B981)"
                num_col = "#38BDF8"
                self._set_battery_badge(
                    "⚡ Charging" if en else "⚡ يشحن",
                    "#38BDF8", "rgba(56,189,248,30)", "rgba(56,189,248,130)"
                )
            elif pct > 40:
                bar_css = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10B981, stop:1 #34D399)"
                num_col = "#34D399"
                self._set_battery_badge(
                    "Discharging" if en else "تفريغ",
                    "#34D399", "rgba(16,185,129,28)", "rgba(52,211,153,115)"
                )
            elif pct > 20:
                bar_css = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #F59E0B, stop:1 #FBBF24)"
                num_col = "#FBBF24"
                self._set_battery_badge(
                    "Discharging" if en else "تفريغ",
                    "#FBBF24", "rgba(245,158,11,28)", "rgba(251,191,36,125)"
                )
            else:
                bar_css = "qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #DC2626, stop:1 #F87171)"
                num_col = "#F87171"
                self._set_battery_badge(
                    "Low" if en else "منخفض",
                    "#F87171", "rgba(239,68,68,32)", "rgba(248,113,113,135)"
                )
            self._set_battery_bar_style(bar_css)
            self.lbl_bat_pct.setText(f"{pct}%")
            self.lbl_bat_pct.setStyleSheet(f"font-family: Consolas; font-size: 20px; font-weight: bold; color: {num_col}; background: transparent;")
        elif self.driver.battery_sleeping:
            self.bat_progress.setValue(0)
            self._set_battery_bar_style("#F59E0B")
            self.lbl_bat_pct.setText("--%")
            self.lbl_bat_pct.setStyleSheet("font-family: Consolas; font-size: 20px; font-weight: bold; color: #FBBF24; background: transparent;")
            self._set_battery_badge("Sleep" if en else "سكون", "#FBBF24", "rgba(245,158,11,28)", "rgba(251,191,36,120)")
        elif self.driver.is_wired:
            self.bat_progress.setValue(100)
            self._set_battery_bar_style("qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2563EB, stop:1 #38BDF8)")
            self.lbl_bat_pct.setText("⚡")
            self.lbl_bat_pct.setStyleSheet("font-size: 19px; font-weight: bold; color: #38BDF8; background: transparent;")
            self._set_battery_badge("⚡ Charging" if en else "⚡ يشحن", "#38BDF8", "rgba(56,189,248,30)", "rgba(56,189,248,130)")
        else:
            self.bat_progress.setValue(0)
            self._set_battery_bar_style("#64748B")
            self.lbl_bat_pct.setText("--%")
            self.lbl_bat_pct.setStyleSheet("font-family: Consolas; font-size: 20px; font-weight: bold; color: #94A3B8; background: transparent;")
            self._set_battery_badge("Waiting" if en else "بانتظار الرد", "#94A3B8", "rgba(148,163,184,25)", "rgba(148,163,184,90)")

        # 3. Clean subtle bottom timestamp ONLY
        last_str = self.driver.last_poll_str or "--:--:--"
        self.lbl_poll_time.setText(f"Last updated: {last_str}" if en else f"آخر تحديث: {last_str}")

    def trigger_apply_to_hardware(self):
        en = (self.lang == "en")
        if self.driver.is_bluetooth and not self.driver.wired_path and not self.driver.wireless_path:
            bt_warn = (
                "Changing settings requires USB or 2.4G Dongle (Bluetooth runs saved onboard profile at 125Hz)" if en
                else "تعديل الإعدادات يتطلب توصيل السلك أو الدونجل 2.4G (البلوتوث يعمل بالإعدادات المحفوظة مسبقاً على 125Hz)"
            )
            self.lbl_status.setStyleSheet("font-size: 12px; font-weight: bold; color: #FBBF24; background: transparent;")
            self.lbl_status.setText("⚠️ " + bt_warn)
            QMessageBox.information(self, "Bluetooth Mode (125Hz)" if en else "وضع البلوتوث (Bluetooth - 125Hz)", bt_warn)
            return
        self.btn_save_hw.setEnabled(False)
        self.btn_save_hw.setText("Writing to onboard memory..." if en else "جاري الكتابة في ذاكرة الماوس...")
        threading.Thread(target=self._apply_worker, daemon=True).start()

    def _apply_worker(self):
        ok, msg = self.driver.apply_to_hardware(apply_buttons=True)
        self.signals.apply_done.emit(ok, msg)

    def _on_apply_done(self, ok: bool, msg: str):
        self.btn_save_hw.setEnabled(True)
        self.btn_save_hw.setText(
            "💾 Save to Onboard Memory" if self.lang == "en" else "💾 حفظ وتطبيق في ذاكرة الماوس"
        )
        col = "#34D399" if ok else "#F87171"
        self.lbl_status.setStyleSheet(f"font-size: 12px; font-weight: bold; color: {col}; background: transparent;")
        self.lbl_status.setText(msg)
        self._update_battery_header()
        self._refresh_tray()

    # ---------------- System Tray Integration ----------------

    def _setup_tray(self):
        ico_p = get_active_icon_path(self.settings.get("custom_icon", ""))
        self.tray = QSystemTrayIcon(build_tray_qicon(self.driver, ico_p), self)
        menu = QMenu()
        self.act_open = QAction("فتح مركز التحكم (Aigo GM80 Plus)", self)
        self.act_open.triggered.connect(self.restore_from_tray)
        self.act_poll = QAction("تحديث البطارية والحالة الآن", self)
        self.act_poll.triggered.connect(lambda: self.trigger_battery_poll(manual=True))
        self.act_quit = QAction("إغلاق البرنامج نهائياً", self)
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
        en = (self.lang == "en")
        ico_p = get_active_icon_path(self.settings.get("custom_icon", ""))
        self.tray.setIcon(build_tray_qicon(self.driver, ico_p))
        if not self.driver.connected:
            tip = "Aigo GM80 Plus — Disconnected" if en else "Aigo GM80 Plus — غير متصل"
        elif self.driver.battery_percent is not None:
            bat_lbl = "Battery" if en else "الشحن"
            tip = f"Aigo GM80 Plus — {bat_lbl}: {self.driver.battery_percent}% ({self.driver.battery_voltage:.2f}V) | {self.driver.dpi_values[self.driver.active_dpi_stage]} DPI @ {self.driver.polling_rate}"
        else:
            mode = "USB Wired" if self.driver.is_wired else ("Bluetooth" if self.driver.is_bluetooth else "2.4G Wireless")
            tip = f"Aigo GM80 Plus ({mode}) | {self.driver.dpi_values[self.driver.active_dpi_stage]} DPI @ {self.driver.polling_rate}"
        self.tray.setToolTip(tip)

    def _on_tray_activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.restore_from_tray()

    def hide_to_tray(self):
        self.hide()
        interval_lbl = self._current_interval_label()
        if self.lang == "en":
            body = f"Running in the system tray (Battery polling: {interval_lbl})."
        else:
            body = f"البرنامج يعمل في الخلفية جنب الساعة (فحص البطارية: {interval_lbl})."
        self.tray.showMessage("Aigo GM80 Plus Control", body, QSystemTrayIcon.Information, 2500)

    def restore_from_tray(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowMinimized) | Qt.WindowActive)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            ctypes.windll.user32.SetForegroundWindow(int(self.winId()))
        except Exception:
            pass

    def closeEvent(self, event):
        if self.run_in_background:
            event.ignore()
            self.hide_to_tray()
        else:
            event.accept()
            self.quit_app()

    def quit_app(self):
        for t in (self.slideshow_timer, self.fade_timer, self.battery_timer, self.hotplug_timer):
            try:
                t.stop()
            except Exception:
                pass
        try:
            self.tray.hide()
            self.tray.deleteLater()
        except Exception:
            pass
        QApplication.instance().quit()


# ============================================================================
# ENTRY POINT
# ============================================================================
if __name__ == "__main__":
    drv = YJXGM80PlusDriver()

    if "--verify-hw" in sys.argv:
        ok_r, msg_r = drv.read_hardware_state()
        print("READ HW :", ok_r, "|", msg_r)
        ok_b, msg_b = drv.poll_battery_status()
        print("BATTERY :", ok_b, "|", msg_b)
        ok_w, msg_w = drv.apply_to_hardware(apply_buttons=True)
        print("WRITE HW:", ok_w, "|", msg_w)
        sys.exit(0 if (ok_r and ok_w) else 1)

    _single_mutex = acquire_single_instance_or_activate()
    if _single_mutex is None:
        sys.exit(0)

    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        win = GM80PlusGlassWindow(drv)
        win.show()
        sys.exit(app.exec())
    finally:
        try:
            ctypes.windll.kernel32.CloseHandle(_single_mutex)
        except Exception:
            pass
