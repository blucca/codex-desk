"""Local preparation review/reuse through real SQLite, HTTP and Chromium."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk import server as desk_server
from codex_desk.drafts import DraftConflict, save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def check(width, browser, root, evidence):
    with tempfile.TemporaryDirectory(dir=root, prefix='preparation-') as tmp:
        folder=Path(tmp);home=folder/'home';home.mkdir();(home/'config.toml').write_text('model="fixture"\n')
        a=folder/'active';a.mkdir();b=folder/'removed';b.mkdir()
        desk=Desk('not-executed',home,folder/'state')
        for id,cwd in [('a',a),('b',b),('c',b)]:
            desk.store.create(str(cwd),'default',identifier=id,name='Project '+id.upper())
            desk.store.update(id,thread_id='native-'+id,status='saved',thread_saved=1,name_pending=0)
        save_draft(desk.store,'a','Active Plan remains exactly unchanged.','plan',0)
        save_draft(desk.store,'b','Retained next check.','plan',0)
        save_draft(desk.store,'c','Archived review.','native',0);desk.store.archive('c',True)
        first=add_followup(desk.store,'b','Check the retained command output.','native')
        add_followup(desk.store,'b','Inspect the second queued decision.','plan')
        queue=followup_snapshot(desk.store,'b');b.rmdir()
        native=[];http=[];errors=[]
        class Catalog:
            def request(self,method,params):
                native.append(method);assert method=='thread/list';return {'data':[],'nextCursor':None}
        desk.catalog=lambda:Catalog()
        def open_saved(id):
            native.append('explicit-open:'+id);assert id=='a'
            desk.store.update(id,status='ready',provider='fixture',model='fixture')
            return {'thread':{'id':'native-a','cwd':str(a),'name':'Active Plan','turns':[]},'model':'fixture','modelProvider':'fixture'}
        desk.open=open_saved
        base=handler(desk)
        class Handler(base):
            def do_GET(self):http.append(('GET',urlsplit(self.path).path));return super().do_GET()
            def do_POST(self):http.append(('POST',urlsplit(self.path).path));return super().do_POST()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler);worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844})
        page=await context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
        await context.grant_permissions(['clipboard-read','clipboard-write'])
        checks=[];draft_response_codes=[]
        page.on('response',lambda response: draft_response_codes.append(response.status)
            if response.request.method=='POST' and urlsplit(response.url).path=='/api/draft' else None)
        async def unchanged():
            assert await page.evaluate("selected==='a' && nativeThreadId==='native-a'")
            assert await page.locator('#prompt').input_value()=='Active Plan remains exactly unchanged.'
            assert await page.locator('#turn-mode').input_value()=='plan'
            assert load_draft(desk.store,'a')['text']=='Active Plan remains exactly unchanged.'
            assert followup_snapshot(desk.store,'b')==queue
            assert native==native_before
            assert not any(method=='POST' and path not in ('/api/open','/api/draft') for method,path in http)
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        try:
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.locator('.session-row[data-session="a"] .session').click()
            await page.wait_for_function("selected==='a' && !opening && !$('task').hidden")
            native_before=list(native)
            await page.locator('#show-preparation').click()
            await page.wait_for_function("$('preparation-list').textContent.includes('Project B')")
            assert 'Project C' not in await page.locator('#preparation-list').inner_text()
            await page.get_by_role('button',name='Review preparation in Project B',exact=True).click()
            await page.wait_for_function("!$('preparation-save').disabled")
            assert await page.locator('#preparation-text').input_value()=='Retained next check.'
            assert not await page.locator('#preparation-conflict').is_visible()
            assert str(b) in await page.locator('#preparation-editor-binding').inner_text()
            assert await page.locator('.preparation-followup').count()==2
            await unchanged();checks.append('removed-folder local review isolates active Plan and preserves queue')
            await page.locator('.preparation-followup').first.get_by_role('button',name='Use in this session draft',exact=True).click()
            assert await page.locator('#preparation-text').input_value()=='Retained next check.'
            await page.locator('#preparation-append').click()
            assert await page.locator('#preparation-text').input_value()=='Retained next check.\n\n'+first['text']
            assert load_draft(desk.store,'b')['text']=='Retained next check.'
            await page.locator('#preparation-save').click()
            await page.wait_for_function("$('preparation-draft-status').textContent.includes('Draft saved locally') && !$('preparation-save').disabled")
            assert load_draft(desk.store,'b')['text']=='Retained next check.\n\n'+first['text']
            assert load_draft(desk.store,'b')['mode']=='plan'
            await page.locator('#preparation-copy').click()
            await page.wait_for_function("$('preparation-draft-status').textContent.includes('Draft text copied')")
            assert await page.evaluate('navigator.clipboard.readText()')==load_draft(desk.store,'b')['text']
            await unchanged();checks.append('explicit append/save/real clipboard reuse leaves original queue unchanged')
            await page.locator('#preparation-text').fill('MY REVIEW retained during conflict.')
            saved=load_draft(desk.store,'b');save_draft(desk.store,'b','OTHER TAB newer draft.','native',saved['revision'])
            await page.locator('#preparation-save').click()
            await page.locator('#preparation-conflict').wait_for()
            assert await page.locator('#preparation-text').input_value()=='MY REVIEW retained during conflict.'
            await page.locator('#preparation-keep').click()
            await page.wait_for_function("$('preparation-conflict').hidden && !$('preparation-save').disabled")
            assert load_draft(desk.store,'b')['text']=='MY REVIEW retained during conflict.'
            assert not await page.locator('#preparation-conflict').is_visible()
            await unchanged();checks.append('real revision conflict keeps editor until explicit keep-mine save')
            await page.locator('#preparation-archived').check()
            await page.wait_for_function("$('preparation-list').textContent.includes('Project C')")
            await page.locator('#preparation-close').click()
            await page.reload();await page.wait_for_function("selected==='a' && !opening && !$('task').hidden")
            native_before=list(native)
            await page.locator('#show-preparation').click()
            await page.wait_for_function("$('preparation-list').textContent.includes('Project B')")
            await page.get_by_role('button',name='Review preparation in Project B',exact=True).click()
            await page.wait_for_function("!$('preparation-save').disabled")
            assert await page.locator('#preparation-text').input_value()=='MY REVIEW retained during conflict.'
            await unchanged();checks.append('reload restores saved cross-project preparation and original active Plan')

            # A deliberate modal save for a clean active session updates its own
            # task box; the local overview does not require a native reopen.
            await page.get_by_role('button',name='Review preparation in Project A',exact=True).click()
            clean_text='Clean same-session work reviewed in Prepared work.'
            await page.locator('#preparation-text').fill(clean_text)
            await page.locator('#preparation-mode').select_option('native')
            await page.locator('#preparation-save').click()
            await page.wait_for_function("v => !$('preparation-save').disabled && $('prompt').value===v",arg=clean_text)
            assert await page.locator('#turn-mode').input_value()=='native'
            assert load_draft(desk.store,'a')['text']==clean_text
            assert not await page.evaluate("draftConflicts.has('a')")
            assert native==native_before and followup_snapshot(desk.store,'b')==queue
            checks.append('explicit clean same-session save updates active text and mode without native reopen')
            await page.locator('#preparation-close').click()

            # Hold the normal task-box writer before its SQLite transaction.
            # The modal's distinct writer can save against the reviewed revision
            # while this request is pending; releasing it must return a real409.
            normal_text='NORMAL TASK BOX unsaved Plan stays here while its save waits.'
            modal_text='MODAL CHOICE saved locally without replacing pending Plan.'
            entered,release=threading.Event(),threading.Event();root_conflicts=[]
            root_writer=await page.evaluate('draftWriter')
            def controlled_save(store,session,text,mode,revision,writer=None,sequence=None):
                held=session=='a' and writer==root_writer and text==normal_text
                if held:
                    entered.set();assert release.wait(30),'Unreleased normal draft save'
                try:return save_draft(store,session,text,mode,revision,writer,sequence)
                except DraftConflict:
                    if held:root_conflicts.append('real revision409')
                    raise
            try:
                with patch.object(desk_server,'save_draft',side_effect=controlled_save):
                    await page.locator('#prompt').fill(normal_text)
                    await page.locator('#turn-mode').select_option('plan')
                    assert await asyncio.to_thread(entered.wait,10),'Normal task-box save never entered the held POST'
                    await page.wait_for_function("draftSaves.has('a')")
                    assert load_draft(desk.store,'a')['text']==clean_text
                    await page.locator('#show-preparation').click()
                    await page.wait_for_function("$('preparation-list').textContent.includes('Project A')")
                    await page.get_by_role('button',name='Review preparation in Project A',exact=True).click()
                    assert await page.locator('#preparation-text').input_value()==clean_text
                    await page.locator('#preparation-text').fill(modal_text)
                    await page.locator('#preparation-mode').select_option('native')
                    await page.locator('#preparation-save').click()
                    await page.wait_for_function("!$('preparation-save').disabled && draftConflicts.has('a')")
                    assert await page.locator('#prompt').input_value()==normal_text
                    assert await page.locator('#turn-mode').input_value()=='plan'
                    assert await page.evaluate("draftConflicts.get('a').text")==modal_text
                    assert load_draft(desk.store,'a')['text']==modal_text
                    assert load_draft(desk.store,'a')['mode']=='native'
                    assert native==native_before and followup_snapshot(desk.store,'b')==queue
                    conflicts_before=draft_response_codes.count(409);release.set()
                    await page.wait_for_function("!draftSaves.has('a') && draftConflicts.has('a')")
                    assert root_conflicts==['real revision409']
                    assert draft_response_codes.count(409)==conflicts_before+1,draft_response_codes
                    assert await page.locator('#prompt').input_value()==normal_text
                    assert await page.locator('#turn-mode').input_value()=='plan'
                    assert load_draft(desk.store,'a')['text']==modal_text
                    assert await page.locator('#preparation-text').input_value()==modal_text
                    assert await page.evaluate("!$('draft-conflict').hidden && !$('draft-keep').hidden && !$('draft-load').hidden")
                    checks.append('pending normal POST receives real409 after modal save; both same-session drafts and conflict choices remain')
                    await page.locator('#preparation-close').click()
                    await page.locator('#draft-load').click()
                    assert await page.locator('#prompt').input_value()==modal_text
                    assert await page.locator('#turn-mode').input_value()=='native'
                    assert not await page.evaluate("draftConflicts.has('a')")
                    assert load_draft(desk.store,'a')['text']==modal_text
                    assert native==native_before and followup_snapshot(desk.store,'b')==queue
                    checks.append('explicit Load saved resolves same-session coordination without a task or native call')
            finally:release.set()

            # The normal task-box writer can clear a draft while this modal's
            # retained editor has unsaved text. A query-free refresh must read
            # the exact empty revision, not mistake list absence for filtering.
            await page.locator('#show-preparation').click()
            await page.wait_for_function("!$('preparation-list').getAttribute('aria-busy') || $('preparation-list').getAttribute('aria-busy')==='false'")
            await page.get_by_role('button',name='Review preparation in Project A',exact=True).click()
            retained_text='UNSAVED PREPARATION remains until I choose how to handle the cleared draft.'
            await page.locator('#preparation-text').fill(retained_text)
            await page.locator('#preparation-mode').select_option('plan')
            await page.locator('#preparation-close').click()
            await page.locator('#prompt').fill('')
            await page.wait_for_function("draftSaved.get('a')?.text==='' && !draftTimers.has('a') && !draftSaves.has('a')")
            cleared=load_draft(desk.store,'a');assert cleared['text']==''
            reads_before=sum(method=='GET' and path=='/api/draft' for method,path in http)
            posts_before=sum(method=='POST' and path=='/api/draft' for method,path in http)
            await page.locator('#show-preparation').click()
            await page.locator('#preparation-conflict').wait_for()
            await page.locator('#preparation-refresh').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            assert not await page.locator('.preparation-session[data-session="a"]').count()
            assert await page.locator('#preparation-text').input_value()==retained_text
            assert await page.locator('#preparation-mode').input_value()=='plan'
            assert await page.locator('#preparation-save').is_disabled()
            assert sum(method=='GET' and path=='/api/draft' for method,path in http)>reads_before
            assert sum(method=='POST' and path=='/api/draft' for method,path in http)==posts_before
            await page.locator('#preparation-load').click()
            assert await page.locator('#preparation-text').input_value()==''
            assert await page.locator('#preparation-mode').input_value()==cleared['mode']
            assert not await page.locator('#preparation-conflict').is_visible()
            assert await page.locator('#prompt').input_value()==''
            assert load_draft(desk.store,'a')==cleared
            assert native==native_before and followup_snapshot(desk.store,'b')==queue
            checks.append('actual workbench clear and explicit Refresh retain unsaved preparation until Load saved; exact empty revision is read without a save/native call')
            assert not any(method=='POST' and path not in ('/api/open','/api/draft') for method,path in http)
            await page.screenshot(path=str(evidence/f'preparation-{width}.png'))
            assert not errors
            receipt={'width':width,'checks':checks,'javascript_errors':errors,'controlled_model_turns':0,'preparation_native_calls':0,
                     'same_session_clean_update':True,'pending_root_revision_conflict':root_conflicts,'draft_response_codes':draft_response_codes}
            (evidence/f'acceptance-{width}.json').write_text(json.dumps(receipt,indent=2)+'\n')
            return len(checks)
        except Exception:
            await page.screenshot(path=str(evidence/f'failure-{width}.png'),full_page=True)
            raise
        finally:
            await context.close();server.shutdown();server.server_close();worker.join(timeout=5);desk.close();desk.store.db.close()


async def main():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ.get('DESK_TEST_EVIDENCE',str(root/'preparation-evidence')));evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:count=sum([await check(width,browser,root,evidence) for width in (1250,390)])
        finally:await browser.close()
    for f in evidence.iterdir():
        if f.is_file():f.chmod(0o600)
    print(json.dumps({'preparation_acceptance':'PASS','checks':count,'widths':[1250,390],'controlled_model_turns':0}))


if __name__=='__main__':asyncio.run(main())
