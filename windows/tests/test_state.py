import threading

import pytest

from jev_windows import i18n
from jev_windows.state import ProgressState


def test_poll_returns_only_revision_when_nothing_changed():
    progress = ProgressState("zh-CN")
    first = progress.poll()
    assert first["revision"] == 0
    assert first["phase"] == "idle"
    assert progress.poll(first["revision"]) == {"revision": 0}


def test_update_bumps_revision_and_keeps_messages_translatable():
    progress = ProgressState("zh-CN")
    before = progress.poll()["revision"]
    progress.update(phase="judging", status=i18n.msg("status.judging", count=3))
    after = progress.poll(before)
    assert after["revision"] == before + 1
    assert after["status"] == i18n.translate("status.judging", "zh-CN", count=3)
    assert after["status_message"]["key"] == "status.judging"


def test_language_switch_rerenders_existing_progress_without_changing_the_message():
    progress = ProgressState("zh-CN")
    progress.update(phase="ranking", status=i18n.msg("status.ranking"))
    message = progress.poll()["status_message"]
    progress.set_language("fr")
    current = progress.poll()
    assert current["status"] == i18n.translate("status.ranking", "fr")
    # The structured identity is preserved so re-rendering stays possible.
    assert current["status_message"] == message


def test_exception_status_and_error_are_described_not_stringified():
    progress = ProgressState("zh-CN")
    failure = RuntimeError(i18n.msg("error.jev401"))
    progress.update(phase="error", status=failure, error=failure)
    current = progress.poll()
    assert current["status_message"]["key"] == "error.jev401"
    assert current["error_message"]["key"] == "error.jev401"
    assert current["error"] == i18n.translate("error.jev401", "zh-CN")


def test_plain_string_status_is_preserved_as_is():
    progress = ProgressState("zh-CN")
    progress.update(phase="recognizing", status="正在识别文字")
    current = progress.poll()
    assert current["status"] == "正在识别文字"
    assert current["status_message"] is None


def test_phase_and_snapshot_are_readable_without_holding_the_lock():
    progress = ProgressState("zh-CN")
    assert progress.phase() == "idle"
    progress.update(phase="capturing")
    assert progress.phase() == "capturing"
    assert progress.snapshot()["phase"] == "capturing"


def test_concurrent_updates_do_not_lose_revisions():
    progress = ProgressState("zh-CN")

    def worker(index: int) -> None:
        for _ in range(50):
            progress.update(phase=f"step{index}")

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert progress.revision() == 400


def test_render_failure_free_when_no_message_present():
    progress = ProgressState("zh-CN")
    progress.update(status="", error="")
    current = progress.poll()
    assert current["status"] == ""
    assert current["error"] == ""
