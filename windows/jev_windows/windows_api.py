from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass

import win32gui
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


def screenshot(rect: Rect):
    return ImageGrab.grab((rect.left, rect.top, rect.right, rect.bottom), all_screens=True)

