"""Validated reply settings and model prompt instructions."""
from __future__ import annotations

from collections.abc import Mapping

from .i18n import resolve_language


DEFAULT_PREFERENCES = {"length": "short", "style": "natural", "language": "zh-CN"}
LANGUAGES = {"zh-CN", "en", "fr", "ru", "ja", "ko"}
_OPTIONS = {
    "length": {"short", "detailed"},
    "style": {"natural", "formal", "gentle", "direct"},
    "language": LANGUAGES | {"interface"},
}


def validate_preferences(preferences: object = None) -> dict[str, str]:
    """Return a fresh normalized dict; missing/invalid fields use defaults."""
    source = preferences if isinstance(preferences, Mapping) else {}
    return {
        key: value if isinstance(value := source.get(key), str) and value in _OPTIONS[key] else default
        for key, default in DEFAULT_PREFERENCES.items()
    }


def resolve_preferences(preferences: object = None, interface_language: str = "zh-CN") -> dict[str, str]:
    """Resolve 'interface' (including a system UI locale) for generation."""
    result = validate_preferences(preferences)
    if result["language"] == "interface":
        result["language"] = resolve_language(interface_language)
    return result


def build_reply_prompt(preferences: object = None, interface_language: str = "zh-CN") -> str:
    """Build system instructions without changing the three-reply JSON contract."""
    resolved = resolve_preferences(preferences, interface_language)
    length = {"short": "Keep each reply short and concise.",
              "detailed": "Give detailed replies with useful context and explanation."}[resolved["length"]]
    style = {"natural": "Use a natural, conversational tone.",
             "formal": "Use a formal, professional tone.",
             "gentle": "Use a gentle, considerate tone.",
             "direct": "Use a direct, straightforward tone."}[resolved["style"]]
    language = {"zh-CN": "Simplified Chinese", "en": "English", "fr": "French",
                "ru": "Russian", "ja": "Japanese", "ko": "Korean"}[resolved["language"]]
    return (
        "You are a cautious chat reply assistant. Jev has completed the structured judgment; "
        "draft replies based on it. Provide exactly three distinct suggestions. "
        "Do not invent facts, memories, promises, or times. Do not send replies for the user. "
        f"{length} {style} Write all replies in {language} ({resolved['language']}). "
        'Output only JSON: {"replies":["...","...","..."]}.'
    )
