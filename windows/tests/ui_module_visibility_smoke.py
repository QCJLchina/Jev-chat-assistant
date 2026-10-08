"""Headless visibility controls: persistence, failure rollback and core workflow."""
import os
from playwright.sync_api import expect, sync_playwright
from ui_features_smoke import MOCK_BRIDGE, FRONTEND_URL

MOCK = MOCK_BRIDGE + r"""
(() => {
 const api=window.pywebview.api, get=api.get_state;
 let saved=JSON.parse(localStorage.getItem('fixture.modules') || '{"welcome":true,"model":true,"messages":true,"judgment":true}');
 api.get_state=async()=>({...await get(),module_visibility:{...saved}});
 api.set_module_visibility=async changes=>{
   if(window.__failVisibility) return {ok:false,error:'Synthetic save failure'};
   saved={...saved,...changes};localStorage.setItem('fixture.modules',JSON.stringify(saved));
   return {ok:true,module_visibility:{...saved}};
 };
})();
"""


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=os.environ.get("JEV_BROWSER_CHANNEL") or None)
        try:
            page = browser.new_page(viewport={"width": 980, "height": 760})
            errors = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.add_init_script(MOCK)
            page.goto(FRONTEND_URL, wait_until="networkidle")
            page.locator(".top-actions .button").click()
            expect(page.locator(".module-visibility-panel input")).to_have_count(4)
            for name in ("welcome", "model", "messages", "judgment"):
                page.locator(f"#module-{name}").uncheck()
                expect(page.locator(f"#module-{name}")).to_be_enabled()
            page.locator(".back-button").click()
            for selector in (".welcome-row", ".model-card", ".messages-card", ".judgement-card", ".results-grid"):
                expect(page.locator(selector)).to_have_count(0)
            expect(page.locator(".input-source-panel")).to_be_visible()
            expect(page.locator(".analysis-card")).to_be_visible()
            expect(page.locator(".suggestions-section")).to_be_visible()
            assert page.locator(".content-grid").evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length") == 1
            page.reload(wait_until="networkidle")
            expect(page.locator(".model-card")).to_have_count(0)
            page.locator(".top-actions .button").click()
            expect(page.locator("#module-messages")).not_to_be_checked()
            page.evaluate("window.__failVisibility=true")
            page.locator("#module-messages").click()
            expect(page.locator(".toast-message")).to_contain_text("Synthetic save failure")
            expect(page.locator("#module-messages")).not_to_be_checked()
            page.evaluate("window.__failVisibility=false")
            page.locator("#module-messages").check()
            page.locator(".back-button").click()
            expect(page.locator(".messages-card")).to_be_visible()
            expect(page.locator(".judgement-card")).to_have_count(0)
            assert page.locator(".results-grid").evaluate("e=>getComputedStyle(e).gridTemplateColumns.split(' ').length") == 1
            page.get_by_role("button", name="Paste text", exact=True).click()
            page.locator("#analysis-text").fill("other: synthetic greeting")
            page.locator(".analyze-button").click()
            page.evaluate("window.__features.finish('Synthetic completed reply')")
            expect(page.locator(".suggestion-list")).to_be_visible()
            page.locator(".top-actions .button").click()
            page.get_by_role("button", name="Show all modules", exact=True).click()
            expect(page.locator("#module-welcome")).to_be_checked()
            page.locator(".back-button").click()
            expect(page.locator(".welcome-row")).to_be_visible()
            expect(page.locator(".model-card")).to_be_visible()
            expect(page.locator(".judgement-card")).to_be_visible()
            assert not errors, errors
            print("Module visibility smoke passed: hide, persist, rollback, restore and core workflow")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
