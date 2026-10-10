"""Bound review drafts before copying, joining, or scanning their contents."""
from .i18n import msg

MAX_DRAFT_MESSAGES = 20_000
MAX_DRAFT_CHARACTERS = 200_000


def validate_draft(messages, *, wire=False, raw_text=""):
    if not isinstance(messages, list):
        raise ValueError(msg("review.invalidMessages"))
    if len(messages) > MAX_DRAFT_MESSAGES or len(raw_text) > MAX_DRAFT_CHARACTERS:
        raise ValueError(msg("review.capacityExceeded"))
    characters = 0
    for message in messages:
        if wire:
            if not isinstance(message, dict):
                raise ValueError(msg("review.invalidMessages"))
            side, text = message.get("side"), message.get("text")
        else:
            side, text = message.side, message.text
        if not isinstance(side, str) or side not in {"me", "other"} or not isinstance(text, str):
            raise ValueError(msg("review.invalidMessages"))
        characters += len(text)
        if characters > MAX_DRAFT_CHARACTERS:
            raise ValueError(msg("review.capacityExceeded"))
