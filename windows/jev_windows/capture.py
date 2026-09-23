from __future__ import annotations

import re
from dataclasses import dataclass

from .models import ChatSnapshot, Message, Rect
from .windows_api import WeChatWindow, client_rect_on_screen, screenshot


_OCR_ENGINE = None


@dataclass(frozen=True)
class TextBox:
    text: str
    rect: Rect


def _absolute_rect(window: WeChatWindow, relative: Rect) -> Rect:
    client = client_rect_on_screen(window.hwnd)
    return Rect(
        client.left + relative.left,
        client.top + relative.top,
        client.left + relative.right,
        client.top + relative.bottom,
    )


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _uia_boxes(window: WeChatWindow, area: Rect) -> list[TextBox]:
    """Best-effort UI Automation extraction; modern WeChat may expose no text."""
    try:
        import uiautomation as auto

        root = auto.ControlFromHandle(window.hwnd)
        boxes: list[TextBox] = []
        for control, depth in auto.WalkControl(root, maxDepth=14):
            if depth == 0:
                continue
            name = _clean_text(control.Name or "")
            if not name or len(name) > 500:
                continue
            bound = control.BoundingRectangle
            rect = Rect(int(bound.left), int(bound.top), int(bound.right), int(bound.bottom))
            cx = (rect.left + rect.right) // 2
            cy = (rect.top + rect.bottom) // 2
            if area.contains(cx, cy) and rect.width > 1 and rect.height > 1:
                boxes.append(TextBox(name, rect))
        # A useful accessibility result has multiple distinct chat lines. A lone
        # container name is not enough, so let OCR handle it.
        distinct = {box.text for box in boxes}
        return boxes if len(distinct) >= 2 else []
    except Exception:
        return []


def _ocr_boxes(area: Rect) -> list[TextBox]:
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError("未安装本地 OCR 组件，请运行 windows\\install.ps1。") from exc

    global _OCR_ENGINE
    image = screenshot(area)
    if _OCR_ENGINE is None:
        _OCR_ENGINE = RapidOCR()
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
            tolerance = max(13, box.rect.height * 0.65)
            if abs(cy - last_cy) <= tolerance:
                rows[-1].append(box)
                continue
        rows.append([box])

    messages: list[Message] = []
    message_bounds: list[Rect] = []
    midpoint = area.left + area.width / 2
    dead_zone = area.width * 0.07
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
        if abs(center - midpoint) <= dead_zone and right - left < area.width * 0.55:
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
            max_gap = max(8, min(bound.height, previous.height) * 0.45)
            if -2 <= gap <= max_gap and edge_delta <= area.width * 0.08:
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
    return [message for message in messages if message.text][-10:]


def capture_chat(window: WeChatWindow, relative_chat_rect: Rect) -> ChatSnapshot:
    area = _absolute_rect(window, relative_chat_rect)
    client = client_rect_on_screen(window.hwnd)
    if (
        area.left < client.left
        or area.top < client.top
        or area.right > client.right
        or area.bottom > client.bottom
    ):
        raise RuntimeError("微信窗口尺寸已变化，请重新框选聊天区域。")
    boxes = _uia_boxes(window, area)
    if not boxes:
        boxes = _ocr_boxes(area)
    messages = _boxes_to_messages(boxes, area)
    if not messages:
        raise RuntimeError("没有识别到聊天文字，请确认聊天窗口可见并重新框选聊天区域。")
    raw_text = "\n".join(box.text for box in boxes)
    return ChatSnapshot(window.title or "微信聊天", messages, raw_text)
