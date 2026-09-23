from jev_windows.workflow import capture_without_overlay


def test_overlay_is_hidden_while_capture_runs_and_restored_afterward():
    events = []

    def hide():
        events.append("hide")

    def capture():
        events.append("capture")
        return "snapshot"

    def show():
        events.append("show")

    result = capture_without_overlay(hide, show, capture, settle=lambda _: None)

    assert result == "snapshot"
    assert events == ["hide", "capture", "show"]


def test_overlay_is_restored_when_capture_fails():
    events = []

    def fail():
        events.append("capture")
        raise RuntimeError("ocr failed")

    try:
        capture_without_overlay(
            lambda: events.append("hide"),
            lambda: events.append("show"),
            fail,
            settle=lambda _: None,
        )
    except RuntimeError:
        pass

    assert events == ["hide", "capture", "show"]
