from __future__ import annotations

from .i18n import msg

import json
import os
from dataclasses import replace
from .i18n import LANGUAGES, bridge_errors, describe, render, resolve_language, settings_lock, translate
import re
import sys
import tempfile
import threading
import tkinter as tk
import uuid
from pathlib import Path

import webview

from . import __version__
from .capture import capture_chat, capture_desktop_chat
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
from .deepseek_client import SUPPORTED_PROTOCOLS, DeepSeekError, generate_suggestions, list_models, test_connection
from .jev_api import judge, recommend_replies
from .models import Analysis, Rect
from .safety import assert_safe_chat
from .updater import (
    UpdateError,
    app_install_dir,
    apply_staged_update,
    compare_versions,
    download_release,
    fetch_latest_release,
    stage_update,
    verify_sha256,
)
from .windows_api import (
    ensure_dpi_awareness,
    find_wechat_window,
    screenshot,
    virtual_screen_rect,
    window_title_at,
)
from .workflow import capture_without_overlay


def _rect_data(rect: Rect | None) -> dict | None:
    return {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom} if rect else None


def _analysis_data(analysis: Analysis | None) -> dict | None:
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


def overlay_geometry(rect: Rect) -> str:
    # Tk reads a bare negative offset ("-500") as "distance from the right
    # edge". An explicit "+-500" selects x=-500, which is what secondary
    # monitors to the left of the primary need.
    return f"{rect.width}x{rect.height}+{rect.left}+{rect.top}"


class DesktopApi:
    """Small, secret-safe bridge between Vue and existing Windows workflows."""

    def __init__(self):
        self.settings = AppConfig.load()
        self.resolved_language = resolve_language(self.settings.language)
        self.window = None
        self._lock = threading.RLock()
        self._state = {
            "status": msg("status.initial"),
            "phase": "idle",
            "preview": [],
            "analysis": None,
            "suggestions": [],
            "error": "",
        }
        self._state["status_message"] = describe(self._state["status"])
        self._state["error_message"] = None
        self._state_revision = 0
        self.update_info: dict | None = None
        self.update_cancel = threading.Event()
        self.update_thread: threading.Thread | None = None

    def _set_progress(self, **updates: object) -> None:
        with self._lock:
            for field in ("status", "error"):
                if field in updates:
                    updates[field + "_message"] = describe(updates[field])
                    if isinstance(updates[field], Exception):
                        updates[field] = str(updates[field])
            self._state.update(updates)
            self._state_revision += 1

    def get_progress(self, known_revision: int = -1) -> dict:
        with self._lock:
            revision = self._state_revision
            if known_revision == revision:
                return {"revision": revision}
            return {"revision": revision, **self._render_state()}

    def _render_state(self) -> dict:
        state = dict(self._state)
        for field in ("status", "error"):
            state[field] = render(state.get(field + "_message"), self.resolved_language, str(state[field]))
        return state

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
            self._state_revision += 1
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
        with self._lock:
            state = self._render_state()
            revision = self._state_revision
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

    @bridge_errors
    def start_calibration(self) -> dict:
        try:
            client = virtual_screen_rect()
        except Exception as exc:
            raise
        self._set_progress(phase="calibrating", status=msg("status.calibrating"))

        def overlay() -> None:
            # hide/show must not run on the main thread while a js_api call is
            # in flight: pywebview marshals them back onto the UI thread, which
            # is currently blocked executing this very bridge call -> deadlock.
            if self.window:
                self.window.hide()
            try:
                root = tk.Tk()
            except Exception as exc:
                self._set_progress(phase="error", status=msg("status.overlayFailed", detail=exc))
                if self.window:
                    self.window.show()
                    self.window.restore()
                return
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.28)
            root.geometry(overlay_geometry(client))
            canvas = tk.Canvas(root, bg="#111827", highlightthickness=0, cursor="crosshair")
            canvas.pack(fill="both", expand=True)
            canvas.create_text(client.width // 2, 28, text=translate("capture.overlay", self.resolved_language), fill="white", font=("Microsoft YaHei UI", 14, "bold"))
            start: list[tuple[int, int] | None] = [None]
            shape: list[int | None] = [None]

            def finish(rect: Rect | None) -> None:
                if rect and rect.width >= 200 and rect.height >= 100:
                    with self._lock:
                        self.settings.chat_rect = rect
                        self.settings.chat_rect_mode = "screen"
                        self.settings.save()
                    self._set_progress(status=msg("status.areaSaved"), phase="idle")
                elif rect:
                    self._set_progress(status=msg("status.areaSmall"), phase="idle")
                else:
                    self._set_progress(status=msg("status.cancelled"), phase="idle")
                root.destroy()
                if self.window:
                    self.window.show()
                    self.window.restore()

            def down(event) -> None:
                start[0] = (event.x, event.y)
                shape[0] = canvas.create_rectangle(event.x, event.y, event.x, event.y, outline="#1497f5", width=4)

            def drag(event) -> None:
                if start[0] and shape[0]:
                    canvas.coords(shape[0], start[0][0], start[0][1], event.x, event.y)

            def up(event) -> None:
                if not start[0]:
                    return
                left, right = sorted((start[0][0], event.x))
                top, bottom = sorted((start[0][1], event.y))
                left += client.left
                right += client.left
                top += client.top
                bottom += client.top
                finish(Rect(left, top, right, bottom))

            canvas.bind("<Button-1>", down)
            canvas.bind("<B1-Motion>", drag)
            canvas.bind("<ButtonRelease-1>", up)
            root.bind("<Escape>", lambda _: finish(None))
            root.mainloop()

        threading.Thread(target=overlay, daemon=True).start()
        return {"ok": True}

    @bridge_errors
    def analyze(self) -> dict:
        with self._lock:
            if self._state["phase"] not in {"idle", "error"}:
                return {"ok": False, "error": msg("error.busy")}
        if not self.settings.chat_rect:
            return {"ok": False, "error": msg("error.selectFirst")}
        if self.settings.chat_rect_mode == "wechat-client":
            return {"ok": False, "error": msg("error.legacyArea")}
        jev_key = load_api_key()
        if not jev_key:
            return {"ok": False, "error": msg("error.jevKey")}
        selected_profile = next((p for p in self.settings.model_profiles if p.id == self.settings.active_model_id), None)
        profile_key = load_model_api_key(selected_profile.id) if selected_profile else ""
        profile = selected_profile if selected_profile and profile_key else None

        with self._lock:
            if self._state["phase"] not in {"idle", "error"}:
                return {"ok": False, "error": msg("error.busy")}
            self._set_progress(
                phase="capturing", status=msg("status.capturing"),
                error="", analysis=None, suggestions=[],
            )

        def worker() -> None:
            try:
                window = find_wechat_window() if self.settings.chat_rect_mode == "wechat-client" else None
                hide = lambda: self.window.hide() if self.window else None
                show = lambda: (self.window.show(), self.window.restore()) if self.window else None
                if window is not None:
                    snapshot = capture_without_overlay(
                        hide, show, lambda: capture_chat(window, self.settings.chat_rect)
                    )
                else:
                    def capture_frame(area: Rect) -> tuple[object, str]:
                        frame = capture_without_overlay(
                            hide,
                            show,
                            lambda: (
                                screenshot(area),
                                window_title_at(area.left + area.width // 2, area.top + area.height // 2),
                            ),
                        )
                        self._set_progress(phase="recognizing", status=msg("status.recognizing"))
                        return frame

                    snapshot = capture_desktop_chat(self.settings.chat_rect, capture_frame)
                assert_safe_chat(snapshot.raw_text)
                if self.settings.allowed_titles and not any(title in snapshot.title for title in self.settings.allowed_titles):
                    raise RuntimeError(msg("error.allowlist", name=snapshot.title))
                self._set_progress(
                    phase="judging", status=msg("status.judging", count=len(snapshot.messages)),
                    preview=[{"side": m.side, "text": m.text} for m in snapshot.messages[-8:]],
                )
                analysis = judge(snapshot, self.settings.relationship, jev_key)
                self._set_progress(phase="generating" if profile else "idle", status=msg("status.generating") if profile else msg("status.judged"), analysis=_analysis_data(analysis))
                if profile:
                    replies = generate_suggestions(
                        snapshot, self.settings.relationship, analysis, profile_key,
                        profile.model, profile.base_url, profile.max_tokens, profile.protocol,
                    )
                    self._set_progress(phase="ranking", status=msg("status.ranking"))
                    try:
                        suggestions = recommend_replies(
                            snapshot, self.settings.relationship, replies, jev_key
                        )
                        status = msg("status.complete")
                    except Exception as rank_error:
                        suggestions = [
                            {"text": reply, "probability": None, "confidence": None, "recommended": False}
                            for reply in replies
                        ]
                        status = msg("status.rankFailed", detail=rank_error)
                    self._set_progress(phase="idle", status=status, suggestions=suggestions)
            except Exception as exc:
                self._set_progress(phase="error", status=exc, error=exc)

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True}

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
    # In-app update bridge
    # ------------------------------------------------------------------

    @bridge_errors
    def check_for_updates(self) -> dict:
        release = fetch_latest_release()
        info = {
            "update_available": compare_versions(__version__, release["version"]) < 0,
            "latest_version": release["version"],
            "current_version": __version__,
            "download_url": release["download_url"],
            "size": release["size"],
            "sha256": release["sha256"],
        }
        self.update_info = info
        with self._lock:
            self._state["update_info"] = info
            self._state_revision += 1
        return info

    def start_background_check(self) -> None:
        """Silent update check shortly after startup; never blocks or errors UI."""

        def worker() -> None:
            threading.Event().wait(3.0)
            try:
                self.check_for_updates()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    @bridge_errors
    def download_update(self) -> dict:
        if self.update_thread and self.update_thread.is_alive():
            raise ValueError(msg("update.inProgress"))
        info = self.update_info or self._state.get("update_info")
        if not info or not info.get("download_url"):
            raise ValueError(msg("update.notChecked"))
        self.update_cancel = threading.Event()
        self._set_progress(phase="updating", status=msg("update.downloading"), error=None)

        def worker() -> None:
            temp_zip = Path(tempfile.gettempdir()) / f"jevchat-update-{info['latest_version']}.zip"
            try:
                def progress(percent: int) -> None:
                    self._set_progress(status=msg("update.downloading", percent=percent))

                download_release(
                    info["download_url"], temp_zip, expected_size=info.get("size", 0),
                    progress_cb=progress, cancel_event=self.update_cancel,
                )
                if info.get("sha256"):
                    self._set_progress(status=msg("update.verifying"))
                    if not verify_sha256(temp_zip, info["sha256"]):
                        temp_zip.unlink(missing_ok=True)
                        raise UpdateError("update.checksumMismatch")
                self._set_progress(status=msg("update.staging"))
                stage_update(temp_zip)
                temp_zip.unlink(missing_ok=True)
                self._set_progress(status=msg("update.ready"), phase="updateReady")
            except Exception as exc:
                temp_zip.unlink(missing_ok=True)
                if isinstance(exc, UpdateError) and str(exc.args[0]) == "update.cancelled":
                    self._set_progress(phase="idle", status=msg("update.cancelled"))
                else:
                    self._set_progress(phase="error", status=exc, error=exc)

        self.update_thread = threading.Thread(target=worker, daemon=True)
        self.update_thread.start()
        return {"ok": True}

    @bridge_errors
    def cancel_update(self) -> dict:
        self.update_cancel.set()
        return {"ok": True}

    @bridge_errors
    def apply_update(self) -> dict:
        with self._lock:
            phase = self._state.get("phase")
        if phase != "updateReady":
            raise ValueError(msg("update.notReady"))
        apply_staged_update(app_install_dir())
        return {"ok": True}


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
