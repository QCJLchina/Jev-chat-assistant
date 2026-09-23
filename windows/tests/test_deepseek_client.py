import io
import json
import urllib.error

import pytest

from jev_windows import deepseek_client
from jev_windows.models import Analysis, ChatSnapshot, Message


def test_generate_three_suggestions_uses_jev_judgment(monkeypatch):
    captured = {}

    def fake_post(key, body, timeout=35):
        captured.update(body)
        return {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {"replies": ["好呀，晚上七点见。", "可以，还是老地方吗？", "没问题，我七点过去。"]},
                            ensure_ascii=False,
                        )
                    }
                }
            ]
        }

    monkeypatch.setattr(deepseek_client, "_post", fake_post)
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
    assert captured["thinking"] == {"type": "disabled"}
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
    monkeypatch.setattr(
        deepseek_client,
        "_post",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "{}"}}]},
    )

    with pytest.raises(deepseek_client.DeepSeekError, match="有效"):
        deepseek_client.generate_suggestions(
            ChatSnapshot("朋友", [Message("other", "你好")]),
            "朋友",
            Analysis(),
            "key",
        )

