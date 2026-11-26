"""First-use recent native work via real HTTP/SQLite; controlled native responses.

DESK_TEST_TEMP=/workspace/temp DESK_CHROMIUM=/usr/bin/chromium python tests/browser_home.py
Use DESK_USE_INSTALLED=1 for an installed package and DESK_TEST_EVIDENCE for receipts.
"""
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import urlsplit
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(root / 'home-evidence')))
    evidence.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-home-') as tmp:
        folder=Path(tmp); project=folder/'demo-app'; project.mkdir()
        home=folder/'home'; home.mkdir(); (home/'config.toml').write_text('model="fixture"\n')
        before=(home/'config.toml').read_bytes()
        desk=Desk('never-executed', home, folder/'state')
        def thread(n):
            return {'id': 'native-'+str(n), 'cwd': str(project), 'name': 'Verify the checkout flow' if n==0 else 'Project task '+str(n),
                'modelProvider':'openai', 'model':'fixture', 'turns':[{'id':'prior-turn', 'items':[
                    {'id':'task','type':'userMessage','content':[{'type':'text','text':'Run the checkout tests and summarize the result.'}]},
                    {'id':'command','type':'commandExecution','command':'npm test -- checkout', 'aggregatedOutput':'12 checkout tests passed', 'exitCode':0, 'status':'completed'},
                    {'id':'answer','type':'agentMessage','text':'## Checkout verified\nAll 12 tests passed. Next: check the empty-cart state.'}]}]}
        threads={t['id']:t for t in [thread(n) for n in range(8)]}
        missing=thread(99);missing['cwd']=str(folder/'removed-project');missing['name']='Work in a removed folder'
        threads={missing['id']:missing,**threads}
        pristine=json.dumps(threads,sort_keys=True)
        native_calls=[]; http_calls=[]; opened=[]; controls={}
        def hold(key):
            if controls.get('hold')==key:
                controls['entered'].set(); assert controls['release'].wait(12)
        class Catalog:
            def request(self, method, params):
                native_calls.append((method,params)); assert method in ('thread/list','thread/read')
                hold('list' if method=='thread/list' else 'read')
                if method=='thread/read': return {'thread':threads[params['threadId']]}
                if controls.get('fail'): raise RuntimeError('Fixture catalog unavailable')
                return {'data':[] if controls.get('empty') else list(threads.values()), 'nextCursor':None}
        desk.catalog=lambda:Catalog()
        def open_saved(identifier):
            opened.append(identifier); binding=desk.store.get(identifier)
            desk.store.update(identifier,status='ready',provider='openai',model='fixture')
            native_calls.append(('thread/resume',{'threadId':binding['thread_id']}))
            return {'thread':threads[binding['thread_id']], 'model':'fixture','modelProvider':'openai'}
        desk.open=open_saved
        ordinary=handler(desk)
        class Handler(ordinary):
            def do_GET(self): http_calls.append(('GET',urlsplit(self.path).path)); return super().do_GET()
            def do_POST(self): http_calls.append(('POST',urlsplit(self.path).path)); return super().do_POST()
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler); worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        results=[]; errors=[]
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(headless=True,executable_path=os.environ.get('DESK_CHROMIUM'))
                async def visit(width=1250,last=None):
                    context=await browser.new_context(viewport={'width':width,'height':950})
                    if last: await context.add_init_script('localStorage.setItem("codex-desk-session",'+json.dumps(last)+')')
                    page=await context.new_page(); page.on('pageerror',lambda e:errors.append(str(e)))
                    await page.goto(f'http://127.0.0.1:{server.server_port}')
                    return context,page
                for width in (1250,390):
                    native_calls.clear(); http_calls.clear(); opened.clear()
                    context,page=await visit(width)
                    await page.wait_for_function('document.querySelector("#home-list").children.length===6')
                    await page.wait_for_timeout(4200)
                    assert [c[0] for c in native_calls]==['thread/list'],native_calls
                    assert 'unavailable' in await page.locator('#home-status').inner_text()
                    assert 'Work in a removed folder' not in await page.locator('#home-list').inner_text()
                    assert not any(method=='POST' for method,path in http_calls),http_calls
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if width==1250:
                        await page.locator('#home-list small').evaluate_all("els=>els.forEach(e=>e.textContent='/projects/demo-app · openai')")
                        await page.screenshot(path=str(evidence/'home.png'))
                    await page.locator('#home-list button').first.click(); await page.locator('#task').wait_for()
                    assert 'All 12 tests passed.' in await page.locator('#activity').inner_text()
                    await page.locator('#activity details summary').first.click()
                    assert '12 checkout tests passed' in await page.locator('#activity').inner_text()
                    assert [c[0] for c in native_calls]==['thread/list','thread/read','thread/resume']
                    binding=desk.store.sessions()[0]; assert binding['thread_id']=='native-0' and binding['profile']=='default'
                    assert await page.locator('#welcome').is_hidden()
                    assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                    if width==1250:
                        await page.locator('#prompt').fill('Check the empty-cart state next. Keep the checkout tests passing.')
                        await page.wait_for_function('document.querySelector("#draft-status").textContent.includes("Draft saved locally")')
                        await page.locator('#binding').evaluate("e=>e.textContent='/projects/demo-app · Current Codex settings → openai / configured model'")
                        await page.locator('.project-path').evaluate_all("els=>els.forEach(e=>e.textContent='/projects/demo-app')")
                        await page.screenshot(path=str(evidence/'resumed.png'))
                    results.append({'case':'one-click-existing','width':width,'thread':'native-0','noAutomaticTask':True})
                    await context.close()
                saved_id=desk.store.sessions()[0]['id']
                native_calls.clear(); context,page=await visit(last=saved_id)
                await page.locator('#task').wait_for(); assert [c[0] for c in native_calls]==['thread/resume']
                assert 'Check the empty-cart state next.' in await page.locator('#prompt').input_value()
                results.append({'case':'return-same-thread-and-draft','noCatalogRequest':True}); await context.close()
                controls['empty']=True; context,page=await visit(390)
                await page.wait_for_function('document.querySelector("#home-status").textContent.includes("No saved conversations")')
                await page.locator('#home-project').click(); await page.locator('#project').wait_for(); await page.locator('#cancel').click()
                await page.locator('#home-browse').click(); await page.locator('#history').wait_for()
                results.append({'case':'empty-home-actions'}); await context.close(); controls.clear()
                controls['fail']=True; context,page=await visit()
                await page.locator('#home-retry').wait_for(); assert 'Fixture catalog unavailable' in await page.locator('#home-error').inner_text()
                controls.clear(); await page.locator('#home-retry').click()
                await page.wait_for_function('document.querySelector("#home-list").children.length===6')
                results.append({'case':'failure-explicit-retry'}); await context.close()
                for pending in ('list','read'):
                    controls.clear(); controls.update(hold=pending,entered=threading.Event(),release=threading.Event())
                    context,page=await visit(); opened.clear()
                    if pending=='read':
                        await page.wait_for_function('document.querySelector("#home-list").children.length===6')
                        await page.locator('#home-list button').nth(1).click()
                        await page.wait_for_function('Array.from(document.querySelectorAll("#home-list button")).every(b=>b.disabled)')
                    assert await asyncio.to_thread(controls['entered'].wait,5)
                    await page.locator('.session').first.click(); await page.locator('#task').wait_for()
                    selected_title=await page.locator('#title').inner_text(); selected_opened=list(opened)
                    controls['release'].set(); await page.wait_for_timeout(650)
                    assert await page.locator('#title').inner_text()==selected_title
                    assert opened==selected_opened
                    assert await page.locator('#welcome').is_hidden()
                    results.append({'case':'late-'+pending+'-cannot-replace-selection'}); await context.close()
                controls.clear()
                assert not any(method in ('thread/start','turn/start') for method,params in native_calls)
                assert not any(path in ('/api/turn','/api/sessions') for method,path in http_calls)
                assert (home/'config.toml').read_bytes()==before
                assert json.dumps(threads,sort_keys=True)==pristine
                assert not errors,errors
                await browser.close()
        finally:
            if controls.get('release'): controls['release'].set()
            server.shutdown();worker.join(timeout=5);server.server_close();desk.close();desk.store.db.close()
        receipt={'pass':True,'cases':results,'pageErrors':errors,'originalSettingsAndHistoryPreserved':True,'newNativeTurns':0}
        (evidence/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n'); print(json.dumps(receipt,indent=2))

if __name__=='__main__': asyncio.run(check())
