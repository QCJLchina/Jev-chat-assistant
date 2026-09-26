import io
import json
import threading
import zipfile

import pytest

from jev_windows import updater


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def headers(self):  # pragma: no cover - urllib uses mapping attribute
        return {}


def _patch_urlopen(monkeypatch, payloads: dict):
    """Patch urllib.urlopen with a handler keyed by URL substring."""
    def fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        for fragment, body in payloads.items():
            if fragment in url:
                response = FakeResponse(body if isinstance(body, bytes) else body.encode("utf-8"))
                response.headers = {"Content-Length": str(len(body))}
                return response
        raise AssertionError(f"unexpected url {url}")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)


def test_compare_versions_orders_semantically():
    assert updater.compare_versions("1.1.1", "v1.2.0") == -1
    assert updater.compare_versions("1.1.1", "1.1.1") == 0
    assert updater.compare_versions("v1.10.0", "1.9.9") == 1
    assert updater.compare_versions("1.1", "1.1.1") == -1
    assert updater.compare_versions("1.2.0-beta", "1.2.0") == 0


def test_fetch_latest_release_parses_assets(monkeypatch):
    release_payload = json.dumps({
        "tag_name": "v1.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {"name": "Jev对话助手.zip", "size": 1024, "browser_download_url": "https://example.com/app.zip"},
            {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": "https://example.com/SHA256SUMS.txt"},
        ],
    })
    sums = "0" * 64 + "  Jev对话助手.zip\n"
    _patch_urlopen(monkeypatch, {"api.github.com": release_payload, "SHA256SUMS.txt": sums})
    info = updater.fetch_latest_release()
    assert info["version"] == "v1.2.0"
    assert info["download_url"] == "https://example.com/app.zip"
    assert info["size"] == 1024
    assert info["sha256"] == "0" * 64


def test_fetch_latest_release_uses_asset_digest(monkeypatch):
    """GitHub supplies a per-asset digest; it takes precedence and needs no extra request."""
    release_payload = json.dumps({
        "tag_name": "v1.2.0",
        "draft": False,
        "prerelease": False,
        "assets": [
            {
                "name": "Jev-Chat-Assistant-v1.2.0-windows-x64.zip", "size": 1024,
                "browser_download_url": "https://example.com/app.zip",
                "digest": "sha256:" + "a" * 64,
            },
            {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": "https://example.com/SHA256SUMS.txt"},
        ],
    })
    called: list[str] = []

    def spy(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else str(request)
        called.append(url)
        if "SHA256SUMS.txt" in url:
            raise AssertionError("digest present -> checksum file must not be fetched")
        response = FakeResponse(release_payload.encode("utf-8"))
        response.headers = {"Content-Length": str(len(release_payload))}
        return response
    monkeypatch.setattr(updater.urllib.request, "urlopen", spy)

    info = updater.fetch_latest_release()
    assert info["sha256"] == "a" * 64
    assert len(called) == 1 and "api.github.com" in called[0]


def test_fetch_latest_release_falls_back_to_checksum_file(monkeypatch):
    release_payload = json.dumps({
        "tag_name": "v1.2.0", "draft": False, "prerelease": False,
        "assets": [
            {"name": "app.zip", "size": 10, "browser_download_url": "https://example.com/app.zip"},
            {"name": "SHA256SUMS.txt", "size": 100, "browser_download_url": "https://example.com/SHA256SUMS.txt"},
        ],
    })
    sums = "b" * 64 + "  app.zip\n"
    _patch_urlopen(monkeypatch, {"api.github.com": release_payload, "SHA256SUMS.txt": sums})
    assert updater.fetch_latest_release()["sha256"] == "b" * 64


@pytest.mark.parametrize("digest", ["", "sha256:not-hex", "md5:" + "a" * 64, "sha256:" + "a" * 63])
def test_fetch_latest_release_ignores_unusable_digest(monkeypatch, digest):
    asset = {"name": "app.zip", "size": 10, "browser_download_url": "https://example.com/app.zip"}
    if digest:
        asset["digest"] = digest
    release_payload = json.dumps({"tag_name": "v1.2.0", "draft": False, "prerelease": False, "assets": [asset]})
    _patch_urlopen(monkeypatch, {"api.github.com": release_payload})
    assert updater.fetch_latest_release()["sha256"] == ""


def test_fetch_latest_release_skips_prerelease(monkeypatch):
    release_payload = json.dumps({"tag_name": "v2.0.0", "draft": False, "prerelease": True, "assets": []})
    _patch_urlopen(monkeypatch, {"api.github.com": release_payload})
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release()


def test_fetch_latest_release_network_error(monkeypatch):
    def boom(request, timeout=None):
        raise updater.urllib.error.URLError("down")
    monkeypatch.setattr(updater.urllib.request, "urlopen", boom)
    with pytest.raises(updater.UpdateError):
        updater.fetch_latest_release()


def test_download_release_streams_and_reports_progress(monkeypatch, tmp_path):
    body = b"x" * 1024
    _patch_urlopen(monkeypatch, {"example.com/blob": body})
    dest = tmp_path / "out.zip"
    seen = []
    updater.download_release("https://example.com/blob", dest, expected_size=len(body), progress_cb=seen.append)
    assert dest.read_bytes() == body
    assert seen[-1] == 100


def test_download_release_rejects_size_mismatch(monkeypatch, tmp_path):
    _patch_urlopen(monkeypatch, {"example.com/blob": b"short"})
    dest = tmp_path / "out.zip"
    with pytest.raises(updater.UpdateError):
        updater.download_release("https://example.com/blob", dest, expected_size=999)
    assert not dest.exists()


def test_download_release_honors_cancel(monkeypatch, tmp_path):
    class BigResponse(io.BytesIO):
        headers = {"Content-Length": str(10 * 1024 * 1024)}
        def read(self, amount=-1):
            return b"a" * amount

    def fake_urlopen(request, timeout=None):
        return BigResponse(b"")
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    dest = tmp_path / "out.zip"
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(updater.UpdateError):
        updater.download_release("https://example.com/blob", dest, cancel_event=cancel)
    assert not dest.exists()


def test_verify_sha256(tmp_path):
    import hashlib
    data = b"payload"
    path = tmp_path / "pkg.zip"
    path.write_bytes(data)
    digest = hashlib.sha256(data).hexdigest()
    assert updater.verify_sha256(path, digest)
    assert not updater.verify_sha256(path, "f" * 64)
    assert not updater.verify_sha256(path, "")  # absent checksum never verifies


def _make_zip(tmp_path, exe_name=updater.APP_EXE_NAME, wrap=False):
    zip_path = tmp_path / "pkg.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        if wrap:
            archive.writestr("Jev对话助手/" + exe_name, b"MZ")
            archive.writestr("Jev对话助手/_internal/locales/zh-CN.json", "{}")
        else:
            archive.writestr(exe_name, b"MZ")
            archive.writestr("_internal/locales/zh-CN.json", "{}")
    return zip_path


def test_stage_update_accepts_flat_zip(tmp_path):
    zip_path = _make_zip(tmp_path)
    staging = updater.stage_update(zip_path, install_dir=tmp_path)
    assert (staging / updater.APP_EXE_NAME).exists()


def test_stage_update_unwraps_single_folder(tmp_path):
    zip_path = _make_zip(tmp_path, wrap=True)
    staging = updater.stage_update(zip_path, install_dir=tmp_path)
    assert (staging / updater.APP_EXE_NAME).exists()
    assert (staging / "_internal" / "locales" / "zh-CN.json").exists()


def test_stage_update_rejects_zip_without_exe(tmp_path):
    zip_path = tmp_path / "bad.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("readme.txt", "no exe here")
    with pytest.raises(updater.UpdateError):
        updater.stage_update(zip_path, install_dir=tmp_path)
    assert not (tmp_path / updater.STAGING_DIR_NAME).exists()


def test_apply_staged_update_writes_manifest(monkeypatch, tmp_path):
    staging = tmp_path / updater.STAGING_DIR_NAME
    staging.mkdir()
    (staging / updater.APP_EXE_NAME).write_bytes(b"MZ")
    helper = tmp_path / "update_helper.exe"
    helper.write_bytes(b"MZ")
    exit_calls = []
    monkeypatch.setattr(updater.os, "_exit", lambda code: exit_calls.append(code))
    launched = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: launched.append(args))
    updater.apply_staged_update(install_dir=tmp_path, helper_path=helper)
    manifest = json.loads((tmp_path / updater.MANIFEST_NAME).read_text(encoding="utf-8"))
    assert manifest["staging_dir"] == str(staging)
    assert manifest["install_dir"] == str(tmp_path)
    assert manifest["backup_dir"] == str(tmp_path / updater.BACKUP_DIR_NAME)
    assert launched and exit_calls == [0]


def test_apply_staged_update_requires_helper(monkeypatch, tmp_path):
    staging = tmp_path / updater.STAGING_DIR_NAME
    staging.mkdir()
    (staging / updater.APP_EXE_NAME).write_bytes(b"MZ")
    with pytest.raises(updater.UpdateError):
        updater.apply_staged_update(install_dir=tmp_path, helper_path=tmp_path / "missing.exe")
    assert not (tmp_path / updater.MANIFEST_NAME).exists()


def test_run_update_helper_swaps_and_restarts(tmp_path, monkeypatch):
    install = tmp_path / "install"
    staging = tmp_path / "staging"
    install.mkdir()
    staging.mkdir()
    (install / updater.APP_EXE_NAME).write_bytes(b"OLD")
    (staging / updater.APP_EXE_NAME).write_bytes(b"NEW")
    (staging / "extra.dll").write_bytes(b"x")
    manifest_path = tmp_path / updater.MANIFEST_NAME
    manifest_path.write_text(json.dumps({
        "install_dir": str(install), "staging_dir": str(staging),
        "backup_dir": str(tmp_path / updater.BACKUP_DIR_NAME), "exe_name": updater.APP_EXE_NAME,
    }), encoding="utf-8")
    launched = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: launched.append(args))
    code = updater.run_update_helper(tmp_path)
    assert code == 0
    assert (install / updater.APP_EXE_NAME).read_bytes() == b"NEW"
    assert (install / "extra.dll").exists()
    assert not (tmp_path / updater.BACKUP_DIR_NAME).exists()
    assert not staging.exists()
    assert not manifest_path.exists()
    assert launched


def test_run_update_helper_rolls_back_when_staging_broken(tmp_path, monkeypatch):
    install = tmp_path / "install"
    staging = tmp_path / "staging"
    install.mkdir()
    staging.mkdir()
    (install / updater.APP_EXE_NAME).write_bytes(b"OLD")
    # staging lacks the exe -> immediate failure, nothing moved
    manifest_path = tmp_path / updater.MANIFEST_NAME
    manifest_path.write_text(json.dumps({
        "install_dir": str(install), "staging_dir": str(staging),
        "backup_dir": str(tmp_path / updater.BACKUP_DIR_NAME), "exe_name": updater.APP_EXE_NAME,
    }), encoding="utf-8")
    code = updater.run_update_helper(tmp_path)
    assert code == 3
    assert (install / updater.APP_EXE_NAME).read_bytes() == b"OLD"


def test_run_update_helper_reverses_failed_move(tmp_path, monkeypatch):
    install = tmp_path / "install"
    staging = tmp_path / "staging"
    install.mkdir()
    staging.mkdir()
    (install / updater.APP_EXE_NAME).write_bytes(b"OLD")
    (staging / updater.APP_EXE_NAME).write_bytes(b"NEW")
    manifest_path = tmp_path / updater.MANIFEST_NAME
    manifest_path.write_text(json.dumps({
        "install_dir": str(install), "staging_dir": str(staging),
        "backup_dir": str(tmp_path / updater.BACKUP_DIR_NAME), "exe_name": updater.APP_EXE_NAME,
    }), encoding="utf-8")

    real_move = updater.shutil.move
    def move_that_fails_second(src, dst):
        if str(src) == str(staging):
            raise OSError("disk full")
        return real_move(src, dst)
    monkeypatch.setattr(updater.shutil, "move", move_that_fails_second)
    monkeypatch.setattr(updater.subprocess, "Popen", lambda args, **kw: (_ for _ in ()).throw(AssertionError("no restart on failure")))
    code = updater.run_update_helper(tmp_path)
    assert code == 5
    assert (install / updater.APP_EXE_NAME).read_bytes() == b"OLD"
