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
from .models import Analysis, ChatSnapshot, Message
from .reply_intent import validate_intent
from .deepseek_client import rewrite_reply
from .context import normalize_context, compose_context
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
    context_options: dict = field(default_factory=dict)
    context_prepared: bool = False
    context_stats: dict | None = None
    snapshot: ChatSnapshot | None = None
    judgment: Analysis | None = None
    replies: list[str] = field(default_factory=list)
    stage: str = "capture"
    task_id: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)
    review: bool = False
    original_snapshot: ChatSnapshot | None = None
    intent: str = "general"
    histories: list[list[str]] = field(default_factory=list)
    reply_revision: int = 0
    rewrite_request: tuple[int, str, int] | None = None


class GuardedProgress:
    def __init__(self, controller, job):
        self.controller, self.job = controller, job

    def update(self, **values):
        self.controller.publish(self.job, **values)


class AnalysisController:
    def __init__(self, progress, binding_service=None):
        self.progress = progress
        self.binding_service = binding_service
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

    def start(self, settings, locale, window=None, text=None, preferences=None, context=None,
              review=False, intent="general"):
        frozen = copy.deepcopy(settings)
        selected = validate_preferences({**frozen.reply_preferences, **(preferences or {})})
        selected = resolve_preferences(selected, locale)
        options = normalize_context(context)
        snapshot = parse_text(text) if text is not None else None
        key = load_api_key()
        if not key and not review:
            raise ValueError(msg("error.jevKey"))
        if text is None:
            if self.binding_service is not None and frozen.selection_mode == "window":
                if not frozen.window_binding:
                    raise ValueError(msg("binding.selectFirst"))
            elif not frozen.chat_rect:
                raise ValueError(msg("error.selectFirst"))
        profile = next((p for p in frozen.model_profiles if p.id == frozen.active_model_id), None)
        model_key = load_model_api_key(profile.id) if profile else ""
        if profile and not (model_key or is_local_base_url(profile.base_url)):
            profile = None
        job = Job(frozen, locale, "text" if text is not None else "desktop", selected,
                  key, model_key, profile, context_options=options, snapshot=snapshot, stage="judge" if snapshot else "capture")
        job.review = review
        job.intent = validate_intent(intent)
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
            values.update(preview=[], analysis=None, suggestions=[], context_stats=None,
                          review_id=None, review_messages=[], task_intent=job.intent,
                          reply_revision=job.reply_revision, reply_histories=[], ranking_valid=False)
        self.progress.update(**values)
        threading.Thread(target=self._run, args=(job, window), daemon=True).start()

    def cancel(self, task_id):
        with self.progress.lock:
            job = self._lookup(task_id)
            if self.progress.phase() not in {"capturing", "recognizing", "judging", "generating", "ranking", "rewriting"}:
                raise ValueError(msg("feature.taskInactive"))
            job.cancel.set()
            self.progress.update(phase="idle", status=msg("feature.cancelled"), error="",
                                 failed_stage=job.stage, retryable_stages=[job.stage])
        return {"ok": True}

    def _lookup(self, task_id):
        if not self.job or task_id != self.job.task_id:
            raise ValueError(msg("feature.taskExpired"))
        return self.job

    def retry(self, task_id, stage, window=None, selected_rect=None, selected_binding=None):
        with self.progress.lock:
            old = self._lookup(task_id)
            if self.progress.phase() not in {"idle", "error"}:
                raise ValueError(msg("error.busy"))
            if stage not in self.progress.get("retryable_stages", []):
                raise ValueError(msg("feature.invalidRetry"))
            job = copy.copy(old)
            if stage == "capture":
                job.snapshot = None
                job.context_prepared = False
                job.context_stats = None
                if (selected_binding is not None and self.binding_service is not None
                        and job.settings.selection_mode == "window"
                        and self.binding_service.same_target(old.settings.window_binding, selected_binding)):
                    job.settings = copy.deepcopy(old.settings)
                    job.settings.window_binding = copy.deepcopy(selected_binding)
                if selected_rect is not None and job.settings.selection_mode == "screen":
                    job.settings = copy.deepcopy(old.settings)
                    job.settings.chat_rect = selected_rect
            job.stage = stage
            self._launch(job, window)
        return {"ok": True, "task_id": job.task_id}

    def invalidate(self):
        """Changing capture targets ends the previous in-memory session."""
        with self.progress.lock:
            if self.job:
                self.job.cancel.set()
            self.job = None
            self.progress.update(task_id=None, input_source=None, failed_stage=None,
                                 retryable_stages=[], preview=[], analysis=None, suggestions=[], context_stats=None,
                                 review_id=None, review_messages=[], reply_histories=[], reply_revision=0,
                                 ranking_valid=False, task_intent="general",
                                 error="", status=msg("status.initial"), phase="idle")

    def submit_review(self, review_id, messages, settings, locale, preferences=None, context=None, intent="general", window=None):
        """Original text is held by the backend and cannot be overwritten by edits."""
        with self.progress.lock:
            old = self._lookup(review_id)
            if self.progress.phase() not in {"idle", "error"}:
                raise ValueError(msg("error.busy"))
            if not old.review or old.original_snapshot is None:
                raise ValueError(msg("feature.taskExpired"))
            if not isinstance(messages, list):
                raise ValueError(msg("review.invalidMessages"))
            corrected = []
            for message in messages:
                if (not isinstance(message, dict) or message.get("side") not in {"me", "other"}
                        or not isinstance(message.get("text"), str)):
                    raise ValueError(msg("review.invalidMessages"))
                if message["text"].strip():
                    corrected.append(Message(message["side"], message["text"]))
            if not corrected:
                raise ValueError(msg("feature.emptyText"))
            original = old.original_snapshot
            raw = original.raw_text + "\n" + "\n".join(m.text for m in original.messages)
            raw += "\n" + old.context_options.get("prior_text", "") + "\n" + old.context_options.get("background", "")
            raw += "\n" + "\n".join(m.text for m in corrected)
            snapshot, stats = compose_context(ChatSnapshot(original.title, corrected, raw), context)
            key = load_api_key()
            if not key:
                raise ValueError(msg("error.jevKey"))
            frozen = copy.deepcopy(settings)
            profile = next((p for p in frozen.model_profiles if p.id == frozen.active_model_id), None)
            model_key = load_model_api_key(profile.id) if profile else ""
            if profile and not (model_key or is_local_base_url(profile.base_url)):
                profile = None
            selected = resolve_preferences(validate_preferences({**frozen.reply_preferences, **(preferences or {})}), locale)
            job = Job(frozen, locale, old.source, selected, key, model_key, profile,
                      snapshot=snapshot, context_prepared=True, context_stats=stats, stage="judge",
                      intent=validate_intent(intent))
            old.cancel.set()
            self._launch(job, window, fresh=True)
            self.progress.update(context_stats=stats)
            return {"ok": True, "task_id": job.task_id}

    def _reply_job(self, task_id, revision):
        job = self._lookup(task_id)
        if self.progress.phase() not in {"idle", "error"}:
            raise ValueError(msg("error.busy"))
        if type(revision) is not int or revision != job.reply_revision or not job.replies:
            raise ValueError(msg("feature.taskExpired"))
        return job

    def _unranked(self, job):
        return [{"text": r, "probability": None, "confidence": None, "recommended": False}
                for r in job.replies]

    def _changed_replies(self, job):
        self.progress.update(suggestions=self._unranked(job), reply_revision=job.reply_revision,
                             reply_histories=[len(h) for h in job.histories], ranking_valid=False,
                             failed_stage=None, retryable_stages=[], error="", phase="idle",
                             status=msg("review.pendingRank"))

    def undo_reply(self, task_id, index, revision):
        with self.progress.lock:
            job = self._reply_job(task_id, revision)
            if type(index) is not int or not 0 <= index < len(job.histories) or not job.histories[index]:
                raise ValueError(msg("review.invalidAction"))
            job.replies[index] = job.histories[index].pop()
            job.reply_revision += 1
            job.rewrite_request = None
            self._changed_replies(job)
        return {"ok": True}

    def rewrite(self, task_id, index, action, revision):
        with self.progress.lock:
            old = self._reply_job(task_id, revision)
            if (type(index) is not int or not 0 <= index < len(old.replies)
                    or action not in {"shorter", "natural", "gentle"} or not old.profile):
                raise ValueError(msg("review.invalidAction"))
            job = copy.copy(old)
            job.cancel = threading.Event()
            job.replies = list(old.replies)
            job.histories = copy.deepcopy(old.histories)
            job.stage = "rewrite"
            job.rewrite_request = (index, action, revision)
            old.cancel.set()
            self.job = job
            self.progress.update(phase="rewriting", status=msg("review.rewriting"),
                                 error="", failed_stage=None, retryable_stages=[])
            threading.Thread(target=self._run_rewrite, args=(job,), daemon=True).start()
        return {"ok": True, "task_id": job.task_id}

    def retry_rewrite(self, task_id):
        with self.progress.lock:
            old = self._lookup(task_id)
            if "rewrite" not in self.progress.get("retryable_stages", []) or not old.rewrite_request:
                raise ValueError(msg("feature.invalidRetry"))
            return self.rewrite(task_id, *old.rewrite_request[:2], old.rewrite_request[2])

    def rank(self, task_id, revision):
        with self.progress.lock:
            old = self._reply_job(task_id, revision)
            job = copy.copy(old)
            job.replies = list(old.replies)
            job.stage = "rank"
            old.cancel.set()
            self._launch(job, None)
        return {"ok": True, "task_id": job.task_id}

    def _run_rewrite(self, job):
        try:
            index, action, revision = job.rewrite_request
            p = job.profile
            result = rewrite_reply(job.snapshot, job.settings.relationship, job.judgment,
                job.replies[index], action, job.model_key, p.model, p.base_url, p.max_tokens, p.protocol,
                preferences=job.preferences, intent=job.intent, cancel_event=job.cancel)
            if not isinstance(result, str) or not result.strip():
                raise ValueError(msg("review.invalidReply"))
            assert_safe_chat(result)
            with self.progress.lock:
                if not self._current(job) or job.reply_revision != revision:
                    return
                job.histories[index].append(job.replies[index])
                job.replies[index] = result.strip()
                job.reply_revision += 1
                job.rewrite_request = None
                self._changed_replies(job)
        except Exception as exc:
            self.publish(job, phase="idle", status=msg("review.rewriteFailed"), error=exc,
                         failed_stage="rewrite", retryable_stages=["rewrite"])

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
                    snapshot = workflow.AnalysisService(job.settings, GuardedProgress(self, job), window, binding_service=self.binding_service).capture(job.settings.chat_rect)
                if not self._checkpoint(job, snapshot=snapshot, stage="judge"):
                    return
            if job.review:
                if job.source == "desktop" and job.settings.allowed_titles and not any(t in job.snapshot.title for t in job.settings.allowed_titles):
                    raise RuntimeError(msg("error.allowlist", name=job.snapshot.title))
                if not self._checkpoint(job, original_snapshot=job.snapshot):
                    return
                self.publish(job, phase="idle", status=msg("review.ready"),
                             review_id=job.task_id,
                             review_messages=[{"side": m.side, "text": m.text} for m in job.snapshot.messages])
                return
            if not job.context_prepared:
                snapshot, stats = compose_context(job.snapshot, job.context_options)
                if not self._checkpoint(job, snapshot=snapshot, context_prepared=True, context_stats=stats):
                    return
                self.publish(job, context_stats=stats)
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
                self.publish(job, phase="idle", status=msg("review.judgedOnly"))
                return
            if not job.replies:
                if not self.publish(job, phase="generating", status=msg("status.generating")):
                    return
                p = job.profile
                replies = workflow.generate_suggestions(job.snapshot, job.settings.relationship, job.judgment,
                    job.model_key, p.model, p.base_url, p.max_tokens, p.protocol, preferences=job.preferences, cancel_event=job.cancel,
                    **({"intent": job.intent} if job.intent != "general" else {}))
                if not self._checkpoint(job, replies=replies, histories=[[] for _ in replies], stage="rank"):
                    return
                self.publish(job, suggestions=[{"text": r, "probability": None, "confidence": None, "recommended": False} for r in replies])
            if not self.publish(job, phase="ranking", status=msg("status.ranking")):
                return
            suggestions = workflow.recommend_replies(job.snapshot, job.settings.relationship, job.replies, job.key, cancel_event=job.cancel)
            self.publish(job, phase="idle", status=msg("status.complete"), suggestions=suggestions,
                         ranking_valid=True, reply_revision=job.reply_revision,
                         reply_histories=[len(h) for h in job.histories], retryable_stages=[], failed_stage=None)
        except Exception as exc:
            self.publish(job, phase="idle" if job.stage == "rank" else "error",
                         status=msg("status.rankFailed", detail=exc) if job.stage == "rank" else exc,
                         error=exc, failed_stage=job.stage, retryable_stages=[job.stage])
