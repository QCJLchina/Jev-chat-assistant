"""Security boundaries use synthetic data and never contact external services."""
import io
import json
import urllib.error
from types import SimpleNamespace

import pytest

from jev_windows import deepseek_client, jev_api, i18n, update_service
from jev_windows.review_limits import validate_draft
from jev_windows.state import ProgressState

SECRET = "Bearer synthetic-secret /private/chat synthetic-chat"


@pytest.mark.parametrize("protocol", sorted(deepseek_client.SUPPORTED_PROTOCOLS))
@pytest.mark.parametrize("status", [401, 403, 402, 429, 500])
def test_http_body_never_read_or_exposed(monkeypatch, protocol, status):
    error = urllib.error.HTTPError("https://test.invalid", status, SECRET, {}, io.BytesIO(SECRET.encode()))
    error.read = lambda *a: pytest.fail("HTTP error body must never be read")
    monkeypatch.setattr(deepseek_client.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(error))
    with pytest.raises(deepseek_client.DeepSeekError) as caught:
        deepseek_client._request_json("https://test.invalid", "messages", "test-key", protocol)
    assert caught.value.status == status
    assert SECRET not in json.dumps(i18n.describe(caught.value))


@pytest.mark.parametrize("status", [401, 403, 422, 429, 500])
def test_jev_body_never_read_even_on_retry(monkeypatch, status):
    calls = []
    def fail(*a, **k):
        calls.append(1)
        error = urllib.error.HTTPError("https://test.invalid", status, SECRET, {}, io.BytesIO(b""))
        error.read = lambda *a: pytest.fail("HTTP error body must never be read")
        raise error
    monkeypatch.setattr(jev_api.urllib.request, "urlopen", fail)
    monkeypatch.setattr(jev_api, "_retry_wait", lambda *a: None)
    with pytest.raises(jev_api.JevApiError) as caught:
        jev_api._post("test-key", {})
    assert caught.value.status == status
    assert len(calls) == (2 if status in (429, 500) else 1)
    assert SECRET not in json.dumps(i18n.describe(caught.value))


def test_unknown_and_nested_errors_never_reach_bridge_or_progress():
    @i18n.bridge_errors
    def fail(self):
        raise RuntimeError(SECRET)
    result = fail(SimpleNamespace(resolved_language="en"))
    progress = ProgressState("en")
    progress.update(error=RuntimeError(SECRET), status=i18n.msg("status.rankFailed", detail=RuntimeError(SECRET)))
    for payload in (result, progress.snapshot(), progress.poll(), progress.rendered()):
        assert SECRET not in str(payload)
    assert i18n.describe(RuntimeError(SECRET))["params"] == {}
    assert isinstance(progress.get("error_message"), dict)
    for locale in i18n.LANGUAGES - {"system"}:
        assert "{detail}" not in i18n.render(result["error_message"], locale)


def test_localized_error_keeps_its_message_while_unknown_stays_generic():
    from jev_windows.i18n import LocalizedError
    progress = ProgressState("en")
    progress.update(error=LocalizedError(i18n.msg("review.rewriteFailed")))
    rendered = progress.poll()
    assert rendered["error_message"] == {"key": "review.rewriteFailed", "params": {}}
    assert SECRET not in str(rendered)
    progress.update(error=RuntimeError(SECRET))
    assert SECRET not in str(progress.poll())


@pytest.mark.parametrize("client", [jev_api, deepseek_client])
def test_network_error_is_fixed_message(monkeypatch, client):
    monkeypatch.setattr(client.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError(SECRET)))
    monkeypatch.setattr(jev_api, "_retry_wait", lambda *a: None)
    with pytest.raises(RuntimeError) as caught:
        client._post("test-key", {})
    assert SECRET not in str(i18n.describe(caught.value))


@pytest.mark.parametrize("count,characters,ok", [(20000, 200000, True), (20001, 1, False), (1, 200001, False)])
def test_draft_capacity_counts_blank_and_unicode(count, characters, ok):
    messages = [{"side": "me", "text": ""} for _ in range(count)]
    messages[0]["text"] = "😀" * characters
    if ok:
        validate_draft(messages, wire=True)
    else:
        with pytest.raises(ValueError):
            validate_draft(messages, wire=True)


@pytest.mark.parametrize("sha", [None, "", "z" * 64, "a" * 63, 123])
def test_update_without_digest_cannot_download_stage_or_apply(monkeypatch, sha):
    service = update_service.UpdateService(ProgressState("en"))
    monkeypatch.setattr(update_service, "fetch_latest_release", lambda: {
        "version": "v99", "download_url": "https://test.invalid", "size": 1, "sha256": sha})
    monkeypatch.setattr(update_service, "download_release", lambda *a, **k: pytest.fail("download"))
    monkeypatch.setattr(update_service, "stage_update", lambda *a: pytest.fail("stage"))
    monkeypatch.setattr(update_service, "apply_staged_update", lambda *a: pytest.fail("apply"))
    assert service.check()["installable"] is False
    with pytest.raises(update_service.UpdateError):
        service.download()
    service._download_worker(dict(service.info))
    assert service.progress.phase() == "error"
    service.progress.update(phase="updateReady")
    with pytest.raises(ValueError):
        service.apply()


@pytest.mark.parametrize("outcome", ["ok", "failure", "cancel", "checksum"])
def test_update_temp_path_is_unique_cleaned_and_version_independent(monkeypatch, outcome):
    service = update_service.UpdateService(ProgressState("en"))
    paths = []
    stages = []
    def download(url, dest, **kwargs):
        paths.append(dest)
        assert dest.name == "package.zip"
        dest.write_bytes(b"synthetic")
        if outcome == "failure":
            raise RuntimeError(SECRET)
        if outcome == "cancel":
            service.cancel.set()
    monkeypatch.setattr(update_service, "download_release", download)
    monkeypatch.setattr(update_service, "verify_sha256", lambda *a: outcome != "checksum")
    monkeypatch.setattr(update_service, "stage_update", lambda path: stages.append(path))
    for _ in range(2):
        service.cancel.clear()
        service._download_worker({"latest_version": "../../escape", "download_url": "fake", "sha256": "a" * 64})
    assert paths[0].parent != paths[1].parent
    assert all(not path.parent.exists() for path in paths)
    assert len(stages) == (2 if outcome == "ok" else 0)
    assert SECRET not in str(service.progress.poll())
