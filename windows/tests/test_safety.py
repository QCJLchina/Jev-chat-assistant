import pytest

from jev_windows.safety import BLOCKED_KEYWORDS, assert_safe_chat, find_blocked_keyword, normalize


@pytest.mark.parametrize("text", ["给你转账了", "请点收款", "payment received"])
def test_money_screens_are_blocked(text):
    with pytest.raises(RuntimeError):
        assert_safe_chat(text)


def test_normal_chat_is_allowed():
    assert assert_safe_chat("今晚七点一起吃饭吗") is None


@pytest.mark.parametrize("keyword", BLOCKED_KEYWORDS)
def test_every_keyword_is_blocked_individually(keyword):
    """The blocklist is the product's safety promise; every entry must actually fire."""
    assert find_blocked_keyword(f"请确认：{keyword}") == keyword


@pytest.mark.parametrize("keyword", BLOCKED_KEYWORDS)
def test_keywords_match_case_insensitively(keyword):
    assert find_blocked_keyword(keyword.upper()) == keyword


def test_english_keyword_inside_a_sentence_is_blocked():
    assert find_blocked_keyword("I will send the Payment tomorrow") == "payment"
    assert find_blocked_keyword("TRANSFER done") == "transfer"


def test_traditional_and_variant_spellings_are_covered():
    assert find_blocked_keyword("帮我转帐") == "转帐"


@pytest.mark.parametrize("text", [
    "转 账",
    "转　账",
    "收.款",
    "付-款",
    "支 付 宝",
    "二 维 码 收 款",
    "t r a n s f e r",
])
def test_ocr_separated_keywords_are_still_blocked(text):
    """OCR frequently splits a single rendered run; separators must not defeat the scan."""
    assert find_blocked_keyword(text) is not None, text


def test_keyword_embedded_in_longer_text_is_blocked():
    long_text = "今天天气不错然后他说要给我转账一万块但是我觉得太多了所以先拒绝了他"
    assert find_blocked_keyword(long_text) == "转账"


def test_normalization_strips_separators_and_lowercases():
    assert normalize(" 转-账 ") == "转账"
    assert normalize("T R A N S F E R") == "transfer"


def test_normalization_keeps_cjk_and_ascii_alphanumerics():
    assert normalize("收款码abc123") == "收款码abc123"


@pytest.mark.parametrize("text", [
    "这笔钱我下次请你吃饭抵了",
    "今天银行股涨得不错",
    "我余额不多了要省着花",
    "周末去打羽毛球",
])
def test_ordinary_chat_is_not_over_blocked(text):
    """Over-blocking is a real risk: generic money words must not trip the filter."""
    assert find_blocked_keyword(text) is None, text
