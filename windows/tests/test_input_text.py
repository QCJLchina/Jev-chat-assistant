import pytest

from jev_windows.i18n import describe
from jev_windows.input_text import parse_text
from jev_windows.models import Message


def test_prefixes_continuations_and_raw_input():
    text = "  opening\n\n我：你好\n continuation\n对方:收到\nME: hello\nOtHeR：hi\n"
    snapshot = parse_text(text)
    assert snapshot.raw_text == text
    assert snapshot.messages == [Message("other", "opening"), Message("me", "你好\ncontinuation"),
                                 Message("other", "收到"), Message("me", "hello"), Message("other", "hi")]


def test_all_messages_keep_continuations_and_entire_raw_text():
    text = "\n".join(f"me: {index}" for index in range(15)) + "\ncontinued"
    snapshot = parse_text(text)
    assert len(snapshot.messages) == 15
    assert snapshot.messages[0].text == "0"
    assert snapshot.messages[-1].text == "14\ncontinued"
    assert snapshot.raw_text == text


@pytest.mark.parametrize("text", ["", " \n\t\r\n", "me:\n对方："])
def test_empty_text_has_localization_identity(text):
    with pytest.raises(ValueError) as caught:
        parse_text(text)
    assert describe(caught.value) == {"key": "feature.emptyText", "params": {}}


def test_length_limit_counts_full_input():
    assert parse_text("x" * 20_000).raw_text == "x" * 20_000
    with pytest.raises(ValueError) as caught:
        parse_text(" " * 20_001)
    assert describe(caught.value) == {"key": "feature.textTooLong", "params": {}}


def test_empty_speaker_header_sets_next_message_side():
    assert parse_text("other: hello\nME：\n\nreply\ncontinued").messages == [
        Message("other", "hello"), Message("me", "reply\ncontinued")]


def test_prefix_must_be_at_start_and_have_a_colon():
    assert parse_text("meeting\nquote me: hi").messages == [Message("other", "meeting\nquote me: hi")]
