import json

from jev_windows import config


def test_legacy_deepseek_settings_migrate_to_openai_chat_profile(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "deepseek_model": "deepseek-v4-pro",
        "relationship": "同事",
        "allowed_titles": ["工作群"],
        "chat_rect": {"left": 1, "top": 2, "right": 500, "bottom": 400},
    }), encoding="utf-8")

    settings = config.AppConfig.load()

    assert settings.active_model_id == "deepseek-default"
    assert len(settings.model_profiles) == 1
    assert settings.model_profiles[0].protocol == "openai-chat"
    assert settings.model_profiles[0].model == "deepseek-v4-pro"
    assert settings.relationship == "同事"
    assert settings.allowed_titles == ["工作群"]
    assert settings.chat_rect.left == 1


def test_legacy_wechat_client_coordinates_are_cleared_on_load(tmp_path, monkeypatch):
    """v1.0 stored WeChat client-area coordinates; they cannot be reinterpreted."""
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "chat_rect": {"left": 10, "top": 20, "right": 900, "bottom": 700},
        "chat_rect_mode": "wechat-client",
        "relationship": "同事",
        "allowed_titles": ["工作群"],
        "model_profiles": [{"id": "m1", "name": "M", "base_url": "https://x.test", "model": "m"}],
        "active_model_id": "m1",
    }), encoding="utf-8")

    settings = config.AppConfig.load()

    assert settings.chat_rect is None
    assert settings.relationship == "同事"
    assert settings.allowed_titles == ["工作群"]
    assert [item.id for item in settings.model_profiles] == ["m1"]
    assert settings.active_model_id == "m1"
    # The obsolete key must not survive into a re-saved file.
    settings.save()
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    assert "chat_rect_mode" not in saved
    assert saved["chat_rect"] is None


def test_screen_mode_coordinates_are_kept_on_load(tmp_path, monkeypatch):
    """Only the legacy client-area mode resets the rectangle."""
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "chat_rect": {"left": 10, "top": 20, "right": 900, "bottom": 700},
        "chat_rect_mode": "screen",
    }), encoding="utf-8")

    settings = config.AppConfig.load()

    assert settings.chat_rect.left == 10
    assert settings.chat_rect.bottom == 700


def test_saved_model_keys_use_profile_scoped_credential_targets(monkeypatch):
    saved = {}
    monkeypatch.setattr(config.win32cred, "CredWrite", lambda credential, flags: saved.update(credential))
    monkeypatch.setattr(config.win32cred, "CRED_TYPE_GENERIC", 1, raising=False)
    monkeypatch.setattr(config.win32cred, "CRED_PERSIST_LOCAL_MACHINE", 2, raising=False)

    config.save_model_api_key("profile-123", "secret-value")

    assert saved["TargetName"] == "JevChatAssistant/Model/profile-123"
    assert saved["CredentialBlob"] == "secret-value"


def test_explicitly_empty_model_list_stays_empty_after_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({
        "model_profiles": [], "active_model_id": "", "relationship": "朋友"
    }), encoding="utf-8")

    settings = config.AppConfig.load()

    assert settings.model_profiles == []
    assert settings.active_model_id == ""
