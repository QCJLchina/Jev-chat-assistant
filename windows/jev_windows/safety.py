from __future__ import annotations

from .i18n import msg

import re


# Transaction vocabulary. Keep this list plain-language: it is scanned against
# raw OCR output, so it must stay readable and easy to audit. Terms here are
# deliberately tied to payments/transfers rather than generic banking words
# ("金额", "余额"), which show up in ordinary conversation and would over-block.
BLOCKED_KEYWORDS = (
    "转账",
    "转帐",
    "红包",
    "收款",
    "付款",
    "支付",
    "付钱",
    "打款",
    "汇款",
    "银行卡",
    "信用卡",
    "支付宝",
    "微信支付",
    "二维码收款",
    "收款码",
    "付款码",
    "transfer",
    "payment",
    "remittance",
    "bank transfer",
)


# OCR output routinely inserts spaces or separators between characters that the
# source rendered as one run ("转 账", "收.款"). Matching on the raw string would
# silently miss those variants, so normalize away everything that is not a
# letter, digit, or CJK character before comparing.
_SEPARATORS = re.compile(r"[\s\-_.,、·|/\\()\[\]{}<>:;'\"`~!?@#$%^&*+=]+")


def normalize(text: str) -> str:
    return _SEPARATORS.sub("", text).lower()


def _normalized_keywords() -> tuple[str, ...]:
    return tuple(normalize(word) for word in BLOCKED_KEYWORDS)


NORMALIZED_KEYWORDS = _normalized_keywords()


def find_blocked_keyword(raw_text: str) -> str | None:
    """Return the most specific matched keyword, or None when the text looks safe."""
    normalized = normalize(raw_text)
    matches = [
        keyword
        for keyword, normalized_keyword in zip(BLOCKED_KEYWORDS, NORMALIZED_KEYWORDS)
        if normalized_keyword and normalized_keyword in normalized
    ]
    # Overlapping entries exist ("支付" inside "支付宝"); report the most specific
    # one so the user-facing message names the term that actually appeared.
    return max(matches, key=len) if matches else None


def assert_safe_chat(raw_text: str) -> None:
    matched = find_blocked_keyword(raw_text)
    if matched:
        raise RuntimeError(msg("error.sensitive", word=matched))
