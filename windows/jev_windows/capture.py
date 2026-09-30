from __future__ import annotations

from .i18n import msg

import re
from collections.abc import Callable
from dataclasses import dataclass

from .models import ChatSnapshot, Message, Rect
from .windows_api import screenshot


_OCR_ENGINE = None

# --- OCR extraction tuning -------------------------------------------------------
# These values were tuned against real chat layouts. They encode layout
# assumptions, so keep the intent with the number when adjusting.
# --- Row/message grouping --------------------------------------------------------
# Two boxes share a row when their vertical centers are within this many pixels...
ROW_TOLERANCE_MIN_PX = 13
# ...or within this fraction of the taller box's height, whichever is larger.
ROW_TOLERANCE_HEIGHT_RATIO = 0.65
# Fraction of the region width around the midline treated as "system/timestamp".
CENTER_DEAD_ZONE_RATIO = 0.07
# Centered lines narrower than this fraction of the width are system notices.
CENTER_LINE_MAX_WIDTH_RATIO = 0.55
# Consecutive same-speaker lines merge when vertically within this many pixels...
MESSAGE_MERGE_MIN_GAP_PX = 8
# ...or this fraction of the shorter box height.
MESSAGE_MERGE_GAP_RATIO = 0.45
# Negative gaps occur from slight overlap; tolerate this many pixels.
MESSAGE_MERGE_OVERLAP_PX = 2
# Merged lines must share a left (other) or right (me) edge within this fraction.
EDGE_ALIGNMENT_RATIO = 0.08
# Cap how many trailing messages are sent for analysis.
MAX_MESSAGES = 10


@dataclass(frozen=True)
class TextBox:
    text: str
    rect: Rect


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _ocr_boxes(area: Rect, image: object | None = None) -> list[TextBox]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError(msg("error.ocrMissing")) from exc

    global _OCR_ENGINE
    if image is None:
        image = screenshot(area)
    if _OCR_ENGINE is None:
        # Keep ONNX from occupying every core while the desktop UI is visible.
        _OCR_ENGINE = RapidOCR(intra_op_num_threads=1, inter_op_num_threads=1)
    result, _ = _OCR_ENGINE(image)
    boxes: list[TextBox] = []
    for item in result or []:
        polygon, text = item[0], _clean_text(str(item[1]))
        if not text:
            continue
        xs = [int(point[0]) + area.left for point in polygon]
        ys = [int(point[1]) + area.top for point in polygon]
        boxes.append(TextBox(text, Rect(min(xs), min(ys), max(xs), max(ys))))
    return boxes


def _boxes_to_messages(boxes: list[TextBox], area: Rect) -> list[Message]:
    if not boxes:
        return []
    boxes = sorted(boxes, key=lambda box: (box.rect.top, box.rect.left))
    rows: list[list[TextBox]] = []
    for box in boxes:
        cy = (box.rect.top + box.rect.bottom) / 2
        if rows:
            last_cy = sum((b.rect.top + b.rect.bottom) / 2 for b in rows[-1]) / len(rows[-1])
            tolerance = max(ROW_TOLERANCE_MIN_PX, box.rect.height * ROW_TOLERANCE_HEIGHT_RATIO)
            if abs(cy - last_cy) <= tolerance:
                rows[-1].append(box)
                continue
        rows.append([box])

    messages: list[Message] = []
    message_bounds: list[Rect] = []
    midpoint = area.left + area.width / 2
    dead_zone = area.width * CENTER_DEAD_ZONE_RATIO
    for row in rows:
        row.sort(key=lambda box: box.rect.left)
        text = _clean_text(" ".join(box.text for box in row))
        left = min(box.rect.left for box in row)
        top = min(box.rect.top for box in row)
        right = max(box.rect.right for box in row)
        bottom = max(box.rect.bottom for box in row)
        bound = Rect(left, top, right, bottom)
        center = (left + right) / 2
        # Timestamp/system lines are normally centered and should not be treated
        # as either speaker.
        if abs(center - midpoint) <= dead_zone and right - left < area.width * CENTER_LINE_MAX_WIDTH_RATIO:
            continue
        side = "me" if center > midpoint else "other"
        if messages and messages[-1].side == side:
            previous = message_bounds[-1]
            gap = bound.top - previous.bottom
            edge_delta = (
                abs(bound.right - previous.right)
                if side == "me"
                else abs(bound.left - previous.left)
            )
            max_gap = max(
                MESSAGE_MERGE_MIN_GAP_PX,
                min(bound.height, previous.height) * MESSAGE_MERGE_GAP_RATIO,
            )
            if -MESSAGE_MERGE_OVERLAP_PX <= gap <= max_gap and edge_delta <= area.width * EDGE_ALIGNMENT_RATIO:
                messages[-1] = Message(side, f"{messages[-1].text} {text}")
                message_bounds[-1] = Rect(
                    min(previous.left, bound.left),
                    min(previous.top, bound.top),
                    max(previous.right, bound.right),
                    max(previous.bottom, bound.bottom),
                )
                continue
        messages.append(Message(side, text))
        message_bounds.append(bound)
    return [message for message in messages if message.text][-MAX_MESSAGES:]


def capture_desktop_chat(
    screen_rect: Rect,
    capture_frame: Callable[[Rect], tuple[object, str]] | None = None,
) -> ChatSnapshot:
    """OCR a selected desktop region without requiring a particular app."""
    from .windows_api import virtual_screen_rect, window_title_at

    desktop = virtual_screen_rect()
    if (
        screen_rect.width < 80
        or screen_rect.height < 40
        or screen_rect.left < desktop.left
        or screen_rect.top < desktop.top
        or screen_rect.right > desktop.right
        or screen_rect.bottom > desktop.bottom
    ):
        raise RuntimeError(msg("error.offscreen"))
    if capture_frame is None:
        image = screenshot(screen_rect)
        title = window_title_at(
            screen_rect.left + screen_rect.width // 2,
            screen_rect.top + screen_rect.height // 2,
        )
    else:
        image, title = capture_frame(screen_rect)
    boxes = _ocr_boxes(screen_rect, image)
    messages = _boxes_to_messages(boxes, screen_rect)
    if not messages:
        raise RuntimeError(msg("error.noText"))
    # Keep the raw window title; the localized fallback is applied at display time
    # so the allowlist check never matches against translated placeholder text.
    return ChatSnapshot(title or "", messages, "\n".join(box.text for box in boxes))
