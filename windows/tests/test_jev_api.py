import io
import urllib.error

import pytest

from jev_windows import jev_api
from jev_windows.models import ChatSnapshot, Message


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
