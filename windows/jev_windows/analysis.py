"""The analyze workflow: capture -> safety -> judge -> generate -> rank.

Extracted from the desktop bridge so the multi-step orchestration is readable on
its own and can be exercised without pywebview.
"""
from __future__ import annotations

import threading

from .capture import capture_chat, capture_desktop_chat
from .config import AppConfig, load_api_key, load_model_api_key
from .deepseek_client import generate_suggestions
from .i18n import msg, translate
from .jev_api import judge, recommend_replies
from .models import Analysis, Rect
from .safety import assert_safe_chat
from .state import ProgressState
from .windows_api import find_wechat_window, screenshot, window_title_at
from .workflow import capture_without_overlay


def analysis_data(analysis: Analysis | None) -> dict | None:
    if not analysis:
        return None
    return {
        "true_intent": analysis.true_intent,
        "danger_level": analysis.danger_level,
        "need": analysis.need,
        "best_action": analysis.best_action,
        "should_reply_now": analysis.should_reply_now,
        "tension_resolved": analysis.tension_resolved,
        "latency_ms": analysis.latency_ms,
    }


class AnalysisService:
    """Runs one analysis pass on a worker thread and reports through ProgressState."""

    def __init__(self, settings: AppConfig, progress: ProgressState, window_for_hiding=None):
        self.settings = settings
        self.progress = progress
        self.window = window_for_hiding

    def _hide(self) -> None:
        if self.window:
            self.window.hide()

    def _show(self) -> None:
        if self.window:
            self.window.show()
            self.window.restore()

    def capture(self, area: Rect):
        """Grab the chat text, hiding the assistant so OCR cannot read itself."""
        window = find_wechat_window() if self.settings.chat_rect_mode == "wechat-client" else None
        if window is not None:
            return capture_without_overlay(self._hide, self._show, lambda: capture_chat(window, area))

        def capture_frame(region: Rect) -> tuple[object, str]:
            frame = capture_without_overlay(
                self._hide,
                self._show,
                lambda: (screenshot(region), window_title_at(
                    region.left + region.width // 2, region.top + region.height // 2,
                )),
            )
            self.progress.update(phase="recognizing", status=msg("status.recognizing"))
            return frame

        return capture_desktop_chat(area, capture_frame)

    def run(self, locale: str) -> None:
        """Execute the full workflow; any failure lands in the progress error field."""
        try:
            snapshot = self.capture(self.settings.chat_rect)
            assert_safe_chat(snapshot.raw_text)
            title = snapshot.title or translate("capture.desktopTitle", locale)
            if self.settings.allowed_titles and not any(item in snapshot.title for item in self.settings.allowed_titles):
                raise RuntimeError(msg("error.allowlist", name=title))
            self.progress.update(
                phase="judging",
                status=msg("status.judging", count=len(snapshot.messages)),
                preview=[{"side": m.side, "text": m.text} for m in snapshot.messages[-8:]],
            )
            analysis = judge(snapshot, self.settings.relationship, load_api_key())
            self.progress.update(
                phase="generating" if self._active_profile() else "idle",
                status=msg("status.generating") if self._active_profile() else msg("status.judged"),
                analysis=analysis_data(analysis),
            )
            self._maybe_suggest(snapshot, analysis)
        except Exception as exc:
            self.progress.update(phase="error", status=exc, error=exc)

    def _active_profile(self):
        profile = next(
            (p for p in self.settings.model_profiles if p.id == self.settings.active_model_id), None,
        )
        return profile if profile and load_model_api_key(profile.id) else None

    def _maybe_suggest(self, snapshot, analysis) -> None:
        profile = self._active_profile()
        if not profile:
            return
        replies = generate_suggestions(
            snapshot, self.settings.relationship, analysis, load_model_api_key(profile.id),
            profile.model, profile.base_url, profile.max_tokens, profile.protocol,
        )
        self.progress.update(phase="ranking", status=msg("status.ranking"))
        try:
            suggestions = recommend_replies(snapshot, self.settings.relationship, replies, load_api_key())
            status = msg("status.complete")
        except Exception as rank_error:
            suggestions = [
                {"text": reply, "probability": None, "confidence": None, "recommended": False}
                for reply in replies
            ]
            status = msg("status.rankFailed", detail=rank_error)
        self.progress.update(phase="idle", status=status, suggestions=suggestions)


def start_analysis(settings: AppConfig, progress: ProgressState, locale: str, window=None) -> None:
    """Validate preconditions and spawn the worker. Raises ValueError when blocked."""
    if progress.phase() not in {"idle", "error"}:
        raise ValueError(msg("error.busy"))
    if not settings.chat_rect:
        raise ValueError(msg("error.selectFirst"))
    if settings.chat_rect_mode == "wechat-client":
        raise ValueError(msg("error.legacyArea"))
    if not load_api_key():
        raise ValueError(msg("error.jevKey"))
    progress.update(
        phase="capturing", status=msg("status.capturing"),
        error="", analysis=None, suggestions=[],
    )
    service = AnalysisService(settings, progress, window)
    threading.Thread(target=service.run, args=(locale,), daemon=True).start()
