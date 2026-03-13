"""
System Health Monitor
==================
Module 6: log_view.py
Responsibility: Cleanup Log page - live scrolling log output,
                run status, summary card, and clear button.

How it plugs into main.py:
    from log_view import LogFrame
    app.register_frame("CleanupLog", LogFrame(app.content, app))

How cleanup.py writes to it:
    log_frame.get_log_callback()  >  returns a thread-safe callable
    Pass that callable as log_callback to CleanupEngine.

Thread safety:
    CleanupEngine runs in a background thread.
    All UI updates go through root.after(0, ...) so Tkinter
    is only ever touched from the main thread.
"""

import tkinter as tk
import datetime
import sys
import threading
from typing import Optional, Callable

# ─────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────
from app_config import THEME, PATHS, CONSTANTS, _pick_font

MAX_LOG_LINES = CONSTANTS.MAX_LOG_LINES


# ─────────────────────────────────────────────
# RunSummary  - data shown in the summary card
# ─────────────────────────────────────────────
class RunSummary:
    """Holds stats for the most recent cleanup run."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.running      = False
        self.started_at   = None
        self.finished_at  = None
        self.freed_bytes  = 0
        self.deleted      = 0
        self.errors       = 0
        self.skipped      = 0

    def start(self):
        self.reset()
        self.running    = True
        self.started_at = datetime.datetime.now()

    def finish(self, freed_bytes=0, deleted=0, errors=0, skipped=0):
        self.running     = False
        self.finished_at = datetime.datetime.now()
        self.freed_bytes = freed_bytes
        self.deleted     = deleted
        self.errors      = errors
        self.skipped     = skipped

    def duration_str(self) -> str:
        if not self.started_at or not self.finished_at:
            return "-"
        secs = int((self.finished_at - self.started_at).total_seconds())
        return f"{secs}s" if secs < 60 else f"{secs//60}m {secs%60}s"

    def freed_str(self) -> str:
        n = self.freed_bytes
        if n >= 1024**3: return f"{n/1024**3:.2f} GB"
        if n >= 1024**2: return f"{n/1024**2:.1f} MB"
        if n >= 1024:    return f"{n/1024:.0f} KB"
        return f"{n} B"


# ─────────────────────────────────────────────
# SummaryCard  - stats shown above the log
# ─────────────────────────────────────────────
class SummaryCard(tk.Frame):
    """
    Shows four stat boxes: Space Freed / Files Deleted / Errors / Duration.
    Updates in real time as cleanup runs.
    Hidden when no run has happened yet.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self._build()
        self._stats = {}

    def _build(self):
        # Outer border
        border = tk.Frame(self, bg=THEME.BORDER_CARD, padx=1, pady=1)
        border.pack(fill="x")
        card = tk.Frame(border, bg=THEME.BG_CARD, padx=16, pady=12)
        card.pack(fill="both", padx=1, pady=1)

        # Title row
        title_row = tk.Frame(card, bg=THEME.BG_CARD)
        title_row.pack(fill="x", pady=(0, 10))
        tk.Label(title_row, text="Last Run Summary",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_TITLE).pack(side="left")
        self._status_dot = tk.Label(title_row, text="o",
                                    bg=THEME.BG_CARD, fg=THEME.BORDER,
                                    font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 10))
        self._status_dot.pack(side="right", padx=(0, 4))
        self._status_lbl = tk.Label(title_row, text="No runs yet",
                                    bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                                    font=THEME.FONT_SMALL)
        self._status_lbl.pack(side="right")

        # Four stat boxes in a row
        stats_row = tk.Frame(card, bg=THEME.BG_CARD)
        stats_row.pack(fill="x")
        for i in range(4):
            stats_row.columnconfigure(i, weight=1)

        self._stat_boxes = {}
        specs = [
            ("freed",    "Space Freed",   "-", THEME.ACCENT),
            ("deleted",  "Files Deleted", "-", THEME.TEXT_PRIMARY),
            ("errors",   "Errors",        "-", THEME.DANGER),
            ("duration", "Duration",      "-", THEME.TEXT_SECONDARY),
        ]
        for col, (key, label, default, color) in enumerate(specs):
            box = tk.Frame(stats_row, bg=THEME.BG_DARK, padx=12, pady=10)
            box.grid(row=0, column=col, sticky="nsew",
                     padx=(0 if col == 0 else 6, 0))

            val_lbl = tk.Label(box, text=default,
                               bg=THEME.BG_DARK, fg=color,
                               font=_pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 18, "bold"))
            val_lbl.pack()
            tk.Label(box, text=label,
                     bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                     font=THEME.FONT_SMALL).pack()

            self._stat_boxes[key] = val_lbl

    def set_running(self):
        self._status_dot.config(fg=THEME.WARN)
        self._status_lbl.config(text="Running...", fg=THEME.WARN)
        for key, lbl in self._stat_boxes.items():
            lbl.config(text="...")

    def set_finished(self, summary: RunSummary):
        if summary.errors > 0:
            self._status_dot.config(fg=THEME.WARN)
            self._status_lbl.config(
                text=f"Finished with {summary.errors} error(s)",
                fg=THEME.WARN)
        else:
            self._status_dot.config(fg=THEME.ACCENT)
            self._status_lbl.config(text="Completed successfully",
                                    fg=THEME.ACCENT)

        self._stat_boxes["freed"].config(text=summary.freed_str())
        self._stat_boxes["deleted"].config(text=str(summary.deleted))
        self._stat_boxes["errors"].config(
            text=str(summary.errors),
            fg=THEME.DANGER if summary.errors > 0 else THEME.TEXT_SECONDARY)
        self._stat_boxes["duration"].config(text=summary.duration_str())

    def set_idle(self):
        self._status_dot.config(fg=THEME.BORDER)
        self._status_lbl.config(text="No runs yet", fg=THEME.TEXT_SECONDARY)
        for lbl in self._stat_boxes.values():
            lbl.config(text="-")


# ─────────────────────────────────────────────
# LogPanel  - the scrollable terminal-style log
# ─────────────────────────────────────────────
class LogPanel(tk.Frame):
    """
    A dark terminal-style scrollable text area.

    Uses tk.Text in read-only mode with colour tags for each
    log line type. Auto-scrolls to the bottom as new lines arrive.

    Methods
    -------
    append(line)      - add a line (thread-safe via root.after)
    clear()           - wipe all content
    export_text()     - return full log as a plain string
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=THEME.BG_LOG, **kwargs)
        self._line_count = 0
        self._build()

    def _build(self):
        # Toolbar
        toolbar = tk.Frame(self, bg=THEME.BG_DARK)
        toolbar.pack(fill="x")

        tk.Label(toolbar, text="  Cleanup Output",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_SMALL).pack(side="left", pady=4)

        self._line_count_lbl = tk.Label(
            toolbar, text="0 lines",
            bg=THEME.BG_DARK, fg=THEME.BORDER,
            font=THEME.FONT_SMALL)
        self._line_count_lbl.pack(side="right", padx=8)

        # Auto-scroll toggle
        self._autoscroll = tk.BooleanVar(value=True)
        tk.Checkbutton(
            toolbar, text="Auto-scroll",
            variable=self._autoscroll,
            bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
            selectcolor=THEME.BG_CARD,
            activebackground=THEME.BG_DARK,
            font=THEME.FONT_SMALL
        ).pack(side="right")

        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x")

        # Text widget + scrollbar
        text_frame = tk.Frame(self, bg=THEME.BG_LOG)
        text_frame.pack(fill="both", expand=True)

        self._text = tk.Text(
            text_frame,
            bg=THEME.BG_LOG, fg=THEME.TEXT_PRIMARY,
            font=THEME.FONT_MONO,
            wrap="none",
            state="disabled",
            cursor="arrow",
            highlightthickness=0,
            relief="flat",
            padx=10, pady=6,
            selectbackground=THEME.BORDER,
        )

        v_scroll = tk.Scrollbar(text_frame, orient="vertical",
                                command=self._text.yview)
        h_scroll = tk.Scrollbar(text_frame, orient="horizontal",
                                command=self._text.xview)

        self._text.configure(
            yscrollcommand=v_scroll.set,
            xscrollcommand=h_scroll.set
        )

        h_scroll.pack(side="bottom", fill="x")
        v_scroll.pack(side="right",  fill="y")
        self._text.pack(side="left", fill="both", expand=True)

        # Configure colour tags
        self._setup_tags()

    def _setup_tags(self):
        """Register colour tags for different log line types."""
        self._text.tag_configure("success",   foreground=THEME.ACCENT)
        self._text.tag_configure("deleted",   foreground="#A8A8B3")
        self._text.tag_configure("warning",   foreground=THEME.WARN)
        self._text.tag_configure("error",     foreground=THEME.DANGER)
        self._text.tag_configure("header",    foreground="#64D2FF")
        self._text.tag_configure("aborted",   foreground=THEME.DANGER)
        self._text.tag_configure("divider",   foreground=THEME.BORDER)
        self._text.tag_configure("dry_run",   foreground=THEME.WARN)
        self._text.tag_configure("default",   foreground=THEME.TEXT_SECONDARY)
        self._text.tag_configure("timestamp", foreground="#555558")

    def _classify(self, line: str) -> str:
        """Return a tag name based on the content of the log line."""
        if "[OK]" in line:     return "success"
        if "[!]"  in line:   return "warning"
        if "[!!]"  in line:    return "error"
        if "[STOP]"  in line:    return "aborted"
        if "[>]"  in line:    return "success"
        if ">"   in line:    return "header"
        if "[DRY]" in line:  return "dry_run"
        if "[x]"  in line:    return "deleted"
        if line.strip().startswith("="): return "divider"
        return "default"

    def append(self, line: str):
        """
        Add a line to the log.
        Safe to call from any thread - schedules UI update via after().
        """
        # Get root window for after() scheduling
        try:
            root = self.winfo_toplevel()
            root.after(0, lambda l=line: self._append_ui(l))
        except Exception:
            pass

    def _append_ui(self, line: str):
        """Must only be called from the main thread."""
        self._text.configure(state="normal")

        # Trim if over limit
        if self._line_count >= MAX_LOG_LINES:
            self._text.delete("1.0", "2.0")
            self._line_count -= 1

        tag = self._classify(line)

        # Split timestamp from content for separate colouring
        # Lines look like:  [HH:MM:SS]  content
        if line.startswith("[") and "]" in line:
            bracket_end = line.index("]") + 1
            ts      = line[:bracket_end]
            content = line[bracket_end:]
            self._text.insert("end", ts, "timestamp")
            self._text.insert("end", content + "\n", tag)
        else:
            self._text.insert("end", line + "\n", tag)

        self._line_count += 1
        self._line_count_lbl.config(
            text=f"{self._line_count} line{'s' if self._line_count != 1 else ''}")

        self._text.configure(state="disabled")

        if self._autoscroll.get():
            self._text.see("end")

    def clear(self):
        self._text.configure(state="normal")
        self._text.delete("1.0", "end")
        self._text.configure(state="disabled")
        self._line_count = 0
        self._line_count_lbl.config(text="0 lines")

    def export_text(self) -> str:
        return self._text.get("1.0", "end")


# ─────────────────────────────────────────────
# LogFrame  - the full Cleanup Log page
# ─────────────────────────────────────────────
class LogFrame(tk.Frame):
    """
    The Cleanup Log page.

    Layout:
        ┌──────────────────────────────────────┐
        │  Header + action buttons             │
        ├──────────────────────────────────────┤
        │  SummaryCard (last run stats)        │
        ├──────────────────────────────────────┤
        │  LogPanel (scrollable terminal)      │
        └──────────────────────────────────────┘

    Public API for other modules:
        log_frame.get_log_callback()  > thread-safe log_callback
        log_frame.notify_run_started()
        log_frame.notify_run_finished(result)
    """

    def __init__(self, parent, app=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self.app      = app
        self._summary = RunSummary()
        self._build()

    def _build(self):
        # ── header ─────────────────────────────
        header = tk.Frame(self, bg=THEME.BG_DARK)
        header.pack(fill="x", padx=20, pady=(16, 8))

        tk.Label(header, text="Cleanup Output",
                 bg=THEME.BG_DARK, fg=THEME.TEXT_PRIMARY,
                 font=THEME.FONT_SECTION).pack(side="left")

        # Action buttons (right side)
        btn_frame = tk.Frame(header, bg=THEME.BG_DARK)
        btn_frame.pack(side="right")

        self._clear_btn = self._make_btn(
            btn_frame, "[x]  Clear Log",
            command=self._clear_log
        )
        self._clear_btn.pack(side="left", padx=(0, 8))

        self._export_btn = self._make_btn(
            btn_frame, "[D]  Export",
            command=self._export_log
        )
        self._export_btn.pack(side="left")

        # ── summary card ───────────────────────
        self._summary_card = SummaryCard(self)
        self._summary_card.pack(fill="x", padx=20, pady=(0, 10))

        # ── log panel ──────────────────────────
        self._log_panel = LogPanel(self)
        self._log_panel.pack(fill="both", expand=True,
                             padx=20, pady=(0, 12))

        # ── status bar ─────────────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x")
        status_bar = tk.Frame(self, bg=THEME.BG_DARK)
        status_bar.pack(fill="x", padx=20, pady=6)

        self._status_lbl = tk.Label(
            status_bar, text="No cleanup has run yet.",
            bg=THEME.BG_DARK, fg=THEME.TEXT_SECONDARY,
            font=THEME.FONT_SMALL, anchor="w"
        )
        self._status_lbl.pack(side="left")

        self._time_lbl = tk.Label(
            status_bar, text="",
            bg=THEME.BG_DARK, fg=THEME.BORDER,
            font=THEME.FONT_SMALL, anchor="e"
        )
        self._time_lbl.pack(side="right")

    # ── button factory ─────────────────────────
    def _make_btn(self, parent, text, command):
        border = tk.Frame(parent, bg=THEME.BORDER_CARD, padx=1, pady=1)
        btn = tk.Label(border, text=f"  {text}  ",
                       bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                       font=THEME.FONT_BTN, cursor="hand2")
        btn.pack()
        for w in (border, btn):
            w.bind("<Button-1>", lambda _: command())
            w.bind("<Enter>",
                   lambda _, b=btn: b.config(fg=THEME.TEXT_PRIMARY))
            w.bind("<Leave>",
                   lambda _, b=btn: b.config(fg=THEME.TEXT_SECONDARY))
        return border

    # ── public API ─────────────────────────────
    def get_log_callback(self) -> Callable[[str], None]:
        """
        Returns a thread-safe callable to pass as log_callback
        to CleanupEngine.

        Usage:
            engine = CleanupEngine(
                log_callback=log_frame.get_log_callback(),
                dry_run=False
            )
        """
        return self._log_panel.append

    def notify_run_started(self):
        """Call this when a cleanup run begins."""
        self._summary.start()
        self._summary_card.set_running()
        self._status_lbl.config(
            text="[>]  Cleanup running...", fg=THEME.WARN)
        self._time_lbl.config(text="")
        # Navigate to this page automatically
        if self.app and hasattr(self.app, "show_page"):
            self.app.show_page("CleanupLog")

    def notify_run_finished(self, result=None):
        """
        Call this when CleanupEngine finishes.
        result: a CleanupResult from cleanup.py (or None)
        """
        if result:
            self._summary.finish(
                freed_bytes=result.freed_bytes,
                deleted=len(result.deleted_files),
                errors=len(result.errors),
                skipped=len(result.skipped),
            )
        else:
            self._summary.finish()

        self._summary_card.set_finished(self._summary)

        now = datetime.datetime.now().strftime("%H:%M:%S")
        if self._summary.errors > 0:
            self._status_lbl.config(
                text=f"[!]  Finished with {self._summary.errors} error(s)",
                fg=THEME.WARN)
        else:
            self._status_lbl.config(
                text=f"[OK]  Cleanup complete - "
                     f"{self._summary.freed_str()} freed",
                fg=THEME.ACCENT)
        self._time_lbl.config(text=f"Finished at {now}")
        # Save to history
        if result and self.app:
            history_frame = self.app.frames.get("History")
            if history_frame:
                history_frame.add_record(result)

    # ── button handlers ────────────────────────
    def _clear_log(self):
        self._log_panel.clear()
        self._summary_card.set_idle()
        self._summary.reset()
        self._status_lbl.config(
            text="Log cleared.", fg=THEME.TEXT_SECONDARY)
        self._time_lbl.config(text="")

    def _export_log(self):
        """Save log to a text file in ~/Desktop/system-health-monitor/logs/"""
        import os
        log_dir = os.path.expanduser(str(PATHS.LOGS_DIR))
        os.makedirs(log_dir, exist_ok=True)
        ts       = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(log_dir, f"cleanup_{ts}.txt")
        try:
            text = self._log_panel.export_text()
            with open(filename, "w") as f:
                f.write(text)
            self._status_lbl.config(
                text=f"[OK]  Log exported to {filename}",
                fg=THEME.ACCENT)
        except OSError as e:
            self._status_lbl.config(
                text=f"[!!]  Export failed: {e}",
                fg=THEME.DANGER)
        self.after(10000, lambda: self._status_lbl.config(
            text="", fg=THEME.TEXT_SECONDARY))


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    """
    Demo: simulates a cleanup run with fake log lines
    so you can see the full UI without running real cleanup.
    """
    root = tk.Tk()
    root.title("Cleanup Log - Module 6 Test")
    root.geometry("860x600")
    root.minsize(700, 500)
    root.configure(bg=THEME.BG_DARK)

    frame = LogFrame(root)
    frame.pack(fill="both", expand=True)

    # Simulate a cleanup run after 1 second
    def simulate():
        frame.notify_run_started()

        fake_lines = [
            "================================================",
            "[>]  Cleanup started - 2024-01-15 03:00:00",
            "Targets: caches, logs, downloads",
            "================================================",
            "",
            ">  Cleaning: CACHES",
            "   [x]  com.apple.Safari  (42.9 MB)",
            "   [x]  com.google.Chrome  (114.4 MB)",
            "",
            ">  Cleaning: LOGS",
            "   [x]  crash_2024-01-15.crash  (33 KB, 90 days old)",
            "   [x]  system_diagnostic.log  (12 KB, 14 days old)",
            "",
            ">  Cleaning: DOWNLOADS",
            "   [x]  old_installer.pkg  (238.4 MB, 95 days old)",
            "   [x]  archive_2023.zip  (42.9 MB, 200 days old)",
            "   [!]  Permission denied: locked_file.dmg",
            "",
            "================================================",
            "[OK]  Done - Freed 438.7 MB · 6 files deleted"
            " · 1 error · 4s",
            "================================================",
        ]

        import time

        class FakeResult:
            freed_bytes   = int(438.7 * 1024**2)
            deleted_files = ["a","b","c","d","e","f"]
            errors        = [("locked_file.dmg", "Permission denied")]
            skipped       = []

        def stream_lines(lines, idx=0):
            if idx < len(lines):
                frame.get_log_callback()(lines[idx])
                root.after(120, lambda: stream_lines(lines, idx + 1))
            else:
                frame.notify_run_finished(FakeResult())

        stream_lines(fake_lines)

    root.after(800, simulate)
    root.mainloop()


# ─────────────────────────────────────────────
# Test suite  (python log_view.py --test)
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 52)
    print("Module 6 - log_view.py test suite")
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

    # 1. RunSummary logic
    s = RunSummary()
    check("initial not running", not s.running)

    s.start()
    check("after start running",  s.running)
    check("started_at set",       s.started_at is not None)

    import time as _time
    _time.sleep(0.05)
    s.finish(freed_bytes=5*1024**2, deleted=10, errors=2, skipped=3)
    check("after finish not running", not s.running)
    check("freed_str MB",         s.freed_str() == "5.0 MB")
    check("duration > 0",         s.duration_str() != "-")
    check("deleted count",        s.deleted == 10)
    check("error count",          s.errors == 2)

    s2 = RunSummary()
    s2.finish(freed_bytes=2*1024**3)
    check("freed_str GB",  s2.freed_str() == "2.00 GB")
    s3 = RunSummary()
    s3.finish(freed_bytes=512*1024)
    check("freed_str KB",  s3.freed_str() == "512 KB")
    s4 = RunSummary()
    s4.finish(freed_bytes=999)
    check("freed_str B",   s4.freed_str() == "999 B")

    # 2. LogPanel tag classification (no display needed)
    class FakeLogPanel:
        def _classify(self, line):
            if "[OK]" in line:     return "success"
            if "[!]" in line:    return "warning"
            if "[!!]" in line:     return "error"
            if "[STOP]" in line:     return "aborted"
            if "[>]" in line:     return "success"
            if ">" in line:      return "header"
            if "[DRY]" in line:  return "dry_run"
            if "[x]" in line:     return "deleted"
            if line.strip().startswith("="): return "divider"
            return "default"

    lp = FakeLogPanel()
    check("classify success",  lp._classify("[10:00:00]  [OK]  Done") == "success")
    check("classify deleted",  lp._classify("   [x]  file.txt") == "deleted")
    check("classify warning",  lp._classify("   [!]  Permission") == "warning")
    check("classify error",    lp._classify("   [!!]  Failed") == "error")
    check("classify header",   lp._classify(">  Cleaning") == "header")
    check("classify divider",  lp._classify("====") == "divider")
    check("classify dry_run",  lp._classify("[DRY] [x] file") == "dry_run")
    check("classify default",  lp._classify("some line") == "default")

    # 3. Tkinter widget instantiation
    try:
        root = tk.Tk()
        root.withdraw()

        # SummaryCard
        sc = SummaryCard(root)
        sc.set_running()
        check("SummaryCard running", True)
        s_test = RunSummary()
        s_test.start(); s_test.finish(freed_bytes=1024**2, deleted=5)
        sc.set_finished(s_test)
        check("SummaryCard finished", True)
        sc.set_idle()
        check("SummaryCard idle", True)

        # LogPanel
        lp_widget = LogPanel(root)
        lp_widget._append_ui("[10:00:00]  [>]  Test line")
        check("LogPanel append",
              lp_widget._line_count == 1)
        lp_widget._append_ui("[10:00:01]  [OK]  Success line")
        check("LogPanel count 2",
              lp_widget._line_count == 2)
        exported = lp_widget.export_text()
        check("LogPanel export non-empty", len(exported) > 0)
        lp_widget.clear()
        check("LogPanel clear", lp_widget._line_count == 0)

        # LogFrame
        lf = LogFrame(root)
        cb = lf.get_log_callback()
        check("get_log_callback callable", callable(cb))

        lf.notify_run_started()
        check("notify_run_started", lf._summary.running)

        class FakeResult:
            freed_bytes   = 2 * 1024**2
            deleted_files = ["a", "b"]
            errors        = []
            skipped       = ["c"]

        lf.notify_run_finished(FakeResult())
        check("notify_run_finished",
              lf._summary.freed_str() == "2.0 MB")
        check("deleted count after finish",
              lf._summary.deleted == 2)

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
