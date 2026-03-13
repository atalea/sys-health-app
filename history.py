"""
System Health Monitor
==================
Module 7: history.py
Responsibility: Cleanup History page - persists every cleanup run to disk,
                displays a sortable list of past runs, and shows a
                detail panel for each run.

Storage:
    ~/Desktop/system-health-monitor/history.txt
    Human-readable text blocks, newest first.
    Max MAX_HISTORY_RECORDS records kept (oldest pruned automatically).

How it plugs into main.py:
    from history import HistoryFrame
    app.register_frame("History", HistoryFrame(app.content, app))

How log_view.py writes to it:
    from history import HistoryStore
    store = HistoryStore()
    store.append(result)   # pass a CleanupResult from cleanup.py
"""

import tkinter as tk
import datetime
import os
import re
import sys
from pathlib import Path
from typing import Optional, List

# ─────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────
from app_config import THEME, PATHS, CONSTANTS, bind_scroll, _pick_font

BG_DARK        = THEME.BG_DARK
BG_CARD        = THEME.BG_CARD
BG_ROW         = THEME.BG_ROW
BG_ROW_SEL     = THEME.BG_ROW_SEL
BG_ROW_HOVER   = THEME.BG_ROW_HOVER
ACCENT         = THEME.ACCENT
ACCENT_DIM     = THEME.ACCENT_DIM
WARN           = THEME.WARN
DANGER         = THEME.DANGER
BLUE           = THEME.BLUE
TEXT_PRIMARY   = THEME.TEXT_PRIMARY
TEXT_SECONDARY = THEME.TEXT_SECONDARY
BORDER         = THEME.BORDER
BORDER_CARD    = THEME.BORDER_CARD

FONT_SECTION   = THEME.FONT_SECTION
FONT_TITLE     = THEME.FONT_TITLE
FONT_BODY      = THEME.FONT_BODY
FONT_DETAIL    = THEME.FONT_DETAIL
FONT_SMALL     = THEME.FONT_SMALL
FONT_MONO      = THEME.FONT_MONO
FONT_BTN       = THEME.FONT_BTN

MAX_HISTORY_RECORDS = CONSTANTS.MAX_HISTORY_RECORDS
HISTORY_FILE        = str(PATHS.HISTORY_FILE)


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def _bytes_to_human(n: int) -> str:
    if n >= 1024 ** 3: return f"{n/1024**3:.2f} GB"
    if n >= 1024 ** 2: return f"{n/1024**2:.1f} MB"
    if n >= 1024:      return f"{n/1024:.0f} KB"
    return f"{n} B"


def _fmt_dt(iso: str) -> str:
    """Format ISO datetime string to human-readable."""
    try:
        dt = datetime.datetime.fromisoformat(iso)
        return dt.strftime("%b %d, %Y  %H:%M")
    except Exception:
        return iso


def _duration_str(started: str, finished: str) -> str:
    try:
        s = datetime.datetime.fromisoformat(started)
        f = datetime.datetime.fromisoformat(finished)
        secs = int((f - s).total_seconds())
        return f"{secs}s" if secs < 60 else f"{secs//60}m {secs%60}s"
    except Exception:
        return "-"


def _human_to_bytes(s: str) -> int:
    """Convert human size string back to approximate bytes."""
    try:
        s = s.strip().lstrip("~")
        if "GB" in s: return int(float(s.replace("GB","").strip()) * 1024**3)
        if "MB" in s: return int(float(s.replace("MB","").strip()) * 1024**2)
        if "KB" in s: return int(float(s.replace("KB","").strip()) * 1024)
        if "B"  in s: return int(float(s.replace("B","").strip()))
    except Exception:
        pass
    return 0


def _safe_int(s: str) -> int:
    try: return int(s.strip())
    except Exception: return 0


# ─────────────────────────────────────────────
# HistoryStore  - reads/writes history.json
# ─────────────────────────────────────────────
class HistoryStore:
    """
    Persists cleanup run records to ~/Desktop/system-health-monitor/history.txt.

    Each run is stored as a human-readable block separated by === markers.
    Records are stored newest-first.

    Format:
        === Cleanup Run - Mar 11, 2026  05:06 ===
        Trigger:  manual
        Targets:  caches, logs, downloads
        Freed:    2.7 MB
        Files:    1
        Errors:   0
        Duration: 4s
        Summary:  Freed 2.7 MB · 1 files deleted · 0 errors · 4s
        Started:  2026-03-11T05:06:25
        Finished: 2026-03-11T05:06:29
        ===
    """

    BLOCK_SEP = "==="

    def __init__(self, path: str = HISTORY_FILE):
        self.path = path
        self._cache: list = []   # in-memory fallback if file is deleted
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    # ── serialise ──────────────────────────────
    def _record_to_text(self, record: dict) -> str:
        started  = record.get("started_at", "")
        finished = record.get("finished_at", "")
        freed_b  = record.get("freed_bytes", 0)
        targets  = record.get("targets_run", [])

        try:
            dt_label = datetime.datetime.fromisoformat(started).strftime(
                "%b %d, %Y  %H:%M")
        except Exception:
            dt_label = started

        lines = [
            f"=== Cleanup Run - {dt_label} ===",
            f"Targets:  {', '.join(targets) if targets else '-'}",
            f"Freed:    {_bytes_to_human(freed_b)}",
            f"Files:    {record.get('deleted_count', 0)}",
            f"Errors:   {record.get('error_count', 0)}",
            f"Duration: {_duration_str(started, finished)}",
            f"Summary:  {record.get('summary', '')}",
            f"Started:  {started}",
            f"Finished: {finished}",
            "===",
            "",
        ]
        return "\n".join(lines)

    # ── deserialise ────────────────────────────
    def _text_to_record(self, block: str) -> dict:
        """Parse one === block back into a dict."""
        record = {}
        for line in block.strip().splitlines():
            line = line.strip()
            if line.startswith("===") or not line:
                continue
            if ":" in line:
                key, _, val = line.partition(":")
                key = key.strip().lower()
                val = val.strip()
                if key == "targets":
                    record["targets_run"] = (
                        [t.strip() for t in val.split(",")]
                        if val and val != "-" else [])
                elif key == "freed":
                    record["freed_str"] = val
                    # Convert back to bytes approximately
                    record["freed_bytes"] = _human_to_bytes(val)
                elif key == "files":
                    record["deleted_count"] = _safe_int(val)
                elif key == "errors":
                    record["error_count"] = _safe_int(val)
                elif key == "duration":
                    record["duration"] = val
                elif key == "summary":
                    record["summary"] = val
                elif key == "started":
                    record["started_at"] = val
                elif key == "finished":
                    record["finished_at"] = val
        return record

    # ── public API ─────────────────────────────
    def load(self) -> List[dict]:
        """Return list of run records, newest first."""
        try:
            with open(self.path, "r") as f:
                text = f.read()
        except FileNotFoundError:
            return list(self._cache)  # file deleted - serve from memory

        records = []
        blocks = re.findall(
            r"(=== Cleanup Run.*?^===)",
            text, re.DOTALL | re.MULTILINE)
        for block in blocks:
            record = self._text_to_record(block)
            if record.get("started_at"):
                records.append(record)
        self._cache = list(records)   # keep cache fresh on every read
        return records

    def append(self, record: dict):
        """
        Add a new run record to the top of the file.
        Accepts a dict (from CleanupResult.to_dict()) or
        a CleanupResult object directly.
        """
        if hasattr(record, "to_dict"):
            record = record.to_dict()

        # Read existing content
        try:
            with open(self.path, "r") as f:
                existing = f.read()
        except FileNotFoundError:
            existing = ""

        new_block = self._record_to_text(record)

        # Prepend new block
        self._ensure_dir()
        with open(self.path, "w") as f:
            f.write(new_block)
            if existing.strip():
                f.write(existing)

        # Prune if over limit
        records = self.load()
        if len(records) > MAX_HISTORY_RECORDS:
            self._save_all(records[:MAX_HISTORY_RECORDS])


    def parse_file(self, path: str) -> List[dict]:
        """
        Parse any history .txt file and return records.
        Used for the Import flow - does NOT overwrite the current store.
        """
        try:
            with open(path, "r") as f:
                text = f.read()
        except OSError:
            return []

        records = []
        blocks = re.findall(
            r"(=== Cleanup Run.*?^===)",
            text, re.DOTALL | re.MULTILINE)
        for block in blocks:
            record = self._text_to_record(block)
            if record.get("started_at"):
                records.append(record)
        return records

    def merge_import(self, imported: list):
        """
        Merge imported records into the current store.
        Deduplicates by started_at - existing records are never overwritten.
        Saves to disk after merging.
        """
        existing = self.load()
        existing_keys = {r.get("started_at") for r in existing}
        new_records = [r for r in imported
                       if r.get("started_at") not in existing_keys]
        if not new_records:
            return 0  # nothing new

        merged = new_records + existing   # imported go to top (newest-first)
        # Re-sort by started_at descending
        def _sort_key(r):
            try:
                return r.get("started_at", "")
            except Exception:
                return ""
        merged.sort(key=_sort_key, reverse=True)
        if len(merged) > MAX_HISTORY_RECORDS:
            merged = merged[:MAX_HISTORY_RECORDS]
        self._save_all(merged)
        self._cache = list(merged)
        return len(new_records)

    def clear(self):
        self._ensure_dir()
        with open(self.path, "w") as f:
            f.write("")

    def _save_all(self, records: list):
        self._ensure_dir()
        with open(self.path, "w") as f:
            for r in records:
                f.write(self._record_to_text(r))

    def count(self) -> int:
        return len(self.load())


# ─────────────────────────────────────────────
# DetailPanel  - right side run detail view
# ─────────────────────────────────────────────
class DetailPanel(tk.Frame):
    """
    Shows the details of a selected run record on the right side.
    Displays: date, duration, space freed, files deleted,
              errors, targets run.
    """

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=BG_CARD, **kwargs)
        self._build_empty()

    def _build_empty(self):
        """Show placeholder when nothing is selected."""
        for w in self.winfo_children():
            w.destroy()

        tk.Label(self, text="Select a run\nto see details",
                 bg=BG_CARD, fg=BORDER,
                 font=_pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 13),
                 justify="center").pack(expand=True)

    def show(self, record: dict):
        """Populate with data from a history record."""
        for w in self.winfo_children():
            w.destroy()

        # ── header ─────────────────────────────
        header = tk.Frame(self, bg=BG_CARD, padx=20, pady=16)
        header.pack(fill="x")

        started = record.get("started_at", "")
        tk.Label(header,
                 text=_fmt_dt(started),
                 bg=BG_CARD, fg=TEXT_PRIMARY,
                 font=FONT_TITLE).pack(anchor="w")

        trigger = record.get("targets_run", [])
        trigger_str = ", ".join(trigger) if trigger else "-"
        tk.Label(header,
                 text=f"Targets: {trigger_str}",
                 bg=BG_CARD, fg=TEXT_SECONDARY,
                 font=FONT_SMALL).pack(anchor="w", pady=(2, 0))

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── stat rows ──────────────────────────
        stats = tk.Frame(self, bg=BG_CARD, padx=20, pady=14)
        stats.pack(fill="x")

        freed   = record.get("freed_bytes", 0)
        deleted = record.get("deleted_count", 0)
        errors  = record.get("error_count", 0)
        finished = record.get("finished_at", "")
        duration = _duration_str(started, finished)

        rows = [
            ("Space Freed",    _bytes_to_human(freed),  ACCENT),
            ("Files Deleted",  str(deleted),             TEXT_PRIMARY),
            ("Errors",         str(errors),
             DANGER if errors > 0 else TEXT_SECONDARY),
            ("Duration",       duration,                 TEXT_SECONDARY),
        ]

        for label, value, color in rows:
            row = tk.Frame(stats, bg=BG_CARD)
            row.pack(fill="x", pady=4)
            tk.Label(row, text=label,
                     bg=BG_CARD, fg=TEXT_SECONDARY,
                     font=FONT_DETAIL, width=14,
                     anchor="w").pack(side="left")
            tk.Label(row, text=value,
                     bg=BG_CARD, fg=color,
                     font=FONT_TITLE,
                     anchor="w").pack(side="left")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        # ── summary text ───────────────────────
        summary = record.get("summary", "")
        if summary:
            sum_frame = tk.Frame(self, bg=BG_CARD, padx=20, pady=12)
            sum_frame.pack(fill="x")
            tk.Label(sum_frame, text="Summary",
                     bg=BG_CARD, fg=TEXT_SECONDARY,
                     font=FONT_SMALL).pack(anchor="w")
            tk.Label(sum_frame, text=summary,
                     bg=BG_CARD, fg=TEXT_PRIMARY,
                     font=FONT_DETAIL,
                     wraplength=220, justify="left",
                     anchor="w").pack(anchor="w", pady=(4, 0))

        # ── status badge ───────────────────────
        badge_frame = tk.Frame(self, bg=BG_CARD, padx=20, pady=8)
        badge_frame.pack(fill="x")
        if errors > 0:
            badge_text  = f"[!]  Completed with {errors} error(s)"
            badge_color = WARN
        else:
            badge_text  = "[OK]  Completed successfully"
            badge_color = ACCENT
        tk.Label(badge_frame, text=badge_text,
                 bg=BG_CARD, fg=badge_color,
                 font=FONT_DETAIL).pack(anchor="w")


# ─────────────────────────────────────────────
# HistoryRow  - one row in the run list
# ─────────────────────────────────────────────
class HistoryRow(tk.Frame):
    """A single row in the history list."""

    def __init__(self, parent, record: dict,
                 on_select=None, selected=False, **kwargs):
        super().__init__(parent, bg=BG_ROW_SEL if selected else BG_ROW,
                         **kwargs)
        self.record    = record
        self.on_select = on_select
        self._selected = selected
        self._build()
        self._bind_hover()

    def _build(self):
        content = tk.Frame(self,
                           bg=BG_ROW_SEL if self._selected else BG_ROW)
        content.pack(fill="x", padx=12, pady=8)

        # Date + time
        started  = record = self.record.get("started_at", "")
        date_str = _fmt_dt(started)
        tk.Label(content, text=date_str,
                 bg=content["bg"], fg=TEXT_PRIMARY,
                 font=FONT_DETAIL, anchor="w").pack(anchor="w")

        # Stats row
        freed   = self.record.get("freed_bytes", 0)
        deleted = self.record.get("deleted_count", 0)
        errors  = self.record.get("error_count", 0)

        stats_row = tk.Frame(content, bg=content["bg"])
        stats_row.pack(anchor="w", pady=(2, 0))

        # Freed badge
        freed_lbl = tk.Label(
            stats_row,
            text=f"  {_bytes_to_human(freed)}  ",
            bg=ACCENT_DIM, fg=ACCENT,
            font=FONT_SMALL)
        freed_lbl.pack(side="left", padx=(0, 6))

        tk.Label(stats_row,
                 text=f"{deleted} files",
                 bg=content["bg"], fg=TEXT_SECONDARY,
                 font=FONT_SMALL).pack(side="left", padx=(0, 6))

        if errors > 0:
            tk.Label(stats_row,
                     text=f"{errors} errors",
                     bg=content["bg"], fg=WARN,
                     font=FONT_SMALL).pack(side="left")

        # Divider
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

    def _bind_hover(self):
        def enter(_):
            if not self._selected:
                self._set_bg(BG_ROW_HOVER)

        def leave(_):
            if not self._selected:
                self._set_bg(BG_ROW)

        def click(_):
            if self.on_select:
                self.on_select(self.record)

        for w in self._iter_widgets():
            w.bind("<Enter>",    enter)
            w.bind("<Leave>",    leave)
            w.bind("<Button-1>", click)

    def _iter_widgets(self):
        """Yield self and all descendant widgets."""
        yield self
        stack = list(self.winfo_children())
        while stack:
            w = stack.pop()
            yield w
            stack.extend(w.winfo_children())

    def _set_bg(self, color):
        for w in self._iter_widgets():
            try:
                w.config(bg=color)
            except tk.TclError:
                pass

    def set_selected(self, val: bool):
        self._selected = val
        self._set_bg(BG_ROW_SEL if val else BG_ROW)


# ─────────────────────────────────────────────
# HistoryFrame  - the full History page
# ─────────────────────────────────────────────
class HistoryFrame(tk.Frame):
    """
    The History page.

    Layout:
        ┌─────────────────┬──────────────────┐
        │  Run list       │  Detail panel    │
        │  (scrollable)   │  (selected run)  │
        │                 │                  │
        └─────────────────┴──────────────────┘

    Public API:
        history_frame.add_record(result)  - called by log_view after a run
    """

    def __init__(self, parent, app=None, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self.app          = app
        self._store       = HistoryStore()
        self._rows: List[HistoryRow] = []
        self._selected_record = None
        self._build()
        self._load_records()

    def _build(self):
        # ── page header ────────────────────────
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=20, pady=(16, 10))

        tk.Label(header, text="Cleanup History",
                 bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=FONT_SECTION).pack(side="left")

        # Action buttons
        btn_frame = tk.Frame(header, bg=BG_DARK)
        btn_frame.pack(side="right")

        self._import_btn = self._make_btn(
            btn_frame, "[F]  Import",
            command=self._import_history)
        self._import_btn.pack(side="left", padx=(0, 8))

        self._export_btn = self._make_btn(
            btn_frame, "[D]  Export",
            command=self._export_history)
        self._export_btn.pack(side="left", padx=(0, 8))

        self._clear_btn = self._make_btn(
            btn_frame, "[x]  Clear History",
            command=self._confirm_clear)
        self._clear_btn.pack(side="left")

        # ── main content: list | detail ─────────
        self._content_frame = tk.Frame(self, bg=BG_DARK)
        content = self._content_frame
        content.pack(fill="both", expand=True, padx=20, pady=(0, 12))

        # Left: run list
        list_container = tk.Frame(content, bg=BG_DARK)
        list_container.pack(side="left", fill="both",
                            expand=True, padx=(0, 10))

        # Stats bar above list
        self._stats_bar = tk.Label(
            list_container, text="",
            bg=BG_DARK, fg=TEXT_SECONDARY,
            font=FONT_SMALL, anchor="w")
        self._stats_bar.pack(fill="x", pady=(0, 6))

        # Scrollable list
        list_border = tk.Frame(list_container, bg=BORDER_CARD,
                               padx=1, pady=1)
        list_border.pack(fill="both", expand=True)

        list_inner = tk.Frame(list_border, bg=BG_DARK)
        list_inner.pack(fill="both", expand=True, padx=1, pady=1)

        self._canvas = tk.Canvas(list_inner, bg=BG_ROW,
                                 highlightthickness=0)
        scrollbar = tk.Scrollbar(list_inner, orient="vertical",
                                 command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._list_frame = tk.Frame(self._canvas, bg=BG_ROW)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._list_frame, anchor="nw")

        self._canvas.bind(
            "<Configure>",
            lambda e: self._canvas.itemconfig(
                self._canvas_win, width=e.width))
        self._list_frame.bind(
            "<Configure>",
            lambda e: self._canvas.configure(
                scrollregion=self._canvas.bbox("all")))
        # Two-finger / mousewheel scroll (macOS trackpad safe)
        bind_scroll(self._canvas,
                    lambda d: self._canvas.yview_scroll(d, "units"))

        # Right: detail panel
        detail_border = tk.Frame(content, bg=BORDER_CARD,
                                 padx=1, pady=1,
                                 width=260)
        detail_border.pack(side="right", fill="y")
        detail_border.pack_propagate(False)

        self._detail = DetailPanel(detail_border)
        self._detail.pack(fill="both", expand=True,
                          padx=1, pady=1)

        # ── empty state ────────────────────────
        self._empty_lbl = tk.Label(
            self._list_frame,
            text="No cleanup runs yet.\n\n"
                 "Go to Scheduler and run a cleanup\n"
                 "to see your history here.",
            bg=BG_ROW, fg=BORDER,
            font=_pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 12),
            justify="center")

    def _make_btn(self, parent, text, command):
        border = tk.Frame(parent, bg=BORDER_CARD, padx=1, pady=1)
        btn = tk.Label(border, text=f"  {text}  ",
                       bg=BG_CARD, fg=TEXT_SECONDARY,
                       font=FONT_BTN, cursor="hand2")
        btn.pack()
        for w in (border, btn):
            w.bind("<Button-1>", lambda _: command())
            w.bind("<Enter>",
                   lambda _, b=btn: b.config(fg=TEXT_PRIMARY))
            w.bind("<Leave>",
                   lambda _, b=btn: b.config(fg=TEXT_SECONDARY))
        return border

    # ── data loading ───────────────────────────
    def _load_records(self):
        """Load records from disk and render the list."""
        records = self._store.load()
        self._check_file_deleted(records)
        self._render_list(records)

    def _check_file_deleted(self, records: list):
        """Warn if history file is missing but we have cached data."""
        file_exists = os.path.exists(self._store.path)
        has_cache   = len(self._store._cache) > 0
        if not file_exists and has_cache:
            self._show_file_deleted_banner()
        else:
            self._hide_file_deleted_banner()

    def _show_file_deleted_banner(self):
        if hasattr(self, "_deleted_banner") and self._deleted_banner.winfo_exists():
            return
        self._deleted_banner = tk.Frame(self, bg=WARN)
        self._deleted_banner.pack(fill="x", before=self._content_frame)
        msg = tk.Frame(self._deleted_banner, bg=WARN, padx=20, pady=8)
        msg.pack(fill="x")
        tk.Label(msg,
                 text="[!]  history.txt was deleted - showing last known history from memory.",
                 bg=WARN, fg=BG_DARK,
                 font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 10, "bold")).pack(side="left")
        restore_lbl = tk.Label(msg, text="  Restore File  ",
                               bg=BG_DARK, fg=WARN,
                               font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 10, "bold"),
                               cursor="hand2")
        restore_lbl.pack(side="right")
        restore_lbl.bind("<Button-1>", lambda _: self._restore_history_file())

    def _hide_file_deleted_banner(self):
        if hasattr(self, "_deleted_banner") and self._deleted_banner.winfo_exists():
            self._deleted_banner.destroy()

    def _restore_history_file(self):
        """Write cached records back to disk."""
        records = self._store._cache
        if records:
            self._store._save_all(records)
        self._hide_file_deleted_banner()
        self._load_records()

    def _render_list(self, records: list):
        """Clear and redraw all rows."""
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._rows.clear()

        if not records:
            self._empty_lbl = tk.Label(
                self._list_frame,
                text="No cleanup runs yet.\n\n"
                     "Go to Scheduler and run a cleanup\n"
                     "to see your history here.",
                bg=BG_ROW, fg=BORDER,
                font=_pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 12),
                justify="center")
            self._empty_lbl.pack(expand=True, pady=40)
            self._detail._build_empty()
            self._update_stats(records)
            return

        self._update_stats(records)

        for i, record in enumerate(records):
            selected = (record is self._selected_record or
                        (i == 0 and self._selected_record is None))
            row = HistoryRow(
                self._list_frame, record,
                on_select=self._on_select,
                selected=selected
            )
            row.pack(fill="x")
            self._rows.append(row)

        # Auto-select first row
        if records and self._selected_record is None:
            self._on_select(records[0])

    def _update_stats(self, records: list):
        if not records:
            self._stats_bar.config(text="No runs yet")
            return
        total_freed = sum(r.get("freed_bytes", 0) for r in records)
        self._stats_bar.config(
            text=f"{len(records)} runs  -  "
                 f"{_bytes_to_human(total_freed)} total freed")

    def _on_select(self, record: dict):
        self._selected_record = record
        for row in self._rows:
            row.set_selected(row.record is record)
        self._detail.show(record)

    # ── public API ─────────────────────────────
    def add_record(self, result):
        """
        Called by log_view after a cleanup run finishes.
        Accepts a CleanupResult object or a dict.
        """
        if hasattr(result, "to_dict"):
            record = result.to_dict()
        else:
            record = result

        self._store.append(record)
        self._selected_record = None   # auto-select new record
        self._load_records()

    # ── clear history ──────────────────────────
    def _export_history(self):
        """Export full history to a timestamped .txt in the logs folder."""
        records = self._store.load()
        if not records:
            self._show_status("Nothing to export - no history yet.", WARN)
            return
        log_dir = str(PATHS.LOGS_DIR)
        os.makedirs(log_dir, exist_ok=True)
        import datetime as _dt
        ts       = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(log_dir, f"history_export_{ts}.txt")
        try:
            with open(filename, "w") as f:
                f.write("System Health Monitor - Cleanup History Export\n")
                f.write(f"Exported: {_dt.datetime.now().strftime('%b %d, %Y  %H:%M')}\n")
                f.write(f"Total runs: {len(records)}\n")
                f.write("=" * 48 + "\n\n")
                for r in records:
                    f.write(self._store._record_to_text(r))
            self._show_status(f"[OK]  Exported to logs/history_export_{ts}.txt", ACCENT)
        except OSError as e:
            self._show_status(f"[!!]  Export failed: {e}", DANGER)

    def _import_history(self):
        """Open a file picker to import a history .txt file."""
        import tkinter.filedialog as fd

        path = fd.askopenfilename(
            title="Import History File",
            filetypes=[
                ("History files", "history*.txt"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
            parent=self.winfo_toplevel(),
        )
        if not path:
            return  # user cancelled

        imported = self._store.parse_file(path)
        if not imported:
            self._show_status("[!!]  No valid records found in that file.", DANGER)
            return

        added = self._store.merge_import(imported)
        if added == 0:
            self._show_status("ℹ️  All records already exist - nothing new imported.", TEXT_SECONDARY)
        else:
            self._show_status(f"[OK]  Imported {added} new run(s) from file.", ACCENT)

        self._selected_record = None
        self._load_records()

    def _show_status(self, msg: str, color: str):
        """Temporarily show a message in the stats bar."""
        self._stats_bar.config(text=msg, fg=color)
        self.after(4000, lambda: self._update_stats(self._store.load()))

    def _confirm_clear(self):
        """Show a simple confirmation dialog before clearing."""
        confirm = tk.Toplevel(self)
        confirm.title("Clear History")
        confirm.resizable(False, False)
        confirm.configure(bg=BG_DARK)
        confirm.transient(self)
        confirm.grab_set()

        tk.Label(confirm,
                 text="Clear all cleanup history?",
                 bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=FONT_TITLE,
                 padx=24, pady=20).pack()
        tk.Label(confirm,
                 text="This cannot be undone.",
                 bg=BG_DARK, fg=TEXT_SECONDARY,
                 font=FONT_DETAIL).pack(pady=(0, 16))

        btn_row = tk.Frame(confirm, bg=BG_DARK, padx=20, pady=12)
        btn_row.pack()

        # Cancel
        cancel_b = tk.Frame(btn_row, bg=BORDER_CARD, padx=1, pady=1)
        cancel_b.pack(side="left", padx=(0, 10))
        cancel_l = tk.Label(cancel_b, text="  Cancel  ",
                            bg=BG_CARD, fg=TEXT_SECONDARY,
                            font=FONT_BTN, cursor="hand2")
        cancel_l.pack()
        for w in (cancel_b, cancel_l):
            w.bind("<Button-1>",
                   lambda _: (confirm.grab_release(),
                               confirm.destroy()))

        # Clear
        clear_b = tk.Frame(btn_row, bg=DANGER, padx=1, pady=1)
        clear_b.pack(side="left")
        clear_l = tk.Label(clear_b, text="  Clear All  ",
                           bg=DANGER, fg=BG_DARK,
                           font=FONT_BTN, cursor="hand2")
        clear_l.pack()
        for w in (clear_b, clear_l):
            w.bind("<Button-1>", lambda _: self._do_clear(confirm))

        # Centre over parent
        confirm.update_idletasks()
        px = self.winfo_rootx()
        py = self.winfo_rooty()
        pw = self.winfo_width()
        ph = self.winfo_height()
        ww = confirm.winfo_width()
        wh = confirm.winfo_height()
        confirm.geometry(
            f"+{px+(pw-ww)//2}+{py+(ph-wh)//2}")

    def _do_clear(self, dialog):
        dialog.grab_release()
        dialog.destroy()
        self._store.clear()
        self._selected_record = None
        self._render_list([])


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    """Demo with fake history records."""
    root = tk.Tk()
    root.title("History - Module 7 Test")
    root.geometry("900x600")
    root.minsize(700, 500)
    root.configure(bg=BG_DARK)

    frame = HistoryFrame(root)
    frame.pack(fill="both", expand=True)

    # Inject fake records so we can see the UI
    import random
    now = datetime.datetime.now()
    fake_records = []
    for i in range(8):
        started  = now - datetime.timedelta(days=i*3, hours=random.randint(0,5))
        finished = started + datetime.timedelta(seconds=random.randint(3, 45))
        freed    = random.randint(1, 500) * 1024**2
        deleted  = random.randint(1, 20)
        errors   = random.choice([0, 0, 0, 1, 2])
        targets  = random.choice([
            ["caches", "logs"],
            ["caches", "logs", "downloads"],
            ["caches"],
        ])
        fake_records.append({
            "started_at":    started.isoformat(),
            "finished_at":   finished.isoformat(),
            "freed_bytes":   freed,
            "freed_str":     _bytes_to_human(freed),
            "deleted_count": deleted,
            "error_count":   errors,
            "targets_run":   targets,
            "summary":       (f"Freed {_bytes_to_human(freed)} · "
                              f"{deleted} files deleted · "
                              f"{errors} errors"),
        })

    frame._render_list(fake_records)
    root.mainloop()


# ─────────────────────────────────────────────
# Test suite  (python history.py --test)
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 52)
    print("Module 7 - history.py test suite")
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

    import tempfile, shutil

    # 1. _bytes_to_human
    check("500 B",   _bytes_to_human(500)        == "500 B")
    check("2 KB",    _bytes_to_human(2048)        == "2 KB")
    check("5.0 MB",  _bytes_to_human(5*1024**2)  == "5.0 MB")
    check("2.00 GB", _bytes_to_human(2*1024**3)  == "2.00 GB")

    # 2. _fmt_dt
    iso = "2024-01-15T03:00:00"
    result = _fmt_dt(iso)
    check("_fmt_dt non-empty",   len(result) > 0)
    check("_fmt_dt contains year", "2024" in result)
    check("_fmt_dt bad input",   _fmt_dt("bad") == "bad")

    # 3. _duration_str
    s = "2024-01-15T03:00:00"
    f = "2024-01-15T03:00:45"
    check("duration 45s",  _duration_str(s, f) == "45s")
    s2 = "2024-01-15T03:00:00"
    f2 = "2024-01-15T03:02:30"
    check("duration 2m30s", _duration_str(s2, f2) == "2m 30s")
    check("duration bad",   _duration_str("x","y") == "-")

    # 4. HistoryStore with temp file
    tmp_dir  = tempfile.mkdtemp()
    tmp_file = os.path.join(tmp_dir, "history.txt")
    store    = HistoryStore(path=tmp_file)

    check("empty load",  store.load() == [])
    check("count 0",     store.count() == 0)

    record1 = {
        "started_at":    "2024-01-15T03:00:00",
        "finished_at":   "2024-01-15T03:00:45",
        "freed_bytes":   5 * 1024**2,
        "freed_str":     "5.0 MB",
        "deleted_count": 3,
        "error_count":   0,
        "targets_run":   ["caches", "logs"],
        "summary":       "Freed 5.0 MB · 3 files · 0 errors · 45s",
    }
    store.append(record1)
    check("count after 1", store.count() == 1)

    record2 = {**record1, "freed_bytes": 10*1024**2, "deleted_count": 7}
    store.append(record2)
    loaded = store.load()
    check("count after 2",     len(loaded) == 2)
    check("newest first",      loaded[0]["freed_bytes"] == 10*1024**2)
    check("oldest second",     loaded[1]["freed_bytes"] == 5*1024**2)

    # Test MAX_HISTORY_RECORDS pruning with temp store
    store2 = HistoryStore(path=os.path.join(tmp_dir, "hist2.json"))
    for i in range(5):
        store2.append({**record1, "freed_bytes": i * 1024**2})
    check("pruning keeps all 5", store2.count() == 5)

    # Clear
    store.clear()
    check("clear works", store.count() == 0)

    # Test append with object that has to_dict()
    class FakeResult:
        freed_bytes   = 1024**2
        deleted_files = ["a", "b"]
        errors        = []
        skipped       = []
        targets_run   = ["caches"]
        started_at    = datetime.datetime.now()
        finished_at   = datetime.datetime.now()

        def to_dict(self):
            return {
                "started_at":    self.started_at.isoformat(),
                "finished_at":   self.finished_at.isoformat(),
                "freed_bytes":   self.freed_bytes,
                "freed_str":     "1.0 MB",
                "deleted_count": len(self.deleted_files),
                "error_count":   len(self.errors),
                "targets_run":   self.targets_run,
                "summary":       "Freed 1.0 MB · 2 files · 0 errors",
            }

    store.append(FakeResult())
    check("append CleanupResult object", store.count() == 1)

    shutil.rmtree(tmp_dir)

    # 5. Tkinter widgets
    try:
        root = tk.Tk()
        root.withdraw()

        # DetailPanel
        dp = DetailPanel(root)
        check("DetailPanel created", True)
        dp.show(record1)
        check("DetailPanel show", True)
        dp._build_empty()
        check("DetailPanel empty", True)

        # HistoryFrame with temp store
        tmp_dir2  = tempfile.mkdtemp()
        tmp_file2 = os.path.join(tmp_dir2, "history.json")

        frame = HistoryFrame.__new__(HistoryFrame)
        frame._store = HistoryStore(path=tmp_file2)
        tk.Frame.__init__(frame, root, bg=BG_DARK)
        frame.app = None
        frame._rows = []
        frame._selected_record = None
        frame._build()
        check("HistoryFrame created", True)

        # Add a record
        frame.add_record(FakeResult())
        check("add_record works",
              frame._store.count() == 1)

        root.destroy()
        shutil.rmtree(tmp_dir2)
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
