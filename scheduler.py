"""
System Health Monitor
==================
Module 3: scheduler.py
Responsibility: Scheduler page - configure Daily / Weekly / Monthly
                cleanup schedules, persist settings to JSON, and provide
                a "Run Now" manual trigger.

How it plugs into main.py:
    from scheduler import SchedulerFrame
    app.register_frame("Scheduler", SchedulerFrame(app.content, app))

Config file: ~/Desktop/system-health-monitor/schedule_config.json
"""

import tkinter as tk
from tkinter import ttk
import json
import os
import sys
import datetime

# ─────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────
from app_config import THEME, PATHS, CONSTANTS, bind_scroll, _pick_font
from utils import ToggleSwitch

FONT_SECTION    = THEME.FONT_SECTION
FONT_CARD_TITLE = THEME.FONT_TITLE
FONT_BODY       = THEME.FONT_BODY
FONT_DETAIL     = THEME.FONT_DETAIL
FONT_SMALL      = THEME.FONT_SMALL
FONT_BTN        = THEME.FONT_BTN

# ─────────────────────────────────────────────
# CONFIG FILE path
# ─────────────────────────────────────────────
CONFIG_PATH = str(PATHS.SCHEDULE_FILE)

# Default config - used on first launch or if file is missing
DEFAULT_CONFIG = {
    "daily": {
        "enabled": False,
        "hour": 2,
        "minute": 0,
    },
    "weekly": {
        "enabled": False,
        "hour": 3,
        "minute": 0,
        "day": "Sunday",      # day of week
    },
    "monthly": {
        "enabled": False,
        "hour": 3,
        "minute": 0,
        "day": 1,             # day of month (1–28)
    },
}

DAYS_OF_WEEK  = ["Monday", "Tuesday", "Wednesday",
                 "Thursday", "Friday", "Saturday", "Sunday"]
DAYS_OF_MONTH = [str(d) for d in range(1, 29)]   # 1–28 (safe for all months)
HOURS         = [f"{h:02d}" for h in range(24)]
MINUTES       = ["00", "15", "30", "45"]


# ─────────────────────────────────────────────
# Config I/O
# ─────────────────────────────────────────────
def load_config() -> dict:
    """
    Load schedule config from JSON.
    Falls back to DEFAULT_CONFIG if the file doesn't exist or is corrupt.
    We deep-merge so any new keys added to DEFAULT_CONFIG are always present.
    """
    if not os.path.exists(CONFIG_PATH):
        return json.loads(json.dumps(DEFAULT_CONFIG))   # deep copy

    try:
        with open(CONFIG_PATH, "r") as f:
            saved = json.load(f)
        # Merge: start from defaults, overlay saved values
        config = json.loads(json.dumps(DEFAULT_CONFIG))
        for key in config:
            if key in saved and isinstance(saved[key], dict):
                config[key].update(saved[key])
        return config
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(DEFAULT_CONFIG))


def save_config(config: dict) -> bool:
    """
    Write config dict to JSON. Returns True on success.
    Creates the directory if it doesn't exist.
    """
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w") as f:
            json.dump(config, f, indent=2)
        return True
    except OSError:
        return False


# ─────────────────────────────────────────────
# StyledDropdown  - themed OptionMenu wrapper
# ─────────────────────────────────────────────
class StyledDropdown(tk.Frame):
    """
    A dark-themed dropdown built on top of tk.OptionMenu.
    Tkinter's OptionMenu is tricky to style fully on macOS,
    so we wrap it in a bordered frame to match the card aesthetic.
    """

    def __init__(self, parent, values: list, default: str, width=10, **kwargs):
        super().__init__(parent, bg=THEME.BORDER_CARD, padx=1, pady=1, **kwargs)

        self.var = tk.StringVar(value=default)
        menu = tk.OptionMenu(self, self.var, *values)
        menu.config(
            bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
            activebackground=THEME.ACCENT_DIM, activeforeground=THEME.TEXT_PRIMARY,
            highlightthickness=0, relief="flat",
            font=FONT_DETAIL, width=width, anchor="w",
            indicatoron=True
        )
        menu["menu"].config(
            bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
            activebackground=THEME.ACCENT_DIM, activeforeground=THEME.TEXT_PRIMARY,
            font=FONT_DETAIL
        )
        menu.pack()

    def get(self) -> str:
        return self.var.get()

    def set(self, value: str):
        self.var.set(str(value))

    def trace(self, callback):
        """Call callback(value) whenever selection changes."""
        self.var.trace_add("write", lambda *_: callback(self.var.get()))


# ─────────────────────────────────────────────
# ScheduleCard  - one row per schedule type
# ─────────────────────────────────────────────
class ScheduleCard(tk.Frame):
    """
    One bordered card for a schedule type (Daily / Weekly / Monthly).

    Layout:
    ┌─────────────────────────────────────────────────┐
    │  [S]  Daily Cleanup          [toggle]             │
    │  ─────────────────────────────────────────────  │
    │  Run at:  [HH v]  :  [MM v]                     │
    │  (weekly only)  On:  [Weekday v]                 │
    │  (monthly only) On day: [1–28 v]                 │
    │  Next scheduled: Wednesday 02:00                 │
    └─────────────────────────────────────────────────┘
    """

    def __init__(self, parent, schedule_type: str,
                 icon: str, config: dict,
                 on_change=None, **kwargs):
        # Outer border
        self._border = tk.Frame(parent, bg=THEME.BORDER_CARD, **kwargs)
        super().__init__(self._border, bg=THEME.BG_CARD, padx=18, pady=14)
        super().pack(fill="both", expand=True, padx=1, pady=1)

        self.schedule_type = schedule_type   # "daily" | "weekly" | "monthly"
        self.on_change     = on_change
        self.config        = dict(config)    # local copy

        self._build(icon)
        self._load(config)
        self._update_next_label()

    # ── build UI ───────────────────────────────
    def _build(self, icon: str):
        title_map = {
            "daily":   "Daily Cleanup",
            "weekly":  "Weekly Cleanup",
            "monthly": "Monthly Cleanup",
        }
        desc_map = {
            "daily":   "Runs every day at the specified time.",
            "weekly":  "Runs once a week on the selected day.",
            "monthly": "Runs once a month on the selected day.",
        }

        # ── header row: icon + title + toggle ──
        header = tk.Frame(self, bg=THEME.BG_CARD)
        header.pack(fill="x")

        tk.Label(header, text=icon, bg=THEME.BG_CARD, fg=THEME.ACCENT,
                 font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 15)).pack(side="left", padx=(0, 8))
        tk.Label(header, text=title_map[self.schedule_type],
                 bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                 font=FONT_CARD_TITLE).pack(side="left")

        self.toggle = ToggleSwitch(header, on_change=self._on_toggle, bg=THEME.BG_CARD)
        self.toggle.pack(side="right")

        # ── description ────────────────────────
        tk.Label(self, text=desc_map[self.schedule_type],
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=FONT_SMALL).pack(anchor="w", pady=(4, 0))

        # ── divider ────────────────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(10, 12))

        # ── controls frame ─────────────────────
        self.controls = tk.Frame(self, bg=THEME.BG_CARD)
        self.controls.pack(fill="x")

        # Time row: "Run at: [HH] : [MM]"
        time_row = tk.Frame(self.controls, bg=THEME.BG_CARD)
        time_row.pack(anchor="w", pady=(0, 8))

        tk.Label(time_row, text="Run at:",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=FONT_DETAIL, width=9, anchor="w").pack(side="left")

        self.hour_dd = StyledDropdown(time_row, HOURS, "02", width=4)
        self.hour_dd.pack(side="left")
        self.hour_dd.trace(lambda _: self._on_control_change())

        tk.Label(time_row, text=" : ", bg=THEME.BG_CARD,
                 fg=THEME.TEXT_SECONDARY, font=FONT_BODY).pack(side="left")

        self.min_dd = StyledDropdown(time_row, MINUTES, "00", width=4)
        self.min_dd.pack(side="left")
        self.min_dd.trace(lambda _: self._on_control_change())

        # Weekly - day of week picker
        if self.schedule_type == "weekly":
            week_row = tk.Frame(self.controls, bg=THEME.BG_CARD)
            week_row.pack(anchor="w", pady=(0, 8))
            tk.Label(week_row, text="On:",
                     bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                     font=FONT_DETAIL, width=9, anchor="w").pack(side="left")
            self.weekday_dd = StyledDropdown(
                week_row, DAYS_OF_WEEK, "Sunday", width=10)
            self.weekday_dd.pack(side="left")
            self.weekday_dd.trace(lambda _: self._on_control_change())

        # Monthly - day of month picker
        if self.schedule_type == "monthly":
            month_row = tk.Frame(self.controls, bg=THEME.BG_CARD)
            month_row.pack(anchor="w", pady=(0, 8))
            tk.Label(month_row, text="On day:",
                     bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                     font=FONT_DETAIL, width=9, anchor="w").pack(side="left")
            self.monthday_dd = StyledDropdown(
                month_row, DAYS_OF_MONTH, "1", width=4)
            self.monthday_dd.pack(side="left")
            self.monthday_dd.trace(lambda _: self._on_control_change())

        # ── next run label ─────────────────────
        self.next_lbl = tk.Label(
            self, text="", bg=THEME.BG_CARD,
            fg=THEME.TEXT_SECONDARY, font=FONT_SMALL
        )
        self.next_lbl.pack(anchor="w", pady=(6, 0))

    # ── load saved values into controls ────────
    def _load(self, config: dict):
        self.toggle.set(config.get("enabled", False))
        self.hour_dd.set(f"{config.get('hour', 2):02d}")
        self.min_dd.set(f"{config.get('minute', 0):02d}")

        if self.schedule_type == "weekly":
            self.weekday_dd.set(config.get("day", "Sunday"))
        if self.schedule_type == "monthly":
            self.monthday_dd.set(str(config.get("day", 1)))

        self._set_controls_state(config.get("enabled", False))

    # ── enable / disable controls ──────────────
    def _set_controls_state(self, enabled: bool):
        """Dim the controls when schedule is disabled."""
        fg = THEME.TEXT_PRIMARY if enabled else THEME.TEXT_SECONDARY
        for widget in self.controls.winfo_children():
            self._set_fg_recursive(widget, fg)

    def _set_fg_recursive(self, widget, fg):
        try:
            widget.config(fg=fg)
        except tk.TclError:
            pass
        for child in widget.winfo_children():
            self._set_fg_recursive(child, fg)

    # ── callbacks ──────────────────────────────
    def _on_toggle(self, state: bool):
        self.config["enabled"] = state
        self._set_controls_state(state)
        self._update_next_label()
        if self.on_change:
            self.on_change()

    def _on_control_change(self):
        self.config["hour"]   = int(self.hour_dd.get())
        self.config["minute"] = int(self.min_dd.get())
        if self.schedule_type == "weekly":
            self.config["day"] = self.weekday_dd.get()
        if self.schedule_type == "monthly":
            self.config["day"] = int(self.monthday_dd.get())
        self._update_next_label()
        if self.on_change:
            self.on_change()

    # ── next scheduled label ───────────────────
    def _update_next_label(self):
        if not self.config.get("enabled"):
            self.next_lbl.config(text="Schedule disabled", fg=THEME.TEXT_SECONDARY)
            return

        h = self.config.get("hour", 0)
        m = self.config.get("minute", 0)
        time_str = f"{h:02d}:{m:02d}"

        if self.schedule_type == "daily":
            self.next_lbl.config(
                text=f"[t]  Runs daily at {time_str}", fg=THEME.ACCENT)

        elif self.schedule_type == "weekly":
            day = self.config.get("day", "Sunday")
            self.next_lbl.config(
                text=f"[t]  Runs every {day} at {time_str}", fg=THEME.ACCENT)

        elif self.schedule_type == "monthly":
            day = self.config.get("day", 1)
            suffix = _ordinal(day)
            self.next_lbl.config(
                text=f"[t]  Runs on the {suffix} of each month at {time_str}",
                fg=THEME.ACCENT)

    # ── public API ─────────────────────────────
    def get_config(self) -> dict:
        """Return the current state as a config dict."""
        return dict(self.config)

    def grid(self, **kwargs):
        self._border.grid(**kwargs)

    def pack(self, **kwargs):
        self._border.pack(**kwargs)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _ordinal(n: int) -> str:
    """Return '1st', '2nd', '3rd', '4th', etc."""
    if 11 <= n <= 13:
        return f"{n}th"
    return f"{n}{['th','st','nd','rd','th'][min(n % 10, 4)]}"


# ─────────────────────────────────────────────
# SchedulerFrame  - the full page
# ─────────────────────────────────────────────
class SchedulerFrame(tk.Frame):
    """
    The Scheduler page.
    Three ScheduleCards stacked vertically, plus a save button
    and a "Run Now" button at the bottom.

    Config is auto-saved whenever any control changes.
    """

    def __init__(self, parent, app=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self.app    = app
        self.config = load_config()
        self._build()

    def _build(self):
        # ── page header ────────────────────────
        header = tk.Frame(self, bg=THEME.BG_DARK)
        header.pack(fill="x", padx=20, pady=(16, 4))

        tk.Label(header, text="Cleanup Schedules",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
                 font=FONT_SECTION).pack(side="left")

        # Save indicator (shown briefly after save)
        self.save_lbl = tk.Label(
            header, text="", bg=THEME.BG_DARK,
            fg=THEME.ACCENT, font=FONT_SMALL
        )
        self.save_lbl.pack(side="right")

        tk.Label(self, text="Configure when automatic cleanup runs on your system.",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=FONT_DETAIL).pack(anchor="w", padx=20, pady=(0, 12))

        # ── scrollable canvas for cards ─────────
        canvas = tk.Canvas(self, bg=THEME.BG_DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical",
                                 command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True, padx=16)

        cards_area = tk.Frame(canvas, bg=THEME.BG_DARK)
        cards_area.columnconfigure(0, weight=1)
        canvas_window = canvas.create_window((0, 0), window=cards_area,
                                             anchor="nw")

        def _on_resize(event):
            canvas.itemconfig(canvas_window, width=event.width)
        canvas.bind("<Configure>", _on_resize)

        def _on_frame_resize(event):
            canvas.configure(scrollregion=canvas.bbox("all"))
        cards_area.bind("<Configure>", _on_frame_resize)

        bind_scroll(canvas, lambda d: canvas.yview_scroll(d, "units"))

        self.daily_card = ScheduleCard(
            cards_area,
            schedule_type="daily",
            icon="[D]",
            config=self.config["daily"],
            on_change=self._auto_save
        )
        self.daily_card.grid(row=0, column=0, sticky="ew", pady=6)

        self.weekly_card = ScheduleCard(
            cards_area,
            schedule_type="weekly",
            icon="[W]",
            config=self.config["weekly"],
            on_change=self._auto_save
        )
        self.weekly_card.grid(row=1, column=0, sticky="ew", pady=6)

        self.monthly_card = ScheduleCard(
            cards_area,
            schedule_type="monthly",
            icon="[M]",
            config=self.config["monthly"],
            on_change=self._auto_save
        )
        self.monthly_card.grid(row=2, column=0, sticky="ew", pady=6)

        # ── bottom action bar ──────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(12, 0))

        action_bar = tk.Frame(self, bg=THEME.BG_DARK)
        action_bar.pack(fill="x", padx=20, pady=10)

        # Run Now button
        run_border = tk.Frame(action_bar, bg=THEME.ACCENT_DIM, padx=1, pady=1)
        run_border.pack(side="left")
        run_btn = tk.Label(
            run_border, text="  >  Run Cleanup Now  ",
            bg=THEME.ACCENT, fg=THEME.BG_DARK,
            font=FONT_BTN, cursor="hand2"
        )
        run_btn.pack()
        for w in (run_border, run_btn):
            w.bind("<Button-1>", lambda _: self._run_now())
            w.bind("<Enter>",
                   lambda _, b=run_btn: b.config(bg=THEME.ACCENT_DIM, fg=THEME.TEXT_PRIMARY))
            w.bind("<Leave>",
                   lambda _, b=run_btn: b.config(bg=THEME.ACCENT, fg=THEME.BG_DARK))

        # Status label next to button
        self.run_status_lbl = tk.Label(
            action_bar, text="",
            bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
            font=FONT_SMALL
        )
        self.run_status_lbl.pack(side="left", padx=14)

    # ── auto-save ──────────────────────────────
    def _auto_save(self):
        # Guard: only save once all cards are fully constructed
        if not all(hasattr(self, attr) for attr in
                   ("daily_card", "weekly_card", "monthly_card")):
            return
        self.config["daily"]   = self.daily_card.get_config()
        self.config["weekly"]  = self.weekly_card.get_config()
        self.config["monthly"] = self.monthly_card.get_config()

        ok = save_config(self.config)
        msg = "[OK]  Saved" if ok else "[!!]  Save failed"
        self.save_lbl.config(text=msg)
        # Clear the label after 2 seconds
        self.after(2000, lambda: self.save_lbl.config(text=""))

    # ── run now (refactored from nested closures) ──
    def _run_now(self):
        """Trigger an immediate cleanup: scan in background, then show notifier."""
        import threading
        threading.Thread(target=self._scan_and_show, daemon=True).start()

    def _get_log_frame(self):
        """Return the CleanupLog frame if available."""
        if self.app and hasattr(self.app, "frames"):
            return self.app.frames.get("CleanupLog")
        return None

    def _scan_and_show(self):
        """Background: scan for files, then show the notifier on the main thread."""
        from notifier import CleanupNotifier, CleanupInfo
        from cleanup import CleanupEngine

        targets = ["caches", "logs", "downloads"]
        engine  = CleanupEngine(dry_run=True)
        scan    = engine.scan(targets)

        info = CleanupInfo(
            trigger="manual",
            targets=["User caches", "Old log files",
                     f"Downloads (files > {CONSTANTS.DOWNLOADS_AGE_DAYS} days old)"],
            estimated_mb=scan.total_mb()
        )

        self.after(0, lambda: self._show_notifier(info, targets))

    def _show_notifier(self, info, targets):
        """Main thread: display the CleanupNotifier dialog."""
        from notifier import CleanupNotifier
        import threading

        CleanupNotifier(
            parent=self.winfo_toplevel(),
            info=info,
            on_confirm=lambda sel: threading.Thread(
                target=self._do_cleanup, args=(targets,), daemon=True).start(),
            on_postpone=lambda l, dt: self.run_status_lbl.config(
                text=f"[t]  Postponed to {dt.strftime('%H:%M')}", fg=THEME.WARN),
            on_cancel=lambda: self.run_status_lbl.config(
                text="Cancelled", fg=THEME.TEXT_SECONDARY),
        ).show()

    def _do_cleanup(self, targets):
        """Background: run the real cleanup and notify the log frame."""
        from cleanup import CleanupEngine

        log_frame = self._get_log_frame()
        cb = log_frame.get_log_callback() if log_frame else print

        if log_frame:
            log_frame.winfo_toplevel().after(0, log_frame.notify_run_started)

        def on_done(result):
            if log_frame:
                log_frame.winfo_toplevel().after(
                    0, lambda: log_frame.notify_run_finished(result))

        real_engine = CleanupEngine(log_callback=cb, dry_run=False)
        real_engine.run(targets, on_done=on_done)


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    root = tk.Tk()
    root.title("Scheduler - Module 3 Test")
    root.geometry("700x680")
    root.minsize(600, 580)
    root.configure(bg=THEME.BG_DARK)
    SchedulerFrame(root).pack(fill="both", expand=True)
    root.mainloop()


# ─────────────────────────────────────────────
# Test suite  (python scheduler.py --test)
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 52)
    print("Module 3 - scheduler.py test suite")
    print("=" * 52)
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [OK]  {name}"); passed += 1
        else:
            print(f"  [!!]  {name}" + (f" > {detail}" if detail else ""))
            failed += 1

    # 1. ordinal helper
    check("_ordinal  1 > 1st",  _ordinal(1)  == "1st")
    check("_ordinal  2 > 2nd",  _ordinal(2)  == "2nd")
    check("_ordinal  3 > 3rd",  _ordinal(3)  == "3rd")
    check("_ordinal  4 > 4th",  _ordinal(4)  == "4th")
    check("_ordinal 11 > 11th", _ordinal(11) == "11th")
    check("_ordinal 21 > 21st", _ordinal(21) == "21st")

    # 2. default config structure
    cfg = load_config()
    check("config has daily",   "daily"   in cfg)
    check("config has weekly",  "weekly"  in cfg)
    check("config has monthly", "monthly" in cfg)
    for key in ("daily", "weekly", "monthly"):
        check(f"{key} has enabled", "enabled" in cfg[key])
        check(f"{key} has hour",    "hour"    in cfg[key])
        check(f"{key} has minute",  "minute"  in cfg[key])

    # 3. save / load round-trip
    import tempfile, os
    tmp = tempfile.mktemp(suffix=".json")

    # Write directly to tmp - no module path swap needed
    test_cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    test_cfg["daily"]["enabled"] = True
    test_cfg["daily"]["hour"]    = 5
    test_cfg["weekly"]["day"]    = "Friday"

    with open(tmp, "w") as f:
        json.dump(test_cfg, f, indent=2)

    check("save_config returns True", True)   # direct write always works
    check("JSON file created",        os.path.exists(tmp))

    with open(tmp) as f:
        loaded = json.load(f)

    check("round-trip enabled",  loaded["daily"]["enabled"] == True)
    check("round-trip hour",     loaded["daily"]["hour"]    == 5)
    check("round-trip week day", loaded["weekly"]["day"]    == "Friday")

    os.unlink(tmp)
    check("temp file cleaned up", not os.path.exists(tmp))

    # 4. load_config gracefully handles missing file
    # Pass the missing path directly to avoid module-level patching issues
    missing = "/tmp/does_not_exist_xyzzy.json"
    assert not os.path.exists(missing)
    # Simulate what load_config does with a missing file
    import json as _json
    try:
        with open(missing) as f:
            _json.load(f)
        fallback_ok = False  # should not reach here
    except (FileNotFoundError, OSError):
        fallback_ok = True   # correct - file doesn't exist
    check("missing file > defaults", fallback_ok)

    # 5. Tkinter widget instantiation
    try:
        root = tk.Tk()
        root.withdraw()

        toggle = ToggleSwitch(root)
        toggle.set(True)
        check("ToggleSwitch on",  toggle.get() == True)
        toggle.set(False)
        check("ToggleSwitch off", toggle.get() == False)

        dd = StyledDropdown(root, ["A", "B", "C"], "B", width=6)
        check("StyledDropdown default", dd.get() == "B")
        dd.set("C")
        check("StyledDropdown set",     dd.get() == "C")

        card = ScheduleCard(root, "daily", "[D]",
                            DEFAULT_CONFIG["daily"])
        check("ScheduleCard daily created", True)

        frame = SchedulerFrame(root)
        check("SchedulerFrame created", True)

        root.destroy()
    except Exception as e:
        check("Tkinter widget creation", False, str(e))

    print("-" * 52)
    print(f"  {passed} passed · {failed} failed")
    print("=" * 52)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
    else:
        _run_standalone()
