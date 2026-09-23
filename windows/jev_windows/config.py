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


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_NAME


@dataclass
class AppConfig:
    relationship: str = "对方是我的朋友；from=me 是我发的，from=other 是对方发的"
    deepseek_model: str = "deepseek-flash"
    chat_rect: Rect | None = None
    allowed_titles: list[str] = field(default_factory=list)
    auto_analyze: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        path = config_dir() / "settings.json"
        if not path.exists():
            return cls()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            rect = raw.get("chat_rect")
            raw["chat_rect"] = Rect(**rect) if rect else None
            known = {field.name for field in cls.__dataclass_fields__.values()}
            return cls(**{k: v for k, v in raw.items() if k in known})
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
    win32cred.CredWrite(
        {
            "Type": win32cred.CRED_TYPE_GENERIC,
            "TargetName": DEEPSEEK_CREDENTIAL_TARGET,
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
        credential = win32cred.CredRead(
            DEEPSEEK_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception:
        return ""
    blob = credential.get("CredentialBlob", b"")
    if isinstance(blob, bytes):
        return blob.decode("utf-16-le", errors="ignore").rstrip("\x00")
    return str(blob)


def delete_deepseek_api_key() -> None:
    try:
        win32cred.CredDelete(
            DEEPSEEK_CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC, 0
        )
    except Exception:
        pass
