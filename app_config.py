"""
System Health Monitor
==================
Module 0: app_config.py
Responsibility: Single source of truth for theme colours, fonts,
                file paths, and behavioural constants.

Public API
----------
pick_font(macos_name, fallbacks, size, *style) -> tuple
    Build a cross-platform Tk font tuple.  Previously named _pick_font
    (private); the old name is kept as an alias for backward compatibility.

bind_scroll(canvas, cmd)
    Cross-platform mouse-wheel scroll binding scoped to a canvas widget.

PATHS.set_app_dir(new_dir)
    Change the data folder at runtime; persists across restarts via
    ~/.system_health_monitor_dir.
"""

import os
import json
import platform
from pathlib import Path

# ─────────────────────────────────────────────
# Scroll helper  - USE THIS instead of bind_all
# ─────────────────────────────────────────────
def bind_scroll(canvas, scroll_cmd):
    """
    Bind two-finger / mouse-wheel scroll to *canvas* only while the
    cursor is inside it.  Works on macOS (delta) and Linux (Button-4/5).

    Parameters
    ----------
    canvas     : tk.Canvas to scroll
    scroll_cmd : callable(delta_units) - e.g. canvas.yview_scroll

    Usage
    -----
        bind_scroll(my_canvas,
                    lambda d: my_canvas.yview_scroll(d, "units"))
    """
    _system = platform.system()

    def _on_wheel(event):
        delta = event.delta
        if _system == "Windows":
            # Windows always sends delta in multiples of 120 (one notch = 120).
            units = -int(delta / 120)
        elif _system == "Darwin":
            # macOS trackpad: delta is ±1..±10 per notch.
            # External Windows-style USB mice send ±120 via macOS driver.
            if abs(delta) >= 120:
                units = -int(delta / 120)
            else:
                units = -(int(delta) or (1 if delta >= 0 else -1))
        else:
            # Linux X11: <MouseWheel> may not fire; Button-4/5 below covers it.
            units = -int(delta / 120) if abs(delta) >= 120 else (-(int(delta) or 1))
        scroll_cmd(units)

    def _on_btn4(_event):              # Linux scroll up
        scroll_cmd(-1)

    def _on_btn5(_event):              # Linux scroll down
        scroll_cmd(1)

    def _scroll_on(_event=None):
        canvas.bind("<MouseWheel>", _on_wheel)
        canvas.bind("<Button-4>",   _on_btn4)
        canvas.bind("<Button-5>",   _on_btn5)

    def _scroll_off(_event=None):
        canvas.unbind("<MouseWheel>")
        canvas.unbind("<Button-4>")
        canvas.unbind("<Button-5>")

    canvas.bind("<Enter>", _scroll_on)
    canvas.bind("<Leave>", _scroll_off)

    # Also activate when hovering over child widgets inside the canvas
    # (the content frame and its descendants don't forward Enter to canvas)
    def _bind_children(widget):
        try:
            widget.bind("<Enter>", _scroll_on)
            widget.bind("<Leave>", _scroll_off)
        except Exception:
            pass
        for child in widget.winfo_children():
            _bind_children(child)

    # Re-run after the canvas is fully rendered so all children exist
    canvas.after(200, lambda: _bind_children(canvas))




def pick_font(macos_name: str, fallbacks: tuple, size: int, *style) -> tuple:
    """
    Return a Tk-compatible font tuple.
    On macOS: prefer the native font (SF Pro / SF Mono).
    On other platforms: use the first fallback that Tkinter accepts.
    Tkinter silently falls back to its default when a font is missing,
    so listing the macOS name first on all platforms is safe but means
    macOS users always get the right typeface.
    """
    if platform.system() == "Darwin":
        name = macos_name
    else:
        # On Windows/Linux use the first cross-platform fallback
        name = fallbacks[0] if fallbacks else macos_name
    return (name, size) + style


# Backward-compatible private alias — existing callers of _pick_font still work.
_pick_font = pick_font


# ─────────────────────────────────────────────
# Theme
# ─────────────────────────────────────────────
class _Theme:
    """All colour and font constants.

    Fonts use a cross-platform strategy:
      macOS  → SF Pro Display / SF Pro Text / SF Mono
      Windows → Segoe UI / Consolas
      Linux  → DejaVu Sans / DejaVu Sans Mono (or whatever GTK provides)
    Tkinter silently substitutes its default when a name is unavailable,
    so the tuples are safe on every platform.
    """

    # Background layers
    BG_DARK    = "#0D0D0F"
    BG_PANEL   = "#141416"
    BG_CARD    = "#1A1A1D"
    BG_SIDEBAR = "#111113"

    # Highlight green (fixed)
    ACCENT     = "#30D158"
    ACCENT_DIM = "#1A4D2E"

    # Status
    WARN   = "#FF9F0A"
    DANGER = "#FF453A"
    BLUE   = "#0A84FF"

    # Text
    TEXT_PRIMARY   = "#F2F2F7"
    TEXT_SECONDARY = "#8E8E93"

    # Borders / rows
    BORDER      = "#2C2C2E"
    BORDER_CARD = "#3A3A3C"
    BG_ROW      = "#141416"
    BG_ROW_SEL  = "#1E2E22"
    BG_ROW_HOVER= "#1C1C1F"
    BG_LOG      = "#0D0D0F"
    BG_INPUT    = "#1A1A1D"

    # Fonts — cross-platform stacks
    # Display / UI headings
    FONT_SECTION    = pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 13, "bold")
    FONT_TITLE      = pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 12, "bold")
    FONT_BTN        = pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 11, "bold")
    # Body / detail text
    FONT_BODY       = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 11)
    FONT_BODY_BOLD  = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 11, "bold")
    FONT_DETAIL     = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 10)
    FONT_DETAIL_BOLD= pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 10, "bold")
    FONT_SMALL      = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"),  9)
    FONT_ICON       = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 15)
    FONT_LABEL      = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 12)
    FONT_STAT       = pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 18, "bold")
    FONT_DISPLAY    = pick_font("SF Pro Text",    ("Segoe UI", "Helvetica Neue", "Arial"), 36)
    FONT_PERCENT    = pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 32, "bold")
    # Monospace
    FONT_MONO       = pick_font("SF Mono",        ("Consolas", "Menlo", "Courier New"),     9)

THEME = _Theme()


# ─────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────
# Pointer file - stores user's chosen data folder between sessions
_POINTER_FILE = Path.home() / ".system_health_monitor_dir"


def _read_app_dir() -> Path:
    """
    Read the user-selected data directory.
    First launch (no pointer file): use the directory app_config.py
    lives in - i.e. wherever the user installed the app.
    Subsequent launches: use the saved pointer file, but validate it
    still exists on disk. If the stored path is missing (e.g. an
    external drive was disconnected), fall back to install_dir so the
    first write never hits a confusing FileNotFoundError.
    """
    install_dir = Path(__file__).resolve().parent
    try:
        if _POINTER_FILE.exists():
            stored = _POINTER_FILE.read_text().strip()
            if stored:
                candidate = Path(stored)
                if candidate.exists():
                    return candidate
                # Stored path no longer exists - silently discard it
    except Exception:
        pass
    return install_dir


class _Paths:
    """
    All file/directory paths.

    set_app_dir(new_dir) persists the choice and recalculates sub-paths.
    """

    def __init__(self):
        self._app_dir = _read_app_dir()
        self._dir_change_callbacks = []
        # Eagerly calculate all paths so typos raise AttributeError
        # immediately rather than silently falling into __getattr__.
        self._calc()

    def _calc(self):
        d = self._app_dir
        self.APP_DIR      = d
        self.SETTINGS_FILE= d / "settings.json"
        self.HISTORY_FILE = d / "history.txt"
        self.SCHEDULE_FILE= d / "schedule_config.json"
        self.LOGS_DIR     = d / "logs"

    @property
    def APP_DIR(self) -> Path:
        return self._app_dir

    @APP_DIR.setter
    def APP_DIR(self, value):
        self._app_dir = Path(value)

    def set_app_dir(self, new_dir: str):
        """
        Change the data folder.  Creates it if needed, saves the pointer
        file so it persists across restarts.  Notifies all callbacks.
        """
        p = Path(new_dir)
        p.mkdir(parents=True, exist_ok=True)
        self._app_dir = p
        self._calc()
        try:
            _POINTER_FILE.write_text(str(p))
        except Exception:
            pass
        for cb in self._dir_change_callbacks:
            try:
                cb(p)
            except Exception:
                pass

    def on_dir_change(self, callback):
        """Register a function(new_path) called when the data dir changes."""
        self._dir_change_callbacks.append(callback)


PATHS = _Paths()


# ─────────────────────────────────────────────
# Platform-aware path helpers
# ─────────────────────────────────────────────


def _platform_cache_root() -> Path:
    """Return the OS-specific user cache directory."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Caches"
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data)
        return Path.home() / "AppData" / "Local"
    # Linux / other POSIX
    xdg = os.environ.get("XDG_CACHE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".cache"


def _platform_log_root() -> Path:
    """Return the OS-specific user log directory."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / "Library" / "Logs"
    if system == "Windows":
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "Logs"
        return Path.home() / "AppData" / "Local" / "Logs"
    # Linux / other POSIX
    xdg = os.environ.get("XDG_STATE_HOME")
    if xdg:
        return Path(xdg)
    return Path.home() / ".local" / "share" / "logs"


def _platform_trash() -> Path:
    """Return the OS-specific trash / recycle bin directory."""
    system = platform.system()
    if system == "Darwin":
        return Path.home() / ".Trash"
    if system == "Windows":
        # Windows Recycle Bin is not a simple directory; return None
        # so cleanup.py can gate its trash logic per-platform.
        return None
    # Linux (freedesktop)
    xdg_data = os.environ.get("XDG_DATA_HOME")
    base = Path(xdg_data) if xdg_data else Path.home() / ".local" / "share"
    return base / "Trash" / "files"


def _platform_downloads() -> Path:
    """Return the OS-specific Downloads directory."""
    # ~/Downloads is the standard on macOS, Linux, and Windows
    # (Windows resolves Path.home() to %USERPROFILE% which contains Downloads).
    # Using this helper keeps all OS-path decisions in one place.
    return Path.home() / "Downloads"


# ─────────────────────────────────────────────
# Behavioural Constants
# ─────────────────────────────────────────────
class _Constants:
    DOWNLOADS_AGE_DAYS   = 30
    LOG_AGE_DAYS         = 7
    MAX_HISTORY_RECORDS  = 100
    MAX_LOG_LINES        = 2000
    DASHBOARD_REFRESH_MS = 10_000

    # Platform-aware cache sub-paths
    # On macOS these are bundle-ID subdirs under ~/Library/Caches.
    # On Windows/Linux they are subdirs under the platform cache root.
    @staticmethod
    def cache_subdirs() -> list:
        """Return cache subdirectory names for the current platform."""
        system = platform.system()
        if system == "Darwin":
            return [
                "com.apple.Safari",
                "com.google.Chrome",
                "com.apple.dt.Xcode",
                "com.spotify.client",
                "com.apple.Music",
                "CloudKit",
                "com.apple.bird",
            ]
        if system == "Windows":
            return [
                "Google\\Chrome\\User Data\\Default\\Cache",
                "Mozilla\\Firefox\\Profiles",
            ]
        # Linux / other POSIX
        return [
            "google-chrome",
            "chromium",
            "mozilla",
            "spotify",
        ]

    @property
    def CACHE_SUBDIRS(self) -> list:  # type: ignore[override]
        """
        Property so CONSTANTS.CACHE_SUBDIRS always reflects the live platform.
        Replaces the old class-attribute approach (which used a fragile
        __func__() call evaluated once at import time).
        """
        return self.cache_subdirs()


CONSTANTS = _Constants()


# ─────────────────────────────────────────────
# App Metadata
# ─────────────────────────────────────────────
class _Meta:
    VERSION   = "0.1.0"
    NAME      = "System Health Monitor"
    BUNDLE_ID = "com.systemhealth.monitor"


META = _Meta()
