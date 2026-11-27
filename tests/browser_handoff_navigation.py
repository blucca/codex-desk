"""Held real HTTP handoff replies preserve later review and selected preparation."""
import asyncio,json,os
from pathlib import Path
import sys,tempfile,threading
if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk,ThreadingHTTPServer,handler
from codex_desk.drafts import load_draft
from codex_desk.followups import add_followup,list_followups
from handoff_native_fixture import HandoffNative
from playwright.async_api import async_playwright

async def check():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    result={'cases':[],'javascriptErrors':[],'nativeProcesses':0}
    with tempfile.TemporaryDirectory(dir=root,prefix='handoff-navigation-') as tmp:
        tmp=Path(tmp);project=tmp/'project';project.mkdir()
        desk=Desk('not-executed',tmp/'home',tmp/'state')
        histories={}
        for key in ('a','b','selected'):
            identifier='source-'+key;native='native-'+key
            desk.store.create(str(project),'default',identifier=identifier,name='Source '+key.upper())
            desk.store.update(identifier,thread_id=native,status='completed',thread_saved=1)
            histories[native]={'id':native,'name':'Source '+key.upper(),'cwd':str(project),'turns':[
                {'id':'turn-'+key,'items':[{'id':'answer-'+key,'type':'agentMessage','text':'Original evidence '+key}]}]}
        native=HandoffNative(desk,histories)
        admitted=native.starts;entered,release=native.entered,native.release;fail=False
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(desk));worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
        url=f'http://127.0.0.1:{server.server_port}'
        try:
            async with async_playwright() as p:
                browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
                try:
                    for width in (390,1250):
                        page=await browser.new_page(viewport={'width':width,'height':844})
                        page.on('pageerror',lambda e:result['javascriptErrors'].append(str(e)))
                        await page.goto(url);await page.wait_for_function('state.sessions.length>=3')
                        await page.locator('.session-row[data-session="source-selected"] .session').click()
                        await page.wait_for_function('selected==="source-selected" && !opening')
                        plan='Exact unsent Plan — retained '+str(width)
                        await page.locator('#prompt').fill(plan);await page.locator('#turn-mode').select_option('plan')
                        await page.wait_for_function('v=>draftSaved.get("source-selected")?.text===v',arg=plan)
                        draft=load_draft(desk.store,'source-selected')
                        if not list_followups(desk.store,'source-selected'):
                            add_followup(desk.store,'source-selected','Paused Work','native');add_followup(desk.store,'source-selected','Paused Plan','plan')
                        queue=list_followups(desk.store,'source-selected')
                        for case in ('cancel-reopen-other-success','later-edit-success','cancel-reopen-other-failure'):
                            entered.clear();release.clear();fail=case.endswith('failure');before=len(admitted)
                            await page.evaluate('showHandoff("native-a",state.sessions.find(s=>s.id==="source-a").cwd)')
                            if await page.locator('#handoff-new').is_visible():
                                await page.locator('#handoff-new').click()
                            native.mode='rejected' if fail else 'accepted'
                            await page.locator('#handoff-goal').fill('Submitted A '+case)
                            await page.locator('#handoff-start').click()
                            assert await asyncio.to_thread(entered.wait,10)
                            if case.startswith('cancel'):
                                await page.locator('#preview-close').click()
                                await page.evaluate('showHandoff("native-b",state.sessions.find(s=>s.id==="source-b").cwd)')
                            newer='Newer unsent '+case
                            await page.locator('#handoff-goal').fill(newer)
                            await page.locator('#handoff-text').fill('Exact reviewed later evidence '+case)
                            release.set()
                            await page.wait_for_function('!handoffStarts.has("native-a")')
                            assert await page.locator('#preview').evaluate('n=>n.open')
                            assert await page.locator('#handoff-goal').input_value()==newer
                            assert await page.locator('#handoff-text').input_value()=='Exact reviewed later evidence '+case
                            assert await page.locator('#handoff-error').is_hidden()
                            assert await page.evaluate('selected')=='source-selected'
                            assert await page.locator('#prompt').input_value()==plan
                            assert await page.locator('#turn-mode').input_value()=='plan'
                            assert load_draft(desk.store,'source-selected')==draft
                            assert list_followups(desk.store,'source-selected')==queue
                            assert len(admitted)==before+1
                            assert admitted[-1]['text'].startswith('Next task: Submitted A '+case+'\n\n')
                            if not fail:
                                created=admitted[-1]['session']
                                assert await page.locator(f'.session-row[data-session="{created}"]').count()==1
                            if case=='later-edit-success':
                                assert await page.locator('#handoff-status').is_visible()
                                assert 'later edits have not been sent' in await page.locator('#handoff-status').inner_text()
                            assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
                            await page.screenshot(path=str(evidence/f'{width}-{case}.png'))
                            result['cases'].append({'width':width,'case':case,'exactLaterEditor':True,'selectedPlanAndTwoQueues':True,'retainedTarget':admitted[-1]['session'],'accepted':not fail,'admissions':1})
                            await page.locator('#preview-close').click()
                        await page.close()
                    assert not result['javascriptErrors']
                finally:await browser.close()
        finally:
            release.set();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()
            (evidence/'result.json').write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps(result),flush=True)
if __name__=='__main__':asyncio.run(check())
