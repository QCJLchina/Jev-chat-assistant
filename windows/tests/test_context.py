from dataclasses import FrozenInstanceError

import pytest

from jev_windows.context import compose_context, normalize_context
from jev_windows.i18n import describe
from jev_windows.input_text import parse_text
from jev_windows.models import ChatSnapshot, Message


def test_defaults_exact_fields_and_fresh_options():
    expected = {"prior_text": "", "background": "", "message_limit": None}
    assert normalize_context() == normalize_context({}) == expected
    first = normalize_context()
    first["background"] = "changed"
    assert normalize_context() == expected
    source = {"prior_text": "  me: old\n", "background": "  fact\n", "unused": True}
    assert normalize_context(source) == {**expected, "prior_text": source["prior_text"],
                                         "background": source["background"]}
    assert source["unused"] is True


@pytest.mark.parametrize("payload, key", [
    ([], "invalidOptions"), ("", "invalidOptions"), (False, "invalidOptions"),
    ({"prior_text": None}, "invalidPriorText"), ({"prior_text": []}, "invalidPriorText"),
    ({"background": None}, "invalidBackground"), ({"background": 1}, "invalidBackground"),
    ({"message_limit": True}, "invalidMessageLimit"), ({"message_limit": False}, "invalidMessageLimit"),
    ({"message_limit": 10.0}, "invalidMessageLimit"), ({"message_limit": "10"}, "invalidMessageLimit"),
    ({"message_limit": []}, "invalidMessageLimit"), ({"message_limit": 0}, "invalidMessageLimit"),
    ({"message_limit": 30}, "invalidMessageLimit"),
    ({"prior_text": "界" * 20_001}, "priorTooLong"),
])
def test_validation_error_identity(payload, key):
    with pytest.raises(ValueError) as caught:
        normalize_context(payload)
    assert describe(caught.value) == {"key": f"context.{key}", "params": {}}


@pytest.mark.parametrize("limit", [None, 10, 20, 50])
def test_merge_then_select_and_exact_statistics_without_mutation(limit):
    source = parse_text("\n".join(f"other: current-{index}" for index in range(55)))
    prior_text = "me: prior-0\nother: prior-1"
    options = {"prior_text": prior_text, "background": "background facts", "message_limit": limit}
    original = list(source.messages)
    effective, stats = compose_context(source, options)
    merged = [Message("me", "prior-0"), Message("other", "prior-1"), *original]
    expected = merged if limit is None else merged[-limit:]
    assert effective.messages == expected
    assert effective.background == options["background"]
    assert effective.raw_text == prior_text + "\n" + source.raw_text
    assert stats == {"total_messages": 57, "used_messages": len(expected),
                     "characters": sum(len(m.text) for m in expected) + len(options["background"]),
                     "message_limit": limit, "omitted_messages": 57 - len(expected)}
    assert source.messages == original and source.background == ""
    assert effective.messages is not source.messages
    with pytest.raises(FrozenInstanceError):
        effective.background = "mutated"


@pytest.mark.parametrize("prior", ["", " \n\t"])
def test_empty_prior_allowed_and_three_positional_snapshot_fields_preserved(prior):
    messages = [Message("me", "last")]
    source = ChatSnapshot("title", messages, "raw")
    effective, stats = compose_context(source, {"prior_text": prior})
    assert effective.title == "title" and effective.messages == messages
    assert effective.background == "" and stats["used_messages"] == 1


def test_background_is_metadata_even_without_messages():
    effective, stats = compose_context(ChatSnapshot("", []), {"background": "fact"})
    assert effective.messages == [] and effective.background == "fact"
    assert stats == {"total_messages": 0, "used_messages": 0, "characters": 4,
                     "message_limit": None, "omitted_messages": 0}


def test_unicode_budget_is_bodies_plus_background_and_never_truncates():
    source = ChatSnapshot("", [Message("me", "😀" * 19_999)])
    effective, stats = compose_context(source, {"background": "界"})
    assert stats["characters"] == 20_000
    assert effective.messages[0].text == source.messages[0].text
    with pytest.raises(ValueError) as caught:
        compose_context(source, {"background": "界界"})
    assert describe(caught.value) == {"key": "context.tooLong", "params": {}}
    assert len(source.messages[0].text) == 19_999


def test_prior_budget_and_selected_budget_are_separate():
    assert len(normalize_context({"prior_text": "😀" * 20_000})["prior_text"]) == 20_000
    source = ChatSnapshot("", [Message("other", "x") for _ in range(10)])
    effective, stats = compose_context(source, {"prior_text": "😀" * 20_000, "message_limit": 10})
    assert effective.messages == source.messages
    assert stats["characters"] == 10 and stats["omitted_messages"] == 1
    with pytest.raises(ValueError) as caught:
        compose_context(source, {"prior_text": "😀" * 20_000})
    assert describe(caught.value)["key"] == "context.tooLong"


def test_range_can_fit_a_large_ocr_snapshot_without_truncating_selected_bodies():
    source = ChatSnapshot("", [Message("other", "界" * 2_000) for _ in range(11)], "界" * 22_000)
    with pytest.raises(ValueError):
        compose_context(source, {})
    effective, stats = compose_context(source, {"message_limit": 10})
    assert stats["characters"] == 20_000 and len(effective.raw_text) == 22_000
    assert all(len(m.text) == 2_000 for m in effective.messages)


@pytest.mark.parametrize("where", ["raw", "dropped_current", "dropped_prior", "background"])
def test_safety_scans_all_inputs_before_range_and_size_checks(where):
    source = parse_text("\n".join("me: safe" for _ in range(11)))
    options = {"message_limit": 10}
    if where == "raw":
        source = ChatSnapshot("", source.messages, "付款\n" + source.raw_text)
    elif where == "dropped_current":
        source = ChatSnapshot("", [Message("other", "付款"), *source.messages])
    elif where == "dropped_prior":
        options["prior_text"] = "other: 付款"
    else:
        options["background"] = "界" * 20_001 + "付款"
    with pytest.raises(RuntimeError) as caught:
        compose_context(source, options)
    assert describe(caught.value) == {"key": "error.sensitive", "params": {"word": "付款"}}
