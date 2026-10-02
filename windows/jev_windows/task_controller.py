"""In-memory analysis checkpoints with generation-guarded publication."""
from __future__ import annotations

import copy
import threading
import uuid
from dataclasses import dataclass, field

from . import analysis as workflow
from .config import AppConfig, ModelProfile, load_api_key, load_model_api_key
from .deepseek_client import is_local_base_url
from .i18n import msg, translate
from .input_text import parse_text
from .reply_preferences import resolve_preferences, validate_preferences
from .models import Analysis, ChatSnapshot
from .safety import assert_safe_chat


@dataclass
class Job:
    settings: AppConfig
    locale: str
    source: str
    preferences: dict
    key: str
    model_key: str
    profile: ModelProfile | None
    snapshot: ChatSnapshot | None = None
    judgment: Analysis | None = None
    replies: list[str] = field(default_factory=list)
    stage: str = "capture"
    task_id: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)


class GuardedProgress:
    def __init__(self, controller, job):
        self.controller, self.job = controller, job

    def update(self, **values):
        self.controller.publish(self.job, **values)


class AnalysisController:
    def __init__(self, progress):
        self.progress = progress
        self.job = None
        self.capture_lock = threading.RLock()

    def _current(self, job):
        return self.job is job and not job.cancel.is_set()

    def publish(self, job, **values):
        with self.progress.lock:
            if not self._current(job):
                return False
            self.progress.update(**values)
            return True

    def start(self, settings, locale, window=None, text=None, preferences=None):
        frozen = copy.deepcopy(settings)
        selected = validate_preferences({**frozen.reply_preferences, **(preferences or {})})
        selected = resolve_preferences(selected, locale)
        snapshot = parse_text(text) if text is not None else None
        key = load_api_key()
        if not key:
            raise ValueError(msg("error.jevKey"))
        if text is None and not frozen.chat_rect:
            raise ValueError(msg("error.selectFirst"))
        profile = next((p for p in frozen.model_profiles if p.id == frozen.active_model_id), None)
        model_key = load_model_api_key(profile.id) if profile else ""
        if profile and not (model_key or is_local_base_url(profile.base_url)):
            profile = None
        job = Job(frozen, locale, "text" if text is not None else "desktop", selected,
                  key, model_key, profile, snapshot=snapshot, stage="judge" if snapshot else "capture")
        with self.progress.lock:
            if self.progress.phase() not in {"idle", "error"}:
                raise ValueError(msg("error.busy"))
            if self.job:
                self.job.cancel.set()
            self._launch(job, window, fresh=True)
        return {"ok": True, "task_id": job.task_id}

    def _launch(self, job, window, fresh=False):
        job.task_id = uuid.uuid4().hex
        job.cancel = threading.Event()
        self.job = job
        phases = {"capture": "capturing", "judge": "judging", "generate": "generating", "rank": "ranking"}
        statuses = {"capture": msg("status.capturing"),
                    "judge": msg("status.judging", count=len(job.snapshot.messages) if job.snapshot else 0),
                    "generate": msg("status.generating"), "rank": msg("status.ranking")}
        values = dict(task_id=job.task_id, input_source=job.source, failed_stage=None,
                      retryable_stages=[], error="", phase=phases[job.stage], status=statuses[job.stage])
        if fresh:
            values.update(preview=[], analysis=None, suggestions=[])
        self.progress.update(**values)
        threading.Thread(target=self._run, args=(job, window), daemon=True).start()

    def cancel(self, task_id):
        with self.progress.lock:
            job = self._lookup(task_id)
            if self.progress.phase() not in {"capturing", "recognizing", "judging", "generating", "ranking"}:
                raise ValueError(msg("feature.taskInactive"))
            job.cancel.set()
            self.progress.update(phase="idle", status=msg("feature.cancelled"), error="",
                                 failed_stage=job.stage, retryable_stages=[job.stage])
        return {"ok": True}

    def _lookup(self, task_id):
        if not self.job or task_id != self.job.task_id:
            raise ValueError(msg("feature.taskExpired"))
        return self.job

    def retry(self, task_id, stage, window=None, selected_rect=None):
        with self.progress.lock:
            old = self._lookup(task_id)
            if self.progress.phase() not in {"idle", "error"}:
                raise ValueError(msg("error.busy"))
            if stage not in self.progress.get("retryable_stages", []):
                raise ValueError(msg("feature.invalidRetry"))
            job = copy.copy(old)
            if stage == "capture":
                job.snapshot = None
                if selected_rect is not None:
                    job.settings = copy.deepcopy(old.settings)
                    job.settings.chat_rect = selected_rect
            job.stage = stage
            self._launch(job, window)
        return {"ok": True, "task_id": job.task_id}

    def _checkpoint(self, job, **values):
        with self.progress.lock:
            if not self._current(job):
                return False
            for name, value in values.items():
                setattr(job, name, value)
            return True

    def _run(self, job, window):
        try:
            if job.snapshot is None:
                with self.capture_lock:
                    if not self._current(job):
                        return
                    snapshot = workflow.AnalysisService(job.settings, GuardedProgress(self, job), window).capture(job.settings.chat_rect)
                if not self._checkpoint(job, snapshot=snapshot, stage="judge"):
                    return
            assert_safe_chat(job.snapshot.raw_text)
            if job.source == "desktop" and job.settings.allowed_titles and not any(t in job.snapshot.title for t in job.settings.allowed_titles):
                raise RuntimeError(msg("error.allowlist", name=job.snapshot.title or translate("capture.desktopTitle", job.locale)))
            if job.judgment is None:
                if not self.publish(job, phase="judging", status=msg("status.judging", count=len(job.snapshot.messages)),
                                    preview=[{"side": m.side, "text": m.text} for m in job.snapshot.messages]):
                    return
                result = workflow.judge(job.snapshot, job.settings.relationship, job.key, cancel_event=job.cancel)
                if not self._checkpoint(job, judgment=result, stage="generate"):
                    return
                self.publish(job, analysis=workflow.analysis_data(result))
            if not job.profile:
                self.publish(job, phase="idle", status=msg("status.judged"))
                return
            if not job.replies:
                if not self.publish(job, phase="generating", status=msg("status.generating")):
                    return
                p = job.profile
                replies = workflow.generate_suggestions(job.snapshot, job.settings.relationship, job.judgment,
                    job.model_key, p.model, p.base_url, p.max_tokens, p.protocol, preferences=job.preferences, cancel_event=job.cancel)
                if not self._checkpoint(job, replies=replies, stage="rank"):
                    return
                self.publish(job, suggestions=[{"text": r, "probability": None, "confidence": None, "recommended": False} for r in replies])
            if not self.publish(job, phase="ranking", status=msg("status.ranking")):
                return
            suggestions = workflow.recommend_replies(job.snapshot, job.settings.relationship, job.replies, job.key, cancel_event=job.cancel)
            self.publish(job, phase="idle", status=msg("status.complete"), suggestions=suggestions, retryable_stages=[], failed_stage=None)
        except Exception as exc:
            self.publish(job, phase="idle" if job.stage == "rank" else "error",
                         status=msg("status.rankFailed", detail=exc) if job.stage == "rank" else exc,
                         error=exc, failed_stage=job.stage, retryable_stages=[job.stage])
