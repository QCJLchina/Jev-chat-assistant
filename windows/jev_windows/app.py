from __future__ import annotations

import json
import os
import re
import sys
import threading
import tkinter as tk
import uuid
from dataclasses import replace
from pathlib import Path

import webview

from . import __version__
from .task_controller import AnalysisController
from .window_binding import WindowBindingService
from .reply_preferences import validate_preferences
from .calibration import is_usable_selection, select_region
from .config import (
    AppConfig,
    OPTIONAL_MODULES,
    ModelProfile,
    delete_api_key,
    delete_model_api_key,
    load_api_key,
    load_model_api_key,
    save_api_key,
    save_model_api_key,
)
from .deepseek_client import SUPPORTED_PROTOCOLS, is_local_base_url, list_models, test_connection
from .providers import preset_data
from .i18n import (
    LANGUAGES,
    bridge_errors,
    msg,
    resolve_language,
    settings_lock,
    translate,
)
from .models import Rect
from .state import ProgressState
from .update_service import UpdateService
from .windows_api import ensure_dpi_awareness, virtual_screen_rect


def _rect_data(rect: Rect | None) -> dict | None:
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom} if rect else None


class DesktopApi:
    """Thin, secret-safe façade over the Windows workflows.

    Owns no domain logic: validation and orchestration live in the analysis,
    calibration, and update modules. This class only translates between the Vue
    bridge, persisted settings, and those services.
    """

    def __init__(self):
        self.settings = AppConfig.load()
        self.resolved_language = resolve_language(self.settings.language)
        self.window = None
        self._lock = threading.RLock()
        self.progress = ProgressState(self.resolved_language)
        self.updates = UpdateService(self.progress)
        self._binding_service = WindowBindingService()
        self._selection_revision = 0
        self._analysis = AnalysisController(self.progress, self._binding_service)

    # ------------------------------------------------------------------
    # Progress plumbing
    # ------------------------------------------------------------------

    def _set_progress(self, **updates: object) -> None:
        self.progress.update(**updates)

    def get_progress(self, known_revision: int = -1) -> dict:
        result = self.progress.poll(known_revision)
        if len(result) > 1:
            result.update(self.get_selection_state())
        return result

    def _render_state(self) -> dict:
        return self.progress.rendered()

    # ------------------------------------------------------------------
    # Settings and language
    # ------------------------------------------------------------------

    @bridge_errors
    def set_language(self, language: str) -> dict:
        if not isinstance(language, str) or language not in LANGUAGES:
            raise ValueError(msg("language.invalid"))
        with self._lock:
            resolved = resolve_language(language)
            candidate = replace(self.settings, language=language)
            try:
                candidate.save()
            except Exception as exc:
                raise RuntimeError(msg("language.failed")) from None
            self.settings.language = language
            self.resolved_language = resolved
            self.progress.set_language(resolved)
        # pywebview title updates marshal to the UI thread; never block the bridge.
        if self.window:
            threading.Thread(target=self._update_title, daemon=True).start()
        return {"language": language, "resolved_language": resolved}

    def _update_title(self) -> None:
        self.window.set_title(translate("app.title", self.resolved_language, version=__version__))

    def _safe_profile(self, profile: ModelProfile) -> dict:
        return {
            "id": profile.id,
            "name": profile.name,
            "base_url": profile.base_url,
            "model": profile.model,
            "max_tokens": profile.max_tokens,
            "protocol": profile.protocol,
            "key_configured": bool(load_model_api_key(profile.id)),
            "key_required": not is_local_base_url(profile.base_url),
        }

    @settings_lock
    def get_state(self) -> dict:
        with self.progress.lock:
            state = self._render_state()
            revision = self.progress.revision()
        return {
            **state,
            "revision": revision,
            "version": __version__,
            "language": self.settings.language,
            "resolved_language": self.resolved_language,
            "chat_rect": _rect_data(self.settings.chat_rect),
            "jev_key_configured": bool(load_api_key()),
            "relationship": self.settings.relationship,
            "reply_preferences": self.settings.reply_preferences,
            "module_visibility": dict(self.settings.module_visibility),
            "allowed_titles": self.settings.allowed_titles,
            "profiles": [self._safe_profile(item) for item in self.settings.model_profiles],
            "active_model_id": self.settings.active_model_id,
            "provider_presets": preset_data(),
            **self.get_selection_state(),
        }

    @bridge_errors
    @settings_lock
    def set_module_visibility(self, changes: dict) -> dict:
        if (not isinstance(changes, dict) or any(name not in OPTIONAL_MODULES for name in changes)
                or any(type(value) is not bool for value in changes.values())):
            raise ValueError(msg("layout.invalid"))
        visibility = {**self.settings.module_visibility, **changes}
        candidate = replace(self.settings, module_visibility=visibility)
        candidate.save()
        self.settings.module_visibility = visibility
        return {"ok": True, "module_visibility": dict(visibility)}

    @bridge_errors
    def fetch_models(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        base_url = str(data.get("base_url", "")).strip()
        key = str(data.get("api_key", "")).strip()
        protocol = str(data.get("protocol", "openai-chat"))
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(msg("error.protocolChoices"))
        profile_id = str(data.get("profile_id", "")).strip()
        if not key and profile_id:
            existing = next((p for p in self.settings.model_profiles if p.id == profile_id), None)
            # Never forward a saved (or environment-backed) key to another URL/protocol.
            if existing and existing.base_url.rstrip("/") == base_url.rstrip("/") and existing.protocol == protocol:
                key = load_model_api_key(profile_id)
        return {"models": list_models(base_url, key, protocol=protocol)}

    @bridge_errors
    def test_model(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        base_url = str(data.get("base_url", "")).strip()
        profile_id = str(data.get("profile_id", "")).strip()
        protocol = str(data.get("protocol", "openai-chat"))
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(msg("error.protocol"))
        key = str(data.get("api_key", "")).strip()
        if not key and profile_id:
            existing = next((p for p in self.settings.model_profiles if p.id == profile_id), None)
            if existing and existing.base_url.rstrip("/") == base_url.rstrip("/") and existing.protocol == protocol:
                key = load_model_api_key(profile_id)
        model = str(data.get("model", "")).strip()
        if not model or (not key and not is_local_base_url(base_url)):
            raise ValueError(msg("error.testFields"))
        return {"message": test_connection(base_url, key, model, protocol=protocol)}

    @bridge_errors
    @settings_lock
    def save_settings(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        if "jev_api_key" in data:
            if data.get("clear_jev_key"):
                delete_api_key()
            elif str(data.get("jev_api_key", "")).strip():
                save_api_key(str(data["jev_api_key"]).strip())
        profiles = []
        seen: set[str] = set()
        old_profiles = {p.id: p for p in self.settings.model_profiles}
        for item in data.get("profiles", []):
            profile_id = str(item.get("id") or uuid.uuid4()).strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", profile_id):
                raise ValueError(msg("error.profileId"))
            if profile_id in seen:
                raise ValueError(msg("error.duplicateId"))
            seen.add(profile_id)
            base_url = str(item.get("base_url", "")).strip()
            model = str(item.get("model", "")).strip()
            if not base_url or not model:
                raise ValueError(msg("error.profileFields"))
            protocol = str(item.get("protocol", "openai-chat"))
            if protocol not in SUPPORTED_PROTOCOLS:
                raise ValueError(msg("error.profileProtocol"))
            max_tokens = int(item["max_tokens"]) if item.get("max_tokens") else None
            if max_tokens is not None and not 1 <= max_tokens <= 131072:
                raise ValueError(msg("error.tokens"))
            profiles.append(ModelProfile(
                id=profile_id,
                name=str(item.get("name") or model).strip()[:80],
                base_url=base_url,
                model=model,
                max_tokens=max_tokens,
                protocol=protocol,
            ))
            key = str(item.get("api_key", "")).strip()
            if key:
                save_model_api_key(profile_id, key)
            elif profile_id in old_profiles and (
                old_profiles[profile_id].base_url.rstrip("/") != base_url.rstrip("/")
                or old_profiles[profile_id].protocol != protocol
            ):
                delete_model_api_key(profile_id)
        removed = {p.id for p in self.settings.model_profiles} - seen
        for profile_id in removed:
            delete_model_api_key(profile_id)
        active_id = str(data.get("active_model_id", ""))
        if active_id not in seen:
            active_id = profiles[0].id if profiles else ""
        self.settings.model_profiles = profiles
        self.settings.active_model_id = active_id
        if profiles:
            active = next((p for p in profiles if p.id == active_id), profiles[0])
            self.settings.deepseek_model = active.model
        self.settings.reply_preferences = validate_preferences(data.get("reply_preferences", self.settings.reply_preferences))
        self.settings.relationship = str(data.get("relationship", self.settings.relationship)).strip()
        titles = data.get("allowed_titles", [])
        if isinstance(titles, str):
            titles = titles.replace("，", ",").split(",")
        self.settings.allowed_titles = [str(title).strip() for title in titles if str(title).strip()]
        self.settings.save()
        return self.get_state()

    # ------------------------------------------------------------------
    # Calibration
    # ------------------------------------------------------------------

    def _ensure_selection_idle(self):
        if self.progress.phase() not in {"idle", "error"}:
            raise ValueError(msg("error.busy"))

    @settings_lock
    def get_selection_state(self) -> dict:
        binding = (self._binding_service.status(self.settings.window_binding)
                   if self.settings.selection_mode == "window" else {"status": "none"})
        return {"selection_mode": self.settings.selection_mode, "selection_binding": binding,
                "selection_revision": self._selection_revision, "chat_rect": _rect_data(self.settings.chat_rect)}

    def _publish_selection(self):
        self.progress.update(**self.get_selection_state())

    @bridge_errors
    @settings_lock
    def set_selection_mode(self, mode: str) -> dict:
        if mode not in {"window", "screen"}:
            raise ValueError(msg("binding.invalidMode"))
        with self.progress.lock:
            self._ensure_selection_idle()
            if mode != self.settings.selection_mode:
                candidate = replace(self.settings, selection_mode=mode, chat_rect=None, window_binding=None)
                candidate.save()
                self.settings = candidate
                self._selection_revision += 1
                self._analysis.invalidate()
                self._publish_selection()
        return {"ok": True, **self.get_selection_state()}

    @bridge_errors
    @settings_lock
    def get_binding_candidates(self) -> dict:
        self._ensure_selection_idle()
        return {"ok": True, "candidates": self._binding_service.candidates(self.settings.window_binding)}

    @bridge_errors
    @settings_lock
    def confirm_binding(self, candidate_id: str) -> dict:
        with self.progress.lock:
            self._ensure_selection_idle()
            if self.settings.selection_mode != "window":
                raise ValueError(msg("binding.invalidMode"))
            descriptor = self._binding_service.confirm(self.settings.window_binding, candidate_id)
            candidate = replace(self.settings, window_binding=descriptor)
            candidate.save()
            self.settings = candidate
            self._selection_revision += 1
            self._analysis.invalidate()
            self._publish_selection()
        return {"ok": True, **self.get_selection_state()}

    @bridge_errors
    def start_calibration(self, mode: str | None = None) -> dict:
        requested = mode or self.settings.selection_mode
        if requested not in {"window", "screen"}:
            raise ValueError(msg("binding.invalidMode"))
        client = virtual_screen_rect()
        with self.progress.lock:
            self._ensure_selection_idle()
            self._set_progress(phase="calibrating", status=msg("status.calibrating"))

        def overlay() -> None:
            with self._analysis.capture_lock:
                if self.window:
                    self.window.hide()
                try:
                    select_region(client, self.resolved_language, finish)
                except Exception as exc:
                    self._set_progress(phase="error", status=msg("status.overlayFailed"), error=exc)
                    if self.window:
                        self.window.show()
                        self.window.restore()

        def finish(rect: Rect | None) -> None:
            try:
                if rect and is_usable_selection(rect):
                    descriptor = self._binding_service.bind(rect) if requested == "window" else None
                    with self._lock:
                        changed = (requested != self.settings.selection_mode or
                                   (not self._binding_service.same_target(self.settings.window_binding, descriptor)
                                    if requested == "window" else rect != self.settings.chat_rect))
                        candidate = replace(self.settings, selection_mode=requested, chat_rect=rect, window_binding=descriptor)
                        candidate.save()
                        self.settings = candidate
                        if changed:
                            self._selection_revision += 1
                            self._analysis.invalidate()
                        self._set_progress(status=msg("status.areaSaved"), phase="idle", error="")
                        self._publish_selection()
                elif rect:
                    self._set_progress(status=msg("status.areaSmall"), phase="idle")
                else:
                    self._set_progress(status=msg("status.cancelled"), phase="idle")
            except Exception as exc:
                self._set_progress(phase="error", status=exc, error=exc)
            finally:
                if self.window:
                    self.window.show()
                    self.window.restore()

        threading.Thread(target=overlay, daemon=True).start()
        return {"ok": True}

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    @bridge_errors
    @settings_lock
    def analyze(self, preferences: dict | None = None, context: dict | None = None, intent: str = "general") -> dict:
        return self._analysis.start(self.settings, self.resolved_language, self.window,
                                    preferences=preferences, context=context, review=True, intent=intent)

    @bridge_errors
    @settings_lock
    def analyze_text(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise ValueError(msg("feature.emptyText"))
        return self._analysis.start(self.settings, self.resolved_language, self.window,
                                   text=data.get("text", ""), preferences=data.get("preferences"), context=data.get("context"),
                                   review=True, intent=data.get("intent", "general"))

    @bridge_errors
    @settings_lock
    def submit_review(self, payload: dict) -> dict:
        return self._analysis.submit_review(payload.get("review_id"), payload.get("messages"),
            self.settings, self.resolved_language, preferences=payload.get("preferences"),
            context=payload.get("context"), intent=payload.get("intent", "general"), window=self.window)

    @bridge_errors
    def discard_review(self, review_id: str) -> dict:
        with self.progress.lock:
            job = self._analysis._lookup(review_id)
            if not job.review or self.progress.phase() not in {"idle", "error"}:
                raise ValueError(msg("feature.taskInactive"))
            self._analysis.invalidate()
        return {"ok": True}

    @bridge_errors
    def rewrite_reply(self, task_id: str, index: int, action: str, revision: int) -> dict:
        return self._analysis.rewrite(task_id, index, action, revision)

    @bridge_errors
    def undo_reply(self, task_id: str, index: int, revision: int) -> dict:
        return self._analysis.undo_reply(task_id, index, revision)

    @bridge_errors
    def rank_replies(self, task_id: str, revision: int) -> dict:
        return self._analysis.rank(task_id, revision)

    @bridge_errors
    def cancel_analysis(self, task_id: str) -> dict:
        return self._analysis.cancel(task_id)

    @bridge_errors
    @settings_lock
    def retry_analysis(self, task_id: str, stage: str) -> dict:
        if stage == "rewrite":
            return self._analysis.retry_rewrite(task_id)
        return self._analysis.retry(task_id, stage, self.window, self.settings.chat_rect, self.settings.window_binding)

    # ------------------------------------------------------------------
    # Window and clipboard
    # ------------------------------------------------------------------

    def set_on_top(self, value: bool) -> dict:
        if self.window:
            self.window.on_top = bool(value)
        return {"ok": True}

    @bridge_errors
    @settings_lock
    def set_active_model(self, profile_id: str) -> dict:
        if profile_id and profile_id not in {profile.id for profile in self.settings.model_profiles}:
            raise ValueError(msg("error.profileMissing"))
        self.settings.active_model_id = profile_id
        self.settings.save()
        return {"ok": True}

    @bridge_errors
    def copy_text(self, value: str) -> dict:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(value), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return {"ok": True}

    # ------------------------------------------------------------------
    # In-app update
    # ------------------------------------------------------------------

    @bridge_errors
    def check_for_updates(self) -> dict:
        return self.updates.check()

    def start_background_check(self) -> None:
        self.updates.start_background_check()

    @bridge_errors
    def download_update(self) -> dict:
        self.updates.download()
        return {"ok": True}

    @bridge_errors
    def cancel_update(self) -> dict:
        self.updates.cancel_download()
        return {"ok": True}

    @bridge_errors
    def apply_update(self) -> dict:
        self.updates.apply()
        # The helper waits for this process to exit. Shut down on a timer so the
        # bridge returns first and Python can run its normal cleanup.
        threading.Timer(0.5, self._shutdown_for_update).start()
        return {"ok": True}

    def _shutdown_for_update(self) -> None:
        try:
            if self.window:
                self.window.destroy()
        except Exception:
            pass
        os._exit(0)


def show_startup_error(locale: str, detail: str) -> None:
    root = tk.Tk()
    root.title(translate("error.startup", locale))
    root.attributes("-topmost", True)
    tk.Label(root, text=detail, wraplength=520, justify="left", padx=24, pady=20).pack()
    tk.Button(root, text=translate("common.close", locale), command=root.destroy, padx=20).pack(pady=(0, 20))
    root.bind("<Escape>", lambda _: root.destroy())
    root.mainloop()


def main() -> None:
    ensure_dpi_awareness()
    api = DesktopApi()
    if getattr(sys, "frozen", False):
        frontend = Path(sys._MEIPASS) / "frontend" / "dist" / "index.html"
    else:
        frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
    if not frontend.exists():
        show_startup_error(api.resolved_language, translate("error.frontend", api.resolved_language))
        return
    window = webview.create_window(
        translate("app.title", api.resolved_language, version=__version__),
        frontend.as_uri(),
        width=980,
        height=760,
        min_size=(760, 620),
        resizable=True,
        on_top=True,
    )
    api.window = window
    # Export only the supported bridge methods; do not traverse task caches or
    # native COM objects when pywebview generates its JavaScript API.
    window.expose(*(getattr(api, name) for name in vars(DesktopApi)
                    if not name.startswith("_") and callable(getattr(api, name))))
    api.start_background_check()
    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:
        show_startup_error(api.resolved_language, translate("error.webview", api.resolved_language))


if __name__ == "__main__":
    main()
