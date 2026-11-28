"""Physical original glyph-anchor return: normal, responsive, cold and late input."""
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
from original_character_oracle import probe_character,assert_responsive_character

QUOTE='RETURN PASSAGE Café 项目 😀'
BEFORE=False
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
                return {'data':[{k:v for k,v in original.items() if k!='turns'}] if params.get('archived') is True else [],'nextCursor':None}
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
                assert await page.locator('#history-source').input_value()=='current'
                await page.locator('#history-source').select_option('archived');await page.wait_for_function("!$('history-search-submit').disabled")
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
            async def visible():
                return await target().evaluate(r"""n=>{
                    const p=n.querySelector('pre'),reader=$('history-reader'),body=$('history-reader-body');
                    const pr=p.getBoundingClientRect(),br=body.getBoundingClientRect(),rr=reader.getBoundingClientRect();
                    const clip={left:Math.max(pr.left,br.left,rr.left,0),right:Math.min(pr.right,br.right,rr.right,innerWidth),
                      top:Math.max(pr.top,br.top,rr.top,0),bottom:Math.min(pr.bottom,br.bottom,rr.bottom,innerHeight)};
                    const text=p.textContent,start=Number(n.dataset.windowStart),walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),nodes=[];
                    let offset=0,node;while(node=walker.nextNode()){nodes.push({node,start:offset,end:offset+node.data.length});offset+=node.data.length;}
                    function point(at,right=false){for(const q of nodes){if(at<q.end || !right && at===q.end)return [q.node,at-q.start];}
                      const last=nodes.at(-1);return last?[last.node,last.node.data.length]:null;}
                    function rects(a,b){const first=point(a,true),last=point(b);if(!first || !last)return [];
                      const range=document.createRange();range.setStart(...first);range.setEnd(...last);
                      return [...range.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}));}
                    const inside=r=>r.right>clip.left && r.left<clip.right && r.bottom>clip.top && r.top<clip.bottom;
                    const rows=[];let firstVisible=null,lastVisible=null;
                    for(const match of text.matchAll(/Original (\d{4})[^\n]*/g)){
                      const at=match.index,end=at+match[0].length,boxes=rects(at,end);
                      if(!boxes.some(inside))continue;
                      const chars=[];let local=at;
                      for(const char of match[0]){const last=local+char.length,r=rects(local,last).find(inside);
                        if(r){chars.push(char);if(!firstVisible)firstVisible={offset:start+local,char,line:Number(match[1]),top:r.top};lastVisible={offset:start+last,char,line:Number(match[1]),bottom:r.bottom};}
                        local=last;}
                      rows.push({line:Number(match[1]),offset:start+at,visible_text:chars.join(''),rects:boxes.filter(inside)});
                    }
                    const quote='RETURN PASSAGE Café 项目 😀',at=text.indexOf(quote),boxes=at<0?[]:rects(at,at+quote.length);
                    return {viewport:{width:innerWidth,height:innerHeight},clip,pre:{top:pr.top,bottom:pr.bottom,width:pr.width,height:pr.height,
                      scroll_top:p.scrollTop,font:getComputedStyle(p).font,font_size:getComputedStyle(p).fontSize,line_height:getComputedStyle(p).lineHeight},
                      window_start:start,first_visible:firstVisible,last_visible:lastVisible,visible_lines:rows,
                      quote:{offset:at<0?null:start+at,rects:boxes,visible:boxes.some(inside),fully_visible:boxes.length>0&&boxes.every(r=>r.left>=clip.left&&r.right<=clip.right&&r.top>=clip.top&&r.bottom<=clip.bottom)}};
                }""")
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
                await page.locator('.session-row[data-session="B"] .session').wait_for(state='visible')
                await page.locator('.session-row[data-session="B"] .session').click();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden")
                await frames();selection=await state();db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid);opens=sum(r['path']=='/api/open' for r in http)
                await browse();titles=await page.locator('#native-list').text_content()
                assert await page.locator('#history-source').input_value()=='archived'
                assert await page.locator('#native-list .native-read').count()==1
                assert not await page.locator('#native-list button').filter(has_text='Resume').count()
                assert not await page.locator('#native-list button').filter(has_text='Review handoff').count()
                title_calls=[c for c in calls if c['method']=='thread/list'];assert any(c['params'].get('archived') is True for c in title_calls)
                n=reads();await page.locator('#native-list .native-read').click();await ready();assert reads()==n+1
                first=await passage();visible_before=await visible();await unchanged()
                projection=await target().evaluate("n=>DeskHistoryReader.textForItem({type:'commandExecution',command:'fixture inspect source',status:'completed',exitCode:0,aggregatedOutput:''}).length")
                remembered=await probe_character(target(),output,visible_before['first_visible']['offset']-projection,projection)
                assert visible_before['quote']['fully_visible'],visible_before
                await page.screenshot(path=str(evidence/f'{width}-before.png'))
                await back();assert await page.locator('#history-source').input_value()=='archived'
                n=reads();await read();assert reads()==n+1;normal=await visible();await unchanged()
                assert normal['first_visible']['offset']==visible_before['first_visible']['offset'],(normal,visible_before)
                assert abs(normal['pre']['scroll_top']-first['inner'])<2
                await back()
                stored=await page.evaluate("localStorage.getItem('codex-desk-original-reading-checkpoints-v1')")
                owner=json.loads(stored)['checkpoints'][0]['owner']
                opposite=1250 if width==390 else 390
                await page.set_viewport_size({'width':opposite,'height':900 if opposite==1250 else 844});await frames()
                n=reads();assert not await page.locator('#history-reader').evaluate('n=>n.open')
                await read();assert reads()==n+1;await frames()
                reopened=await view();visible_after=await visible();await unchanged()
                assert reopened['turn']==first['turn'] and reopened['item']==first['item'] and reopened['start']==first['start']
                assert reopened['open']==first['open'] and reopened['disclosures']==first['disclosures']
                assert reopened['query']=='' and reopened['selection']==''
                assert visible_before['quote']['offset']==visible_after['quote']['offset']
                reopened_character=await probe_character(target(),output,remembered['source_offset'],projection)
                assert_responsive_character(remembered,reopened_character)
                cold_reference=await probe_character(target(),output,visible_after['first_visible']['offset']-projection,projection)
                assert visible_after['quote']['fully_visible'],visible_after
                omission=False
                await page.screenshot(path=str(evidence/f'{width}-to-{opposite}-reopened.png'))
                n=reads();await page.reload();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden");await frames()
                assert not await page.locator('#history-reader').evaluate('n=>n.open') and reads()==n
                selection=await state();opens=sum(r['path']=='/api/open' for r in http);await unchanged()
                await page.set_viewport_size({'width':width,'height':900 if width==1250 else 844});await frames()
                await browse();n=reads();await read();assert reads()==n+1;cold=await visible();await unchanged()
                cold_character=await probe_character(target(),output,cold_reference['source_offset'],projection)
                assert_responsive_character(cold_reference,cold_character)
                assert cold['quote']['fully_visible'];await page.screenshot(path=str(evidence/f'{width}-cold-restored.png'))
                await back()
                meta=await page.evaluate("JSON.parse(localStorage.getItem('codex-desk-original-reading-checkpoints-v1'))")
                entry=meta['checkpoints'][0]
                assert entry['owner']==owner and set(entry['owner'])=={'native_home','thread_id'}
                character=next(row['visible_character'] for row in entry['view']['item_views'] if row['item_id']=='A-command')
                assert set(character)=={'offset','top'} and character['offset']==cold['first_visible']['offset']
                assert QUOTE not in json.dumps(meta) and 'Original 1450' not in json.dumps(meta)
                for row in entry['view']['item_views']:row.pop('visible_character',None)
                legacy_inner=next(row['scroll_top'] for row in entry['view']['item_views'] if row['item_id']=='A-command')
                await page.evaluate("m=>localStorage.setItem('codex-desk-original-reading-checkpoints-v1',JSON.stringify(m))",meta)
                await page.set_viewport_size({'width':opposite,'height':900 if opposite==1250 else 844});await frames()
                n=reads();await read();assert reads()==n+1;legacy=await visible();assert legacy['pre']['scroll_top']==legacy_inner
                assert await target().get_attribute('data-window-start')==first['start'];await unchanged()
                await passage();await back()
                await page.evaluate('t=>DeskHistoryReader.show(t,{valid:()=>selected==="B"})',{'thread_id':exact,'turn_id':'A-turn','item_id':'A-neighbor-2','match_text':'Original neighbor 2'})
                await ready();assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='A-neighbor-2'
                assert 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text();await back();await unchanged()
                entered,release=asyncio.Event(),asyncio.Event()
                async def held_home(route):entered.set();await release.wait();await route.continue_()
                await page.route('**/api/native/home',held_home)
                n=reads();await page.locator('#native-list .native-read').click();await ready();await asyncio.wait_for(entered.wait(),10)
                assert reads()==n+1 and 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text()
                await page.locator('#history-reader-find-query').click();await page.keyboard.type('Original neighbor 5');await page.keyboard.press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames()
                newer=page.locator('.history-reader-target');assert await newer.get_attribute('data-item-id')=='A-neighbor-5'
                boxes=await newer.locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
                first_box,last_box=boxes[0],boxes[-1]
                await page.mouse.move(first_box['left']+.5,(first_box['top']+first_box['bottom'])/2);await page.mouse.down()
                await page.mouse.move(last_box['right']-.5,(last_box['top']+last_box['bottom'])/2,steps=10);await page.mouse.up()
                assert await page.evaluate('getSelection().toString()')=='Original neighbor 5'
                def input_state():return page.evaluate("({item:$('history-reader-body').querySelector('.history-reader-target')?.dataset.itemId,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,query:$('history-reader-find-query').value,selectedText:getSelection().toString()})")
                late_before=await input_state();release.set();await page.wait_for_timeout(150);await frames();late_after=await input_state()
                assert late_after==late_before,(late_before,late_after);await page.unroute('**/api/native/home',held_home);await unchanged()
                await page.screenshot(path=str(evidence/f'{width}-late-pointer-retained.png'))
                result={'result':'PASS','direction':[width,opposite],
                  'browser_version':browser.version,'owner':owner,'native_source_unchanged':True,'source_window_and_item_unchanged':True,
                  'same_visible_character':True,'remembered_character':remembered,'reopened_character':reopened_character,'cold_character':cold_character,'cold_reference':cold_reference,'legacy_pixel_fallback':True,'normal':normal,'cold':cold,'legacy':legacy,'late_input_before':late_before,'late_input_after':late_after,'fresh_reads':1,'auto_reads':0,'before':first,'after':reopened,
                  'visible_before':visible_before,'visible_after':visible_after,'original_metadata':json.loads(stored),
                  'http':http,'native':calls,'sqlite_unchanged':True,'B_draft':draft,'B_queue':queue,'B_selection':selection,
                  'task_admissions':0,'external':external,'errors':errors}
                assert not omission,result
                assert {p.name:p.read_bytes() for p in home.iterdir()}==settings
                assert all(c['method'] in ('thread/list','thread/read') for c in calls)
                (evidence/f'{width}-to-{opposite}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'direction':[width,opposite],'before_line':visible_before['first_visible']['line'],
                  'after_line':visible_after['first_visible']['line'],'before_offset':visible_before['first_visible']['offset'],
                  'after_offset':visible_after['first_visible']['offset'],'before_pre_scroll':first['inner'],'after_pre_scroll':visible_after['pre']['scroll_top'],
                  'quote_visible_after':visible_after['quote']['visible'],'sqlite_unchanged':True}),flush=True)
                return result
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (390,1250)]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'PASS','metadata_only':True,'directions':[{'direction':r['direction'],'browser':r['browser_version'],'sqlite_unchanged':True,'same_item_window_character':True,'cold':True,'legacy_fallback':True,'late_pointer':True} for r in results]},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
