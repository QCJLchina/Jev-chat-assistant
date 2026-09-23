from jev_windows.capture import TextBox, _boxes_to_messages
from jev_windows.models import Rect


def test_boxes_are_classified_by_side_and_center_rows_ignored():
    area = Rect(100, 100, 1100, 900)
    boxes = [
        TextBox("10:30", Rect(560, 130, 640, 150)),
        TextBox("你今天有空吗", Rect(170, 220, 360, 260)),
        TextBox("晚上可以", Rect(810, 310, 1020, 350)),
    ]

    messages = _boxes_to_messages(boxes, area)

    assert [(item.side, item.text) for item in messages] == [
        ("other", "你今天有空吗"),
        ("me", "晚上可以"),
    ]


def test_same_visual_row_is_joined_left_to_right():
    area = Rect(0, 0, 1000, 800)
    boxes = [
        TextBox("明天", Rect(100, 200, 180, 230)),
        TextBox("见", Rect(190, 201, 230, 231)),
    ]

    messages = _boxes_to_messages(boxes, area)

    assert messages[0].text == "明天 见"
    assert messages[0].side == "other"


def test_wrapped_lines_from_one_bubble_are_merged():
    area = Rect(0, 0, 1000, 800)
    boxes = [
        TextBox("这个任务最后", Rect(680, 200, 900, 228)),
        TextBox("需要什么格式", Rect(690, 232, 900, 260)),
    ]

    messages = _boxes_to_messages(boxes, area)

    assert [(item.side, item.text) for item in messages] == [
        ("me", "这个任务最后 需要什么格式")
    ]
