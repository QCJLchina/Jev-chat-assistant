"""Exercise controller checkpoints and races without credentials, APIs or a screen."""
import threading
from types import SimpleNamespace

import pytest

from jev_windows import i18n, task_controller as module, update_service
from jev_windows.config import AppConfig, ModelProfile
from jev_windows.models import Analysis, ChatSnapshot, Message, Rect
from jev_windows.state import ProgressState


TIMEOUT = 5
REPLIES = ["你好呀", "最近怎么样", "很高兴见到你"]
RANKED = [{"text": text, "probability": 0.8 if index == 0 else 0.1,
           "confidence": 0.9, "recommended": index == 0}
          for index, text in enumerate(REPLIES)]


def wait(event):
    assert event.wait(TIMEOUT), "worker did not reach the expected barrier"


def join(worker):
    worker.join(TIMEOUT)
    assert not worker.is_alive(), "controller worker did not finish"


@pytest.fixture
def rig(monkeypatch):
    workers, gates, calls = [], [], []
    real_thread = threading.Thread

    def spawn(*args, **kwargs):
        worker = real_thread(*args, **kwargs)
        workers.append(worker)
        return worker

    monkeypatch.setattr(module.threading, "Thread", spawn)
    monkeypatch.setattr(module, "load_api_key", lambda: "judge-key")
    monkeypatch.setattr(module, "load_model_api_key", lambda _id: "model-key")

    def judge(*args, **kwargs):
        calls.append(("judge", args, kwargs))
        return Analysis(true_intent="greeting")

    def generate(*args, **kwargs):
        calls.append(("generate", args, kwargs))
        return list(REPLIES)

    def rank(*args, **kwargs):
        calls.append(("rank", args, kwargs))
        return list(RANKED)

    monkeypatch.setattr(module.workflow, "judge", judge)
    monkeypatch.setattr(module.workflow, "generate_suggestions", generate)
    monkeypatch.setattr(module.workflow, "recommend_replies", rank)
    settings = AppConfig(
        language="zh-CN", relationship="original relationship",
        model_profiles=[ModelProfile("test", "Test", "https://model.test", "original-model", 123, "openai-chat")],
        active_model_id="test",
    )
    progress = ProgressState("zh-CN")

    def gate():
        event = threading.Event()
        gates.append(event)
        return event

    result = SimpleNamespace(settings=settings, progress=progress,
                             controller=module.AnalysisController(progress),
                             workers=workers, calls=calls, gate=gate)
    yield result
    # Even a failed assertion must release/join workers before monkeypatch undo.
    for event in gates:
        event.set()
    for worker in workers:
        join(worker)


def start_text(rig, **kwargs):
    return rig.controller.start(rig.settings, "zh-CN", text="对方：你好", preferences=kwargs.get("preferences", {}))["task_id"]


def snapshot(title="工作群"):
    return ChatSnapshot(title, [Message("other", "你好")], "你好")


def test_text_needs_no_capture_rect_and_bypasses_title_whitelist(rig, monkeypatch):
    rig.settings.allowed_titles = ["a title absent from pasted text"]

    def unexpected_capture(*args, **kwargs):
        pytest.fail("pasted text must never capture the desktop")

    monkeypatch.setattr(module.workflow.AnalysisService, "capture", unexpected_capture)
    task_id = start_text(rig)
    join(rig.workers[-1])
    state = rig.progress.poll()
    assert state["task_id"] == task_id
    assert state["input_source"] == "text"
    assert state["phase"] == "idle"
    assert state["error"] == ""
    assert state["preview"] == [{"side": "other", "text": "你好"}]
    assert state["suggestions"] == RANKED
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank"]


def test_safety_scans_raw_text_including_discarded_first_message(rig):
    text = "对方：请点收款码\n" + "\n".join(f"对方：你好，今天第{i}次聊天" for i in range(10))
    parsed = module.parse_text(text)
    assert len(parsed.messages) == 11
    assert all("收款码" not in message.text for message in parsed.messages[-10:])
    assert parsed.raw_text == text
    rig.controller.start(rig.settings, "zh-CN", text=text, preferences={}, context={"message_limit": 10})
    join(rig.workers[-1])
    state = rig.progress.poll()
    assert state["phase"] == "error"
    assert state["error_message"]["key"] == "error.sensitive"
    assert text not in state["error"]
    assert state["analysis"] is None
    assert state["suggestions"] == []
    assert rig.calls == []  # In particular, never send the trimmed chat to judge.


def test_calibration_phase_blocks_analysis_without_mutating_progress(rig):
    rig.progress.update(phase="calibrating")
    before = rig.progress.poll()
    with pytest.raises(ValueError) as error:
        start_text(rig)
    assert i18n.describe(error.value)["key"] == "error.busy"
    assert rig.progress.poll() == before
    assert rig.workers == []
    assert rig.calls == []


@pytest.mark.parametrize("winner", ["update", "analysis"])
def test_update_and_analysis_atomically_reserve_shared_progress(rig, monkeypatch, winner):
    """Pause after the winning phase read: a competing reservation must wait."""
    phase_read, unlock, contender_waiting = rig.gate(), rig.gate(), rig.gate()
    worker_entered, finish_worker = rig.gate(), rig.gate()
    real_lock = threading.RLock()

    class ObservedLock:
        def __enter__(self):
            if threading.current_thread().name == "contender":
                contender_waiting.set()
            real_lock.acquire()

        def __exit__(self, *args):
            real_lock.release()

    monkeypatch.setattr(rig.progress, "_lock", ObservedLock())
    real_phase = rig.progress.phase
    paused = False

    def phase():
        nonlocal paused
        value = real_phase()
        if threading.current_thread().name == "winner" and not paused:
            paused = True
            phase_read.set()
            wait(unlock)
        return value

    monkeypatch.setattr(rig.progress, "phase", phase)
    updater = update_service.UpdateService(rig.progress)
    updater.info = {"download_url": "https://release.test/update.zip", "latest_version": "test"}

    def pending_download(*args, **kwargs):
        worker_entered.set()
        wait(finish_worker)

    def pending_judge(*args, **kwargs):
        worker_entered.set()
        wait(finish_worker)
        return Analysis(true_intent="greeting")

    # Keep the real download reservation; avoid network, staging and temp files.
    monkeypatch.setattr(updater, "_download_worker", pending_download)
    monkeypatch.setattr(module.workflow, "judge", pending_judge)
    outcomes = {}

    def invoke(operation):
        try:
            outcomes[operation] = updater.download() if operation == "update" else start_text(rig)
        except Exception as error:
            outcomes[operation] = error

    loser = "analysis" if winner == "update" else "update"
    first = threading.Thread(target=invoke, args=(winner,), name="winner", daemon=True)
    first.start()
    wait(phase_read)
    second = threading.Thread(target=invoke, args=(loser,), name="contender", daemon=True)
    second.start()
    wait(contender_waiting)
    assert outcomes == {}  # The winner still holds the reservation lock.
    unlock.set()
    join(first)
    join(second)
    wait(worker_entered)
    assert not isinstance(outcomes[winner], Exception)
    assert isinstance(outcomes[loser], ValueError)
    assert i18n.describe(outcomes[loser])["key"] == "error.busy"
    assert rig.progress.phase() == ("updating" if winner == "update" else "judging")
    if winner == "update":
        assert rig.controller.job is None
        assert updater.thread is not None
        assert rig.calls == []
    else:
        assert rig.progress.get("task_id") == outcomes["analysis"]
        assert updater.thread is None
    finish_worker.set()
    for worker in rig.workers:
        join(worker)


def test_settings_preferences_profile_and_keys_are_frozen_at_start(rig, monkeypatch):
    entered, release = rig.gate(), rig.gate()
    original_judge = module.workflow.judge

    def blocked_judge(*args, **kwargs):
        entered.set()
        wait(release)
        return original_judge(*args, **kwargs)

    monkeypatch.setattr(module.workflow, "judge", blocked_judge)
    preferences = {"length": "detailed", "style": "gentle", "language": "interface"}
    start_text(rig, preferences=preferences)
    wait(entered)
    rig.settings.relationship = "changed relationship"
    rig.settings.model_profiles[0].model = "changed-model"
    rig.settings.model_profiles[0].base_url = "https://changed.test"
    rig.settings.model_profiles[0].max_tokens = 999
    rig.settings.active_model_id = "missing"
    rig.settings.reply_preferences["style"] = "formal"
    preferences.update(length="short", style="direct", language="en")
    monkeypatch.setattr(module, "load_api_key", lambda: "changed-key")
    monkeypatch.setattr(module, "load_model_api_key", lambda _id: "changed-model-key")
    release.set()
    join(rig.workers[-1])
    (_, judge_args, judge_kwargs), (_, generate_args, generate_kwargs), (_, rank_args, rank_kwargs) = rig.calls
    assert judge_args[1:] == ("original relationship", "judge-key")
    assert generate_args[1] == "original relationship"
    assert generate_args[3:] == ("model-key", "original-model", "https://model.test", 123, "openai-chat")
    assert generate_kwargs["preferences"] == {"length": "detailed", "style": "gentle", "language": "zh-CN"}
    assert rank_args[1:] == ("original relationship", REPLIES, "judge-key")
    assert judge_kwargs["cancel_event"] is rank_kwargs["cancel_event"]
    assert rig.progress.poll()["suggestions"] == RANKED


@pytest.mark.parametrize("failed_stage,expected_calls", [
    ("judge", ["judge", "judge", "generate", "rank"]),
    ("generate", ["judge", "generate", "generate", "rank"]),
    ("rank", ["judge", "generate", "rank", "rank"]),
])
def test_retry_reuses_successful_checkpoints(rig, monkeypatch, failed_stage, expected_calls):
    rig.settings.chat_rect = Rect(0, 0, 800, 600)
    captures = []

    def capture(*args, **kwargs):
        captures.append(True)
        return snapshot()

    monkeypatch.setattr(module.workflow.AnalysisService, "capture", capture)
    attribute = {"judge": "judge", "generate": "generate_suggestions", "rank": "recommend_replies"}[failed_stage]
    original = getattr(module.workflow, attribute)
    attempts = 0

    def fail_once(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            rig.calls.append((failed_stage, args, kwargs))
            raise RuntimeError("temporary outage")
        return original(*args, **kwargs)

    monkeypatch.setattr(module.workflow, attribute, fail_once)
    preferences = {"length": "detailed", "style": "gentle", "language": "interface"}
    old_id = rig.controller.start(rig.settings, "zh-CN", preferences=preferences)["task_id"]
    join(rig.workers[-1])
    failed = rig.progress.poll()
    assert failed["failed_stage"] == failed_stage
    assert failed["retryable_stages"] == [failed_stage]
    assert failed["phase"] == ("idle" if failed_stage == "rank" else "error")
    if failed_stage != "judge":
        assert failed["analysis"]["true_intent"] == "greeting"
    if failed_stage == "rank":
        assert [item["text"] for item in failed["suggestions"]] == REPLIES
        assert all(item["probability"] is None for item in failed["suggestions"])
    # Retrying a checkpoint must retain the original inputs and credentials.
    rig.settings.relationship = "changed relationship"
    rig.settings.model_profiles[0].model = "changed-model"
    rig.settings.reply_preferences["style"] = "direct"
    preferences.update(length="short", style="formal", language="en")
    monkeypatch.setattr(module, "load_api_key", lambda: "changed-key")
    monkeypatch.setattr(module, "load_model_api_key", lambda _id: "changed-model-key")
    new_id = rig.controller.retry(old_id, failed_stage)["task_id"]
    join(rig.workers[-1])
    assert new_id != old_id
    assert captures == [True]
    assert [name for name, *_ in rig.calls] == expected_calls
    for name, args, kwargs in rig.calls:
        assert args[1] == "original relationship"
        if name == "generate":
            assert args[3:5] == ("model-key", "original-model")
            assert kwargs["preferences"] == {"length": "detailed", "style": "gentle", "language": "zh-CN"}
        else:
            assert args[-1] == "judge-key"
    state = rig.progress.poll()
    assert state["suggestions"] == RANKED
    assert state["error"] == ""
    assert state["failed_stage"] is None
    assert state["retryable_stages"] == []


@pytest.mark.parametrize("stage", ["judge", "generate", "rank"])
@pytest.mark.parametrize("old_raises", [False, True])
def test_cancelled_worker_cannot_overwrite_new_run(rig, monkeypatch, stage, old_raises):
    entered, release = rig.gate(), rig.gate()
    attribute = {"judge": "judge", "generate": "generate_suggestions", "rank": "recommend_replies"}[stage]
    original = getattr(module.workflow, attribute)
    first = True
    old_cancel_events = []

    def block_old(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            if "cancel_event" in kwargs:
                old_cancel_events.append(kwargs["cancel_event"])
            entered.set()
            wait(release)
            if old_raises:
                raise RuntimeError("late old failure")
            if stage == "judge":
                return Analysis(true_intent="obsolete")
            if stage == "generate":
                return ["obsolete reply"]
            return [{"text": "obsolete ranking"}]
        return original(*args, **kwargs)

    monkeypatch.setattr(module.workflow, attribute, block_old)
    old_id = start_text(rig)
    old_worker = rig.workers[-1]
    wait(entered)
    assert rig.controller.cancel(old_id) == {"ok": True}
    cancelled = rig.progress.poll()
    assert cancelled["phase"] == "idle"
    assert cancelled["failed_stage"] == stage
    assert cancelled["retryable_stages"] == [stage]
    assert all(event.is_set() for event in old_cancel_events)
    new_id = start_text(rig)
    join(rig.workers[-1])
    complete = rig.progress.poll()
    assert complete["task_id"] == new_id != old_id
    assert complete["analysis"]["true_intent"] == "greeting"
    assert complete["suggestions"] == RANKED
    release.set()
    join(old_worker)
    assert rig.progress.poll() == complete  # Includes revision: no stale publication.


def test_stale_ids_and_invalid_retry_leave_current_run_untouched(rig, monkeypatch):
    entered, retry_entered, release = rig.gate(), rig.gate(), rig.gate()
    attempts = 0

    def blocked(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        (entered if attempts == 1 else retry_entered).set()
        wait(release)
        return Analysis()

    monkeypatch.setattr(module.workflow, "judge", blocked)
    old_id = start_text(rig)
    wait(entered)
    with pytest.raises(ValueError) as error:
        start_text(rig)
    assert i18n.describe(error.value)["key"] == "error.busy"
    rig.controller.cancel(old_id)
    state = rig.progress.poll()
    with pytest.raises(ValueError) as error:
        rig.controller.retry(old_id, "rank")
    assert i18n.describe(error.value)["key"] == "feature.invalidRetry"
    assert rig.progress.poll() == state
    new_id = rig.controller.retry(old_id, "judge")["task_id"]
    wait(retry_entered)
    state = rig.progress.poll()
    for operation in (lambda: rig.controller.cancel(old_id),
                      lambda: rig.controller.retry(old_id, "judge"),
                      lambda: rig.controller.cancel("unknown")):
        with pytest.raises(ValueError) as error:
            operation()
        assert i18n.describe(error.value)["key"] == "feature.taskExpired"
        assert rig.progress.poll() == state
    assert new_id != old_id
    release.set()
    for worker in rig.workers:
        join(worker)
    with pytest.raises(ValueError) as error:
        rig.controller.cancel(new_id)
    assert i18n.describe(error.value)["key"] == "feature.taskInactive"


def test_desktop_title_whitelist_blocks_judgment(rig, monkeypatch):
    rig.settings.chat_rect = Rect(0, 0, 800, 600)
    rig.settings.allowed_titles = ["工作群"]
    monkeypatch.setattr(module.workflow.AnalysisService, "capture", lambda *a, **k: snapshot("闲聊群"))
    rig.controller.start(rig.settings, "zh-CN")
    join(rig.workers[-1])
    state = rig.progress.poll()
    assert state["phase"] == "error"
    assert state["error_message"]["key"] == "error.allowlist"
    assert state["error_message"]["params"]["name"] == "闲聊群"
    assert rig.calls == []


@pytest.mark.parametrize("old_capture_raises", [False, True])
def test_capture_serialized_and_window_restored_before_next_capture(rig, monkeypatch, old_capture_raises):
    rig.settings.chat_rect = Rect(0, 0, 800, 600)
    entered, release, waiting = rig.gate(), rig.gate(), rig.gate()
    events = []
    lock = threading.RLock()

    class ObservedLock:
        attempts = 0

        def __enter__(self):
            self.attempts += 1
            if self.attempts == 2:
                waiting.set()
            lock.acquire()

        def __exit__(self, *args):
            lock.release()

    rig.controller.capture_lock = ObservedLock()

    class Window:
        def hide(self):
            events.append("hide")

        def show(self):
            events.append("show")

        def restore(self):
            events.append("restore")

    frames = 0

    def screenshot(area):
        nonlocal frames
        frames += 1
        events.append("frame")
        assert area == rig.settings.chat_rect
        if frames == 1:
            entered.set()
            wait(release)
            if old_capture_raises:
                raise RuntimeError("old screenshot failed")
        return object()

    def capture(area, capture_frame):
        capture_frame(area)
        return snapshot()

    monkeypatch.setattr(module.workflow, "screenshot", screenshot)
    monkeypatch.setattr(module.workflow, "window_title_at", lambda *a: "工作群")
    monkeypatch.setattr(module.workflow, "capture_desktop_chat", capture)
    window = Window()
    old_id = rig.controller.start(rig.settings, "zh-CN", window=window)["task_id"]
    wait(entered)
    rig.controller.cancel(old_id)
    new_id = rig.controller.start(rig.settings, "zh-CN", window=window)["task_id"]
    wait(waiting)
    assert events == ["hide", "frame"]
    assert rig.progress.poll()["phase"] == "capturing"
    release.set()
    for worker in rig.workers:
        join(worker)
    assert events == ["hide", "frame", "show", "restore"] * 2
    state = rig.progress.poll()
    assert state["task_id"] == new_id
    assert state["phase"] == "idle"
    assert state["error"] == ""
    assert state["suggestions"] == RANKED
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank"]
