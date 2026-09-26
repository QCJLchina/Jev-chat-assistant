from dataclasses import asdict
import json
from pathlib import Path
import re

import pytest

from jev_windows import app, config, i18n
from jev_windows.models import Rect
from tools.jev.questions import JUDGE_QUESTIONS


LOCALES = ("zh-CN", "en", "fr", "ru", "ja")


def test_catalogs_have_identical_keys_parameters_and_all_result_choices():
    base = i18n.catalog("zh-CN")
    for locale in LOCALES:
        catalog = i18n.catalog(locale)
        assert catalog.keys() == base.keys()
        for key, text in catalog.items():
            assert text.strip(), (locale, key)
            assert set(re.findall(r"\{(\w+)\}", text)) == set(re.findall(r"\{(\w+)\}", base[key])), (locale, key)
        for prefix, question in (("intent", "true_intent"), ("need", "she_needs"), ("action", "best_action")):
            for choice in JUDGE_QUESTIONS[question]["criteria"]:
                assert f"{prefix}.{choice}" in catalog


def test_missing_translation_uses_chinese_and_parameters_are_not_reinterpreted(monkeypatch):
    catalogs = {locale: dict(i18n.catalog(locale)) for locale in LOCALES}
    del catalogs["fr"]["common.save"]
    monkeypatch.setattr(i18n, "catalog", lambda locale: catalogs[locale])
    assert i18n.translate("common.save", "fr") == "保存"
    assert "{status}" in i18n.translate("error.modelHttp", "en", status=500, detail="{status}")


def test_message_is_not_a_string_so_it_cannot_be_render_stale():
    """A str subclass would freeze text in the construction-time locale."""
    message = i18n.msg("common.save")
    assert not isinstance(message, str)
    assert message.message["key"] == "common.save"
    # Equality is by identity (key + params), not by rendered text.
    assert message == i18n.msg("common.save")
    assert message != i18n.msg("common.cancel")
    assert message != i18n.msg("common.save", count=1)


def test_message_renders_in_the_requested_locale_at_presentation_time(monkeypatch):
    calls = []
    original = i18n.translate
    monkeypatch.setattr(i18n, "translate", lambda key, locale="zh-CN", **params: calls.append(locale) or original(key, locale, **params))
    message = i18n.msg("common.save")
    # Constructing must not translate; only rendering does.
    assert calls == []
    assert i18n.render(i18n.describe(message), "fr") == original("common.save", "fr")
    assert calls == ["fr"]


def test_nested_message_parameters_survive_render(monkeypatch):
    inner = i18n.msg("common.cancel")
    outer = i18n.msg("error.unexpected", detail=inner)
    described = i18n.describe(outer)
    assert described["params"]["detail"]["key"] == "common.cancel"
    assert i18n.render(described, "ja") == i18n.translate("error.unexpected", "ja", detail=i18n.msg("common.cancel"))


def test_exception_wrapping_a_message_describes_to_that_message():
    failure = RuntimeError(i18n.msg("error.jev401"))
    assert i18n.describe(failure)["key"] == "error.jev401"
    assert i18n.describe(ValueError("plain")) == {"key": "error.unexpected", "params": {"detail": "plain"}}


@pytest.mark.parametrize("system,expected", [
    ("zh-CN", "zh-CN"), ("zh-SG", "zh-CN"), ("zh-Hans", "zh-CN"),
    ("zh-Hans-CN", "zh-CN"), ("zh-TW", "en"), ("de-DE", "en"), ("", "en"),
    ("en-GB", "en"), ("fr-CA", "fr"), ("ru-RU", "ru"), ("ja-JP", "ja"),
])
def test_system_language_mapping(monkeypatch, system, expected):
    monkeypatch.setattr(i18n, "system_language", lambda: system)
    assert i18n.resolve_language("system") == expected
    assert i18n.resolve_language("ja") == "ja"


def test_system_detection_failure_defaults_to_english(monkeypatch):
    class MissingKernel:
        @property
        def kernel32(self):
            raise OSError("unavailable")
    monkeypatch.setattr(i18n.ctypes, "windll", MissingKernel())
    assert i18n.system_language() == "en"


@pytest.mark.parametrize("stored", [None, "unsupported", 5, [], {}])
def test_legacy_or_invalid_language_preserves_configuration(tmp_path, monkeypatch, stored):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    raw = asdict(config.AppConfig(relationship="自定义关系", allowed_titles=["工作"], chat_rect=Rect(-600, 0, 0, 400)))
    if stored is None:
        raw.pop("language")
    else:
        raw["language"] = stored
    (tmp_path / "settings.json").write_text(json.dumps(raw), encoding="utf-8")
    actual = config.AppConfig.load()
    raw["language"] = "zh-CN"
    assert asdict(actual) == raw


def test_new_install_defaults_to_system_and_manual_choice_survives_restart(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    assert config.AppConfig.load().language == "system"
    settings = config.AppConfig.load()
    settings.language = "ru"
    settings.save()
    assert config.AppConfig.load().language == "ru"


@pytest.fixture
def api(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    settings = config.AppConfig(language="zh-CN", relationship="朋友（不翻译）", chat_rect=Rect(0, 0, 800, 600))
    settings.save()
    return app.DesktopApi()


@pytest.mark.parametrize("locale", LOCALES)
def test_language_changes_only_language_and_retranslates_active_progress(api, locale, monkeypatch):
    before = asdict(api.settings)
    def no_credentials(*args):
        raise AssertionError("language changes and progress must not touch credentials")
    for name in ("load_api_key", "load_model_api_key", "save_api_key", "save_model_api_key", "delete_api_key", "delete_model_api_key"):
        monkeypatch.setattr(app, name, no_credentials)
    api._set_progress(phase="judging", status=i18n.msg("status.judging", count=3), preview=[{"side": "other", "text": "原文"}])
    previous = api.get_progress()
    assert api.set_language(locale) == {"language": locale, "resolved_language": locale}
    before["language"] = locale
    assert asdict(config.AppConfig.load()) == before
    current = api.get_progress(previous["revision"])
    assert current["revision"] > previous["revision"]
    assert current["phase"] == "judging"
    assert current["preview"][0]["text"] == "原文"
    assert current["status"] == i18n.translate("status.judging", locale, count=3)
    assert current["status_message"] == previous["status_message"]
    assert api.get_progress(current["revision"]) == {"revision": current["revision"]}


def test_language_save_failure_rolls_back_memory_disk_and_revision(api, monkeypatch):
    before = asdict(api.settings)
    progress = api.get_progress()
    def fail(_self):
        raise OSError("disk unavailable")
    monkeypatch.setattr(config.AppConfig, "save", fail)
    result = api.set_language("fr")
    assert result["ok"] is False
    assert result["error_message"]["key"] == "language.failed"
    assert asdict(api.settings) == before
    assert asdict(config.AppConfig.load()) == before
    assert api.get_progress() == progress


def test_reselect_system_refreshes_language_and_invalid_choice_does_not_save(api, monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "fr-CA")
    assert api.set_language("system")["resolved_language"] == "fr"
    monkeypatch.setattr(i18n, "system_language", lambda: "ja-JP")
    assert api.set_language("system")["resolved_language"] == "ja"
    assert api.set_language("unknown")["ok"] is False
    assert config.AppConfig.load().language == "system"


def test_structured_errors_and_nested_failures_remain_translatable(api):
    failure = RuntimeError(i18n.msg("error.jev401"))
    api._set_progress(status=i18n.msg("status.rankFailed", detail=failure))
    api.set_language("fr")
    assert i18n.translate("error.jev401", "fr") in api.get_progress()["status"]
    api._set_progress(phase="error", status=failure, error=failure)
    api.set_language("ja")
    current = api.get_progress()
    assert current["error"] == i18n.translate("error.jev401", "ja")
    result = api.test_model({"protocol": "invalid"})
    assert result["error_message"]["key"] == "error.protocol"
    assert result["error"] == i18n.translate("error.protocol", "ja")
    json.dumps(current)  # Wire data stays JSON serializable.


def test_all_static_message_keys_exist():
    root = Path(__file__).resolve().parents[1]
    for path in [*root.joinpath("jev_windows").glob("*.py"), *root.joinpath("frontend/src").glob("*.ts"), root / "frontend/src/App.vue"]:
        source = path.read_text(encoding="utf-8")
        for key in re.findall(r"\b(?:msg|m|t|translate)\(['\"]([\w.]+)['\"]", source):
            assert key in i18n.catalog("zh-CN"), (path, key)
