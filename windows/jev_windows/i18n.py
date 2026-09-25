"""Shared, offline message catalog. Messages retain identity until presentation."""
from __future__ import annotations

import ctypes
import json
import re
import sys
from functools import lru_cache, wraps
from pathlib import Path

LANGUAGES = {"system", "zh-CN", "en", "fr", "ru", "ja"}


def system_language() -> str:
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        buffer = ctypes.create_unicode_buffer(85)
        if ctypes.windll.kernel32.LCIDToLocaleName(lang_id, buffer, len(buffer), 0):
            return buffer.value
    except (AttributeError, OSError):
        pass
    return "en"


def resolve_language(language: str) -> str:
    if language != "system":
        return language if language in LANGUAGES else "zh-CN"
    name = system_language().replace("_", "-").lower()
    if name in {"zh-cn", "zh-sg", "zh-hans"} or name.startswith("zh-hans-"):
        return "zh-CN"
    base = name.split("-")[0]
    return base if base in {"en", "fr", "ru", "ja"} else "en"


@lru_cache(maxsize=5)
def catalog(locale: str) -> dict[str, str]:
    root = Path(sys._MEIPASS) if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return json.loads((root / "locales" / f"{locale}.json").read_text(encoding="utf-8"))


def translate(key: str, locale: str = "zh-CN", **params) -> str:
    template = catalog(locale).get(key, catalog("zh-CN").get(key, key))
    def replace(match):
        name = match.group(1)
        value = params.get(name, match.group(0))
        if isinstance(value, dict) and "key" in value:
            return render(value, locale)
        return str(value)
    return re.sub(r"\{([A-Za-z_][A-Za-z_0-9]*)\}", replace, template)


class Message(str):
    def __new__(cls, key: str, **params):
        normalized = {k: describe(v) if isinstance(v, (Message, Exception)) else v for k, v in params.items()}
        obj = super().__new__(cls, translate(key, **normalized))
        obj.message = {"key": key, "params": normalized}
        return obj


def msg(key: str, **params) -> Message:
    return Message(key, **params)


def describe(value) -> dict | None:
    if isinstance(value, Message):
        return value.message
    if isinstance(value, Exception):
        if value.args and isinstance(value.args[0], Message):
            return value.args[0].message
        return {"key": "error.unexpected", "params": {"detail": str(value)}}
    return None


def render(message: dict | None, locale: str, fallback: str = "") -> str:
    return translate(message["key"], locale, **message.get("params", {})) if message else fallback


def bridge_errors(method):
    """Keep expected errors structured instead of losing them in JS exceptions."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        try:
            result = method(self, *args, **kwargs)
            for field in ("error", "message"):
                if isinstance(result.get(field), Message):
                    result[field + "_message"] = describe(result[field])
                    result[field] = render(result[field + "_message"], self.resolved_language)
            return result
        except Exception as exc:
            message = describe(exc)
            return {"ok": False, "error": render(message, self.resolved_language), "error_message": message}
    return wrapped


def settings_lock(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return wrapped
