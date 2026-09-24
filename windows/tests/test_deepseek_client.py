import io
import json
import urllib.error
import urllib.parse

import pytest

from jev_windows import deepseek_client
from jev_windows.models import Analysis, ChatSnapshot, Message


def test_generate_three_suggestions_uses_jev_judgment(monkeypatch):
    captured = {}

    def fake_call(base_url, key, protocol, body, timeout):
        captured.update(body)
        captured["protocol"] = protocol
        return {"choices": [{"message": {"content": json.dumps(
            {"replies": ["好呀，晚上七点见。", "可以，还是老地方吗？", "没问题，我七点过去。"]}, ensure_ascii=False
        )}}]}

    monkeypatch.setattr(deepseek_client, "_call_model", fake_call)
    snapshot = ChatSnapshot("朋友", [Message("other", "晚上七点一起吃饭吗？")])
    analysis = Analysis(
        true_intent="request_action",
        danger_level=1.0,
        need="action",
        best_action="make_plan",
        should_reply_now=1.0,
        tension_resolved=1.0,
    )

    replies = deepseek_client.generate_suggestions(
        snapshot, "对方是朋友", analysis, "deepseek-secret", "deepseek-flash"
    )

    assert len(replies) == 3
    assert captured["model"] == "deepseek-flash"
    assert captured["protocol"] == "openai-chat"
    assert "request_action" in captured["messages"][1]["content"]


def test_invalid_deepseek_key_has_readable_error(monkeypatch):
    error = urllib.error.HTTPError(
        deepseek_client.CHAT_URL, 401, "Unauthorized", {}, io.BytesIO(b"{}")
    )
    monkeypatch.setattr(
        deepseek_client.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(deepseek_client.DeepSeekError, match="密钥无效"):
        deepseek_client._post("bad-key", {"messages": []})


def test_malformed_reply_payload_is_rejected(monkeypatch):
    monkeypatch.setattr(deepseek_client, "_call_model", lambda *args, **kwargs: {"choices": [{"message": {"content": "{}"}}]})

    with pytest.raises(deepseek_client.DeepSeekError, match="有效"):
        deepseek_client.generate_suggestions(
            ChatSnapshot("朋友", [Message("other", "你好")]),
            "朋友",
            Analysis(),
            "key",
        )


@pytest.mark.parametrize(
    ("base_url", "protocol", "path"),
    [
        ("https://api.example.test/proxy/v1/chat/completions", "openai-chat", "/proxy/v1/models"),
        ("https://api.example.test/proxy/v1/responses", "openai-responses", "/proxy/v1/models"),
        ("https://api.anthropic.com/v1/messages", "anthropic", "/v1/models"),
    ],
)
def test_model_discovery_is_unauthenticated_and_preserves_prefix(monkeypatch, base_url, protocol, path):
    captured = {}

    def fake_open(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = {key.lower(): value for key, value in request.header_items()}
        return io.BytesIO(json.dumps({"data": [{"id": "model-z"}, {"id": "model-a"}]}).encode())

    monkeypatch.setattr(deepseek_client.urllib.request, "urlopen", fake_open)
    assert deepseek_client.list_models(base_url, protocol=protocol) == ["model-a", "model-z"]
    assert urllib.parse.urlsplit(captured["url"]).path == path
    if protocol == "anthropic":
        assert captured["headers"]["anthropic-version"] == deepseek_client.ANTHROPIC_VERSION
        assert "x-api-key" not in captured["headers"]
        assert "authorization" not in captured["headers"]
    else:
        assert "authorization" not in captured["headers"]


@pytest.mark.parametrize(
    ("protocol", "response", "endpoint"),
    [
        ("openai-chat", {"choices": [{"message": {"content": '{"replies":["a","b","c"]}'}}]}, "chat/completions"),
        ("openai-responses", {"output_text": '{"replies":["a","b","c"]}'}, "responses"),
        ("anthropic", {"content": [{"type": "text", "text": '{"replies":["a","b","c"]}'}]}, "messages"),
    ],
)
def test_generation_uses_each_protocol_request_shape(monkeypatch, protocol, response, endpoint):
    captured = {}

    def fake_call(base_url, key, used_protocol, body, timeout):
        captured.update(protocol=used_protocol, body=body, endpoint=deepseek_client._endpoint(base_url, endpoint, used_protocol))
        return response

    monkeypatch.setattr(deepseek_client, "_call_model", fake_call)
    snapshot = ChatSnapshot("朋友", [Message("other", "你好")])
    result = deepseek_client.generate_suggestions(snapshot, "朋友", Analysis(), "secret", "model-x", "https://api.example.test/v1", protocol=protocol)
    assert result == ["a", "b", "c"]
    assert captured["protocol"] == protocol
    assert captured["body"]["model"] == "model-x"
    assert "你好" in json.dumps(captured["body"], ensure_ascii=False)
    if protocol == "openai-responses":
        assert captured["body"]["max_output_tokens"] == 400
        assert captured["body"]["store"] is False
    elif protocol == "anthropic":
        assert captured["body"]["max_tokens"] == 400
        assert "system" in captured["body"]
    else:
        assert captured["body"]["messages"][0]["role"] == "system"


@pytest.mark.parametrize("protocol", ["openai-chat", "openai-responses", "anthropic"])
def test_connection_probe_contains_no_conversation_data(monkeypatch, protocol):
    captured = {}

    def fake_call(base_url, key, used_protocol, body, timeout):
        captured.update(protocol=used_protocol, body=body, timeout=timeout)
        return {
            "choices": [{"message": {"content": "OK"}}],
            "output_text": "OK",
            "content": [{"type": "text", "text": "OK"}],
        }

    monkeypatch.setattr(deepseek_client, "_call_model", fake_call)
    assert deepseek_client.test_connection("https://service.test/v1", "secret", "model-1", protocol) == "OK"
    serialized = json.dumps(captured["body"], ensure_ascii=False)
    assert "Reply with OK." in serialized
    assert "conversation" not in serialized
    assert "secret" not in serialized
    assert captured["timeout"] == 15


@pytest.mark.parametrize(
    ("base_url", "protocol", "path"),
    [
        ("https://api.openai.com", "openai-chat", "/v1/chat/completions"),
        ("https://api.openai.com", "openai-responses", "/v1/responses"),
        ("https://api.anthropic.com", "anthropic", "/v1/messages"),
    ],
)
def test_root_provider_urls_receive_required_version_prefix(base_url, protocol, path):
    endpoint = {"openai-chat": "chat/completions", "openai-responses": "responses", "anthropic": "messages"}[protocol]

    assert urllib.parse.urlsplit(deepseek_client._endpoint(base_url, endpoint, protocol)).path == path

