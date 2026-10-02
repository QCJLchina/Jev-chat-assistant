"""Parse pasted conversations without discarding the original input."""
from __future__ import annotations

import re

from .i18n import msg
from .models import ChatSnapshot, Message


MAX_TEXT_LENGTH = 20_000
_PREFIX = re.compile(r"^(我|对方|me|other)\s*[:：]\s*(.*)$", re.IGNORECASE)


def parse_text(text: str) -> ChatSnapshot:
    """Keep the last ten messages; continuations join the preceding message."""
    if not isinstance(text, str):
        raise ValueError(msg("feature.emptyText"))
    if len(text) > MAX_TEXT_LENGTH:
        raise ValueError(msg("feature.textTooLong"))
    messages: list[Message] = []
    pending_side: str | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        match = _PREFIX.match(line)
        if match:
            side = "me" if match[1].lower() in {"我", "me"} else "other"
            content = match[2].strip()
            pending_side = side if not content else None
            if content:
                messages.append(Message(side, content))
        elif pending_side is not None or not messages:
            messages.append(Message(pending_side or "other", line))
            pending_side = None
        else:
            previous = messages[-1]
            messages[-1] = Message(previous.side, previous.text + "\n" + line)
    if not messages:
        raise ValueError(msg("feature.emptyText"))
    return ChatSnapshot(title="", messages=messages[-10:], raw_text=text)
