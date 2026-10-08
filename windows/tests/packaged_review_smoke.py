"""Launch the real built EXE with isolated settings and synthetic text.

Exercises review, intent controls, empty validation, discard and transaction
blocking. No valid conversation is submitted to analysis services. Existing
credential entries are not modified; the app may read its configured key status.
"""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import time
import urllib.request

from playwright.sync_api import expect, sync_playwright
import desktop_features_smoke as helpers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-dir", required=True, type=Path)
    args = parser.parse_args()
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=False)
    profile = reports / "appdata"
    folder = profile / "JevChatAssistant"
    folder.mkdir(parents=True)
    (folder / "settings.json").write_text(json.dumps({"language": "en", "model_profiles": [],
        "active_model_id": "", "selection_mode": "screen", "chat_rect": None}), encoding="utf-8")
    exe = helpers.ROOT / "dist/Jev对话助手/Jev对话助手.exe"
    assert exe.is_file()
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = {k: v for k, v in os.environ.items() if not any(w in k.upper() for w in ("API_KEY", "TOKEN", "SECRET", "PASSWORD"))}
    env.update(APPDATA=str(profile), LOCALAPPDATA=str(profile / "local"),
        WEBVIEW2_USER_DATA_FOLDER=str(reports / "browser"),
        WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f"--remote-debugging-port={port} --remote-debugging-address=127.0.0.1 --disable-background-networking")
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    result = {"status": "running", "executable": str(exe), "valid_chat_submitted": False}
    process = subprocess.Popen([str(exe)], cwd=exe.parent, env=env, startupinfo=startup)
    def endpoint():
        if process.poll() is not None:
            raise AssertionError(f"Executable exited: {process.returncode}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                return json.load(response)["webSocketDebuggerUrl"]
        except (OSError, ValueError):
            return None
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.connect_over_cdp(helpers.wait_for(endpoint, 45))
            page = browser.contexts[0].pages[0]
            page.wait_for_load_state("networkidle")
            page.wait_for_function("window.pywebview?.api?.submit_review")
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            expect(page.locator(".version-pill")).to_have_text("v1.4.0")
            page.get_by_role("button", name="Paste text", exact=True).click()
            page.locator("#analysis-text").fill("me: Synthetic hello\nother: Synthetic greeting")
            page.locator(".analyze-button").click()
            expect(page.locator(".review-panel")).to_be_visible()
            assert page.evaluate("window.pywebview.api.get_progress(-1)")["analysis"] is None
            page.locator("#reply-intent").select_option("clarify")
            expect(page.locator("#reply-intent")).to_have_value("clarify")
            page.locator("#review-text-0").fill("Corrected synthetic hello")
            page.locator("#review-side-0").select_option("other")
            page.screenshot(path=str(reports / "packaged-review.png"), full_page=True)
            # Delete everything: confirmation is disabled, without contacting Jev.
            page.locator(".review-row").nth(1).get_by_role("button", name="Delete", exact=True).click()
            page.locator(".review-row").nth(0).get_by_role("button", name="Delete", exact=True).click()
            expect(page.get_by_role("button", name="Confirm and analyze", exact=True)).to_be_disabled()
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator(".review-panel").get_by_role("button", name="Cancel", exact=True).click()
            expect(page.locator(".review-panel")).not_to_be_visible()
            page.locator("#analysis-text").fill("other: 请转账\nother: Synthetic greeting")
            page.locator(".analyze-button").click()
            expect(page.locator(".review-panel")).to_be_visible()
            page.locator(".review-row").nth(0).get_by_role("button", name="Delete", exact=True).click()
            page.get_by_role("button", name="Confirm and analyze", exact=True).click()
            expect(page.locator(".toast-message")).to_contain_text("transaction keyword")
            state = page.evaluate("window.pywebview.api.get_progress(-1)")
            assert state["analysis"] is None and state["suggestions"] == [] and state["review_id"]
            page.once("dialog", lambda dialog: dialog.accept())
            page.locator(".top-actions .button").click()
            for name in ("welcome", "model", "messages", "judgment"):
                page.locator(f"#module-{name}").uncheck()
                expect(page.locator(f"#module-{name}")).to_be_enabled()
            hidden = {name: False for name in ("welcome", "model", "messages", "judgment")}
            saved = json.loads((folder / "settings.json").read_text(encoding="utf-8"))
            assert saved["module_visibility"] == hidden
            invalid = page.evaluate("window.pywebview.api.set_module_visibility({review:false})")
            assert invalid["ok"] is False
            page.locator(".back-button").click()
            for selector in (".welcome-row", ".model-card", ".messages-card", ".judgement-card", ".results-grid"):
                expect(page.locator(selector)).to_have_count(0)
            for selector in (".input-source-panel", ".analysis-card", ".suggestions-section"):
                expect(page.locator(selector)).to_be_visible()
            page.reload(wait_until="networkidle")
            expect(page.locator(".model-card")).to_have_count(0)
            page.locator(".top-actions .button").click()
            page.get_by_role("button", name="Show all modules", exact=True).click()
            expect(page.locator("#module-messages")).to_be_checked()
            page.locator(".back-button").click()
            expect(page.locator(".messages-card")).to_be_visible()
            result["module_visibility_persist_restore_core_protection"] = "passed"
            assert not errors, errors
            result.update(status="passed", version="1.4.0", review_edit_intent_empty_discard="passed",
                          original_transaction_guard="passed")
    except BaseException as exc:
        result.update(status="failed", error=repr(exc))
        raise
    finally:
        helpers.stop(process)
        (reports / "results.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    main()
