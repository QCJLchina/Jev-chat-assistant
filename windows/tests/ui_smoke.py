from __future__ import annotations

import os
import tempfile

from playwright.sync_api import expect, sync_playwright


FRONTEND_URL = os.environ.get("JEV_FRONTEND_URL", "http://127.0.0.1:5173")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1280, "height": 1100}, device_scale_factor=1)
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.add_init_script("""
            const current = {
              status: '请先配置 Jev API 并框选聊天区域', phase: 'idle', preview: [],
              analysis: null, suggestions: [], error: '', version: 'test', chat_rect: null,
              jev_key_configured: false, relationship: '朋友', allowed_titles: [],
              profiles: [], active_model_id: ''
            };
            window.__bridgeCalls = [];
            window.pywebview = {api: {
              get_state: async () => structuredClone(current),
              fetch_models: async raw => {
                const value = JSON.parse(raw); window.__bridgeCalls.push(['fetch', value]);
                return {models: ['claude-sonnet-test', 'gpt-test']};
              },
              test_model: async raw => {
                window.__bridgeCalls.push(['test', JSON.parse(raw)]);
                return {message: 'OK'};
              },
              save_settings: async raw => {
                const value = JSON.parse(raw); window.__savedSettings = value;
                current.relationship = value.relationship;
                current.allowed_titles = value.allowed_titles;
                current.active_model_id = value.active_model_id;
                current.profiles = value.profiles.map(item => ({
                  id: item.id, name: item.name, base_url: item.base_url, model: item.model,
                  protocol: item.protocol, max_tokens: item.max_tokens,
                  key_configured: Boolean(item.api_key) || Boolean(item.key_configured)
                }));
                current.jev_key_configured = Boolean(value.jev_api_key) || current.jev_key_configured;
                return structuredClone(current);
              },
              start_calibration: async () => ({ok: true}),
              analyze: async () => ({ok: true}),
              set_on_top: async () => ({ok: true}),
              set_active_model: async id => { current.active_model_id = id; return {ok: true}; },
              copy_text: async () => ({ok: true})
            }};
        """)
        page.goto(FRONTEND_URL, wait_until="networkidle")
        expect(page.get_by_role("heading", name="对话分析")).to_be_visible()
        page.get_by_role("button", name="设置").click()
        expect(page.get_by_role("heading", name="Jev 判断服务")).to_be_visible()
        page.get_by_role("button", name="添加模型配置").click()

        dialog = page.locator(".model-dialog")
        expect(dialog).to_be_visible()
        page.set_viewport_size({"width": 820, "height": 620})
        assert page.locator(".dialog-scroll").evaluate("el => el.scrollHeight > el.clientHeight")
        page.screenshot(path=os.path.join(tempfile.gettempdir(), "jev-vue-model-dialog.png"), full_page=True)

        protocol = page.locator("#provider")
        expect(protocol.locator("option")).to_have_count(4)
        protocol.select_option("anthropic")
        page.locator("#provider-name").fill("Anthropic 测试")
        page.locator("#base-url").fill("https://api.anthropic.com/v1/messages")
        page.locator("#model-key").fill("test-secret-not-persisted")
        expect(page.get_by_text("已找到 2 个模型")).to_be_visible(timeout=5000)
        page.locator("#model-name").fill("claude-sonnet-test")
        page.get_by_role("button", name="测试连接").click()
        expect(page.get_by_text("连接成功：OK")).to_be_visible(timeout=3000)
        page.get_by_role("button", name="保存", exact=True).last.click()
        expect(page.get_by_text("Anthropic 测试")).to_be_visible()
        page.get_by_role("button", name="保存设置").click()
        expect(page.get_by_role("heading", name="对话分析")).to_be_visible()
        expect(page.locator("body")).not_to_contain_text("test-secret-not-persisted")
        assert not page.evaluate("Object.values(localStorage).join(' ')").find("test-secret-not-persisted") >= 0
        assert not page_errors, page_errors
        screenshot = os.path.join(tempfile.gettempdir(), "jev-vue-ui-smoke.png")
        page.screenshot(path=screenshot, full_page=True)
        print(f"UI smoke passed; screenshot: {screenshot}")
        browser.close()


if __name__ == "__main__":
    main()
