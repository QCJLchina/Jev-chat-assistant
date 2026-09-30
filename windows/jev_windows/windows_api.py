from __future__ import annotations

from .i18n import msg

import ctypes
from ctypes import wintypes

import win32gui
import win32con
from PIL import ImageGrab

from .models import Rect


_USER32 = ctypes.WinDLL("user32", use_last_error=True)
_USER32.GetSystemMetrics.argtypes = [ctypes.c_int]
_USER32.GetSystemMetrics.restype = ctypes.c_int

_DPI_SET = False
_DPI_CONTEXT_PER_MONITOR_V2 = ctypes.c_void_p(-4)


def ensure_dpi_awareness() -> bool:
    """Make screen, Tk, and screenshot coordinates share physical pixels.

    Without this, a non-DPI-aware process gets virtualized coordinates on
    scaled displays, so the selection overlay and the captured image disagree.
    """
    global _DPI_SET
    if _DPI_SET:
        return True
    # Prefer per-monitor v2: on mixed-DPI laptops (e.g. a scaled laptop panel
    # next to a 100% external monitor), v2 keeps physical-pixel coordinates
    # per monitor instead of virtualizing the secondary display.
    try:
        set_context = _USER32.SetProcessDpiAwarenessContext
        set_context.argtypes = [ctypes.c_void_p]
        set_context.restype = wintypes.BOOL
        if set_context(_DPI_CONTEXT_PER_MONITOR_V2):
            _DPI_SET = True
            return True
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PER_MONITOR_AWARE
        _DPI_SET = True
        return True
    except (AttributeError, OSError):
        try:
            _DPI_SET = bool(_USER32.SetProcessDPIAware())
        except (AttributeError, OSError):
            return False
    return _DPI_SET


def virtual_screen_rect() -> Rect:
    """Bounds of all attached monitors in virtual-desktop coordinates."""
    left = _USER32.GetSystemMetrics(76)  # SM_XVIRTUALSCREEN
    top = _USER32.GetSystemMetrics(77)  # SM_YVIRTUALSCREEN
    width = _USER32.GetSystemMetrics(78)  # SM_CXVIRTUALSCREEN
    height = _USER32.GetSystemMetrics(79)  # SM_CYVIRTUALSCREEN
    return Rect(left, top, left + width, top + height)


def window_title_at(x: int, y: int) -> str:
    hwnd = win32gui.WindowFromPoint((x, y))
    root = win32gui.GetAncestor(hwnd, win32con.GA_ROOT)
    return win32gui.GetWindowText(root or hwnd).strip()


def screenshot(rect: Rect):
    return ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom), all_screens=True)
