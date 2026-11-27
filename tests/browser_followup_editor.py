"""Held queued-entry editing through the product app, HTTP and ephemeral Chromium."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

SOURCE = Path(os.environ.get('DESK_SOURCE', str(Path(__file__).resolve().parents[1]))).resolve()
USE_INSTALLED = os.environ.get('DESK_USE_INSTALLED') == '1'
if not USE_INSTALLED:
    sys.path.insert(0, str(SOURCE))
import codex_desk
PACKAGE_PATH = Path(codex_desk.__file__).resolve()
if USE_INSTALLED:
    assert not PACKAGE_PATH.is_relative_to(SOURCE), f'Installed acceptance imported source package: {PACKAGE_PATH}'
from codex_desk.server import Desk, handler
from codex_desk.followups import add_followup, edit_followup, list_followups
from playwright.async_api import async_playwright

ACCESS = 'private-queued-editor-fixture'
LONG = ('Exact queued Work — 保留 résumé  \n' * 130) + 'ORIGINAL END  '
NEWER = ('Newer unsent Plan — 保留  \n' * 110) + 'NEWER END  '


class Fixture:
    def __init__(self, root):
        self.desk = Desk('never-executed', root/'home', root/'state')
        self.opens, self.http, self.gates = [], [], []
        for session in ('a', 'b'):
            self.desk.store.create(str(root/session), 'default', identifier=session, name='Project '+session.upper())
            self.desk.store.update(session, status='saved', thread_id='native-'+session, thread_saved=1, name_pending=0)
        self.one = add_followup(self.desk.store, 'a', LONG, 'native')
        self.two = add_followup(self.desk.store, 'a', 'Other Plan '+LONG, 'plan')
        self.three = add_followup(self.desk.store, 'a', 'Other Work '+LONG, 'native')
        self.b = add_followup(self.desk.store, 'b', 'B retained Plan '+LONG, 'plan')
        owner = self
        class Catalog:
            def request(self, method, params):
                assert method == 'thread/list', method
                return {'data': [], 'nextCursor': None}
        self.desk.catalog = lambda: Catalog()
        def open_session(session):
            owner.opens.append(session)
            return {'thread': {'id': 'native-'+session, 'cwd': str(root/session), 'turns': []},
                    'model': 'fixture', 'modelProvider': 'fixture'}
        self.desk.open = open_session
        class Handler(handler(self.desk, ACCESS)):
            def do_POST(self):
                owner.http.append({'method': 'POST', 'path': urlsplit(self.path).path})
                super().do_POST()
            def reply(self, value, status=200):
                if self.command == 'POST' and self.path == '/api/followups/edit':
                    owner.http[-1]['status'] = status
                    for gate in owner.gates:
                        if gate['armed']:
                            gate['armed'] = False; gate['entered'].set()
                            assert gate['release'].wait(30), 'Held queue edit reply not released'
                            break
                super().reply(value, status)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval':.01}, daemon=True)
        self.worker.start()

    def gate(self):
        gate={'armed':True, 'entered':threading.Event(), 'release':threading.Event()}
        self.gates.append(gate)
        return gate

    def finish(self):
        for gate in self.gates: gate['release'].set()
        self.server.shutdown(); self.server.server_close(); self.worker.join(5)
        self.desk.close(); self.desk.store.db.close()


async def check(browser, width, root, evidence):
    f=Fixture(root)
    context=await browser.new_context(viewport={'width':width, 'height':844})
    page=await context.new_page();page.set_default_timeout(12_000)
    errors,external=[],[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    url=f'http://127.0.0.1:{f.server.server_port}'
    async def isolated(route):
        if urlsplit(route.request.url).netloc != urlsplit(url).netloc:
            external.append(route.request.url);await route.abort()
        else: await route.continue_()
    await context.route('**/*',isolated)
    try:
        await page.goto(url+'/#access='+ACCESS)
        await page.wait_for_function('state.sessions.length===2')
        async def choose(session):
            await page.locator(f'.session-row[data-session="{session}"] .session').click()
            await page.wait_for_function('s=>selected===s && !opening && !$("task").hidden',arg=session)
            await page.locator('#followups').evaluate('n=>n.open=true')
            await page.wait_for_function('$("followup-list").querySelectorAll(".followup-entry").length>0')
        def row(entry): return page.locator(f'.followup-entry[data-followup="{entry["id"]}"]')
        async def edit(entry,text,mode):
            await row(entry).get_by_role('button',name='Edit',exact=True).click()
            await row(entry).get_by_role('textbox',name='Follow-up task').fill(text)
            await row(entry).get_by_role('combobox',name='Follow-up mode').select_option(mode)
        async def hold_reader(entry):
            await row(entry).get_by_role('textbox',name='Follow-up task').evaluate("""n=>{
              window.liveReader=n;n.focus({preventScroll:true});n.setSelectionRange(9,31,'backward');n.scrollTop=80;
              document.getElementById('followup-list').scrollTop=37;
            }""")
            return await reader_snapshot(entry)
        async def reader_snapshot(entry):
            return await row(entry).get_by_role('textbox',name='Follow-up task').evaluate("""n=>({
              same:n===window.liveReader,active:n===document.activeElement,text:n.value,
              caret:[n.selectionStart,n.selectionEnd,n.selectionDirection],scroll:n.scrollTop,
              listScroll:document.getElementById('followup-list').scrollTop,
              mode:n.parentElement.querySelector('select').value,session:selected})""")
        async def save(entry):
            await row(entry).get_by_role('button',name='Save changes',exact=True).evaluate('n=>n.click()')
        async def settled(entry):
            await row(entry).get_by_role('button',name='Save changes',exact=True).wait_for(state='visible')
            await page.wait_for_function('id=>![...$("followup-list").querySelectorAll(".followup-entry")].find(n=>n.dataset.followup===id).querySelector("button").disabled',arg=entry['id'])
        await choose('a');await edit(f.one,LONG,'native')
        before=await hold_reader(f.one)
        changed=edit_followup(f.desk.store,'a',f.two['id'],'Other entry updated '+LONG,'plan',f.two['revision'])
        await page.evaluate('DeskFollowups.refresh()')
        assert await reader_snapshot(f.one)==before,'Other-entry refresh changed reader'
        gate=f.gate();await save(f.one);assert await asyncio.to_thread(gate['entered'].wait,10)
        assert await reader_snapshot(f.one)==before,'Pending save changed live reader'
        assert not await row(f.one).get_by_role('textbox',name='Follow-up task').is_disabled()
        await row(f.one).get_by_role('textbox',name='Follow-up task').fill(NEWER)
        await row(f.one).get_by_role('combobox',name='Follow-up mode').select_option('plan')
        newer=await hold_reader(f.one);gate['release'].set();await settled(f.one)
        assert await reader_snapshot(f.one)==newer,'Save response changed newer reader'
        persisted=next(e for e in list_followups(f.desk.store,'a') if e['id']==f.one['id'])
        assert persisted['text']==LONG and persisted['mode']=='native' and persisted['revision']==2
        assert await row(f.two).get_by_role('button',name='Edit',exact=True).is_disabled()
        other=edit_followup(f.desk.store,'a',f.one['id'],'Other tab version '+LONG,'native',persisted['revision'])
        await page.evaluate('DeskFollowups.refresh()')
        assert await reader_snapshot(f.one)==newer
        assert 'This entry changed in another tab' in await row(f.one).inner_text()
        async with page.expect_response(lambda r:urlsplit(r.url).path=='/api/followups/edit') as conflict:
            await save(f.one)
        assert (await conflict.value).status==409
        await settled(f.one);assert await reader_snapshot(f.one)==newer
        assert next(e for e in list_followups(f.desk.store,'a') if e['id']==f.one['id'])==other
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(evidence/f'editor-conflict-{width}.png'),full_page=True)
        await row(f.one).get_by_role('button',name='Cancel edit',exact=True).click()
        await edit(f.one,LONG,'native');gate=f.gate();await save(f.one)
        assert await asyncio.to_thread(gate['entered'].wait,10)
        await row(f.one).get_by_role('textbox',name='Follow-up task').fill(NEWER)
        await row(f.one).get_by_role('combobox',name='Follow-up mode').select_option('plan')
        await choose('b');await edit(f.b,'B newer unsent '+LONG,'plan');b_reader=await hold_reader(f.b)
        gate['release'].set();await page.wait_for_timeout(200)
        assert await reader_snapshot(f.b)==b_reader,'Late A reply changed B editor'
        await choose('a')
        assert await row(f.one).get_by_role('textbox',name='Follow-up task').input_value()==NEWER
        assert await row(f.one).get_by_role('combobox',name='Follow-up mode').input_value()=='plan'
        assert not await row(f.one).get_by_role('textbox',name='Follow-up task').evaluate('n=>n===document.activeElement')
        assert not errors and not external,{'errors':errors,'external':external}
        assert not f.desk.runtimes
        assert not any(call['path'] in ('/api/turn','/api/followups/send','/api/sessions','/api/import') for call in f.http)
        assert [call['status'] for call in f.http if call['path']=='/api/followups/edit']==[200,409,200]
        result={'width':width,'installed':USE_INSTALLED,'package_path':str(PACKAGE_PATH),'other_refresh_exact':True,'pending_reader_exact':True,'newer_reply_reader_exact':True,
            'conflict_local_reader_exact':True,'late_session_reader_exact':True,'http':f.http,'native_starts':0,
            'browser_errors':errors,'external':external,'final_newer_a_unsent':True,'newer_snapshot':newer}
        (evidence/f'result-{width}.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
        print(json.dumps({'width':width,'passed':True,'native_starts':0,'installed':USE_INSTALLED,'package_path':str(PACKAGE_PATH)}),flush=True)
    finally:
        await context.close();f.finish()


async def main():
    os.umask(0o077)
    scratch=Path(os.environ['DESK_TEST_TEMP']);scratch.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,
                                        args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            for width in (1250,390):
                with tempfile.TemporaryDirectory(dir=scratch,prefix='queue-editor-') as temporary:
                    await check(browser,width,Path(temporary),evidence)
        finally: await browser.close()


if __name__=='__main__':
    asyncio.run(main())
