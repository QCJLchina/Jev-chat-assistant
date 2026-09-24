from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import win32gui
import win32con
import win32process
from PIL import ImageGrab

from .models import Rect


WECHAT_EXECUTABLES = {"wechat.exe", "weixin.exe"}

_KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
_KERNEL32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_KERNEL32.OpenProcess.restype = wintypes.HANDLE
_KERNEL32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.LPWSTR,
    ctypes.POINTER(wintypes.DWORD),
]
_KERNEL32.QueryFullProcessImageNameW.restype = wintypes.BOOL
_KERNEL32.CloseHandle.argtypes = [wintypes.HANDLE]
_KERNEL32.CloseHandle.restype = wintypes.BOOL

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


@dataclass(frozen=True)
class WeChatWindow:
    hwnd: int
    title: str
    process_name: str
    rect: Rect


def _process_name(hwnd: int) -> str:
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    process = _KERNEL32.OpenProcess(0x1000, False, pid)
    if not process:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if _KERNEL32.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)):
            return buffer.value.rsplit("\\", 1)[-1]
        return ""
    finally:
        _KERNEL32.CloseHandle(process)


def find_wechat_window() -> WeChatWindow:
    candidates: list[WeChatWindow] = []

    def collect(hwnd: int, _: object) -> bool:
        if not win32gui.IsWindowVisible(hwnd) or win32gui.IsIconic(hwnd):
            return True
        process_name = _process_name(hwnd)
        if process_name.lower() not in WECHAT_EXECUTABLES:
            return True
        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        rect = Rect(left, top, right, bottom)
        if rect.width >= 500 and rect.height >= 400:
            candidates.append(
                WeChatWindow(hwnd, win32gui.GetWindowText(hwnd), process_name, rect)
            )
        return True

    win32gui.EnumWindows(collect, None)
    if not candidates:
        raise RuntimeError("未找到可见的电脑版微信窗口，请先打开微信并进入一个聊天。")
    return max(candidates, key=lambda item: item.rect.width * item.rect.height)


def client_rect_on_screen(hwnd: int) -> Rect:
    left, top = win32gui.ClientToScreen(hwnd, (0, 0))
    client = win32gui.GetClientRect(hwnd)
    return Rect(left, top, left + client[2], top + client[3])


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

