"""In-app self-update against GitHub Releases. Standard library only."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

RELEASES_API_URL = "https://api.github.com/repos/QCJLchina/Jev-chat-assistant/releases/latest"
APP_EXE_NAME = "Jev对话助手.exe"
STAGING_DIR_NAME = "_update_staging"
BACKUP_DIR_NAME = "_update_backup"
MANIFEST_NAME = "update_manifest.json"
CHECKSUM_ASSET_NAME = "SHA256SUMS.txt"
CHUNK_BYTES = 256 * 1024


class UpdateError(Exception):
    """Structured update failure the bridge can surface."""


def app_install_dir() -> Path:
    """Directory holding the running packaged app (one level above _internal)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def _asset(payload: dict, suffix: str) -> dict | None:
    for asset in payload.get("assets") or []:
        name = str(asset.get("name", ""))
        if name.lower().endswith(suffix.lower()):
            return asset
    return None


def fetch_latest_release(timeout: float = 10.0) -> dict:
    """Return {version, download_url, size, asset_name, sha256} for the latest release."""
    request = urllib.request.Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "JevChatAssistant-Updater"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise UpdateError("update.httpError") from exc
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise UpdateError("update.networkError") from exc

    if payload.get("draft") or payload.get("prerelease"):
        raise UpdateError("update.noRelease")
    asset = _asset(payload, ".zip")
    if not asset:
        raise UpdateError("update.noAsset")
    tag = str(payload.get("tag_name") or "").strip()
    if not tag:
        raise UpdateError("update.noRelease")
    checksum_asset = _asset(payload, ".txt")
    sha256 = ""
    if checksum_asset and str(checksum_asset.get("name", "")) == CHECKSUM_ASSET_NAME:
        sha256 = _checksum_for(str(checksum_asset.get("browser_download_url", "")), asset.get("name"), timeout)
    return {
        "version": tag,
        "download_url": str(asset.get("browser_download_url", "")),
        "size": int(asset.get("size") or 0),
        "asset_name": str(asset.get("name", "")),
        "sha256": sha256,
    }


def _checksum_for(url: str, asset_name: object, timeout: float) -> str:
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "JevChatAssistant-Updater"})
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, OSError):
        return ""
    for line in text.splitlines():
        parts = line.strip().split(None, 1)
        if len(parts) == 2 and parts[1].strip().strip("*") == str(asset_name):
            digest = parts[0].strip().lower()
            return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else ""
    return ""


def compare_versions(current: str, candidate: str) -> int:
    """-1 when candidate is newer, 0 equal, 1 when current is newer."""

    def parse(value: str) -> tuple[int, ...]:
        core = re.match(r"v?(\d+(?:\.\d+)*)", value.strip().lower())
        return tuple(int(part) for part in core.group(1).split(".")) if core else (0,)

    left, right = parse(current), parse(candidate)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return -1 if right > left else (1 if left > right else 0)


def download_release(
    url: str,
    dest: Path,
    expected_size: int = 0,
    progress_cb=None,
    cancel_event: threading.Event | None = None,
) -> Path:
    """Stream the release asset to dest, calling progress_cb(percent) as it goes."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "JevChatAssistant-Updater"})
    try:
        with urllib.request.urlopen(request, timeout=30) as response, open(dest, "wb") as handle:
            total = int(response.headers.get("Content-Length") or expected_size or 0)
            received = 0
            while True:
                if cancel_event and cancel_event.is_set():
                    handle.close()
                    dest.unlink(missing_ok=True)
                    raise UpdateError("update.cancelled")
                chunk = response.read(CHUNK_BYTES)
                if not chunk:
                    break
                handle.write(chunk)
                received += len(chunk)
                if progress_cb and total:
                    progress_cb(min(99, int(received * 100 / total)))
    except UpdateError:
        raise
    except (urllib.error.URLError, OSError) as exc:
        dest.unlink(missing_ok=True)
        raise UpdateError("update.networkError") from exc
    if expected_size and dest.stat().st_size != expected_size:
        dest.unlink(missing_ok=True)
        raise UpdateError("update.sizeMismatch")
    if progress_cb:
        progress_cb(100)
    return dest


def verify_sha256(path: Path, expected: str) -> bool:
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected or ""):
        return False
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected.lower()


def stage_update(zip_path: Path, install_dir: Path | None = None) -> Path:
    """Extract the downloaded zip into a staging dir and sanity-check its layout."""
    install_dir = install_dir or app_install_dir()
    staging = install_dir / STAGING_DIR_NAME
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    try:
        with zipfile.ZipFile(zip_path) as archive:
            names = archive.namelist()
            if any(name.startswith("/") or ".." in Path(name).parts for name in names):
                raise UpdateError("update.unsafeZip")
            top_prefix = os.path.commonprefix([name for name in names if name.strip()]).split("/")[0]
            entries = {name.split("/")[0] for name in names if name.strip()}
            unpack_into = staging
            if len(entries) == 1 and top_prefix and not top_prefix.endswith(".exe"):
                # Zip wraps everything in a single folder: extract, then hoist.
                inner = staging / "_unwrap"
                archive.extractall(inner)
                staged_children = list(inner.iterdir())
                if len(staged_children) == 1 and staged_children[0].is_dir():
                    for child in staged_children[0].iterdir():
                        shutil.move(str(child), str(staging / child.name))
                shutil.rmtree(inner, ignore_errors=True)
            else:
                archive.extractall(staging)
    except UpdateError:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    except (zipfile.BadZipFile, OSError) as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("update.badZip") from exc

    exe = _find_staged_exe(staging)
    if not exe:
        shutil.rmtree(staging, ignore_errors=True)
        raise UpdateError("update.stagingInvalid")
    return staging


def _find_staged_exe(staging: Path) -> Path | None:
    candidate = staging / APP_EXE_NAME
    if candidate.exists():
        return candidate
    for path in staging.rglob(APP_EXE_NAME):
        return path
    return None


def apply_staged_update(install_dir: Path | None = None, helper_path: Path | None = None) -> None:
    """Hand control to the helper process; this process must exit immediately."""
    install_dir = install_dir or app_install_dir()
    staging = install_dir / STAGING_DIR_NAME
    if not _find_staged_exe(staging):
        raise UpdateError("update.stagingInvalid")
    manifest = {
        "install_dir": str(install_dir),
        "staging_dir": str(staging),
        "backup_dir": str(install_dir / BACKUP_DIR_NAME),
        "exe_name": APP_EXE_NAME,
    }
    manifest_path = install_dir / MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    helper = helper_path or install_dir / "update_helper.exe"
    if not helper.exists():
        manifest_path.unlink(missing_ok=True)
        raise UpdateError("update.helperMissing")
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([str(helper)], cwd=str(install_dir), close_fds=True, creationflags=flags)
    os._exit(0)


def run_update_helper(install_dir: Path) -> int:
    """Entry point for update_helper.exe. Returns a process exit code."""
    manifest_path = install_dir / MANIFEST_NAME
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return 2
    install = Path(manifest["install_dir"])
    staging = Path(manifest["staging_dir"])
    backup = Path(manifest["backup_dir"])
    exe_name = manifest.get("exe_name") or APP_EXE_NAME
    if not (staging / exe_name).exists():
        return 3
    if install.exists():
        try:
            shutil.move(str(install), str(backup))
        except OSError:
            return 4
    try:
        shutil.move(str(staging), str(install))
    except OSError:
        shutil.move(str(backup), str(install))
        return 5
    shutil.rmtree(backup, ignore_errors=True)
    shutil.rmtree(staging, ignore_errors=True)
    manifest_path.unlink(missing_ok=True)
    subprocess.Popen(
        [str(install / exe_name)],
        cwd=str(install),
        close_fds=True,
        creationflags=getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
    )
    return 0


def _run_helper_cli() -> int:
    if len(sys.argv) > 1:
        return run_update_helper(Path(sys.argv[1]).resolve().parent)
    if getattr(sys, "frozen", False):
        return run_update_helper(Path(sys.executable).resolve().parent)
    return run_update_helper(Path.cwd())


if __name__ == "__main__":
    sys.exit(_run_helper_cli())
