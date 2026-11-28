"""Original new-material frontier omission after metadata-only return; selected installed frontier browser."""
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
        items=[{'id':f'A-neighbor-{n}','type':'agentMessage','text':f'Original neighbor {n}'} for n in range(185)]
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
                await browse();n=reads();await read();assert reads()==n+1
                old=await passage();initial_coverage=await page.locator('#history-reader-coverage').inner_text()
                assert 'of 185.' in initial_coverage
                await back();stored_before=await page.evaluate("localStorage.getItem('codex-desk-original-reading-checkpoints-v1')")
                original['turns'].append({'id':'A-first-new-turn','status':'completed','items':[
                  {'id':'A-first-new-user','type':'userMessage','content':[{'type':'text','text':'Inspect the newly retained transport evidence.'}]},
                  {'id':'A-first-new-command','type':'commandExecution','command':'fixture inspect new transport','status':'completed','exitCode':0,'aggregatedOutput':'NEW FIRST MATERIAL Café 项目 😀 — transport observation before the later summary.'},
                  {'id':'A-first-new-answer','type':'agentMessage','phase':'final_answer','text':'First new turn conclusion: retain the native cancellation test.'}]})
                later=[{'id':'A-later-user','type':'userMessage','content':[{'type':'text','text':'Complete the separate later documentation review.'}]}]
                later.extend({'id':f'A-later-note-{i}','type':'agentMessage','phase':'commentary','text':f'Separate later review note {i}'} for i in range(79))
                later.append({'id':'A-later-final','type':'agentMessage','phase':'final_answer','text':'Later review complete; documentation was retained.'})
                original['turns'].append({'id':'A-later-new-turn','status':'completed','items':later})
                first_frontier={'turn_id':'A-first-new-turn','item_id':'A-first-new-user','row_index':185}
                n=reads();await read();assert reads()==n+1
                reopened=await view();assert reopened['item']==old['item'] and reopened['start']==old['start'] and reopened['open']==old['open']
                fresh_coverage=await page.locator('#history-reader-coverage').inner_text()
                assert 'of 269.' in fresh_coverage and 'Page 2 of 7.' in fresh_coverage
                assert not await page.locator('.history-reader-item[data-item-id="A-first-new-user"]').count()
                assert not await page.locator('.history-reader-item[data-item-id="A-first-new-command"]').count()
                visible_actions=await page.locator('#history-reader button:visible').all_text_contents()
                assert await page.locator('#history-reader-first-new').is_visible()
                assert '84 newly supplied native items' in await page.locator('#history-reader-new-status').inner_text()
                before_action=await passage();n=reads()
                await page.locator('#history-reader-first-new').evaluate('e=>e.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                assert reads()==n
                assert await page.locator('.history-reader-target').get_attribute('data-turn-id')=='A-first-new-turn'
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-first-new-user'
                assert 'Page 5 of 7.' in await page.locator('#history-reader-coverage').inner_text()
                await page.locator('#history-reader-task-passage').click();await frames()
                returned=await view();same(before_action,returned)
                assert returned['query']==before_action['query'] and returned['selection']==before_action['selection']
                observations.append({'case':'close-add-native-items-explicit-reread-first-new-return','initial_count':185,'fresh_count':269,
                  'known_first_new':first_frontier,'before':old,'after':reopened,'coverage':fresh_coverage,
                  'direct_first_new_item':'A-first-new-user','direct_first_new_page':5,'first_new_action_native_reads':0,
                  'original_passage_Find_Range_return_exact':True,'fresh_native_reads':1})
                await unchanged();await page.screenshot(path=str(evidence/f'{width}-new-items-reopen-old-passage.png'))
                original['turns'].append({'id':'A-refresh-new-turn','status':'completed','items':[
                  {'id':'A-refresh-new-user','type':'userMessage','content':[{'type':'text','text':'Check the newly retained last source observation.'}]},
                  {'id':'A-refresh-new-command','type':'commandExecution','command':'fixture inspect refresh delta','status':'completed','exitCode':0,'aggregatedOutput':'REFRESH NEW MATERIAL Café 项目 😀 — exact refreshed source observation.'},
                  {'id':'A-refresh-new-final','type':'agentMessage','phase':'final_answer','text':'Latest task response: source review completed.'}]})
                n=reads();await page.locator('#history-reader-refresh').click()
                await page.wait_for_function("!$('history-reader-refresh').disabled && $('history-reader-status').textContent.startsWith('Original refreshed.')");await frames()
                assert reads()==n+1;refreshed=await view()
                assert refreshed['item']==old['item'] and refreshed['start']==old['start'] and refreshed['open']==old['open']
                assert 'of 272.' in refreshed['page'] and 'Page 2 of 7.' in refreshed['page']
                refresh_status=await page.locator('#history-reader-status').inner_text()
                assert not await page.locator('.history-reader-item[data-item-id="A-refresh-new-user"]').count()
                assert '87 newly supplied native items' in await page.locator('#history-reader-new-status').inner_text()
                assert await page.locator('#history-reader-first-new').is_visible()
                refresh_passage=await view();n=reads();await page.locator('#history-reader-first-new').evaluate('e=>e.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-first-new-user'
                await page.locator('#history-reader-task-passage').click();await frames();same(refresh_passage,await view());assert reads()==n
                observations.append({'case':'open-add-native-items-Refresh-keeps-previous-visit-boundary','previous_count':269,'fresh_count':272,
                  'known_first_new':first_frontier,'latest_refresh_added_first_item':{'turn_id':'A-refresh-new-turn','item_id':'A-refresh-new-user','row_index':269},
                  'view':refreshed,'status':refresh_status,'fresh_native_reads':1,'first_new_present_in_dom':False})
                await unchanged();await page.screenshot(path=str(evidence/f'{width}-refresh-new-items-old-passage.png'))
                full_reads=reads();next_steps=0
                while not await page.locator('#history-reader-next').is_disabled():
                    await page.locator('#history-reader-next').click();await frames();next_steps+=1
                assert next_steps==5 and reads()==full_reads
                last=page.locator('.history-reader-item[data-item-id="A-refresh-new-final"]')
                assert await last.count()==1
                await last.get_by_role('button',name='Read containing task',exact=True).click()
                await page.locator('.history-reader-task-context').get_by_role('button',name='Read this task response',exact=True).click();await frames()
                response=await page.locator('.history-reader-target').inner_text()
                assert 'Latest task response: source review completed.' in response and 'NEW FIRST MATERIAL' not in response
                await page.locator('#history-reader-task-passage').click();await frames()
                await page.locator('#history-reader-find-query').fill('NEW FIRST MATERIAL');await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames()
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-first-new-command'
                assert reads()==full_reads
                await page.evaluate("navigator.clipboard.writeText=async t=>globalThis.__item_copy=t")
                await page.locator('.history-reader-target').get_by_role('button',name='Copy full item text',exact=True).click()
                copied=await page.evaluate('globalThis.__item_copy');assert 'NEW FIRST MATERIAL' in copied
                observations.append({'case':'existing-original-navigation-Find-response-baselines','first_new_full_item_copy_chars':len(copied),
                  'all_new_text_supplied':True,'next_page_steps_to_latest':next_steps,'latest_response_is_own_turn':True,
                  'latest_response_not_first_new_tool_evidence':True,'known_clue_Find_exact_item':'A-first-new-command','baseline_extra_native_reads':0})
                await unchanged();await page.screenshot(path=str(evidence/f'{width}-existing-find-reaches-first-new-tool.png'))
                storage=await page.evaluate('Object.fromEntries(Object.entries(localStorage))')
                entries=json.loads(stored_before)['checkpoints'];assert len(entries)==1 and entries[0]['owner']['thread_id']==exact
                assert set(entries[0]['owner'])=={'native_home','thread_id'}
                assert 'A-neighbor-184' not in stored_before and 'A-first-new-user' not in stored_before
                frontier_key='codex-desk-original-frontiers-v1'
                frontier_raw=await page.evaluate('k=>localStorage.getItem(k)',frontier_key)
                frontier=json.loads(frontier_raw)['snapshots'];assert len(frontier)==1
                assert frontier[0]['snapshot']=={'item_count':272,'boundary':{'turn_id':'A-refresh-new-turn','item_id':'A-refresh-new-final'}}
                assert 'NEW FIRST MATERIAL' not in frontier_raw and QUOTE not in frontier_raw
                await back();saved_frontier=await page.evaluate('k=>localStorage.getItem(k)',frontier_key)
                original['turns'].append({'id':'A-next-visit-turn','status':'completed','items':[
                  {'id':'A-next-visit-user','type':'userMessage','content':[{'type':'text','text':'Review next original snapshot.'}]},
                  {'id':'A-next-visit-final','type':'agentMessage','phase':'final_answer','text':'Next snapshot response.'}]})
                await page.evaluate('t=>DeskHistoryReader.show(t,{valid:()=>selected==="B"})',{'thread_id':exact,'turn_id':'A-turn','item_id':'A-neighbor-2','match_text':'Original neighbor 2'})
                await ready();assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-neighbor-2'
                assert not await page.locator('#history-reader-first-new').is_visible()
                assert await page.evaluate('k=>localStorage.getItem(k)',frontier_key)==saved_frontier
                await back();n=reads();await read();assert reads()==n+1
                assert '2 newly supplied native items' in await page.locator('#history-reader-new-status').inner_text()
                await page.locator('#history-reader-first-new').click();await frames()
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-next-visit-user'
                await page.locator('#history-reader-task-passage').click();await frames();await unchanged()
                observations.append({'case':'exact-source-target-priority-and-next-deliberate-original-read','explicit_target_preserved':True,'explicit_target_frontier_writes':0,'new_visit_first_item':'A-next-visit-user','prior_snapshot_item_count':272})
                await back();n=reads();await page.reload();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden");await frames()
                assert reads()==n and not await page.locator('#history-reader').evaluate('e=>e.open')
                selection=await state();opens=sum(r['path']=='/api/open' for r in http)
                await browse();await read();assert not await page.locator('#history-reader-first-new').is_visible();await unchanged()
                await back();original['turns'][-1]['items'][-1]['id']='replaced-previous-boundary'
                await read();assert 'boundary unavailable' in await page.locator('#history-reader-new-status').inner_text()
                assert not await page.locator('#history-reader-first-new').is_visible();await unchanged()
                await back();before_late=await page.evaluate('k=>localStorage.getItem(k)',frontier_key)
                entered,release=threading.Event(),threading.Event();holds['read']=(entered,release)
                await page.locator('#history-id').press('Enter');assert await asyncio.to_thread(entered.wait,10)
                await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
                release.set();await page.wait_for_function("!$('history-id-read').disabled");holds.clear()
                assert await page.evaluate('k=>localStorage.getItem(k)',frontier_key)==before_late
                await unchanged();observations.append({'case':'cold-no-auto-read-boundary-availability-late-closed-read','reload_auto_original_reads':0,'missing_prior_boundary_not_substituted':True,'late_closed_metadata_writes':0})
                assert {p.name:p.read_bytes() for p in home.iterdir()}==settings
                assert all(c['method'] in ('thread/list','thread/read') for c in calls)
                result={'viewport':width,'browser_version':browser.version,'result':'PASS','observations':observations,
                  'previous_original_checkpoint':entries[0],'storage':storage,'http':http,'native':calls,'sqlite_unchanged':True,
                  'B_draft':draft,'B_queue':queue,'errors':errors,'new_task_admissions':0,'implementation_changes':4}
                (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');return result
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (1250,390)]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'PASS','viewports':[{'width':r['viewport'],'browser':r['browser_version'],'sqlite_unchanged':True} for r in results]},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
