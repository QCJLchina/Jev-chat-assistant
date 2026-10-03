"""Guard screenshot coordinates and discard unstable frames before OCR."""
from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from jev_windows import analysis
from jev_windows.models import ChatSnapshot, Message, Rect
from jev_windows.state import ProgressState
from jev_windows.window_binding import BindingError


@pytest.mark.parametrize("failure", [None, "pixels", "changed"])
def test_bound_capture_uses_physical_context_and_restores_before_ocr(monkeypatch, failure):
    events = []
    active = False
    rect = Rect(-600, 20, -100, 320)
    frame = object()

    @contextmanager
    def physical():
        nonlocal active
        active = True
        events.append("physical")
        try:
            yield
        finally:
            active = False
            events.append("leave")

    class Binder:
        def resolve(self, descriptor):
            assert active
            events.append("resolve")
            return SimpleNamespace(rect=rect, title="Fixture")

        def validate_after(self, descriptor, resolved):
            assert active and resolved.rect == rect
            events.append("validate")
            if failure == "changed":
                raise BindingError("binding.changed")

    class Window:
        def hide(self):
            events.append("hide")

        def show(self):
            assert not active
            events.append("show")

        def restore(self):
            events.append("restore")

    def pixels(area):
        assert active and area == rect
        events.append("pixels")
        if failure == "pixels":
            raise analysis.NativeWindowError("fixture unavailable")
        return frame

    def ocr(area, capture_frame):
        assert not active and events[-1] == "restore"
        assert area == rect and capture_frame(area) == (frame, "Fixture")
        events.append("ocr")
        return ChatSnapshot("Fixture", [Message("other", "hello")], "hello")

    monkeypatch.setattr(analysis, "physical_window_coordinates", physical)
    monkeypatch.setattr(analysis, "screenshot", pixels)
    monkeypatch.setattr(analysis, "capture_desktop_chat", ocr)
    service = analysis.AnalysisService(
        SimpleNamespace(selection_mode="window", window_binding={}),
        ProgressState("en"), Window(), Binder())
    if failure:
        with pytest.raises(BindingError) as error:
            service.capture(None)
        assert error.value.key == ("binding.unavailable" if failure == "pixels" else "binding.changed")
        assert "ocr" not in events
    else:
        assert service.capture(None).messages[0].text == "hello"
    assert events[:3] == ["hide", "physical", "resolve"]
    assert events[-3:] == (["show", "restore", "ocr"] if failure is None else ["leave", "show", "restore"])
