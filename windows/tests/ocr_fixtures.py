"""Frozen OCR samples for the chat-extraction pipeline.

These are *recorded shapes of real OCR output* (box positions are uneven, rows
are a few pixels off, separators leak into the text), not hand-drawn perfect
rectangles. They exist so the tuning constants at the top of
`jev_windows.capture` cannot be changed without a visible diff: each scenario
states the message split it must produce.

This module is intentionally not named `test_*` so pytest does not collect it.
"""
from __future__ import annotations

from jev_windows.capture import TextBox
from jev_windows.models import Rect


def _box(text: str, left: int, top: int, right: int, bottom: int) -> TextBox:
    return TextBox(text, Rect(left, top, right, bottom))


# A plain 1000x800 selection on the primary monitor.
DESKTOP = Rect(0, 0, 1000, 800)
# A selection on a monitor placed to the left of the primary one.
LEFT_MONITOR = Rect(-1920, 0, 0, 1080)


OCR_SCENARIOS: list[dict] = [
    {
        "name": "centered_timestamp_is_not_a_speaker",
        "why": (
            "A system notice sits near the midline but off centre; the dead zone "
            "must still swallow it. This locks CENTER_DEAD_ZONE_RATIO (at 0 the "
            "timestamp becomes a bogus 'other' message)."
        ),
        "area": DESKTOP,
        "boxes": [
            _box("10:30", 470, 130, 570, 150),
            _box("你今天有空吗", 100, 220, 300, 260),
            _box("晚上可以", 700, 320, 940, 360),
        ],
        "expected": [("other", "你今天有空吗"), ("me", "晚上可以")],
    },
    {
        "name": "same_visual_row_is_joined_left_to_right",
        "why": "One rendered line split into several boxes is still one message.",
        "area": DESKTOP,
        "boxes": [
            _box("明天", 100, 200, 180, 230),
            _box("见", 190, 201, 230, 231),
        ],
        "expected": [("other", "明天 见")],
    },
    {
        "name": "wrapped_lines_of_one_bubble_merge",
        "why": "A wrapped bubble shares the right edge for 'me' and must merge.",
        "area": DESKTOP,
        "boxes": [
            _box("这个任务最后", 680, 200, 900, 228),
            _box("需要什么格式", 690, 232, 900, 260),
        ],
        "expected": [("me", "这个任务最后 需要什么格式")],
    },
    {
        "name": "edge_misalignment_blocks_a_merge",
        "why": (
            "Vertically adjacent, same-side boxes with different left edges are "
            "separate bubbles; this locks EDGE_ALIGNMENT_RATIO."
        ),
        "area": DESKTOP,
        "boxes": [
            _box("第一个气泡", 60, 200, 300, 240),
            _box("第二个气泡", 200, 242, 440, 282),
        ],
        "expected": [("other", "第一个气泡"), ("other", "第二个气泡")],
    },
    {
        "name": "wide_centered_row_is_still_a_bubble",
        "why": (
            "Only narrow centered rows are system notices; a wide centered bubble "
            "must survive. This locks CENTER_LINE_MAX_WIDTH_RATIO."
        ),
        "area": DESKTOP,
        "boxes": [
            _box("这是一条很长很长的居中气泡内容需要保留下来", 150, 300, 850, 340),
        ],
        "expected": [("other", "这是一条很长很长的居中气泡内容需要保留下来")],
    },
    {
        "name": "ocr_separators_are_preserved_for_the_safety_check",
        "why": (
            "Capture collapses whitespace but does NOT strip separators: "
            "'转 账' must reach safety.normalize intact, which is what makes the "
            "transaction block work on spaced OCR output."
        ),
        "area": DESKTOP,
        "boxes": [
            _box("转 账 记 录", 100, 200, 400, 240),
        ],
        "expected": [("other", "转 账 记 录")],
    },
    {
        "name": "negative_monitor_coordinates_keep_their_side",
        "why": "Multi-monitor selections use negative virtual-desktop coordinates.",
        "area": LEFT_MONITOR,
        "boxes": [
            _box("在吗", -1850, 200, -1700, 240),
            _box("在", -400, 300, -250, 340),
        ],
        "expected": [("other", "在吗"), ("me", "在")],
    },
    {
        "name": "only_the_last_messages_are_sent",
        "why": "A long transcript is capped, the oldest lines are dropped.",
        "area": DESKTOP,
        "boxes": [
            _box(
                f"消息{index:02d}",
                *((100, 100 + index * 50, 300, 130 + index * 50) if index % 2 == 0
                  else (700, 100 + index * 50, 900, 130 + index * 50)),
            )
            for index in range(14)
        ],
        "expected": [
            ("other" if index % 2 == 0 else "me", f"消息{index:02d}")
            for index in range(4, 14)
        ],
    },
    {
        "name": "taller_fonts_are_still_grouped_into_one_row",
        "why": (
            "Rendering scale is not fixed across displays, so row grouping must "
            "follow the ratio of the box height rather than a single pixel value. "
            "This locks ROW_TOLERANCE_HEIGHT_RATIO."
        ),
        "area": Rect(0, 0, 1000, 900),
        "boxes": [
            _box("明天", 100, 400, 180, 460),
            _box("见", 190, 420, 230, 480),
        ],
        "expected": [("other", "明天 见")],
    },
    {
        "name": "small_text_still_shares_a_row",
        "why": (
            "For small text the ratio alone is too tight, so the pixel floor has "
            "to keep the row together. The two boxes are side by side with "
            "different left edges, so the later vertical merge cannot rescue them "
            "by accident: only row grouping can join them. Locks "
            "ROW_TOLERANCE_MIN_PX."
        ),
        "area": Rect(0, 0, 500, 800),
        "boxes": [
            _box("明天", 100, 400, 180, 410),
            _box("见", 200, 412, 300, 422),
        ],
        "expected": [("other", "明天 见")],
    },
    {
        "name": "wide_line_spacing_still_merges_one_bubble",
        "why": (
            "Lines of a large-font bubble are far apart in absolute pixels but "
            "close relative to the line height. This locks MESSAGE_MERGE_GAP_RATIO."
        ),
        "area": Rect(0, 0, 1600, 1200),
        "boxes": [
            _box("这个方案", 100, 200, 900, 300),
            _box("下周再定", 100, 330, 900, 430),
        ],
        "expected": [("other", "这个方案 下周再定")],
    },
    {
        "name": "small_text_still_merges_within_the_pixel_floor",
        "why": (
            "Small bubbles are separated by a gap the ratio would reject but the "
            "pixel floor accepts. This locks MESSAGE_MERGE_MIN_GAP_PX."
        ),
        "area": Rect(0, 0, 1400, 800),
        "boxes": [
            _box("好的", 200, 200, 300, 210),
            _box("收到", 200, 216, 300, 226),
        ],
        "expected": [("other", "好的 收到")],
    },
    {
        "name": "separate_bubbles_with_a_large_gap_stay_separate",
        "why": (
            "A wide vertical gap is not a wrapped bubble, so the message cap and "
            "merge floor must not fuse unrelated messages. This locks the upper "
            "bound of MESSAGE_MERGE_MIN_GAP_PX."
        ),
        "area": Rect(0, 0, 1400, 900),
        "boxes": [
            _box("先说这个", 200, 200, 700, 220),
            _box("再说那个", 200, 320, 700, 340),
        ],
        "expected": [("other", "先说这个"), ("other", "再说那个")],
    },
]


def scenario_by_name(name: str) -> dict:
    for scenario in OCR_SCENARIOS:
        if scenario["name"] == name:
            return scenario
    raise KeyError(name)
