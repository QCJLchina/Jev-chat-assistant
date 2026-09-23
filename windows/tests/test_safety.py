import pytest

from jev_windows.safety import assert_safe_chat


@pytest.mark.parametrize("text", ["给你转账了", "请点收款", "payment received"])
def test_money_screens_are_blocked(text):
    with pytest.raises(RuntimeError):
        assert_safe_chat(text)


def test_normal_chat_is_allowed():
    assert_safe_chat("今晚七点一起吃饭吗")

