from __future__ import annotations

import os
import tempfile

from playwright.sync_api import expect, sync_playwright


FRONTEND_URL = os.environ.get("JEV_FRONTEND_URL", "http://127.0.0.1:5173")


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            channel=os.environ.get("JEV_BROWSER_CHANNEL") or None,
        )
        page = browser.new_page(viewport={"width": 1280, "height": 1100}, device_scale_factor=1)
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.add_init_script("""
            const current = {
              revision: 0, status: '请先配置 Jev API 并框选聊天区域', phase: 'idle', preview: [],
              analysis: null, suggestions: [], error: '', version: 'test', chat_rect: {left: 0, top: 0, right: 800, bottom: 600}, selection_mode: 'screen',
              jev_key_configured: false, relationship: '朋友', allowed_titles: [],
              provider_presets: [{"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "default_model": "deepseek-flash", "protocol": "openai-chat", "suggested_models": ["deepseek-v4-pro"], "key_site": "platform.deepseek.com", "local": false, "models": ["deepseek-flash", "deepseek-v4-pro"]}, {"id": "dashscope", "name": "通义千问（阿里云百炼·北京）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen3.8-flash", "protocol": "openai-chat", "suggested_models": ["qwen3.7-plus", "qwen3.8-max"], "key_site": "bailian.console.aliyun.com", "local": false, "models": ["qwen3.8-flash", "qwen3.7-plus", "qwen3.8-max"]}, {"id": "moonshot", "name": "Kimi（月之暗面）", "base_url": "https://api.moonshot.cn/v1", "default_model": "kimi-k3", "protocol": "openai-chat", "suggested_models": [], "key_site": "platform.kimi.com", "local": false, "models": ["kimi-k3"]}, {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-5.3", "protocol": "openai-chat", "suggested_models": ["glm-5.3-flash"], "key_site": "bigmodel.cn", "local": false, "models": ["glm-5.3", "glm-5.3-flash"]}, {"id": "ark", "name": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-seed-2.0", "protocol": "openai-chat", "suggested_models": [], "key_site": "console.volcengine.com/ark", "local": false, "models": ["doubao-seed-2.0"]}, {"id": "siliconflow", "name": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "default_model": "deepseek-ai/DeepSeek-V3.2", "protocol": "openai-chat", "suggested_models": ["Pro/moonshotai/Kimi-K2.6"], "key_site": "cloud.siliconflow.cn", "local": false, "models": ["deepseek-ai/DeepSeek-V3.2", "Pro/moonshotai/Kimi-K2.6"]}, {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-6.1-sol", "protocol": "openai-responses", "suggested_models": ["gpt-6-luna"], "key_site": "platform.openai.com", "local": false, "models": ["gpt-6.1-sol", "gpt-6-luna"]}, {"id": "anthropic", "name": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "default_model": "claude-sonnet-5-5", "protocol": "anthropic", "suggested_models": [], "key_site": "platform.claude.com", "local": false, "models": ["claude-sonnet-5-5"]}, {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-3.8-flash", "protocol": "openai-chat", "suggested_models": [], "key_site": "aistudio.google.com", "local": false, "models": ["gemini-3.8-flash"]}, {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_model": "google/gemini-3.8-flash", "protocol": "openai-chat", "suggested_models": [], "key_site": "openrouter.ai", "local": false, "models": ["google/gemini-3.8-flash"]}, {"id": "ollama", "name": "Ollama（本地）", "base_url": "http://localhost:11434/v1", "default_model": "qwen3", "protocol": "openai-chat", "suggested_models": [], "key_site": "", "local": true, "models": ["qwen3"]}], profiles: [], active_model_id: ''
            };
            window.__bridgeCalls = [];
            window.__fullStateCalls = 0;
            window.__progressRevision = 0;
            window.__activeProgress = 0;
            window.__maxActiveProgress = 0;
            window.pywebview = {api: {
              get_state: async () => { window.__fullStateCalls++; return structuredClone(current); },
              get_progress: async knownRevision => {
                window.__activeProgress++;
                window.__maxActiveProgress = Math.max(window.__maxActiveProgress, window.__activeProgress);
                try {
                  await new Promise(resolve => setTimeout(resolve, 1050));
                  const revision = window.__progressRevision;
                  if (knownRevision === revision) return {revision};
                  return {revision, status: current.status, phase: current.phase,
                    preview: current.preview, analysis: current.analysis,
                    suggestions: current.suggestions, error: current.error};
                } finally { window.__activeProgress--; }
              },
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
              analyze: async () => {
                // Match the backend's atomic task reservation before accepting.
                current.phase = 'capturing';
                current.status = '正在读取聊天区域';
                current.task_id = 'smoke-analysis';
                window.__progressRevision++;
                setTimeout(() => {
                  current.phase = 'recognizing';
                  current.status = '正在识别文字';
                  window.__progressRevision++;
                  setTimeout(() => {
                    current.phase = 'idle';
                    current.status = '模拟分析完成';
                    window.__progressRevision++;
                  }, 150);
                }, 2200);
                return {ok: true};
              },
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
        expect(protocol.locator("option")).to_have_count(12)
        # Every preset fills all required fields without touching the URL input.
        for preset in page.evaluate("window.pywebview.api.get_state().then(s => s.provider_presets)"):
            protocol.select_option(preset["id"])
            expect(page.locator("#provider-name")).to_have_value(preset["name"])
            expect(page.locator("#model-name")).to_have_value(preset["default_model"])
            assert page.locator("#base-url").input_value().startswith(preset["base_url"].rstrip("/"))
        protocol.select_option("ollama")
        expect(page.get_by_text("本地服务无需 API Key，请先启动服务并选择已安装的模型。")).to_be_visible()
        page.get_by_role("button", name="测试连接").click()
        expect(page.get_by_text("连接成功：OK")).to_be_visible()
        assert page.evaluate("window.__bridgeCalls.filter(c => c[0] === 'test').at(-1)[1].api_key") == ""
        protocol.select_option("custom")
        expect(page.locator("#protocol")).to_be_visible()
        page.locator("#protocol").select_option("openai-responses")
        protocol.select_option("anthropic")
        page.locator("#provider-name").fill("Anthropic 测试")
        expect(page.locator("#base-url")).to_have_value("https://api.anthropic.com/v1/messages")
        expect(page.locator("#model-name")).to_have_value("claude-sonnet-5-5")
        page.locator("#model-key").fill("test-secret-not-persisted")
        expect(page.get_by_text("已找到 2 个模型")).to_be_visible(timeout=5000)
        page.locator("#model-name").fill("")
        page.locator("#model-name").click()
        dropdown = page.locator(".model-dropdown")
        expect(dropdown).to_be_visible()
        expect(dropdown.locator("li")).to_have_count(2)
        dropdown.get_by_text("claude-sonnet-test").click()
        expect(page.locator("#model-name")).to_have_value("claude-sonnet-test")
        page.get_by_role("button", name="测试连接").click()
        expect(page.get_by_text("连接成功：OK")).to_be_visible(timeout=3000)
        page.get_by_role("button", name="保存", exact=True).last.click()
        expect(page.get_by_text("Anthropic 测试")).to_be_visible()
        page.get_by_role("button", name="保存设置").click()
        expect(page.get_by_role("heading", name="对话分析")).to_be_visible()
        expect(page.locator("body")).not_to_contain_text("test-secret-not-persisted")
        assert not page.evaluate("Object.values(localStorage).join(' ')").find("test-secret-not-persisted") >= 0
        assert not page_errors, page_errors
        full_state_calls = page.evaluate("window.__fullStateCalls")
        page.get_by_role("button", name="分析当前选区").click()
        expect(page.locator(".status-line")).to_contain_text("模拟分析完成", timeout=5000)
        assert page.evaluate("window.__maxActiveProgress") == 1
        assert page.evaluate("window.__fullStateCalls") == full_state_calls
        screenshot = os.path.join(tempfile.gettempdir(), "jev-vue-ui-smoke.png")
        page.screenshot(path=screenshot, full_page=True)
        print(f"UI smoke passed; screenshot: {screenshot}")
        browser.close()


if __name__ == "__main__":
    main()
