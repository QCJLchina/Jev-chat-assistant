"""Mocked desktop-bridge feature smoke against a running local Vue frontend.

Run: python windows/tests/ui_features_smoke.py
JEV_FRONTEND_URL defaults to http://127.0.0.1:5173; JEV_BROWSER_CHANNEL
optionally selects an installed Chromium browser (e.g. msedge).
Requires Playwright and Chromium. No backend, API keys, OCR, or network APIs.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile

from playwright.sync_api import expect, sync_playwright


FRONTEND_URL = os.environ.get("JEV_FRONTEND_URL", "http://127.0.0.1:5173")
CATALOG = json.loads((Path(__file__).resolve().parents[1] / "locales/en.json").read_text(encoding="utf-8"))

MOCK_BRIDGE = r"""
(() => {
  const defaults = {length: 'short', style: 'natural', language: 'zh-CN'};
  const current = {
    language: 'en', resolved_language: 'en', revision: 0, phase: 'idle',
    status: 'Ready', error: '', preview: [], analysis: null, suggestions: [],
    version: 'test', chat_rect: null, jev_key_configured: true,
    relationship: 'Friends', allowed_titles: [], provider_presets: [],
    profiles: [{id: 'local', name: 'Mock local model', model: 'mock',
      base_url: 'http://localhost:11434/v1', protocol: 'openai-chat',
      key_configured: false, key_required: false, max_tokens: 400}],
    active_model_id: 'local', reply_preferences: {...defaults},
    task_id: null, input_source: null, failed_stage: null, retryable_stages: []
  };
  let serial = 0;
  let nextFailure = null;
  const cancelled = new Set();
  window.__featureCalls = [];
  window.__lateCompletionAttempts = [];
  const clone = () => structuredClone(current);
  const publish = patch => { Object.assign(current, patch); current.revision++; };
  const record = (method, payload) => window.__featureCalls.push({method, payload: structuredClone(payload)});
  const replies = label => [{text: label, probability: null, confidence: null, recommended: false}];
  const finish = (taskId, label) => {
    if (cancelled.has(taskId) || current.task_id !== taskId) return false;
    publish({phase: 'idle', status: label, suggestions: replies(label),
      preview: [{side: 'other', text: 'Mock conversation'}],
      analysis: {true_intent: 'casual_chat', need: 'nothing', best_action: 'acknowledge',
        danger_level: 0, should_reply_now: 1, tension_resolved: 1, latency_ms: 1},
      error: '', failed_stage: null, retryable_stages: []});
    return true;
  };
  const begin = (source, payload) => {
    record(source === 'text' ? 'analyze_text' : 'analyze', payload);
    const taskId = `task-${++serial}`;
    publish({task_id: taskId, input_source: source,
      phase: source === 'text' ? 'judging' : 'capturing', status: 'Running',
      error: '', suggestions: [], preview: [], analysis: null,
      failed_stage: null, retryable_stages: []});
    if (nextFailure) {
      const stage = nextFailure;
      nextFailure = null;
      setTimeout(() => window.__features.fail(stage, source), 100);
    }
    return {ok: true, task_id: taskId};
  };
  window.__features = {
    snapshot: clone,
    queueFailure: stage => { nextFailure = stage; },
    selectArea: () => publish({selection_mode: 'screen', chat_rect: {left: 0, top: 0, right: 800, bottom: 600}}),
    finish: label => finish(current.task_id, label),
    // Inject a backend checkpoint and let the real frontend load it.
    fail: (stage, source) => publish({task_id: `checkpoint-${++serial}`,
      input_source: source, phase: stage === 'rank' ? 'idle' : 'error',
      status: 'Mock stage failed', error: 'Mock stage failed',
      failed_stage: stage, retryable_stages: [stage],
      suggestions: stage === 'rank' ? replies('Unranked reply is still copyable') : []}),
    late: taskId => {
      const accepted = finish(taskId, 'STALE cancelled reply');
      window.__lateCompletionAttempts.push({taskId, accepted});
      return accepted;
    }
  };
  window.pywebview = {api: {
    get_state: async () => clone(),
    get_selection_state: async () => ({selection_mode: current.selection_mode ?? (current.chat_rect ? 'screen' : 'window'),
      selection_binding: current.selection_binding ?? {status: 'none'}, chat_rect: current.chat_rect, selection_revision: 0}),
    get_progress: async known => known === current.revision ? {revision: known} : clone(),
    analyze: async preferences => begin('desktop', preferences ?? null),
    analyze_text: async payload => begin('text', payload),
    cancel_analysis: async taskId => {
      record('cancel_analysis', taskId); cancelled.add(taskId);
      publish({phase: 'idle', status: 'Cancelled', failed_stage: 'judge', retryable_stages: ['judge']});
      return {ok: true};
    },
    retry_analysis: async (taskId, stage) => {
      record('retry_analysis', {task_id: taskId, stage});
      const next = `retry-${++serial}`;
      publish({task_id: next, phase: {capture: 'capturing', judge: 'judging',
        generate: 'generating', rank: 'ranking'}[stage], status: `Retrying ${stage}`,
        error: '', failed_stage: null, retryable_stages: []});
      setTimeout(() => finish(next, `Completed ${stage} retry`), 150);
      return {ok: true, task_id: next};
    },
    save_settings: async raw => {
      const value = JSON.parse(raw); record('save_settings', value);
      publish({reply_preferences: {...value.reply_preferences}, relationship: value.relationship,
        allowed_titles: value.allowed_titles, profiles: value.profiles, active_model_id: value.active_model_id});
      return clone();
    },
    copy_text: async value => { record('copy_text', value); return {ok: true}; },
    start_calibration: async () => {record('start_calibration', null); return {ok: true};},
    set_on_top: async value => {record('set_on_top', value); return {ok: true};},
    set_active_model: async id => {publish({active_model_id: id}); return {ok: true};},
    check_for_updates: async () => ({ok: true, update_available: false, current_version: 'test', latest_version: 'test'}),
    set_language: async language => {publish({language, resolved_language: language}); return clone();}
  }};
})();
"""


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=os.environ.get("JEV_BROWSER_CHANNEL") or None)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 1100})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(MOCK_BRIDGE)
            page.goto(FRONTEND_URL, wait_until="networkidle")

            def button(key: str):
                return page.get_by_role("button", name=CATALOG[key], exact=True)

            def last_call(method: str):
                return page.evaluate("method => window.__featureCalls.filter(c => c.method === method).at(-1)", method)

            expect(page.get_by_role("heading", name=CATALOG["analysis.title"], exact=True)).to_be_visible()
            expect(button("feature.inputDesktop")).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".setup-card")).to_be_visible()
            button("feature.inputText").click()
            expect(page.locator(".setup-card")).to_have_count(0)
            expect(page.locator(".analyze-button")).to_be_disabled()
            text = "me: Are we meeting tomorrow?\nother: Yes, after lunch."
            page.locator("#analysis-text").fill("   ")
            expect(page.locator(".analyze-button")).to_be_disabled()
            page.locator("#analysis-text").fill("x" * 20_001)
            expect(page.locator(".analyze-button")).to_be_disabled()
            expect(page.locator("#text-input-error")).to_have_text(CATALOG["feature.textTooLong"])
            # Match Python's Unicode character limit rather than UTF-16 units.
            page.locator("#analysis-text").fill("😀" * 20_000)
            expect(page.locator(".analyze-button")).to_be_enabled()
            expect(page.locator("#analysis-text")).to_have_attribute("aria-invalid", "false")
            page.locator("#analysis-text").fill(text)
            expect(page.locator(".analyze-button")).to_be_enabled()

            # Persist defaults, then send session overrides without saving them.
            page.locator(".top-actions").get_by_role("button", name=CATALOG["common.settings"], exact=True).click()
            for field, value in {"length": "detailed", "style": "formal", "language": "fr"}.items():
                page.locator(f"#default-{field}").select_option(value)
            button("settings.save").click()
            defaults = {"length": "detailed", "style": "formal", "language": "fr"}
            assert last_call("save_settings")["payload"]["reply_preferences"] == defaults
            button("feature.temporaryPreferences").click()
            page.locator(".temporary-enable input").check()
            overrides = {"length": "short", "style": "gentle", "language": "ja"}
            for field, value in overrides.items():
                page.locator(f"#temporary-{field}").select_option(value)
            page.locator(".analyze-button").click()
            expect(page.locator(".cancel-analysis")).to_be_visible()
            assert last_call("analyze_text")["payload"] == {"text": text, "preferences": overrides,
                "context": {"prior_text": "", "background": "", "message_limit": None}, "intent": "general"}
            assert page.evaluate("window.__features.snapshot().chat_rect") is None
            assert last_call("start_calibration") is None
            assert page.evaluate("window.__features.snapshot().reply_preferences") == defaults
            expect(button("feature.inputDesktop")).to_be_disabled()
            expect(page.locator("#analysis-text")).to_be_disabled()

            # Cancel, start a newer task, and simulate an old worker's completion.
            old_id = page.evaluate("window.__features.snapshot().task_id")
            button("feature.cancelAnalysis").click()
            expect(page.locator(".status-line")).to_contain_text("Cancelled")
            assert last_call("cancel_analysis")["payload"] == old_id
            button("feature.resetOverrides").click()
            page.locator(".analyze-button").click()
            expect(page.locator(".cancel-analysis")).to_be_visible()
            assert last_call("analyze_text")["payload"]["preferences"] == defaults
            assert page.evaluate("id => window.__features.late(id)", old_id) is False
            page.evaluate("window.__features.finish('Fresh current reply')")
            expect(page.locator(".status-line")).to_contain_text("Fresh current reply", timeout=5000)
            expect(page.locator(".suggestion-list")).not_to_contain_text("STALE")

            # Text survives switching back and forth between input sources.
            button("feature.inputDesktop").click()
            expect(page.locator(".setup-card")).to_be_visible()
            button("feature.inputText").click()
            expect(page.locator("#analysis-text")).to_have_value(text)

            # Check all stage-specific retry buttons and their bridge contracts.
            page.evaluate("window.__features.selectArea()")
            for stage in ("capture", "judge", "generate", "rank"):
                button("feature.inputDesktop" if stage == "capture" else "feature.inputText").click()
                page.evaluate("stage => window.__features.queueFailure(stage)", stage)
                page.locator(".analyze-button").click()
                retry_name = CATALOG["feature.retryStage"].replace("{stage}", CATALOG[f"feature.stage{stage.title()}"])
                retry = page.get_by_role("button", name=retry_name, exact=True)
                expect(retry).to_be_visible()
                expect(page.locator(".retry-actions button")).to_have_count(1)
                checkpoint = page.evaluate("window.__features.snapshot().task_id")
                if stage == "rank":
                    expect(page.locator(".suggestion-list")).to_contain_text("Unranked reply is still copyable")
                    page.locator(".copy-button").click()
                    assert last_call("copy_text")["payload"] == "Unranked reply is still copyable"
                    expect(page.locator(".suggestion-confidence")).to_contain_text("—")
                retry.click()
                expect(page.locator(".status-line")).to_contain_text(f"Completed {stage} retry", timeout=5000)
                assert last_call("retry_analysis")["payload"] == {"task_id": checkpoint, "stage": stage}
                assert page.evaluate("window.__features.snapshot().task_id") != checkpoint

            # Capture retries must never be offered for a text-origin task.
            page.evaluate("window.__features.queueFailure('capture')")
            page.locator(".analyze-button").click()
            expect(page.locator(".status-line")).to_contain_text("Mock stage failed", timeout=5000)
            expect(page.locator(".retry-actions button")).to_have_count(0)
            assert not errors, errors
            expect(page.locator("body")).not_to_contain_text("feature.")
            screenshot = os.path.join(tempfile.gettempdir(), "jev-vue-features-smoke.png")
            page.screenshot(path=screenshot, full_page=True)
            print(f"Feature UI smoke passed; screenshot: {screenshot}")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
