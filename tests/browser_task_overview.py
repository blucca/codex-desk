"""Installed supplied-task overview: deliberate task/response and exact source return."""
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
PREVIOUS='Previous supplied instruction, retained literally — Café 项目 😀.'
FOLLOWING='Following supplied instruction, retained literally — Café 项目 😀.'
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
        items[0]={'id':'A-current-instruction','type':'userMessage','content':[{'type':'text','text':'Current supplied instruction — inspect the retained transport observation.'}]}
        items[-1]={'id':'shared-response','type':'agentMessage','phase':'final_answer','text':'Current exact final, not previous or next.'}
        original={'id':exact,'cwd':str(root/'removed-A'),'name':'A retained original','modelProvider':'fixture-provider',
                  'turns':[
                    {'id':'A-previous-task','status':'completed','items':[{'id':'A-previous-instruction','type':'userMessage','content':[{'type':'text','text':PREVIOUS}]},{'id':'shared-response','type':'agentMessage','phase':'final_answer','text':'Previous exact final.'}]},
                    {'id':'A-turn','status':'failed','error':{'message':'Exact current source outcome retained.'},'items':items},
                    {'id':'A-following-task','status':'completed','items':[{'id':'A-following-instruction','type':'userMessage','content':[{'type':'text','text':FOLLOWING}]},{'id':'shared-response','type':'agentMessage','phase':'final_answer','text':'Following exact final.'},{'id':'following-commentary','type':'agentMessage','phase':'commentary','text':'Later commentary must not replace the final.'}]},
                    {'id':'A-empty-outcome','status':'interrupted','error':{'message':'Exact empty native outcome retained.'},'items':[]}]}
        for n in range(39):
            original['turns'].append({'id':f'skim-{n}','status':'failed' if n==29 else 'completed',
              'error':{'message':'Own skim native failure'} if n==29 else None,
              'items':[{'id':'same-user','type':'userMessage','content':[{'type':'text','text':f'Repeated skim instruction Café 项目 😀 — task {n}'}]},
                       {'id':'shared-response','type':'agentMessage','phase':'final_answer','text':f'OWN skim response {n}'},
                       {'id':'later-comment','type':'agentMessage','phase':'commentary','text':f'Later commentary {n} must not replace final'}]})
        original['turns'][34]['items']=[{'id':'shared-response','type':'agentMessage','text':'Own phase-absent response'}]
        original['turns'][35]['items']=[{'id':'shared-response','type':'agentMessage','phase':'partial_answer','text':'Own partial response without user input'}]
        original['turns'][36]['items']=[{'id':'only-tool','type':'commandExecution','command':'No assistant supplied','status':'completed','exitCode':0,'aggregatedOutput':'Actual tool only'}]
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
            def action(name):return page.locator(f'#history-reader-body [data-task-action="{name}"]')
            async def key(locator):await locator.evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
            async def context_turn():
                text=await page.locator('.history-reader-task-context').inner_text()
                return text.split('Turn ',1)[1].split('\n',1)[0]
            async def read_neighbor(turn_id,instruction_id,instruction,response):
                assert await context_turn()==turn_id
                context_text=await page.locator('.history-reader-task-context').inner_text();assert instruction in context_text
                assert 'Jump to supplied user instruction' in context_text
                await key(action('instruction:'+instruction_id))
                item=page.locator('.history-reader-target');assert await item.get_attribute('data-turn-id')==turn_id
                assert await item.get_attribute('data-item-id')==instruction_id
                assert await item.locator('pre').text_content()=='User\n'+instruction
                await key(page.locator('#history-reader-task-return'));assert await context_turn()==turn_id
                await key(action('response'));item=page.locator('.history-reader-target')
                assert await item.get_attribute('data-turn-id')==turn_id and await item.get_attribute('data-item-id')=='shared-response'
                assert await item.locator('pre').text_content()=='Codex\n'+response
                await key(page.locator('#history-reader-task-return'));assert await context_turn()==turn_id
                observations.append({'turn':turn_id,'instruction_item':instruction_id,'response_item':'shared-response','exact_turn_bound_instruction_response':True})
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.locator('.session-row[data-session="B"] .session').wait_for(state='visible')
                await page.locator('.session-row[data-session="B"] .session').click();await page.wait_for_function("selected==='B' && !opening && !$('task').hidden")
                await frames();selection=await state();db=list(desk.store.db.iterdump());draft=load_draft(desk.store,sid);queue=followup_snapshot(desk.store,sid);opens=sum(r['path']=='/api/open' for r in http)
                await browse();n=reads();await read();assert reads()==n+1
                before=await passage();await unchanged();await page.screenshot(path=str(evidence/f'{width}-direct-Find-source-passage.png'))
                native_boundary=reads();groups=[]
                async def tab_to(action_id):
                    for _ in range(95):
                        if await page.evaluate("document.activeElement?.dataset?.taskAction")==action_id:return
                        await page.keyboard.press('Tab')
                    raise AssertionError('Did not physically Tab to '+action_id)
                async def overview_state():
                    return await page.evaluate("""()=>({coverage:$('history-reader-coverage').textContent,body:$('history-reader-body').scrollTop,
                      outer:$('history-reader').scrollTop,focus:document.activeElement?.dataset?.taskAction,
                      rows:[...document.querySelectorAll('.history-reader-task-overview-row')].map(n=>n.dataset.turnId)})""")
                async def overview_return(expected):
                    await key(page.locator('#history-reader-task-overview-return'));await frames()
                    actual=await overview_state()
                    for name in ('coverage','rows','focus'):assert actual[name]==expected[name],(name,expected,actual)
                    for name in ('body','outer'):assert abs(actual[name]-expected[name])<2,(name,expected,actual)
                    return actual
                # Keyboard entrance keeps the long original passage's pointer Range/viewport.
                await key(page.locator('#history-reader-task-overview-show'))
                assert await page.locator('.history-reader-task-overview-row').count()==20
                assert 'Page 1 of 3' in await page.locator('#history-reader-coverage').text_content()
                assert await action('overview-previous').is_disabled()
                assert await page.locator('#history-reader-find-form').is_hidden()
                await action('overview-next').click();await frames()
                assert 'Page 2 of 3' in await page.locator('#history-reader-coverage').text_content()
                # Genuine pointer chooses one exact duplicate-prompt row, then its own response.
                pointer=action('overview-context:skim-29');await pointer.scroll_into_view_if_needed()
                pointer_view=await overview_state();pointer_view['focus']='overview-context:skim-29'
                await pointer.click();await frames();assert await context_turn()=='skim-29'
                assert 'Own skim native failure' in await page.locator('.history-reader-task-context').inner_text()
                await action('response').click();await frames();item=page.locator('.history-reader-target')
                assert await item.get_attribute('data-turn-id')=='skim-29' and await item.get_attribute('data-item-id')=='shared-response'
                assert await item.locator('pre').text_content()=='Codex\nOWN skim response 29'
                assert 'Final answer' in await page.locator('#history-reader-task-status').text_content()
                assert 'failed' in await page.locator('#history-reader-task-status').text_content()
                await overview_return(pointer_view);await unchanged()
                groups.append('pointer exact own task/final response and overview page/focus return')
                await page.screenshot(path=str(evidence/f'{width}-pointer-overview-page-row-return.png'))
                # A genuinely tabbed row opens its actual phase-absent response, not another final.
                await key(action('overview-previous'));await key(action('overview-next'))
                await tab_to('overview-response:skim-30');keyboard_view=await overview_state()
                await page.keyboard.press('Enter');await frames();item=page.locator('.history-reader-target')
                assert await item.get_attribute('data-turn-id')=='skim-30'
                assert await item.locator('pre').text_content()=='Codex\nOwn phase-absent response'
                labels=await page.locator('#history-reader-task-status').text_content()
                assert 'Last assistant message' in labels and 'Phase: unreported' in labels,labels
                await overview_return(keyboard_view);await unchanged()
                groups.append('genuine Tab/Enter exact phase-absent own response and page/focus return')
                await page.screenshot(path=str(evidence/f'{width}-keyboard-own-phase-absent-response-return.png'))
                own_partial=page.locator('.history-reader-task-overview-row[data-turn-id="skim-31"]')
                assert 'Partial answer · Phase: partial_answer' in await own_partial.inner_text()
                assert 'No user instruction was supplied' in await own_partial.inner_text()
                tool_only=page.locator('.history-reader-task-overview-row[data-turn-id="skim-32"]')
                assert 'No readable assistant response was supplied' in await tool_only.inner_text()
                assert await tool_only.get_by_role('button',name='Read task response',exact=True).is_disabled()
                await key(action('overview-previous'))
                empty=page.locator('.history-reader-task-overview-row[data-turn-id="A-empty-outcome"]')
                assert 'interrupted' in await empty.inner_text() and 'Exact empty native outcome retained.' in await empty.inner_text()
                assert await empty.get_by_role('button',name='Read task response',exact=True).is_disabled()
                await empty.get_by_role('button',name='Read task',exact=True).click();assert await context_turn()=='A-empty-outcome'
                await key(page.locator('#history-reader-task-overview-return'))
                await key(action('overview-next'));await key(action('overview-next'))
                assert await page.locator('.history-reader-task-overview-row').count()==3
                assert await action('overview-next').is_disabled()
                groups.append('20task bound/end pages and actual empty/error/noassistant/partial outcomes')
                await key(page.locator('#history-reader-task-passage'));await frames();after=await view()
                same(before,after);assert before['query']==after['query'] and before['selection']==after['selection']==QUOTE
                assert reads()==native_boundary;await unchanged()
                groups.append('exact later Unicode original Find/backwards pointer Range/glyph passage return')
                await page.screenshot(path=str(evidence/f'{width}-exact-original-Find-pointer-passage-return.png'))
                await page.evaluate("()=>{window.overviewEvents=[];for(const type of ['click','keydown','keyup'])document.addEventListener(type,e=>overviewEvents.push({type,key:e.key,id:e.target.id,action:e.target.dataset?.taskAction,focus:document.activeElement.id,coverage:$('history-reader-coverage').textContent}),true)}")
                # Refresh commits the latest overview page, while retiring old DOM actions.
                await key(page.locator('#history-reader-task-overview-show'));await key(action('overview-next'))
                await page.evaluate("()=>{globalThis.staleOverviewAction=document.querySelector('[data-task-action=\"overview-response:skim-29\"]').onclick;}")
                entered,release=threading.Event(),threading.Event();holds['read']=(entered,release)
                await key(page.locator('#history-reader-refresh'));assert await asyncio.to_thread(entered.wait,10)
                await key(action('overview-next'))
                original['turns'].append({'id':'fresh-task','status':'completed','items':[{'id':'fresh-answer','type':'agentMessage','phase':'final_answer','text':'Actual fresh supplied response'}]})
                release.set();await page.wait_for_function("!$('history-reader-refresh').disabled");await frames();holds.clear()
                assert 'Page 3 of 3' in await page.locator('#history-reader-coverage').text_content()
                assert await page.locator('.history-reader-task-overview-row').count()==4
                await page.evaluate('staleOverviewAction()');assert await page.locator('.history-reader-task-overview').count()==1
                assert 'Actual fresh supplied response' in await page.locator('.history-reader-task-overview').inner_text()
                await unchanged();groups.append('held Refresh preserves newer overview page and retires stale source action')
                await page.screenshot(path=str(evidence/f'{width}-held-Refresh-newer-overview-page.png'))
                await key(action('overview-previous'));await key(action('overview-response:skim-29'))
                original['turns']=[turn for turn in original['turns'] if turn['id']!='skim-29']
                await key(page.locator('#history-reader-refresh'));await page.wait_for_function("!$('history-reader-refresh').disabled");await frames()
                assert 'not present' in await page.locator('#history-reader-match').text_content()
                await key(page.locator('#history-reader-task-overview-return'))
                assert 'previously selected from this overview is no longer available' in await page.locator('.history-reader-task-overview').inner_text()
                await unchanged();groups.append('missing selected turn keeps exact source identity/availability')
                await page.screenshot(path=str(evidence/f'{width}-missing-selected-task-kept-not-substituted.png'))
                entered,release=threading.Event(),threading.Event();holds['read']=(entered,release)
                await key(page.locator('#history-reader-refresh'));assert await asyncio.to_thread(entered.wait,10)
                await key(page.locator('#history-reader-close'));release.set();await page.wait_for_timeout(100);await frames();holds.clear()
                assert not await page.locator('#history-reader').evaluate('n=>n.open');await unchanged()
                groups.append('closed reader retires held refresh with exact B Plan/twoqueues/SQL/noPOST')
                result={'result':'PASS','width':width,'browser':browser.version,'groups':groups,'runtime':'installed',
                    'source_tasks':43,'task_page_limit':20,'B_plan':draft,'B_queues':queue,'sqlite_unchanged':True,
                    'native_reads_while_skim_context_response_original_return':0,'explicit_refresh_reads':reads()-native_boundary,
                    'original_Find_backwards_pointer_Range_return_exact':True,'genuine_Tab_Enter':True,'genuine_pointer':True,
                    'http':http,'native':calls,'errors':errors,'external':external}
                (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                print(json.dumps({'width':width,'result':'PASS','groups':len(groups),'bound':20,'original_exact':True,'B_unchanged':True}),flush=True)
                return result
            except BaseException:
                await page.screenshot(path=str(evidence/f'{width}-failure.png'))
                diagnostic=await page.evaluate("({open:$('history-reader').open,body:$('history-reader-body').innerText,status:$('history-reader-status').textContent,coverage:$('history-reader-coverage').textContent,active:document.activeElement?.outerHTML})")
                (evidence/f'{width}-failure.json').write_text(json.dumps({'ui':diagnostic,'errors':errors,'native':calls,'events':await page.evaluate('window.overviewEvents')},ensure_ascii=False,indent=2))
                raise
            finally:
                for _,release in holds.values():release.set()
                await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()

async def main():
    os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as pw:results=[await check(width,pw,evidence) for width in map(int,os.environ.get('DESK_VIEWPORTS','1250,390').split(','))]
    (evidence/'acceptance.json').write_text(json.dumps({'result':'PASS','widths':[r['width'] for r in results],'groups':sum(len(r['groups']) for r in results),'overview_task_page_limit':20},indent=2)+'\n')
if __name__=='__main__':asyncio.run(main())
