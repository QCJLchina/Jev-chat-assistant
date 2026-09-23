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
