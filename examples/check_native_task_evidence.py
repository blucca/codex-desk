import asyncio,copy,importlib.util,json,os,tempfile,threading,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
S=Path(os.environ['DESK_SOURCE'])
SPEC=importlib.util.spec_from_file_location('union_nav',S/'examples/check_native_find_matches.py');nav=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(nav)
base=nav.base
from codex_desk.drafts import load_draft,save_draft
from codex_desk.evidence_reference import parse_evidence_blocks
from playwright.async_api import async_playwright
SOURCE,TURN,COMMAND,PHRASE,QUERY=nav.SOURCE,nav.TURN,nav.COMMAND,nav.PHRASE,nav.QUERY
def make_tasks(root):
 thread=nav.make_source(root)
 for n,turn in enumerate(thread['turns']):
  items=[{'id':'own-instruction','type':'userMessage','content':[{'type':'text','text':f'Inspect exact supplied task {n:02d}.'}]}]
  for index in range(1,47):
   items.append({'id':f'command-{index:02d}','type':'commandExecution','command':f'inspect task {n} item {index}','status':'completed','exitCode':0,'aggregatedOutput':f'Original task{n} native item{index} — Café 项目 😀'})
  items[46]=base.assistant('same-reply-id',f'Actual final response task {n}.','final_answer')
  if n==41:
   items[1]=None;items[2]={'id':'future-item','type':'futureNativeItem','data':'retained unsupported'}
   items[3]={'id':'plan','type':'plan','text':'Actual supplied plan evidence'}
   items[4]={'id':'files','type':'fileChange','changes':[{'path':'parser.py','diff':'-old\n+native correction'}]}
   items[5]={'id':'mcp','type':'mcpToolCall','server':'native-server','tool':'inspect','arguments':{'name':'actual'},'result':{'content':[{'type':'text','text':'Exact original MCP result'}]}}
   items[6]={'id':'tool','type':'dynamicToolCall','tool':'actualInspect','arguments':{'path':'parser.py'},'contentItems':[{'type':'inputText','text':'Exact original dynamic result'}]}
   items[7]={'id':'collab','type':'collabAgentToolCall','tool':'wait','status':'completed','senderThreadId':SOURCE,'receiverThreadIds':[]}
   output='\n'.join(f'Native source line {i:04d} retains Café 项目 😀'+(' '+PHRASE if i==1450 else '') for i in range(1900))
   items[42]={'id':COMMAND,'type':'commandExecution','command':'inspect source without executing','status':'completed','exitCode':0,'aggregatedOutput':output}
  elif n in (0,45):items[42]={'id':COMMAND,'type':'commandExecution','command':'inspect neighbor original','status':'completed','exitCode':0,'aggregatedOutput':PHRASE+' outside selected task'}
  turn['items']=items
 return thread
async def one(browser,width,evidence):
 with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'],prefix=f'connected-union-{width}-') as tmp:
  root=Path(tmp);f=base.Fixture(root);context=None;holds={};http=[];errors=[];external=[];phase='prepare';steps=[];glyphs=[]
  f.threads[SOURCE]=make_tasks(root);command=f.threads[SOURCE]['turns'][41]['items'][42];original_output=command['aggregatedOutput']
  save_draft(f.desk.store,base.ORIGINAL,'B exact unsent Plan — 保持\nUse only reviewed original evidence.','plan',1)
  class Reader(f.reader_type):
   def request(self,method,params,timeout=30):
    hold=holds.get(params.get('threadId'))
    if hold:
     entered,release=hold;entered.set();assert release.wait(30),'Unreleased connected native original'
    return super().request(method,params,timeout)
  result={'result':'RUNNING','width':width}
  with patch.object(base.product,'_NativeReader',Reader),patch.object(base.product,'Runtime',side_effect=AssertionError('Connected source read created a native task')):
   try:
    context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844});page=await context.new_page();page.set_default_timeout(15000)
    await context.add_init_script("(()=>{const later=setTimeout;window.setTimeout=function(fn,...args){if(fn?.name==='tick')return 0;return later.call(this,fn,...args);};})();")
    await context.add_init_script("Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(text){(window.__copies ||= []).push(text)}}});")
    page.on('pageerror',lambda e:errors.append(str(e)))
    def requested(r):
     u=urlsplit(r.url);http.append({'path':u.path,'query':parse_qs(u.query),'method':r.method})
     if u.hostname!='127.0.0.1':external.append(r.url)
    page.on('request',requested)
    await page.goto(f'http://127.0.0.1:{f.server.server_port}')
    await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click();await page.wait_for_function('id=>selected===id&&!opening',arg=base.ORIGINAL)
    sql=f.sql();preparation=f.prepared();selection=await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})");opens=list(f.opens);queue_initial=copy.deepcopy(preparation[base.ORIGINAL]['queue'])
    allowed_draft_posts=0
    async def unchanged():
     assert f.sql()==sql and f.prepared()==preparation and f.opens==opens
     assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")==selection
     assert preparation[base.ORIGINAL]['queue']==queue_initial
     assert not errors and not external,(errors,external)
     assert len([r for r in http if r['method']=='POST' and r['path']=='/api/draft'])==allowed_draft_posts
     assert not [r for r in http if r['method']=='POST' and r['path'] not in ('/api/open','/api/draft')]
     assert command['aggregatedOutput']==original_output
     assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
    async def record(name):
     nonlocal phase
     phase=name;await unchanged();steps.append(name);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
    async def frames():await base.frames(page)
    async def ready():await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames()
    async def read(identifier=SOURCE):
     await page.locator('#history-id').fill(identifier);await page.locator('#history-id').press('Enter');await ready()
    async def find(query=QUERY,count=3):
     await page.locator('#history-reader-find-query').fill(query);await page.locator('#history-reader-find-query').press('Enter')
     await page.wait_for_function('count=>$('+'"history-reader-find-status"'+').textContent.includes("Match 1 of "+count)',arg=count);await frames()
    def target():return page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{COMMAND}"]')
    async def view():
     return await target().evaluate("n=>({turn:n.dataset.turnId,item:n.dataset.itemId,start:Number(n.dataset.windowStart),scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString(),backward:getSelection().anchorNode===getSelection().focusNode?getSelection().anchorOffset>getSelection().focusOffset:null,query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop})")
    async def overview(returned=False):
     await page.locator('#history-reader-find-matches-return' if returned else '#history-reader-find-matches-show').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
     assert await page.locator('#history-reader-find-matches').is_visible()
     while int(await page.locator('.history-reader-find-match').first.get_attribute('data-match-index'))!=40:
      at=int(await page.locator('.history-reader-find-match').first.get_attribute('data-match-index'))
      await page.locator('#history-reader-find-matches-next' if at<40 else '#history-reader-find-matches-previous').focus();await page.keyboard.press('Enter');await frames()
    async def choose(late=True,keyboard=False):
     rows=page.locator(f'.history-reader-find-match[data-turn-id="{TURN}"][data-item-id="{COMMAND}"]');row=rows.last if late else rows.first
     at=int(await row.get_attribute('data-match-index'))
     if keyboard:
      await page.locator('#history-reader-find-matches-status').focus()
      for _ in range(at-40+1):await page.keyboard.press('Tab')
      assert await page.evaluate('document.activeElement.dataset.findAction')=='match:'+str(at);await page.keyboard.press('Enter')
     else:await row.locator('button').click()
     await frames();assert await target().locator('mark').text_content()==PHRASE
     assert await page.locator('.history-reader-target').get_attribute('data-item-id')==COMMAND
     return at
    async def quote():
     boxes=await target().locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))');a,b=boxes[0],boxes[-1]
     await page.mouse.move(b['right']-.5,(b['top']+b['bottom'])/2);await page.mouse.down();await page.mouse.move(a['left']+.5,(a['top']+a['bottom'])/2,steps=12);await page.mouse.up()
     assert await page.evaluate('getSelection().toString()')==PHRASE
     assert await page.evaluate('getSelection().anchorNode===getSelection().focusNode&&getSelection().anchorOffset>getSelection().focusOffset')
    async def glyph(output_at=None):
     return await target().evaluate(r'''(n,arg)=>{
      const p=n.querySelector('pre'),text=p.textContent,start=Number(n.dataset.windowStart),summary=n.querySelector('summary').textContent;
      const prefix=DeskHistoryReader.textForItem({type:'commandExecution',command:arg.command,status:summary.includes('inProgress')?'inProgress':'completed',exitCode:summary.includes('exit 0')?0:null,aggregatedOutput:''}).length;
      const pr=p.getBoundingClientRect(),br=$('history-reader-body').getBoundingClientRect(),rr=$('history-reader').getBoundingClientRect();
      const clip={top:Math.max(pr.top,br.top,rr.top,0),bottom:Math.min(pr.bottom,br.bottom,rr.bottom,innerHeight),left:Math.max(pr.left,br.left,rr.left,0),right:Math.min(pr.right,br.right,rr.right,innerWidth)};
      const walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),nodes=[];let node,offset=0;
      while(node=walker.nextNode()){nodes.push({node,start:offset,end:offset+node.data.length});offset+=node.data.length;}
      function point(at,right=false){for(const q of nodes)if(at<q.end||!right&&at===q.end)return[q.node,at-q.start];const last=nodes.at(-1);return last?[last.node,last.node.data.length]:null;}
      function rects(at,end){const a=point(at,true),b=point(end);if(!a||!b)return[];const r=document.createRange();r.setStart(...a);r.setEnd(...b);return [...r.getClientRects()].filter(q=>q.width>0&&q.height>0);}
      function seen(r){return r.right>clip.left&&r.left<clip.right&&r.bottom>clip.top&&r.top<clip.bottom;}
      let at=arg.output_at===null?null:arg.output_at+prefix-start;
      if(at===null){outer:for(const m of text.matchAll(/Native source line \d{4}[^\n]*/g)){
       if(!rects(m.index,m.index+m[0].length).some(seen))continue;
       let i=m.index;for(const ch of m[0]){if(rects(i,i+ch.length).some(seen)){at=i;break outer;}i+=ch.length;}
      }}
      if(at===null||at<0||at>=text.length)return {available:false,output_at:arg.output_at,prefix,start,clip};
      const length=text.codePointAt(at)>0xffff?2:1,r=rects(at,at+length)[0];
      return r?{available:true,output_at:start+at-prefix,visible:seen(r),top:r.top-clip.top,bottom:r.bottom-clip.top,prefix,start,scroll:p.scrollTop,character:text.slice(at,at+length)}:{available:false};
     }''',{'output_at':output_at,'command':command['command']})
    async def same_glyph(before,name):
     after=await glyph(before['output_at']);glyphs.append({'phase':name,'before':before,'after':after})
     assert before['available'] and after['available'] and after['visible'] and before['character']==after['character'] and abs(before['top']-after['top'])<2,(name,before,after)
     return after
    async def begin_hold():
     entered,release=threading.Event(),threading.Event();holds[SOURCE]=(entered,release)
     await page.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter')
     assert await asyncio.to_thread(entered.wait,10);return release
    async def release_hold(release):
     release.set();holds.clear();await page.wait_for_function("!$('history-reader-refresh').disabled&&!$('history-reader-find-submit').disabled");await frames();await frames()
    def mutate(status,code):command['status']=status;command['exitCode']=code
    def item_action(item_id):return 'evidence-item:'+__import__('urllib.parse',fromlist=['quote']).quote(json.dumps([TURN,item_id],separators=(',',':')),safe='')
    async def action(name):
     control=page.locator('[data-task-action="'+name+'"]');await control.evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
    async def evidence_page(at):
     while int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))!=at:
      current=int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))
      await action('evidence-next' if current<at else 'evidence-previous')
    async def one_item():
     assert await page.locator('.history-reader-item').count()==1
     assert await page.locator('.history-reader-item').get_attribute('data-turn-id')==TURN
     assert await page.locator('.history-reader-item').get_attribute('data-item-id')==COMMAND
    async def return_evidence():
     await page.locator('#history-reader-task-evidence-return').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
     assert await page.locator('.history-reader-task-evidence').is_visible()
    await page.locator('#browse').click();await page.wait_for_function("!$('history-search-submit').disabled");await read();before_reads=len(f.calls);await find()
    await page.locator('#history-reader-find-next').click();await frames();await quote();passage=await view();passage_glyph=await glyph()
    assert passage['turn']==TURN and passage['start']>20000 and passage['backward']
    phase='context-to-exact20-native-items'
    await target().locator('.history-reader-task-open').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames();await action('evidence-open')
    assert await page.locator('.history-reader-task-evidence-row').count()==20
    rows=await page.locator('.history-reader-task-evidence-row').evaluate_all('nodes=>nodes.map(n=>({index:Number(n.dataset.itemIndex),item:n.dataset.itemId,type:n.querySelector("h4").textContent,disabled:n.querySelector("button").disabled}))')
    assert [r['index'] for r in rows]==list(range(20)) and rows[1]['disabled'] and rows[2]['disabled'] and 'futureNativeItem' in rows[2]['type']
    assert all(r['index'] not in (1,2) or r['disabled'] for r in rows)
    assert await page.locator('#history-reader-find-scope').input_value()=='task'
    assert len(f.calls)==before_reads;await record('native-order20-bounded-evidence-types-and-unsupported-rows-retained')
    phase='fresh-native-insert-keeps-exact-focused-item-page'
    await evidence_page(20);await page.locator('[data-item-index="39"] button').focus()
    focused_key=await page.evaluate('document.activeElement.dataset.taskAction')
    inserted={'id':'inserted-native','type':'commandExecution','command':'actual supplied insertion','status':'completed','exitCode':0,'aggregatedOutput':'New exact native item'}
    f.threads[SOURCE]['turns'][41]['items'].insert(0,inserted)
    await page.locator('#history-reader-refresh').evaluate('n=>n.click()');await page.wait_for_function("!$('history-reader-refresh').disabled");await frames()
    assert await page.evaluate('document.activeElement.dataset.taskAction')==focused_key
    assert int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))==40
    f.threads[SOURCE]['turns'][41]['items'].pop(0)
    await page.locator('#history-reader-refresh').evaluate('n=>n.click()');await page.wait_for_function("!$('history-reader-refresh').disabled");await frames()
    assert await page.evaluate('document.activeElement.dataset.taskAction')==focused_key
    assert int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))==20
    before_reads=len(f.calls);await record('fresh-supplied-insert-removal-keeps-exact-item-key-page-focus-not-neighbor')
    phase='late-item-keyboard-exact-list-return'
    await evidence_page(40);assert await page.locator('.history-reader-task-evidence-row').count()==7
    # Real keyboard path from page status to the third item control.
    await page.locator('.history-reader-task-evidence').focus()
    for _ in range(3):await page.keyboard.press('Tab')
    assert await page.evaluate('document.activeElement.dataset.taskAction')==item_action(COMMAND)
    list_view=await page.evaluate('({body:$("history-reader-body").scrollTop,outer:$("history-reader").scrollTop,action:document.activeElement.dataset.taskAction})')
    await page.keyboard.press('Enter');await frames();await one_item()
    await return_evidence();assert int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))==40
    assert await page.evaluate('({body:$("history-reader-body").scrollTop,outer:$("history-reader").scrollTop,action:document.activeElement.dataset.taskAction})')==list_view
    await record('real-Tab-Enter-one-exact-late-item-and-exact-evidence-page-focus-scroll-return')
    phase='task-only-Find-fullCopy-and-quote-return'
    await find(count=1);await one_item();assert await page.locator('#history-reader-find-label').text_content()=="Find in this task’s supplied evidence"
    assert await target().locator('mark').text_content()==PHRASE;await quote();item_view=await view()
    await target().locator('.history-reader-copy-text').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await frames()
    copied=await page.evaluate('window.__copies.at(-1)');expected='Command\n'+command['command']+'\nStatus: completed\nExit: 0\n'+original_output
    assert copied==expected and len(copied)>20000
    await target().locator('.history-reader-review-evidence').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await page.wait_for_function("$('evidence-preparation').open&&!$('evidence-preparation-append').disabled")
    assert await page.locator('#evidence-preparation-quote').text_content()==PHRASE
    await page.locator('#evidence-preparation-cancel').click();await frames();v=await view();assert v['selection']==PHRASE and v['backward'] and v['start']==item_view['start']
    await return_evidence();await action(item_action(COMMAND));await one_item();v=await view();assert v['selection']==PHRASE and v['backward'] and v['start']==item_view['start']
    assert len(f.calls)==before_reads;await record('task-only-exact-UTF16-Find-full-original-Copy-and-quote-Range-return')
    phase='explicit-whole-original-Find-positive-control'
    await page.locator('#history-reader-find-scope').select_option('original');await find(count=3)
    assert await page.locator('#history-reader-find-label').text_content()=='Find in this original conversation'
    await return_evidence();assert int(await page.locator('.history-reader-task-evidence-row').first.get_attribute('data-item-index'))==40
    assert len(f.calls)==before_reads;await record('explicit-whole-original-Find-sees-all-three-tasks-and-exact-task-list-return')
    phase='held-Refresh-newer-query-detached-item-guard'
    await page.locator('[data-item-index="42"] button').evaluate('n=>window.__staleEvidence=n');release=await begin_hold();mutate('inProgress',None)
    await page.locator('#history-reader-find-query').fill('Newer unsent task evidence query');await page.evaluate('window.__staleEvidence.click()');await release_hold(release)
    assert await page.locator('.history-reader-task-evidence').is_visible() and await page.locator('#history-reader-find-query').input_value()=='Newer unsent task evidence query'
    await record('held-fresh-Refresh-keeps-evidence-page-newer-unsent-query-and-rejects-detached-item')
    phase='original-passage-exact-Range-and-Find-return'
    await page.locator('#history-reader-task-return').click();await frames();assert await page.locator('.history-reader-task-context').is_visible()
    await page.locator('#history-reader-task-passage').evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await page.wait_for_function("!$('history-reader-find-submit').disabled");await frames()
    v=await view();assert v['selection']==PHRASE and v['backward'] and v['query']==QUERY and 'Match 2 of 3' in v['status'];await same_glyph(passage_glyph,'task-evidence-original-passage-return')
    await record('exact-task-context-and-original-passage-Range-Find-output-glyph-return')
    phase='missing-exact-item-no-neighbor-substitution'
    await target().locator('.history-reader-task-open').click();await frames();await action('evidence-open');await evidence_page(40);await action(item_action(COMMAND));await one_item()
    removed=f.threads[SOURCE]['turns'][41]['items'].pop(42)
    await page.locator('#history-reader-refresh').click();await page.wait_for_function("!$('history-reader-refresh').disabled");await frames()
    assert await page.locator('.history-reader-item').count()==0 and COMMAND in await page.locator('.history-reader-task-evidence-status').text_content()
    await record('fresh-missing-exact-task-item-retains-identity-not-equal-neighbor-command')
    f.threads[SOURCE]['turns'][41]['items'].insert(42,removed);await return_evidence();await page.locator('#history-reader-refresh').click();await page.wait_for_function("!$('history-reader-refresh').disabled");await frames()
    await page.locator('[data-item-index="42"] button').evaluate('n=>window.__staleEvidenceSource=n');release=await begin_hold()
    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open");await read('native-other')
    async with page.expect_request_finished(lambda r:urlsplit(r.url).path=='/api/native/evidence-source' and parse_qs(urlsplit(r.url).query).get('thread')==[SOURCE]):release.set();holds.clear()
    await frames();await page.evaluate('window.__staleEvidenceSource.click()');await frames()
    assert 'native-other' in await page.locator('#history-reader-binding').text_content() and await page.locator('.history-reader-task-evidence').count()==0
    await record('late-closed-source-and-detached-evidence-item-cannot-replace-newer-original')
    assert {p:p.read_bytes() for p in f.protected}==f.protected
    result.update(result='PASS',browser=browser.version,checks=steps,glyphs=glyphs,B_Plan_two_queues_exact=True,SQL_exact=True,native_admissions=0,extra_navigation_native_reads=0,http=http,source_calls=f.calls,full_copy_exact=True,quote_return_backward_Range=True)
   except Exception as error:
    if context:
     try:result['page_diagnostic']=await page.evaluate("({status:$('history-reader-status').textContent,error:$('history-reader-error').textContent,query:$('history-reader-find-query').value,find:$('history-reader-find-status').textContent,reader:$('history-reader').open,refresh_disabled:$('history-reader-refresh').disabled})")
     except Exception:pass
    result.update(result='FAIL',phase=phase,checks=steps,error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc(),glyphs=glyphs,http=http,source_calls=f.calls)
    if context:await page.screenshot(path=str(evidence/f'{width}-failure.png'))
   finally:
    for _,release in holds.values():release.set()
    (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if context:await context.close()
    f.stop()
  return result
async def main():
 os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);rows=[await one(browser,w,evidence) for w in (1250,390)];await browser.close()
 summary={'result':'PASS' if all(r['result']=='PASS' for r in rows) else 'FAIL','widths':[1250,390],'groups':sum(len(r['checks']) for r in rows),'metadata':base.codex_desk.__version__,'scope':'isolated task evidence UI'}
 (evidence/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
 for r in rows:
  if r['result']=='FAIL':print(r['traceback'])
 assert summary['result']=='PASS'
if __name__=='__main__':asyncio.run(main())
