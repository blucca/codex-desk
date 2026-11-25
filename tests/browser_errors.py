"""Actual loopback error/retry paths in open dialogs; no native/provider calls."""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk.runtime import save_profile
from playwright.async_api import async_playwright

class Catalog:
    def request(self, method, params):
        assert method == 'thread/list'
        return {'data':[{'id':'old-thread', 'cwd':'/saved/project-no-longer-exists', 'modelProvider':'openai', 'name':'Old project'}], 'nextCursor':None}

async def check():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-errors-') as folder:
        desk=Desk('not-called',Path(folder)/'home',Path(folder)/'state')
        save_profile(desk.home, 'retained', 'https://example.com/v1', 'existing-model', 'synthetic-only')
        desk.catalog=lambda:Catalog()
        desk.history=lambda thread:{'id':thread, 'cwd':'/saved/project-no-longer-exists', 'turns':[]}
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(desk))
        worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    page=await browser.new_page(viewport={'width':390,'height':844})
                    errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
                    await page.goto(f'http://127.0.0.1:{server.server_port}')
                    await page.wait_for_function('state.profiles.length===2')
                    await page.click('#add-provider')
                    for name,value in [('name','retained'),('endpoint','https://example.com/v1'),('model','retry-model'),('key','synthetic-new-key')]:
                        await page.fill('#provider-'+name,value)
                    await page.click('#provider-save')
                    await page.wait_for_function("!$('provider-save').disabled")
                    provider=await page.evaluate("""() => ({open:$('provider').open,error:$('provider-error')?.textContent||'',errorVisible:!!$('provider-error')&&!$('provider-error').hidden,name:$('provider-name').value,model:$('provider-model').value,keyCleared:$('provider-key').value==='',globalErrorHidden:$('error').hidden})""")
                    # Keep nonsecret inputs and retry using an unused profile name.
                    if provider['open']:
                        await page.fill('#provider-name','retry');await page.fill('#provider-key','synthetic-retry-key')
                        await page.click('#provider-save');await page.wait_for_function("!$('provider').open")
                    retrySaved=(desk.home/'retry.config.toml').exists()
                    # Esc closes native dialogs too: it must clear the key.
                    await page.click('#add-provider');await page.fill('#provider-key','synthetic-cancel-key');await page.press('#provider-key','Escape')
                    await page.wait_for_function("!$('provider').open && $('provider-key').value===''")
                    escapeCleared=await page.evaluate("$('provider-key').value===''")
                    await page.evaluate("""() => {fillProfiles($('handoff-profile'));$('handoff-cwd').value='/missing/project';$('handoff-text').value='Prior task evidence';$('handoff-goal').value='Run verification';$('preview').showModal();}""")
                    await page.click('#handoff-start');await page.wait_for_function("!$('handoff-start').disabled")
                    handoff=await page.evaluate("""() => ({open:$('preview').open,error:$('handoff-error')?.textContent||'',errorVisible:!!$('handoff-error')&&!$('handoff-error').hidden,evidence:$('handoff-text').value,goal:$('handoff-goal').value,globalErrorHidden:$('error').hidden})""")
                    await page.click('#preview-close')
                    await page.click('#browse');await page.wait_for_selector('.native-row button')
                    await page.click('.native-row button');await page.wait_for_function("!document.querySelector('.native-row button').disabled")
                    history=await page.evaluate("""() => ({open:$('history').open,error:$('history-error').textContent,errorVisible:!$('history-error').hidden,globalErrorHidden:$('error').hidden})""")
                    overflow=await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    result={'provider':provider,'providerRetrySaved':retrySaved,'escapeKeyCleared':escapeCleared,'handoff':handoff,'history':history,'mobileOverflow':overflow,'javascriptErrors':errors,'nativeTurns':0}
                    print(json.dumps(result,indent=2),flush=True)
                    assert provider['open'] and provider['errorVisible'] and 'already exists' in provider['error'] and provider['keyCleared'] and provider['globalErrorHidden'],result
                    assert provider['name']=='retained' and provider['model']=='retry-model' and retrySaved and escapeCleared,result
                    assert handoff['open'] and handoff['errorVisible'] and handoff['evidence']=='Prior task evidence' and handoff['goal']=='Run verification' and handoff['globalErrorHidden'],result
                    assert history['open'] and history['errorVisible'] and 'folder no longer exists' in history['error'] and history['globalErrorHidden'],result
                    assert not errors and not overflow and not desk.store.sessions(),result
                finally:await browser.close()
        finally:
            server.shutdown();worker.join(timeout=5);server.server_close();desk.close();desk.store.db.close()

if __name__=='__main__':asyncio.run(check())
