from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from tools.jev.questions import JUDGE_QUESTIONS, build_state

from .models import Analysis, ChatSnapshot


SYSTEM_ONE_URL = "https://api.typesafe.ai/v1/systemone"
JEV_MODEL = "jev-latest"


class JevApiError(RuntimeError):
    pass


def _post(key: str, body: dict, timeout: float = 20) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(2):
        request = urllib.request.Request(
            SYSTEM_ONE_URL,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json; charset=utf-8",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            status = exc.code
            body_text = exc.read().decode("utf-8", errors="replace")[:300]
            if status in (429, 500, 502, 503, 529) and attempt == 0:
                time.sleep(1)
                continue
            readable = {
                401: "Jev / TypeSafe API 密钥无效（401）",
                403: "当前 Jev API 密钥没有访问权限（403）",
                422: f"Jev 请求格式被拒绝（422）：{body_text}",
                429: "Jev 请求过于频繁（429）",
            }.get(status, f"Jev API 请求失败（HTTP {status}）：{body_text}")
            raise JevApiError(readable) from None
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1)
                continue
    raise JevApiError(f"无法连接 Jev API：{last_error}")


def _state(snapshot: ChatSnapshot, relationship: str) -> dict:
    # Keep the calibrated question set's historical wire labels.
    messages = [("me" if message.side == "me" else "her", message.text) for message in snapshot.messages]
    return build_state(messages, relationship)


def _choice(answers: dict, name: str) -> str:
    value = answers.get(name) or {}
    return str(value.get("choice") or value.get("answer") or "")


def _number(answers: dict, name: str, *keys: str) -> float | None:
    value = answers.get(name) or {}
    for key in keys:
        number = value.get(key)
        if isinstance(number, (int, float)):
            return float(number)
    return None


def judge(snapshot: ChatSnapshot, relationship: str, key: str) -> Analysis:
    start = time.monotonic()
    response = _post(
        key,
        {"model": JEV_MODEL, "state": _state(snapshot, relationship), "questions": JUDGE_QUESTIONS},
    )
    answers = response.get("answers") or {}
    return Analysis(
        true_intent=_choice(answers, "true_intent"),
        danger_level=_number(answers, "danger_level", "score", "answer"),
        need=_choice(answers, "she_needs"),
        best_action=_choice(answers, "best_action"),
        should_reply_now=_number(answers, "should_reply_now", "noul", "answer"),
        tension_resolved=_number(answers, "tension_resolved", "noul", "answer"),
        latency_ms=int((time.monotonic() - start) * 1000),
    )

