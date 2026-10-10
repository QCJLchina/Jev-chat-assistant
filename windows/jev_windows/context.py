"""Validate and compose the complete context before any model request."""
from __future__ import annotations

from dataclasses import replace

from .i18n import msg
from .input_text import MAX_TEXT_LENGTH, parse_text
from .models import ChatSnapshot
from .safety import assert_safe_chat


def normalize_context(payload=None) -> dict:
    """Return fresh options, preserving text exactly and rejecting invalid types."""
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise ValueError(msg("context.invalidOptions"))
    prior_text = payload.get("prior_text", "")
    background = payload.get("background", "")
    message_limit = payload.get("message_limit", None)
    if not isinstance(prior_text, str):
        raise ValueError(msg("context.invalidPriorText"))
    if not isinstance(background, str):
        raise ValueError(msg("context.invalidBackground"))
    if message_limit is not None and (type(message_limit) is not int or message_limit not in (10, 20, 50)):
        raise ValueError(msg("context.invalidMessageLimit"))
    if len(prior_text) > MAX_TEXT_LENGTH:
        raise ValueError(msg("context.priorTooLong"))
    if len(background) > MAX_TEXT_LENGTH:
        raise ValueError(msg("context.tooLong"))
    return {"prior_text": prior_text, "background": background, "message_limit": message_limit}


def compose_context(snapshot: ChatSnapshot, options) -> tuple[ChatSnapshot, dict]:
    """Scan all input, then select messages and enforce the Unicode body budget.

    The source snapshot is never mutated. Raw input remains complete, including
    text outside the selected range, so subsequent safety scans remain valid.
    Background is metadata and never changes speaker identity or latest_from.
    """
    normalized = normalize_context(options)
    prior_text = normalized["prior_text"]
    background = normalized["background"]
    message_limit = normalized["message_limit"]
    raw_text = "\n".join(text for text in (prior_text, snapshot.raw_text) if text)
    # Scan before parsing/selecting, including OCR text not classified as chat.
    assert_safe_chat("\n".join((snapshot.raw_text, prior_text, background)))
    # Programmatic snapshots may omit raw_text; their bodies must be safe too.
    assert_safe_chat("\n".join(message.text for message in snapshot.messages))
    prior_messages = parse_text(prior_text).messages if prior_text.strip() else []
    messages = [*prior_messages, *snapshot.messages]
    selected = messages if message_limit is None else messages[-message_limit:]
    characters = sum(len(message.text) for message in selected) + len(background)
    if characters > MAX_TEXT_LENGTH:
        raise ValueError(msg("context.tooLong"))
    effective = replace(snapshot, messages=selected, raw_text=raw_text, background=background)
    return effective, {
        "total_messages": len(messages),
        "used_messages": len(selected),
        "characters": characters,
        "message_limit": message_limit,
        "omitted_messages": len(messages) - len(selected),
    }
