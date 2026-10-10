"""In-app update orchestration: check, download, verify, stage, apply.

Extracted from the desktop bridge. Network, checksum and staging live in
`updater`; this layer owns the threading and progress reporting.
"""
from __future__ import annotations

import tempfile
import re
import threading
from pathlib import Path

from . import __version__
from .i18n import msg
from .state import ProgressState
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


class UpdateService:
    """Owns the background update worker and its cancel flag."""

    def __init__(self, progress: ProgressState):
        self.progress = progress
        self.info: dict | None = None
        self.cancel = threading.Event()
        self.thread: threading.Thread | None = None
        self._verified_ready = False

    def check(self) -> dict:
        release = fetch_latest_release()
        installable = self._valid_digest(release.get("sha256"))
        info = {
            "update_available": compare_versions(__version__, release["version"]) < 0,
            "latest_version": release["version"],
            "current_version": __version__,
            "download_url": release["download_url"],
            "size": release["size"],
            "sha256": release["sha256"],
            "installable": installable,
            "blocked_reason": None if installable else "update.checksumRequired",
        }
        self.info = info
        self.progress.update(update_info=info)
        return info

    def start_background_check(self, delay: float = 3.0) -> None:
        """Silent check shortly after startup; never blocks or surfaces errors."""

        def worker() -> None:
            threading.Event().wait(delay)
            try:
                self.check()
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def download(self) -> None:
        with self.progress.lock:
            if self.progress.phase() not in {"idle", "error", "updateReady"}:
                raise ValueError(msg("error.busy"))
            if self.thread and self.thread.is_alive():
                raise ValueError(msg("update.inProgress"))
            info = self.info
            if not info or not info.get("download_url"):
                raise ValueError(msg("update.notChecked"))
            if not self._valid_digest(info.get("sha256")):
                raise UpdateError("update.checksumRequired")
            self._verified_ready = False
            self.cancel = threading.Event()
            self.progress.update(phase="updating", status=msg("update.downloading"), error=None)
            self.thread = threading.Thread(target=self._download_worker, args=(dict(info),), daemon=True)
            self.thread.start()

    @staticmethod
    def _valid_digest(value) -> bool:
        return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{64}", value) is not None

    def _download_worker(self, info: dict) -> None:
        self._verified_ready = False
        try:
            if not self._valid_digest(info.get("sha256")):
                raise UpdateError("update.checksumRequired")
            with tempfile.TemporaryDirectory(prefix="jevchat-update-") as temp_dir:
                temp_zip = Path(temp_dir) / "package.zip"
                download_release(
                    info["download_url"], temp_zip, expected_size=info.get("size", 0),
                    progress_cb=lambda percent: self.progress.update(
                        status=msg("update.downloading", percent=percent),
                    ),
                    cancel_event=self.cancel,
                )
                if self.cancel.is_set():
                    raise UpdateError("update.cancelled")
                self.progress.update(status=msg("update.verifying"))
                if not verify_sha256(temp_zip, info["sha256"]):
                    raise UpdateError("update.checksumMismatch")
                if self.cancel.is_set():
                    raise UpdateError("update.cancelled")
                self.progress.update(status=msg("update.staging"))
                stage_update(temp_zip)
            if self.cancel.is_set():
                raise UpdateError("update.cancelled")
            self._verified_ready = True
            self.progress.update(status=msg("update.ready"), phase="updateReady")
        except Exception as exc:
            self._verified_ready = False
            if isinstance(exc, UpdateError) and exc.key == "update.cancelled":
                self.progress.update(phase="idle", status=msg("update.cancelled"))
            else:
                self.progress.update(phase="error", status=exc, error=exc)

    def cancel_download(self) -> None:
        self.cancel.set()

    def apply(self) -> Path:
        """Stage the swap and return the install dir; the caller owns shutdown."""
        if self.progress.phase() != "updateReady" or not self._verified_ready:
            raise ValueError(msg("update.notReady"))
        install_dir = app_install_dir()
        apply_staged_update(install_dir)
        return install_dir
