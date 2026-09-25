from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import win32cred

from .models import Rect


APP_NAME = "JevChatAssistant"
CREDENTIAL_TARGET = "JevChatAssistant/TypeSafe"
LEGACY_CREDENTIAL_TARGET = "JevChatAssistant/OpenRouter"
DEEPSEEK_CREDENTIAL_TARGET = "JevChatAssistant/DeepSeek"
MODEL_CREDENTIAL_PREFIX = "JevChatAssistant/Model/"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


@dataclass
class ModelProfile:
    id: str
    name: str
    base_url: str
    model: str
    max_tokens: int | None = None
    protocol: str = "openai-chat"


@dataclass
class AppConfig:
    language: str = "system"
    relationship: str = "对方是我的朋友；from=me 是我发的，from=other 是对方发的"
    deepseek_model: str = "deepseek-flash"
    chat_rect: Rect | None = None
    chat_rect_mode: str = "screen"
    allowed_titles: list[str] = field(default_factory=list)
    auto_analyze: bool = False
    model_profiles: list[ModelProfile] = field(default_factory=lambda: [ModelProfile(
        id="deepseek-default", name="DeepSeek", base_url="https://api.deepseek.com",
        model="deepseek-flash",
    )])
    active_model_id: str = "deepseek-default"

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            from .i18n import LANGUAGES
            if not isinstance(raw.get("language"), str) or raw["language"] not in LANGUAGES:
                raw["language"] = "zh-CN"
            legacy_model_config = "model_profiles" not in raw
            rect = raw.get("chat_rect")
            raw["chat_rect"] = Rect(**rect) if rect else None
            if "chat_rect_mode" not in raw:
                raw["chat_rect_mode"] = "wechat-client" if rect else "screen"
            if raw.get("chat_rect_mode") not in {"screen", "wechat-client"}:
                raw["chat_rect_mode"] = "screen"
            raw["model_profiles"] = [ModelProfile(**item) for item in raw.get("model_profiles", [])]
            known = {field.name for field in cls.__dataclass_fields__.values()}
            config = cls(**{k: v for k, v in raw.items() if k in known})
            if legacy_model_config:
                config.model_profiles = [ModelProfile(
                    id="deepseek-default", name="DeepSeek", base_url="https://api.deepseek.com",
                    model=config.deepseek_model or "deepseek-flash",
                )]
                config.active_model_id = config.model_profiles[0].id
            elif config.model_profiles and config.active_model_id not in {item.id for item in config.model_profiles}:
                config.active_model_id = config.model_profiles[0].id
            elif not config.model_profiles:
                config.active_model_id = ""
            return config
        except (OSError, ValueError, TypeError):
            return cls()

    def save(self) -> None:
        directory = config_dir()
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "settings.json"
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        temp.replace(path)


def save_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        delete_api_key()
        return
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": CREDENTIAL_TARGET,
            "CredentialBlob": key,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "UserName": APP_NAME,
        },
        0,
    )


def load_api_key() -> str:
    env_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        credential = win32cred.CredRead(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        try:
            # One-time compatibility for users who entered a Jev key into the
            # old field before direct TypeSafe support was added.
            credential = win32cred.CredRead(
                LEGACY_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
            )
        except Exception:
            return ""
    blob = credential.get("CredentialBlob", b"")
    if isinstance(blob, bytes):
        return blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
    return str(blob)


def delete_api_key() -> None:
    for target in (CREDENTIAL_TARGET, LEGACY_CREDENTIAL_TARGET):
        try:
            win32cred.CredDelete(target, win32cred.CRED_TYPE_GENERIC, 0)
        except Exception:
            pass


def save_deepseek_api_key(key: str) -> None:
    key = key.strip()
    if not key:
        delete_deepseek_api_key()
        return
    save_model_api_key("deepseek-default", key)


def save_model_api_key(profile_id: str, key: str) -> None:
    key = key.strip()
    if not key:
        delete_model_api_key(profile_id)
        return
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": MODEL_CREDENTIAL_PREFIX + profile_id,
            "CredentialBlob": key,
            "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            "UserName": APP_NAME,
        },
        0,
    )


def load_deepseek_api_key() -> str:
    env_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        return load_model_api_key("deepseek-default")
    except Exception:
        return ""


def delete_deepseek_api_key() -> None:
    delete_model_api_key("deepseek-default")
    try:
        win32cred.CredDelete(
            DEEPSEEK_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception:
        pass


def load_model_api_key(profile_id: str) -> str:
    env_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if env_key and profile_id == "deepseek-default":
        return env_key
    try:
        credential = win32cred.CredRead(
            MODEL_CREDENTIAL_PREFIX + profile_id, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception:
        if profile_id != "deepseek-default":
            return ""
        try:
            credential = win32cred.CredRead(DEEPSEEK_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0)
            blob = credential.get("CredentialBlob", b"")
            key = blob.decode("utf-16-le", errors="ignore").rstrip("\x00") if isinstance(blob, bytes) else str(blob)
            if key:
                save_model_api_key(profile_id, key)
            return key
        except Exception:
            return ""
    blob = credential.get("CredentialBlob", b"")
    return blob.decode("utf-16-le", errors="ignore").rstrip("\x00") if isinstance(blob, bytes) else str(blob)


def delete_model_api_key(profile_id: str) -> None:
    try:
        win32cred.CredDelete(MODEL_CREDENTIAL_PREFIX + profile_id, win32cred.CRED_TYPE_GENERIC, 0)
    except Exception:
        pass
