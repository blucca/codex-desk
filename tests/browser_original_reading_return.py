"""Explicit original close/reopen and reload; installed browser, fresh loopback reads."""
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

QUOTE='RETURN PASSAGE Café 项目 😀'
BEFORE=os.environ.get('DESK_READER_RETURN_BEFORE')=='1'
async def check(width,pw,evidence):
    with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'],prefix=f'original-return-{width}-') as tmp:
        root=Path(tmp);home=root/'home';home.mkdir();project=root/'B';project.mkdir()
        (home/'config.toml').write_text('model="fixture-model"\n');(home/'auth.json').write_text('{"fixture":"unchanged"}\n')
        settings={p.name:p.read_bytes() for p in home.iterdir()}
        exact='known-A/接口?+'
        output='\n'.join(f'Original {n:04d} Café 项目 😀'+(' '+QUOTE if n==1450 else '') for n in range(1900))
        items=[{'id':f'A-neighbor-{n}','type':'agentMessage','text':f'Original neighbor {n}'} for n in range(85)]
        items[45]={'id':'A-command','type':'commandExecution','command':'fixture inspect source','status':'completed','exitCode':0,'aggregatedOutput':output}
        original={'id':exact,'cwd':str(root/'removed-A'),'name':'A retained original','modelProvider':'fixture-provider',
                  'turns':[{'id':'A-turn','status':'completed','items':items}]}
        B={'id':'B-thread','cwd':str(project),'name':'B selected task','modelProvider':'fixture-provider',
            'turns':[{'id':'B-turn','status':'completed','items':[{'id':'B-reply','type':'agentMessage','text':'B earlier output'}]}]}
        calls=[];http=[];errors=[];external=[];holds={};observations=[]
        class Catalog:
            def request(self,method,params):
                calls.append({'transport':'catalog','method':method,'params':dict(params)})
                if method=='thread/read':assert params=={'threadId':exact,'includeTurns':True};return {'thread':copy.deepcopy(original)}
                assert method=='thread/list',method
                return {'data':[{k:v for k,v in original.items() if k!='turns'}],'nextCursor':None}
        class Reader:
            def __init__(self,*args):self.closing=False;self.process=SimpleNamespace(poll=lambda:None)
            def request(self,method,params):
                calls.append({'transport':'original','method':method,'params':dict(params)})
                assert method=='thread/read' and params=={'threadId':exact,'includeTurns':True}
                if holds:
                    entered,release=holds['read'];entered.set();assert release.wait(30)
                return {'thread':copy.deepcopy(original)}
            def close(self):self.closing=True;self.process.poll=lambda:0
        with patch.object(S,'_NativeReader',Reader),patch.object(S.Desk,'catalog',return_value=Catalog()),patch.object(S,'Runtime',side_effect=AssertionError('Unexpected task admission')):
            desk=S.Desk('never-executed',home,root/'state')
            sid=desk.store.create(str(project),'default',identifier='B',name='B selected task')
            desk.store.update(sid,thread_id=B['id'],status='ready',thread_saved=1,name_pending=0)
            connected=SimpleNamespace(process=SimpleNamespace(poll=lambda:None),thread_result={'thread':B,'model':'fixture-model','modelProvider':'fixture-provider'},approvals={},pending={},close=lambda:None)
            desk.runtimes[sid]=connected
            save_draft(desk.store,sid,'B exact unsent Plan — 保持','plan',0)
            add_followup(desk.store,sid,'B paused Work','native');add_followup(desk.store,sid,'B paused Plan','plan')
            server=S.ThreadingHTTPServer(('127.0.0.1',0),S.handler(desk));worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
            browser=await pw.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844})
            page=await context.new_page();page.set_default_timeout(15000)
            page.on('pageerror',lambda e:errors.append(str(e)))
            def requested(r):
                u=urlsplit(r.url);http.append({'path':u.path,'query':parse_qs(u.query),'method':r.method})
                if u.hostname!='127.0.0.1':external.append(r.url)
            page.on('request',requested)
            async def frames():await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            async def ready():
                await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'");await frames()
            async def browse():
                await page.locator('#browse').click();await page.wait_for_function("!$('history-search-submit').disabled")
                await page.locator('#history-search').fill('A retained');await page.locator('#history-search').press('Enter');await page.wait_for_function("!$('history-search-submit').disabled")
            async def read():
                await page.locator('#history-id').fill(exact);await page.locator('#history-id').press('Enter');await ready()
            async def back():
                await page.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter')
                await page.wait_for_function("!$('history-reader').open && $('history').open")
            def target():return page.locator('.history-reader-item[data-turn-id="A-turn"][data-item-id="A-command"]')
            async def view():
                return await page.evaluate("""()=>{const n=document.querySelector('.history-reader-item[data-item-id="A-command"]'),p=n?.querySelector('pre');
                  return {thread:$('history-reader-binding').textContent,turn:n?.dataset.turnId,item:n?.dataset.itemId,start:n?.dataset.windowStart,open:n?.open,
                    inner:p?.scrollTop,left:p?.scrollLeft,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,
                    top:n?.getBoundingClientRect().top,page:$('history-reader-coverage').textContent,query:$('history-reader-find-query').value,
                    selection:getSelection().toString(),disclosures:[...$('history-reader-body').querySelectorAll('.history-reader-item')].map(n=>[n.dataset.itemId,n.open,n.dataset.windowStart])};}""")
            async def passage():
                await page.locator('#history-reader-find-query').fill(QUOTE);await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames()
                assert int(await target().get_attribute('data-window-start'))>20000
                rects=await target().locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
                first,last=rects[0],rects[-1]
                await page.mouse.move(last['right']-.5,(last['top']+last['bottom'])/2);await page.mouse.down()
                await page.mouse.move(first['left']+.5,(first['top']+first['bottom'])/2,steps=12);await page.mouse.up()
                assert await page.evaluate('getSelection().toString()')==QUOTE
                box=await target().locator('pre').bounding_box();await page.mouse.move(box['x']+box['width']/2,min(box['y']+box['height']/2,750));await page.mouse.wheel(0,35)
                await page.wait_for_timeout(100);await frames()
                result=await view();assert result['selection']==QUOTE and result['open'] and result['inner']>0
                return result
            async def state():return await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
            async def unchanged():
                assert list(desk.store.db.iterdump())==db
                assert load_draft(desk.store,sid)==draft and followup_snapshot(desk.store,sid)==queue
                assert await state()==selection
                assert not errors and not external,(errors,external)
                assert not any(r['method']=='POST' and r['path']!='/api/open' for r in http)
                assert sum(r['path']=='/api/open' for r in http)==opens
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            def same(a,b):
                for key in ('turn','item','start','open','disclosures'):assert a.get(key)==b.get(key),(key,a,b)
                for key in ('inner','left','body','top'):assert abs(a[key]-b[key])<2,(key,a,b)
                assert a['page']==b['page']
            def reads():return sum(c['method']=='thread/read' for c in calls)
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function("$('home-list').children.length>0")
                await page.locator('.session-row[data-session="B"] .session').click();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden")
                await frames();selection=await state();db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid);opens=sum(r['path']=='/api/open' for r in http)
                await browse();titles=await page.locator('#native-list').text_content();await read();first=await passage()
                await page.screenshot(path=str(evidence/f'{width}-close-before.png'));await back()
                assert await page.locator('#history-search').input_value()=='A retained' and await page.locator('#native-list').text_content()==titles
                n=reads();await read();assert reads()==n+1
                reopened=await view();observations.append({'case':'close-ID-reopen','before':first,'after':reopened,'fresh_reads':1,'outer_compensation':reopened['outer']-first['outer'],'geometry_policy':'fresh Find chrome; same visible native passage'})
                if BEFORE:assert reopened['start']!=''+first['start'] or not reopened['open']
                else:same(first,reopened);assert reopened['query']==''
                await unchanged();await page.screenshot(path=str(evidence/f'{width}-close-reopened.png'))
                if BEFORE:await passage()
                await back();n=reads();await page.locator('#native-list .native-read').click();await ready();assert reads()==n+1
                title_view=await view();observations.append({'case':'title-reopen','after':title_view,'fresh_reads':1})
                if not BEFORE:same(first,title_view)
                second=await passage();n=reads();await page.reload();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden");await frames()
                assert not await page.locator('#history-reader').evaluate('n=>n.open');assert reads()==n,'Reload auto-read an original'
                selection=await state();opens=sum(r['path']=='/api/open' for r in http);await unchanged()
                await browse();n=reads();await read();assert reads()==n+1
                reloaded=await view();observations.append({'case':'reload-explicit-reopen','before':second,'after':reloaded,'fresh_reads':1,'reload_original_reads':0,'outer_compensation':reloaded['outer']-second['outer']})
                if BEFORE:assert reloaded['start']!=second['start'] or not reloaded['open']
                else:same(second,reloaded)
                await unchanged();await page.screenshot(path=str(evidence/f'{width}-reload-reopened.png'))
                storage=await page.evaluate('Object.fromEntries(Object.entries(localStorage))')
                if not BEFORE:
                    entries=json.loads(storage['codex-desk-original-reading-checkpoints-v1'])['checkpoints'];assert len(entries)==1
                    assert set(entries[0]['owner'])=={'native_home','thread_id'} and entries[0]['owner']['thread_id']==exact
                    assert QUOTE not in json.dumps(entries) and 'Original 1450' not in json.dumps(entries)
                    activity=json.loads(storage['codex-desk-reading-checkpoints-v1'])['checkpoints'];assert all(e['owner']['session']=='B' and e['owner']['thread_id']=='B-thread' for e in activity)
                    await back()
                    exact_target={'thread_id':exact,'turn_id':'A-turn','item_id':'A-neighbor-2','match_text':'Original neighbor 2'}
                    await page.evaluate('t=>DeskHistoryReader.show(t,{valid:()=>selected==="B"})',exact_target);await ready()
                    assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-neighbor-2';assert 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text()
                    await back();await read();same(second,await view());await unchanged()
                    await back()
                    remembered=await page.evaluate("localStorage.getItem('codex-desk-original-reading-checkpoints-v1')")
                    original['turns'][0]['items'][45]['id']='replacement-command'
                    await read();assert 'Previous original reading place unavailable' in await page.locator('#history-reader-status').inner_text()
                    assert 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text();await back()
                    assert await page.evaluate("localStorage.getItem('codex-desk-original-reading-checkpoints-v1')")==remembered
                    original['turns'][0]['items'][45]['id']='A-command';await read();same(second,await view());await back()
                    original_home=desk.home;desk.home=root/'different-home';n=reads();await read();assert reads()==n+1
                    assert 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text()
                    assert not await target().count();await back();desk.home=original_home
                    await read();same(second,await view());await back();await unchanged()
                    observations.append({'case':'missing-item-and-different-home','exact_saved_metadata_retained':True,'no_substitution':True})
                    entered,release=threading.Event(),threading.Event();holds['read']=(entered,release)
                    await page.locator('#history-id').press('Enter');assert await asyncio.to_thread(entered.wait,10)
                    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
                    release.set();await page.wait_for_function("!$('history-id-read').disabled");holds.clear()
                    assert not await page.locator('#history-reader').evaluate('n=>n.open');await unchanged()
                assert {p.name:p.read_bytes() for p in home.iterdir()}==settings
                assert all(c['method'] in ('thread/list','thread/read') for c in calls)
                result={'viewport':width,'browser_version':browser.version,'result':'OBSERVED_OMISSION' if BEFORE else 'PASS','observations':observations,'storage':storage,'http':http,'native':calls,'sqlite_unchanged':True,'B_draft':draft,'B_queue':queue,'errors':errors}
                (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (1250,390)]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'OBSERVED_OMISSION' if BEFORE else 'PASS','viewports':[{'width':r['viewport'],'browser':r['browser_version'],'sqlite_unchanged':True} for r in results]},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
