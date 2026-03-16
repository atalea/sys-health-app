"""
System Health Monitor
==================
Module 1: main.py
Responsibility: Application entry point, root window, layout scaffold,
                sidebar navigation, and frame management.

All other modules will drop their widgets into the frames created here.
"""

import tkinter as tk
from tkinter import ttk
import sys
import os
from app_config import THEME, PATHS, META

# ─────────────────────────────────────────────
# CONSTANTS - sourced from app_config
# ─────────────────────────────────────────────
BG_DARK        = THEME.BG_DARK
BG_PANEL       = THEME.BG_PANEL
BG_SIDEBAR     = THEME.BG_SIDEBAR
ACCENT         = THEME.ACCENT
ACCENT_DIM     = THEME.ACCENT_DIM
TEXT_PRIMARY   = THEME.TEXT_PRIMARY
TEXT_SECONDARY = THEME.TEXT_SECONDARY
BORDER         = THEME.BORDER

# Item 5 fix: use THEME.FONT_TITLE instead of a local redefinition.
# THEME.FONT_TITLE already has the correct cross-platform font stack.
FONT_TITLE   = THEME.FONT_TITLE         # was: ("SF Pro Display", 18, "bold")
FONT_NAV     = THEME.FONT_SMALL
FONT_NAV_SEL = THEME.FONT_BODY_BOLD   # use dedicated bold variant from _Theme
FONT_SMALL   = THEME.FONT_SMALL

SIDEBAR_W    = 200          # pixels
WIN_W        = 1100
WIN_H        = 820
WIN_MIN_W    = 960
WIN_MIN_H    = 780

# Item 11: hand2 is valid on all Tk platforms but may render differently.
# Use 'hand2' everywhere — it shows a pointing hand on macOS/Windows and
# a reasonable pointer on Linux. No substitution needed.
_CURSOR_HAND = "hand2"


# ─────────────────────────────────────────────
# NavButton - a styled sidebar button
# ─────────────────────────────────────────────
class NavButton(tk.Frame):
    """
    A custom sidebar navigation item.
    Selected: 3px accent-coloured left bar + lighter bg + bold white text.
    Unselected: no bar, dim text, subtle hover highlight.
    """

    BORDER_W = 3
    # Item 7 fix: hover colour from THEME instead of hardcoded hex
    _HOVER_BG = THEME.BG_CARD

    def __init__(self, parent, text, command, **kwargs):
        super().__init__(parent, bg=BG_SIDEBAR, cursor=_CURSOR_HAND, **kwargs)

        self.command  = command
        self.selected = False

        # Left accent bar (hidden until selected)
        self._bar = tk.Frame(self, bg=BG_SIDEBAR, width=self.BORDER_W)
        self._bar.pack(side="left", fill="y")
        self._bar.pack_propagate(False)

        # Text label
        self.text_lbl = tk.Label(
            self, text=text, bg=BG_SIDEBAR,
            fg=TEXT_SECONDARY, font=FONT_NAV,
            anchor="w"
        )
        self.text_lbl.pack(side="left", fill="x", expand=True,
                           padx=(14, 12), pady=11)

        for widget in (self, self._bar, self.text_lbl):
            widget.bind("<Button-1>", self._on_click)
            widget.bind("<Enter>",    self._on_enter)
            widget.bind("<Leave>",    self._on_leave)

    def set_selected(self, selected: bool):
        self.selected = selected
        self._refresh()

    def _refresh(self):
        if self.selected:
            bg, fg, font, bar = BG_PANEL, ACCENT, FONT_NAV_SEL, ACCENT
        else:
            bg, fg, font, bar = BG_SIDEBAR, TEXT_SECONDARY, FONT_NAV, BG_SIDEBAR

        self.config(bg=bg)
        self._bar.config(bg=bar)
        self.text_lbl.config(bg=bg, fg=fg, font=font)

    def _on_enter(self, _event=None):
        if not self.selected:
            for w in (self, self._bar, self.text_lbl):
                w.config(bg=self._HOVER_BG)

    def _on_leave(self, _event=None):
        if not self.selected:
            for w in (self, self._bar, self.text_lbl):
                w.config(bg=BG_SIDEBAR)

    def _on_click(self, _event=None):
        self.command()

# ─────────────────────────────────────────────
# App - the root window and layout manager
# ─────────────────────────────────────────────
class App(tk.Tk):
    """
    The single Tk root window.

    Layout (left > right):
    ┌──────────┬──────────────────────────────┐
    │          │  header (title bar)           │
    │ sidebar  ├──────────────────────────────┤
    │          │  content  (swappable frames)  │
    │          │                              │
    └──────────┴──────────────────────────────┘

    self.frames  - dict of page_name > tk.Frame
                   populated by register_frame()
    self.nav_btns - dict of page_name > NavButton
    """

    def __init__(self):
        super().__init__()

        self._configure_window()
        self._build_layout()
        self._build_sidebar()
        self._build_header()
        self._build_content_area()

        # Show the first page on launch
        self.show_page("Dashboard")

    # ── window setup ──────────────────────────
    def _configure_window(self):
        self.title("System Health Monitor")
        self.geometry(f"{WIN_W}x{WIN_H}")
        self.minsize(WIN_MIN_W, WIN_MIN_H)
        self.configure(bg=BG_DARK)

    # ── top-level grid ─────────────────────────
    def _build_layout(self):
        """
        Two columns: sidebar (fixed) | main area (grows).
        The main area has two rows: header (fixed) | content (grows).
        """
        self.columnconfigure(0, weight=0, minsize=SIDEBAR_W)  # sidebar
        self.columnconfigure(1, weight=1)                      # main
        self.rowconfigure(0, weight=1)

    # ── sidebar ────────────────────────────────
    def _build_sidebar(self):
        self.sidebar = tk.Frame(self, bg=BG_SIDEBAR, width=SIDEBAR_W)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)   # keep fixed width

        # App logo / name at the top
        logo_frame = tk.Frame(self.sidebar, bg=BG_SIDEBAR)
        logo_frame.pack(fill="x", pady=(20, 6))

        tk.Label(logo_frame, text="SH", bg=BG_SIDEBAR,
                 fg=ACCENT, font=THEME.FONT_SECTION).pack(side="left", padx=(16, 8))

        name_stack = tk.Frame(logo_frame, bg=BG_SIDEBAR)
        name_stack.pack(side="left")
        tk.Label(name_stack, text="System Health",
                 bg=BG_SIDEBAR, fg=TEXT_PRIMARY,
                 font=THEME.FONT_SECTION, anchor="w").pack(anchor="w")
        tk.Label(name_stack, text="Monitor",
                 bg=BG_SIDEBAR, fg=TEXT_SECONDARY,
                 font=FONT_SMALL, anchor="w").pack(anchor="w")

        # Divider
        tk.Frame(self.sidebar, bg=BORDER, height=1).pack(fill="x", padx=14, pady=10)

        # Nav items - (display text, emoji icon, page name)
        nav_items = [
            ("Dashboard",  "Dashboard"),
            ("Scheduler",  "Scheduler"),
            ("Cleanup Log","CleanupLog"),
            ("History",    "History"),
            ("Settings",   "Settings"),
        ]

        self.nav_btns: dict[str, NavButton] = {}
        for label, page in nav_items:
            btn = NavButton(
                self.sidebar, text=label,
                command=lambda p=page: self.show_page(p)
            )
            btn.pack(fill="x")
            self.nav_btns[page] = btn

        # Version stamp at the bottom
        tk.Label(self.sidebar, text=f"v{META.VERSION}",
                 bg=BG_SIDEBAR, fg=BORDER,
                 font=FONT_SMALL).pack(side="bottom", pady=12)

    # ── header bar ─────────────────────────────
    def _build_header(self):
        """
        Thin bar at the top of the main area.
        Shows the current page title + a live status dot.
        """
        self.main_frame = tk.Frame(self, bg=BG_DARK)
        self.main_frame.grid(row=0, column=1, sticky="nsew")
        self.main_frame.rowconfigure(1, weight=1)
        self.main_frame.columnconfigure(0, weight=1)

        self.header = tk.Frame(self.main_frame, bg=BG_PANEL, height=52)
        self.header.grid(row=0, column=0, sticky="ew")
        self.header.grid_propagate(False)
        self.header.columnconfigure(0, weight=1)

        # Page title (updated by show_page)
        self.header_title = tk.Label(
            self.header, text="",
            bg=BG_PANEL, fg=TEXT_PRIMARY,
            font=FONT_TITLE, anchor="w"
        )
        self.header_title.grid(row=0, column=0, padx=20, pady=12, sticky="w")

        # Status indicator (green dot = healthy)
        status_frame = tk.Frame(self.header, bg=BG_PANEL)
        status_frame.grid(row=0, column=1, padx=16)

        tk.Label(status_frame, text="o", bg=BG_PANEL,
                 fg=ACCENT, font=THEME.FONT_DETAIL).pack(side="left")
        tk.Label(status_frame, text="Healthy", bg=BG_PANEL,
                 fg=TEXT_SECONDARY, font=FONT_SMALL).pack(side="left", padx=(4, 0))

        # Separator line under header
        tk.Frame(self.main_frame, bg=BORDER, height=1).grid(
            row=0, column=0, sticky="ew", pady=(52, 0)
        )

    # ── content area ───────────────────────────
    def _build_content_area(self):
        """
        A plain container that each module's Frame is placed inside.
        Frames are stacked on top of each other; show_page() raises the right one.
        """
        self.content = tk.Frame(self.main_frame, bg=BG_DARK)
        self.content.grid(row=1, column=0, sticky="nsew", padx=0, pady=0)
        self.content.rowconfigure(0, weight=1)
        self.content.columnconfigure(0, weight=1)

        self.frames: dict[str, tk.Frame] = {}

        # Placeholder frames (modules will replace these later)
        for page in ("Dashboard", "Scheduler", "CleanupLog", "History", "Settings"):
            frame = tk.Frame(self.content, bg=BG_DARK)
            frame.grid(row=0, column=0, sticky="nsew")
            self._build_placeholder(frame, page)
            self.frames[page] = frame

    def _build_placeholder(self, frame: tk.Frame, name: str):
        """Temporary content - replaced when each module is implemented."""
        tk.Label(
            frame,
            text=f"{name}\n\nModule coming soon...",
            bg=BG_DARK, fg=TEXT_SECONDARY,
            font=THEME.FONT_BODY, justify="center"
        ).place(relx=0.5, rely=0.5, anchor="center")

    # ── public API used by all modules ─────────
    def register_frame(self, page_name: str, frame: tk.Frame):
        """
        Modules call this to replace a placeholder frame with their own.

        Usage (from another module):
            app.register_frame("Dashboard", DashboardFrame(app.content, app))
        """
        if page_name in self.frames:
            self.frames[page_name].destroy()
        frame.grid(row=0, column=0, sticky="nsew")
        self.frames[page_name] = frame

    def show_page(self, page_name: str):
        """Raise a frame to the top and update the header title + nav selection."""
        frame = self.frames.get(page_name)
        if frame:
            frame.tkraise()

        self.header_title.config(text=page_name.replace("Log", " Log"))

        for name, btn in self.nav_btns.items():
            btn.set_selected(name == page_name)

    def get_theme(self) -> dict:
        """
        Returns the colour/font constants as a dict so modules can
        import a consistent theme without importing this file directly.
        """
        return {
            "BG_DARK": BG_DARK, "BG_PANEL": BG_PANEL,
            "BG_SIDEBAR": BG_SIDEBAR,
            "ACCENT": ACCENT, "ACCENT_DIM": ACCENT_DIM,
            "TEXT_PRIMARY": TEXT_PRIMARY, "TEXT_SECONDARY": TEXT_SECONDARY,
            "BORDER": BORDER,
            "FONT_TITLE": FONT_TITLE, "FONT_NAV": FONT_NAV,
            "FONT_SMALL": FONT_SMALL,
        }


# ─────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────
if __name__ == "__main__":
    # Item 2 fix: import all frame modules BEFORE constructing App().
    # This ensures:
    #   (a) import errors (e.g. missing psutil) fail cleanly before any
    #       window opens, rather than crashing after showing placeholders.
    #   (b) no placeholder flash — real frames are available immediately
    #       when register_frame() is called right after App() starts.
    try:
        from dashboard import DashboardFrame
        from scheduler import SchedulerFrame
        from log_view import LogFrame
        from history import HistoryFrame
        from settings import SettingsFrame
    except ImportError as e:
        import sys as _sys
        print(f"[ERROR] Failed to import a required module: {e}", file=_sys.stderr)
        print("Make sure all dependencies (psutil, schedule, etc.) are installed.",
              file=_sys.stderr)
        _sys.exit(1)

    app = App()
    app.register_frame("Dashboard", DashboardFrame(app.content, app))
    app.register_frame("Scheduler", SchedulerFrame(app.content, app))
    app.register_frame("CleanupLog", LogFrame(app.content, app))
    app.register_frame("History", HistoryFrame(app.content, app))
    app.register_frame("Settings", SettingsFrame(app.content, app))

    app.show_page("Dashboard")  # < always land on Dashboard at startup
    app.mainloop()
