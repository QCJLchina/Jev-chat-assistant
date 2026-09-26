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
from .analysis import start_analysis
from .calibration import is_usable_selection, select_region
from .config import (
    AppConfig,
    ModelProfile,
    delete_api_key,
    delete_model_api_key,
    load_api_key,
    load_model_api_key,
    save_api_key,
    save_model_api_key,
)
from .deepseek_client import SUPPORTED_PROTOCOLS, list_models, test_connection
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

    # ------------------------------------------------------------------
    # Progress plumbing
    # ------------------------------------------------------------------

    def _set_progress(self, **updates: object) -> None:
        self.progress.update(**updates)

    def get_progress(self, known_revision: int = -1) -> dict:
        return self.progress.poll(known_revision)

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
                raise RuntimeError(msg("language.failed", detail=str(exc))) from None
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
        }

    def get_state(self) -> dict:
        state = self._render_state()
        revision = self.progress.revision()
        return {
            **state,
            "revision": revision,
            "version": __version__,
            "language": self.settings.language,
            "resolved_language": self.resolved_language,
            "chat_rect": _rect_data(self.settings.chat_rect),
            "chat_rect_mode": self.settings.chat_rect_mode,
            "jev_key_configured": bool(load_api_key()),
            "relationship": self.settings.relationship,
            "allowed_titles": self.settings.allowed_titles,
            "profiles": [self._safe_profile(item) for item in self.settings.model_profiles],
            "active_model_id": self.settings.active_model_id,
        }

    @bridge_errors
    def fetch_models(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        base_url = str(data.get("base_url", "")).strip()
        key = str(data.get("api_key", "")).strip()
        protocol = str(data.get("protocol", "openai-chat"))
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError(msg("error.protocolChoices"))
        if not key:
            key = os.environ.get("OPENAI_API_KEY", "").strip()
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
        if not key or not model:
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

    @bridge_errors
    def start_calibration(self) -> dict:
        # Raises if no virtual screen is available; surfaced by @bridge_errors.
        client = virtual_screen_rect()
        self._set_progress(phase="calibrating", status=msg("status.calibrating"))

        def overlay() -> None:
            # hide/show must not run on the main thread while a js_api call is
            # in flight: pywebview marshals them back onto the UI thread, which
            # is currently blocked executing this very bridge call -> deadlock.
            if self.window:
                self.window.hide()
            try:
                select_region(client, self.resolved_language, finish)
            except Exception as exc:
                self._set_progress(phase="error", status=msg("status.overlayFailed", detail=exc))
                if self.window:
                    self.window.show()
                    self.window.restore()

        def finish(rect: Rect | None) -> None:
            if rect and is_usable_selection(rect):
                with self._lock:
                    self.settings.chat_rect = rect
                    self.settings.chat_rect_mode = "screen"
                    self.settings.save()
                self._set_progress(status=msg("status.areaSaved"), phase="idle")
            elif rect:
                self._set_progress(status=msg("status.areaSmall"), phase="idle")
            else:
                self._set_progress(status=msg("status.cancelled"), phase="idle")
            if self.window:
                self.window.show()
                self.window.restore()

        threading.Thread(target=overlay, daemon=True).start()
        return {"ok": True}

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    @bridge_errors
    def analyze(self) -> dict:
        try:
            start_analysis(self.settings, self.progress, self.resolved_language, self.window)
        except ValueError as exc:
            return {"ok": False, "error": exc.args[0]}
        return {"ok": True}

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
        js_api=api,
        width=980,
        height=760,
        min_size=(760, 620),
        resizable=True,
        on_top=True,
    )
    api.window = window
    api.start_background_check()
    try:
        webview.start(gui="edgechromium", debug=False)
    except Exception as exc:
        show_startup_error(api.resolved_language, translate("error.webview", api.resolved_language, detail=str(exc)))


if __name__ == "__main__":
    main()
