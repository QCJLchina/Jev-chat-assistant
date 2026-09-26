from jev_windows.calibration import (
    MIN_SELECTION_HEIGHT,
    MIN_SELECTION_WIDTH,
    _relative_to_screen,
    is_usable_selection,
    overlay_geometry,
)
from jev_windows.models import Rect


def test_overlay_geometry_selects_negative_secondary_screen_coordinates():
    assert overlay_geometry(Rect(-1920, 0, 0, 1080)) == "1920x1080+-1920+0"
    assert overlay_geometry(Rect(100, -250, 900, 350)) == "800x600+100+-250"


def test_relative_selection_is_translated_to_screen_space():
    client = Rect(-1920, -100, 0, 980)
    assert _relative_to_screen(client, (10, 20), (210, 140)) == Rect(-1910, -80, -1710, 40)


def test_reverse_drag_normalizes_to_a_positive_rectangle():
    client = Rect(100, 100, 1100, 900)
    rect = _relative_to_screen(client, (400, 300), (200, 150))
    assert rect == Rect(300, 250, 500, 400)
    assert rect.width > 0 and rect.height > 0


def test_selection_thresholds_reject_accidental_clicks():
    assert is_usable_selection(Rect(0, 0, MIN_SELECTION_WIDTH, MIN_SELECTION_HEIGHT))
    assert not is_usable_selection(Rect(0, 0, MIN_SELECTION_WIDTH - 1, MIN_SELECTION_HEIGHT))
    assert not is_usable_selection(Rect(0, 0, MIN_SELECTION_WIDTH, MIN_SELECTION_HEIGHT - 1))
    assert not is_usable_selection(Rect(0, 0, 0, 0))
