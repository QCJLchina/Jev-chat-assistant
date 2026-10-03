"""Full-context checkpoints exercised without a desktop or model-service calls."""
import threading
from types import SimpleNamespace

import pytest

from jev_windows import task_controller as module
from jev_windows.config import AppConfig, ModelProfile
from jev_windows.input_text import parse_text
from jev_windows.i18n import describe
from jev_windows.models import Analysis, Rect
from jev_windows.state import ProgressState


REPLIES = ["first", "second", "third"]
RANKED = [{"text": text, "recommended": index == 0} for index, text in enumerate(REPLIES)]
TEXT = "\n".join(f"other: current-{index:02d}" for index in range(24))
PRIOR = "me: prior-first\nother: prior-second"
BACKGROUND = "We met at a conference."


def binding_descriptor(left=10):
    return {"version": 1, "binding_id": "d47a1e72-3703-4bd9-9caa-6840966a4738",
            "app_path": r"C:\Apps\Chat\chat.exe", "window_class": "ChatWindow",
            "relative_rect": {"left": left, "top": 20, "right": 900, "bottom": 700},
            "reference_width": 1000, "reference_height": 800, "reference_dpi": 96}


def finish(worker):
    worker.join(5)
    assert not worker.is_alive(), "controller worker did not finish"


@pytest.fixture
def rig(monkeypatch):
    workers, gates, calls, compositions = [], [], [], []
    real_thread = threading.Thread
    real_compose = module.compose_context

    def spawn(*args, **kwargs):
        worker = real_thread(*args, **kwargs)
        workers.append(worker)
        return worker

    def compose(snapshot, options):
        compositions.append((snapshot, dict(options)))
        return real_compose(snapshot, options)

    def stage(name, result):
        def call(*args, **kwargs):
            calls.append((name, args[0], args[1], kwargs["cancel_event"]))
            return result
        return call

    monkeypatch.setattr(module.threading, "Thread", spawn)
    monkeypatch.setattr(module, "compose_context", compose)
    monkeypatch.setattr(module, "load_api_key", lambda: "judge-key")
    monkeypatch.setattr(module, "load_model_api_key", lambda _: "model-key")
    monkeypatch.setattr(module.workflow, "judge", stage("judge", Analysis(true_intent="greeting")))
    monkeypatch.setattr(module.workflow, "generate_suggestions", stage("generate", REPLIES))
    monkeypatch.setattr(module.workflow, "recommend_replies", stage("rank", RANKED))
    settings = AppConfig(selection_mode="screen", chat_rect=Rect(0, 0, 1000, 800),
                         relationship="original relationship",
                         model_profiles=[ModelProfile("test", "Test", "https://model.test", "model")],
                         active_model_id="test")
    progress = ProgressState("en")

    def gate():
        event = threading.Event()
        gates.append(event)
        return event

    result = SimpleNamespace(settings=settings, progress=progress,
                             controller=module.AnalysisController(progress), workers=workers,
                             calls=calls, compositions=compositions, gate=gate)
    yield result
    for event in gates:
        event.set()
    for worker in workers:
        finish(worker)


def start(rig, **kwargs):
    return rig.controller.start(rig.settings, "en", **kwargs)["task_id"]


def assert_shared_context(rig, expected):
    assert rig.calls
    effective = rig.controller.job.snapshot
    assert all(snapshot is effective for _, snapshot, _, _ in rig.calls)
    assert [(m.side, m.text) for m in effective.messages] == [(m.side, m.text) for m in expected]
    assert effective.background == BACKGROUND
    assert all(relationship == "original relationship" for _, _, relationship, _ in rig.calls)
    assert rig.progress.get("preview") == [{"side": m.side, "text": m.text} for m in expected]
    assert rig.progress.get("context_stats") == {
        "total_messages": 26, "used_messages": len(expected),
        "characters": sum(len(m.text) for m in expected) + len(BACKGROUND),
        "message_limit": rig.controller.job.context_options["message_limit"],
        "omitted_messages": 26 - len(expected)}


@pytest.mark.parametrize("limit", [None, 10, 20, 50])
def test_context_is_frozen_before_capture_and_shared_by_all_stages(rig, monkeypatch, limit):
    entered, release = rig.gate(), rig.gate()
    source = parse_text(TEXT)

    def capture(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return source

    monkeypatch.setattr(module.workflow.AnalysisService, "capture", capture)
    options = {"prior_text": PRIOR, "background": BACKGROUND, "message_limit": limit}
    start(rig, context=options)
    assert entered.wait(5)
    options.update(prior_text="other: changed", background="changed", message_limit=10)
    rig.settings.relationship = "changed relationship"
    release.set()
    finish(rig.workers[-1])
    merged = [*parse_text(PRIOR).messages, *source.messages]
    selected = merged if limit is None else merged[-limit:]
    assert_shared_context(rig, selected)
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank"]
    assert len(rig.compositions) == 1
    assert source.background == "" and len(source.messages) == 24
    assert rig.controller.job.context_prepared


def test_default_context_sends_more_than_ten_messages_to_every_stage(rig):
    start(rig, text=TEXT)
    finish(rig.workers[-1])
    assert [name for name, *_ in rig.calls] == ["judge", "generate", "rank"]
    assert all(len(snapshot.messages) == 24 for _, snapshot, _, _ in rig.calls)
    assert all(snapshot is rig.controller.job.snapshot for _, snapshot, _, _ in rig.calls)
    assert rig.progress.get("context_stats")["message_limit"] is None


@pytest.mark.parametrize("stage, attribute", [("judge", "judge"), ("generate", "generate_suggestions"),
                                               ("rank", "recommend_replies")])
def test_repeated_stage_retries_reuse_snapshot_without_composing_or_duplicating_prior(rig, monkeypatch, stage, attribute):
    original = getattr(module.workflow, attribute)
    failed_snapshots = []

    def fail_twice(*args, **kwargs):
        if len(failed_snapshots) < 2:
            failed_snapshots.append(args[0])
            raise RuntimeError("temporary model failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module.workflow, attribute, fail_twice)
    task_id = start(rig, text=TEXT, context={"prior_text": PRIOR, "background": BACKGROUND})
    finish(rig.workers[-1])
    effective = rig.controller.job.snapshot
    for _ in range(2):
        assert rig.progress.get("failed_stage") == stage
        task_id = rig.controller.retry(task_id, stage)["task_id"]
        finish(rig.workers[-1])
    assert all(snapshot is effective for snapshot in failed_snapshots)
    assert len(rig.compositions) == 1
    assert_shared_context(rig, [*parse_text(PRIOR).messages, *parse_text(TEXT).messages])
    assert sum(m.text == "prior-first" for m in effective.messages) == 1
    assert rig.progress.get("suggestions") == RANKED
    assert rig.progress.get("retryable_stages") == []


@pytest.mark.parametrize("stage, attribute", [("judge", "judge"), ("generate", "generate_suggestions"),
                                               ("rank", "recommend_replies")])
def test_cancel_and_retry_does_not_recompose_or_accept_late_result(rig, monkeypatch, stage, attribute):
    entered, release = rig.gate(), rig.gate()
    original = getattr(module.workflow, attribute)
    first = True

    def block_once(*args, **kwargs):
        nonlocal first
        if first:
            first = False
            entered.set()
            assert release.wait(5)
            assert kwargs["cancel_event"].is_set()
        return original(*args, **kwargs)

    monkeypatch.setattr(module.workflow, attribute, block_once)
    task_id = start(rig, text=TEXT, context={"prior_text": PRIOR, "background": BACKGROUND})
    assert entered.wait(5)
    effective = rig.controller.job.snapshot
    rig.controller.cancel(task_id)
    cancelled = rig.progress.poll()
    release.set()
    finish(rig.workers[-1])
    assert rig.progress.poll() == cancelled
    new_id = rig.controller.retry(task_id, stage)["task_id"]
    finish(rig.workers[-1])
    assert new_id != task_id and rig.controller.job.snapshot is effective
    assert len(rig.compositions) == 1
    assert_shared_context(rig, [*parse_text(PRIOR).messages, *parse_text(TEXT).messages])
    assert rig.progress.get("suggestions") == RANKED


@pytest.mark.parametrize("location", ["dropped_current", "dropped_prior", "background"])
def test_sensitive_input_outside_selected_range_prevents_every_outbound_stage(rig, location):
    text = TEXT
    options = {"message_limit": 10}
    if location == "dropped_current":
        text = "other: 请付款\n" + text
    elif location == "dropped_prior":
        options["prior_text"] = "other: 请付款"
    else:
        options["background"] = "需要付款"
    start(rig, text=text, context=options)
    finish(rig.workers[-1])
    state = rig.progress.poll()
    assert state["phase"] == "error"
    assert state["error_message"] == {"key": "error.sensitive", "params": {"word": "付款"}}
    assert state["analysis"] is None and state["suggestions"] == []
    assert rig.calls == []


@pytest.mark.parametrize("retry_stage, attribute", [("judge", "judge"), ("generate", "generate_suggestions")])
def test_capture_retry_resolves_again_but_model_retry_reuses_capture(rig, monkeypatch, retry_stage, attribute):
    descriptor = binding_descriptor()
    resolutions, frames, validations = [], [], []
    region = Rect(200, 300, 1200, 1100)

    class BindingService:
        def resolve(self, value):
            resolutions.append(dict(value))
            if len(resolutions) == 1:
                raise RuntimeError("window temporarily unavailable")
            return SimpleNamespace(rect=region, title="resolved window")

        def validate_after(self, value, resolved):
            validations.append((dict(value), resolved.rect))

    rig.settings.selection_mode = "window"
    rig.settings.window_binding = descriptor
    rig.controller.binding_service = BindingService()
    monkeypatch.setattr(module.workflow, "capture_without_overlay", lambda hide, show, capture: capture())

    def screenshot(rect):
        frames.append(rect)
        return object()

    def ocr(rect, capture_frame):
        image, title = capture_frame(rect)
        assert image is not None and title == "resolved window" and rect == region
        return parse_text(TEXT)

    monkeypatch.setattr(module.workflow, "screenshot", screenshot)
    monkeypatch.setattr(module.workflow, "capture_desktop_chat", ocr)
    original = getattr(module.workflow, attribute)
    attempted = []

    def fail_once(*args, **kwargs):
        attempted.append(args[0])
        if len(attempted) == 1:
            raise RuntimeError("temporary model failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(module.workflow, attribute, fail_once)
    task_id = start(rig, context={"prior_text": PRIOR, "background": BACKGROUND})
    finish(rig.workers[-1])
    assert rig.progress.get("failed_stage") == "capture" and rig.calls == []
    assert len(rig.compositions) == 0
    task_id = rig.controller.retry(task_id, "capture")["task_id"]
    finish(rig.workers[-1])
    assert rig.progress.get("failed_stage") == retry_stage
    effective = rig.controller.job.snapshot
    rig.settings.window_binding = {"test": "changed binding"}
    rig.controller.retry(task_id, retry_stage)
    finish(rig.workers[-1])
    assert resolutions == [descriptor, descriptor]
    assert frames == [region] and validations == [(descriptor, region)]
    assert len(rig.compositions) == 1
    assert attempted == [effective, effective]
    assert_shared_context(rig, [*parse_text(PRIOR).messages, *parse_text(TEXT).messages])


@pytest.mark.parametrize("same_target", [True, False])
def test_capture_retry_accepts_reselected_binding_only_for_same_target_and_preserves_frozen_inputs(rig, monkeypatch, same_target):
    descriptor = binding_descriptor()
    replacement = binding_descriptor(left=50)
    comparisons, captures = [], []
    entered, release = rig.gate(), rig.gate()

    class BindingService:
        def same_target(self, old, new):
            comparisons.append((old, new))
            return same_target

    rig.controller.binding_service = BindingService()
    rig.settings.selection_mode = "window"
    rig.settings.window_binding = descriptor

    def capture(service, area):
        captures.append(service.settings.window_binding)
        if len(captures) == 1:
            raise RuntimeError("window resized; reselect region")
        entered.set()
        assert release.wait(5)
        return parse_text(TEXT)

    monkeypatch.setattr(module.workflow.AnalysisService, "capture", capture)
    options = {"prior_text": PRIOR, "background": BACKGROUND, "message_limit": None}
    task_id = start(rig, context=options)
    finish(rig.workers[-1])
    old_job = rig.controller.job
    rig.settings.relationship = "changed relationship"
    rig.settings.model_profiles[0].model = "changed-model"
    options.update(prior_text="other: changed", background="changed", message_limit=10)
    new_id = rig.controller.retry(task_id, "capture", selected_binding=replacement)["task_id"]
    assert entered.wait(5)
    # Caller mutation after retry must not alter the replacement frozen on job.
    replacement["relative_rect"]["left"] = 99
    release.set()
    finish(rig.workers[-1])
    new_job = rig.controller.job
    assert new_id != task_id
    assert old_job.settings.window_binding == descriptor
    assert captures == [descriptor, binding_descriptor(left=50) if same_target else descriptor]
    assert comparisons[0][0] == descriptor
    assert new_job.settings.model_profiles[0].model == "model"
    assert new_job.profile.model == "model" and new_job.key == "judge-key" and new_job.model_key == "model-key"
    assert new_job.context_options == {"prior_text": PRIOR, "background": BACKGROUND, "message_limit": None}
    assert len(rig.compositions) == 1
    assert_shared_context(rig, [*parse_text(PRIOR).messages, *parse_text(TEXT).messages])


def test_invalidation_after_target_change_expires_failed_capture_job_and_clears_context(rig, monkeypatch):
    def failed_capture(*args, **kwargs):
        raise RuntimeError("window unavailable")

    monkeypatch.setattr(module.workflow.AnalysisService, "capture", failed_capture)
    task_id = start(rig, context={"prior_text": PRIOR, "background": BACKGROUND})
    finish(rig.workers[-1])
    old_job = rig.controller.job
    assert rig.progress.get("failed_stage") == "capture"
    rig.controller.invalidate()
    state = rig.progress.poll()
    assert old_job.cancel.is_set() and rig.controller.job is None
    assert state["task_id"] is None and state["context_stats"] is None
    assert state["preview"] == [] and state["analysis"] is None and state["suggestions"] == []
    assert state["failed_stage"] is None and state["retryable_stages"] == []
    with pytest.raises(ValueError) as caught:
        rig.controller.retry(task_id, "capture", selected_binding=binding_descriptor(left=50))
    assert describe(caught.value)["key"] == "feature.taskExpired"
    assert rig.progress.poll() == state
    assert len(rig.workers) == 1 and rig.calls == []
