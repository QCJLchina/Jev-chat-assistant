"""Review checkpoints and reply mutations: no real credentials or API calls."""
import pytest

from jev_windows import task_controller as module, i18n
from jev_windows.models import ChatSnapshot, Message, Rect
from test_task_controller import rig, join, start_text, REPLIES


def prepare(rig, text="other: hello", **kwargs):
    task = rig.controller.start(rig.settings, "en", text=text, review=True, **kwargs)["task_id"]
    join(rig.workers[-1])
    assert rig.progress.get("review_id") == task
    assert rig.calls == []
    return task


def confirm(rig, task, messages=None, **kwargs):
    result = rig.controller.submit_review(task, messages or [{"side": "other", "text": "corrected"}],
        rig.settings, "en", **kwargs)
    join(rig.workers[-1])
    return result["task_id"]


def test_review_without_keys_or_network_and_freeze_at_confirmation(rig, monkeypatch):
    monkeypatch.setattr(module, "load_api_key", lambda: "")
    task = prepare(rig)
    assert rig.progress.get("analysis") is None
    monkeypatch.setattr(module, "load_api_key", lambda: "confirmed-key")
    rig.settings.relationship = "confirmed relationship"
    confirm(rig, task, [{"side": "me", "text": "new first"}, {"side": "other", "text": " "},
                        {"side": "other", "text": "new second"}], intent="decline")
    judge, generate, rank = rig.calls
    assert [m.text for m in judge[1][0].messages] == ["new first", "new second"]
    assert judge[1][0].messages[0].side == "me"
    assert judge[1][1:] == ("confirmed relationship", "confirmed-key")
    assert generate[2]["intent"] == "decline"
    assert rig.progress.get("task_intent") == "decline"
    assert rig.progress.get("review_id") is None


def test_desktop_review_stops_after_capture(rig, monkeypatch):
    rig.settings.chat_rect = Rect(0, 0, 800, 600)
    monkeypatch.setattr(module.workflow.AnalysisService, "capture", lambda *a, **k:
                        ChatSnapshot("chat", [Message("other", "hello")], "hello"))
    result = rig.controller.start(rig.settings, "en", review=True)
    join(rig.workers[-1])
    assert rig.progress.get("review_id") == result["task_id"]
    assert rig.calls == []
    confirm(rig, result["task_id"])
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank"]


@pytest.mark.parametrize("where", ["raw", "prior", "background", "correction", "omitted"])
def test_deleted_or_out_of_range_transactions_still_block(rig, where):
    options = {"prior_text": "other: 请转账" if where == "prior" else "",
               "background": "请转账" if where == "background" else ""}
    task = prepare(rig, text="other: 请转账" if where == "raw" else "other: hello", context=options)
    messages = [{"side": "other", "text": "请转账" if where in {"correction", "omitted"} else "hello"}]
    if where == "omitted":
        messages.extend({"side": "other", "text": "safe"} for _ in range(10))
    with pytest.raises(RuntimeError) as error:
        confirm(rig, task, messages, context={"message_limit": 10})
    assert i18n.describe(error.value)["key"] == "error.sensitive"
    assert rig.calls == []
    assert rig.progress.get("review_id") == task


@pytest.mark.parametrize("size,ok", [(20000, True), (20001, False)])
def test_review_unicode_budget(rig, size, ok):
    task = prepare(rig)
    messages = [{"side": "me", "text": "😀" * size}]
    if ok:
        confirm(rig, task, messages)
        assert rig.progress.get("context_stats")["characters"] == size
    else:
        with pytest.raises(ValueError):
            confirm(rig, task, messages)
        assert rig.calls == []


@pytest.mark.parametrize("kind", ["count", "characters", "background"])
def test_oversized_review_rejected_before_credentials_or_scanning(rig, monkeypatch, kind):
    task = prepare(rig)
    original = rig.controller.job.original_snapshot
    monkeypatch.setattr(module, "load_api_key", lambda: pytest.fail("credentials read"))
    monkeypatch.setattr(module, "compose_context", lambda *a: pytest.fail("context composed"))
    messages = [{"side": "other", "text": " "} for _ in range(20001)] if kind == "count" else [
        {"side": "other", "text": "😀" * (200001 if kind == "characters" else 1)}]
    with pytest.raises(ValueError):
        rig.controller.submit_review(task, messages, rig.settings, "en",
            context={"message_limit": 10, "background": "x" * (20001 if kind == "background" else 0)})
    assert rig.controller.job.original_snapshot is original
    assert rig.progress.get("review_id") == task
    assert rig.calls == []


def test_full_draft_capacity_can_select_last_ten(rig):
    task = prepare(rig)
    messages = [{"side": "other", "text": "😀" * 10} for _ in range(20000)]
    confirm(rig, task, messages, context={"message_limit": 10})
    assert rig.progress.get("context_stats")["characters"] == 100
    assert len(rig.calls[0][1][0].messages) == 10


@pytest.mark.parametrize("raw_only", [False, True])
def test_oversized_ocr_never_enters_editor(rig, monkeypatch, raw_only):
    rig.settings.chat_rect = Rect(0, 0, 800, 600)
    snapshot = ChatSnapshot("chat", [Message("other", "x" if raw_only else "x" * 200001)],
                            "x" * 200001 if raw_only else "")
    monkeypatch.setattr(module.workflow.AnalysisService, "capture", lambda *a, **k: snapshot)
    rig.controller.start(rig.settings, "en", review=True)
    join(rig.workers[-1])
    assert rig.progress.get("review_id") is None
    assert rig.progress.get("review_messages") == []
    assert rig.calls == []


@pytest.mark.parametrize("messages", [[], [{"side": "me", "text": " "}], [{"side": "bad", "text": "x"}], [{"side": "me", "text": 3}], {}])
def test_invalid_review_does_not_consume_draft(rig, messages):
    task = prepare(rig)
    with pytest.raises(ValueError):
        rig.controller.submit_review(task, messages, rig.settings, "en")
    assert rig.progress.get("review_id") == task
    assert rig.calls == []


def test_discard_and_new_draft_expire_previous_id(rig):
    task = prepare(rig)
    rig.controller.invalidate()
    assert rig.progress.get("review_messages") == []
    with pytest.raises(ValueError):
        confirm(rig, task)
    newer = prepare(rig)
    latest = prepare(rig)
    assert newer != latest
    with pytest.raises(ValueError):
        confirm(rig, newer)


def test_judge_without_model(rig):
    task = prepare(rig)
    rig.settings.model_profiles = []
    confirm(rig, task)
    assert [name for name, *_ in rig.calls] == ["judge"]
    assert rig.progress.get("status_message")["key"] == "review.judgedOnly"


def test_rewrite_undo_invalidate_all_scores_and_manual_rank(rig, monkeypatch):
    task = start_text(rig)
    join(rig.workers[-1])
    captured = []
    def rewrite(*args, **kwargs):
        captured.append((args, kwargs))
        return args[3] + " edited"
    monkeypatch.setattr(module, "rewrite_reply", rewrite)
    rig.settings.relationship = "changed"
    rig.settings.model_profiles[0].model = "changed"
    rig.controller.rewrite(task, 1, "shorter", 0)
    join(rig.workers[-1])
    assert rig.controller.job.replies == [REPLIES[0], REPLIES[1] + " edited", REPLIES[2]]
    assert captured[0][0][1] == "original relationship"
    assert captured[0][0][6] == "original-model"
    assert rig.progress.get("reply_histories") == [0, 1, 0]
    assert not rig.progress.get("ranking_valid")
    assert all(s["probability"] is None and not s["recommended"] for s in rig.progress.get("suggestions"))
    rig.controller.rewrite(task, 1, "gentle", 1)
    join(rig.workers[-1])
    assert rig.progress.get("reply_histories") == [0, 2, 0]
    rig.controller.undo_reply(task, 1, 2)
    assert rig.controller.job.replies[1] == REPLIES[1] + " edited"
    rig.controller.undo_reply(task, 1, 3)
    assert rig.controller.job.replies == REPLIES
    new_id = rig.controller.rank(task, 4)["task_id"]
    join(rig.workers[-1])
    assert rig.progress.get("ranking_valid")
    assert new_id != task
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank", "rank"]


@pytest.mark.parametrize("outcome", ["", "请转账", None])
def test_bad_rewrite_keeps_text_and_scores(rig, monkeypatch, outcome):
    task = start_text(rig)
    join(rig.workers[-1])
    before = rig.progress.get("suggestions")
    monkeypatch.setattr(module, "rewrite_reply", lambda *a, **k: outcome)
    rig.controller.rewrite(task, 0, "natural", 0)
    join(rig.workers[-1])
    assert rig.progress.get("suggestions") == before
    assert rig.progress.get("reply_revision") == 0
    assert rig.progress.get("retryable_stages") == ["rewrite"]
    monkeypatch.setattr(module, "rewrite_reply", lambda *a, **k: "safe revised reply")
    rig.controller.retry_rewrite(task)
    join(rig.workers[-1])
    assert rig.controller.job.replies[0] == "safe revised reply"


@pytest.mark.parametrize("raises", [True, False])
def test_cancelled_rewrite_cannot_overwrite_new_task(rig, monkeypatch, raises):
    task = start_text(rig)
    join(rig.workers[-1])
    entered, release = rig.gate(), rig.gate()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        if raises:
            raise RuntimeError("late failure")
        return "obsolete"
    monkeypatch.setattr(module, "rewrite_reply", blocked)
    rig.controller.rewrite(task, 0, "natural", 0)
    old_worker = rig.workers[-1]
    assert entered.wait(5)
    with pytest.raises(ValueError):
        rig.controller.rewrite(task, 1, "gentle", 0)
    rig.controller.cancel(task)
    assert rig.controller.job.replies == REPLIES
    start_text(rig)
    join(rig.workers[-1])
    before = rig.progress.poll()
    release.set()
    join(old_worker)
    assert rig.progress.poll() == before


def test_stale_reply_revision_rejected(rig, monkeypatch):
    task = start_text(rig)
    join(rig.workers[-1])
    monkeypatch.setattr(module, "rewrite_reply", lambda *a, **k: "new reply")
    rig.controller.rewrite(task, 0, "shorter", 0)
    join(rig.workers[-1])
    before = rig.progress.poll()
    for operation in (lambda: rig.controller.rewrite(task, 0, "gentle", 0),
                      lambda: rig.controller.rank(task, 0), lambda: rig.controller.undo_reply(task, 0, 0)):
        with pytest.raises(ValueError):
            operation()
    assert rig.progress.poll() == before
