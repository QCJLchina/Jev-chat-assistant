"""Offline provider, credential isolation, and local-model regressions."""
import json
import re
from dataclasses import asdict
from urllib.parse import urlsplit

import pytest

from jev_windows import analysis, app, config, deepseek_client, providers
from jev_windows.state import ProgressState


def test_default_profiles_and_public_catalog():
    settings = config.AppConfig()
    assert settings.active_model_id == "deepseek"
    assert settings.model_profiles == providers.default_profiles()
    ids = [p.id for p in providers.PROVIDER_PRESETS]
    assert len(ids) == len(set(ids))
    for preset in providers.PROVIDER_PRESETS:
        assert re.fullmatch(r"[A-Za-z0-9_-]{1,80}", preset.id)
        assert preset.default_model
        assert preset.protocol in deepseek_client.SUPPORTED_PROTOCOLS
        assert urlsplit(preset.base_url).scheme == "https" or preset.local
        endpoint = {"openai-chat": "chat/completions", "openai-responses": "responses", "anthropic": "messages"}[preset.protocol]
        path = urlsplit(deepseek_client._endpoint(preset.base_url, endpoint, preset.protocol)).path
        prefixes = {"deepseek": "", "dashscope": "/compatible-mode/v1", "moonshot": "/v1", "zhipu": "/api/paas/v4", "ark": "/api/v3", "siliconflow": "/v1", "openai": "/v1", "anthropic": "/v1", "gemini": "/v1beta/openai", "openrouter": "/api/v1", "ollama": "/v1"}
        assert path == prefixes[preset.id] + "/" + endpoint
        assert "//" not in path
    payload = providers.preset_data()
    json.dumps(payload)
    assert all("api_key" not in p for p in payload)
    assert all(p["default_model"] in p["models"] for p in payload)


@pytest.mark.parametrize("url", ["http://localhost:11434/v1", "https://127.0.0.1/v1", "http://[::1]:11434/v1"])
def test_local_urls(url):
    assert deepseek_client.is_local_base_url(url)


@pytest.mark.parametrize("url", ["https://localhost.evil.test/v1", "http://127.0.0.2/v1", "http://0.0.0.0/v1", "https://localhost@evil.test/v1", "localhost:11434/v1", "file://localhost/a", "http://[broken"])
def test_nonlocal_urls(url):
    assert not deepseek_client.is_local_base_url(url)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setattr(config.AppConfig, "load", classmethod(lambda cls: cls()))
    monkeypatch.setattr(app, "load_api_key", lambda: "")
    monkeypatch.setattr(app, "load_model_api_key", lambda _id: "")
    return app.DesktopApi()


def test_safe_state_contains_presets_without_keys(api):
    state = api.get_state()
    assert state["provider_presets"] == providers.preset_data()
    assert all("api_key" not in p for p in state["profiles"])
    assert next(p for p in state["profiles"] if p["id"] == "ollama")["key_required"] is False
    assert next(p for p in state["profiles"] if p["id"] == "deepseek")["key_required"] is True


@pytest.mark.parametrize("url,allowed", [("http://localhost:11434/v1", True), ("https://api.example.test/v1", False), ("http://localhost.evil.test/v1", False)])
def test_connection_empty_key_only_local(api, monkeypatch, url, allowed):
    calls = []
    monkeypatch.setattr(app, "test_connection", lambda *a, **k: calls.append(a) or "OK")
    result = api.test_model({"base_url": url, "model": "model-x"})
    assert bool(calls) is allowed
    if not allowed:
        assert result["error_message"]["key"] == "error.testFields"


@pytest.mark.parametrize("changed", [None, "url", "protocol", "id"])
def test_fetch_models_reuses_key_only_same_saved_destination(api, monkeypatch, changed):
    profile = config.ModelProfile("p1", "P", "https://saved.test/v1", "m")
    api.settings.model_profiles = [profile]
    loaded = []
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-leak")
    monkeypatch.setattr(app, "load_model_api_key", lambda pid: loaded.append(pid) or "saved-secret")
    captured = []
    monkeypatch.setattr(app, "list_models", lambda url, key, **kw: captured.append(key) or ["m"])
    data = {"profile_id": "p1", "base_url": profile.base_url + "/", "protocol": profile.protocol}
    if changed == "url":
        data["base_url"] = "https://other.test/v1"
    elif changed == "protocol":
        data["protocol"] = "anthropic"
    elif changed == "id":
        data["profile_id"] = "unknown"
    api.fetch_models(data)
    assert captured == (["saved-secret"] if changed is None else [""])
    assert loaded == (["p1"] if changed is None else [])


def test_fetch_explicit_key_takes_precedence(api, monkeypatch):
    monkeypatch.setattr(app, "load_model_api_key", lambda _id: pytest.fail("must not read stored key"))
    monkeypatch.setattr(app, "list_models", lambda url, key, **kw: [key])
    assert api.fetch_models({"base_url": "https://other.test/v1", "api_key": "explicit"}) == {"models": ["explicit"]}


@pytest.mark.parametrize("pid", ["deepseek", "deepseek-default"])
def test_deepseek_environment_compatibility(monkeypatch, pid):
    monkeypatch.setenv("OPENAI_API_KEY", "environment-secret")
    assert config.load_model_api_key(pid) == "environment-secret"


@pytest.mark.parametrize("pid", ["deepseek", "deepseek-default"])
def test_deepseek_legacy_credential_migration(monkeypatch, pid):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    writes = []
    def read(target, _kind, _flags):
        if target != config.DEEPSEEK_CREDENTIAL_TARGET:
            raise RuntimeError("missing")
        return {"CredentialBlob": "legacy-secret"}
    monkeypatch.setattr(config.win32cred, "CredRead", read)
    monkeypatch.setattr(config, "save_model_api_key", lambda *a: writes.append(a))
    assert config.load_model_api_key(pid) == "legacy-secret"
    assert writes == [(pid, "legacy-secret")]


@pytest.mark.parametrize("url,active", [("http://localhost:11434/v1", True), ("https://remote.test/v1", False)])
def test_analysis_local_profile_needs_no_key(monkeypatch, url, active):
    profile = config.ModelProfile("p1", "P", url, "m")
    settings = config.AppConfig(model_profiles=[profile], active_model_id="p1")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "")
    service = analysis.AnalysisService(settings, ProgressState("zh-CN"))
    assert (service._active_profile() is profile) is active


@pytest.mark.parametrize("raw,expected_ids,active", [
    ({"deepseek_model": "custom-legacy-model"}, ["deepseek-default"], "deepseek-default"),
    ({"model_profiles": [], "active_model_id": ""}, [], ""),
    ({"model_profiles": [{"id": "custom", "name": "Custom", "base_url": "https://x.test", "model": "m"}], "active_model_id": "custom"}, ["custom"], "custom"),
])
def test_config_existing_and_legacy_lists_not_reseeded(monkeypatch, raw, expected_ids, active):
    # Avoid temp-dir dependencies: mock only the settings-file read.
    monkeypatch.setattr(config.Path, "exists", lambda self: True)
    monkeypatch.setattr(config.Path, "read_text", lambda self, **kw: json.dumps(raw))
    settings = config.AppConfig.load()
    assert [p.id for p in settings.model_profiles] == expected_ids
    assert settings.active_model_id == active
    if active == "deepseek-default":
        assert settings.model_profiles[0].model == "custom-legacy-model"


def test_new_install_loads_catalog(monkeypatch):
    monkeypatch.setattr(config.Path, "exists", lambda self: False)
    settings = config.AppConfig.load()
    assert settings.model_profiles == providers.default_profiles()
    assert settings.active_model_id == "deepseek"


def test_existing_profile_schema_unchanged():
    assert set(asdict(config.ModelProfile("p", "P", "https://x.test", "m"))) == {"id", "name", "base_url", "model", "max_tokens", "protocol"}
