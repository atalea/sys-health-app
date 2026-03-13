"""
System Health Monitor
==================
Module 4: notifier.py  (v2 - with file review screen)
Responsibility: Pre-cleanup notification modal dialog.
                Step 1: Summary screen - what will be cleaned + postpone/cancel
                Step 2: Review screen - scrollable checklist, uncheck to keep files
                Step 3: on_confirm(selected_files) called with only checked files

How it's used:
    from notifier import CleanupNotifier, CleanupInfo, FileItem
    notifier = CleanupNotifier(
        parent, info, file_items,
        on_confirm, on_postpone, on_cancel
    )
    notifier.show()
"""

import tkinter as tk
import datetime
import sys
import os
import time
from pathlib import Path
from typing import Callable, Optional, List

# ─────────────────────────────────────────────
# THEME
# ─────────────────────────────────────────────
from app_config import THEME, bind_scroll, _pick_font, CONSTANTS

BG_DARK        = THEME.BG_DARK
BG_CARD        = THEME.BG_CARD
ACCENT         = THEME.ACCENT
ACCENT_DIM     = THEME.ACCENT_DIM
WARN           = THEME.WARN
DANGER         = THEME.DANGER
TEXT_PRIMARY   = THEME.TEXT_PRIMARY
TEXT_SECONDARY = THEME.TEXT_SECONDARY
BORDER         = THEME.BORDER
BORDER_CARD    = THEME.BORDER_CARD
BG_ROW_HOVER   = THEME.BG_ROW_HOVER

FONT_TITLE     = THEME.FONT_TITLE
FONT_SUBTITLE  = THEME.FONT_SECTION
FONT_BODY      = THEME.FONT_BODY
FONT_DETAIL    = THEME.FONT_DETAIL
FONT_SMALL     = THEME.FONT_SMALL
FONT_BTN       = THEME.FONT_BTN
FONT_BTN_SM    = THEME.FONT_SMALL
FONT_MONO      = THEME.FONT_MONO

POSTPONE_OPTIONS = {
    "1 hour":   60,
    "3 hours":  180,
    "Tonight":  None,
    "Tomorrow": None,
}

DIALOG_W = 580
DIALOG_H = 420
REVIEW_H = 520


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def calc_postpone_time(label: str) -> datetime.datetime:
    now = datetime.datetime.now()
    minutes = POSTPONE_OPTIONS.get(label)
    if minutes is not None:
        return now + datetime.timedelta(minutes=minutes)
    if label == "Tonight":
        t = now.replace(hour=22, minute=0, second=0, microsecond=0)
        if t <= now:
            t += datetime.timedelta(days=1)
        return t
    if label == "Tomorrow":
        return (now + datetime.timedelta(days=1)).replace(
            hour=3, minute=0, second=0, microsecond=0)
    return now + datetime.timedelta(hours=1)


def format_postpone_time(label: str) -> str:
    dt  = calc_postpone_time(label)
    now = datetime.datetime.now()
    if dt.date() == now.date():
        return f"today at {dt.strftime('%H:%M')}"
    elif dt.date() == (now + datetime.timedelta(days=1)).date():
        return f"tomorrow at {dt.strftime('%H:%M')}"
    return dt.strftime("%A at %H:%M")


def _bytes_to_human(n: int) -> str:
    if n >= 1024 ** 3: return f"{n/1024**3:.2f} GB"
    if n >= 1024 ** 2: return f"{n/1024**2:.1f} MB"
    if n >= 1024:      return f"{n/1024:.0f} KB"
    return f"{n} B"


def _age_str(path_str: str) -> str:
    """Return human-readable file age e.g. '3 days', '2 months'."""
    try:
        mtime = Path(path_str).stat().st_mtime
        days  = (time.time() - mtime) / 86400
        if days < 1:   return "today"
        if days < 7:   return f"{int(days)}d ago"
        if days < 30:  return f"{int(days/7)}w ago"
        if days < 365: return f"{int(days/30)}mo ago"
        return f"{int(days/365)}y ago"
    except OSError:
        return "unknown"


# ─────────────────────────────────────────────
# CleanupInfo
# ─────────────────────────────────────────────
class CleanupInfo:
    """Summary info shown on the first screen of the notifier."""

    def __init__(self, trigger: str, targets: list, estimated_mb: int = 0):
        self.trigger      = trigger
        self.targets      = targets
        self.estimated_mb = estimated_mb

    def size_str(self) -> str:
        if self.estimated_mb == 0:   return "Unknown"
        if self.estimated_mb >= 1024: return f"~{self.estimated_mb/1024:.1f} GB"
        return f"~{self.estimated_mb} MB"

    def trigger_label(self) -> str:
        return {
            "daily":   "Daily Cleanup",
            "weekly":  "Weekly Cleanup",
            "monthly": "Monthly Cleanup",
            "manual":  "Manual Cleanup",
        }.get(self.trigger, "Cleanup")


# ─────────────────────────────────────────────
# FileItem  - one file in the review list
# ─────────────────────────────────────────────
class FileItem:
    """
    Represents one file that would be cleaned.

    Attributes
    ----------
    path     : full path string
    size     : file size in bytes
    category : "trash" | "caches" | "logs" | "downloads"
    selected : whether the checkbox starts checked (default True)
    """

    def __init__(self, path: str, size: int, category: str,
                 selected: bool = True):
        self.path     = path
        self.size     = size
        self.category = category
        self.selected = selected

    @property
    def name(self) -> str:
        return os.path.basename(self.path)

    @property
    def size_str(self) -> str:
        return _bytes_to_human(self.size)

    @property
    def age_str(self) -> str:
        return _age_str(self.path)

    @property
    def category_icon(self) -> str:
        return {"trash": "[x]", "caches": "[C]",
                "logs": "[L]", "downloads": "[v]"}.get(self.category, "[f]")


# ─────────────────────────────────────────────
# PostponeMenu
# ─────────────────────────────────────────────
class PostponeMenu(tk.Frame):

    def __init__(self, parent, on_select=None, **kwargs):
        super().__init__(parent, bg=BG_DARK, **kwargs)
        self.on_select = on_select
        self._popup    = None

        btn_border = tk.Frame(self, bg=BORDER_CARD, padx=1, pady=1,
                              cursor="hand2")
        btn_border.pack()
        self._btn = tk.Label(btn_border,
                             text="  [t]  Postpone  v  ",
                             bg=BG_CARD, fg=TEXT_SECONDARY,
                             font=FONT_BTN_SM, cursor="hand2")
        self._btn.pack()

        for w in (btn_border, self._btn):
            w.bind("<Button-1>", self._toggle_popup)
            w.bind("<Enter>", lambda _, b=self._btn: b.config(fg=TEXT_PRIMARY))
            w.bind("<Leave>", lambda _, b=self._btn: b.config(fg=TEXT_SECONDARY))

    def _toggle_popup(self, _=None):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy(); self._popup = None; return
        self._show_popup()

    def _show_popup(self):
        self._popup = tk.Toplevel(self)
        self._popup.overrideredirect(True)
        self._popup.configure(bg=BORDER_CARD)
        self.update_idletasks()
        x = self.winfo_rootx()
        y = self.winfo_rooty() + self.winfo_height()
        self._popup.geometry(f"+{x}+{y}")

        inner = tk.Frame(self._popup, bg=BG_CARD)
        inner.pack(padx=1, pady=1)

        for label in POSTPONE_OPTIONS:
            when = format_postpone_time(label)
            row  = tk.Frame(inner, bg=BG_CARD, cursor="hand2")
            row.pack(fill="x")
            tk.Label(row, text=f"  {label}", bg=BG_CARD, fg=TEXT_PRIMARY,
                     font=FONT_BTN_SM, anchor="w", width=12).pack(
                         side="left", pady=6)
            tk.Label(row, text=f"{when}  ", bg=BG_CARD, fg=TEXT_SECONDARY,
                     font=FONT_SMALL, anchor="e").pack(side="right", pady=6)
            row.bind("<Enter>", lambda _, r=row: r.config(bg=BORDER))
            row.bind("<Leave>", lambda _, r=row: r.config(bg=BG_CARD))
            row.bind("<Button-1>", lambda _, l=label: self._select(l))
            for c in row.winfo_children():
                c.bind("<Button-1>", lambda _, l=label: self._select(l))

        self._popup.bind("<FocusOut>", lambda _: self._close())
        self._popup.focus_set()

    def _select(self, label):
        self._close()
        if self.on_select:
            self.on_select(label, calc_postpone_time(label))

    def _close(self):
        if self._popup and self._popup.winfo_exists():
            self._popup.destroy(); self._popup = None


# ─────────────────────────────────────────────
# FileReviewDialog  - step 2 checklist
# ─────────────────────────────────────────────
class FileReviewDialog:
    """
    Step 2 of the notification flow.
    Shows a scrollable checklist of files that would be deleted.
    User can uncheck files to keep them.

    on_confirm(selected_items: list[FileItem]) - called with only checked items
    on_back() - user clicked Back, return to step 1
    """

    def __init__(self, parent, file_items: List[FileItem],
                 on_confirm=None, on_back=None):
        self.parent     = parent
        self.items      = file_items
        self.on_confirm = on_confirm
        self.on_back    = on_back
        self._window    = None
        self._vars: dict[int, tk.BooleanVar] = {}   # index > BooleanVar

    def show(self):
        self._window = tk.Toplevel(self.parent)
        self._window.title("Review Files")
        self._window.resizable(True, True)
        self._window.configure(bg=BG_DARK)
        self._window.geometry(f"{DIALOG_W}x{REVIEW_H}")
        self._window.minsize(480, 400)
        self._window.transient(self.parent)
        self._window.grab_set()
        self._window.protocol("WM_DELETE_WINDOW", self._on_back)
        self._build()
        self._centre()

    def _build(self):
        w = self._window

        # ── header ─────────────────────────────
        header = tk.Frame(w, bg=BG_DARK, padx=20, pady=16)
        header.pack(fill="x")

        tk.Label(header, text="[L]  Review Files to Delete",
                 bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=FONT_TITLE).pack(side="left")

        # Select all / none buttons
        sel_frame = tk.Frame(header, bg=BG_DARK)
        sel_frame.pack(side="right")

        tk.Label(sel_frame, text="Select: ", bg=BG_DARK,
                 fg=TEXT_SECONDARY, font=FONT_SMALL).pack(side="left")

        for label, val in [("All", True), ("None", False)]:
            lbl = tk.Label(sel_frame, text=label, bg=BG_DARK,
                           fg=ACCENT, font=FONT_SMALL, cursor="hand2")
            lbl.pack(side="left", padx=4)
            lbl.bind("<Button-1>",
                     lambda _, v=val: self._set_all(v))

        tk.Label(w,
                 text="Uncheck any file you want to keep. "
                      "Unchecked files will NOT be deleted.",
                 bg=BG_DARK, fg=TEXT_SECONDARY,
                 font=FONT_DETAIL).pack(anchor="w", padx=20, pady=(0, 8))

        # ── category filter tabs ───────────────
        self._active_filter = tk.StringVar(value="all")
        tab_frame = tk.Frame(w, bg=BG_DARK)
        tab_frame.pack(fill="x", padx=20, pady=(0, 8))

        categories = ["all"] + sorted(
            set(item.category for item in self.items))
        self._tab_btns = {}
        for cat in categories:
            count = (len(self.items) if cat == "all"
                     else sum(1 for i in self.items if i.category == cat))
            label = f"{cat.title()}  ({count})"
            btn = tk.Label(tab_frame, text=label,
                           bg=BG_CARD, fg=TEXT_SECONDARY,
                           font=FONT_SMALL, padx=10, pady=4,
                           cursor="hand2")
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>",
                     lambda _, c=cat: self._filter(c))
            self._tab_btns[cat] = btn
        self._highlight_tab("all")

        # ── scrollable file list ───────────────
        list_frame = tk.Frame(w, bg=BG_DARK)
        list_frame.pack(fill="both", expand=True, padx=20)

        self._canvas = tk.Canvas(list_frame, bg=BG_DARK,
                                 highlightthickness=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical",
                                 command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        self._list_inner = tk.Frame(self._canvas, bg=BG_DARK)
        self._canvas_win = self._canvas.create_window(
            (0, 0), window=self._list_inner, anchor="nw")

        self._canvas.bind("<Configure>",
                          lambda e: self._canvas.itemconfig(
                              self._canvas_win, width=e.width))
        self._list_inner.bind("<Configure>",
                              lambda e: self._canvas.configure(
                                  scrollregion=self._canvas.bbox("all")))
        # Two-finger / mousewheel scroll (macOS trackpad safe)
        bind_scroll(self._canvas,
                    lambda d: self._canvas.yview_scroll(d, "units"))

        self._render_list(self.items)

        # ── footer ─────────────────────────────
        tk.Frame(w, bg=BORDER, height=1).pack(fill="x", pady=(8, 0))
        footer = tk.Frame(w, bg=BG_DARK, padx=20, pady=12)
        footer.pack(fill="x")

        # Summary label
        self._summary_lbl = tk.Label(
            footer, text="", bg=BG_DARK,
            fg=TEXT_SECONDARY, font=FONT_SMALL)
        self._summary_lbl.pack(side="left")
        self._update_summary()

        # Back button
        back_border = tk.Frame(footer, bg=BORDER_CARD, padx=1, pady=1)
        back_border.pack(side="left", padx=(12, 0))
        back_btn = tk.Label(back_border, text="  < Back  ",
                            bg=BG_CARD, fg=TEXT_SECONDARY,
                            font=FONT_BTN_SM, cursor="hand2")
        back_btn.pack()
        for ww in (back_border, back_btn):
            ww.bind("<Button-1>", lambda _: self._on_back())
            ww.bind("<Enter>",
                    lambda _, b=back_btn: b.config(fg=TEXT_PRIMARY))
            ww.bind("<Leave>",
                    lambda _, b=back_btn: b.config(fg=TEXT_SECONDARY))

        # Confirm deletion button
        confirm_border = tk.Frame(footer, bg=ACCENT_DIM, padx=1, pady=1)
        confirm_border.pack(side="right")
        self._confirm_btn = tk.Label(
            confirm_border, text="  [x]  Confirm Deletion  ",
            bg=ACCENT, fg=BG_DARK,
            font=FONT_BTN, cursor="hand2")
        self._confirm_btn.pack()
        for ww in (confirm_border, self._confirm_btn):
            ww.bind("<Button-1>", lambda _: self._on_confirm())
            ww.bind("<Enter>",
                    lambda _, b=self._confirm_btn: b.config(
                        bg=ACCENT_DIM, fg=TEXT_PRIMARY))
            ww.bind("<Leave>",
                    lambda _, b=self._confirm_btn: b.config(
                        bg=ACCENT, fg=BG_DARK))

    def _render_list(self, items: list):
        """Draw file rows for the given item list."""
        for widget in self._list_inner.winfo_children():
            widget.destroy()

        if not items:
            tk.Label(self._list_inner,
                     text="No files in this category.",
                     bg=BG_DARK, fg=TEXT_SECONDARY,
                     font=FONT_DETAIL).pack(pady=20)
            return

        # Column headers
        hdr = tk.Frame(self._list_inner, bg=BG_DARK)
        hdr.pack(fill="x", pady=(0, 4))
        hdr.columnconfigure(1, weight=1)
        for col, text, w in [
            (0, "  Keep", 6), (1, "File name", 0),
            (2, "Size", 8),   (3, "Age", 8),
            (4, "Category", 10)
        ]:
            tk.Label(hdr, text=text, bg=BG_DARK, fg=TEXT_SECONDARY,
                     font=FONT_SMALL, width=w if w else 0,
                     anchor="w").grid(row=0, column=col,
                                      sticky="w", padx=4)

        tk.Frame(self._list_inner, bg=BORDER, height=1).pack(
            fill="x", pady=(0, 4))

        # File rows
        for idx, item in enumerate(items):
            global_idx = self.items.index(item)
            if global_idx not in self._vars:
                self._vars[global_idx] = tk.BooleanVar(value=item.selected)

            var = self._vars[global_idx]
            bg  = BG_DARK

            row = tk.Frame(self._list_inner, bg=bg)
            row.pack(fill="x", pady=1)
            row.columnconfigure(1, weight=1)

            # Checkbox
            cb = tk.Checkbutton(
                row, variable=var,
                bg=bg, activebackground=bg,
                selectcolor=BG_CARD,
                fg=ACCENT, command=self._update_summary
            )
            cb.grid(row=0, column=0, padx=(4, 0))

            # Filename (truncated)
            name = item.name
            if len(name) > 38:
                name = name[:35] + "..."
            tk.Label(row, text=name, bg=bg, fg=TEXT_PRIMARY,
                     font=FONT_DETAIL, anchor="w").grid(
                         row=0, column=1, sticky="w", padx=4)

            # Size
            tk.Label(row, text=item.size_str, bg=bg,
                     fg=TEXT_SECONDARY, font=FONT_MONO,
                     width=8, anchor="e").grid(row=0, column=2, padx=4)

            # Age
            tk.Label(row, text=item.age_str, bg=bg,
                     fg=TEXT_SECONDARY, font=FONT_SMALL,
                     width=8, anchor="e").grid(row=0, column=3, padx=4)

            # Category icon
            tk.Label(row, text=f"{item.category_icon} {item.category}",
                     bg=bg, fg=TEXT_SECONDARY,
                     font=FONT_SMALL, width=10,
                     anchor="w").grid(row=0, column=4, padx=4)

            # Hover highlight
            def _enter(_, r=row, c=cb):
                r.config(bg=BG_ROW_HOVER)
                c.config(bg=BG_ROW_HOVER, activebackground=BG_ROW_HOVER)
                for ch in r.winfo_children():
                    try: ch.config(bg=BG_ROW_HOVER)
                    except tk.TclError: pass

            def _leave(_, r=row, c=cb, b=bg):
                r.config(bg=b)
                c.config(bg=b, activebackground=b)
                for ch in r.winfo_children():
                    try: ch.config(bg=b)
                    except tk.TclError: pass

            row.bind("<Enter>", _enter)
            row.bind("<Leave>", _leave)

    def _filter(self, category: str):
        self._active_filter.set(category)
        self._highlight_tab(category)
        if category == "all":
            self._render_list(self.items)
        else:
            self._render_list(
                [i for i in self.items if i.category == category])

    def _highlight_tab(self, active: str):
        for cat, btn in self._tab_btns.items():
            if cat == active:
                btn.config(bg=ACCENT, fg=BG_DARK)
            else:
                btn.config(bg=BG_CARD, fg=TEXT_SECONDARY)

    def _set_all(self, value: bool):
        for var in self._vars.values():
            var.set(value)
        self._update_summary()

    def _update_summary(self):
        selected = [self.items[i] for i, v in self._vars.items()
                    if v.get() and i < len(self.items)]
        total_bytes = sum(item.size for item in selected)
        kept = len(self.items) - len(selected)
        text = (f"{len(selected)} of {len(self.items)} files selected  -  "
                f"{_bytes_to_human(total_bytes)} will be freed")
        if kept > 0:
            text += f"  -  {kept} kept"
        self._summary_lbl.config(text=text)

    def _get_selected(self) -> List[FileItem]:
        return [self.items[i] for i, v in self._vars.items()
                if v.get() and i < len(self.items)]

    def _centre(self):
        self._window.update_idletasks()
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()
        ww = self._window.winfo_width()
        wh = self._window.winfo_height()
        self._window.geometry(
            f"+{px + (pw-ww)//2}+{py + (ph-wh)//2}")

    def _on_confirm(self):
        selected = self._get_selected()
        self._close()
        if self.on_confirm:
            self.on_confirm(selected)

    def _on_back(self):
        self._close()
        if self.on_back:
            self.on_back()

    def _close(self):
        if self._window and self._window.winfo_exists():
            self._window.grab_release()
            self._window.destroy()
            self._window = None


# ─────────────────────────────────────────────
# CleanupNotifier  - step 1 summary screen
# ─────────────────────────────────────────────
class CleanupNotifier:
    """
    Two-step modal flow:
      Step 1 (this class): Summary - icon, targets, size, postpone/cancel
      Step 2 (FileReviewDialog): Checklist - review & uncheck files to keep

    Parameters
    ----------
    parent       : parent tk widget
    info         : CleanupInfo
    file_items   : list[FileItem] - files to show in review screen.
                   Pass [] to skip review and go straight to on_confirm.
    on_confirm   : callable(selected: list[FileItem])
    on_postpone  : callable(label, datetime)
    on_cancel    : callable()
    """

    def __init__(self, parent, info: CleanupInfo,
                 file_items: Optional[List[FileItem]] = None,
                 on_confirm=None, on_postpone=None, on_cancel=None):
        self.parent      = parent
        self.info        = info
        self.file_items  = file_items or []
        self.on_confirm  = on_confirm
        self.on_postpone = on_postpone
        self.on_cancel   = on_cancel
        self._window     = None
        self._countdown  = 0       # disabled by default
        self._after_id   = None

    def show(self):
        if self._window and self._window.winfo_exists():
            self._window.lift(); return

        self._window = tk.Toplevel(self.parent)
        self._window.title("Cleanup Notification")
        self._window.resizable(False, False)
        self._window.configure(bg=BG_DARK)
        self._window.geometry(f"{DIALOG_W}x{DIALOG_H}")
        self._window.transient(self.parent)
        self._window.grab_set()
        self._window.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self._build()
        self._centre()
        self._start_countdown()

    def _build(self):
        w = self._window

        # ── icon + title ───────────────────────
        top = tk.Frame(w, bg=BG_DARK, padx=24, pady=20)
        top.pack(fill="x")
        tk.Label(top, text="[>]", bg=BG_DARK,
                 font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 36)).pack(side="left", padx=(0,14))
        col = tk.Frame(top, bg=BG_DARK)
        col.pack(side="left")
        tk.Label(col, text=self.info.trigger_label(),
                 bg=BG_DARK, fg=TEXT_PRIMARY,
                 font=FONT_TITLE, anchor="w").pack(anchor="w")
        tk.Label(col, text="Your Mac is ready to be cleaned up.",
                 bg=BG_DARK, fg=TEXT_SECONDARY,
                 font=FONT_SUBTITLE, anchor="w").pack(anchor="w", pady=(2,0))

        # ── info card ──────────────────────────
        card_border = tk.Frame(w, bg=BORDER_CARD, padx=24, pady=1)
        card_border.pack(fill="x", padx=24, pady=(0, 6))
        card = tk.Frame(card_border, bg=BG_CARD, padx=16, pady=14)
        card.pack(fill="both", padx=1, pady=1)

        tk.Label(card, text="What will be cleaned:",
                 bg=BG_CARD, fg=TEXT_SECONDARY,
                 font=FONT_DETAIL, anchor="w").pack(anchor="w")

        for target in self.info.targets:
            row = tk.Frame(card, bg=BG_CARD)
            row.pack(fill="x", pady=1)
            tk.Label(row, text="  -  ", bg=BG_CARD,
                     fg=ACCENT, font=FONT_BODY).pack(side="left")
            tk.Label(row, text=target, bg=BG_CARD,
                     fg=TEXT_PRIMARY, font=FONT_BODY).pack(side="left")

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", pady=(10,8))

        size_row = tk.Frame(card, bg=BG_CARD)
        size_row.pack(fill="x")
        tk.Label(size_row, text="Estimated space to free:",
                 bg=BG_CARD, fg=TEXT_SECONDARY,
                 font=FONT_DETAIL).pack(side="left")
        tk.Label(size_row, text=f"  {self.info.size_str()}",
                 bg=BG_CARD, fg=ACCENT,
                 font=_pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 10, "bold")).pack(side="left")

        # Review files hint
        if self.file_items:
            tk.Label(card,
                     text=f">  {len(self.file_items)} files queued - "
                          f"click 'Review Files' to uncheck any you want to keep.",
                     bg=BG_CARD, fg=TEXT_SECONDARY,
                     font=FONT_SMALL, anchor="w").pack(
                         anchor="w", pady=(8, 0))

        # ── countdown ──────────────────────────
        self._countdown_lbl = tk.Label(w, text="", bg=BG_DARK,
                                       fg=TEXT_SECONDARY, font=FONT_SMALL)
        self._countdown_lbl.pack(pady=(6, 0))

        # ── action buttons ─────────────────────
        btn_row = tk.Frame(w, bg=BG_DARK, padx=24, pady=16)
        btn_row.pack(fill="x")

        # Cancel
        self._make_btn(btn_row, "  Cancel  ", BG_CARD, TEXT_SECONDARY,
                       DANGER, self._on_cancel, side="left")

        # Postpone
        self._postpone_menu = PostponeMenu(
            btn_row, on_select=self._on_postpone)
        self._postpone_menu.pack(side="left", padx=10)

        # Review Files (shown only if file_items provided)
        if self.file_items:
            self._make_btn(btn_row,
                           f"  [L]  Review {len(self.file_items)} Files  ",
                           BG_CARD, TEXT_SECONDARY, ACCENT,
                           self._open_review, side="right", padx=(0, 8))

        # Run Now / Skip Review
        label = "  >  Run Now  " if not self.file_items else "  >  Run All  "
        run_border = tk.Frame(btn_row, bg=ACCENT_DIM, padx=1, pady=1)
        run_border.pack(side="right")
        run_btn = tk.Label(run_border, text=label,
                           bg=ACCENT, fg=BG_DARK,
                           font=FONT_BTN, cursor="hand2")
        run_btn.pack()
        for ww in (run_border, run_btn):
            ww.bind("<Button-1>", lambda _: self._on_confirm_all())
            ww.bind("<Enter>",
                    lambda _, b=run_btn: b.config(bg=ACCENT_DIM,
                                                  fg=TEXT_PRIMARY))
            ww.bind("<Leave>",
                    lambda _, b=run_btn: b.config(bg=ACCENT, fg=BG_DARK))

    def _make_btn(self, parent, text, bg, fg, hover_fg,
                  command, side="left", padx=0):
        border = tk.Frame(parent, bg=BORDER_CARD, padx=1, pady=1)
        border.pack(side=side, padx=padx)
        btn = tk.Label(border, text=text, bg=bg, fg=fg,
                       font=FONT_BTN_SM, cursor="hand2")
        btn.pack()
        for w in (border, btn):
            w.bind("<Button-1>", lambda _: command())
            w.bind("<Enter>", lambda _, b=btn: b.config(fg=hover_fg))
            w.bind("<Leave>", lambda _, b=btn: b.config(fg=fg))

    def _centre(self):
        self._window.update_idletasks()
        pw = self.parent.winfo_width()
        ph = self.parent.winfo_height()
        px = self.parent.winfo_rootx()
        py = self.parent.winfo_rooty()
        ww = self._window.winfo_width()
        wh = self._window.winfo_height()
        self._window.geometry(
            f"+{px+(pw-ww)//2}+{py+(ph-wh)//2}")

    # ── countdown ──────────────────────────────
    def _start_countdown(self):
        if self._countdown > 0:
            self._tick()

    def _tick(self):
        if not self._window or not self._window.winfo_exists(): return
        if self._countdown <= 0:
            self._countdown_lbl.config(text="")
            self._on_confirm_all(); return
        self._countdown_lbl.config(
            text=f"Auto-running in {self._countdown}s")
        self._countdown -= 1
        self._after_id = self._window.after(1000, self._tick)

    def _cancel_countdown(self):
        self._countdown = 0
        if self._after_id:
            try: self._window.after_cancel(self._after_id)
            except Exception: pass
        self._countdown_lbl.config(text="")

    # ── open review screen ─────────────────────
    def _open_review(self):
        """Close step 1, open FileReviewDialog (step 2)."""
        self._cancel_countdown()
        # Hide (don't destroy) step 1 so we can restore it on Back
        self._window.withdraw()

        def on_confirm_selected(selected):
            self._close()
            if self.on_confirm:
                self.on_confirm(selected)

        def on_back():
            # Restore step 1
            if self._window and self._window.winfo_exists():
                self._window.deiconify()
                self._window.grab_set()

        FileReviewDialog(
            parent=self.parent,
            file_items=self.file_items,
            on_confirm=on_confirm_selected,
            on_back=on_back
        ).show()

    # ── action handlers ────────────────────────
    def _on_confirm_all(self):
        """Run Now / Run All - skip review, pass all items."""
        self._cancel_countdown()
        self._close()
        if self.on_confirm:
            self.on_confirm(self.file_items)

    def _on_postpone(self, label, dt):
        self._cancel_countdown()
        self._close()
        if self.on_postpone:
            self.on_postpone(label, dt)

    def _on_cancel(self):
        self._cancel_countdown()
        self._close()
        if self.on_cancel:
            self.on_cancel()

    def _close(self):
        if self._window and self._window.winfo_exists():
            self._window.grab_release()
            self._window.destroy()
            self._window = None

    def dismiss(self):
        self._cancel_countdown()
        self._close()


# ─────────────────────────────────────────────
# Demo helpers - build fake FileItems for testing
# ─────────────────────────────────────────────
def _make_demo_items() -> List[FileItem]:
    """Generate realistic-looking demo FileItems."""
    import random
    items = []
    now = time.time()

    demo_files = [
        ("trash",     "old_report.pdf",          1_200_000,  45),
        ("trash",     "screenshot_2024.png",        450_000,  60),
        ("trash",     "project_backup.zip",       8_500_000,  30),
        ("caches",    "com.apple.Safari",         45_000_000,  7),
        ("caches",    "com.google.Chrome",        120_000_000, 3),
        ("logs",      "crash_2024-01-15.crash",      34_000,  90),
        ("logs",      "system_diagnostic.log",       12_000,  14),
        ("downloads", "Xcode_15.dmg",          8_000_000_000,  180),
        ("downloads", "old_installer.pkg",        250_000_000,  95),
        ("downloads", "archive_2023.zip",          45_000_000,  200),
        ("downloads", "presentation_draft.pptx",    3_200_000,  35),
    ]

    for cat, name, size, age_days in demo_files:
        fake_path = str(Path.home() / cat / name)
        item = FileItem(path=fake_path, size=size, category=cat)
        # Override age_str for demo purposes
        item._demo_age = f"{age_days}d ago"
        items.append(item)

    return items


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    root = tk.Tk()
    root.title("Notifier - Module 4 Test")
    root.geometry("500x300")
    root.configure(bg=BG_DARK)

    status = tk.Label(root, text="Click to test the notifier",
                      bg=BG_DARK, fg=TEXT_SECONDARY,
                      font=_pick_font("SF Pro Text", ("Segoe UI", "Helvetica Neue", "Arial"), 12))
    status.pack(expand=True)

    def update(msg, color=ACCENT):
        status.config(text=msg, fg=color)

    def show():
        items = _make_demo_items()
        info  = CleanupInfo(
            trigger="manual",
            targets=["User caches", "Old log files",
                     f"Downloads (> {CONSTANTS.DOWNLOADS_AGE_DAYS} days)"],
            estimated_mb=sum(i.size for i in items) // (1024**2)
        )
        CleanupNotifier(
            parent=root, info=info, file_items=items,
            on_confirm=lambda sel: update(
                f"[OK]  Running cleanup on {len(sel)} files"),
            on_postpone=lambda l, dt: update(
                f"[t]  Postponed: {format_postpone_time(l)}", WARN),
            on_cancel=lambda: update("[!!]  Cancelled", DANGER),
        ).show()

    border = tk.Frame(root, bg=BORDER_CARD, padx=1, pady=1)
    border.pack(pady=10)
    btn = tk.Label(border, text="  Show Cleanup Notification  ",
                   bg=BG_CARD, fg=ACCENT,
                   font=FONT_BTN, cursor="hand2")
    btn.pack()
    for w in (border, btn):
        w.bind("<Button-1>", lambda _: show())

    root.mainloop()


# ─────────────────────────────────────────────
# Test suite
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 52)
    print("Module 4 - notifier.py test suite (v2)")
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

    now = datetime.datetime.now()

    # 1. calc_postpone_time
    t1h = calc_postpone_time("1 hour")
    check("1h postpone",   abs((t1h-now).total_seconds()-3600) < 5)
    t3h = calc_postpone_time("3 hours")
    check("3h postpone",   abs((t3h-now).total_seconds()-10800) < 5)
    tonight = calc_postpone_time("Tonight")
    check("Tonight future",  tonight > now)
    check("Tonight 22:00",   tonight.hour == 22)
    tomorrow = calc_postpone_time("Tomorrow")
    check("Tomorrow future", tomorrow > now)
    check("Tomorrow 03:00",  tomorrow.hour == 3)
    check("Tomorrow next day", tomorrow.date() > now.date())

    # 2. format_postpone_time
    for label in POSTPONE_OPTIONS:
        check(f"format({label!r})", len(format_postpone_time(label)) > 0)

    # 3. CleanupInfo
    info = CleanupInfo("daily", ["Trash"], 512)
    check("trigger daily",   info.trigger_label() == "Daily Cleanup")
    check("size 512MB",      info.size_str() == "~512 MB")
    check("size 2GB",        CleanupInfo("x",[],2048).size_str() == "~2.0 GB")
    check("size unknown",    CleanupInfo("x",[],0).size_str() == "Unknown")

    # 4. FileItem
    item = FileItem("/tmp/test.pdf", 1_024_000, "downloads")
    check("FileItem name",     item.name == "test.pdf")
    check("FileItem size_str", item.size_str == "1000 KB")
    check("FileItem icon",     item.category_icon == "[v]")
    check("FileItem selected", item.selected == True)

    item2 = FileItem("/tmp/x", 500, "trash", selected=False)
    check("FileItem unselected", item2.selected == False)

    # 5. _bytes_to_human
    check("500 B",    _bytes_to_human(500)        == "500 B")
    check("2 KB",     _bytes_to_human(2048)        == "2 KB")
    check("5.0 MB",   _bytes_to_human(5*1024**2)  == "5.0 MB")
    check("2.00 GB",  _bytes_to_human(2*1024**3)  == "2.00 GB")

    # 6. Tkinter widgets
    try:
        root = tk.Tk()
        root.withdraw()

        pm = PostponeMenu(root)
        check("PostponeMenu created", True)

        results = {}
        def on_confirm(sel): results["sel"] = sel
        def on_cancel():     results["cancel"] = True
        def on_postpone(l, dt): results["postpone"] = l

        items = [FileItem("/tmp/a.txt", 100, "trash"),
                 FileItem("/tmp/b.txt", 200, "downloads", selected=False)]

        n = CleanupNotifier(root, info, items,
                            on_confirm=on_confirm,
                            on_cancel=on_cancel,
                            on_postpone=on_postpone)
        n._countdown = 0
        n.show()
        check("CleanupNotifier created", True)

        # Test confirm all
        n._on_confirm_all()
        check("on_confirm_all fires",   "sel" in results)
        check("all items passed",       len(results.get("sel", [])) == 2)

        # Test cancel
        n2 = CleanupNotifier(root, info, [], on_cancel=on_cancel)
        n2._countdown = 0
        n2.show()
        n2._on_cancel()
        check("on_cancel fires", results.get("cancel") == True)

        # Test postpone
        n3 = CleanupNotifier(root, info, [], on_postpone=on_postpone)
        n3._countdown = 0
        n3.show()
        n3._on_postpone("1 hour", calc_postpone_time("1 hour"))
        check("on_postpone fires", results.get("postpone") == "1 hour")

        # Test FileReviewDialog selection logic
        vars_map = {0: tk.BooleanVar(value=True),
                    1: tk.BooleanVar(value=False)}
        fd = FileReviewDialog.__new__(FileReviewDialog)
        fd.items = items
        fd._vars = vars_map
        selected = fd._get_selected()
        check("review selects checked only", len(selected) == 1)
        check("review correct item",
              selected[0].name == "a.txt")

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
