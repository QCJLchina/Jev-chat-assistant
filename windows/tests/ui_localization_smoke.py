"""Offline browser regression for all locales; run against the Vite preview server.

Manual acceptance, not part of CI: the script asserts that choosing "follow the
system" interface language resolves to English, so it needs a machine whose
Windows display language is English. It also launches the msedge channel by
default (override with JEV_BROWSER_CHANNEL=chromium after `playwright install`).
Install its dependency with windows/requirements-smoke.txt, start
`npm --prefix windows/frontend run preview`, and point JEV_FRONTEND_URL at it.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CATALOGS = {locale: json.loads((ROOT / "windows/locales" / f"{locale}.json").read_text(encoding="utf-8")) for locale in ("zh-CN", "en", "fr", "ru", "ja", "ko")}


def _app_version() -> str:
    """Read the single-sourced version so smoke fixtures never drift from it."""
    source = (ROOT / "windows/jev_windows/__init__.py").read_text(encoding="utf-8")
    return re.search(r'__version__\s*=\s*"([^"]+)"', source).group(1)


APP_VERSION = _app_version()
REPORTS = ROOT / "_reports" / f"v{APP_VERSION}"

MOCK = r"""
const initial = {
  provider_presets: [{"id": "deepseek", "name": "DeepSeek", "base_url": "https://api.deepseek.com", "default_model": "deepseek-flash", "protocol": "openai-chat", "suggested_models": ["deepseek-v4-pro"], "key_site": "platform.deepseek.com", "local": false, "models": ["deepseek-flash", "deepseek-v4-pro"]}, {"id": "dashscope", "name": "通义千问（阿里云百炼·北京）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "default_model": "qwen3.8-flash", "protocol": "openai-chat", "suggested_models": ["qwen3.7-plus", "qwen3.8-max"], "key_site": "bailian.console.aliyun.com", "local": false, "models": ["qwen3.8-flash", "qwen3.7-plus", "qwen3.8-max"]}, {"id": "moonshot", "name": "Kimi（月之暗面）", "base_url": "https://api.moonshot.cn/v1", "default_model": "kimi-k3", "protocol": "openai-chat", "suggested_models": [], "key_site": "platform.kimi.com", "local": false, "models": ["kimi-k3"]}, {"id": "zhipu", "name": "智谱 GLM", "base_url": "https://open.bigmodel.cn/api/paas/v4", "default_model": "glm-5.3", "protocol": "openai-chat", "suggested_models": ["glm-5.3-flash"], "key_site": "bigmodel.cn", "local": false, "models": ["glm-5.3", "glm-5.3-flash"]}, {"id": "ark", "name": "豆包（火山方舟）", "base_url": "https://ark.cn-beijing.volces.com/api/v3", "default_model": "doubao-seed-2.0", "protocol": "openai-chat", "suggested_models": [], "key_site": "console.volcengine.com/ark", "local": false, "models": ["doubao-seed-2.0"]}, {"id": "siliconflow", "name": "硅基流动 SiliconFlow", "base_url": "https://api.siliconflow.cn/v1", "default_model": "deepseek-ai/DeepSeek-V3.2", "protocol": "openai-chat", "suggested_models": ["Pro/moonshotai/Kimi-K2.6"], "key_site": "cloud.siliconflow.cn", "local": false, "models": ["deepseek-ai/DeepSeek-V3.2", "Pro/moonshotai/Kimi-K2.6"]}, {"id": "openai", "name": "OpenAI", "base_url": "https://api.openai.com/v1", "default_model": "gpt-6.1-sol", "protocol": "openai-responses", "suggested_models": ["gpt-6-luna"], "key_site": "platform.openai.com", "local": false, "models": ["gpt-6.1-sol", "gpt-6-luna"]}, {"id": "anthropic", "name": "Anthropic Claude", "base_url": "https://api.anthropic.com/v1", "default_model": "claude-sonnet-5-5", "protocol": "anthropic", "suggested_models": [], "key_site": "platform.claude.com", "local": false, "models": ["claude-sonnet-5-5"]}, {"id": "gemini", "name": "Google Gemini", "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/", "default_model": "gemini-3.8-flash", "protocol": "openai-chat", "suggested_models": [], "key_site": "aistudio.google.com", "local": false, "models": ["gemini-3.8-flash"]}, {"id": "openrouter", "name": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "default_model": "google/gemini-3.8-flash", "protocol": "openai-chat", "suggested_models": [], "key_site": "openrouter.ai", "local": false, "models": ["google/gemini-3.8-flash"]}, {"id": "ollama", "name": "Ollama（本地）", "base_url": "http://localhost:11434/v1", "default_model": "qwen3", "protocol": "openai-chat", "suggested_models": [], "key_site": "", "local": true, "models": ["qwen3"]}],
  language: 'zh-CN', resolved_language: 'zh-CN', revision: 1, version: '__VERSION__',
  status: '', status_message: {key: 'status.complete'}, error: '', error_message: null,
  phase: 'idle', preview: [{side:'other', text:'原始聊天 / Original conversation'}],
  analysis: {true_intent:'confirm_you_care', need:'care', best_action:'acknowledge',
    danger_level:2.5, should_reply_now:0.6, tension_resolved:0.9, latency_ms:1234},
  suggestions:[{text:'原始回复 / Original reply', probability:0.7, confidence:0.8, recommended:true}],
  chat_rect:{left:0,top:0,right:800,bottom:600},
  jev_key_configured:true, relationship:'原始关系', allowed_titles:['原始标题'],
  active_model_id:'test-model', profiles:[{id:'test-model',name:'My model',model:'sample-model',
    base_url:'https://example.test/v1',protocol:'openai-chat',max_tokens:400,key_configured:true}]
};
const current = JSON.parse(sessionStorage.getItem('fixture') || 'null') || initial;
window.__fixture = current;
window.__saveCalls = 0;
window.__failLanguage = false;
window.pywebview = {api: {
  get_state:async()=>structuredClone(current),
  get_progress:async revision=>revision===current.revision?{revision}:structuredClone(current),
  set_language:async language=>{
    if(window.__failLanguage) return {ok:false,error_message:{key:'language.failed',params:{detail:'test failure'}}};
    current.language=language;current.resolved_language=language==='system'?'en':language;current.revision++;
    sessionStorage.setItem('fixture', JSON.stringify(current));
    return {language:current.language,resolved_language:current.resolved_language};
  },
  fetch_models:async()=>({models:['sample-model','sample-other']}),
  test_model:async()=>({message:'OK'}),
  save_settings:async()=>{window.__saveCalls++;return structuredClone(current)},
  copy_text:async value=>{window.__copied=value;return {ok:true}},
  set_active_model:async()=>({ok:true}),set_on_top:async()=>({ok:true}),
  start_calibration:async()=>({ok:true}),
  analyze:async()=>{
    current.phase='judging';current.status_message={key:'status.judging',params:{count:3}};current.revision++;
    return {ok:true};
  }
}};
"""


def check_layout(page):
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), "horizontal page overflow"
    clipped = page.locator("button, .nav-item, .brand-name, .dialog-footer, .panel-heading").evaluate_all("""els => els.filter(el => {
      const r=el.getBoundingClientRect();
      return r.width && r.height && el.scrollWidth > el.clientWidth + 2;
    }).map(el => el.className + ': ' + el.textContent.trim())""")
    assert not clipped, clipped


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=os.environ.get("JEV_BROWSER_CHANNEL", "msedge"))
        try:
            for locale, text in CATALOGS.items():
                for width, height in ((760, 620), (980, 760)):
                    page = browser.new_page(viewport={"width":width,"height":height})
                    errors = []
                    page.on("pageerror", lambda error: errors.append(str(error)))
                    page.add_init_script(MOCK.replace("__VERSION__", APP_VERSION))
                    page.goto(os.environ.get("JEV_FRONTEND_URL", "http://127.0.0.1:5173"), wait_until="networkidle")
                    expect(page.get_by_role("heading", name=CATALOGS['zh-CN']['analysis.title'], exact=True)).to_be_visible()
                    page.locator('.top-actions .button').click()
                    page.locator('#relationship').fill('Uncommitted relationship')
                    page.locator('#jev-key').fill('temporary-test-key')
                    page.locator('#interface-language').select_option(locale)
                    expect(page.locator('html')).to_have_attribute('lang', locale)
                    expect(page.locator('#relationship')).to_have_value('Uncommitted relationship')
                    expect(page.locator('#jev-key')).to_have_value('temporary-test-key')
                    assert page.evaluate('window.__saveCalls') == 0
                    assert page.evaluate('window.__fixture.relationship') == '原始关系'
                    check_layout(page)
                    page.screenshot(path=str(REPORTS/f'{locale}-{width}-settings.png'), full_page=True)

                    page.locator('.configured-main').click()
                    page.locator('.configured-model .small-icon:not(.delete-icon)').click()
                    dialog = page.get_by_role('dialog')
                    expect(dialog.get_by_role('heading')).to_have_text(text['model.edit'])
                    page.locator('#provider-name').fill('Unsaved model name')
                    page.locator('#model-key').fill('temporary-test-key')
                    expect(page.locator('.model-list-row')).to_contain_text(text['model.found'].replace('{count}','2'))
                    page.get_by_role('button', name=text['model.test'], exact=True).click()
                    expect(page.locator('.toast-message')).to_have_text(text['model.connected'].replace('{detail}','OK'))
                    check_layout(page)
                    page.screenshot(path=str(REPORTS/f'{locale}-{width}-model.png'), full_page=True)
                    dialog.get_by_role('button', name=text['common.save'], exact=True).click()
                    page.locator('#interface-language').select_option('system')
                    expect(page.locator('html')).to_have_attribute('lang','en')
                    expect(page.locator('.configured-name')).to_contain_text('Unsaved model name')
                    page.locator('#interface-language').select_option(locale)
                    expect(page.locator('html')).to_have_attribute('lang',locale)

                    page.locator('.delete-icon').click()
                    confirmation = page.get_by_role('alertdialog')
                    expect(confirmation).to_contain_text(text['model.confirmDelete'].replace('{name}','Unsaved model name'))
                    check_layout(page)
                    page.screenshot(path=str(REPORTS/f'{locale}-{width}-confirm.png'),full_page=True)
                    confirmation.get_by_role('button',name=text['common.cancel']).click()
                    expect(page.locator('.configured-name')).to_contain_text('Unsaved model name')

                    page.evaluate('window.__failLanguage = true')
                    page.locator('#interface-language').select_option('ja' if locale != 'ja' else 'fr')
                    expect(page.locator('#interface-language')).to_have_value(locale)
                    expect(page.locator('html')).to_have_attribute('lang',locale)
                    expect(page.locator('.toast-message')).to_have_text(text['language.failed'].replace('{detail}','test failure'))
                    page.evaluate('window.__failLanguage = false')
                    page.locator('.back-button').click()
                    expect(page.locator('.intent-value')).to_have_text(text['intent.confirm_you_care'])
                    expect(page.locator('.status-line')).to_have_text(text['status.complete'])
                    expect(page.locator('.message-bubble')).to_contain_text('原始聊天 / Original conversation')
                    page.locator('.copy-button').click()
                    assert page.evaluate('window.__copied') == '原始回复 / Original reply'
                    check_layout(page)
                    page.screenshot(path=str(REPORTS/f'{locale}-{width}-home.png'),full_page=True)
                    page.locator('.analyze-button').click()
                    expect(page.locator('.status-line')).to_have_text(text['status.judging'].replace('{count}','3'))
                    page.locator('.top-actions .button').click()
                    page.locator('#interface-language').select_option('en' if locale != 'en' else 'fr')
                    target = 'en' if locale != 'en' else 'fr'
                    page.locator('.back-button').click()
                    expect(page.locator('.status-line')).to_have_text(CATALOGS[target]['status.judging'].replace('{count}','3'))
                    expect(page.locator('.analyze-button')).to_be_disabled()
                    page.reload(wait_until='networkidle')
                    expect(page.locator('html')).to_have_attribute('lang',target)
                    assert not errors, errors
                    page.close()
                    print(f'PASS {locale} {width}x{height}', flush=True)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
