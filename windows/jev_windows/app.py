from __future__ import annotations

import json
import re
import sys
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
from .windows_api import find_wechat_window, virtual_screen_rect
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


class DesktopApi:
    """Small, secret-safe bridge between Vue and existing Windows workflows."""

    def __init__(self):
        self.settings = AppConfig.load()
        self.window = None
        self._lock = threading.RLock()
        self._state = {
            "status": "请先设置 Jev API 密钥并框选聊天区",
            "phase": "idle",
            "preview": [],
            "analysis": None,
            "suggestions": [],
            "error": "",
        }

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
            state = dict(self._state)
        return {
            **state,
            "version": __version__,
            "chat_rect": _rect_data(self.settings.chat_rect),
            "chat_rect_mode": self.settings.chat_rect_mode,
            "jev_key_configured": bool(load_api_key()),
            "relationship": self.settings.relationship,
            "allowed_titles": self.settings.allowed_titles,
            "profiles": [self._safe_profile(item) for item in self.settings.model_profiles],
            "active_model_id": self.settings.active_model_id,
        }

    def fetch_models(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        base_url = str(data.get("base_url", "")).strip()
        profile_id = str(data.get("profile_id", "")).strip()
        protocol = str(data.get("protocol", "openai-chat"))
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("请选择 openai-chat、openai-responses 或 anthropic 协议。")
        key = str(data.get("api_key", "")).strip()
        if not key and profile_id:
            existing = next((p for p in self.settings.model_profiles if p.id == profile_id), None)
            if existing and existing.base_url.rstrip("/") == base_url.rstrip("/") and existing.protocol == protocol:
                key = load_model_api_key(profile_id)
        if not key:
            raise ValueError("请先填写此接口对应的 API Key。")
        return {"models": list_models(base_url, key, protocol=protocol)}

    def test_model(self, payload: str | dict) -> dict:
        data = json.loads(payload) if isinstance(payload, str) else payload
        base_url = str(data.get("base_url", "")).strip()
        profile_id = str(data.get("profile_id", "")).strip()
        protocol = str(data.get("protocol", "openai-chat"))
        if protocol not in SUPPORTED_PROTOCOLS:
            raise ValueError("不支持的接口协议。")
        key = str(data.get("api_key", "")).strip()
        if not key and profile_id:
            existing = next((p for p in self.settings.model_profiles if p.id == profile_id), None)
            if existing and existing.base_url.rstrip("/") == base_url.rstrip("/") and existing.protocol == protocol:
                key = load_model_api_key(profile_id)
        model = str(data.get("model", "")).strip()
        if not key or not model:
            raise ValueError("请填写 API Key 和模型名称后再测试。")
        return {"message": test_connection(base_url, key, model, protocol=protocol)}

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
                raise ValueError("模型配置标识格式不正确。")
            if profile_id in seen:
                raise ValueError("模型配置标识重复。")
            seen.add(profile_id)
            base_url = str(item.get("base_url", "")).strip()
            model = str(item.get("model", "")).strip()
            if not base_url or not model:
                raise ValueError("每个模型配置都需要接口地址和模型名称。")
            protocol = str(item.get("protocol", "openai-chat"))
            if protocol not in SUPPORTED_PROTOCOLS:
                raise ValueError("每个模型配置都需要选择有效的接口协议。")
            max_tokens = int(item["max_tokens"]) if item.get("max_tokens") else None
            if max_tokens is not None and not 1 <= max_tokens <= 131072:
                raise ValueError("输出长度必须在 1 到 131072 tokens 之间。")
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

    def start_calibration(self) -> dict:
        try:
            client = virtual_screen_rect()
        except Exception as exc:
            return {"ok": False, "error": str(exc)}
        with self._lock:
            self._state["phase"] = "calibrating"
            self._state["status"] = "请在微信聊天窗口拖动框选消息区域"
        if self.window:
            self.window.hide()

        def overlay() -> None:
            try:
                root = tk.Tk()
            except Exception as exc:
                with self._lock:
                    self._state.update(phase="error", status=f"无法启动框选窗口：{exc}")
                if self.window:
                    self.window.show()
                    self.window.restore()
                return
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            root.attributes("-alpha", 0.28)
            xpos = f"+{client.left}" if client.left >= 0 else str(client.left)
            ypos = f"+{client.top}" if client.top >= 0 else str(client.top)
            root.geometry(f"{client.width}x{client.height}{xpos}{ypos}")
            canvas = tk.Canvas(root, bg="#111827", highlightthickness=0, cursor="crosshair")
            canvas.pack(fill="both", expand=True)
            canvas.create_text(client.width // 2, 28, text="拖动框选聊天消息区域 · Esc 取消", fill="white", font=("Microsoft YaHei UI", 14, "bold"))
            start: list[tuple[int, int] | None] = [None]
            shape: list[int | None] = [None]

            def finish(rect: Rect | None) -> None:
                if rect and rect.width >= 200 and rect.height >= 100:
                    self.settings.chat_rect = rect
                    self.settings.chat_rect_mode = "screen"
                    self.settings.save()
                    with self._lock:
                        self._state["status"] = "聊天区已保存，可以开始分析"
                        self._state["phase"] = "idle"
                elif rect:
                    with self._lock:
                        self._state["status"] = "框选区域太小，请重新框选聊天消息区域。"
                        self._state["phase"] = "idle"
                else:
                    with self._lock:
                        self._state.update(status="已取消框选", phase="idle")
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

    def analyze(self) -> dict:
        with self._lock:
            if self._state["phase"] not in {"idle", "error"}:
                return {"ok": False, "error": "分析正在进行中。"}
        if not self.settings.chat_rect:
            return {"ok": False, "error": "请先框选聊天消息区域。"}
        if self.settings.chat_rect_mode == "wechat-client":
            return {"ok": False, "error": "旧版微信框选坐标已失效，请重新框选一次桌面对话区域。"}
        jev_key = load_api_key()
        if not jev_key:
            return {"ok": False, "error": "请先在设置中保存 Jev / TypeSafe API 密钥。"}
        selected_profile = next((p for p in self.settings.model_profiles if p.id == self.settings.active_model_id), None)
        profile_key = load_model_api_key(selected_profile.id) if selected_profile else ""
        profile = selected_profile if selected_profile and profile_key else None

        def worker() -> None:
            try:
                with self._lock:
                    self._state.update(phase="capturing", status="正在读取微信…截图时窗口会暂时隐藏", error="", analysis=None, suggestions=[])
                window = find_wechat_window() if self.settings.chat_rect_mode == "wechat-client" else None
                snapshot = capture_without_overlay(
                    lambda: self.window.hide() if self.window else None,
                    lambda: (self.window.show(), self.window.restore()) if self.window else None,
                    lambda: (
                        capture_chat(window, self.settings.chat_rect)
                        if window is not None
                        else capture_desktop_chat(self.settings.chat_rect)
                    ),
                )
                assert_safe_chat(snapshot.raw_text)
                if self.settings.allowed_titles and not any(title in snapshot.title for title in self.settings.allowed_titles):
                    raise RuntimeError(f"当前会话“{snapshot.title}”不在白名单中。")
                with self._lock:
                    self._state.update(
                        phase="judging", status=f"已识别 {len(snapshot.messages)} 条消息，正在调用 Jev 判断…",
                        preview=[{"side": m.side, "text": m.text} for m in snapshot.messages[-8:]],
                    )
                analysis = judge(snapshot, self.settings.relationship, jev_key)
                with self._lock:
                    self._state.update(phase="generating" if profile else "idle", status="Jev 判断完成，正在生成建议回复…" if profile else "Jev 判断完成", analysis=_analysis_data(analysis))
                if profile:
                    replies = generate_suggestions(
                        snapshot, self.settings.relationship, analysis, profile_key,
                        profile.model, profile.base_url, profile.max_tokens, profile.protocol,
                    )
                    with self._lock:
                        self._state.update(phase="ranking", status="Jev 正在评估候选回复的推荐度…")
                    try:
                        suggestions = recommend_replies(
                            snapshot, self.settings.relationship, replies, jev_key
                        )
                        status = "Jev 判断、建议回复和推荐度评估已完成"
                    except Exception as rank_error:
                        suggestions = [
                            {"text": reply, "probability": None, "confidence": None, "recommended": False}
                            for reply in replies
                        ]
                        status = f"回复已生成；Jev 推荐度暂不可用：{rank_error}"
                    with self._lock:
                        self._state.update(phase="idle", status=status, suggestions=suggestions)
            except Exception as exc:
                with self._lock:
                    self._state.update(phase="error", status=str(exc), error=str(exc))

        threading.Thread(target=worker, daemon=True).start()
        return {"ok": True}

    def set_on_top(self, value: bool) -> dict:
        if self.window:
            self.window.on_top = bool(value)
        return {"ok": True}

    def set_active_model(self, profile_id: str) -> dict:
        if profile_id and profile_id not in {profile.id for profile in self.settings.model_profiles}:
            raise ValueError("所选模型配置不存在。")
        self.settings.active_model_id = profile_id
        self.settings.save()
        return {"ok": True}

    def copy_text(self, value: str) -> dict:
        import win32clipboard

        win32clipboard.OpenClipboard()
        try:
            win32clipboard.EmptyClipboard()
            win32clipboard.SetClipboardText(str(value), win32clipboard.CF_UNICODETEXT)
        finally:
            win32clipboard.CloseClipboard()
        return {"ok": True}


def main() -> None:
    api = DesktopApi()
    if getattr(sys, "frozen", False):
        frontend = Path(sys._MEIPASS) / "frontend" / "dist" / "index.html"
    else:
        frontend = Path(__file__).resolve().parents[1] / "frontend" / "dist" / "index.html"
    if not frontend.exists():
        raise RuntimeError("未找到 Vue 前端资源，请在 windows/frontend 运行 npm run build。")
    window = webview.create_window(
        f"Jev 对话助手 · Windows v{__version__}",
        frontend.as_uri(),
        js_api=api,
        width=980,
        height=760,
        min_size=(760, 620),
        resizable=True,
        on_top=True,
    )
    api.window = window
    try:
        webview.start(gui="edgechromium", debug=not getattr(sys, "frozen", False))
    except Exception as exc:
        root = tk.Tk()
        root.withdraw()
        from tkinter import messagebox

        messagebox.showerror(
            "无法启动桌面界面",
            f"请确认已安装 Microsoft Edge WebView2 Runtime。\n\n{exc}",
            parent=root,
        )
        root.destroy()


if __name__ == "__main__":
    main()
