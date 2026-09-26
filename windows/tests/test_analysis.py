"""The analysis workflow is now testable without pywebview or a real screen."""
import pytest

from jev_windows import analysis, i18n
from jev_windows.config import AppConfig, ModelProfile
from jev_windows.models import Analysis, ChatSnapshot, Message, Rect
from jev_windows.state import ProgressState


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setattr("jev_windows.config.config_dir", lambda: tmp_path)
    return AppConfig(language="zh-CN", chat_rect=Rect(0, 0, 800, 600))


def _snapshot(text="晚上七点一起吃饭吗？"):
    return ChatSnapshot("朋友", [Message("other", text)], text)


def test_start_analysis_rejects_when_busy(settings):
    progress = ProgressState("zh-CN")
    progress.update(phase="judging")
    with pytest.raises(ValueError) as caught:
        analysis.start_analysis(settings, progress, "zh-CN")
    assert i18n.describe(caught.value)["key"] == "error.busy"


def test_start_analysis_requires_a_selected_area(settings):
    settings.chat_rect = None
    progress = ProgressState("zh-CN")
    with pytest.raises(ValueError) as caught:
        analysis.start_analysis(settings, progress, "zh-CN")
    assert i18n.describe(caught.value)["key"] == "error.selectFirst"


def test_start_analysis_rejects_legacy_wechat_area(settings):
    settings.chat_rect_mode = "wechat-client"
    progress = ProgressState("zh-CN")
    with pytest.raises(ValueError) as caught:
        analysis.start_analysis(settings, progress, "zh-CN")
    assert i18n.describe(caught.value)["key"] == "error.legacyArea"


def test_start_analysis_requires_a_jev_key(settings, monkeypatch):
    monkeypatch.setattr(analysis, "load_api_key", lambda: "")
    progress = ProgressState("zh-CN")
    with pytest.raises(ValueError) as caught:
        analysis.start_analysis(settings, progress, "zh-CN")
    assert i18n.describe(caught.value)["key"] == "error.jevKey"


def test_missing_key_does_not_mutate_progress_phase(settings, monkeypatch):
    """Validation failures must not leave the UI stuck in a working phase."""
    monkeypatch.setattr(analysis, "load_api_key", lambda: "")
    progress = ProgressState("zh-CN")
    with pytest.raises(ValueError):
        analysis.start_analysis(settings, progress, "zh-CN")
    assert progress.phase() == "idle"


def test_safety_block_lands_in_error_state_without_leaking_chat_text(settings, monkeypatch):
    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "")
    monkeypatch.setattr(analysis, "find_wechat_window", lambda: None)
    monkeypatch.setattr(
        analysis, "capture_desktop_chat",
        lambda area, capture_frame: _snapshot("请点收款码"),
    )
    progress = ProgressState("zh-CN")
    service = analysis.AnalysisService(settings, progress)
    service.run("zh-CN")
    current = progress.poll()
    assert current["phase"] == "error"
    assert current["error_message"]["key"] == "error.sensitive"


def test_allowlist_mismatch_is_reported_with_the_window_title(settings, monkeypatch):
    settings.allowed_titles = ["工作群"]
    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "")
    monkeypatch.setattr(
        analysis, "capture_desktop_chat",
        lambda area, capture_frame: ChatSnapshot("闲聊群", [Message("other", "你好")], "你好"),
    )
    progress = ProgressState("zh-CN")
    analysis.AnalysisService(settings, progress).run("zh-CN")
    current = progress.poll()
    assert current["error_message"]["key"] == "error.allowlist"
    assert current["error_message"]["params"]["name"] == "闲聊群"


def test_analysis_without_a_model_profile_stops_after_judging(settings, monkeypatch):
    """No reply model configured means no suggestions, and phase returns to idle."""
    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "")
    monkeypatch.setattr(
        analysis, "capture_desktop_chat",
        lambda area, capture_frame: _snapshot(),
    )
    monkeypatch.setattr(analysis, "judge", lambda *a, **k: Analysis(true_intent="request_action"))
    progress = ProgressState("zh-CN")
    analysis.AnalysisService(settings, progress).run("zh-CN")
    current = progress.poll()
    assert current["phase"] == "idle"
    assert current["analysis"]["true_intent"] == "request_action"
    assert current["suggestions"] == []


def test_full_workflow_ranks_three_suggestions(settings, monkeypatch):
    settings.model_profiles = [ModelProfile(id="m1", name="M", base_url="https://x.test", model="m")]
    settings.active_model_id = "m1"
    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "model-key")
    monkeypatch.setattr(analysis, "capture_desktop_chat", lambda area, capture_frame: _snapshot())
    monkeypatch.setattr(analysis, "judge", lambda *a, **k: Analysis(true_intent="request_action"))
    monkeypatch.setattr(analysis, "generate_suggestions", lambda *a, **k: ["a", "b", "c"])
    monkeypatch.setattr(analysis, "recommend_replies", lambda *a, **k: [
        {"text": "a", "probability": 0.7, "confidence": 0.7, "recommended": True},
        {"text": "b", "probability": 0.2, "confidence": None, "recommended": False},
        {"text": "c", "probability": 0.1, "confidence": None, "recommended": False},
    ])
    progress = ProgressState("zh-CN")
    analysis.AnalysisService(settings, progress).run("zh-CN")
    current = progress.poll()
    assert current["phase"] == "idle"
    assert [item["text"] for item in current["suggestions"]] == ["a", "b", "c"]
    assert current["suggestions"][0]["recommended"] is True


def test_ranking_failure_still_returns_unranked_candidates(settings, monkeypatch):
    """A Jev ranking outage must not throw away the generated replies."""
    settings.model_profiles = [ModelProfile(id="m1", name="M", base_url="https://x.test", model="m")]
    settings.active_model_id = "m1"
    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "model-key")
    monkeypatch.setattr(analysis, "capture_desktop_chat", lambda area, capture_frame: _snapshot())
    monkeypatch.setattr(analysis, "judge", lambda *a, **k: Analysis())

    def boom(*args, **kwargs):
        raise RuntimeError("rank down")
    monkeypatch.setattr(analysis, "generate_suggestions", lambda *a, **k: ["a", "b", "c"])
    monkeypatch.setattr(analysis, "recommend_replies", boom)
    progress = ProgressState("zh-CN")
    analysis.AnalysisService(settings, progress).run("zh-CN")
    current = progress.poll()
    assert [item["text"] for item in current["suggestions"]] == ["a", "b", "c"]
    assert all(item["probability"] is None for item in current["suggestions"])
    assert current["phase"] == "idle"


def test_capture_hides_and_restores_the_window_around_ocr(settings, monkeypatch):
    events = []

    class FakeWindow:
        def hide(self):
            events.append("hide")

        def show(self):
            events.append("show")

        def restore(self):
            events.append("restore")

    monkeypatch.setattr(analysis, "load_api_key", lambda: "key")
    monkeypatch.setattr(analysis, "load_model_api_key", lambda _id: "")
    monkeypatch.setattr(analysis, "judge", lambda *a, **k: Analysis())

    def fake_capture(area, capture_frame):
        capture_frame(area)
        return _snapshot()

    monkeypatch.setattr(analysis, "capture_desktop_chat", fake_capture)
    monkeypatch.setattr(analysis, "screenshot", lambda area: object())
    monkeypatch.setattr(analysis, "window_title_at", lambda x, y: "标题")
    progress = ProgressState("zh-CN")
    service = analysis.AnalysisService(settings, progress, FakeWindow())
    service.run("zh-CN")
    assert events == ["hide", "show", "restore"]
