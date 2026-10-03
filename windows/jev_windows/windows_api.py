from __future__ import annotations

from .i18n import msg

import ctypes
from ctypes import wintypes
from contextlib import contextmanager
from dataclasses import dataclass
import os

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


class NativeWindowError(RuntimeError):
    """Native identity or physical geometry could not be established safely."""


@dataclass(frozen=True)
class WindowSnapshot:
    hwnd: int
    pid: int
    creation_time: int
    app_path: str
    window_class: str
    client_rect: Rect
    dpi: int
    title: str
    visible: bool
    minimized: bool
    cloaked: bool = False

    @property
    def identity(self) -> tuple:
        return (self.hwnd, self.pid, self.creation_time,
                self.window_class, self.app_path.casefold())


_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_KERNEL32.OpenProcess.restype = wintypes.HANDLE
_KERNEL32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
_KERNEL32.GetProcessTimes.restype = wintypes.BOOL
_KERNEL32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
_KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.CloseHandle.restype = wintypes.BOOL
_USER32.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
_USER32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
_USER32.GetDpiForWindow.argtypes = [wintypes.HWND]
_USER32.GetDpiForWindow.restype = wintypes.UINT
_USER32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_USER32.GetWindowThreadProcessId.restype = wintypes.DWORD
_DWMAPI = ctypes.WinDLL("dwmapi", use_last_error=True)
_DWMAPI.DwmGetWindowAttribute.argtypes = [
    wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
_DWMAPI.DwmGetWindowAttribute.restype = ctypes.c_long


@contextmanager
def physical_window_coordinates():
    """Binding never relies on the process-wide DPI-awareness fallback."""
    previous = _USER32.SetThreadDpiAwarenessContext(_DPI_CONTEXT_PER_MONITOR_V2)
    if not previous:
        raise NativeWindowError("Physical window coordinates unavailable")
    try:
        yield
    finally:
        if not _USER32.SetThreadDpiAwarenessContext(previous):
            raise NativeWindowError("Could not restore DPI context")


def current_process_id() -> int:
    return os.getpid()


def process_identity(pid: int) -> tuple[str, int]:
    """Read executable and creation FILETIME using one limited-query handle."""
    handle = _KERNEL32.OpenProcess(0x1000, False, pid)
    if not handle:
        raise NativeWindowError("Window process unavailable")
    try:
        times = [wintypes.FILETIME() for _ in range(4)]
        if not _KERNEL32.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
            raise NativeWindowError("Process creation time unavailable")
        path = ctypes.create_unicode_buffer(32768)
        length = wintypes.DWORD(len(path))
        if not _KERNEL32.QueryFullProcessImageNameW(handle, 0, path, ctypes.byref(length)):
            raise NativeWindowError("Window executable unavailable")
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        return path.value, created
    finally:
        _KERNEL32.CloseHandle(handle)


def _window_process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    if not _USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid)) or not pid.value:
        raise NativeWindowError("Window unavailable")
    return pid.value


def _window_cloaked(hwnd: int) -> bool:
    value = wintypes.DWORD()
    result = _DWMAPI.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(value), ctypes.sizeof(value))
    if result != 0:
        raise NativeWindowError("Window visibility unavailable")
    return bool(value.value)


def window_snapshot(hwnd: int) -> WindowSnapshot:
    """Fresh identity plus physical ClientToScreen corners; no cached PID data."""
    try:
        with physical_window_coordinates():
            if not win32gui.IsWindow(hwnd) or win32gui.GetAncestor(hwnd, win32con.GA_ROOT) != hwnd:
                raise NativeWindowError("Root window unavailable")
            pid = _window_process_id(hwnd)
            path, created = process_identity(pid)
            window_class = win32gui.GetClassName(hwnd)
            minimized = bool(win32gui.IsIconic(hwnd))
            left, top, right, bottom = win32gui.GetClientRect(hwnd)
            x1, y1 = win32gui.ClientToScreen(hwnd, (left, top))
            x2, y2 = win32gui.ClientToScreen(hwnd, (right, bottom))
            dpi = _USER32.GetDpiForWindow(hwnd)
            invalid_geometry = not dpi or x2 <= x1 or y2 <= y1
            # Minimized windows can report an empty client or zero DPI. Keep
            # their real identity and raw geometry so the service can prompt
            # restore without retiring the binding. Capture rejects IsIconic.
            if invalid_geometry and not minimized:
                raise NativeWindowError("Client geometry unavailable")
            result = WindowSnapshot(
                hwnd, pid, created, path, window_class, Rect(x1, y1, x2, y2), dpi,
                win32gui.GetWindowText(hwnd), bool(win32gui.IsWindowVisible(hwnd)),
                minimized, _window_cloaked(hwnd))
            # A HWND/PID may be destroyed and reused while the native reads run.
            if (_window_process_id(hwnd) != pid or process_identity(pid) != (path, created)
                    or win32gui.GetClassName(hwnd) != window_class):
                raise NativeWindowError("Window identity changed")
            if invalid_geometry and not win32gui.IsIconic(hwnd):
                raise NativeWindowError("Client geometry unavailable")
            return result
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError("Window unavailable") from exc


def root_window_at(x: int, y: int) -> int:
    try:
        with physical_window_coordinates():
            hwnd = win32gui.WindowFromPoint((x, y))
            return win32gui.GetAncestor(hwnd, win32con.GA_ROOT) if hwnd else 0
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError("Window unavailable") from exc


def root_windows() -> list[int]:
    """Top-to-bottom Z order, INCLUDING owned popups (GA_ROOT, not ROOTOWNER)."""
    try:
        result: list[int] = []
        seen: set[int] = set()
        hwnd = win32gui.GetTopWindow(0)
        while hwnd:
            if hwnd in seen or len(result) >= 10000:
                raise NativeWindowError("Window order changed")
            seen.add(hwnd)
            result.append(hwnd)
            hwnd = win32gui.GetWindow(hwnd, win32con.GW_HWNDNEXT)
        return result
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError("Window order unavailable") from exc


def visible_window_bounds(hwnd: int) -> Rect | None:
    """Conservative occluder bounds; layered/transparent/owned windows count."""
    try:
        with physical_window_coordinates():
            if not win32gui.IsWindow(hwnd):
                raise NativeWindowError("Window order changed")
            if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd) or _window_cloaked(hwnd):
                return None
            # GetWindowRect includes borders/shadows: extra rejection is safe.
            return Rect(*win32gui.GetWindowRect(hwnd))
    except NativeWindowError:
        raise
    except Exception as exc:
        raise NativeWindowError("Occluder geometry unavailable") from exc


def monitor_rects() -> list[Rect]:
    """Actual monitor coverage, so gaps in the virtual bounding box are rejected."""
    rectangles: list[Rect] = []
    callback_type = ctypes.WINFUNCTYPE(
        wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
        ctypes.POINTER(wintypes.RECT), wintypes.LPARAM)

    @callback_type
    def collect(_monitor, _dc, rectangle, _data):
        r = rectangle.contents
        rectangles.append(Rect(r.left, r.top, r.right, r.bottom))
        return True

    enum = _USER32.EnumDisplayMonitors
    enum.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), callback_type, wintypes.LPARAM]
    enum.restype = wintypes.BOOL
    with physical_window_coordinates():
        if not enum(None, None, collect, 0):
            raise NativeWindowError("Monitor coverage unavailable")
    return rectangles


def selection_on_screen(rect: Rect) -> bool:
    remaining = [rect]
    for monitor in monitor_rects():
        next_remaining: list[Rect] = []
        for part in remaining:
            l, t = max(part.left, monitor.left), max(part.top, monitor.top)
            r, b = min(part.right, monitor.right), min(part.bottom, monitor.bottom)
            if l >= r or t >= b:
                next_remaining.append(part)
                continue
            next_remaining.extend(piece for piece in (
                Rect(part.left, part.top, part.right, t),
                Rect(part.left, b, part.right, part.bottom),
                Rect(part.left, t, l, b), Rect(r, t, part.right, b),
            ) if piece.width and piece.height)
        remaining = next_remaining
    return rect.width > 0 and rect.height > 0 and not remaining
