"""Session-only reply goals; never persisted with reply preferences."""
from .i18n import msg

INTENTS = {
    "general": "",
    "decline": "Politely but clearly decline. Do not make additional promises.",
    "clarify": "Clarify the misunderstanding and explain the user's position without blame or speculation.",
    "close": "Naturally end the topic without introducing another question or topic.",
    "deescalate": "Reduce conflict, express understanding, and maintain the user's boundaries.",
}


def validate_intent(value="general"):
    if not isinstance(value, str) or value not in INTENTS:
        raise ValueError(msg("review.invalidIntent"))
    return value


def intent_prompt(value="general"):
    return INTENTS[validate_intent(value)]
