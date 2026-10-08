"""Presentation choices persist without changing analysis state or credentials."""
from dataclasses import asdict
import json

import pytest

from jev_windows import app, config


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    config.AppConfig(model_profiles=[]).save()
    return app.DesktopApi()


def test_default_legacy_and_invalid_visibility(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    for value in (None, "bad", {"model": 0, "messages": "false", "analysis": False}):
        (tmp_path / "settings.json").write_text(json.dumps({"module_visibility": value}), encoding="utf-8")
        assert config.AppConfig.load().module_visibility == {name: True for name in config.OPTIONAL_MODULES}


def test_hide_all_persists_only_presentation_without_progress_or_credentials(api, monkeypatch):
    def forbidden(*args):
        pytest.fail("visibility changes must not access credentials")
    for name in ("load_api_key", "load_model_api_key", "save_api_key", "save_model_api_key", "delete_api_key", "delete_model_api_key"):
        monkeypatch.setattr(app, name, forbidden)
    api.progress.update(phase="generating", analysis={"true_intent": "casual_chat"}, task_id="current")
    before = asdict(api.settings)
    progress = api.progress.poll()
    hidden = {name: False for name in config.OPTIONAL_MODULES}
    result = api.set_module_visibility(hidden)
    assert result == {"ok": True, "module_visibility": hidden}
    after = asdict(config.AppConfig.load())
    before["module_visibility"] = hidden
    assert after == before
    assert api.progress.poll() == progress
    assert api.set_module_visibility({"messages": True})["module_visibility"] == {**hidden, "messages": True}


@pytest.mark.parametrize("changes", [{"analysis": False}, {"review": False}, {"suggestions": False},
    {"input": False}, {"model": "false"}, {"model": 0}, [], None])
def test_core_or_invalid_visibility_is_rejected_without_mutation(api, changes):
    before = asdict(api.settings)
    result = api.set_module_visibility(changes)
    assert result["ok"] is False
    assert result["error_message"]["key"] == "layout.invalid"
    assert asdict(api.settings) == asdict(config.AppConfig.load()) == before


def test_visibility_save_failure_rolls_back(api, monkeypatch):
    before = asdict(api.settings)
    def fail(*args):
        raise OSError("synthetic save failure")
    monkeypatch.setattr(config.AppConfig, "save", fail)
    assert api.set_module_visibility({"messages": False})["ok"] is False
    assert asdict(api.settings) == asdict(config.AppConfig.load()) == before


def test_bridge_state_returns_saved_visibility(api, monkeypatch):
    monkeypatch.setattr(app, "load_api_key", lambda: "")
    api.set_module_visibility({"judgment": False})
    assert api.get_state()["module_visibility"]["judgment"] is False
