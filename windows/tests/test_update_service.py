"""Update orchestration is testable without network or a real install directory."""
import time

import pytest

from jev_windows import i18n, update_service
from jev_windows.state import ProgressState


@pytest.fixture
def service(monkeypatch):
    monkeypatch.setattr(update_service, "app_install_dir", lambda: None)
    return update_service.UpdateService(ProgressState("zh-CN"))


def _release(version="v9.9.9", sha="a" * 64):
    return {
        "version": version, "download_url": "https://example.test/app.zip",
        "size": 10, "asset_name": "app.zip", "sha256": sha,
    }


def test_check_reports_available_update_and_publishes_to_progress(service, monkeypatch):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release())
    info = service.check()
    assert info["update_available"] is True
    assert info["current_version"] == update_service.__version__
    assert service.progress.poll()["update_info"]["latest_version"] == "v9.9.9"


def test_check_reports_no_update_when_current_is_newer(service, monkeypatch):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release("v0.0.1"))
    assert service.check()["update_available"] is False


def test_download_requires_a_prior_check(service):
    with pytest.raises(ValueError) as caught:
        service.download()
    assert i18n.describe(caught.value)["key"] == "update.notChecked"


def test_download_rejects_a_second_concurrent_attempt(service, monkeypatch):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release())
    service.check()
    alive = type("T", (), {"is_alive": lambda self: True})()
    service.thread = alive
    with pytest.raises(ValueError) as caught:
        service.download()
    assert i18n.describe(caught.value)["key"] == "update.inProgress"


def test_successful_download_verifies_stages_and_reaches_ready(service, monkeypatch, tmp_path):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release())
    service.check()
    staged = {}

    def fake_download(url, dest, expected_size=0, progress_cb=None, cancel_event=None):
        if progress_cb:
            progress_cb(50)
        return dest

    def fake_verify(path, expected):
        staged["verified"] = expected
        return True

    def fake_stage(path):
        staged["staged"] = True
        return tmp_path

    monkeypatch.setattr(update_service, "download_release", fake_download)
    monkeypatch.setattr(update_service, "verify_sha256", fake_verify)
    monkeypatch.setattr(update_service, "stage_update", fake_stage)
    service.download()
    service.thread.join(timeout=5)
    current = service.progress.poll()
    assert current["phase"] == "updateReady"
    assert staged == {"verified": "a" * 64, "staged": True}


def test_checksum_mismatch_aborts_before_staging(service, monkeypatch, tmp_path):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release())
    service.check()
    staged = []
    monkeypatch.setattr(update_service, "download_release", lambda *a, **k: None)
    monkeypatch.setattr(update_service, "verify_sha256", lambda *a, **k: False)
    monkeypatch.setattr(update_service, "stage_update", lambda path: staged.append(path))
    service.download()
    service.thread.join(timeout=5)
    current = service.progress.poll()
    assert current["phase"] == "error"
    assert current["error_message"]["key"] == "update.checksumMismatch"
    assert staged == []


def test_cancelled_download_returns_to_idle_not_error(service, monkeypatch):
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda *a, **k: _release())
    service.check()

    def cancelled(*args, **kwargs):
        raise update_service.UpdateError("update.cancelled")

    monkeypatch.setattr(update_service, "download_release", cancelled)
    service.download()
    service.thread.join(timeout=5)
    current = service.progress.poll()
    assert current["phase"] == "idle"
    assert current["status_message"]["key"] == "update.cancelled"


def test_apply_requires_the_ready_phase(service):
    with pytest.raises(ValueError) as caught:
        service.apply()
    assert i18n.describe(caught.value)["key"] == "update.notReady"


def test_apply_delegates_to_the_updater_once_ready(service, monkeypatch):
    installed = []
    service.progress.update(phase="updateReady")
    monkeypatch.setattr(update_service, "apply_staged_update", lambda path: installed.append(path))
    monkeypatch.setattr(update_service, "app_install_dir", lambda: "INSTALL")
    assert service.apply() == "INSTALL"
    assert installed == ["INSTALL"]


def test_background_check_swallows_failures(monkeypatch):
    """A silent startup check must never raise into the UI."""
    monkeypatch.setattr(
        update_service, "fetch_latest_release",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    service = update_service.UpdateService(ProgressState("zh-CN"))
    service.start_background_check(delay=0)
    service.thread = None
    # Give the daemon thread a moment; it must fail silently.
    for _ in range(50):
        if service.info is not None:
            break
        time.sleep(0.01)
    assert service.info is None
    assert service.progress.phase() == "idle"
