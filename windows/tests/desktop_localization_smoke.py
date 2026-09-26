"""Exercise the packaged EXE with real WebView2 and an isolated settings directory.

Uses WebView2's process-only debugging environment; the shipped app has no debug switch.
Never invokes model services, saves credentials, or reads a user's settings file.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import tempfile
import time
import urllib.request

import win32con
import win32gui
import win32process
from playwright.sync_api import expect, sync_playwright

from ui_localization_smoke import APP_VERSION, CATALOGS, REPORTS


def wait_for(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = check()
        if value:
            return value
        time.sleep(0.1)
    raise AssertionError("Timed out waiting for native desktop state")


def windows_for(pid):
    handles = []
    win32gui.EnumWindows(lambda hwnd, _: handles.append(hwnd) if win32process.GetWindowThreadProcessId(hwnd)[1] == pid else None, None)
    return handles


def start(exe, profile):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = dict(os.environ, APPDATA=str(profile), WEBVIEW2_USER_DATA_FOLDER=str(profile/'webview'),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port} --remote-debugging-address=127.0.0.1')
    for key in ('TYPESAFE_API_KEY', 'DEEPSEEK_API_KEY', 'OPENAI_API_KEY'):
        env.pop(key, None)
    process = subprocess.Popen([str(exe)], env=env, cwd=str(exe.parent))
    def ready():
        if process.poll() is not None:
            raise AssertionError(f'EXE exited: {process.returncode}')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1) as response:
                return json.load(response).get('webSocketDebuggerUrl')
        except (OSError, ValueError):
            return None
    try:
        endpoint = wait_for(ready, 45)
        return process, endpoint
    except BaseException:
        process.terminate()
        process.wait(timeout=15)
        raise


def stop(process):
    if process.poll() is not None:
        return
    for hwnd in windows_for(process.pid):
        if win32gui.IsWindowVisible(hwnd) and win32gui.GetClassName(hwnd) != 'TkTopLevel':
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--exe', type=Path, required=True)
    args = parser.parse_args()
    exe = args.exe.resolve(strict=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    profile = Path(tempfile.mkdtemp(prefix='desktop-', dir=REPORTS))
    # Real migration fixture contains no keys or user data.
    settings_file = profile/'JevChatAssistant/settings.json'
    settings_file.parent.mkdir()
    settings_file.write_text(json.dumps({'relationship':'Migration fixture', 'model_profiles':[], 'active_model_id':''}),encoding='utf-8')
    results = []
    with sync_playwright() as playwright:
        process, endpoint = start(exe, profile)
        browser = None
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            page = wait_for(lambda: next(iter(context.pages), None))
            page.wait_for_function('Boolean(window.pywebview?.api)')
            expect(page.locator('html')).to_have_attribute('lang','zh-CN')
            context.set_offline(True)
            for locale, text in CATALOGS.items():
                page.locator('.top-actions .button').click()
                page.locator('#interface-language').select_option(locale)
                expect(page.locator('html')).to_have_attribute('lang',locale)
                assert json.loads(settings_file.read_text(encoding='utf-8'))['language'] == locale
                expected_title = text['app.title'].replace('{version}', APP_VERSION)
                hwnd = wait_for(lambda: next((h for h in windows_for(process.pid) if win32gui.GetWindowText(h)==expected_title),None))
                assert json.loads(settings_file.read_text(encoding='utf-8'))['relationship'] == 'Migration fixture'
                page.screenshot(path=str(REPORTS/f'desktop-{locale}-settings.png'),full_page=True)
                page.locator('.back-button').click()
                page.locator('.analyze-button').click()
                expect(page.locator('.toast-message')).to_have_text(text['error.selectFirst'])
                # Open the actual Tk overlay; cancel it without capturing chat or sending text.
                page.locator('.setup-actions .button').click()
                overlay = wait_for(lambda: next((h for h in windows_for(process.pid) if win32gui.IsWindowVisible(h) and win32gui.GetClassName(h)=='TkTopLevel'),None))
                assert not win32gui.IsWindowVisible(hwnd)
                win32gui.PostMessage(overlay, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                win32gui.PostMessage(overlay, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                wait_for(lambda: not win32gui.IsWindow(overlay))
                expect(page.locator('.status-line')).to_have_text(text['status.cancelled'])
                results.append({'locale':locale, 'window_title':expected_title, 'offline':True, 'overlay_cancelled':True})
                print(f'PASS packaged desktop {locale}',flush=True)
        finally:
            stop(process)
            if browser:
                browser.close()
        process, endpoint = start(exe, profile)
        browser = None
        try:
            browser = playwright.chromium.connect_over_cdp(endpoint)
            page = wait_for(lambda: next(iter(browser.contexts[0].pages),None))
            expect(page.locator('html')).to_have_attribute('lang','ja')
            results.append({'restart_language':'ja'})
        finally:
            stop(process)
            if browser:
                browser.close()
    (REPORTS/'desktop-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
    print('PASS packaged restart; all desktop checks completed',flush=True)


if __name__ == '__main__':
    main()
