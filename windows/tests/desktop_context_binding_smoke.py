"""Native source/WebView2 context/binding smoke; no release executable.

Project Python only. --report-dir must be new. Reuses desktop_features_smoke's
launcher, APPDATA/browser-profile/port isolation and shutdown helpers. The only
screen images are generated PIL fixtures processed by actual RapidOCR. A separate
process owns all target/occluder windows. No clipboard or user-window actions.
Calibration uses a controlled selection callback over the owned fixture; actual
interactive overlay dragging is outside this smoke's scope.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid

import desktop_features_smoke as helpers

ROOT = helpers.ROOT
SCRIPT = Path(__file__).resolve()
FRONTEND = helpers.FRONTEND
TITLE = 'Jev owned context binding fixture'
PRIOR = 'other: Earlier synthetic question\nme: Earlier synthetic answer'
BACKGROUND = 'Synthetic friends arranging lunch.'


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value), encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def fixture(profile):
    """Only this process creates/moves/minimizes/destroys synthetic root windows."""
    import win32con as con
    import win32gui as gui
    sys.path.insert(0, str(ROOT/'windows'))
    from jev_windows import windows_api as native
    native.ensure_dpi_awareness()
    rects = native.monitor_rects()
    import ctypes
    import win32api
    monitor_inventory = []
    get_dpi = ctypes.windll.shcore.GetDpiForMonitor
    get_dpi.argtypes = [ctypes.c_void_p,ctypes.c_int,ctypes.POINTER(ctypes.c_uint),ctypes.POINTER(ctypes.c_uint)]
    for handle,_,bounds in win32api.EnumDisplayMonitors():
        dpi_x,dpi_y = ctypes.c_uint(),ctypes.c_uint()
        code = get_dpi(int(handle),0,ctypes.byref(dpi_x),ctypes.byref(dpi_y))
        monitor_inventory.append(dict(bounds=list(bounds),dpi=[dpi_x.value,dpi_y.value] if code==0 else None))
    monitor = next((r for r in rects if r.left <= 0 < r.right and r.top <= 0 < r.bottom), rects[0])
    assert monitor.width >= 850 and monitor.height >= 600, 'Fixture needs a monitor at least 850x600'
    origin = (monitor.left+70, monitor.top+70)
    width, height = 700, 420
    owned = []
    def create(title=TITLE, x=None, y=None, w=width, h=height):
        hwnd = gui.CreateWindowEx(con.WS_EX_TOPMOST|con.WS_EX_TOOLWINDOW, 'STATIC', title,
            con.WS_POPUP|con.WS_VISIBLE, origin[0] if x is None else x,
            origin[1] if y is None else y, w, h, 0, 0, 0, None)
        owned.append(hwnd)
        return hwnd
    target, blocker = create(), None
    last = None
    try:
        while True:
            gui.PumpWaitingMessages()
            command = read_json(profile/'fixture-command.json')
            if command and command['id'] != last:
                last = command['id']
                action = command['action']
                if action == 'stop':
                    return
                if action == 'move':
                    gui.SetWindowPos(target, con.HWND_TOPMOST, origin[0]+50, origin[1]+60,width,height,con.SWP_NOACTIVATE)
                elif action == 'resize':
                    x,y,_,_ = gui.GetWindowRect(target)
                    gui.SetWindowPos(target,con.HWND_TOPMOST,x,y,width+60,height+40,con.SWP_NOACTIVATE)
                elif action == 'restore_size':
                    x,y,_,_ = gui.GetWindowRect(target)
                    gui.SetWindowPos(target,con.HWND_TOPMOST,x,y,width,height,con.SWP_NOACTIVATE)
                elif action == 'occlude':
                    x,y,_,_ = gui.GetWindowRect(target)
                    blocker = create('Jev owned synthetic occluder',x+20,y+20,650,360)
                elif action == 'unocclude':
                    if blocker and gui.IsWindow(blocker): gui.DestroyWindow(blocker)
                    blocker = None
                elif action == 'minimize':
                    gui.ShowWindow(target,con.SW_MINIMIZE)
                elif action == 'restore':
                    gui.ShowWindow(target,con.SW_SHOWNOACTIVATE)
                    gui.SetWindowPos(target,con.HWND_TOPMOST,0,0,0,0,con.SWP_NOMOVE|con.SWP_NOSIZE|con.SWP_NOACTIVATE)
                elif action == 'destroy':
                    gui.DestroyWindow(target)
                elif action == 'reopen':
                    target = create()
                snapshot, native_error = None, None
                if gui.IsWindow(target):
                    try:
                        snapshot = asdict(native.window_snapshot(target))
                    except native.NativeWindowError as exc:
                        native_error = str(exc)
                write_json(profile/'fixture-reply.json',dict(id=last,pid=os.getpid(),hwnd=target,
                    blocker=blocker,snapshot=snapshot,native_error=native_error,
                    minimized=bool(gui.IsIconic(target)) if gui.IsWindow(target) else False))
            if not (profile/'fixture-info.json').exists():
                write_json(profile/'fixture-info.json',dict(pid=os.getpid(),hwnd=target,
                    snapshot=asdict(native.window_snapshot(target)), monitors=[asdict(r) for r in rects],
                    monitor_inventory=monitor_inventory))
            time.sleep(.025)
    finally:
        for hwnd in reversed(owned):
            if gui.IsWindow(hwnd): gui.DestroyWindow(hwnd)


def child(profile, events):
    assert Path(os.environ['APPDATA']).resolve() == profile.resolve()
    # Exercise capture's per-thread physical context even when the executable
    # starts system-DPI-aware; process-wide ensure_dpi_awareness cannot upgrade it.
    import ctypes
    user32 = ctypes.WinDLL('user32',use_last_error=True)
    assert user32.SetProcessDPIAware(), 'Could not establish system-DPI-aware source fixture'
    process_dpi = ctypes.c_int()
    assert ctypes.windll.shcore.GetProcessDpiAwareness(None,ctypes.byref(process_dpi))==0
    assert process_dpi.value==1,process_dpi.value
    sys.path.insert(0,str(ROOT/'windows'))
    sys.path.insert(0,str(ROOT))
    import win32cred
    import win32clipboard
    import win32gui as gui
    import webview
    from PIL import Image, ImageDraw, ImageFont, ImageGrab
    lock = threading.Lock()
    def record(stage, **values):
        with lock, events.open('a',encoding='utf-8') as stream:
            stream.write(json.dumps(dict(stage=stage,**values))+'\n')
    def forbidden(*args, **kwargs):
        import traceback
        record('forbidden_call',stack=[f'{Path(f.filename).name}:{f.lineno}:{f.name}'
            for f in traceback.extract_stack(limit=6)])
        raise AssertionError('Credential, clipboard, network or desktop pixels forbidden')
    record('child_started',pid=os.getpid(),appdata=str(profile),browser_data=os.environ['WEBVIEW2_USER_DATA_FOLDER'],
        process_dpi_awareness=process_dpi.value)
    for name in ('CredRead','CredWrite','CredDelete','CredEnumerate'):
        setattr(win32cred,name,forbidden)
    for name in ('OpenClipboard','GetClipboardData','EmptyClipboard','SetClipboardData'):
        setattr(win32clipboard,name,forbidden)
    ImageGrab.grab = ImageGrab.grabclipboard = forbidden
    from jev_windows import config
    config.load_api_key = lambda: 'fixture-judge-key'
    config.load_model_api_key = lambda *_: 'fixture-model-key'
    for name in ('save_api_key','delete_api_key','save_model_api_key','delete_model_api_key'):
        setattr(config,name,forbidden)
    from jev_windows import app, analysis, task_controller, capture, windows_api as native
    from jev_windows.models import Rect, Analysis
    for module in (app,analysis,task_controller):
        module.load_api_key = config.load_api_key
        module.load_model_api_key = config.load_model_api_key
    def start_background_check(self):
        record('updates_disabled')
    app.DesktopApi.start_background_check = start_background_check
    app.UpdateService.start_background_check = forbidden
    app.UpdateService.check = lambda self: dict(ok=True,update_available=False,
        current_version='fixture',latest_version='fixture')
    app.list_models = app.test_connection = forbidden
    urllib.request.urlopen = socket.create_connection = forbidden
    connect = socket.socket.connect
    def local_connect(sock,address):
        if not isinstance(address,tuple) or address[0] not in ('127.0.0.1','localhost','::1'):
            return forbidden()
        return connect(sock,address)
    socket.socket.connect = local_connect
    native.ensure_dpi_awareness()
    startup = subprocess.STARTUPINFO()
    startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    fixture_log = (profile/'fixture.log').open('w',encoding='utf-8')
    target_process = subprocess.Popen([sys.executable,str(SCRIPT),'--fixture','--profile',str(profile)],
        cwd=ROOT,env=os.environ.copy(),startupinfo=startup,stdout=fixture_log,stderr=fixture_log)
    info = helpers.wait_for(lambda: read_json(profile/'fixture-info.json'))
    assert info['pid'] != os.getpid()
    record('fixture_started',**info)
    api = app.DesktopApi()
    window = webview.create_window('Jev source context binding smoke',FRONTEND.as_uri(),width=980,height=760,on_top=True)
    api.window = window
    window.expose(*(getattr(api,name) for name in vars(app.DesktopApi)
        if not name.startswith('_') and callable(getattr(api,name))))
    def target_snapshot():
        latest = read_json(profile/'fixture-reply.json') or info
        hwnd = latest['hwnd']
        snapshot = native.window_snapshot(hwnd)
        assert snapshot.pid == info['pid'], 'Never use a user-owned window'
        return snapshot
    def select(_client,_locale,finish):
        assert not gui.IsWindowVisible(int(window.native.Handle.ToInt64()))
        snap = target_snapshot()
        r = snap.client_rect
        area = Rect(r.left+20,r.top+20,r.left+660,r.top+370)
        record('controlled_selection',rect=asdict(area),dpi=snap.dpi)
        finish(area)
    app.select_region = select
    original_ocr = capture._ocr_boxes
    def ocr(area,image=None):
        assert image is not None, 'OCR must consume the synthetic frame'
        boxes = original_ocr(area,image)
        record('actual_ocr',text=[b.text for b in boxes])
        assert any('Hello' in b.text for b in boxes), boxes
        return boxes
    capture._ocr_boxes = ocr
    font = ImageFont.truetype(str(Path(os.environ['WINDIR'])/'Fonts/arial.ttf'),28)
    def screenshot(region):
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.AreDpiAwarenessContextsEqual.argtypes = [ctypes.c_void_p,ctypes.c_void_p]
        user32.AreDpiAwarenessContextsEqual.restype = ctypes.c_int
        thread_context = user32.GetThreadDpiAwarenessContext()
        assert user32.AreDpiAwarenessContextsEqual(thread_context,ctypes.c_void_p(-4)), 'Screenshot was not in per-monitor-v2 physical context'
        hwnd = int(window.native.Handle.ToInt64())
        assert not gui.IsWindowVisible(hwnd), 'Assistant must be natively hidden'
        snap = target_snapshot()
        assert snap.client_rect.contains(region.left,region.top) and snap.client_rect.contains(region.right,region.bottom)
        assert region.width == 640 and region.height == 350
        image = Image.new('RGB',(region.width,region.height),'white')
        draw = ImageDraw.Draw(image)
        draw.text((18,35),'Hello fixture friend',fill='black',font=font)
        draw.text((300,140),'Lunch tomorrow',fill='black',font=font)
        draw.text((18,245),'See you soon',fill='black',font=font)
        image.save(profile.parent/f'ocr-frame-{uuid.uuid4().hex[:8]}.png')
        record('capture_hidden',rect=asdict(region),assistant_hwnd=hwnd,fixture_pid=snap.pid,dpi=snap.dpi,
            physical_thread_context_verified=True)
        return image
    analysis.screenshot = screenshot
    native.screenshot = capture.screenshot = forbidden
    def model_record(stage,snapshot):
        record(stage,messages=[m.text for m in snapshot.messages],background=snapshot.background,raw_text=snapshot.raw_text)
    def judge(snapshot,relationship,key,**kwargs):
        assert key == 'fixture-judge-key'
        model_record('judge',snapshot)
        return Analysis(true_intent='casual_chat',danger_level=0,need='nothing',best_action='acknowledge')
    def generate(snapshot,relationship,judgment,key,*args,**kwargs):
        assert key == 'fixture-model-key'
        model_record('generate',snapshot)
        return ['Synthetic context reply']
    def rank(snapshot,relationship,replies,key,**kwargs):
        assert key == 'fixture-judge-key'
        model_record('rank',snapshot)
        return [dict(text=replies[0],probability=.9,confidence=.9,recommended=True)]
    analysis.judge,analysis.generate_suggestions,analysis.recommend_replies = judge,generate,rank
    api.start_background_check()
    try:
        webview.start(gui='edgechromium',debug=False,storage_path=os.environ['WEBVIEW2_USER_DATA_FOLDER'])
    finally:
        write_json(profile/'fixture-command.json',dict(id=uuid.uuid4().hex,action='stop'))
        try: target_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            target_process.terminate()
            target_process.wait(timeout=5)
        fixture_log.close()


def launch(profile,events,log):
    # Reuse the existing launcher unchanged; its child script is module.__file__.
    original = helpers.__file__
    helpers.__file__ = str(SCRIPT)
    try:
        return helpers.launch(profile,events,log)
    finally:
        helpers.__file__ = original


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child',action='store_true')
    parser.add_argument('--fixture',action='store_true')
    parser.add_argument('--profile',type=Path)
    parser.add_argument('--events',type=Path)
    parser.add_argument('--report-dir',type=Path)
    args = parser.parse_args()
    if args.fixture:
        fixture(args.profile)
        return
    if args.child:
        child(args.profile,args.events)
        return
    assert args.report_dir, '--report-dir NEW_DIRECTORY is required'
    from playwright.sync_api import expect,sync_playwright
    import win32gui as gui
    import win32process
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True,exist_ok=False)
    profile = reports/'profile'
    settings = profile/'JevChatAssistant/settings.json'
    settings.parent.mkdir(parents=True)
    write_json(settings,dict(language='en',relationship='Synthetic friends',chat_rect=None,selection_mode='window',
        model_profiles=[dict(id='fixture',name='Fixture model',base_url='https://fixture.invalid/v1',model='fixture')],
        active_model_id='fixture'))
    events = reports/'events.jsonl'
    result = dict(status='running',reports=str(reports),source_app=True,real_binding_runtime=True,
        real_desktop_pixels=False,actual_ocr=True,real_model_services=False,clipboard_access=False,
        interactive_calibration_overlay=False,frontend_sha256=hashlib.sha256(FRONTEND.read_bytes()).hexdigest(),
        limitations=['Synthetic PIL pixels with actual OCR; no OCR accuracy claim for user apps.',
                     'Controlled calibration completion; no physical pointer/overlay drag tested.'])
    result['source_sha256'] = {name:hashlib.sha256((ROOT/'windows/jev_windows'/name).read_bytes()).hexdigest()
        for name in ('app.py','window_binding.py','windows_api.py','task_controller.py','analysis.py')}
    process = browser = None
    try:
        with sync_playwright() as p,(reports/'child.log').open('w',encoding='utf-8') as log:
            process,endpoint = launch(profile,events,log)
            result['launch'] = dict(source_pid=process.smoke_pid,browser_data=process.browser_data,debug_port=process.debug_port,appdata=str(profile))
            browser = p.chromium.connect_over_cdp(endpoint)
            context = browser.contexts[0]
            context.set_offline(True)
            page = next(iter(context.pages),None) or context.wait_for_event('page',timeout=45000)
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            page.wait_for_function('typeof window.pywebview?.api?.get_selection_state === "function"')
            bridge_keys = page.evaluate('Object.keys(window.pywebview.api)')
            assert not {'window','settings','_binding_service','_analysis'}.intersection(bridge_keys)
            result['bridge_keys'] = bridge_keys
            catalog = json.loads((ROOT/'windows/locales/en.json').read_text(encoding='utf-8'))
            button = lambda key:page.get_by_role('button',name=catalog[key],exact=True)
            api = lambda method,arg=None:page.evaluate('async ([m,a])=>await window.pywebview.api[m](...(a===null?[]:a))',[method,arg])
            state = lambda:api('get_state')
            selection = lambda:api('get_selection_state')
            records = lambda:[json.loads(line) for line in events.read_text(encoding='utf-8').splitlines()]
            capture_count = lambda:sum(r['stage']=='capture_hidden' for r in records())
            info = read_json(profile/'fixture-info.json')
            result['fixture'] = info
            assert info['pid'] != process.smoke_pid
            assert win32process.GetWindowThreadProcessId(info['hwnd'])[1] == info['pid']
            assistant = helpers.wait_for(lambda:next((h for h in helpers.windows_for(process.smoke_pid)
                if gui.GetClassName(h).startswith('WindowsForms10.Window')),None))
            result['assistant_hwnd'] = assistant
            def fixture_action(action):
                ident = uuid.uuid4().hex
                write_json(profile/'fixture-command.json',dict(id=ident,action=action))
                def ready():
                    reply = read_json(profile/'fixture-reply.json')
                    return reply if reply and reply['id']==ident else None
                reply = helpers.wait_for(ready)
                assert reply['pid']==info['pid']
                return reply
            def restored():
                helpers.wait_for(lambda:gui.IsWindowVisible(assistant) and not gui.IsIconic(assistant))
            def calibrate():
                response = api('start_calibration',['window'])
                assert response.get('ok'),response
                helpers.wait_for(lambda:state()['phase'] in ('idle','error'))
                assert not state()['error'],state()
                restored()
                assert selection()['selection_binding']['status']=='bound',selection()
            def analyze(expect_error=None,options=None):
                before = capture_count()
                response = api('analyze',[None,options or dict(prior_text=PRIOR,background=BACKGROUND,message_limit=None)])
                assert response.get('ok'),response
                helpers.wait_for(lambda:state()['phase'] in ('idle','error'))
                current = state()
                restored()
                if expect_error:
                    assert current['failed_stage']=='capture',current
                    assert expect_error in json.dumps(current),current
                    assert capture_count()==before,'Blocked capture read pixels'
                else:
                    assert not current['error'],current
                    assert capture_count()==before+1
                    assert current['context_stats']['message_limit'] is None
                    assert current['context_stats']['used_messages']==current['context_stats']['total_messages']
                return current
            expect(page.locator('#context-message-limit')).to_have_value('all')
            calibrate()
            initial = selection()
            analyze()
            model_calls = [r for r in records() if r['stage'] in ('judge','generate','rank')]
            assert [r['stage'] for r in model_calls] == ['judge','generate','rank']
            assert all(r['background']==BACKGROUND and 'Earlier synthetic question' in r['messages'] for r in model_calls)
            assert all(r['messages']==model_calls[0]['messages'] for r in model_calls)
            result['actual_ocr_context_model_stages_hide_restore'] = 'passed'
            started = next(r for r in records() if r['stage']=='child_started')
            result['system_dpi_aware_source_physical_capture_context'] = dict(
                process_dpi_awareness=started['process_dpi_awareness'],
                all_capture_threads_per_monitor_v2=True,status='passed')
            page.screenshot(path=str(reports/'source-bound.png'),full_page=True)
            before_rect = initial['selection_binding']['rect']
            moved = fixture_action('move')
            after = selection()
            after_rect = after['selection_binding']['rect']
            assert after['selection_binding']['status']=='bound'
            assert after_rect['left']-before_rect['left']==50 and after_rect['top']-before_rect['top']==60
            assert after['selection_revision']==initial['selection_revision']
            analyze()
            result['real_window_move_followed'] = 'passed'
            fixture_action('resize')
            resized = selection()['selection_binding']
            assert resized['status']=='invalid' and resized['reason']=='binding.reselectRequired',resized
            failed_resize = analyze('binding.reselectRequired')
            calibrate()
            assert selection()['selection_revision']==initial['selection_revision'],'Same target reselection must retain context session'
            before_retry = capture_count()
            retry = api('retry_analysis',[failed_resize['task_id'],'capture'])
            assert retry.get('ok'),retry
            helpers.wait_for(lambda:state()['phase'] in ('idle','error'))
            assert not state()['error'],state()
            assert capture_count()==before_retry+1
            assert state()['context_stats']['total_messages']==5
            restored()
            result['capture_retry_reselected_same_target_retains_context'] = 'passed'
            result['real_resize_requires_reselection_same_target_revision_retained'] = 'passed'
            fixture_action('occlude')
            # Idle status intentionally ignores occlusion; actual resolve must block.
            assert selection()['selection_binding']['status']=='bound'
            analyze('binding.occluded')
            fixture_action('unocclude')
            result['real_occlusion_blocked_before_pixels'] = 'passed'
            before_minimize_revision = selection()['selection_revision']
            minimized_fixture = fixture_action('minimize')
            assert minimized_fixture['minimized']
            minimized = selection()['selection_binding']
            assert minimized['status']=='invalid' and minimized['reason']=='binding.unavailable',minimized
            analyze(minimized['reason'])
            result['minimized_live_status'] = minimized
            fixture_action('restore')
            restored_binding = selection()
            assert restored_binding['selection_binding']['status']=='bound',restored_binding
            assert restored_binding['selection_revision']==before_minimize_revision
            analyze()
            result['restore_minimized_bound_without_reselect_or_confirmation'] = 'passed'
            fixture_action('restore_size')
            calibrate()
            result['real_minimize_blocked_before_pixels'] = 'passed'
            fixture_action('destroy')
            assert selection()['selection_binding']['status']=='needs_confirmation'
            expect(page.locator('.analyze-button')).to_be_disabled(timeout=6000)
            reopened = fixture_action('reopen')
            assert reopened['snapshot']['app_path']==info['snapshot']['app_path']
            assert reopened['snapshot']['window_class']==info['snapshot']['window_class']
            assert selection()['selection_binding']['status']=='needs_confirmation'
            response = api('get_binding_candidates')
            assert response.get('ok'),response
            candidates = response['candidates']
            assert len(candidates)==1,candidates
            candidate = candidates[0]
            assert set(candidate)=={'id','title'} and candidate['title']==TITLE
            assert len(candidate['id'])==12 and all(c in '0123456789abcdef' for c in candidate['id'])
            assert candidate['id']!=str(reopened['hwnd'])
            assert selection()['selection_binding']['status']=='needs_confirmation'
            assert not api('confirm_binding',[str(reopened['hwnd'])]).get('ok')
            previous_revision = selection()['selection_revision']
            assert api('confirm_binding',[candidate['id']]).get('ok')
            assert selection()['selection_revision']==previous_revision+1
            assert not api('confirm_binding',[candidate['id']]).get('ok'),'Opaque ID must be single-use'
            analyze()
            result['destroy_reopen_same_class_app_requires_explicit_opaque_confirmation'] = 'passed'
            # Drive one full run through the actual frontend, then reselect the
            # same native target and check its session inputs and stats survive.
            expect(page.locator('.analyze-button')).to_be_enabled(timeout=6000)
            button('context.supplement').click()
            page.locator('#context-prior-text').fill(PRIOR)
            page.locator('#context-background').fill(BACKGROUND)
            page.locator('.analyze-button').click()
            expect(page.locator('.suggestion-list')).to_contain_text('Synthetic context reply',timeout=15000)
            expect(page.locator('.context-stats')).to_be_visible()
            ui_revision = selection()['selection_revision']
            button('binding.reselect').click()
            expect(page.locator('.analyze-button')).to_be_enabled(timeout=10000)
            assert selection()['selection_revision']==ui_revision,'Same native window reselection changed revision'
            expect(page.locator('#context-prior-text')).to_have_value(PRIOR)
            expect(page.locator('#context-background')).to_have_value(BACKGROUND)
            expect(page.locator('.context-stats')).to_be_visible()
            result['native_frontend_same_window_reselect_retains_supplements_and_stats'] = 'passed'
            result['native_frontend_same_window_revision'] = ui_revision
            # Read-only monitor inventory. No simulated monitor/DPI result is claimed.
            monitors = info['monitor_inventory']
            frames = [r for r in records() if r['stage']=='capture_hidden']
            negative_tested = any(r['rect']['left']<0 or r['rect']['top']<0 for r in frames)
            mixed_tested = len({r['dpi'] for r in frames})>1
            result['monitor_coverage'] = dict(inventory=monitors,negative_coordinates_tested=negative_tested,
                mixed_dpi_tested=mixed_tested,simulated_monitors=False)
            assert not errors,errors
            assert not any(r['stage']=='forbidden_call' for r in records())
            result['credential_clipboard_network_pixel_guards'] = 'passed'
            page.screenshot(path=str(reports/'source-reconfirmed.png'),full_page=True)
            result['status'] = 'passed'
    except BaseException as exc:
        result.update(status='failed',error=repr(exc))
        raise
    finally:
        if process: helpers.stop(process)
        # sync_playwright already disconnects CDP on context exit; stop the
        # source process above rather than calling a closed Playwright loop.
        (reports/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(result,indent=2),flush=True)


if __name__=='__main__':
    main()
