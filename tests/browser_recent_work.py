"""Recent work over a mounted active Plan, protected HTTP and retained SQLite.

Controlled native list/read/open boundary; the shipped browser controllers and
API handlers run unchanged. DESK_USE_INSTALLED=1 selects installed assets.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def check(width,browser,root,evidence):
    with tempfile.TemporaryDirectory(dir=root,prefix='recent-work-') as tmp:
        folder=Path(tmp);home=folder/'home';home.mkdir();active=folder/'active';active.mkdir()
        removed=folder/'removed';removed.mkdir();removed.rmdir()
        (home/'config.toml').write_text('model="fixture"\n')
        (home/'auth.json').write_text('{"synthetic":"retained"}\n')
        settings={p.name:p.read_bytes() for p in home.iterdir()}
        draft_text='  Exact unsent Plan — 保留\nDo not change these next checks. 🔧\n'
        active_thread={'id':'native-active','cwd':str(active),'name':'Retained active Plan','modelProvider':'fixture',
            'turns':[{'id':'active-turn','status':'inProgress','items':[
                {'id':'active-answer','type':'agentMessage','text':'Planning the active task.'}]}]}
        old={'id':'native-removed','cwd':str(removed),'name':'Removed-folder original decision','modelProvider':'fixture',
            'turns':[{'id':'original-turn','status':'completed','items':[
                {'id':'original-answer','type':'agentMessage','text':'ORIGINAL DECISION: keep three retries and inspect the saved command.'},
                {'id':'original-command','type':'commandExecution','command':'check --retained','status':'completed',
                 'exitCode':0,'aggregatedOutput':'ORIGINAL COMMAND evidence\nretained output'}]}]}
        original=copy.deepcopy(old)
        calls,http,errors,external=[],[],[],[]
        desk=None;server=None;worker=None

        class Catalog:
            def request(self,method,params):
                calls.append({'method':method,'params':copy.deepcopy(params)})
                assert method in ('thread/list','thread/read'),method
                if method=='thread/list':
                    return {'data':[{k:v for k,v in t.items() if k!='turns'} for t in (old,active_thread)],'nextCursor':None}
                assert params.get('includeTurns') is True,params
                assert params['threadId'] in (old['id'],active_thread['id']),params
                return {'thread':copy.deepcopy(old if params['threadId']==old['id'] else active_thread)}

        def start(port=0):
            nonlocal desk,server,worker
            desk=Desk('never-executed',home,folder/'state');desk.catalog=lambda:Catalog()
            def opened(id):
                calls.append({'method':'explicit-open','session':id});assert id=='active'
                desk.store.update(id,status='running',provider='fixture',model='fixture')
                return {'thread':copy.deepcopy(active_thread),'model':'fixture','modelProvider':'fixture'}
            desk.open=opened
            token=secrets.token_urlsafe(32)
            server=ThreadingHTTPServer(('127.0.0.1',port),handler(desk,access_token=token))
            worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
            return f'http://127.0.0.1:{server.server_port}#access={token}'

        def stop():
            nonlocal desk,server,worker
            if server:server.shutdown();server.server_close();worker.join(3);server=None
            if desk:desk.close();desk.store.db.close();desk=None

        def paths(path,method=None):
            return [r for r in http if r['path']==path and (not method or r['method']==method)]

        context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844})
        await context.grant_permissions(['clipboard-read','clipboard-write'])
        async def new_page(url):
            p=await context.new_page();p.set_default_timeout(10000);p.on('pageerror',lambda e:errors.append(str(e)))
            def requested(r):
                parsed=urlsplit(r.url);http.append({'path':parsed.path,'query':parsed.query,'method':r.method})
                if parsed.hostname!='127.0.0.1':external.append(r.url)
            p.on('request',requested);await p.goto(url);return p

        async def snapshot(page):
            return await page.evaluate("({selected,generation,nativeThreadId,prompt:$('prompt').value,mode:$('turn-mode').value,binding:$('binding').textContent,currentTurn,caret:[$('prompt').selectionStart,$('prompt').selectionEnd,$('prompt').selectionDirection]})")

        async def same(page,before):
            assert await snapshot(page)==before
            assert load_draft(desk.store,'active')==draft_saved
            assert followup_snapshot(desk.store,'active')==queue
            assert await page.locator('#followup-count').inner_text()=='2'
            assert await page.locator('#followup-send').is_disabled()
            assert await page.locator('#send').is_disabled()
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')

        async def inspect(page,phase,live=False):
            before=await snapshot(page);open_count=len(paths('/api/open'));import_count=len(paths('/api/import'))
            await page.locator('#show-recent').focus();await page.keyboard.press('Enter')
            await page.wait_for_function("$('recent-work').open && $('home-list').getAttribute('aria-busy')==='false'")
            assert 'Retained active Plan · running' in await page.locator('#recent-selected-status').inner_text()
            assert await page.locator('#home-list .native-row').count()==2
            assert 'project folder(s) unavailable' in await page.locator('#home-status').inner_text()
            if live:await page.screenshot(path=str(evidence/f'active-recent-overview-{width}.png'))
            rows_before=await page.locator('#home-list').inner_text()
            row=page.locator('#home-list .native-row[data-thread="native-removed"]')
            assert await row.get_by_role('button',name='Resume conversation',exact=True).count()==0
            assert 'Original evidence is still readable' in await row.inner_text()
            scroll=await page.evaluate('scrollY')
            await row.locator('.native-read').focus();await page.keyboard.press('Enter')
            await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            assert await page.locator('#history-reader-binding').inner_text()==f"Thread native-removed\n{removed}\nProvider: fixture"
            assert await page.locator('#history-reader-back').inner_text()=='Back to recent work'
            assert await page.locator('#recent-work').evaluate('(n)=>n.open')
            item=page.locator('#history-reader-body [data-item-id="original-answer"]')
            assert await item.get_attribute('data-turn-id')=='original-turn'
            if not await item.evaluate('(n)=>n.open'):await item.locator('summary').click()
            assert 'ORIGINAL DECISION' in await item.locator('.history-reader-text').inner_text()
            await page.screenshot(path=str(evidence/f'{phase}-original-{width}.png'))
            await item.get_by_role('button',name='Copy source reference',exact=True).click()
            await page.wait_for_function("$('history-reader-body').textContent.includes('Source reference copied.')")
            copied=await page.evaluate('navigator.clipboard.readText()')
            assert f'Thread: native-removed\nTurn: original-turn\nItem: original-answer\nProject folder: {removed}' in copied
            await same(page,before)
            sequence_before=await page.evaluate('after')
            if live:
                delta=' Live progress while reviewing recent work.'
                active_thread['turns'][0]['items'][0]['text']+=delta
                desk.store.event('active',{'method':'item/agentMessage/delta','params':{
                    'threadId':'native-active','turnId':'active-turn','itemId':'active-answer','delta':delta}})
                desk.store.update('active',status='approval')
                await page.wait_for_function("$('activity').textContent.includes('Live progress') && $('recent-selected-status').textContent.includes('· approval')")
                assert await page.locator('#status').inner_text()=='approval'
                assert await page.evaluate('scrollY')==scroll
                assert await page.evaluate('after')>sequence_before
                await same(page,before)
                desk.store.update('active',status='running')
                await page.wait_for_function("$('recent-selected-status').textContent.includes('· running')")
            assert await page.evaluate("$('recent-work').scrollWidth<=$('recent-work').clientWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth && $('history-reader-body').scrollWidth<=$('history-reader-body').clientWidth")
            await page.locator('#history-reader-back').click()
            await page.wait_for_function("!$('history-reader').open && $('recent-work').open")
            assert await row.locator('.native-read').evaluate('(n)=>n===document.activeElement')
            assert await page.locator('#home-list').inner_text()==rows_before
            await same(page,before)
            await page.locator('#recent-return').click()
            await page.wait_for_function("!$('recent-work').open && $('welcome').parentNode.tagName==='MAIN'")
            assert await page.locator('#show-recent').evaluate('(n)=>n===document.activeElement')
            assert await page.locator('#task').is_visible()
            assert len(paths('/api/open'))==open_count and len(paths('/api/import'))==import_count
            await same(page,before)
            await page.screenshot(path=str(evidence/f'{phase}-return-{width}.png'))
            return {'phase':phase,'exact_read_and_back_focus':True,'return_no_reopen':True,'active_stream_preserved':True,'live_progress_injected':live}

        try:
            url=start()
            desk.store.create(str(active),'default',identifier='active',name='Retained active Plan')
            desk.store.update('active',thread_id='native-active',status='saved',thread_saved=1,mode='plan',name_pending=0)
            save_draft(desk.store,'active',draft_text,'plan',0)
            add_followup(desk.store,'active','First queued native check.','native')
            add_followup(desk.store,'active','Second queued Plan clarification.','plan')
            desk.store.event('active',{'method':'turn/started','params':{'threadId':'native-active','turn':{'id':'active-turn'}}})
            page=await new_page(url)
            await page.locator('.session-row[data-session="active"] .session').click()
            await page.wait_for_function("selected==='active' && !opening && !$('task').hidden && $('followup-count').textContent==='2' && currentTurn==='active-turn'")
            # One ordinary task-box edit is saved before entering read-only work.
            # The inspection itself adds no draft or queue mutation.
            draft_text+='Prepared after opening; still unsent.\n'
            await page.locator('#prompt').fill(draft_text)
            await page.wait_for_function("v => draftSaved.get('active')?.text===v",arg=draft_text)
            draft_saved=load_draft(desk.store,'active');queue=followup_snapshot(desk.store,'active')
            checks=[await inspect(page,'active',live=True)]
            assert len(paths('/api/open'))==1 and not paths('/api/import')
            assert [r['path'] for r in http if r['method']=='POST']==['/api/open','/api/draft']
            # Fresh JS document on the same retained browser session.
            await page.reload();await page.wait_for_function("selected==='active' && !opening && $('followup-count').textContent==='2' && currentTurn==='active-turn'")
            checks.append(await inspect(page,'restored'))
            # Stop and recreate Desk against the exact retained SQLite/native
            # home and origin, consume a fresh per-launch access fragment.
            port=server.server_port;await page.close();stop();url=start(port)
            page=await new_page(url);await page.wait_for_function("selected==='active' && !opening && $('followup-count').textContent==='2' && currentTurn==='active-turn'")
            checks.append(await inspect(page,'cold'))
            assert len(paths('/api/open'))==3 and not paths('/api/import')
            assert old==original and {p.name:p.read_bytes() for p in home.iterdir()}==settings
            assert not removed.exists() and desk.runtimes=={}
            assert [r['path'] for r in http if r['method']=='POST']==['/api/open','/api/draft','/api/open','/api/open']
            reads=paths('/api/native/thread');assert len(reads)==3
            assert all(parse_qs(r['query'])=={'id':['native-removed']} for r in reads)
            # Resume remains a separate, explicit action. Reusing the already
            # bound active thread still requires import followed by native open.
            await page.locator('#show-recent').click()
            await page.wait_for_function("$('recent-work').open && $('home-list').getAttribute('aria-busy')==='false'")
            generation_before=await page.evaluate('generation')
            await page.locator('#home-list .native-row[data-thread="native-active"]').get_by_role('button',name='Resume conversation',exact=True).click()
            await page.wait_for_function("g => generation===g+1 && !opening && !$('recent-work').open",arg=generation_before)
            assert len(paths('/api/import'))==1 and len(paths('/api/open'))==4
            assert await page.locator('#prompt').input_value()==draft_text
            assert followup_snapshot(desk.store,'active')==queue and load_draft(desk.store,'active')==draft_saved
            assert not errors and not external
            return {'width':width,'checks':checks,'removed_folder_original_reads':3,
                'prepared_followups_unchanged':2,'task_box_draft_and_mode_preserved':True,
                'protected_http_fresh_capability_on_cold_return':True,'explicit_resume_imports':1,
                'native_model_turns':0,'errors':errors}
        finally:
            await context.close();stop()


async def main():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage'])
        try:checks=[await check(width,browser,root,evidence) for width in (1250,390)]
        finally:await browser.close()
    (evidence/'summary.json').write_text(json.dumps({'result':'PASS','checks':checks},indent=2)+'\n')
    print(json.dumps({'result':'PASS','recent_cases':6,'viewports':[1250,390]}),flush=True)


if __name__=='__main__':asyncio.run(main())
