"""Real Vue/WebView2/bridge review and rewrite smoke with isolated synthetic services.

No user settings, credentials, clipboard, desktop pixels or remote APIs are used.
Run with project Python: desktop_review_smoke.py --report-dir <new directory>.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
import threading
import time
import urllib.request

import desktop_features_smoke as helpers

ROOT = helpers.ROOT


def child(profile, events):
    sys.path[:0] = [str(ROOT / "windows"), str(ROOT)]
    import win32cred
    import win32clipboard
    import webview
    from PIL import ImageGrab

    lock = threading.Lock()
    def record(stage, **values):
        with lock, events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"stage": stage, **values}, ensure_ascii=False) + "\n")

    def forbidden(*args, **kwargs):
        record("forbidden_call")
        raise AssertionError("Real credentials, clipboard, pixels and remote services are forbidden")

    assert Path(os.environ["APPDATA"]).resolve() == profile.resolve()
    record("child_started", pid=os.getpid())
    for name in ("CredRead", "CredWrite", "CredDelete", "CredEnumerate"):
        setattr(win32cred, name, forbidden)
    win32clipboard.OpenClipboard = forbidden
    ImageGrab.grab = ImageGrab.grabclipboard = forbidden
    from jev_windows import config
    config.load_api_key = lambda: "fixture-judge"
    config.load_model_api_key = lambda *_: "fixture-model"
    from jev_windows import app, analysis, task_controller, windows_api
    from jev_windows.models import Analysis, ChatSnapshot, Message
    for module in (app, analysis, task_controller):
        module.load_api_key = config.load_api_key
        module.load_model_api_key = config.load_model_api_key
    urllib.request.urlopen = forbidden
    app.DesktopApi.start_background_check = lambda *_: None
    app.UpdateService.check = lambda *_: dict(ok=True, update_available=False,
        current_version="fixture", latest_version="fixture")
    def capture(*args, **kwargs):
        record("capture")
        return ChatSnapshot("fixture", [Message("other", "OCR greeting"), Message("me", "OCR answer")],
                            "OCR greeting\nOCR answer")
    analysis.AnalysisService.capture = capture
    def judge(snapshot, relationship, key, **kwargs):
        record("judge", messages=[vars(m) for m in snapshot.messages])
        return Analysis(true_intent="casual_chat", need="nothing", best_action="acknowledge")
    def generate(*args, **kwargs):
        record("generate", intent=kwargs.get("intent", "general"), preferences=kwargs["preferences"])
        return ["Fixture first", "Fixture second", "Fixture third"]
    def rank(snapshot, relationship, replies, key, **kwargs):
        record("rank", replies=replies)
        return [dict(text=r, probability=.8 if i == 0 else .1, confidence=None, recommended=i == 0)
                for i, r in enumerate(replies)]
    failures = {"natural": True}
    def rewrite(*args, **kwargs):
        action = args[4]
        record("rewrite", action=action, intent=kwargs["intent"], text=args[3])
        if failures.get(action):
            failures[action] = False
            raise RuntimeError("Synthetic retryable failure")
        if action == "gentle":
            time.sleep(1)
        return args[3] + " / " + action
    analysis.judge, analysis.generate_suggestions, analysis.recommend_replies = judge, generate, rank
    task_controller.rewrite_reply = rewrite
    windows_api.ensure_dpi_awareness()
    api = app.DesktopApi()
    window = webview.create_window("Jev isolated review smoke", helpers.FRONTEND.as_uri(), width=980, height=760)
    api.window = window
    window.expose(*(getattr(api, name) for name in vars(app.DesktopApi)
                    if not name.startswith("_") and callable(getattr(api, name))))
    webview.start(gui="edgechromium", debug=False, storage_path=os.environ["WEBVIEW2_USER_DATA_FOLDER"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--child", action="store_true")
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--report-dir", type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.profile, args.events)
        return
    from playwright.sync_api import expect, sync_playwright
    sys.path[:0] = [str(ROOT / "windows"), str(ROOT)]
    from jev_windows.config import AppConfig, ModelProfile
    from jev_windows.models import Rect
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=False)
    profile = reports / "appdata"
    settings_dir = profile / "JevChatAssistant"
    settings_dir.mkdir(parents=True)
    settings = AppConfig(language="en", selection_mode="screen", chat_rect=Rect(0, 0, 500, 400),
        model_profiles=[ModelProfile("fixture", "Fixture", "https://fixture.invalid", "fixture-model")],
        active_model_id="fixture")
    (settings_dir / "settings.json").write_text(json.dumps(asdict(settings)), encoding="utf-8")
    events = reports / "events.jsonl"
    result = {"status": "running", "remote_services": False, "real_bridge": True}
    process = None
    helpers.__file__ = str(Path(__file__).resolve())
    def records():
        return [json.loads(line) for line in events.read_text(encoding="utf-8").splitlines()]
    try:
        with (reports / "child.log").open("w", encoding="utf-8") as log, sync_playwright() as playwright:
            process, endpoint = helpers.launch(profile, events, log)
            browser = playwright.chromium.connect_over_cdp(endpoint)
            page = browser.contexts[0].pages[0]
            page.wait_for_load_state("networkidle")
            page.wait_for_function("window.pywebview?.api?.submit_review")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            def state():
                return page.evaluate("window.pywebview.api.get_progress(-1)")
            def click(name):
                page.get_by_role("button", name=name, exact=True).click()

            # Native bridge capture ends at review without external stages.
            page.locator(".analyze-button").click()
            expect(page.locator(".review-panel")).to_be_visible()
            assert [r["stage"] for r in records() if r["stage"] in {"capture", "judge", "generate", "rank"}] == ["capture"]
            page.locator("#review-text-0").fill("Corrected OCR greeting")
            page.locator("#review-side-0").select_option("me")
            click("Add message")
            page.locator("#review-text-2").fill("Added message")
            page.locator(".review-row").nth(2).get_by_role("button", name="Move up").click()
            page.locator(".review-row").nth(2).get_by_role("button", name="Delete").click()
            page.locator("#reply-intent").select_option("decline")
            page.screenshot(path=str(reports / "review.png"), full_page=True)
            click("Confirm and analyze")
            expect(page.locator(".suggestion-list")).to_contain_text("Fixture first")
            helpers.wait_for(lambda: state()["ranking_valid"])
            assert next(r for r in records() if r["stage"] == "judge")["messages"] == [
                {"side": "me", "text": "Corrected OCR greeting"}, {"side": "other", "text": "Added message"}]
            assert next(r for r in records() if r["stage"] == "generate")["intent"] == "decline"
            first = page.locator(".suggestion-item").nth(0)
            first.get_by_role("button", name="Make shorter", exact=True).click()
            expect(first).to_contain_text("Fixture first / shorter")
            expect(page.get_by_role("button", name="Rank again", exact=True)).to_be_visible()
            assert not state()["ranking_valid"]
            assert state()["suggestions"][1]["text"] == "Fixture second"
            first.get_by_role("button", name="More natural", exact=True).click()
            # Failure reasons from model responses are never surfaced; the panel
            # shows a fixed localized message plus a retry action.
            expect(page.locator(".analysis-recovery")).to_contain_text("Rewrite failed")
            assert "Synthetic retryable failure" not in page.locator(".analysis-recovery").inner_text()
            assert state()["suggestions"][0]["text"] == "Fixture first / shorter"
            page.locator(".retry-actions").get_by_role("button", name="Retry Rewrite", exact=True).click()
            expect(first).to_contain_text("Fixture first / shorter / natural")
            first.get_by_role("button", name="Undo last rewrite", exact=True).click()
            expect(first.locator("p")).to_contain_text("Fixture first / shorter")
            first.get_by_role("button", name="Undo last rewrite", exact=True).click()
            expect(first.locator("p")).to_have_text("Fixture first")
            click("Rank again")
            helpers.wait_for(lambda: state()["ranking_valid"])
            expect(page.locator(".recommend-badge")).to_have_text("Recommended")
            first.get_by_role("button", name="More tactful", exact=True).click()
            page.locator(".cancel-analysis").click()
            helpers.wait_for(lambda: state()["phase"] == "idle")
            assert state()["suggestions"][0]["text"] == "Fixture first"
            result["capture_edit_intent_rewrite_retry_undo_rank_cancel"] = "passed"

            click("Paste text")
            page.locator("#analysis-text").fill("me: Hello\nother: Good morning")
            page.locator(".analyze-button").click()
            expect(page.locator(".review-panel")).to_be_visible()
            for width, height in [(980, 760), (760, 620)]:
                page.set_viewport_size({"width": width, "height": height})
                for locale in ("zh-CN", "en", "fr", "ru", "ja", "ko"):
                    page.evaluate("locale => window.pywebview.api.set_language(locale)", locale)
                    page.reload(wait_until="networkidle")
                    catalog = json.loads((ROOT / "windows/locales" / f"{locale}.json").read_text(encoding="utf-8"))
                    expect(page.locator(".review-panel h2")).to_have_text(catalog["review.title"])
                    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
                    page.screenshot(path=str(reports / f"review-{locale}-{width}.png"), full_page=True)
            result["six_languages_two_sizes"] = "passed"
            page.evaluate("window.pywebview.api.set_language('en')")
            page.reload(wait_until="networkidle")
            expect(page.locator(".review-panel h2")).to_have_text("Review conversation")
            page.locator("#review-text-0").fill("Unsaved edit")
            page.once("dialog", lambda dialog: dialog.dismiss())
            click("Desktop capture")
            expect(page.locator(".review-panel")).to_be_visible()
            expect(page.locator("#review-text-0")).to_have_value("Unsaved edit")
            page.once("dialog", lambda dialog: dialog.accept())
            click("Desktop capture")
            expect(page.locator(".review-panel")).not_to_be_visible()
            assert state()["review_messages"] == []
            result["draft_switch_confirmation"] = "passed"
            click("Paste text")
            page.locator("#analysis-text").fill("other: 请转账\nother: hello")
            page.locator(".analyze-button").click()
            expect(page.locator(".review-panel")).to_be_visible()
            page.locator(".review-row").nth(0).get_by_role("button", name="Delete").click()
            count = sum(r["stage"] == "judge" for r in records())
            click("Confirm and analyze")
            expect(page.locator(".toast-message")).to_be_visible()
            assert sum(r["stage"] == "judge" for r in records()) == count
            assert state()["review_id"]
            result["deleted_transaction_blocked"] = "passed"
            assert not errors, errors
            assert not any(r["stage"] == "forbidden_call" for r in records())
            result["status"] = "passed"
    except BaseException as exc:
        result.update(status="failed", error=repr(exc))
        raise
    finally:
        if process:
            helpers.stop(process)
        (reports / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
