"""Physical original command-output return across generated Status/Exit changes."""
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
BOUNDARY_BEFORE=os.environ.get("DESK_BOUNDARY_BEFORE")=="1"
BEFORE=False
async def check(width,pw,evidence):
    with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'],prefix=f'original-return-{width}-') as tmp:
        root=Path(tmp);home=root/'home';home.mkdir();project=root/'B';project.mkdir()
        (home/'config.toml').write_text('model="fixture-model"\n');(home/'auth.json').write_text('{"fixture":"unchanged"}\n')
        settings={p.name:p.read_bytes() for p in home.iterdir()}
        exact='known-A/接口?+'
        output='\n'.join(f'L{n:04d}'+(' '+QUOTE if n==6450 else '') for n in range(10000))
        items=[{'id':f'A-neighbor-{n}','type':'agentMessage','text':f'Original neighbor {n}'} for n in range(85)]
        items[45]={'id':'A-command','type':'commandExecution','command':'fixture inspect source','status':'inProgress','exitCode':None,'aggregatedOutput':output}
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
                    for(const match of text.matchAll(/L(\d{4})[^\n]*/g)){
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
            async def observe():
                v=await visible();text=await target().locator('pre').text_content()
                projected=await target().evaluate("n=>DeskHistoryReader.textForItem({type:'commandExecution',command:'fixture inspect source',status:n.querySelector('summary').textContent.includes('inProgress')?'inProgress':'completed',exitCode:n.querySelector('summary').textContent.includes('exit 0')?0:null,aggregatedOutput:''})")
                v['output_boundary']=len(projected.encode('utf-16-le'))//2
                if v['first_visible']:v['first_visible']['output_offset']=v['first_visible']['offset']-v['output_boundary']
                return v
            async def mutate(status,code):
                command=original['turns'][0]['items'][45]
                command['status']=status;command['exitCode']=code
                await page.evaluate("x=>{globalThis.__native_status=x[0];globalThis.__native_exit=x[1]}",[status,code])
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.locator('.session-row[data-session="B"] .session').wait_for(state='visible')
                await page.locator('.session-row[data-session="B"] .session').click();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden")
                await frames();selection=await state();db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid);opens=sum(r['path']=='/api/open' for r in http)
                await mutate('inProgress',None);await browse();n=reads();await read();assert reads()==n+1
                before=await passage();v_before=await observe();await unchanged();await page.screenshot(path=str(evidence/f'{width}-before.png'))
                await back();stored=await page.evaluate("localStorage.getItem('codex-desk-original-reading-checkpoints-v1')")
                await mutate('completed',0);n=reads();await read();assert reads()==n+1
                after=await view();v_after=await observe();await unchanged();await page.screenshot(path=str(evidence/f'{width}-reopen.png'))
                reopen_same=v_before['first_visible']['output_offset']==v_after['first_visible']['output_offset']
                observations.append({'case':'close-header-only-change-reopen','before':v_before,'after':v_after,'before_view':before,'after_view':after,'same_output_character':reopen_same})
                await mutate('completed',0);await passage();refresh_before=await view();vr_before=await observe()
                await mutate('inProgress',None);n=reads();await page.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter')
                await page.wait_for_function("!$('history-reader-refresh').disabled && $('history-reader-status').textContent.startsWith('Original refreshed.')");await frames();assert reads()==n+1
                refresh_after=await view();vr_after=await observe();await unchanged();await page.screenshot(path=str(evidence/f'{width}-refresh.png'))
                refresh_same=vr_before['first_visible']['output_offset']==vr_after['first_visible']['output_offset']
                if not BOUNDARY_BEFORE:
                    assert refresh_after['selection']==QUOTE,refresh_after
                    assert refresh_after['query']==QUOTE
                    assert 'Match 1 of 1' in await page.locator('#history-reader-find-status').inner_text()
                    assert int(after['start'])==int(before['start'])-12
                    await target().get_by_role('button',name='Read containing task',exact=True).evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                    await page.locator('#history-reader-task-passage').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                    assert (await view())['selection']==QUOTE
                    await unchanged()
                observations.append({'case':'in-view-header-only-change-Refresh','before':vr_before,'after':vr_after,'before_view':refresh_before,'after_view':refresh_after,'same_output_character':refresh_same})
                await passage();nested_before=await observe();nested_view=await view()
                await target().get_by_role('button',name='Read containing task',exact=True).evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                await mutate('completed',0);n=reads();await page.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter')
                await page.wait_for_function("!$('history-reader-refresh').disabled && $('history-reader-status').textContent.startsWith('Original refreshed.')");await frames();assert reads()==n+1
                await page.locator('#history-reader-task-passage').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
                await page.wait_for_function("!$('history-reader-find-submit').disabled");await frames()
                nested_after=await observe();nested_return=await view();await unchanged();await page.screenshot(path=str(evidence/f'{width}-task-Refresh-return.png'))
                nested_same=nested_before['first_visible']['output_offset']==nested_after['first_visible']['output_offset']
                observations.append({'case':'containing-task-header-only-Refresh-return-original-passage','before':nested_before,'after':nested_after,'before_view':nested_view,'after_view':nested_return,'same_output_character':nested_same})
                print(json.dumps({'width':width,'nested_same':nested_same,'nested_before':nested_before['first_visible'],'nested_after':nested_after['first_visible']}),flush=True)
                if not BOUNDARY_BEFORE:
                    assert nested_same and nested_return['selection']==QUOTE,nested_return
                    assert 'Match 1 of 1' in await page.locator('#history-reader-find-status').inner_text()
                opposite=390 if width==1250 else 1250
                async def begin_hold():
                    entered,release=threading.Event(),threading.Event();holds['read']=(entered,release)
                    await page.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter')
                    assert await asyncio.to_thread(entered.wait,10)
                    return release
                async def release_hold(release):
                    release.set();holds.clear()
                    await page.wait_for_function("!$('history-reader-refresh').disabled");await frames();await frames()
                    status=await page.locator('#history-reader-status').inner_text()
                    if not status.startswith('Original refreshed.'):
                        diagnostic={'status':status,'view':await view(),'visible':await observe(),'errors':errors}
                        (evidence/f'{width}-held-diagnostic.json').write_text(json.dumps(diagnostic,indent=2)+'\n')
                        await page.screenshot(path=str(evidence/f'{width}-held-diagnostic.png'))
                await passage();held_before=await observe();held_character=await probe_character(target(),output,held_before['first_visible']['output_offset'],held_before['output_boundary']);release=await begin_hold();await mutate('inProgress',None)
                await page.set_viewport_size({'width':opposite,'height':900 if opposite==1250 else 844});await frames();await release_hold(release)
                held_after=await observe();held_view=await view();await unchanged();await page.screenshot(path=str(evidence/f'{width}-held-resize.png'))
                returned_character=await probe_character(target(),output,held_character['source_offset'],held_after['output_boundary'])
                assert_responsive_character(held_character,returned_character);held_same=True
                observations.append({'case':'held-header-Refresh-passive-opposite-width-resize','before':held_before,'after':held_after,'same_output_character':held_same,'before_character':held_character,'after_character':returned_character})
                if not BOUNDARY_BEFORE:assert held_same and held_view['selection']==QUOTE,(held_before,held_after,held_view)
                await passage();release=await begin_hold();await mutate('completed',0)
                await page.set_viewport_size({'width':width,'height':900 if width==1250 else 844});await frames()
                # Responsive layout can move the retained item outside the
                # reader while its fresh read is held. Reveal the actual source
                # before a physical wheel; a negative viewport point is no gesture.
                await target().locator('pre').scroll_into_view_if_needed();await frames()
                wheel_clip=await target().evaluate("n=>{const p=n.querySelector('pre').getBoundingClientRect(),b=$('history-reader-body').getBoundingClientRect(),r=$('history-reader').getBoundingClientRect();return {left:Math.max(p.left,b.left,r.left,0),right:Math.min(p.right,b.right,r.right,innerWidth),top:Math.max(p.top,b.top,r.top,0),bottom:Math.min(p.bottom,b.bottom,r.bottom,innerHeight),inner:n.querySelector('pre').scrollTop}}")
                assert wheel_clip['right']>wheel_clip['left'] and wheel_clip['bottom']>wheel_clip['top'],wheel_clip
                await page.mouse.move((wheel_clip['left']+wheel_clip['right'])/2,(wheel_clip['top']+wheel_clip['bottom'])/2);await page.mouse.wheel(0,105)
                await page.wait_for_function("n=>document.querySelector('.history-reader-item[data-item-id=\"A-command\"] pre').scrollTop>n",arg=wheel_clip['inner'])
                await page.wait_for_timeout(150);await frames();wheel_before=await observe();await release_hold(release);wheel_after=await observe();await unchanged()
                wheel_same=wheel_before['first_visible']['output_offset']==wheel_after['first_visible']['output_offset']
                observations.append({'case':'held-header-Refresh-resize-newer-physical-wheel-wins','wheel_clip':wheel_clip,'before':wheel_before,'after':wheel_after,'same_output_character':wheel_same})
                if not BOUNDARY_BEFORE:assert wheel_same,(wheel_before,wheel_after)
                await passage();release=await begin_hold();await mutate('inProgress',None)
                await page.set_viewport_size({'width':opposite,'height':900 if opposite==1250 else 844});await frames()
                await page.locator('#history-reader-find-query').fill('L3000');await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames()
                find_before=await observe();await release_hold(release);find_after=await observe();await unchanged()
                find_same=find_before['first_visible']['output_offset']==find_after['first_visible']['output_offset']
                observations.append({'case':'held-header-Refresh-resize-newer-physical-Find-wins','before':find_before,'after':find_after,'same_output_character':find_same})
                if not BOUNDARY_BEFORE:
                    assert find_same,(find_before,find_after)
                    assert (await view())['query']=='L3000' and 'Match 1 of 1' in await page.locator('#history-reader-find-status').inner_text()
                print(json.dumps({'width':width,'held_resize_same':held_same,'later_wheel_same':wheel_same,'later_Find_same':find_same}),flush=True)
                result={'result':'OBSERVED' if BOUNDARY_BEFORE else 'PASS','browser':browser.version,'width':width,'observations':observations,'native':calls,'http':http,'sqlite_unchanged':True,'B_draft':draft,'B_queue':queue,'B_selection':selection,'task_admissions':0,'external':external,'errors':errors,'stored_metadata':json.loads(stored),'unchanged_native_output':original['turns'][0]['items'][45]['aggregatedOutput']==output}
                (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'width':width,'reopen_same':reopen_same,'refresh_same':refresh_same,'before':v_before['first_visible'],'after':v_after['first_visible'],'refresh_before':vr_before['first_visible'],'refresh_after':vr_after['first_visible']}),flush=True)
                if not BOUNDARY_BEFORE:assert reopen_same and refresh_same,result
                return result
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in (1250,390)]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'OBSERVED' if BOUNDARY_BEFORE else 'PASS','widths':[r['width'] for r in results]},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
