"""Browser contract smoke. Local Vue only, mocked bridge, no user data/actions.

Run with project Python, a running Vite frontend, and --report-dir NEW_DIRECTORY.
JEV_BROWSER_CHANNEL defaults to msedge. Every report directory must be new.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
CATALOG = json.loads((ROOT / 'windows/locales/en.json').read_text(encoding='utf-8'))
PRIOR = 'other: Earlier fixture message\nme: Earlier fixture answer'
BACKGROUND = 'Synthetic friends planning a picnic.'

MOCK = r"""
(() => {
 const s = {language:'en', resolved_language:'en', revision:0, phase:'idle',
 status:'Ready', error:'', preview:[], analysis:null, suggestions:[], version:'smoke',
 chat_rect:{left:40,top:40,right:460,bottom:220}, jev_key_configured:true,
 relationship:'Synthetic friends', allowed_titles:[], provider_presets:[],
 profiles:[], active_model_id:'', reply_preferences:{length:'short',style:'natural',language:'en'},
 task_id:null,input_source:null,failed_stage:null,retryable_stages:[],
 selection_mode:'screen',selection_binding:{status:'none'},selection_revision:4};
 const clone = x => structuredClone(x);
 const calls = [];
 const record = (method,payload=null) => calls.push({method,payload:clone(payload)});
 const patch = x => {Object.assign(s,x);s.revision++;};
 const selection = () => clone(Object.fromEntries(['selection_mode','selection_binding',
 'selection_revision','chat_rect'].map(k=>[k,s[k]])));
 const candidates = [{id:'a9f72d3e10bc',title:'Fixture Alpha'},
 {id:'b4e80ac219df',title:'Fixture Beta'}];
 const begin = (method,payload) => {
 record(method,payload); const id=`task-${calls.length}`;
 patch({task_id:id,input_source:method==='analyze'?'desktop':'text',phase:'judging'});
 const error = window.__contextSmoke.nextError ? 'Fixture ranking error' : '';
 window.__contextSmoke.nextError=false;
 setTimeout(()=>patch({phase:'idle',status:'Complete',error,
 failed_stage:error?'rank':null,suggestions:[{text:'Fixture completed',
 probability:null,confidence:null,recommended:false}],context_stats:{total_messages:32,
 used_messages:Math.min(payload.context.message_limit??32,32),characters:320,
 message_limit:payload.context.message_limit,omitted_messages:32-Math.min(payload.context.message_limit??32,32)}}),120);
 return {ok:true,task_id:id};
 };
 window.__contextSmoke={calls,patch,selection,candidates};
 window.pywebview={api:{
 get_state:async()=>clone(s),get_progress:async()=>clone(s),
 get_selection_state:async()=>{record('get_selection_state');return selection();},
 analyze:async(preferences,context)=>begin('analyze',{preferences,context}),
 analyze_text:async payload=>begin('analyze_text',payload),
 start_calibration:async mode=>{record('start_calibration',mode);patch({phase:'idle'});return {ok:true};},
 set_selection_mode:async mode=>{record('set_selection_mode',mode);patch({selection_mode:mode,
 selection_binding:{status:mode==='window'?'needs_confirmation':'none'},
 selection_revision:s.selection_revision+1});return {ok:true};},
 get_binding_candidates:async()=>{record('get_binding_candidates');return {ok:true,candidates:clone(candidates)};},
 confirm_binding:async id=>{record('confirm_binding',id);if(!candidates.some(c=>c.id===id))return {ok:false};
 patch({selection_binding:{status:'bound',display_name:candidates.find(c=>c.id===id).title},
 selection_revision:s.selection_revision+1});return {ok:true};},
 check_for_updates:async()=>({ok:true,update_available:false}),
 set_on_top:async()=>({ok:true}),
 save_settings:async raw=>{record('save_settings',JSON.parse(raw));return clone(s);}
 }};
})();
"""


def run(page, reports, result):
    button = lambda key: page.get_by_role('button', name=CATALOG[key], exact=True)
    analyze = page.locator('.analyze-button')
    limit = page.locator('#context-message-limit')
    prior = page.locator('#context-prior-text')
    background = page.locator('#context-background')
    patch = lambda values: page.evaluate('v => window.__contextSmoke.patch(v)', values)
    calls = lambda name: page.evaluate('n => window.__contextSmoke.calls.filter(c=>c.method===n)', name)

    def supplements():
        toggle = button('context.supplement')
        if toggle.get_attribute('aria-expanded') != 'true':
            toggle.click()

    def retained():
        supplements()
        expect(prior).to_have_value(PRIOR)
        expect(background).to_have_value(BACKGROUND)

    def analysis(method, expected):
        count = len(calls(method))
        analyze.click()
        page.wait_for_function('([n,c])=>window.__contextSmoke.calls.filter(x=>x.method===n).length>c', arg=[method,count])
        assert calls(method)[-1]['payload']['context'] == expected, calls(method)
        expect(analyze).to_be_enabled(timeout=10000)

    expect(limit).to_have_value('all')
    expect(analyze).to_be_enabled()  # Existing fixed rectangle is immediately usable.
    supplements()
    prior.fill(PRIOR)
    background.fill(BACKGROUND)
    options = dict(prior_text=PRIOR, background=BACKGROUND, message_limit=None)
    analysis('analyze', options)
    for value in (10, 20, 50):
        limit.select_option(str(value))
        analysis('analyze', {**options, 'message_limit':value})
    limit.select_option('all')
    button('feature.inputText').click()
    page.locator('#analysis-text').fill('other: New synthetic message\nme: Thanks')
    analysis('analyze_text', options)
    analysis('analyze_text', options)
    retained()
    page.locator('.top-actions').get_by_role('button', name=CATALOG['common.settings'], exact=True).click()
    button('settings.save').click()
    retained()
    saved = calls('save_settings')[-1]['payload']
    assert not {'context','prior_text','background','message_limit'}.intersection(saved)
    result['context_payloads_ranges_navigation_repeated_analysis'] = 'passed'
    page.evaluate('window.__contextSmoke.nextError=true')
    analysis('analyze_text', options)
    expect(page.locator('.analysis-recovery')).to_contain_text('Fixture ranking error')
    button('feature.inputDesktop').click()
    button('binding.reselect').click()
    expect(analyze).to_be_enabled(timeout=10000)
    retained()  # Same window, no revision change.
    expect(page.locator('.suggestion-list')).to_contain_text('Fixture completed')
    expect(page.locator('.context-stats')).to_be_visible()
    patch({'selection_binding':{'status':'invalid'}, 'selection_revision':4})
    retained()
    patch({'selection_revision':5})
    expect(prior).to_have_value('', timeout=6000)
    expect(background).to_have_value('')
    expect(limit).to_have_value('all')
    expect(page.locator('.suggestion-list')).to_have_count(0)
    expect(page.locator('.context-stats')).to_have_count(0)
    expect(page.locator('.analysis-recovery')).to_have_count(0)
    result['supplements_clear_only_on_revision_increment'] = 'passed'
    analysis('analyze',dict(prior_text='',background='',message_limit=None))
    expect(page.locator('.suggestion-list')).to_contain_text('Fixture completed')
    page.locator('#selection-mode').select_option('window')
    expect(analyze).to_be_disabled()
    expect(page.locator('.suggestion-list')).to_have_count(0)
    expect(page.locator('.context-stats')).to_have_count(0)
    button('feature.inputText').click()
    expect(analyze).to_be_enabled()
    analysis('analyze_text', dict(prior_text='', background='', message_limit=None))
    expect(page.locator('.suggestion-list')).to_contain_text('Fixture completed')
    button('feature.inputDesktop').click()
    button('binding.chooseWindow').click()
    dialog = page.get_by_role('dialog')
    confirm = dialog.get_by_role('button', name=CATALOG['binding.confirm'], exact=True)
    expect(confirm).to_be_disabled()
    assert not calls('confirm_binding')
    expect(dialog.locator('.binding-candidate')).to_have_count(2)
    expect(dialog).to_contain_text('Fixture Alpha')
    expect(dialog).to_contain_text('Fixture Beta')
    radios = dialog.locator('input[type=radio]')
    assert radios.evaluate_all('(xs)=>xs.map(x=>x.value)') == ['a9f72d3e10bc','b4e80ac219df']
    assert radios.evaluate_all('(xs)=>xs.every(x=>!x.checked)')
    radios.nth(1).check()
    confirm.click()
    expect(dialog).to_have_count(0)
    expect(analyze).to_be_enabled()
    assert calls('confirm_binding')[-1]['payload'] == 'b4e80ac219df'
    expect(page.locator('.suggestion-list')).to_have_count(0)
    expect(page.locator('.context-stats')).to_have_count(0)
    expect(page.locator('.analysis-recovery')).to_have_count(0)
    result['revision_switch_reconfirmation_clear_old_results_stats_errors'] = 'passed'
    prior.fill(PRIOR)
    background.fill(BACKGROUND)
    page.screenshot(path=str(reports / 'confirmed-context.png'), full_page=True)
    before = len(calls('get_selection_state'))
    patch({'selection_binding':{'status':'needs_confirmation'}})
    expect(analyze).to_be_disabled(timeout=6000)
    assert len(calls('get_selection_state')) > before
    retained()
    button('feature.inputText').click()
    expect(analyze).to_be_enabled()
    page.screenshot(path=str(reports / 'closed-window-text-enabled.png'), full_page=True)
    result['opaque_candidates_explicit_confirmation_idle_close_desktop_only_block'] = 'passed'
    result['calls'] = page.evaluate('window.__contextSmoke.calls')
    # Compatibility with old bridges that send a rectangle and no selection fields.
    page.close()


def localized_layout(context, url, reports):
    cases = []
    for language in ('zh-CN','en','ja','ko','fr','ru'):
        catalog = json.loads((ROOT/f'windows/locales/{language}.json').read_text(encoding='utf-8'))
        for width,height in ((760,620),(980,760)):
            page = context.new_page()
            page.set_viewport_size({'width':width,'height':height})
            errors = []
            page.on('pageerror',lambda error:errors.append(str(error)))
            initial = dict(language=language,resolved_language=language,selection_mode='window',
                selection_binding={'status':'bound','display_name':'Fixture Alpha'},
                context_stats=dict(total_messages=32,used_messages=32,characters=320,message_limit=None,omitted_messages=0))
            page.add_init_script(MOCK+'\nwindow.__contextSmoke.patch('+json.dumps(initial)+');')
            page.goto(url,wait_until='networkidle')
            expect(page.locator('html')).to_have_attribute('lang',language)
            page.get_by_role('button',name=catalog['context.supplement'],exact=True).click()
            expect(page.locator('#context-supplements')).to_be_visible()
            page.locator('#context-prior-text').fill(PRIOR)
            page.locator('#context-background').fill(BACKGROUND)
            for key in ('context.help','context.safetyNote','context.priorText','context.background'):
                expect(page.get_by_text(catalog[key],exact=True)).to_be_visible()
            expect(page.locator('.context-stats')).to_be_visible()
            def layout(modal=False):
                overflow = page.evaluate('''() => {
                  const visible = e => {const r=e.getBoundingClientRect();return r.width&&r.height&&getComputedStyle(e).visibility!=='hidden';};
                  return {page:document.documentElement.scrollWidth>innerWidth+2,
                    clipped:[...document.querySelectorAll('button,label,.field-hint,.context-stats,.binding-candidate,.dialog-footer')]
                      .filter(e=>visible(e)&&e.scrollWidth>e.clientWidth+2)
                      .map(e=>({tag:e.tagName,class:e.className,text:e.textContent.trim()})),
                    untranslated:document.body.innerText.match(/\\b(?:context|binding)\\.[A-Za-z]+/g)||[]};
                }''')
                assert not overflow['page'] and not overflow['clipped'] and not overflow['untranslated'],(language,width,overflow)
                if modal:
                    bounds = page.get_by_role('dialog').bounding_box()
                    assert bounds and bounds['x']>=-1 and bounds['y']>=-1 and bounds['x']+bounds['width']<=width+1 and bounds['y']+bounds['height']<=height+1,(language,width,bounds)
                return overflow
            expanded = layout()
            page.screenshot(path=str(reports/f'{language}-{width}-expanded-context.png'),full_page=True)
            page.get_by_role('button',name=catalog['binding.chooseWindow'],exact=True).click()
            dialog = page.get_by_role('dialog')
            expect(dialog.get_by_role('heading',name=catalog['binding.confirmTitle'],exact=True)).to_be_visible()
            expect(dialog).to_contain_text(catalog['binding.confirmHelp'])
            expect(dialog.locator('.binding-candidate')).to_have_count(2)
            confirm = dialog.get_by_role('button',name=catalog['binding.confirm'],exact=True)
            expect(confirm).to_be_disabled()
            dialog.locator('input[type=radio]').nth(1).check()
            expect(confirm).to_be_enabled()
            modal = layout(True)
            page.screenshot(path=str(reports/f'{language}-{width}-binding-confirmation.png'),full_page=True)
            assert not errors,(language,width,errors)
            cases.append(dict(locale=language,width=width,height=height,expanded_context=expanded,confirmation_modal=modal,status='passed'))
            page.close()
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report-dir', required=True, type=Path)
    parser.add_argument('--url', default=os.environ.get('JEV_FRONTEND_URL','http://127.0.0.1:5173'))
    args = parser.parse_args()
    reports = args.report_dir.resolve()
    reports.mkdir(parents=True, exist_ok=False)
    result = {'status':'running','reports':str(reports),'url':args.url,'real_backend':False,
              'app_vue_sha256':hashlib.sha256((ROOT/'windows/frontend/src/App.vue').read_bytes()).hexdigest()}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, channel=os.environ.get('JEV_BROWSER_CHANNEL','msedge'))
            try:
                errors = []
                context = browser.new_context(viewport={'width':1280,'height':1100})
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(args.url.rstrip('/')+'/') else route.abort())
                page = context.new_page()
                page.on('pageerror', lambda error: errors.append(str(error)))
                page.add_init_script(MOCK)
                page.goto(args.url, wait_until='networkidle')
                run(page,reports,result)
                legacy = context.new_page()
                legacy.on('pageerror', lambda error: errors.append(str(error)))
                legacy.add_init_script(MOCK + "\nconst api=window.pywebview.api; const get=api.get_state; api.get_state=async()=>{const s=await get();delete s.selection_mode;delete s.selection_revision;delete s.selection_binding;return s;}; delete api.get_selection_state;")
                legacy.goto(args.url,wait_until='networkidle')
                expect(legacy.locator('#selection-mode')).to_have_value('screen')
                expect(legacy.locator('.analyze-button')).to_be_enabled()
                legacy.screenshot(path=str(reports/'legacy-fixed-ready.png'),full_page=True)
                result['legacy_rectangle_ready'] = 'passed'
                legacy.close()
                result['localized_expanded_context_and_binding_modal'] = localized_layout(context,args.url,reports)
                assert not errors, errors
            finally:
                browser.close()
        result['status'] = 'passed'
    except BaseException as exc:
        result.update(status='failed',error=repr(exc))
        raise
    finally:
        (reports/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
        print(json.dumps(dict(status=result['status'],reports=str(reports),
            locale_size_cases=len(result.get('localized_expanded_context_and_binding_modal',[])),
            error=result.get('error')),indent=2),flush=True)


if __name__ == '__main__':
    main()
