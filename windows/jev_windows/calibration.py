"""Full-screen region picker used to calibrate the chat area.

Kept apart from the bridge so the Tk event plumbing and its coordinate maths do
not sit in the same file as the application workflow.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable

from .i18n import translate
from .models import Rect

# Drag smaller than this is treated as a stray click, not a selection.
MIN_SELECTION_WIDTH = 200
MIN_SELECTION_HEIGHT = 100


def overlay_geometry(rect: Rect) -> str:
    # Tk reads a bare negative offset ("-500") as "distance from the right
    # edge". An explicit "+-500" selects x=-500, which is what secondary
    # monitors to the left of the primary need.
    return f"{rect.width}x{rect.height}+{rect.left}+{rect.top}"


def _relative_to_screen(client: Rect, start: tuple[int, int], end: tuple[int, int]) -> Rect:
    left, right = sorted((start[0], end[0]))
    top, bottom = sorted((start[1], end[1]))
    return Rect(left + client.left, top + client.top, right + client.left, bottom + client.top)


def select_region(
    client: Rect,
    locale: str,
    on_finish: Callable[[Rect | None], None],
) -> None:
    """Show a translucent overlay over the whole virtual desktop.

    `on_finish` receives the chosen screen-space rectangle, or None on cancel.
    Coordinates are already translated from overlay-local to screen space.
    """
    root = tk.Tk()
    root.overrideredirect(True)
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.28)
    root.geometry(overlay_geometry(client))
    canvas = tk.Canvas(root, bg="#111827", highlightthickness=0, cursor="crosshair")
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        client.width // 2, 28,
        text=translate("capture.overlay", locale),
        fill="white", font=("Microsoft YaHei UI", 14, "bold"),
    )
    start: list[tuple[int, int] | None] = [None]
    shape: list[int | None] = [None]

    def finish(rect: Rect | None) -> None:
        root.destroy()
        on_finish(rect)

    def down(event) -> None:
        start[0] = (event.x, event.y)
        shape[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#1497f5", width=4)

    def drag(event) -> None:
        if start[0] and shape[0]:
            canvas.coords(shape[0], start[0][0], start[0][1], event.x, event.y)

    def up(event) -> None:
        if not start[0]:
            return
        finish(_relative_to_screen(client, start[0], (event.x, event.y)))

    canvas.bind("<Button-1>", down)
    canvas.bind("<B1-Motion>", drag)
    canvas.bind("<ButtonRelease-1>", up)
    root.bind("<Escape>", lambda _: finish(None))
    root.mainloop()


def is_usable_selection(rect: Rect) -> bool:
    return rect.width >= MIN_SELECTION_WIDTH and rect.height >= MIN_SELECTION_HEIGHT
