import io
import urllib.error

import pytest

from jev_windows import jev_api
from jev_windows.models import ChatSnapshot, Message
from tools.jev.questions import build_state


def test_judge_calls_direct_typesafe_api_and_maps_other_side(monkeypatch):
    captured = {}

    def fake_post(key, body, timeout=20):
        captured.update(body)
        return {
            "answers": {
                "true_intent": {"choice": "casual_chat"},
                "danger_level": {"score": 1.0},
                "she_needs": {"choice": "nothing"},
                "best_action": {"choice": "acknowledge"},
                "should_reply_now": {"noul": 0.2},
                "tension_resolved": {"noul": 0.9},
            }
        }

    monkeypatch.setattr(jev_api, "_post", fake_post)
    snapshot = ChatSnapshot("朋友", [Message("other", "你好"), Message("me", "嗨")])

    result = jev_api.judge(snapshot, "朋友", "typesafe-secret")

    assert jev_api.SYSTEM_ONE_URL == "https://api.typesafe.ai/v1/systemone"
    assert captured["model"] == "jev-latest"
    assert captured["state"]["chat"]["messages"][0]["from"] == "her"
    assert result.true_intent == "casual_chat"
    assert result.danger_level == 1.0
    assert result.should_reply_now == 0.2


def test_invalid_direct_jev_key_has_readable_error(monkeypatch):
    error = urllib.error.HTTPError(
        jev_api.SYSTEM_ONE_URL, 401, "Unauthorized", {}, io.BytesIO(b"{}")
    )
    monkeypatch.setattr(
        jev_api.urllib.request,
        "urlopen",
        lambda *args, **kwargs: (_ for _ in ()).throw(error),
    )

    with pytest.raises(jev_api.JevApiError, match="密钥无效"):
        jev_api._post("bad-key", {"state": {}, "questions": {}})


def test_build_state_default_preserves_calibration_last_ten_contract():
    messages = [("her", str(index)) for index in range(14)] + [("me", "last")]
    expected = [{"from": who, "text": text} for who, text in messages[-10:]]
    assert build_state(messages, "friends") == {
        "chat": {"relationship": "friends", "messages": expected, "latest_from": "me"}}
    assert len(build_state(messages, "friends", message_limit=None)["chat"]["messages"]) == 15
    assert build_state([], "friends")["chat"]["latest_from"] == "her"


@pytest.mark.parametrize("limit", [0, -1, True, 10.0, "10"])
def test_build_state_rejects_invalid_explicit_limits(limit):
    with pytest.raises(ValueError):
        build_state([], "friends", message_limit=limit)


def test_windows_state_keeps_all_messages_and_background_only_in_relationship():
    source = ChatSnapshot("title", [Message("other", str(index)) for index in range(14)]
                          + [Message("me", "last")], "raw", "me: background fact")
    chat = jev_api._state(source, "friends")["chat"]
    assert len(chat["messages"]) == 15 and chat["latest_from"] == "me"
    assert chat["relationship"] == (
        "friends\n\nBackground (user-provided context, not chat messages):\nme: background fact")
    assert set(chat) == {"relationship", "messages", "latest_from"}
    assert source.background == "me: background fact"


def test_empty_chat_background_does_not_change_latest_speaker():
    assert jev_api._state(ChatSnapshot("", [], "", "fact"), "friends")["chat"]["latest_from"] == "her"
