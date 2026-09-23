from __future__ import annotations


BLOCKED_KEYWORDS = (
    "转账",
    "红包",
    "收款",
    "付款",
    "支付",
    "银行卡",
    "二维码收款",
    "transfer",
    "payment",
)


def assert_safe_chat(raw_text: str) -> None:
    lowered = raw_text.lower()
    matched = next((word for word in BLOCKED_KEYWORDS if word.lower() in lowered), None)
    if matched:
        raise RuntimeError(f"当前画面包含敏感交易词“{matched}”，已停止分析和回填。")

