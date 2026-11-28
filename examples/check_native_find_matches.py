#!/usr/bin/env python3
"""Exact supplied-original Find occurrence overview through installed HTTP/SQLite/Chromium."""
import asyncio,copy,importlib.util,json,os,tempfile,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
SPEC=importlib.util.spec_from_file_location('find_matches_fixture',Path(__file__).with_name('check_native_task_response.py'))
base=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(base)
from codex_desk.drafts import save_draft
from codex_desk.evidence_reference import capture_reference,format_evidence_block
from playwright.async_api import async_playwright
SOURCE,CHILD='source-A/接口?+known','child-C/接口?+retained'
PHRASE='MATCH OVERVIEW Straße Café 项目 😀'
QUERY='MATCH OVERVIEW STRASSE Cafe\u0301 项目 😀'
TURN,COMMAND='A-task-41','long-A-command'
def make_source(root):
 turns=[]
 for n in range(63):
  item=base.assistant('same-item-id',PHRASE+' identical repeated source context.','final_answer')
  if n==41:
   output='\n'.join(f'Native source line {i:04d} retains Café 项目 😀'+(' '+PHRASE if i in (100,1450) else '') for i in range(1900))
   item={'id':COMMAND,'type':'commandExecution','command':'inspect source without executing','status':'completed','exitCode':0,'aggregatedOutput':output}
  turns.append({'id':f'A-task-{n:02d}','status':'completed','items':[{'id':'own-instruction','type':'userMessage','content':[{'type':'text','text':f'Inspect retained task {n:02d} source evidence.'}]},item]})
 return {'id':SOURCE,'name':'A retained many-match original','cwd':str(root/'removed-A'),'turns':turns}
async def one(browser,width,evidence):
 with tempfile.TemporaryDirectory(dir=os.environ['DESK_TEST_TEMP'],prefix=f'original-find-matches-{width}-') as tmp:
  root=Path(tmp);f=base.Fixture(root);context=None;http=[];errors=[];external=[];phase='prepare';held=[]
  f.threads[SOURCE]=make_source(root)
  childtext='Exact captured child excerpt — '+PHRASE
  f.threads[CHILD]={'id':CHILD,'name':'Child exact retained source','cwd':str(root/'removed-child'),'turns':[{'id':'child-turn','status':'completed','items':[base.assistant('child-item',childtext,'final_answer')]}]}
  projection='Codex\n'+childtext;start=projection.index(PHRASE)
  reference=capture_reference(f.threads[CHILD],native_home=f.desk.native_home_namespace(),thread_id=CHILD,turn_id='child-turn',item_id='child-item',quote_start=start,quote_end=start+len(PHRASE),text_for_item=lambda item:projection)
  f.threads[SOURCE]['turns'][41]['items'][0]['content'][0]['text']+='\n\n'+format_evidence_block(reference)
  save_draft(f.desk.store,base.ORIGINAL,'B exact unsent Plan — 保持\nDo not run source A.','plan',1)
  result={'viewport':width,'result':'PENDING','checks':[]}
  with patch.object(base.product,'_NativeReader',f.reader_type),patch.object(base.product,'Runtime',side_effect=AssertionError('Unexpected native task admission')):
   try:
    context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844});page=await context.new_page();page.set_default_timeout(15000)
    await context.add_init_script("(()=>{const later=setTimeout;window.setTimeout=function(fn,...args){if(fn?.name==='tick')return 0;return later.call(this,fn,...args);};})();")
    page.on('pageerror',lambda x:errors.append(str(x)))
    def requested(r):
     u=urlsplit(r.url);http.append({'path':u.path,'query':parse_qs(u.query),'method':r.method})
     if u.hostname!='127.0.0.1':external.append(r.url)
    page.on('request',requested)
    await page.goto(f'http://127.0.0.1:{f.server.server_port}')
    await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click();await page.wait_for_function('id=>selected===id&&!opening',arg=base.ORIGINAL)
    sql=f.sql();preparation=f.prepared();selected=await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})");opens=list(f.opens)
    async def unchanged():
     assert f.sql()==sql and f.prepared()==preparation and f.opens==opens
     assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")==selected
     assert not errors and not external and not [q for q in http if q['method']=='POST' and q['path']!='/api/open']
     assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
    async def check(name):
     nonlocal phase
     phase=name;await unchanged();result['checks'].append(name);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
    async def ready():await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await base.frames(page)
    async def read(identifier):
     await page.locator('#history-id').fill(identifier);await page.locator('#history-id').press('Enter');await ready()
    async def find(query=QUERY,count=65):
     await page.locator('#history-reader-find-query').fill(query);await page.locator('#history-reader-find-query').press('Enter')
     await page.wait_for_function('count=>$('+'"history-reader-find-status"'+').textContent.includes("Match 1 of "+count)',arg=count);await base.frames(page)
    def target():return page.locator('.history-reader-target')
    async def original():
     return await target().evaluate("n=>({turn:n.dataset.turnId,item:n.dataset.itemId,start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString(),query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent})")
    async def overview(returned=False):
     control='#history-reader-find-matches-return' if returned else '#history-reader-find-matches-show'
     await page.locator(control).evaluate('n=>n.focus({preventScroll:true})');await page.keyboard.press('Enter');await base.frames(page)
     assert await page.locator('#history-reader-find-matches').is_visible()
    async def page_to(offset):
     while int(await page.locator('.history-reader-find-match').first.get_attribute('data-match-index'))!=offset:
      current=int(await page.locator('.history-reader-find-match').first.get_attribute('data-match-index'))
      control='#history-reader-find-matches-next' if current<offset else '#history-reader-find-matches-previous'
      await page.locator(control).focus();await page.keyboard.press('Enter');await base.frames(page)
    async def long_match(late=True,keyboard=False):
     await page_to(40)
     row=page.locator(f'.history-reader-find-match[data-turn-id="{TURN}"][data-item-id="{COMMAND}"]')
     selected_row=row.last if late else row.first
     at=int(await selected_row.get_attribute('data-match-index'))
     if keyboard:
      await page.locator('#history-reader-find-matches-status').focus()
      for _ in range(at-40+1):await page.keyboard.press('Tab')
      assert await page.evaluate('document.activeElement.dataset.findAction')=='match:'+str(at)
      await page.keyboard.press('Enter')
     else:await selected_row.locator('button').click()
     await base.frames(page)
     assert await target().get_attribute('data-turn-id')==TURN and await target().get_attribute('data-item-id')==COMMAND
     assert await target().locator('mark').text_content()==PHRASE
     assert ('Occurrence '+('2' if late else '1')) in await selected_row.locator('p').text_content()
     return at
    async def select_quote():
     boxes=await target().locator('mark').evaluate('n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
     first,last=boxes[0],boxes[-1]
     await page.mouse.move(last['right']-.5,(last['top']+last['bottom'])/2);await page.mouse.down();await page.mouse.move(first['left']+.5,(first['top']+first['bottom'])/2,steps=12);await page.mouse.up()
     assert await page.evaluate('getSelection().toString()')==PHRASE
    async def hold_refresh():
     entered,release=asyncio.Event(),asyncio.Event();held.append(release)
     async def route(r):
      if parse_qs(urlsplit(r.request.url).query).get('thread')!=[SOURCE]:await r.continue_();return
      response=await r.fetch();entered.set();await release.wait();await r.fulfill(response=response)
     await page.route('**/api/native/evidence-source?*',route);await page.locator('#history-reader-refresh').click();await asyncio.wait_for(entered.wait(),15)
     return release,route
    await page.locator('#browse').click();await page.wait_for_function("!$('history-search-submit').disabled");await read(SOURCE);await find()
    before=len(f.calls);first_read=await original();await overview()
    seen=[]
    for offset,count in [(0,20),(20,20),(40,20),(60,5)]:
     await page_to(offset);rows=page.locator('.history-reader-find-match');assert await rows.count()==count
     seen+=await rows.evaluate_all('nodes=>nodes.map(n=>[n.dataset.matchIndex,n.dataset.turnId,n.dataset.itemId,n.dataset.matchStart,n.dataset.matchEnd])')
     assert await page.locator('.history-reader-item').count()<=40
    assert len({r[0] for r in seen})==65 and set(int(r[0]) for r in seen)==set(range(65)) and len(f.calls)==before
    assert await page.locator('#history-reader-find-matches-next').is_disabled()
    await page.locator('#history-reader-find-matches-close').click();await base.frames(page);assert await original()==first_read
    await check('bounded-all-exact-spans-reachable-no-source-read-and-current-passage-return')
    await overview();late_index=await long_match(keyboard=True);late=await original();assert int(late['start'])>20000 and late['scroll']>0
    await check('real-Tab-Enter-selects-second-long-Unicode-occurrence-not-equal-first')
    await select_quote();selected_long=await original();await overview(True)
    assert await page.evaluate('document.activeElement.dataset.findAction')=='match:'+str(late_index)
    await page.locator('#history-reader-find-matches-close').click();await base.frames(page);assert await original()==selected_long
    await overview(True);await long_match(late=False);assert int((await original())['start'])<int(late['start'])
    await overview(True);await long_match(late=True);await select_quote();selected_long=await original()
    await check('pointer-distinguishes-identical-within-item-occurrences-and-keeps-backward-Range')
    await overview(True);await page_to(0);await page.locator('.history-reader-find-match[data-match-index="2"] button').focus();await page.keyboard.press('Enter');await base.frames(page)
    assert await target().get_attribute('data-turn-id')=='A-task-02' and await target().get_attribute('data-item-id')=='same-item-id'
    await page.keyboard.press('F3');await base.frames(page);assert await target().get_attribute('data-turn-id')=='A-task-03'
    await check('duplicate-snippets-same-item-id-different-turn-and-immediate-F3-continue-exactly')
    await overview(True);await long_match();await select_quote();selected_long=await original()
    await target().locator('.history-reader-task-open').click();await base.frames(page);assert await page.locator('.history-reader-task-context').count()==1
    await page.locator('[data-task-action="instruction:own-instruction"]').click();await base.frames(page)
    await page.locator('.history-reader-read-reference').click();await ready();assert CHILD in await page.locator('#history-reader-binding').text_content()
    assert await page.locator('#history-reader-saved-evidence-quote').text_content()==PHRASE
    await page.locator('#history-reader-back').click();await ready();assert SOURCE in await page.locator('#history-reader-binding').text_content()
    await page.locator('#history-reader-task-return').click();await base.frames(page)
    await page.locator('#history-reader-task-passage').click();await base.frames(page);assert await original()==selected_long
    await overview(True);assert int(await page.locator('.history-reader-find-match').first.get_attribute('data-match-index'))==40
    await page.locator('#history-reader-find-matches-close').click();await base.frames(page)
    await check('containing-task-full-instruction-embedded-reference-child-and-exact-original-matches-return')
    await target().locator('.history-reader-review-evidence').click();await page.wait_for_function("$('evidence-preparation').open")
    assert await page.locator('#evidence-preparation-quote').text_content()==PHRASE
    await page.locator('#evidence-preparation-cancel').click();await base.frames(page);assert await original()==selected_long
    await check('reviewed-quote-cancel-keeps-existing-B-Plan-and-exact-match-Range')
    await overview(True);f.failures.add(SOURCE);await page.locator('#history-reader-refresh').click();await page.wait_for_function("$('history-reader-status').textContent.startsWith('Refresh failed.')&&!$('history-reader-refresh').disabled")
    assert await page.locator('#history-reader-find-matches').is_visible() and await page.locator('.history-reader-find-match').count()==20
    f.failures.clear();f.threads[SOURCE]['turns'].append({'id':'A-added-task','status':'completed','items':[base.assistant('A-added-item',PHRASE+' refreshed occurrence','final_answer')]})
    await page.locator('#history-reader-refresh').click();await page.wait_for_function("$('history-reader-status').textContent.startsWith('Original refreshed.')&&!$('history-reader-refresh').disabled")
    await page.wait_for_function("$('history-reader-find-matches-status').textContent.includes('of 66')");assert await page.locator('#history-reader-find-matches').is_visible()
    await page_to(60);assert await page.locator('.history-reader-find-match').count()==6
    await check('failed-Refresh-keeps-overview-success-rebuilds-current-submitted-exact-index')
    await page_to(40);await long_match();await overview(True);await page.locator('.history-reader-find-match button').first.evaluate('n=>window.__staleMatchButton=n')
    release,route=await hold_refresh();await page.locator('#history-reader-find-query').fill('Newer deliberately unsent query')
    await page.evaluate('window.__staleMatchButton.click()');release.set();await page.wait_for_function("!$('history-reader-refresh').disabled");await page.unroute('**/api/native/evidence-source?*',route)
    assert await page.locator('#history-reader-find-query').input_value()=='Newer deliberately unsent query' and await page.locator('#history-reader-find-matches').is_hidden()
    assert await page.locator('#history-reader-find-matches-show').is_disabled()
    await check('held-Refresh-and-detached-result-cannot-revive-old-submitted-query')
    await page.evaluate("()=>{window.__spans=DeskHistoryFind.spansAsync;window.__holdFind=true;DeskHistoryFind.spansAsync=async(...args)=>{if(window.__holdFind){window.__holdFind=false;await new Promise(r=>window.__releaseFind=r);}return window.__spans(...args);};}")
    await page.locator('#history-reader-find-query').fill(QUERY);await page.locator('#history-reader-find-form').evaluate('n=>n.requestSubmit()');await page.wait_for_function('!!window.__releaseFind')
    await page.locator('#history-reader-find-query').fill('Newer absent phrase');await page.locator('#history-reader-find-form').evaluate('n=>n.requestSubmit()');await page.wait_for_function("$('history-reader-find-status').textContent.startsWith('No matches')")
    await page.evaluate('window.__releaseFind()');await page.wait_for_timeout(100);await base.frames(page)
    assert await page.locator('#history-reader-find-query').input_value()=='Newer absent phrase' and await page.locator('#history-reader-find-matches').is_hidden()
    await page.evaluate('()=>{DeskHistoryFind.spansAsync=window.__spans;}');await check('held-Find-work-rejects-newer-query-generation')
    await find(count=66);await overview();await page.locator('.history-reader-find-match button').first.evaluate('n=>window.__staleSourceButton=n')
    release,route=await hold_refresh();await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
    await read(CHILD);await find(count=1);await overview();release.set();await page.wait_for_timeout(100);await page.unroute('**/api/native/evidence-source?*',route)
    await page.evaluate('window.__staleSourceButton.click()');await base.frames(page)
    assert CHILD in await page.locator('#history-reader-binding').text_content() and await page.locator('.history-reader-find-match').count()==1
    assert await page.locator('.history-reader-find-match').get_attribute('data-turn-id')=='child-turn'
    await check('late-closed-A-overview-cannot-replace-newer-child-source-or-preparation')
    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
    assert await page.locator('#history-reader-find-matches').is_hidden() and await page.locator('#history-reader-find-matches-return').is_hidden()
    await unchanged();assert {p:p.read_bytes() for p in f.protected}==f.protected
    result.update(result='PASS',browser=browser.version,checks_count=len(result['checks']),B_Plan_two_queues_exact=True,sql_exact=True,native_admissions=0,source_calls=f.calls,http=http)
   except Exception as error:
    result.update(result='FAIL',phase=phase,error_type=type(error).__name__,error=str(error),traceback=traceback.format_exc())
    if context:await page.screenshot(path=str(evidence/f'{width}-failure.png'))
   finally:
    for release in held:release.set()
    (evidence/f'{width}-receipt.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    if context:await context.close()
    f.stop()
  return result
async def main():
 os.umask(0o077);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);rows=[await one(browser,w,evidence) for w in (1250,390)];await browser.close()
 summary={'result':'PASS' if all(r['result']=='PASS' for r in rows) else 'FAIL','widths':[1250,390],'groups':sum(len(r['checks']) for r in rows),'version':base.codex_desk.__version__}
 (evidence/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
 for r in rows:
  if r['result']!='PASS':print(r['traceback'])
 assert summary['result']=='PASS'
if __name__=='__main__':asyncio.run(main())
