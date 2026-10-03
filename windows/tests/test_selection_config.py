"""Selection migration and persisted descriptor privacy contract."""
import copy
import json

import pytest

from jev_windows import config
from jev_windows.models import Rect
from jev_windows.window_binding import validate_descriptor


@pytest.fixture
def settings_path(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    return tmp_path / "settings.json"


@pytest.fixture
def descriptor():
    return {"version": 1, "binding_id": "d47a1e72-3703-4bd9-9caa-6840966a4738",
            "app_path": r"C:\Apps\Chat\chat.exe", "window_class": "ChatWindow",
            "relative_rect": {"left": 10, "top": 20, "right": 900, "bottom": 700},
            "reference_width": 1000, "reference_height": 800, "reference_dpi": 96}


def test_fresh_settings_default_to_window_mode(settings_path):
    assert not settings_path.exists()
    assert config.AppConfig().selection_mode == "window"
    assert config.AppConfig.load().selection_mode == "window"
    assert config.AppConfig.load().window_binding is None


@pytest.mark.parametrize("old", [{}, {"chat_rect": {"left": 10, "top": 20, "right": 900, "bottom": 700}}])
def test_missing_selection_mode_migrates_old_settings_to_screen(settings_path, old):
    settings_path.write_text(json.dumps({"relationship": "existing", **old}), encoding="utf-8")
    loaded = config.AppConfig.load()
    assert loaded.selection_mode == "screen"
    assert loaded.relationship == "existing"
    assert loaded.chat_rect == (Rect(**old["chat_rect"]) if "chat_rect" in old else None)
    loaded.save()
    assert json.loads(settings_path.read_text(encoding="utf-8"))["selection_mode"] == "screen"
    assert config.AppConfig.load().selection_mode == "screen"


@pytest.mark.parametrize("mode", ["screen", "window"])
def test_selection_mode_and_valid_descriptor_round_trip(settings_path, descriptor, mode):
    settings = config.AppConfig(selection_mode=mode, window_binding=descriptor)
    settings.save()
    loaded = config.AppConfig.load()
    assert loaded.selection_mode == mode
    assert loaded.window_binding == descriptor
    loaded.window_binding["relative_rect"]["left"] = 99
    assert descriptor["relative_rect"]["left"] == 10


def test_validator_returns_detached_descriptor_without_runtime_identity(descriptor):
    supplied = {**copy.deepcopy(descriptor), "hwnd": 9876, "pid": 4321, "title": "PRIVATE TITLE",
                "identity": [9876, 4321], "candidate_id": "transient", "process_start_time": 123}
    supplied["relative_rect"]["hwnd"] = 555
    normalized = validate_descriptor(supplied)
    assert normalized == descriptor
    normalized["relative_rect"]["left"] = 99
    assert supplied["relative_rect"]["left"] == 10
    assert supplied["title"] == "PRIVATE TITLE"


@pytest.mark.parametrize("entry", ["construct", "load", "save"])
def test_config_filters_runtime_hwnd_pid_and_title_on_every_entry(settings_path, descriptor, entry):
    supplied = {**copy.deepcopy(descriptor), "hwnd": 9876, "pid": 4321, "title": "PRIVATE TITLE",
                "HWND": 9876, "PID": 4321, "candidate_id": "transient"}
    if entry == "construct":
        settings = config.AppConfig(selection_mode="window", window_binding=supplied)
    elif entry == "load":
        settings_path.write_text(json.dumps({"selection_mode": "window", "window_binding": supplied}), encoding="utf-8")
        settings = config.AppConfig.load()
    else:
        settings = config.AppConfig(selection_mode="window", window_binding=descriptor)
        settings.window_binding = supplied
        settings.save()
    assert settings.window_binding == descriptor
    settings.save()
    saved = json.loads(settings_path.read_text(encoding="utf-8"))
    assert saved["window_binding"] == descriptor
    assert "PRIVATE TITLE" not in settings_path.read_text(encoding="utf-8")
    assert config.AppConfig.load().window_binding == descriptor
    assert supplied["title"] == "PRIVATE TITLE"


@pytest.mark.parametrize("invalid", [None, "bad", {}, {"version": 1}])
def test_invalid_persisted_binding_is_cleared_without_losing_settings(settings_path, invalid):
    settings_path.write_text(json.dumps({"selection_mode": "window", "window_binding": invalid,
                                        "relationship": "keep this"}), encoding="utf-8")
    loaded = config.AppConfig.load()
    assert loaded.window_binding is None
    assert loaded.selection_mode == "window" and loaded.relationship == "keep this"
