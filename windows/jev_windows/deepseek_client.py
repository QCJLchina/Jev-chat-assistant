from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request

from .models import Analysis, ChatSnapshot


CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-flash"


class DeepSeekError(RuntimeError):
    pass


def _post(key: str, body: dict, timeout: float = 35) -> dict:
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error: Exception | None = None
    for attempt in range(2):
        request = urllib.request.Request(
            CHAT_URL,
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
            detail = exc.read().decode("utf-8", errors="replace")[:300]
            if status in (429, 500, 502, 503) and attempt == 0:
                time.sleep(1)
                continue
            readable = {
                401: "DeepSeek API 密钥无效（401）",
                402: "DeepSeek API 余额不足（402）",
                429: "DeepSeek 请求过于频繁（429）",
            }.get(status, f"DeepSeek 请求失败（HTTP {status}）：{detail}")
            raise DeepSeekError(readable) from None
        except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
            last_error = exc
            if attempt == 0:
                time.sleep(1)
                continue
    raise DeepSeekError(f"无法连接 DeepSeek API：{last_error}")


def generate_suggestions(
    snapshot: ChatSnapshot,
    relationship: str,
    analysis: Analysis,
    key: str,
    model: str = DEFAULT_MODEL,
) -> list[str]:
    transcript = "\n".join(
        f"{'我' if message.side == 'me' else '对方'}：{message.text}"
        for message in snapshot.messages
    )
    judgment = {
        "true_intent": analysis.true_intent,
        "danger_level_0_to_9": analysis.danger_level,
        "need": analysis.need,
        "best_action": analysis.best_action,
        "should_reply_probability": analysis.should_reply_now,
        "tension_resolved_probability": analysis.tension_resolved,
    }
    response = _post(
        key,
        {
            "model": model or DEFAULT_MODEL,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "你是谨慎的中文聊天回复助手。Jev 已经完成结构化判断，你只负责据此起草回复。"
                        "给出恰好三条简短、自然、彼此不同的建议，不编造事实、记忆、承诺或时间。"
                        "不要替用户发送。只输出 JSON：{\"replies\":[\"...\",\"...\",\"...\"]}。"
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"关系：{relationship}\n"
                        f"Jev判断：{json.dumps(judgment, ensure_ascii=False)}\n"
                        f"对话：\n{transcript}"
                    ),
                },
            ],
            "thinking": {"type": "disabled"},
            "max_tokens": 400,
            "response_format": {"type": "json_object"},
            "stream": False,
        },
    )
    try:
        content = response["choices"][0]["message"]["content"]
        parsed = json.loads(content)
        replies = parsed["replies"]
        cleaned = [str(item).strip() for item in replies if str(item).strip()]
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeepSeekError("DeepSeek 没有返回有效的建议回复。") from exc
    if len(cleaned) != 3:
        raise DeepSeekError("DeepSeek 返回的建议回复不是三条。")
    return cleaned

