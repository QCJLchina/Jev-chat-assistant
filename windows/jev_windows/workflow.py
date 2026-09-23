from __future__ import annotations

import time
from collections.abc import Callable
from typing import TypeVar


T = TypeVar("T")


def capture_without_overlay(
    hide_overlay: Callable[[], None],
    show_overlay: Callable[[], None],
    capture: Callable[[], T],
    *,
    settle: Callable[[float], None] = time.sleep,
) -> T:
    """Hide our own topmost window so local OCR cannot read itself."""
    hide_overlay()
    try:
        # Let DWM finish removing the window before taking the screenshot.
        settle(0.25)
        return capture()
    finally:
        show_overlay()

