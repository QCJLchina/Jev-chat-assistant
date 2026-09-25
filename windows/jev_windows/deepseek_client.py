from __future__ import annotations

from .i18n import msg

import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from .models import Analysis, ChatSnapshot


CHAT_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_API_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-flash"
DEFAULT_PROTOCOL = "openai-chat"
SUPPORTED_PROTOCOLS = {"openai-chat", "openai-responses", "anthropic"}
ANTHROPIC_VERSION = "2023-06-01"


class DeepSeekError(RuntimeError):
    pass


def _endpoint(base_url: str, endpoint: str, protocol: str = DEFAULT_PROTOCOL) -> str:
    value = (base_url or DEFAULT_API_BASE_URL).strip().rstrip("/")
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme not in {"https", "http"} or not parsed.netloc:
        raise DeepSeekError(msg("error.url"))
    if parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise DeepSeekError(msg("error.https"))
    if protocol not in SUPPORTED_PROTOCOLS:
        raise DeepSeekError(msg("error.protocol"))
    path = parsed.path.rstrip("/")
    suffixes = {"/models", "/chat/completions", "/responses", "/messages"}
    for suffix in suffixes:
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    if not path and parsed.hostname == "api.anthropic.com":
        path = "/v1"
    elif not path and parsed.hostname == "api.openai.com":
        path = "/v1"
    path = f"{path}/{endpoint}" if path else f"/{endpoint}"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, parsed.query, ""))


def _headers(key: str, protocol: str, *, json_body: bool = False) -> dict[str, str]:
    headers = {"Accept": "application/json"}
    if json_body:
        headers["Content-Type"] = "application/json; charset=utf-8"
    if protocol == "anthropic":
        headers["anthropic-version"] = ANTHROPIC_VERSION
        if key:
            headers["x-api-key"] = key
    else:
        if key:
            headers["Authorization"] = f"Bearer {key}"
    return headers


def _request_json(
    base_url: str,
    path: str,
    key: str,
    protocol: str,
    *,
    body: dict | None = None,
    timeout: float = 35,
    query: dict[str, str] | None = None,
) -> dict:
    url = _endpoint(base_url, path, protocol)
    if query:
        parsed = urllib.parse.urlsplit(url)
        old_query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
        url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path,
            urllib.parse.urlencode([*old_query, *query.items()]), ""))
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        url,
        data=data,
        method="POST" if body is not None else "GET",
        headers=_headers(key, protocol, json_body=body is not None),
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:240]
        if exc.code in {404, 405} and path == "models":
            raise DeepSeekError(msg("error.noModelsEndpoint")) from None
        message = {
            401: msg("error.model401"),
            403: msg("error.model403"),
            402: msg("error.model402"),
            429: msg("error.model429"),
        }.get(exc.code, msg("error.modelHttp", status=exc.code, detail=detail))
        raise DeepSeekError(message) from None
    except (TimeoutError, socket.timeout, urllib.error.URLError) as exc:
        raise DeepSeekError(msg("error.modelConnect", detail=str(exc))) from None
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise DeepSeekError(msg("error.modelData")) from exc


def _post(
    key: str,
    body: dict,
    timeout: float = 35,
    base_url: str = DEFAULT_API_BASE_URL,
) -> dict:
    """Backward-compatible OpenAI Chat request helper."""
    return _request_json(base_url, "chat/completions", key, "openai-chat", body=body, timeout=timeout)


def list_models(base_url: str, key: str = "", timeout: float = 12, protocol: str = DEFAULT_PROTOCOL) -> list[str]:
    # Some gateways expose /models publicly, others require the API key.
    # Try unauthenticated first; retry once with the user's key on 401.
    try:
        payload = _request_json(base_url, "models", "", protocol, timeout=timeout)
    except DeepSeekError as exc:
        if not key or "401" not in str(exc):
            raise
        payload = _request_json(base_url, "models", key, protocol, timeout=timeout)
    try:
        data = payload["data"]
        models = sorted({str(item["id"]).strip() for item in data if item.get("id")})
    except (KeyError, TypeError, AttributeError) as exc:
        raise DeepSeekError(msg("error.modelListFormat")) from exc

    if protocol == "anthropic" and payload.get("has_more") and models:
        after_id = str(payload.get("last_id") or models[-1])
        for _ in range(9):
            page = _request_json(base_url, "models", key, protocol, timeout=timeout, query={"after_id": after_id})
            try:
                page_models = [str(item["id"]).strip() for item in page["data"] if item.get("id")]
            except (KeyError, TypeError, AttributeError) as exc:
                raise DeepSeekError(msg("error.modelPagination")) from exc
            models.extend(page_models)
            if not page.get("has_more") or not page_models:
                break
            after_id = str(page.get("last_id") or page_models[-1])
    models = sorted(set(models))
    if not models:
        raise DeepSeekError(msg("error.emptyModels"))
    return models


def _message_body(protocol: str, model: str, system: str, user: str, max_tokens: int) -> dict:
    if protocol == "openai-responses":
        return {
            "model": model,
            "instructions": system,
            "input": [{"role": "user", "content": user}],
            "max_output_tokens": max_tokens,
            "store": False,
        }
    if protocol == "anthropic":
        return {
            "model": model,
            "system": system,
            "messages": [{"role": "user", "content": user}],
            "max_tokens": max_tokens,
        }
    return {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "max_tokens": max_tokens,
        "stream": False,
    }


def _call_model(base_url: str, key: str, protocol: str, body: dict, timeout: float) -> dict:
    endpoint = {"openai-chat": "chat/completions", "openai-responses": "responses", "anthropic": "messages"}[protocol]
    return _request_json(base_url, endpoint, key, protocol, body=body, timeout=timeout)


def _response_text(response: dict, protocol: str) -> str:
    if protocol == "openai-chat":
        content = response["choices"][0]["message"]["content"]
        if isinstance(content, str):
            return content
        return "".join(str(item.get("text", "")) for item in content if isinstance(item, dict))
    if protocol == "openai-responses":
        if response.get("output_text"):
            return str(response["output_text"])
        texts: list[str] = []
        for item in response.get("output", []):
            for part in item.get("content", []):
                if part.get("type") in {"output_text", "text"}:
                    texts.append(str(part.get("text", "")))
        return "".join(texts)
    return "".join(str(item.get("text", "")) for item in response.get("content", []) if item.get("type") == "text")


def test_connection(base_url: str, key: str, model: str, protocol: str = DEFAULT_PROTOCOL) -> str:
    body = _message_body(protocol, model, "Reply with OK.", "Reply with OK.", 16)
    response = _call_model(base_url, key, protocol, body, 15)
    try:
        return _response_text(response, protocol).strip()[:100] or msg("model.success")
    except (KeyError, IndexError, TypeError, AttributeError):
        raise DeepSeekError(msg("error.modelResponse")) from None


def _parse_suggestions(content: str) -> list[str]:
    cleaned_content = content.strip()
    if cleaned_content.startswith("```"):
        cleaned_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned_content, flags=re.I)
    parsed = json.loads(cleaned_content)
    replies = parsed["replies"]
    return [str(item).strip() for item in replies if str(item).strip()]


def generate_suggestions(
    snapshot: ChatSnapshot,
    relationship: str,
    analysis: Analysis,
    key: str,
    model: str = DEFAULT_MODEL,
    base_url: str = DEFAULT_API_BASE_URL,
    max_tokens: int | None = None,
    protocol: str = DEFAULT_PROTOCOL,
) -> list[str]:
    if protocol not in SUPPORTED_PROTOCOLS:
        raise DeepSeekError(msg("error.protocol"))
    transcript = "\n".join(f"{'我' if message.side == 'me' else '对方'}：{message.text}" for message in snapshot.messages)
    judgment = {
        "true_intent": analysis.true_intent,
        "danger_level_0_to_9": analysis.danger_level,
        "need": analysis.need,
        "best_action": analysis.best_action,
        "should_reply_probability": analysis.should_reply_now,
        "tension_resolved_probability": analysis.tension_resolved,
    }
    system = (
        "你是谨慎的中文聊天回复助手。Jev 已经完成结构化判断，你只负责据此起草回复。"
        "给出恰好三条简短、自然、彼此不同的建议，不编造事实、记忆、承诺或时间。"
        "不要替用户发送。只输出 JSON：{\"replies\":[\"...\",\"...\",\"...\"]}。"
    )
    user = f"关系：{relationship}\nJev判断：{json.dumps(judgment, ensure_ascii=False)}\n对话：\n{transcript}"
    body = _message_body(protocol, model or DEFAULT_MODEL, system, user, max_tokens or 400)
    response = _call_model(base_url, key, protocol, body, 35)
    try:
        replies = _parse_suggestions(_response_text(response, protocol))
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise DeepSeekError(msg("error.repliesInvalid")) from exc
    if len(replies) != 3:
        raise DeepSeekError(msg("error.repliesCount"))
    return replies
