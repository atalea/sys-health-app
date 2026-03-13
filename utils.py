"""
System Health Monitor
==================
Module: utils.py
Responsibility: Shared widgets and helper functions used across modules.

Exports
-------
bytes_to_human(n)   - convert byte count to human-readable string
ToggleSwitch        - pill-shaped on/off toggle canvas widget
"""

import tkinter as tk
from app_config import THEME


# ─────────────────────────────────────────────
# bytes_to_human
# ─────────────────────────────────────────────
def bytes_to_human(n: int) -> str:
    """Convert a byte count to a human-readable GB / MB / KB string."""
    gb = n / (1024 ** 3)
    if gb >= 1:
        return f"{gb:.1f} GB"
    mb = n / (1024 ** 2)
    if mb >= 1:
        return f"{mb:.0f} MB"
    kb = n / 1024
    if kb >= 1:
        return f"{kb:.0f} KB"
    return f"{n} B"


# ─────────────────────────────────────────────
# ToggleSwitch
# ─────────────────────────────────────────────
class ToggleSwitch(tk.Canvas):
    """
    Pill-shaped on/off toggle drawn on a Canvas.

    Width=46, Height=24 gives a proportional macOS-style toggle.
    The knob slides left/right to indicate state.

    Parameters
    ----------
    parent      : tk parent widget
    value       : initial boolean state (default False)
    on_change   : optional callback(bool) fired on each toggle
    bg          : background colour (defaults to THEME.BG_CARD)
    command     : alias for on_change (accepted for backward compatibility)

    Usage
    -----
        toggle = ToggleSwitch(parent, value=True, on_change=my_callback)
        toggle.set(False)
        state = toggle.get()   # bool
    """

    W, H, R = 46, 24, 11

    def __init__(self, parent, value: bool = False,
                 on_change=None, command=None, bg: str = None, **kwargs):
        _bg = bg or THEME.BG_CARD
        kwargs.pop("bg", None)
        super().__init__(
            parent,
            width=self.W, height=self.H,
            bg=_bg, highlightthickness=0,
            cursor="hand2", **kwargs
        )
        self._value = bool(value)
        # Accept either keyword for callbacks
        self.on_change = on_change or command
        self._draw()
        self.bind("<Button-1>", self._toggle)

    def _draw(self):
        self.delete("all")
        color = THEME.ACCENT if self._value else THEME.BORDER_CARD
        x1, y1, x2, y2 = 2, 2, self.W - 2, self.H - 2
        # Pill track
        self.create_oval(x1, y1, x1 + self.H - 4, y2, fill=color, outline="")
        self.create_oval(x2 - self.H + 4, y1, x2, y2, fill=color, outline="")
        self.create_rectangle(
            x1 + self.H // 2 - 2, y1,
            x2 - self.H // 2 + 2, y2,
            fill=color, outline=""
        )
        # Knob
        kx = self.W - 4 - self.R if self._value else 4 + self.R
        self.create_oval(
            kx - self.R, self.H // 2 - self.R,
            kx + self.R, self.H // 2 + self.R,
            fill="white", outline=""
        )

    def _toggle(self, _event=None):
        self._value = not self._value
        self._draw()
        if self.on_change:
            self.on_change(self._value)

    def get(self) -> bool:
        return self._value

    def set(self, value: bool):
        self._value = bool(value)
        self._draw()
