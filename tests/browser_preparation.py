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
        a=folder/'active';a.mkdir();b=folder/'removed';b.mkdir();d=folder/'daily';d.mkdir()
        desk=Desk('not-executed',home,folder/'state')
        for id,cwd in [('a',a),('b',b),('c',b),('d',d)]:
            desk.store.create(str(cwd),'default',identifier=id,name='Project '+id.upper())
            desk.store.update(id,thread_id='native-'+id,status='saved',thread_saved=1,name_pending=0)
        save_draft(desk.store,'a','Active Plan remains exactly unchanged.','plan',0)
        save_draft(desk.store,'b','Retained next check.','plan',0)
        save_draft(desk.store,'c','Archived review.','native',0);desk.store.archive('c',True)
        first=add_followup(desk.store,'b','Check the retained command output.','native')
        add_followup(desk.store,'b','Inspect the second queued decision.','plan')
        queue=followup_snapshot(desk.store,'b');b.rmdir()
        daily_work=add_followup(desk.store,'d','Verify the retained acceptance using native tools.','native')
        daily_plan=add_followup(desk.store,'d','Clarify the next saved decision before editing.','plan')
        daily_queue=followup_snapshot(desk.store,'d')
        native=[];http=[];errors=[]
        class Catalog:
            def request(self,method,params):
                native.append(method);assert method=='thread/list';return {'data':[],'nextCursor':None}
        open_control={'fail':False}
        def open_saved(id):
            native.append('explicit-open:'+id);assert id in ('a','d')
            if id=='d' and open_control['fail']:raise OSError('Daily project temporarily unavailable')
            desk.store.update(id,status='ready',provider='fixture',model='fixture')
            if id=='d' and open_control.get('entered'):
                open_control['entered'].set()
                assert open_control['release'].wait(30),'Native open reply was not released'
            return {'thread':{'id':'native-'+id,'cwd':str(a if id=='a' else d),'name':'Project '+id.upper(),'turns':[]},'model':'fixture','modelProvider':'fixture'}
        def start_server(port=0):
            desk.catalog=lambda:Catalog();desk.open=open_saved
            base=handler(desk)
            class Handler(base):
                def do_GET(self):http.append(('GET',urlsplit(self.path).path));return super().do_GET()
                def do_POST(self):http.append(('POST',urlsplit(self.path).path));return super().do_POST()
            server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
            worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
            return server,worker
        def stop_server():
            server.shutdown();server.server_close();worker.join(timeout=5);desk.close();desk.store.db.close()
        server,worker=start_server()
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
            # Ordinary first-task reuse: append preserves the destination Plan;
            # Save and open never hands off an older capture after newer typing.
            daily_native_before=list(native)
            await page.get_by_role('button',name='Review preparation in Project D',exact=True).click()
            await page.wait_for_function("!$('preparation-save-open').disabled")
            await page.locator('#preparation-text').fill('Reviewed destination before the acceptance.')
            await page.locator('#preparation-mode').select_option('plan')
            await page.locator(f'.preparation-followup[data-followup="{daily_work["id"]}"]').get_by_role('button',name='Use in this session draft',exact=True).click()
            await page.locator('#preparation-append').click()
            captured='Reviewed destination before the acceptance.\n\n'+daily_work['text']
            assert await page.locator('#preparation-text').input_value()==captured
            assert await page.locator('#preparation-mode').input_value()=='plan'
            assert load_draft(desk.store,'d')['text']==''
            assert await page.locator('#preparation-open').inner_text()=='Open without these edits'
            entered,release=threading.Event(),threading.Event()
            def hold_reviewed_reply(store,session,text,mode,revision,writer=None,sequence=None):
                result=save_draft(store,session,text,mode,revision,writer,sequence)
                if session=='d' and text==captured:
                    entered.set();assert release.wait(30),'Reviewed save reply was not released'
                return result
            try:
                with patch.object(desk_server,'save_draft',side_effect=hold_reviewed_reply):
                    await page.locator('#preparation-save-open').click()
                    assert await asyncio.to_thread(entered.wait,10),'Reviewed save never entered'
                    assert await page.locator('#preparation-open').is_disabled()
                    newer='Newer unsent Work acceptance after the reviewed capture.'
                    await page.locator('#preparation-text').fill(newer)
                    await page.locator('#preparation-mode').select_option('native')
                    release.set()
                    await page.wait_for_function("!$('preparation-save-open').disabled")
                    assert await page.locator('#preparation').is_visible()
                    assert await page.locator('#preparation-text').input_value()==newer
                    assert load_draft(desk.store,'d')['text']==captured
                    assert native==daily_native_before
                    assert await page.evaluate("selected==='a'")
            finally:release.set()
            await page.locator('#preparation-save-open').click()
            await page.wait_for_function("!$('preparation').open && selected==='d' && !opening && !$('task').hidden")
            assert await page.locator('#prompt').input_value()==newer
            assert await page.locator('#turn-mode').input_value()=='native'
            assert load_draft(desk.store,'d')['text']==newer
            assert followup_snapshot(desk.store,'d')==daily_queue
            assert native==daily_native_before+['explicit-open:d']
            checks.append('queued Work append preserves destination Plan; a late save keeps newer Work edits local until a second explicit Save and open shows the exact unsent task')

            # Save has finished, but the admitted native Open reply is still
            # waiting. New typing belongs to this retained local editor, not
            # the saved capture being opened behind it.
            await page.locator('#show-preparation').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await page.get_by_role('button',name='Review preparation in Project D',exact=True).click()
            saved_open_capture='Saved Plan capture before the native Open reply.'
            await page.locator('#preparation-text').fill(saved_open_capture)
            await page.locator('#preparation-mode').select_option('plan')
            entered,release=threading.Event(),threading.Event()
            open_control.update(entered=entered,release=release)
            opens_before=list(native)
            try:
                await page.locator('#preparation-save-open').click()
                assert await asyncio.to_thread(entered.wait,10),'Native open never entered the held reply'
                assert load_draft(desk.store,'d')['text']==saved_open_capture
                assert load_draft(desk.store,'d')['mode']=='plan'
                assert native==opens_before+['explicit-open:d']
                assert await page.locator('#preparation-open').is_disabled()
                newer='Newer unsent Work while the native Open reply waits.'
                await page.locator('#preparation-text').fill(newer)
                await page.locator('#preparation-mode').select_option('native')
                release.set()
                await page.wait_for_function("!opening && !$('preparation-save-open').disabled && $('preparation').open")
                assert await page.locator('#prompt').input_value()==saved_open_capture
                assert await page.locator('#turn-mode').input_value()=='plan'
                assert await page.locator('#preparation-text').input_value()==newer
                assert await page.locator('#preparation-mode').input_value()=='native'
                assert 'Newer edits' in await page.locator('#preparation-draft-status').inner_text()
                assert load_draft(desk.store,'d')['text']==saved_open_capture
                assert followup_snapshot(desk.store,'d')==daily_queue
                assert native==opens_before+['explicit-open:d']
            finally:
                release.set();open_control.pop('entered',None);open_control.pop('release',None)
            await page.get_by_role('button',name='Review preparation in Project B',exact=True).click()
            await page.get_by_role('button',name='Review preparation in Project D',exact=True).click()
            assert await page.locator('#preparation-text').input_value()==newer
            assert await page.locator('#preparation-mode').input_value()=='native'
            await page.locator('#preparation-save').click()
            await page.wait_for_function("v => !$('preparation-save').disabled && $('prompt').value===v",arg=newer)
            assert load_draft(desk.store,'d')['text']==newer
            assert load_draft(desk.store,'d')['mode']=='native'
            assert await page.locator('#turn-mode').input_value()=='native'
            assert native==opens_before+['explicit-open:d']
            assert followup_snapshot(desk.store,'d')==daily_queue
            await page.locator('#preparation-close').click()
            checks.append('real held native Open reply admits one open and shows its saved Plan capture while newer Work text stays in the current modal, survives review switching, and reaches the task only after an explicit later local Save')

            # Replace explicitly adopts the queued Plan mode. Real save errors,
            # another writer's revision, and an unavailable open each keep it.
            await page.locator('#show-preparation').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await page.get_by_role('button',name='Review preparation in Project D',exact=True).click()
            await page.locator(f'.preparation-followup[data-followup="{daily_plan["id"]}"]').get_by_role('button',name='Use in this session draft',exact=True).click()
            await page.locator('#preparation-replace').click()
            assert await page.locator('#preparation-text').input_value()==daily_plan['text']
            assert await page.locator('#preparation-mode').input_value()=='plan'
            opens_before=list(native)
            with patch.object(desk_server,'save_draft',side_effect=OSError('Daily save temporarily unavailable')):
                await page.locator('#preparation-save-open').click()
                await page.wait_for_function("!$('preparation-save-open').disabled && $('preparation-draft-status').textContent.includes('not saved')")
            assert native==opens_before and await page.locator('#preparation').is_visible()
            assert load_draft(desk.store,'d')['text']==newer
            current=load_draft(desk.store,'d')
            save_draft(desk.store,'d','Other tab saved daily Work.','native',current['revision'])
            await page.locator('#preparation-save-open').click()
            await page.locator('#preparation-conflict').wait_for()
            assert await page.locator('#preparation-text').input_value()==daily_plan['text']
            assert await page.locator('#preparation-save-open').is_disabled() and native==opens_before
            await page.locator('#preparation-keep').click()
            await page.wait_for_function("$('preparation-conflict').hidden && !$('preparation-save-open').disabled")
            assert await page.locator('#prompt').input_value()==daily_plan['text']
            assert await page.locator('#turn-mode').input_value()=='plan'
            open_control['fail']=True
            await page.locator('#preparation-save-open').click()
            await page.wait_for_function("!$('preparation-save-open').disabled && !$('preparation-error').hidden")
            assert await page.locator('#preparation').is_visible()
            assert await page.locator('#preparation-text').input_value()==daily_plan['text']
            assert load_draft(desk.store,'d')['text']==daily_plan['text']
            posts_before=sum(method=='POST' and path=='/api/draft' for method,path in http)
            open_control['fail']=False;await page.locator('#preparation-open').click()
            await page.wait_for_function("!$('preparation').open && selected==='d' && !opening && !$('task').hidden")
            assert await page.locator('#prompt').input_value()==daily_plan['text']
            assert await page.locator('#turn-mode').input_value()=='plan'
            assert sum(method=='POST' and path=='/api/draft' for method,path in http)==posts_before
            assert followup_snapshot(desk.store,'d')==daily_queue
            checks.append('queued Plan replacement survives a failed real save and external revision conflict; explicit keep/save and native open retry show the exact unsent Plan without changing its queue')

            # Cold same-state return uses a new Desk/Store and the same browser
            # origin, recovering the saved binding, mode and queued originals.
            await page.wait_for_function("!draftTimers.size && !draftSaves.size")
            port=server.server_port
            await asyncio.to_thread(stop_server)
            desk=Desk('not-executed',home,folder/'state');server,worker=start_server(port)
            await page.reload()
            await page.wait_for_function("selected==='d' && !opening && !$('task').hidden")
            assert await page.locator('#prompt').input_value()==daily_plan['text']
            assert await page.locator('#turn-mode').input_value()=='plan'
            assert await page.evaluate("nativeThreadId==='native-d'")
            assert followup_snapshot(desk.store,'d')==daily_queue
            assert followup_snapshot(desk.store,'b')==queue
            assert load_draft(desk.store,'a')['text']==''
            await page.locator('#show-preparation').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await page.get_by_role('button',name='Review preparation in Project D',exact=True).click()
            assert await page.locator('#preparation-text').input_value()==daily_plan['text']
            assert await page.locator('#preparation-mode').input_value()=='plan'
            assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
            assert not any(method=='POST' and path not in ('/api/open','/api/draft') for method,path in http)
            checks.append('cold same-state Desk/Store restart restores the exact unsent Plan, native binding and both original prepared queues; review remains local at this width')
            await page.screenshot(path=str(evidence/f'preparation-{width}.png'))
            assert not errors
            receipt={'width':width,'checks':checks,'javascript_errors':errors,'controlled_model_turns':0,'explicit_preparation_opens':native[len(daily_native_before):],'cold_restart_same_state':True,'newer_editor_during_native_open':True,
                     'same_session_clean_update':True,'pending_root_revision_conflict':root_conflicts,'draft_response_codes':draft_response_codes}
            (evidence/f'acceptance-{width}.json').write_text(json.dumps(receipt,indent=2)+'\n')
            return len(checks)
        except Exception:
            await page.screenshot(path=str(evidence/f'failure-{width}.png'),full_page=True)
            raise
        finally:
            await context.close();stop_server()


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
