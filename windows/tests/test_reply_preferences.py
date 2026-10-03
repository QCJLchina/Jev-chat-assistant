import io
import json
import threading
import urllib.error

import pytest

from jev_windows import config, deepseek_client, i18n, jev_api
from jev_windows.models import Analysis, ChatSnapshot, Message
from jev_windows.reply_preferences import (
    DEFAULT_PREFERENCES, build_reply_prompt, resolve_preferences, validate_preferences,
)


@pytest.mark.parametrize("value", [None, [], "short", 1, {"length": [], "style": {}, "language": False}])
def test_invalid_preferences_use_defaults(value):
    assert validate_preferences(value) == DEFAULT_PREFERENCES


def test_validation_is_fieldwise_and_does_not_mutate_or_share_defaults():
    source = {"length": "detailed", "style": "bad", "language": "fr", "extra": 1}
    result = validate_preferences(source)
    assert result == {"length": "detailed", "style": "natural", "language": "fr"}
    result["length"] = "short"
    assert source["length"] == "detailed"
    assert validate_preferences() == DEFAULT_PREFERENCES


@pytest.mark.parametrize("locale", ["zh-CN", "en", "fr", "ru", "ja", "ko"])
def test_language_resolution(locale):
    assert resolve_preferences({"language": locale}, "en")["language"] == locale
    assert resolve_preferences({"language": "interface"}, locale)["language"] == locale


def test_system_interface_language(monkeypatch):
    monkeypatch.setattr(i18n, "system_language", lambda: "ja-JP")
    assert resolve_preferences({"language": "interface"}, "system")["language"] == "ja"
    assert resolve_preferences({"language": "interface"}, "invalid")["language"] == "zh-CN"


@pytest.mark.parametrize("style, instruction", [("natural", "conversational"), ("formal", "professional"),
                                              ("gentle", "considerate"), ("direct", "straightforward")])
def test_prompt_style_and_output_contract(style, instruction):
    prompt = build_reply_prompt({"style": style, "length": "detailed", "language": "ko"})
    assert instruction in prompt
    assert "detailed" in prompt
    assert "Korean (ko)" in prompt
    assert "exactly three" in prompt
    assert 'Output only JSON: {"replies"' in prompt
    assert "Do not invent" in prompt


def test_config_defaults_legacy_validation_and_persistence(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "config_dir", lambda: tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"relationship": "colleagues"}), encoding="utf-8")
    loaded = config.AppConfig.load()
    assert loaded.reply_preferences == DEFAULT_PREFERENCES
    loaded.reply_preferences = {"length": "detailed", "style": "gentle", "language": "interface"}
    loaded.save()
    assert config.AppConfig.load().reply_preferences == loaded.reply_preferences
    saved = json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))
    saved["reply_preferences"] = {"length": "detailed", "language": ["en"]}
    (tmp_path / "settings.json").write_text(json.dumps(saved), encoding="utf-8")
    normalized = config.AppConfig.load()
    assert normalized.relationship == "colleagues"
    assert normalized.reply_preferences == {"length": "detailed", "style": "natural", "language": "zh-CN"}
    normalized.reply_preferences = None
    normalized.save()
    assert config.AppConfig.load().reply_preferences == DEFAULT_PREFERENCES
    first, second = config.AppConfig(), config.AppConfig()
    first.reply_preferences["style"] = "formal"
    assert second.reply_preferences == DEFAULT_PREFERENCES


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic"])
@pytest.mark.parametrize("length, cap, expected", [("short", None, 400), ("detailed", None, 1200),
                                                ("detailed", 73, 73), ("short", 0, 0)])
def test_generation_preferences_and_explicit_token_caps(monkeypatch, protocol, length, cap, expected):
    captured = {}
    def fake_call(base_url, key, used_protocol, body, timeout):
        captured.update(body)
        content = '{"replies":["a","b","c"]}'
        return {"choices": [{"message": {"content": content}}], "output_text": content,
                "content": [{"type": "text", "text": content}]}
    monkeypatch.setattr(deepseek_client, "_call_model", fake_call)
    replies = deepseek_client.generate_suggestions(
        ChatSnapshot("", [Message("other", "hi")]), "friend", Analysis(), "key",
        protocol=protocol, max_tokens=cap,
        preferences={"length": length, "style": "formal", "language": "interface"}, interface_language="fr")
    assert replies == ["a", "b", "c"]
    assert captured["max_output_tokens" if protocol == "openai-responses" else "max_tokens"] == expected
    system = captured.get("instructions", captured.get("system"))
    if system is None:
        system = captured["messages"][0]["content"]
    assert "French (fr)" in system and "professional" in system


@pytest.mark.parametrize("call", [lambda event: jev_api._post("key", {}, cancel_event=event),
                                  lambda event: jev_api.judge(ChatSnapshot("", []), "", "key", cancel_event=event),
                                  lambda event: jev_api.recommend_replies(ChatSnapshot("", []), "", ["a", "b", "c"], "key", cancel_event=event)])
def test_cancel_before_request(monkeypatch, call):
    monkeypatch.setattr(jev_api.urllib.request, "urlopen", lambda *a, **kw: pytest.fail("unexpected HTTP request"))
    event = threading.Event()
    event.set()
    with pytest.raises(jev_api.JevCancelledError):
        call(event)


@pytest.mark.parametrize("error", [urllib.error.URLError("offline"), TimeoutError(),
                                  urllib.error.HTTPError(jev_api.SYSTEM_ONE_URL, 503, "busy", {}, io.BytesIO(b"{}"))])
def test_cancel_during_backoff_prevents_retry(monkeypatch, error):
    calls = []
    class CancelOnWait(threading.Event):
        def wait(self, timeout=None):
            assert timeout == 1
            self.set()
            return True
    def fake_open(*args, **kwargs):
        calls.append(1)
        raise error
    monkeypatch.setattr(jev_api.urllib.request, "urlopen", fake_open)
    monkeypatch.setattr(jev_api.time, "sleep", lambda _: pytest.fail("noninterruptible backoff"))
    with pytest.raises(jev_api.JevCancelledError):
        jev_api._post("key", {}, cancel_event=CancelOnWait())
    assert len(calls) == 1


def test_uncancelled_event_retries_and_returns(monkeypatch):
    calls = []
    class ImmediateWait(threading.Event):
        def wait(self, timeout=None):
            assert timeout == 1
            return False
    def fake_open(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise urllib.error.URLError("offline")
        return io.BytesIO(b'{"answers": {}}')
    monkeypatch.setattr(jev_api.urllib.request, "urlopen", fake_open)
    assert jev_api._post("key", {}, cancel_event=ImmediateWait()) == {"answers": {}}
    assert len(calls) == 2


def test_judge_and_ranking_forward_event(monkeypatch):
    events = []
    def fake_post(key, body, *, cancel_event):
        events.append(cancel_event)
        return {"answers": {}}
    monkeypatch.setattr(jev_api, "_post", fake_post)
    event = threading.Event()
    snapshot = ChatSnapshot("", [])
    jev_api.judge(snapshot, "friend", "key", cancel_event=event)
    assert len(jev_api.recommend_replies(snapshot, "friend", ["a", "b", "c"], "key", cancel_event=event)) == 3
    assert events == [event, event]


def test_cancelled_generation_does_not_dispatch_request(monkeypatch):
    event = threading.Event()
    event.set()
    def unexpected_request(*args, **kwargs):
        pytest.fail("cancelled generation must not dispatch")
    monkeypatch.setattr(deepseek_client, "_call_model", unexpected_request)
    with pytest.raises(jev_api.JevCancelledError):
        deepseek_client.generate_suggestions(ChatSnapshot("", [Message("other", "hi")]),
                                              "friends", Analysis(), "fixture-key", cancel_event=event)


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic"])
@pytest.mark.parametrize("limit", [None, 20])
def test_full_context_is_consistent_across_judge_generation_and_ranking(monkeypatch, protocol, limit):
    from jev_windows.context import compose_context
    from jev_windows.input_text import parse_text

    source = parse_text("\n".join(f"other: current-{index:02d}" for index in range(23)) + "\nme: last-selected")
    background = "other: background fact; this is metadata"
    effective, stats = compose_context(source, {
        "prior_text": "me: prior-first\nother: prior-second", "background": background,
        "message_limit": limit})
    jev_states = []
    generation = {}

    def fake_post(key, body, **kwargs):
        jev_states.append(body["state"])
        return {"answers": {}}

    def fake_call(base_url, key, used_protocol, body, timeout):
        assert used_protocol == protocol
        generation.update(body)
        content = '{"replies":["a","b","c"]}'
        return {"choices": [{"message": {"content": content}}], "output_text": content,
                "content": [{"type": "text", "text": content}]}

    monkeypatch.setattr(jev_api, "_post", fake_post)
    monkeypatch.setattr(deepseek_client, "_call_model", fake_call)
    relationship = "friends"
    analysis = jev_api.judge(effective, relationship, "key")
    replies = deepseek_client.generate_suggestions(effective, relationship, analysis, "key", protocol=protocol)
    jev_api.recommend_replies(effective, relationship, replies, "key")
    assert jev_states[0] == jev_states[1]
    chat = jev_states[0]["chat"]
    assert chat["messages"] == [{"from": "me" if m.side == "me" else "her", "text": m.text}
                                for m in effective.messages]
    assert len(chat["messages"]) == stats["used_messages"] > 10
    assert chat["latest_from"] == "me"
    assert chat["relationship"] == f"friends\n\nBackground (user-provided context, not chat messages):\n{background}"
    user = (generation["input"][0]["content"] if protocol == "openai-responses" else
            generation["messages"][0 if protocol == "anthropic" else 1]["content"])
    expected_transcript = "\n".join(f"{'我' if m.side == 'me' else '对方'}：{m.text}" for m in effective.messages)
    assert user.endswith(f"对话：\n{expected_transcript}\n\nBackground (user-provided context, not chat messages):\n{background}")
    assert user.count(background) == 1
    assert all(m.text in user for m in effective.messages)
    if limit is not None:
        assert "prior-first" not in user and "current-00" not in user
    assert source.background == "" and len(source.messages) == 24
    assert relationship == "friends"
