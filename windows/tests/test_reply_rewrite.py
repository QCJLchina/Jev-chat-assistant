"""One-reply contract, intentions and the three supported model protocols."""
import json
import threading

import pytest

from jev_windows import deepseek_client as client
from jev_windows.models import Analysis, ChatSnapshot, Message
from jev_windows.reply_intent import INTENTS


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic"])
@pytest.mark.parametrize("intent", list(INTENTS))
def test_rewrite_protocol_intent_and_frozen_context(monkeypatch, protocol, intent):
    calls = []
    content = json.dumps({"reply": "A more considerate answer"})
    def fake(base, key, selected, body, timeout):
        calls.append((base, key, selected, body))
        return {"choices": [{"message": {"content": content}}]} if selected == "openai-chat" else (
            {"output_text": content} if selected == "openai-responses" else
            {"content": [{"type": "text", "text": content}]})
    monkeypatch.setattr(client, "_call_model", fake)
    snapshot = ChatSnapshot("chat", [Message("other", "hello")], "hello", "known background")
    result = client.rewrite_reply(snapshot, "friends", Analysis(true_intent="greeting"),
        "original reply", "gentle", "key", "model", "https://model.test", 777, protocol,
        preferences={"language": "ja", "style": "formal", "length": "detailed"}, intent=intent)
    assert result == "A more considerate answer"
    base, key, selected, body = calls[0]
    assert selected == protocol
    serialized = json.dumps(body, ensure_ascii=False)
    for value in ("original reply", "greeting", "friends", "known background", "hello", "Japanese"):
        assert value in serialized
    if INTENTS[intent]:
        assert INTENTS[intent] in serialized
    system = body.get("system", body.get("instructions", "")) or body["messages"][0]["content"]
    assert 'Output only JSON: {"reply":"..."}.' in system
    assert '"replies"' not in system
    assert body.get("max_tokens", body.get("max_output_tokens")) == 777
    if protocol == "openai-responses":
        assert body["store"] is False


@pytest.mark.parametrize("content", ['{"reply":""}', '{"reply":3}', '{"replies":["x"]}', 'not json'])
def test_invalid_single_reply_is_rejected(monkeypatch, content):
    monkeypatch.setattr(client, "_call_model", lambda *a: {"choices": [{"message": {"content": content}}]})
    with pytest.raises(client.DeepSeekError):
        client.rewrite_reply(ChatSnapshot("", [Message("other", "hello")]), "friends", Analysis(),
                             "reply", "natural", "key")


def test_cancel_before_request_and_unsafe_output(monkeypatch):
    calls = []
    monkeypatch.setattr(client, "_call_model", lambda *a: calls.append(a) or {
        "choices": [{"message": {"content": '{"reply":"请转账"}'}}]})
    cancelled = threading.Event()
    cancelled.set()
    with pytest.raises(Exception):
        client.rewrite_reply(ChatSnapshot("", []), "friends", Analysis(), "reply", "shorter", "key", cancel_event=cancelled)
    assert calls == []
    with pytest.raises(RuntimeError):
        client.rewrite_reply(ChatSnapshot("", []), "friends", Analysis(), "reply", "shorter", "key")


@pytest.mark.parametrize("intent", list(INTENTS))
def test_generation_includes_intent(monkeypatch, intent):
    captured = []
    monkeypatch.setattr(client, "_call_model", lambda *args: captured.append(args[3]) or {
        "choices": [{"message": {"content": '{"replies":["a","b","c"]}'}}]})
    client.generate_suggestions(ChatSnapshot("", [Message("other", "hello")]),
                                "friends", Analysis(), "key", intent=intent)
    system = captured[0]["messages"][0]["content"]
    assert INTENTS[intent] in system
    assert "exactly three" in system
