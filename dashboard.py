"""
System Health Monitor
==================
Module 2: dashboard.py  (v3 - added Network Activity card)
Responsibility: Dashboard page - live CPU, Memory, Disk, Swap, and Network
                cards in a 2×3 grid with arc gauges and activity bars,
                auto-refresh every 10 seconds.

How it plugs into main.py:
    from dashboard import DashboardFrame
    app.register_frame("Dashboard", DashboardFrame(app.content, app))
"""

import tkinter as tk
import psutil
import sys
import os
import time
import datetime
import platform
from pathlib import Path
from app_config import THEME, CONSTANTS, _pick_font
from utils import bytes_to_human

FONT_PERCENT = _pick_font("SF Pro Display", ("Segoe UI", "Helvetica Neue", "Arial"), 32, "bold")
REFRESH_MS   = CONSTANTS.DASHBOARD_REFRESH_MS

# Track previous net counters for per-second rate calculation
_last_net_bytes = None
_last_net_time  = None


# ─────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────
def threshold_color(pct: float) -> str:
    if pct >= 85: return THEME.DANGER
    if pct >= 60: return THEME.WARN
    return THEME.ACCENT


def _net_rate() -> tuple[int, int]:
    """Return (bytes_sent_per_sec, bytes_recv_per_sec) since last call."""
    global _last_net_bytes, _last_net_time
    now     = time.monotonic()
    counters = psutil.net_io_counters()
    if _last_net_bytes is None:
        _last_net_bytes = (counters.bytes_sent, counters.bytes_recv)
        _last_net_time  = now
        return 0, 0
    elapsed = max(now - _last_net_time, 0.001)
    sent  = int((counters.bytes_sent - _last_net_bytes[0]) / elapsed)
    recv  = int((counters.bytes_recv - _last_net_bytes[1]) / elapsed)
    _last_net_bytes = (counters.bytes_sent, counters.bytes_recv)
    _last_net_time  = now
    return max(sent, 0), max(recv, 0)


# ─────────────────────────────────────────────
# ArcGauge
# ─────────────────────────────────────────────
class ArcGauge(tk.Canvas):
    """
    Arc gauge drawn on a Canvas.
    Starts at 225 degrees (bottom-left), sweeps 270 degrees clockwise.
    Larger size + thicker stroke than v1 for visual impact.
    """

    def __init__(self, parent, size=160, thickness=14, **kwargs):
        super().__init__(
            parent,
            width=size, height=size,
            bg=THEME.BG_CARD, highlightthickness=0,
            **kwargs
        )
        self.size      = size
        self.thickness = thickness
        self.pct       = 0.0
        self._draw(0.0, THEME.ACCENT)

    def set_value(self, pct: float):
        self.pct = pct
        self._draw(pct, threshold_color(pct))

    def _draw(self, pct: float, color: str):
        self.delete("all")
        pad = self.thickness + 6
        x0, y0 = pad, pad
        x1, y1 = self.size - pad, self.size - pad

        # Grey track (full 270 degrees)
        self.create_arc(
            x0, y0, x1, y1,
            start=225, extent=-270,
            style="arc", outline=THEME.BORDER,
            width=self.thickness
        )

        # Coloured fill proportional to pct
        sweep = -(pct / 100) * 270
        if abs(sweep) > 0.5:
            self.create_arc(
                x0, y0, x1, y1,
                start=225, extent=sweep,
                style="arc", outline=color,
                width=self.thickness
            )

        # Percentage text centred
        cx, cy = self.size / 2, self.size / 2
        self.create_text(cx, cy, text=f"{pct:.0f}%",
                         fill=color, font=FONT_PERCENT)


# ─────────────────────────────────────────────
# MetricCard
# ─────────────────────────────────────────────
class MetricCard(tk.Frame):
    """
    Bordered card with:
      - icon + title row
      - thin divider
      - ArcGauge (160px, centred)
      - thin divider
      - stat rows: Used / Free / Total

    Border trick: wrap the inner Frame with a 1px outer Frame
    set to BORDER_CARD colour. The inner Frame is inset by 1px
    on all sides, creating the appearance of a border.
    """

    def __init__(self, parent, title: str,
                 detail_keys: tuple, **kwargs):
        # Outer border frame - provides the visible 1px border
        self._border_frame = tk.Frame(parent, bg=THEME.BORDER_CARD, **kwargs)

        # Inner card - inset 1px to reveal border
        super().__init__(self._border_frame, bg=THEME.BG_CARD, padx=16, pady=14)
        super().pack(fill="both", padx=1, pady=1)

        self.detail_keys = detail_keys

        # ── icon + title ───────────────────────
        title_row = tk.Frame(self, bg=THEME.BG_CARD)
        title_row.pack(fill="x", anchor="w")

        tk.Label(title_row, text=title, bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                 font=THEME.FONT_TITLE).pack(side="left")

        # ── divider ────────────────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(8, 0))

        # ── gauge ──────────────────────────────
        gauge_wrap = tk.Frame(self, bg=THEME.BG_CARD)
        gauge_wrap.pack(pady=(8, 4))
        self.gauge = ArcGauge(gauge_wrap, size=130, thickness=12)
        self.gauge.pack()

        # ── divider ────────────────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(4, 8))

        # ── stat rows ──────────────────────────
        stats = tk.Frame(self, bg=THEME.BG_CARD)
        stats.pack(fill="x")
        stats.columnconfigure(1, weight=1)

        self.detail_labels: dict[str, tk.Label] = {}
        for i, key in enumerate(detail_keys):
            tk.Label(stats, text=key + ":", bg=THEME.BG_CARD,
                     fg=THEME.TEXT_SECONDARY, font=THEME.FONT_DETAIL,
                     anchor="w").grid(row=i, column=0, sticky="w",
                                      pady=2, padx=(0, 14))
            val = tk.Label(stats, text="-", bg=THEME.BG_CARD,
                           fg=THEME.TEXT_PRIMARY, font=THEME.FONT_DETAIL, anchor="w")
            val.grid(row=i, column=1, sticky="w", pady=2)
            self.detail_labels[key] = val

    # ── proxy grid to border frame ─────────────
    def grid(self, **kwargs):
        self._border_frame.grid(**kwargs)

    def update(self, pct: float, details: dict):
        self.gauge.set_value(pct)
        color = threshold_color(pct)
        for key, value in details.items():
            if key not in self.detail_labels:
                continue
            if key == "Used":
                fg = color
            elif key == "Total":
                fg = THEME.TEXT_SECONDARY
            else:
                fg = THEME.TEXT_PRIMARY
            self.detail_labels[key].config(text=value, fg=fg)


# ─────────────────────────────────────────────
# StatusBar
# ─────────────────────────────────────────────
class StatusBar(tk.Frame):

    def __init__(self, parent, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x")
        inner = tk.Frame(self, bg=THEME.BG_DARK)
        inner.pack(fill="x", padx=20, pady=7)

        self.status_lbl = tk.Label(inner, text="", bg=THEME.BG_DARK,
                                   fg=THEME.TEXT_SECONDARY, font=THEME.FONT_DETAIL,
                                   anchor="w")
        self.status_lbl.pack(side="left")

        self.time_lbl = tk.Label(inner, text="", bg=THEME.BG_DARK,
                                 fg=THEME.TEXT_SECONDARY, font=THEME.FONT_DETAIL,
                                 anchor="e")
        self.time_lbl.pack(side="right")

    def update(self, cpu: float, mem: float, disk: float, swap: float):
        issues = []
        for name, val in [("CPU", cpu), ("Memory", mem),
                          ("Disk", disk), ("Swap", swap)]:
            if val >= 85:
                issues.append(f"{name} critical ({val:.0f}%)")
            elif val >= 60:
                issues.append(f"{name} elevated ({val:.0f}%)")

        if issues:
            self.status_lbl.config(
                text="[!]  " + " · ".join(issues), fg=THEME.WARN)
        else:
            self.status_lbl.config(text="[OK]  All systems healthy", fg=THEME.ACCENT)

        now = datetime.datetime.now().strftime("%H:%M:%S")
        self.time_lbl.config(text=f"Last updated {now}")


# ─────────────────────────────────────────────
# NetworkCard
# ─────────────────────────────────────────────
class NetworkCard(tk.Frame):
    """
    Network Activity card with two arc gauges side by side:
        ↓ Download  |  ↑ Upload
    Gauges are relative to a rolling session peak (adapts to fastest
    speed seen so far). Stat rows below match MetricCard style.
    """

    def __init__(self, parent, **kwargs):
        self._border_frame = tk.Frame(parent, bg=THEME.BORDER_CARD, **kwargs)
        super().__init__(self._border_frame, bg=THEME.BG_CARD, padx=16, pady=14)
        super().pack(fill="both", padx=1, pady=1)
        self._peak_recv = 1          # rolling peak bytes/s (min 1 to avoid /0)
        self._peak_sent = 1
        self._build()

    def _build(self):
        # ── title ──────────────────────────────
        tk.Label(self, text="Network Activity",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                 font=THEME.FONT_TITLE).pack(anchor="w")
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(10, 0))

        # ── dual gauge row ─────────────────────
        gauges = tk.Frame(self, bg=THEME.BG_CARD)
        gauges.pack(fill="x", pady=(10, 6))
        gauges.columnconfigure(0, weight=1)
        gauges.columnconfigure(1, weight=0)   # divider
        gauges.columnconfigure(2, weight=1)

        # Download gauge (column 0)
        dl_frame = tk.Frame(gauges, bg=THEME.BG_CARD)
        dl_frame.grid(row=0, column=0, sticky="nsew")
        self._dl_gauge = ArcGauge(dl_frame, size=130, thickness=12)
        self._dl_gauge.pack()
        self._dl_lbl = tk.Label(dl_frame, text="0 KB/s",
                                bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                                font=THEME.FONT_BODY)
        self._dl_lbl.pack(pady=(4, 0))
        tk.Label(dl_frame, text="↓  Download",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_DETAIL).pack()

        # Vertical divider (column 1)
        tk.Frame(gauges, bg=THEME.BORDER, width=1).grid(
            row=0, column=1, sticky="ns", padx=16)

        # Upload gauge (column 2)
        ul_frame = tk.Frame(gauges, bg=THEME.BG_CARD)
        ul_frame.grid(row=0, column=2, sticky="nsew")
        self._ul_gauge = ArcGauge(ul_frame, size=130, thickness=12)
        self._ul_gauge.pack()
        self._ul_lbl = tk.Label(ul_frame, text="0 KB/s",
                                bg=THEME.BG_CARD, fg=THEME.TEXT_PRIMARY,
                                font=THEME.FONT_BODY)
        self._ul_lbl.pack(pady=(4, 0))
        tk.Label(ul_frame, text="↑  Upload",
                 bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
                 font=THEME.FONT_DETAIL).pack()

        # ── divider ────────────────────────────
        tk.Frame(self, bg=THEME.BORDER, height=1).pack(fill="x", pady=(6, 10))

        # ── stat rows (single column, matches mockup) ──
        stats = tk.Frame(self, bg=THEME.BG_CARD)
        stats.pack(fill="x")
        stats.columnconfigure(1, weight=1)

        for i, (label, attr) in enumerate([
            ("Peak download",  "_peak_dl_lbl"),
            ("Peak upload",    "_peak_ul_lbl"),
            ("Total received", "_total_recv_lbl"),
            ("Total sent",     "_total_sent_lbl"),
            ("Interface",      "_iface_lbl"),
        ]):
            tk.Label(stats, text=label + ":", bg=THEME.BG_CARD,
                     fg=THEME.TEXT_SECONDARY, font=THEME.FONT_DETAIL,
                     anchor="w").grid(row=i, column=0, sticky="w",
                                      pady=2, padx=(0, 14))
            lbl = tk.Label(stats, text="-", bg=THEME.BG_CARD,
                           fg=THEME.TEXT_PRIMARY, font=THEME.FONT_DETAIL,
                           anchor="w")
            lbl.grid(row=i, column=1, sticky="w", pady=2)
            setattr(self, attr, lbl)

    @staticmethod
    def _fmt(bps: int) -> str:
        if bps >= 1024 * 1024:
            return f"{bps / 1024 / 1024:.1f} MB/s"
        if bps >= 1024:
            return f"{bps / 1024:.0f} KB/s"
        return f"{bps} B/s"

    def grid(self, **kwargs):
        self._border_frame.grid(**kwargs)

    def update(self, sent: int, recv: int):
        # Update rolling peaks
        self._peak_recv = max(self._peak_recv, recv, 1)
        self._peak_sent = max(self._peak_sent, sent, 1)

        # Gauges: percentage of session peak
        dl_pct = min((recv / self._peak_recv) * 100, 100)
        ul_pct = min((sent / self._peak_sent) * 100, 100)
        self._dl_gauge.set_value(dl_pct)
        self._ul_gauge.set_value(ul_pct)

        # Rate labels
        self._dl_lbl.config(text=self._fmt(recv))
        self._ul_lbl.config(text=self._fmt(sent))

        # Stat rows
        self._peak_dl_lbl.config(text=self._fmt(self._peak_recv))
        self._peak_ul_lbl.config(text=self._fmt(self._peak_sent))

        try:
            c = psutil.net_io_counters()
            self._total_recv_lbl.config(text=bytes_to_human(c.bytes_recv))
            self._total_sent_lbl.config(text=bytes_to_human(c.bytes_sent))
            per_nic = psutil.net_io_counters(pernic=True)
            if per_nic:
                best = max(per_nic, key=lambda k: per_nic[k].bytes_recv)
                self._iface_lbl.config(text=best)
        except Exception:
            pass


# ─────────────────────────────────────────────
# DashboardFrame
# ─────────────────────────────────────────────
class DashboardFrame(tk.Frame):
    """
    2x2 symmetric card grid:
        ┌──────────────┬──────────────┐
        │  CPU Usage   │   Memory     │
        ├──────────────┼──────────────┤
        │  Disk  /     │  Swap Memory │
        └──────────────┴──────────────┘
    """

    def __init__(self, parent, app=None, **kwargs):
        super().__init__(parent, bg=THEME.BG_DARK, **kwargs)
        self.app = app
        self._refresh_job = None
        self._build()
        self._refresh()

    def _build(self):
        # ── status bar (bottom, packed first so it stays fixed) ────
        self.status_bar = StatusBar(self)
        self.status_bar.pack(fill="x", side="bottom")

        # ── section header ─────────────────────
        header = tk.Frame(self, bg=THEME.BG_DARK)
        header.pack(fill="x", padx=20, pady=(16, 0))

        tk.Label(header, text="System Overview", bg=THEME.BG_DARK,
                 fg=THEME.TEXT_PRIMARY, font=THEME.FONT_SECTION).pack(side="left")

        # Refresh button
        btn_border = tk.Frame(header, bg=THEME.BORDER_CARD,
                              padx=1, pady=1, cursor="hand2")
        btn_border.pack(side="right")
        self.refresh_btn = tk.Label(
            btn_border, text="  <>  Refresh  ",
            bg=THEME.BG_CARD, fg=THEME.TEXT_SECONDARY,
            font=THEME.FONT_DETAIL, cursor="hand2"
        )
        self.refresh_btn.pack()
        for w in (btn_border, self.refresh_btn):
            w.bind("<Button-1>", lambda _: self._refresh())
            w.bind("<Enter>",
                   lambda _, b=self.refresh_btn: b.config(fg=THEME.ACCENT))
            w.bind("<Leave>",
                   lambda _, b=self.refresh_btn: b.config(fg=THEME.TEXT_SECONDARY))

        # ── scrollable canvas ──────────────────
        canvas = tk.Canvas(self, bg=THEME.BG_DARK, highlightthickness=0)
        scrollbar = tk.Scrollbar(self, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="top", fill="both", expand=True)

        inner = tk.Frame(canvas, bg=THEME.BG_DARK)
        canvas_win = canvas.create_window((0, 0), window=inner, anchor="nw")

        canvas.bind("<Configure>",
                    lambda e: canvas.itemconfig(canvas_win, width=e.width))

        def _update_scrollregion(_e=None):
            canvas.after(50, lambda: canvas.configure(
                scrollregion=canvas.bbox("all")))

        inner.bind("<Configure>", _update_scrollregion)

        def _on_wheel(e):
            delta = e.delta
            if abs(delta) >= 120:
                units = int(delta / 120)
            else:
                units = int(delta / 4) or (1 if delta > 0 else -1)
            canvas.yview_scroll(-units, "units")

        def _bind_scroll():
            self.bind_all("<MouseWheel>", _on_wheel)
            self.bind_all("<Button-4>",   lambda e: canvas.yview_scroll(-3, "units"))
            self.bind_all("<Button-5>",   lambda e: canvas.yview_scroll(3,  "units"))

        def _unbind_scroll():
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

        # Activate scroll whenever this frame is visible
        self.bind("<Map>",     lambda e: _bind_scroll()   if e.widget is self else None)
        self.bind("<Unmap>",   lambda e: _unbind_scroll() if e.widget is self else None)
        self.bind("<Destroy>", lambda e: _unbind_scroll() if e.widget is self else None)
        # Bind immediately since frame is already being built
        self.after(10, _bind_scroll)

        # ── 2x3 grid inside canvas ─────────────
        # grid fills width only — height comes from row minsizes so
        # inner's true content height drives the scrollregion correctly.
        grid = tk.Frame(inner, bg=THEME.BG_DARK)
        grid.pack(fill="x", padx=12, pady=12)
        grid.columnconfigure(0, weight=1)
        grid.columnconfigure(1, weight=1)
        grid.rowconfigure(0, weight=0)
        grid.rowconfigure(1, weight=0)
        grid.rowconfigure(2, weight=0, minsize=377)

        self.cpu_card = MetricCard(
            grid, title="CPU Usage",
            detail_keys=("Usage", "Cores", "Freq")
        )
        self.cpu_card.grid(row=0, column=0, padx=6, pady=6, sticky="nsew")

        self.mem_card = MetricCard(
            grid, title="Memory",
            detail_keys=("Used", "Free", "Total")
        )
        self.mem_card.grid(row=0, column=1, padx=6, pady=6, sticky="nsew")

        self.disk_card = MetricCard(
            grid, title="Disk",
            detail_keys=("Used", "Free", "Total")
        )
        self.disk_card.grid(row=1, column=0, padx=6, pady=6, sticky="nsew")

        self.swap_card = MetricCard(
            grid, title="Swap Memory",
            detail_keys=("Used", "Free", "Total")
        )
        self.swap_card.grid(row=1, column=1, padx=6, pady=6, sticky="nsew")

        # Network card spans full width
        self.net_card = NetworkCard(grid)
        self.net_card.grid(row=2, column=0, columnspan=2,
                           padx=6, pady=6, sticky="nsew")

    def _get_metrics(self) -> dict:
        """
        Fetch all system metrics via psutil.
        cpu_percent(interval=None) is non-blocking - returns delta
        since last call, which is accurate over our 10s refresh cycle.
        """
        cpu_pct     = psutil.cpu_percent(interval=None)
        cpu_cores   = psutil.cpu_count(logical=False) or 1
        cpu_logical = psutil.cpu_count(logical=True)  or cpu_cores
        try:
            freq = psutil.cpu_freq()
            cpu_freq = f"{freq.current / 1000:.2f} GHz" if freq else "N/A"
        except Exception:
            cpu_freq = "N/A"

        mem  = psutil.virtual_memory()
        if platform.system() == "Darwin" and os.path.exists("/System/Volumes/Data"):
            _disk_path = "/System/Volumes/Data"
        else:
            _disk_path = str(Path("/").anchor)   # "/" on macOS/Linux, "C:\" on Windows
        disk = psutil.disk_usage(_disk_path)
        swap = psutil.swap_memory()
        net_sent, net_recv = _net_rate()

        return {
            "cpu_pct":     cpu_pct,
            "cpu_cores":   cpu_cores,
            "cpu_logical": cpu_logical,
            "cpu_freq":    cpu_freq,

            "mem_pct":   mem.percent,
            "mem_used":  bytes_to_human(mem.used),
            "mem_free":  bytes_to_human(mem.available),
            "mem_total": bytes_to_human(mem.total),

            "disk_pct":   disk.percent,
            "disk_used":  bytes_to_human(disk.used),
            "disk_free":  bytes_to_human(disk.free),
            "disk_total": bytes_to_human(disk.total),

            "swap_pct":   swap.percent,
            "swap_used":  bytes_to_human(swap.used)  if swap.total else "0 MB",
            "swap_free":  bytes_to_human(swap.free)  if swap.total else "0 MB",
            "swap_total": bytes_to_human(swap.total) if swap.total else "0 MB",

            "net_sent": net_sent,
            "net_recv": net_recv,
        }

    def _refresh(self):
        """Push fresh metrics to all cards, then schedule next refresh."""
        m = self._get_metrics()

        self.cpu_card.update(
            pct=m["cpu_pct"],
            details={
                "Usage": f"{m['cpu_pct']:.1f}%",
                "Cores": f"{m['cpu_cores']} physical / {m['cpu_logical']} logical",
                "Freq":  m["cpu_freq"],
            }
        )
        self.mem_card.update(
            pct=m["mem_pct"],
            details={"Used": m["mem_used"], "Free": m["mem_free"],
                     "Total": m["mem_total"]}
        )
        self.disk_card.update(
            pct=m["disk_pct"],
            details={"Used": m["disk_used"], "Free": m["disk_free"],
                     "Total": m["disk_total"]}
        )
        self.swap_card.update(
            pct=m["swap_pct"],
            details={"Used": m["swap_used"], "Free": m["swap_free"],
                     "Total": m["swap_total"]}
        )
        self.net_card.update(m["net_sent"], m["net_recv"])
        self.status_bar.update(
            m["cpu_pct"], m["mem_pct"], m["disk_pct"], m["swap_pct"]
        )

        # Cancel any existing timer before scheduling to prevent stacking
        if self._refresh_job is not None:
            self.after_cancel(self._refresh_job)
        self._refresh_job = self.after(REFRESH_MS, self._refresh)


# ─────────────────────────────────────────────
# Standalone runner
# ─────────────────────────────────────────────
def _run_standalone():
    root = tk.Tk()
    root.title("Dashboard - Module 2 Test")
    root.geometry("860x620")
    root.minsize(700, 520)
    root.configure(bg=THEME.BG_DARK)
    DashboardFrame(root).pack(fill="both", expand=True)
    root.mainloop()


# ─────────────────────────────────────────────
# Test suite  (python dashboard.py --test)
# ─────────────────────────────────────────────
def _run_tests():
    print("=" * 50)
    print("Module 2 - dashboard.py test suite (v2)")
    print("=" * 50)
    passed = 0
    failed = 0

    def check(name, condition, detail=""):
        nonlocal passed, failed
        if condition:
            print(f"  [OK]  {name}"); passed += 1
        else:
            print(f"  [!!]  {name}" + (f" > {detail}" if detail else ""))
            failed += 1

    # 1. psutil importable
    try:
        import psutil as _p
        check("psutil importable", True)
    except ImportError as e:
        check("psutil importable", False, str(e))

    # 2. bytes_to_human
    check("10 GB",  bytes_to_human(10  * 1024**3) == "10.0 GB")
    check("512 MB", bytes_to_human(512 * 1024**2) == "512 MB")
    check("1.5 GB", "GB" in bytes_to_human(1_500_000_000))

    # 3. threshold_color
    check("green  0–59",  threshold_color(30) == THEME.ACCENT)
    check("yellow 60–84", threshold_color(70) == THEME.WARN)
    check("red    85+",   threshold_color(90) == THEME.DANGER)
    check("boundary 60",  threshold_color(60) == THEME.WARN)
    check("boundary 85",  threshold_color(85) == THEME.DANGER)

    # 4. psutil sanity
    cpu  = psutil.cpu_percent(interval=0.1)
    mem  = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path("/").anchor))
    swap = psutil.swap_memory()

    check("cpu  0–100",   0 <= cpu          <= 100, f"got {cpu}")
    check("mem  0–100",   0 <= mem.percent  <= 100)
    check("disk 0–100",   0 <= disk.percent <= 100)
    check("swap >= 0",    swap.percent >= 0)
    check("mem total > 0", mem.total > 0)
    check("disk total > 0", disk.total > 0)

    # 5. widget creation
    try:
        root = tk.Tk()
        root.withdraw()

        g = ArcGauge(root, size=120, thickness=10)
        g.set_value(55)
        check("ArcGauge value stored", g.pct == 55)

        c = MetricCard(root, "Test", ("Used", "Free", "Total"))
        c.update(40, {"Used": "4 GB", "Free": "8 GB", "Total": "16 GB"})
        check("MetricCard Used",  c.detail_labels["Used"].cget("text")  == "4 GB")
        check("MetricCard Total", c.detail_labels["Total"].cget("text") == "16 GB")

        f = DashboardFrame(root)
        check("DashboardFrame created", True)

        root.destroy()
    except Exception as e:
        check("widget creation", False, str(e))

    print("-" * 50)
    print(f"  {passed} passed · {failed} failed")
    print("=" * 50)
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    if "--test" in sys.argv:
        _run_tests()
    else:
        _run_standalone()
