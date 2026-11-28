"""Installed native catalog archive source, pagination and exact original return."""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as S
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

async def check(width, pw, evidence):
    with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'], prefix=f'original-id-{width}-') as tmp:
        root=Path(tmp);home=root/'home';home.mkdir();project=root/'B';project.mkdir()
        (home/'config.toml').write_text('model="fixture-model"\n');(home/'auth.json').write_text('{"fixture":"unchanged"}\n')
        settings={p.name:p.read_bytes() for p in home.iterdir()}
        exact='archived-A/接口?+'
        old_title='Older retry architecture decision'
        full='Command\nfixture inspect source\nStatus: completed\nExit: 0\n'+''.join(f'Original {n:04d} Café 项目 😀\n' for n in range(1600))+'DECISIVE ID SOURCE Café 项目 😀\n'
        original={'id':exact,'cwd':str(root/'removed-A'),'name':old_title,
            'modelProvider':'fixture-provider','turns':[{'id':'A-turn','status':'completed','items':[
            {'id':'A-prompt','type':'userMessage','content':[{'type':'text','text':'Inspect the previous retry check.'}]},
            {'id':'A-command','type':'commandExecution','command':'fixture inspect source','status':'completed','exitCode':0,'aggregatedOutput':full.split('Exit: 0\n',1)[1]},
            {'id':'A-answer','type':'agentMessage','phase':'final_answer','text':'Keep the existing retry budget.'}]}]}
        B={'id':'B-thread','cwd':str(project),'name':'B selected task','modelProvider':'fixture-provider',
            'turns':[{'id':'B-turn','status':'completed','items':[{'id':'B-reply','type':'agentMessage','text':'B exact earlier output'}]}]}
        calls=[];http=[];errors=[];external=[];fails=set();holds={};groups=[]
        catalog=[{'id':f'catalog-{n}','name':f'Keep + Café title {n:02d}','cwd':str(project),'modelProvider':'fixture-provider','updatedAt':1795625000-n} for n in range(32)]
        archived_catalog=[{k:v for k,v in original.items() if k!='turns'}]+[{**t,'id':'archived-'+t['id']} for t in catalog]
        class Catalog:
            def request(self,method,params):
                calls.append({'transport':'catalog','method':method,'params':dict(params)})
                if method=='thread/read':
                    if params['threadId']==exact:return {'thread':copy.deepcopy(original)}
                    row=next(t for t in catalog+archived_catalog if t['id']==params['threadId'])
                    return {'thread':{**row,'turns':[{'id':'title-turn','status':'completed','items':[{'id':'title-answer','type':'agentMessage','text':'Newer selected title original'}]}]}}
                assert method=='thread/list',method
                start=int(params.get('cursor') or 0);size=params.get('limit',30)
                candidates=archived_catalog if params.get('archived') is True else catalog
                rows=[t for t in candidates if params.get('searchTerm','').casefold() in t['name'].casefold()]
                return {'data':copy.deepcopy(rows[start:start+size]),'nextCursor':str(start+size) if start+size<len(rows) else None}
        class Reader:
            def __init__(self,*args):self.closing=False;self.process=SimpleNamespace(poll=lambda:None)
            def request(self,method,params):
                calls.append({'transport':'original','method':method,'params':dict(params)})
                assert method=='thread/read' and params=={'threadId':exact,'includeTurns':True}
                if exact in holds:
                    entered,release=holds[exact];entered.set();assert release.wait(30)
                if exact in fails:raise RuntimeError('Controlled original unavailable')
                return {'thread':copy.deepcopy(original)}
            def close(self):self.closing=True;self.process.poll=lambda:0
        with patch.object(S,'_NativeReader',Reader),patch.object(S.Desk,'catalog',return_value=Catalog()):
            desk=S.Desk('never-executed',home,root/'state')
            sid=desk.store.create(str(project),'default',identifier='B',name='B selected task')
            desk.store.update(sid,thread_id=B['id'],status='ready',thread_saved=1,name_pending=0)
            connected=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),thread_result={'thread':B,'model':'fixture-model','modelProvider':'fixture-provider'},approvals={},pending={},close=lambda:None)
            desk.runtimes[sid]=connected
            save_draft(desk.store,sid,'B exact unsent Plan — 保持','plan',0)
            add_followup(desk.store,sid,'B saved Work','native');add_followup(desk.store,sid,'B saved Plan','plan')
            server=S.ThreadingHTTPServer(('127.0.0.1',0),S.handler(desk));worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
            browser=await pw.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            page=await browser.new_page(viewport={'width':width,'height':900 if width>390 else 844});page.set_default_timeout(15000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            def requested(r):
                u=urlsplit(r.url);http.append({'path':u.path,'query':parse_qs(u.query),'method':r.method})
                if u.hostname!='127.0.0.1':external.append(r.url)
            page.on('request',requested)
            async def ready():await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
            async def read():
                await page.locator('#history-id').fill('  '+exact+'  ');await page.locator('#history-id').press('Enter');await ready()
            async def back():
                await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open && $('history').open")
            async def unchanged():
                assert list(desk.store.db.iterdump())==db
                assert load_draft(desk.store,sid)==draft and followup_snapshot(desk.store,sid)==queue
                assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")==selection
                assert not external and not errors,(external,errors)
                assert not any(r['method']=='POST' and r['path']!='/api/open' for r in http),http
                assert sum(r['path']=='/api/open' for r in http)==opens
            def checkpoint(name):groups.append(name);print(json.dumps({'viewport':width,'passed':name}),flush=True)
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function("$('home-list').children.length>0")
                await page.locator('.session-row[data-session="B"] .session').click()
                await page.wait_for_function("selected==='B' && !opening && !$('task').hidden")
                selection=await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
                db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid);opens=sum(r['path']=='/api/open' for r in http)
                await page.locator('#show-archived').check()
                await page.locator('#browse').click();await page.wait_for_function("!$('history-search-submit').disabled")
                await page.locator('#history-search').fill(old_title);await page.locator('#history-search').press('Enter');await page.wait_for_function("!$('history-search-submit').disabled")
                assert await page.locator('#native-list .native-row').count()==0
                assert await page.locator('#show-archived').is_checked()
                assert await page.locator('#history-search').input_value()==old_title
                absent=await page.locator('#history-summary').inner_text()
                assert old_title in absent and 'No saved' in absent
                assert await page.locator('#history-source').input_value()=='current'
                assert all(c['params'].get('archived') is not True for c in calls if c['method']=='thread/list')
                checkpoint('current catalog excludes archived title; local Show archived stays separate')
                await page.locator('#history-source').select_option('archived')
                await page.wait_for_function("!$('history-search-submit').disabled && $('native-list').children.length===1")
                row=page.locator('#native-list .native-row');assert await row.get_attribute('data-thread')==exact
                assert await row.locator('button').count()==1 and 'Archived in native Codex history' in await row.inner_text()
                assert not await row.get_by_role('button',name='Resume with current settings',exact=True).count()
                archive_titles=await page.locator('#native-list').text_content()
                assert all(c['params']['archived'] is True for c in calls[-1:] if c['method']=='thread/list')
                await row.get_by_role('button',name='Read original conversation',exact=True).click();await ready()
                assert await page.locator('#history-reader-back').inner_text()=='Back to archived conversations'
                assert exact in await page.locator('#history-reader-binding').inner_text()
                await page.locator('#history-reader-find-query').fill('DECISIVE ID SOURCE')
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-command'
                await page.screenshot(path=str(evidence/f'archived-original-{width}.png'))
                await back();assert await page.locator('#history-source').input_value()=='archived'
                assert await page.locator('#history-search').input_value()==old_title
                assert await page.locator('#native-list').text_content()==archive_titles
                assert await page.evaluate("document.activeElement.classList.contains('native-read')")
                await unchanged();checkpoint('archived title exact fresh read and Unicode passage return preserves archived query/row/focus and B')
                before=len(calls);await page.locator('#history-id').fill('Thread: '+exact);await page.locator('#history-id').press('Enter')
                await page.wait_for_function("$('history-id-status').textContent.includes('Paste only')");assert len(calls)==before
                checkpoint('whole reference prose remains locally rejected; no archive or native read mutation')
                await page.locator('#history-search').fill('Keep + Café');await page.locator('#history-search').press('Enter');await page.wait_for_function("!$('history-search-submit').disabled")
                await page.locator('#more').click();await page.wait_for_function("!$('history-search-submit').disabled")
                titles=await page.locator('#native-list').text_content();assert await page.locator('#native-list .native-row').count()==32
                before=sum(c['transport']=='original' for c in calls);await read()
                assert sum(c['transport']=='original' for c in calls)==before+1
                assert exact in await page.locator('#history-reader-binding').inner_text()
                assert str(root/'removed-A') in await page.locator('#history-reader-binding').inner_text()
                assert not (root/'removed-A').exists();assert await page.locator('#history-reader-back').inner_text()=='Back to conversation ID'
                await unchanged();checkpoint('direct ID reads absent-catalog removed-folder original; B Plan/twoqueues/SQLite exact')
                await page.locator('#history-reader-find-query').fill('DECISIVE ID SOURCE');await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
                target=page.locator('.history-reader-target');assert await target.get_attribute('data-item-id')=='A-command'
                await page.evaluate("navigator.clipboard.writeText=async value=>{globalThis.__copied=value;}")
                await target.get_by_role('button',name='Copy full item text',exact=True).click();assert await page.evaluate('globalThis.__copied')==full
                await target.get_by_role('button',name='Copy source reference',exact=True).click();assert 'Thread: '+exact in await page.evaluate('globalThis.__copied')
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth")
                await page.screenshot(path=str(evidence/f'direct-id-{width}.png'))
                await back();assert await page.locator('#history-search').input_value()=='Keep + Café';assert await page.locator('#native-list').text_content()==titles
                assert await page.locator('#history-id').input_value()=='  '+exact+'  '
                assert await page.evaluate("document.activeElement===$('history-id')")
                await unchanged();checkpoint('existing original Unicode Find/full Copy/source then exact ID/title rows return')
                assert {p.name:p.read_bytes() for p in home.iterdir()}==settings
                assert all(c['method'] in ('thread/list','thread/read') for c in calls)
                archive_lists=[c for c in calls if c['method']=='thread/list' and c['params'].get('archived') is True]
                assert len(archive_lists)>=3
                assert archive_lists[-1]['params'].get('cursor')=='30'
                assert archive_lists[-1]['params']['searchTerm']=='Keep + Café'
                assert await page.locator('#history-source').input_value()=='archived'
                assert await page.locator('#show-archived').is_checked()
                await page.locator('#history-source').select_option('current')
                await page.wait_for_function("!$('history-search-submit').disabled")
                assert await page.locator('#native-list .native-row').count()==30
                assert all([await page.locator('#native-list .native-row').nth(i).get_attribute('data-native-source')=='current' for i in range(30)])
                assert await page.locator('#more').is_visible()
                assert calls[-1]['params']['archived'] is False and 'cursor' not in calls[-1]['params']
                await unchanged();checkpoint('switch to current resets archived cursor and keeps independent local archive toggle/B')

                assert not desk.store.get(exact)
                (evidence/f'actual-receipt-{width}.json').write_text(json.dumps({'calls':calls,'http':http,'errors':errors,
                  'selected':selection,'draft':draft,'queue':queue,'database_unchanged':True,
                  'native_admissions':0,'archived_source_task_rows':0,'config_auth_unchanged':True},indent=2)+'\n')
                return {'viewport':width,'groups':groups,'native_original_reads':sum(c['transport']=='original' for c in calls),
                  'copy_chars':len(full),'sqlite_unchanged':True,'source_id':exact,'source_archived':True,
                  'local_and_native_archive_scopes_independent':True,'native_archive_filter_passed':True,
                  'direct_known_id_reads_archived_original':True,'native_admissions':0}
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (1250,390)]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'PASS','implementation_changes':3,'engine':'Chromium141/build1194','playwright':'1.56.0','fixture':'native archive filter/read contracts from retained Codex0.171 source','viewports':results},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
