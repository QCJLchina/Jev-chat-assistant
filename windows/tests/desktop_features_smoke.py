"""Native source/WebView2 feature smoke; never launch a release EXE.

Run with the project's .venv-windows-py312 Python after rebuilding frontend/dist.
Example: .venv-windows-py312/Scripts/python.exe windows/tests/desktop_features_smoke.py
Only this test is authored; reports/profiles go to a fresh directory.
Each launch has fresh browser storage; only isolated APPDATA is reused on restart.
Model stages and credential access are guarded fixtures in the child process.
No desktop pixels are read: capture supplies a synthetic PIL image and OCR fixture.
The real capture orchestration, bridge, frontend and native windows remain active.
Clipboard is exercised ONLY when initially empty; nonempty/opaque formats are skipped.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'windows/frontend/dist/index.html'
DEFAULTS = {'length': 'detailed', 'style': 'formal', 'language': 'fr'}
OVERRIDES = {'length': 'short', 'style': 'gentle', 'language': 'ja'}
TEXT = 'me: Are we meeting tomorrow?\nother: Yes, after lunch.'
REPLIES = ['Synthetic reply one', 'Synthetic reply two', 'Synthetic reply three']


def wait_for(check, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(.1)
    raise AssertionError('Timed out waiting for native source-app state')


def windows_for(pid):
    import win32gui
    import win32process
    handles = []
    def collect(hwnd, _):
        if win32process.GetWindowThreadProcessId(hwnd)[1] == pid:
            handles.append(hwnd)
        return True
    win32gui.EnumWindows(collect, None)
    return handles


def child(profile, events):
    # Fail before importing the app if isolation was not supplied by this runner.
    assert Path(os.environ['APPDATA']).resolve() == profile.resolve()
    sys.path.insert(0, str(ROOT / 'windows'))
    sys.path.insert(0, str(ROOT))
    import threading
    import win32cred
    import win32clipboard
    import win32con
    import win32gui
    import webview
    from PIL import Image, ImageGrab

    lock = threading.Lock()

    def record(stage, **values):
        with lock, events.open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'stage': stage, **values}) + '\n')

    record('child_started', pid=os.getpid(), appdata=str(profile),
           browser_data=os.environ['WEBVIEW2_USER_DATA_FOLDER'])

    def forbidden(*args, **kwargs):
        import traceback
        record('forbidden_call', stack=[f'{Path(f.filename).name}:{f.lineno}:{f.name}'
                                      for f in traceback.extract_stack(limit=6)])
        raise AssertionError('Credential/network/desktop-pixel access forbidden in smoke')

    empty_clipboard = win32clipboard.EmptyClipboard

    def empty_only():
        # DesktopApi already holds OpenClipboard here, preventing concurrent
        # writers between this format check and the native EmptyClipboard call.
        if win32clipboard.EnumClipboardFormats(0):
            raise AssertionError('Clipboard populated before copy; preserved every format')
        empty_clipboard()

    win32clipboard.EmptyClipboard = empty_only

    # Guard the underlying credential APIs before any app imports.
    for name in ('CredRead', 'CredWrite', 'CredDelete', 'CredEnumerate'):
        setattr(win32cred, name, forbidden)
    ImageGrab.grab = forbidden
    ImageGrab.grabclipboard = forbidden
    from jev_windows import config
    config.load_api_key = lambda: 'fixture-judge-key'
    config.load_model_api_key = lambda *_: 'fixture-model-key'
    for name in ('save_api_key', 'delete_api_key', 'save_model_api_key', 'delete_model_api_key'):
        setattr(config, name, forbidden)
    from jev_windows import app, task_controller, analysis, capture, windows_api
    from jev_windows.models import Analysis, Rect
    # Patch imported aliases explicitly as well as config itself.
    for module in (app, task_controller, analysis):
        module.load_api_key = config.load_api_key
        module.load_model_api_key = config.load_model_api_key
    app.DesktopApi.start_background_check = lambda self: record('updates_disabled')
    app.UpdateService.start_background_check = lambda self: forbidden()
    app.UpdateService.check = lambda self: dict(ok=True, update_available=False,
        current_version='fixture', latest_version='fixture')
    app.list_models = app.test_connection = forbidden
    urllib.request.urlopen = forbidden
    socket.create_connection = forbidden
    original_connect = socket.socket.connect

    def local_connect(sock, address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', 'localhost', '::1'):
            return forbidden()
        return original_connect(sock, address)

    socket.socket.connect = local_connect

    def judge(snapshot, relationship, key, **kwargs):
        assert key == 'fixture-judge-key'
        record('judge', messages=[m.text for m in snapshot.messages])
        return Analysis(true_intent='casual_chat', danger_level=0, need='nothing', best_action='acknowledge')

    def generate(*args, **kwargs):
        assert args[3] == 'fixture-model-key'
        record('generate', preferences=kwargs['preferences'])
        return list(REPLIES)

    def rank(snapshot, relationship, replies, key, **kwargs):
        assert key == 'fixture-judge-key' and replies == REPLIES
        record('rank')
        return [dict(text=r, probability=.9, confidence=.9, recommended=i == 0)
                for i, r in enumerate(replies)]

    analysis.judge, analysis.generate_suggestions, analysis.recommend_replies = judge, generate, rank
    windows_api.ensure_dpi_awareness()
    # Native synthetic widget: own PID/handle, no user window title inspection.
    widget = win32gui.CreateWindowEx(win32con.WS_EX_TOPMOST, 'STATIC', 'Jev synthetic fixture',
                                    win32con.WS_POPUP | win32con.WS_VISIBLE,
                                    40, 40, 420, 180, 0, 0, 0, None)
    rect = Rect(40, 40, 460, 220)
    api = app.DesktopApi()
    window = webview.create_window('Jev source feature smoke', FRONTEND.as_uri(),
                                   width=980, height=760, on_top=True)
    api.window = window
    # Expose the real bound methods without recursively exporting the public
    # api.window / controller objects (pywebview traverses native COM properties).
    window.expose(*(getattr(api, name) for name in vars(app.DesktopApi)
                    if not name.startswith('_') and callable(getattr(api, name))))

    def screenshot(region):
        assert region == rect
        hwnd = int(window.native.Handle.ToInt64())
        assert not win32gui.IsWindowVisible(hwnd), 'Source window was not hidden at capture'
        assert win32gui.IsWindow(widget)
        record('capture_hidden', hwnd=hwnd, widget=widget, region=[40, 40, 460, 220])
        return Image.new('RGB', (420, 180), 'white')

    analysis.screenshot = screenshot
    windows_api.screenshot = capture.screenshot = forbidden
    analysis.window_title_at = lambda *_: 'Jev synthetic fixture'
    capture._ocr_boxes = lambda *_: [capture.TextBox('Yes, after lunch.', Rect(20, 40, 180, 60))]
    # Limit the actual native calibration overlay to our synthetic fixture region.
    app.virtual_screen_rect = lambda: rect
    api.start_background_check()

    def configure_capture():
        command = profile / 'capture-request'
        while True:
            if command.exists():
                with api._lock:
                    api.settings.chat_rect = rect
                command.unlink()
                record('capture_configured')
            time.sleep(.1)

    threading.Thread(target=configure_capture, daemon=True).start()
    try:
        # Match pywebview's own cache path to the process-only WebView2 override.
        # Otherwise private-mode cleanup tries to delete an unused temp folder.
        webview.start(gui='edgechromium', debug=False,
                      storage_path=os.environ['WEBVIEW2_USER_DATA_FOLDER'])
    finally:
        if win32gui.IsWindow(widget):
            win32gui.DestroyWindow(widget)


def launch(profile, events, log):
    browser_root = profile.parent / 'browser-profiles'
    browser_root.mkdir(exist_ok=True)
    browser_data = Path(tempfile.mkdtemp(prefix='launch-', dir=browser_root))
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    env = {key: value for key, value in os.environ.items()
           if not any(word in key.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
    env.update(APPDATA=str(profile), LOCALAPPDATA=str(profile / 'local'),
               WEBVIEW2_USER_DATA_FOLDER=str(browser_data),
               WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=f'--remote-debugging-port={port} --remote-debugging-address=127.0.0.1 --disable-background-networking')
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0  # Hide Python console; the authorized app window stays visible.
    process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--child',
                                '--profile', str(profile), '--events', str(events)],
                               cwd=ROOT, env=env, startupinfo=startup, stdout=log, stderr=log)

    def ready():
        if process.poll() is not None:
            raise AssertionError(f'Source child exited {process.returncode}; see child log')
        try:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}/json/version', timeout=1) as response:
                return json.load(response)['webSocketDebuggerUrl']
        except (OSError, ValueError):
            return None

    try:
        endpoint = wait_for(ready, 45)
        records = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
        # Windows venv python.exe may be a launcher with a distinct child PID.
        process.smoke_pid = next(r['pid'] for r in reversed(records) if r['stage'] == 'child_started')
        process.browser_data = str(browser_data)
        process.debug_port = port
        return process, endpoint
    except BaseException:
        stop(process)
        raise


def stop(process):
    import win32con
    import win32gui
    if process.poll() is not None:
        return
    for hwnd in windows_for(getattr(process, 'smoke_pid', process.pid)):
        if win32gui.GetClassName(hwnd) != 'TkTopLevel':
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.terminate()
        process.wait(timeout=8)


def clipboard_check(page):
    import win32clipboard as clipboard
    # Never read opaque handles or binary data. Any existing format => no mutation.
    clipboard.OpenClipboard()
    try:
        if clipboard.EnumClipboardFormats(0):
            return {'status': 'skipped', 'reason': 'Clipboard nonempty; full format restoration not guaranteed; no data read or cleared.'}
    finally:
        clipboard.CloseClipboard()
    # The child checks emptiness again while holding the actual clipboard lock.
    result = page.evaluate('''async () => {
      return await window.pywebview.api.copy_text('Synthetic native clipboard fixture');
    }''')
    if not result.get('ok'):
        if 'Clipboard populated before copy' in str(result):
            return {'status': 'skipped', 'reason': 'Clipboard changed before copy; native locked guard preserved every format.'}
        raise AssertionError(result)
    try:
        clipboard.OpenClipboard()
        try:
            assert clipboard.GetClipboardData(clipboard.CF_UNICODETEXT) == 'Synthetic native clipboard fixture'
        finally:
            clipboard.CloseClipboard()
    finally:
        clipboard.OpenClipboard()
        try:
            # Restore initial emptiness only if this is still our exact text and
            # only Windows' text conversion formats exist; never clear new binary.
            formats, current = [], 0
            while current := clipboard.EnumClipboardFormats(current):
                formats.append(current)
            if set(formats) <= {1, 7, 13, 16} and clipboard.IsClipboardFormatAvailable(13) and clipboard.GetClipboardData(13) == 'Synthetic native clipboard fixture':
                clipboard.EmptyClipboard()
            else:
                raise AssertionError('Clipboard changed concurrently; preserved current contents')
        finally:
            clipboard.CloseClipboard()
    return {'status': 'passed', 'restored': 'initially empty'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', action='store_true')
    parser.add_argument('--report-dir', type=Path, help='New report directory; must not already exist')
    parser.add_argument('--profile', type=Path)
    parser.add_argument('--events', type=Path)
    args = parser.parse_args()
    if args.child:
        child(args.profile, args.events)
        return
    import win32con
    import win32gui
    from playwright.sync_api import expect, sync_playwright
    assert FRONTEND.is_file(), 'Rebuild windows/frontend/dist first'
    if args.report_dir:
        reports = args.report_dir.resolve()
        reports.mkdir(parents=True, exist_ok=False)
    else:
        reports = Path(tempfile.mkdtemp(prefix='jev-desktop-features-'))
    profile = reports / 'profile'
    settings = profile / 'JevChatAssistant/settings.json'
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps(dict(language='en', relationship='Synthetic friends', chat_rect=None,
        model_profiles=[dict(id='fixture', name='Fixture model', base_url='https://fixture.invalid/v1', model='fixture')],
        active_model_id='fixture')), encoding='utf-8')
    events = reports / 'events.jsonl'
    result = {'status': 'running', 'reports': str(reports), 'source_app': True,
              'bridge': 'Real bound DesktopApi methods exposed through pywebview',
              'real_screen_capture': False, 'real_ocr': False, 'packaged_exe': False,
              'frontend_sha256': hashlib.sha256(FRONTEND.read_bytes()).hexdigest(),
              'launches': [],
              'limitations': ['Synthetic capture/OCR fixtures; no real desktop pixels or OCR accuracy tested.']}
    catalog = json.loads((ROOT / 'windows/locales/en.json').read_text(encoding='utf-8'))
    print(f'Reports: {reports}', flush=True)
    try:
        with sync_playwright() as playwright, (reports / 'child.log').open('w', encoding='utf-8') as log:
            for restart in (False, True):
                process, endpoint = launch(profile, events, log)
                launch_result = dict(restart=restart, source_pid=process.smoke_pid,
                                     appdata=str(profile), browser_data=process.browser_data,
                                     debug_port=process.debug_port)
                result['launches'].append(launch_result)
                browser = None
                try:
                    browser = playwright.chromium.connect_over_cdp(endpoint)
                    context = browser.contexts[0]
                    context.set_offline(True)
                    # A time.sleep polling loop never dispatches pending Playwright
                    # events. Await the CDP page event if the initial snapshot is empty.
                    page = next(iter(context.pages), None)
                    if page is None:
                        page = context.wait_for_event('page', timeout=45000)
                    errors = []
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.wait_for_function('typeof window.pywebview?.api?.get_state === "function"')
                    launch_result['page_url'] = page.url
                    bridge = page.evaluate('''() => Object.entries(window.pywebview.api)
                        .map(([name, value]) => ({name, type: typeof value}))''')
                    assert all(entry['type'] == 'function' for entry in bridge), bridge
                    forbidden_objects = {'analysis', '_analysis', 'progress', 'window', 'settings', 'updates'}
                    assert not forbidden_objects.intersection(entry['name'] for entry in bridge), bridge
                    launch_result['bridge_keys'] = sorted(entry['name'] for entry in bridge)
                    result['bridge_methods_only'] = 'passed'
                    state = lambda: page.evaluate('window.pywebview.api.get_state()')
                    if restart:
                        assert process.browser_data != result['launches'][0]['browser_data']
                        assert page.evaluate('localStorage.getItem("__jev_smoke_restart_marker")') is None
                        assert state()['reply_preferences'] == DEFAULTS
                        assert state()['chat_rect'] is None
                        assert settings.read_bytes() == before
                        page.locator('.top-actions').get_by_role('button', name=catalog['common.settings'], exact=True).click()
                        for field, value in DEFAULTS.items():
                            expect(page.locator(f'#default-{field}')).to_have_value(value)
                        result['restart_preferences'] = 'passed'
                        result['config_independent_of_browser_storage'] = 'passed'
                        continue
                    page.evaluate('localStorage.setItem("__jev_smoke_restart_marker", "first-launch")')
                    assert state()['chat_rect'] is None
                    page.get_by_role('button', name=catalog['feature.inputText'], exact=True).click()
                    page.locator('#analysis-text').fill(TEXT)
                    page.locator('.top-actions').get_by_role('button', name=catalog['common.settings'], exact=True).click()
                    for field, value in DEFAULTS.items():
                        page.locator(f'#default-{field}').select_option(value)
                    page.get_by_role('button', name=catalog['settings.save'], exact=True).click()
                    assert json.loads(settings.read_text(encoding='utf-8'))['reply_preferences'] == DEFAULTS
                    before = settings.read_bytes()
                    page.get_by_role('button', name=catalog['feature.temporaryPreferences'], exact=True).click()
                    page.locator('.temporary-enable input').check()
                    for field, value in OVERRIDES.items():
                        page.locator(f'#temporary-{field}').select_option(value)
                    page.locator('.analyze-button').click()
                    expect(page.locator('.suggestion-list')).to_contain_text(REPLIES[0], timeout=15000)
                    assert state()['input_source'] == 'text' and state()['chat_rect'] is None
                    assert settings.read_bytes() == before
                    records = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
                    assert [r['stage'] for r in records if r['stage'] in ('judge', 'generate', 'rank')] == ['judge', 'generate', 'rank']
                    assert next(r for r in records if r['stage'] == 'generate')['preferences'] == OVERRIDES
                    result['text_without_area'] = result['global_preferences'] = result['temporary_not_persisted'] = 'passed'
                    result['clipboard'] = clipboard_check(page)
                    owned = [{'hwnd': h, 'class': win32gui.GetClassName(h), 'title': win32gui.GetWindowText(h)}
                             for h in windows_for(process.smoke_pid)]
                    result['owned_windows'] = owned
                    hwnd = wait_for(lambda: next((h for h in windows_for(process.smoke_pid)
                                                 if win32gui.GetClassName(h).startswith('WindowsForms10.Window')), None))
                    assert page.evaluate('window.pywebview.api.start_calibration()')['ok']
                    overlay = wait_for(lambda: next((h for h in windows_for(process.smoke_pid) if win32gui.GetClassName(h) == 'TkTopLevel' and win32gui.IsWindowVisible(h)), None))
                    assert not win32gui.IsWindowVisible(hwnd)
                    win32gui.PostMessage(overlay, win32con.WM_KEYDOWN, win32con.VK_ESCAPE, 0)
                    win32gui.PostMessage(overlay, win32con.WM_KEYUP, win32con.VK_ESCAPE, 0)
                    wait_for(lambda: not win32gui.IsWindow(overlay))
                    wait_for(lambda: win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd))
                    wait_for(lambda: state()['phase'] == 'idle')
                    result['calibration_escape_restore'] = 'passed'
                    (profile / 'capture-request').touch()
                    wait_for(lambda: state()['chat_rect'] is not None)
                    response = page.evaluate('window.pywebview.api.analyze()')
                    assert response.get('ok'), response
                    wait_for(lambda: state()['phase'] == 'idle' and state()['input_source'] == 'desktop')
                    assert not state()['error'], state()
                    assert 'capture_hidden' in events.read_text(encoding='utf-8')
                    wait_for(lambda: win32gui.IsWindowVisible(hwnd) and not win32gui.IsIconic(hwnd))
                    assert settings.read_bytes() == before
                    result['synthetic_capture_hide_restore'] = 'passed'
                    assert not errors, errors
                    page.screenshot(path=str(reports / 'source-features.png'), full_page=True)
                finally:
                    stop(process)
                    if browser:
                        browser.close()
            records = [json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
            assert not any(r['stage'] == 'forbidden_call' for r in records), records
            result['credential_network_pixel_guards'] = 'passed'
        result['status'] = 'passed'
    except BaseException as error:
        result.update(status='failed', error=str(error))
        raise
    finally:
        (reports / 'results.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    main()
