"""Installed conversation-first recall with actual loopback, SQLite and keyboard."""
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

Q='Retry budget Café 项目 😀'

async def check(width,pw,evidence):
    with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'],prefix=f'grouped-{width}-') as tmp:
        root=Path(tmp);home=root/'home';home.mkdir();project=root/'same-project';project.mkdir()
        (home/'config.toml').write_text('model="fixture-model"\n');(home/'auth.json').write_text('{"fixture":"unchanged"}\n')
        settings={p.name:p.read_bytes() for p in home.iterdir()}
        def source(id,n,at):
            return {'id':id,'cwd':str(project),'name':id,'updatedAt':at,'modelProvider':'fixture',
                    'turns':[{'id':'turn-'+id,'status':'completed','completedAt':at,'items':[
                    {'id':f'item-{i:02}','type':'agentMessage','phase':'final_answer','text':Q+f' own response {i}'} for i in range(n)]}]}
        sources={'dominant-A':source('dominant-A',65,1795600300),'distinct-C':source('distinct-C',1,1795600100)}
        sources['distinct-C']['turns'][0]['items'][0]={'id':'C-command','type':'commandExecution','command':'fixture inspect remembered answer',
            'status':'completed','exitCode':0,'aggregatedOutput':'\n'.join('Source output line '+str(n) for n in range(1600))+'\n'+Q+' decisive separate answer'}
        B={'id':'B-thread','cwd':str(project),'turns':[{'id':'B-turn','status':'completed','items':[{'id':'B-item','type':'agentMessage','text':'B retained original'}]}]}
        calls=[];http=[];errors=[];external=[];groups=[]
        class Catalog:
            def request(self,method,params):
                calls.append({'transport':'catalog','method':method,'params':params})
                if method=='thread/read':
                    assert params['includeTurns'] is True;return {'thread':copy.deepcopy(sources[params['threadId']])}
                assert method=='thread/list';return {'data':[],'nextCursor':None}
        class Reader:
            def __init__(self,*args):self.closing=False;self.process=SimpleNamespace(poll=lambda:None)
            def request(self,method,params):
                calls.append({'transport':'original','method':method,'params':params});assert method=='thread/read' and params['includeTurns'] is True
                return {'thread':copy.deepcopy(sources[params['threadId']])}
            def close(self):self.closing=True;self.process.poll=lambda:0
        with patch.object(S,'_NativeReader',Reader),patch.object(S.Desk,'catalog',return_value=Catalog()),patch.object(S,'Runtime',side_effect=AssertionError('Unexpected admission')):
            desk=S.Desk('never-executed',home,root/'state');sid=desk.store.create(str(project),'default',identifier='B',name='B selected task')
            desk.store.update(sid,thread_id=B['id'],status='ready',thread_saved=1,name_pending=0)
            desk.runtimes[sid]=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),thread_result={'thread':B,'model':'fixture-model','modelProvider':'fixture'},approvals={},pending={},close=lambda:None)
            save_draft(desk.store,sid,'B exact unsent Plan — 保持','plan',0);add_followup(desk.store,sid,'B paused Work','native');add_followup(desk.store,sid,'B paused Plan','plan')
            for original in sources.values():desk.native_index.replace_snapshot(original)
            server=S.ThreadingHTTPServer(('127.0.0.1',0),S.handler(desk));worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
            browser=await pw.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844});page=await context.new_page();page.set_default_timeout(15000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            def request(r):
                u=urlsplit(r.url);http.append({'path':u.path,'query':parse_qs(u.query),'method':r.method})
                if u.hostname!='127.0.0.1':external.append(r.url)
            page.on('request',request)
            async def frames():await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            async def ready():await page.wait_for_function("!$('recall-search').disabled && $('recall-results').getAttribute('aria-busy')==='false'");await frames()
            async def search():await page.locator('#recall-query').press('Enter');await ready()
            async def bstate():return await page.evaluate("({selected,draft:$('prompt').value,mode:$('run-mode').value,native:$('native-id').textContent})")
            def reads():return len([c for c in calls if c['method']=='thread/read'])
            async def unchanged():
                assert await bstate()==baseline;assert list(desk.store.db.iterdump())==db;assert load_draft(desk.store,sid)==draft;assert followup_snapshot(desk.store,sid)==queue
                assert {p.name:p.read_bytes() for p in home.iterdir()}==settings
                assert not [r for r in http if r['method']=='POST' and r['path'] not in ('/api/open',)]
            async def mark(name):
                await unchanged();assert not errors and not external
                assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
                groups.append(name);print(json.dumps({'width':width,'passed':name}),flush=True);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
            async def source_back():await page.locator('#recall-source-back').click();await ready()
            async def reader_return():
                await page.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
            try:
                await context.add_init_script("(()=>{const later=setTimeout;window.setTimeout=function(fn,...args){if(fn?.name==='tick')return 0;return later.call(this,fn,...args);};})();")
                await page.goto(f'http://127.0.0.1:{server.server_port}');await page.locator('.session-row[data-session="B"] .session').click()
                await page.wait_for_function("selected==='B'&&!opening&&!$('task').hidden");await frames();baseline=await bstate();db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid)
                await page.locator('#search-saved-content').click();await page.locator('#recall-query').fill(Q);await search()
                assert await page.locator('#recall-results .recall-result').count()==30
                assert set(await page.locator('#recall-results .recall-result').evaluate_all('ns=>ns.map(n=>n.dataset.thread)'))=={'dominant-A'}
                await mark('ordinary-dominance-positive-control')
                await page.locator('#recall-grouped').check();await search()
                assert await page.locator('#recall-results .recall-result').count()==2
                assert '66 matching items' in await page.locator('#recall-summary').inner_text()
                assert '65 matching items' in await page.locator('[data-group="dominant-A"] .recall-kind').inner_text()
                assert '1 matching item' in await page.locator('[data-group="distinct-C"] .recall-kind').inner_text()
                await mark('distinct-original-visible-own-counts')
                await page.locator('.recall-group').first.focus();await page.keyboard.press('Tab');assert await page.evaluate("document.activeElement.closest('article').dataset.group==='distinct-C'")
                await page.keyboard.press('Enter');await ready();assert await page.locator('#recall-results .recall-result').count()==1
                assert await page.locator('#recall-source-label').inner_text()=='Matching items in distinct-C · Native original · distinct-C'
                n=reads();await page.locator('#recall-results .recall-read').click();await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames()
                assert reads()==n+1;assert calls[-1]['params']=={'threadId':'distinct-C','includeTurns':True}
                assert Q in await page.locator('.history-reader-item[data-item-id="C-command"] mark').inner_text()
                await reader_return();assert await page.evaluate("document.activeElement.classList.contains('recall-read')")
                assert await page.locator('#recall-query').input_value()==Q
                await source_back();assert await page.evaluate("document.activeElement.closest('article').dataset.group==='distinct-C'")
                await mark('keyboard-distinct-fresh-source-and-group-return')
                await page.locator('[data-group="dominant-A"] .recall-group').click();await ready();await page.locator('#recall-next').click();await ready()
                assert 'Items 31–60' in await page.locator('#recall-summary').inner_text();assert set(await page.locator('.recall-result').evaluate_all('ns=>ns.map(n=>n.dataset.thread)'))=={'dominant-A'}
                selected_item=await page.locator('.recall-result').first.get_attribute('data-item');n=reads();await page.locator('.recall-read').first.click();await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                assert reads()==n+1;assert await page.locator('.history-reader-item.history-reader-target').get_attribute('data-item-id')==selected_item
                await reader_return();assert 'Items 31–60' in await page.locator('#recall-summary').inner_text();await source_back();await mark('source-own-page-and-fresh-item-return')
                held=asyncio.Event();release=asyncio.Event()
                async def hold(route):
                    if parse_qs(urlsplit(route.request.url).query).get('source_thread')==['dominant-A']:held.set();await release.wait()
                    await route.continue_()
                await page.route('**/api/recall?*',hold);await page.locator('[data-group="dominant-A"] .recall-group').click();await held.wait();await source_back();release.set();await frames();await page.unroute('**/api/recall?*',hold)
                await ready();assert await page.locator('[data-group="distinct-C"]').count()==1;assert await page.locator('#recall-source').is_hidden();await mark('held-source-cannot-replace-returned-groups')
                changed=copy.deepcopy(sources['dominant-A']);changed['turns'][0]['items'][0]['text']='Changed actual original own item'
                sources['dominant-A']=changed;desk.native_index.replace_snapshot(changed);db=list(desk.store.db.iterdump());await search()
                assert '64 matching items' in await page.locator('[data-group="dominant-A"] .recall-kind').inner_text();assert '65 matching items' in await page.locator('#recall-summary').inner_text();await mark('fresh-replacement-group-counts-exact')
                n=reads();await page.reload();await page.wait_for_function("selected==='B'&&!opening&&!$('task').hidden");await frames()
                assert reads()==n;await unchanged();assert not await page.locator('#history-reader').evaluate('n=>n.open');await mark('reload-no-source-read-B-Plan-queues-exact')
                result={'width':width,'browser':browser.version,'groups':groups,'original_reads':reads(),'native_admissions':0,'B_SQL_draft_queues_exact':True,'errors':errors,'external':external,'http':http,'calls':calls}
                (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
            finally:
                await context.close();await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (1250,390)]
    (evidence/'acceptance.json').write_text(json.dumps({'status':'PASS','groups':sum(len(r['groups']) for r in results),'results':results},ensure_ascii=False,indent=2)+'\n')

if __name__=='__main__':asyncio.run(main())
