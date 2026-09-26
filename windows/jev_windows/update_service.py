"""In-app update orchestration: check, download, verify, stage, apply.

Extracted from the desktop bridge. Network, checksum and staging live in
`updater`; this layer owns the threading and progress reporting.
"""
from __future__ import annotations

import tempfile
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

    def check(self) -> dict:
        release = fetch_latest_release()
        info = {
            "update_available": compare_versions(__version__, release["version"]) < 0,
            "latest_version": release["version"],
            "current_version": __version__,
            "download_url": release["download_url"],
            "size": release["size"],
            "sha256": release["sha256"],
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
        if self.thread and self.thread.is_alive():
            raise ValueError(msg("update.inProgress"))
        info = self.info
        if not info or not info.get("download_url"):
            raise ValueError(msg("update.notChecked"))
        self.cancel = threading.Event()
        self.progress.update(phase="updating", status=msg("update.downloading"), error=None)
        self.thread = threading.Thread(target=self._download_worker, args=(info,), daemon=True)
        self.thread.start()

    def _download_worker(self, info: dict) -> None:
        temp_zip = Path(tempfile.gettempdir()) / f"jevchat-update-{info['latest_version']}.zip"
        try:
            download_release(
                info["download_url"], temp_zip, expected_size=info.get("size", 0),
                progress_cb=lambda percent: self.progress.update(
                    status=msg("update.downloading", percent=percent),
                ),
                cancel_event=self.cancel,
            )
            if info.get("sha256"):
                self.progress.update(status=msg("update.verifying"))
                if not verify_sha256(temp_zip, info["sha256"]):
                    temp_zip.unlink(missing_ok=True)
                    raise UpdateError("update.checksumMismatch")
            self.progress.update(status=msg("update.staging"))
            stage_update(temp_zip)
            temp_zip.unlink(missing_ok=True)
            self.progress.update(status=msg("update.ready"), phase="updateReady")
        except Exception as exc:
            temp_zip.unlink(missing_ok=True)
            if isinstance(exc, UpdateError) and exc.key == "update.cancelled":
                self.progress.update(phase="idle", status=msg("update.cancelled"))
            else:
                self.progress.update(phase="error", status=exc, error=exc)

    def cancel_download(self) -> None:
        self.cancel.set()

    def apply(self) -> Path:
        """Stage the swap and return the install dir; the caller owns shutdown."""
        if self.progress.phase() != "updateReady":
            raise ValueError(msg("update.notReady"))
        install_dir = app_install_dir()
        apply_staged_update(install_dir)
        return install_dir
