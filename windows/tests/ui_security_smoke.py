"""Offline UI enforcement for review capacity and unavailable update checksums."""
import os
from playwright.sync_api import expect, sync_playwright
from ui_features_smoke import MOCK_BRIDGE, FRONTEND_URL

MOCK = MOCK_BRIDGE + r"""
(() => {
 const api = window.pywebview.api, get = api.get_state;
 const info = {update_available:true, latest_version:'v99', current_version:'v1',
   size:10, download_url:'https://example.invalid', sha256:'', installable:false,
   blocked_reason:'update.checksumRequired'};
 api.get_state = async () => ({...await get(), review_id:'draft',
   review_messages:[{side:'other', text:'hello'}], update_info:info});
 api.get_progress = async () => ({revision:0});
 api.discard_review = async () => ({ok:true});
 api.discard_review = async () => ({ok:true});
 api.check_for_updates = async () => info;
 window.__downloads = 0;
 api.download_update = async () => {window.__downloads++; return {ok:true};};
})();
"""


def main():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, channel=os.environ.get('JEV_BROWSER_CHANNEL') or None)
        try:
            page = browser.new_page()
            page.add_init_script(MOCK)
            page.goto(FRONTEND_URL, wait_until='networkidle')
            expect(page.locator('.review-panel')).to_be_visible()
            page.locator('#review-text-0').fill('😀' * 200001)
            expect(page.get_by_role('alert').filter(has_text='A draft can contain')).to_be_visible()
            expect(page.get_by_role('button', name='Confirm and analyze', exact=True)).to_be_disabled()
            page.locator('#review-text-0').fill('hello')
            expect(page.get_by_role('button', name='Confirm and analyze', exact=True)).to_be_enabled()
            page.locator('.top-actions .button').click()
            expect(page.get_by_role('alert').filter(has_text='SHA-256')).to_be_visible()
            expect(page.locator('.update-available-row button')).to_be_disabled()
            assert page.evaluate('window.__downloads') == 0
            print('Security UI smoke passed: capacity rejection/recovery and blocked update')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
