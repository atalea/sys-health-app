"""
System Health Monitor
==================
Module 8: settings.py
Responsibility: Settings page - user preferences, cleanup thresholds,
                history retention, font size, and app info.

Notes
-----
* Data Folder card  - shows current path, "Change Folder" button opens
  a native folder picker and calls PATHS.set_app_dir().
* All scrollable areas use bind_scroll() from app_config (no bind_all leaks).
"""

import tkinter as tk
import tkinter.filedialog as fd
import json
import os
import sys
import datetime
from pathlib import Path
from typing import Any

from app_config import THEME, PATHS, CONSTANTS, META, bind_scroll
from utils import ToggleSwitch

# ─────────────────────────────────────────────
# Default settings
# ─────────────────────────────────────────────
DEFAULTS = {
    "target_caches":             True,
    "target_logs":               True,
    "target_downloads":          True,
    "target_trash":              False,
    "downloads_age_days":        30,
    "logs_age_days":             7,
    "history_max_records":       100,
    "dashboard_refresh_seconds": 10,
    "notify_before_cleanup":     True,
    "open_at_login":             False,
}

SETTINGS_META = {
    "target_caches": (
        "Clean User Caches",
        "Removes cached data from known apps (Safari, Chrome, etc.)",
        "bool", None),
    "target_logs": (
        "Clean Old Log Files",
        "Deletes crash reports and diagnostic logs older than the threshold",
        "bool", None),
    "target_downloads": (
        "Clean Downloads Folder",
        "Deletes files in ~/Downloads older than the age threshold",
        "bool", None),
    "target_trash": (
        "Empty Trash",
        "Permanently deletes items in Trash - cannot be undone",
        "bool", None),
    "downloads_age_days": (
        "Downloads Age Threshold",
        "Only delete Downloads files older than this many days",
        "int", [7, 14, 30, 60, 90, 180]),
    "logs_age_days": (
        "Log Age Threshold",
        "Only delete log files older than this many days",
        "int", [3, 7, 14, 30]),
    "history_max_records": (
        "History Retention",
        "Maximum number of cleanup runs to keep in history",
        "int", [10, 25, 50, 100, 200]),
    "dashboard_refresh_seconds": (
        "Dashboard Refresh Rate",
        "How often the dashboard metrics update (seconds)",
        "int", [5, 10, 30, 60]),
    "notify_before_cleanup": (
        "Show Notification Before Cleanup",
        "Display a confirmation dialog before any scheduled cleanup runs",
        "bool", None),
    "open_at_login": (
        "Open at Login",
        "Automatically launch System Health Monitor when you log in",
        "bool", None),
}


# ─────────────────────────────────────────────
# SettingsStore
# ─────────────────────────────────────────────
class SettingsStore:
    """
    Persists user preferences to settings.json.
    Falls back to DEFAULTS for any missing key.
    """

    def __init__(self, path: str = None):
        self.path = path or str(PATHS.SETTINGS_FILE)
        self._data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, dict):
                self._data = loaded
        except (FileNotFoundError, json.JSONDecodeError):
            self._data = {}

    def get(self, key: str, fallback=None) -> Any:
        if key in self._data:
            return self._data[key]
        if key in DEFAULTS:
            return DEFAULTS[key]
        return fallback

    def set(self, key: str, value: Any):
        self._data[key] = value

    def save(self):
        """
        Persist settings to disk atomically.
        Writes to a sibling .tmp file first, then os.replace() swaps it in,
        so a crash mid-write can never produce a corrupt or zero-byte JSON file.
        """
        p   = Path(self.path)
        tmp = p.with_suffix(".tmp")
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            tmp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
            os.replace(tmp, p)
        except Exception:
            try:
                tmp.unlink(missing_ok=True)
            except Exception:
                pass
            raise

    def reset_to_defaults(self):
        self._data = {}
        self.save()

    def all(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self._data)
        return merged


# ─────────────────────────────────────────────
# SettingRow
# ─────────────────────────────────────────────
class SettingRow(tk.Frame):
    """A single setting row with label, description, and control."""

    def __init__(self, parent, key: str, store: SettingsStore,
                 on_change=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_CARD, **kwargs)
        self.key       = key
        self.store     = store
        self.on_change = on_change
        self._build()

    def _build(self):
        meta  = SETTINGS_META.get(self.key, (self.key, "", "bool", None))
        label, desc, kind, options = meta
        value = self.store.get(self.key)

        text_col = tk.Frame(self, bg=THEME.BG_CARD)
        text_col.pack(side="left", fill="x", expand=True, padx=(0, 12))

        fg = THEME.WARN if self.key == "target_trash" else THEME.TEXT_PRIMARY
        display_label = f"[!]  {label}" if self.key == "target_trash" else label
        tk.Label(text_col, text=display_label,
                 bg=THEME.BG_CARD, fg=fg,
                 font=THEME.FONT_BODY, anchor="w").pack(anchor="w")
        if desc:
            tk.Label(text_col, text=desc,
                     bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                     font=THEME.FONT_SMALL, anchor="w",
                     wraplength=380).pack(anchor="w", pady=(1, 0))

        if kind == "bool":
            # open_at_login is not yet implemented — show toggle but disable it
            if self.key == "open_at_login":
                ctrl = ToggleSwitch(self, value=bool(value), bg=THEME.BG_CARD)
                ctrl.pack(side="right", padx=(0, 4))
                ctrl.configure(state="disabled", cursor="arrow")
                # Add a "(not yet implemented)" note
                tk.Label(text_col, text="Not yet implemented on this platform",
                         bg=THEME.BG_CARD, fg=THEME.BORDER_CARD,
                         font=THEME.FONT_SMALL, anchor="w").pack(anchor="w", pady=(1, 0))
            else:
                ctrl = ToggleSwitch(self, value=bool(value),
                                    on_change=self._on_bool_change, bg=THEME.BG_CARD)
                ctrl.pack(side="right", padx=(0, 4))

        elif kind == "int" and options:
            self._var = tk.StringVar(value=str(value))
            ctrl_frame = tk.Frame(self, bg=THEME.BG_CARD)
            ctrl_frame.pack(side="right")
            border = tk.Frame(ctrl_frame, bg=THEME.BORDER_CARD, padx=1, pady=1)
            border.pack()
            opt = tk.OptionMenu(border, self._var, *[str(o) for o in options])
            opt.config(bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                       activebackground=THEME.BORDER, activeforeground=THEME.TEXT_PRIMARY,
                       highlightthickness=0, relief="flat",
                       font=THEME.FONT_DETAIL, width=6)
            opt["menu"].config(bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                               activebackground=THEME.ACCENT,
                               activeforeground=THEME.BG_DARK,
                               font=THEME.FONT_DETAIL)
            opt.pack()
            self._var.trace_add("write", self._on_int_change)

        tk.Frame(self, bg=THEME.BORDER, height=1).pack(side="bottom", fill="x")

    def _on_bool_change(self, value: bool):
        self.store.set(self.key, value)
        self.store.save()
        if self.on_change:
            self.on_change(self.key, value)

    def _on_int_change(self, *_):
        try:
            value = int(self._var.get())
            self.store.set(self.key, value)
            self.store.save()
            if self.on_change:
                self.on_change(self.key, value)
        except ValueError:
            pass


# ─────────────────────────────────────────────
# SettingsGroup
# ─────────────────────────────────────────────
class SettingsGroup(tk.Frame):
    """A card with a group title and multiple SettingRows."""

    def __init__(self, parent, title: str, keys: list,
                 store: SettingsStore, on_change=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self._build(title, keys, store, on_change)

    def _build(self, title, keys, store, on_change):
        tk.Label(self, text=title,
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_SMALL).pack(anchor="w", pady=(0, 4))
        border = tk.Frame(self, bg=THEME.BORDER_CARD, padx=1, pady=1)
        border.pack(fill="x")
        card = tk.Frame(border, bg=THEME.BG_CARD)
        card.pack(fill="both", padx=1, pady=1)
        for key in keys:
            SettingRow(card, key, store,
                       on_change=on_change).pack(fill="x", padx=16, pady=10)



# ─────────────────────────────────────────────
# DataFolderCard
# ─────────────────────────────────────────────
class DataFolderCard(tk.Frame):
    """
    Shows the current data folder and lets the user pick a new one.
    Calls PATHS.set_app_dir() which persists the choice and notifies
    all modules that registered with PATHS.on_dir_change().
    """

    def __init__(self, parent, store: SettingsStore,
                 on_change=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self._store     = store
        self._on_change = on_change
        self._build()

    def _build(self):
        tk.Label(self, text="DATA FOLDER",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_SMALL).pack(anchor="w", pady=(0, 4))

        border = tk.Frame(self, bg=THEME.BORDER_CARD, padx=1, pady=1)
        border.pack(fill="x")
        card = tk.Frame(border, bg=THEME.BG_CARD, padx=16, pady=14)
        card.pack(fill="both", padx=1, pady=1)

        desc = tk.Frame(card, bg=THEME.BG_CARD)
        desc.pack(fill="x", pady=(0, 8))
        tk.Label(desc, text="All settings, history, logs and schedule files are stored here.",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_SMALL, anchor="w",
                 wraplength=480).pack(anchor="w")

        row = tk.Frame(card, bg=THEME.BG_CARD)
        row.pack(fill="x")

        # Current path label
        self._path_lbl = tk.Label(
            row, text=str(PATHS.APP_DIR),
            bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
            font=THEME.FONT_DETAIL, anchor="w")
        self._path_lbl.pack(side="left", fill="x", expand=True)

        # Buttons row
        btn_row = tk.Frame(card, bg=THEME.BG_CARD)
        btn_row.pack(fill="x", pady=(10, 0))

        # Change Folder button
        btn_border = tk.Frame(btn_row, bg=THEME.BORDER_CARD, padx=1, pady=1)
        btn_border.pack(side="left")
        btn = tk.Label(btn_border, text="  Change Folder  ",
                       bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                       font=THEME.FONT_BTN, cursor="hand2")
        btn.pack()
        for w in (btn_border, btn):
            w.bind("<Button-1>", lambda _: self._choose())
            w.bind("<Enter>",  lambda _, b=btn: b.config(fg=THEME.TEXT_PRIMARY))
            w.bind("<Leave>",  lambda _, b=btn: b.config(fg=THEME.TEXT_SECONDARY))

        # Reset to Default button
        reset_border = tk.Frame(btn_row, bg=THEME.BORDER_CARD, padx=1, pady=1)
        reset_border.pack(side="left", padx=(8, 0))
        reset_btn = tk.Label(reset_border, text="  Reset to Default  ",
                             bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                             font=THEME.FONT_BTN, cursor="hand2")
        reset_btn.pack()
        for w in (reset_border, reset_btn):
            w.bind("<Button-1>", lambda _: self._reset())
            w.bind("<Enter>",  lambda _, b=reset_btn: b.config(fg=THEME.TEXT_PRIMARY))
            w.bind("<Leave>",  lambda _, b=reset_btn: b.config(fg=THEME.TEXT_SECONDARY))

        # Status label
        self._status = tk.Label(card, text="",
                                bg=THEME.BG_CARD, fg=THEME.ACCENT,
                                font=THEME.FONT_SMALL)
        self._status.pack(anchor="w", pady=(6, 0))

    def _choose(self):
        new_dir = fd.askdirectory(
            title="Choose System Health Monitor data folder",
            initialdir=str(PATHS.APP_DIR),
            mustexist=False,
            parent=self.winfo_toplevel(),
        )
        if not new_dir:
            return
        try:
            PATHS.set_app_dir(new_dir)
            self._path_lbl.config(text=new_dir)
            self._status.config(
                text="[OK]  Folder changed — restart may be needed for full effect",
                fg=THEME.ACCENT)
            self.after(4000, lambda: self._status.config(text=""))
            if self._on_change:
                self._on_change("app_dir", new_dir)
        except Exception as e:
            self._status.config(
                text=f"[!!]  Could not set folder: {e}", fg=THEME.DANGER)

    def _reset(self):
        """Reset data folder back to the installation directory."""
        default = str(Path(__file__).resolve().parent)
        try:
            # set_app_dir() persists the new path to the pointer file,
            # so no manual pointer-file manipulation is needed here.
            PATHS.set_app_dir(default)
            self._path_lbl.config(text=default)
            self._status.config(
                text="[OK]  Reset to installation folder — restart may be needed",
                fg=THEME.ACCENT)
            self.after(4000, lambda: self._status.config(text=""))
            if self._on_change:
                self._on_change("app_dir", default)
        except Exception as e:
            self._status.config(
                text=f"[!!]  Could not reset folder: {e}", fg=THEME.DANGER)


# ─────────────────────────────────────────────
# SettingsFrame
# ─────────────────────────────────────────────
class SettingsFrame(tk.Frame):
    """
    The Settings page.

    Layout (scrollable):
        Data Folder         - change where files are stored
        Cleanup Targets     - which targets are active
        Age Thresholds      - age limits for downloads + logs
        Dashboard           - refresh rate
        Notifications       - notify before cleanup
        Startup             - open at login (stub)
        History             - retention limit
        About               - version, reset button
    """

    def __init__(self, parent, app=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self.app    = app
        self._store = SettingsStore()
        self._build()

    def _build(self):
        # ── page header ────────────────────────
        header = tk.Frame(self, bg=THEME.BG_DARK)
        header.pack(fill="x", padx=20, pady=(16, 8))
        tk.Label(header, text="Settings",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
                 font=THEME.FONT_SECTION).pack(side="left")

        # ── scrollable canvas ──────────────────
        canvas    = tk.Canvas(self, bg=THEME.BG_DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True)

        content    = tk.Frame(canvas, bg=THEME.BG_DARK)
        canvas_win = canvas.create_window((0, 0), window=content, anchor="nw")

        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_win, width=e.width))
        content.bind("<Configure>",
                     lambda e: canvas.configure(
                         scrollregion=canvas.bbox("all")))

        bind_scroll(canvas, lambda d: canvas.yview_scroll(d, "units"))

        pad = {"padx": 20, "pady": (0, 16), "fill": "x"}

        # ── Data Folder ────────────────────────
        DataFolderCard(
            content, store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── Cleanup Targets ────────────────────
        SettingsGroup(
            content, title="CLEANUP TARGETS",
            keys=["target_caches", "target_logs",
                  "target_downloads", "target_trash"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── Thresholds ─────────────────────────
        SettingsGroup(
            content, title="AGE THRESHOLDS",
            keys=["downloads_age_days", "logs_age_days"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── Dashboard ──────────────────────────
        SettingsGroup(
            content, title="DASHBOARD",
            keys=["dashboard_refresh_seconds"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── Notifications ──────────────────────
        SettingsGroup(
            content, title="NOTIFICATIONS",
            keys=["notify_before_cleanup"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── Login ──────────────────────────────
        SettingsGroup(
            content, title="STARTUP",
            keys=["open_at_login"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── History ────────────────────────────
        SettingsGroup(
            content, title="HISTORY",
            keys=["history_max_records"],
            store=self._store,
            on_change=self._on_change
        ).pack(**pad)

        # ── About ──────────────────────────────
        self._build_about(content).pack(**pad)

    def _build_about(self, parent) -> tk.Frame:
        group = tk.Frame(parent, bg=THEME.BG_DARK)
        tk.Label(group, text="ABOUT",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_SMALL).pack(anchor="w", pady=(0, 4))

        border = tk.Frame(group, bg=THEME.BORDER_CARD, padx=1, pady=1)
        border.pack(fill="x")
        card = tk.Frame(border, bg=THEME.BG_CARD, padx=16, pady=14)
        card.pack(fill="both", padx=1, pady=1)

        info = [
            ("Version",        META.VERSION),
            ("Settings file",  str(PATHS.SETTINGS_FILE)),
            ("History file",   str(PATHS.HISTORY_FILE)),
            ("Log exports",    str(PATHS.LOGS_DIR)),
        ]
        for label, value in info:
            row = tk.Frame(card, bg=THEME.BG_CARD)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label,
                     bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                     font=THEME.FONT_DETAIL, width=16,
                     anchor="w").pack(side="left")
            tk.Label(row, text=value,
                     bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                     font=THEME.FONT_SMALL,
                     anchor="w").pack(side="left")

        tk.Frame(card, bg=THEME.BORDER, height=1).pack(fill="x", pady=(10, 8))

        btn_row = tk.Frame(card, bg=THEME.BG_CARD)
        btn_row.pack(fill="x")

        reset_border = tk.Frame(btn_row, bg=THEME.BORDER_CARD, padx=1, pady=1)
        reset_border.pack(side="left")
        reset_btn = tk.Label(reset_border,
                             text="  <>  Reset to Defaults  ",
                             bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                             font=THEME.FONT_BTN, cursor="hand2")
        reset_btn.pack()
        for w in (reset_border, reset_btn):
            w.bind("<Button-1>", lambda _: self._confirm_reset())
            w.bind("<Enter>",
                   lambda _, b=reset_btn: b.config(fg=THEME.WARN))
            w.bind("<Leave>",
                   lambda _, b=reset_btn: b.config(fg=THEME.TEXT_SECONDARY))

        self._saved_lbl = tk.Label(btn_row, text="",
                                   bg=THEME.BG_CARD, fg=THEME.ACCENT,
                                   font=THEME.FONT_SMALL)
        self._saved_lbl.pack(side="right", padx=8)

        return group

    # ── change handler ─────────────────────────
    def _on_change(self, key: str, value):
        self._flash_saved()
        if key == "dashboard_refresh_seconds" and self.app:
            frames    = getattr(self.app, "frames", {})
            dashboard = frames.get("Dashboard")
            if dashboard and hasattr(dashboard, "set_refresh_rate"):
                dashboard.set_refresh_rate(value * 1000)

    def _flash_saved(self):
        self._saved_lbl.config(text="[OK]  Saved")
        self.after(2000, lambda: self._saved_lbl.config(text=""))

    # ── reset ──────────────────────────────────
    def _confirm_reset(self):
        confirm = tk.Toplevel(self)
        confirm.title("Reset Settings")
        confirm.resizable(False, False)
        confirm.configure(bg=THEME.BG_DARK)
        confirm.transient(self)
        confirm.grab_set()

        tk.Label(confirm,
                 text="Reset all settings to defaults?",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
                 font=THEME.FONT_BTN,
                 padx=24, pady=20).pack()
        tk.Label(confirm,
                 text="Your history and log files will not be affected.",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_DETAIL).pack(pady=(0, 16))

        btn_row = tk.Frame(confirm, bg=THEME.BG_DARK, padx=20, pady=12)
        btn_row.pack()

        cb = tk.Frame(btn_row, bg=THEME.BORDER_CARD, padx=1, pady=1)
        cb.pack(side="left", padx=(0, 10))
        cl = tk.Label(cb, text="  Cancel  ",
                      bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                      font=THEME.FONT_BTN, cursor="hand2")
        cl.pack()
        for w in (cb, cl):
            w.bind("<Button-1>",
                   lambda _: (confirm.grab_release(), confirm.destroy()))

        rb = tk.Frame(btn_row, bg=THEME.WARN, padx=1, pady=1)
        rb.pack(side="left")
        rl = tk.Label(rb, text="  Reset  ",
                      bg=THEME.WARN, fg=THEME.BG_DARK,
                      font=THEME.FONT_BTN, cursor="hand2")
        rl.pack()
        for w in (rb, rl):
            w.bind("<Button-1>",
                   lambda _: self._do_reset(confirm))

        confirm.update_idletasks()
        px = self.winfo_rootx()
        py = self.winfo_rooty()
        pw = self.winfo_width()
        ph = self.winfo_height()
        ww = confirm.winfo_width()
        wh = confirm.winfo_height()
        confirm.geometry(f"+{px+(pw-ww)//2}+{py+(ph-wh)//2}")

    def _do_reset(self, dialog):
        dialog.grab_release()
        dialog.destroy()
        self._store.reset_to_defaults()
        for w in self.winfo_children():
            w.destroy()
        self._build()

    # ── public API ─────────────────────────────
    def get_store(self) -> SettingsStore:
        return self._store


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    root = tk.Tk()
    root.title("Settings - Module 8 Test")
    root.geometry("780x680")
    root.minsize(600, 500)
    root.configure(bg=THEME.BG_DARK)
    SettingsFrame(root).pack(fill="both", expand=True)
    root.mainloop()


if __name__ == "__main__":
    _run_standalone()
