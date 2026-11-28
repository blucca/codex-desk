"""Actual isolated original-reader selection and clipboard artifact acceptance."""
import argparse,asyncio,copy,json,os,sys,tempfile
from pathlib import Path
from unittest.mock import patch

parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,required=True);parser.add_argument('--evidence',type=Path,required=True);parser.add_argument('--before',action='store_true');a=parser.parse_args()
a.source=a.source.resolve();os.environ['DESK_SOURCE']=str(a.source)
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(a.source))
sys.path.insert(0,str(a.source/'examples'))
from check_native_task_response import Fixture,product,PARENT,ORIGINAL,OTHER,frames
from playwright.async_api import async_playwright
from codex_desk.evidence_reference import format_evidence_block,parse_evidence_blocks,resolve_reference
QUOTE='Cafe\u0301🙂 项目 check'
OUTPUT='Output beginning\n'+QUOTE+'\n'+('stable numbered line for source identity 🌱\n'*760)+QUOTE+'\nOutput end'
ITEM='copy-command';TURN='copy-turn'

async def run(browser,width,with_b):
 record={'width':width,'with_B':with_b,'passed':False,'checks':[]};context=None
 root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
 with tempfile.TemporaryDirectory(dir=root,prefix='copy-artifact-') as tmp:
  f=Fixture(Path(tmp));f.threads[PARENT]={'id':PARENT,'cwd':'/removed/copy-project','name':'Copied native evidence',
   'turns':[{'id':TURN,'status':'inProgress','items':[{'id':ITEM,'type':'commandExecution','command':'inspect 🌱 original','status':'inProgress','aggregatedOutput':OUTPUT},
   {'id':'other-equal-item','type':'agentMessage','text':QUOTE,'phase':'final_answer'}]}]}
  errors=[];requests=[]
  try:
   with patch.object(product,'_NativeReader',f.reader_type),patch.object(product,'Runtime',side_effect=AssertionError('Task runtime forbidden')):
    context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844})
    await context.add_init_script("""Object.defineProperty(navigator,'clipboard',{configurable:true,value:{async writeText(text){(window.__artifactCopies ||= []).push(text);if(window.__artifactCopyHold)await window.__artifactCopyHold}}});""")
    page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:requests.append({'method':r.method,'url':r.url}))
    await page.goto(f'http://127.0.0.1:{f.server.server_port}');await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
    if with_b:
     await page.locator(f'.session-row[data-session="{ORIGINAL}"] .session').click();await page.wait_for_function('id=>selected===id&&!opening',arg=ORIGINAL)
     await page.get_by_role('button',name='Browse existing Codex sessions',exact=True).click()
    else:
     assert not await page.evaluate('selected');await page.locator('#home-browse').click()
    await page.locator('#history-id').fill(PARENT);await page.locator('#history-id-read').click()
    await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
    await page.locator('#history-reader-find-query').fill(QUOTE);await page.locator('#history-reader-find-query').press('Enter');await page.wait_for_function("!$('history-reader-find-submit').disabled&&!$('history-reader-find-next').disabled");await frames(page)
    await page.keyboard.press('F3');await frames(page)
    target=page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
    await target.wait_for();pre=target.locator('.history-reader-text')
    assert await target.evaluate('n=>n.open');assert await target.evaluate('n=>+n.dataset.windowStart')>10000
    state=f.sql();prepared=f.prepared();opens=len(f.opens);native=len(f.calls);http_start=len(requests)
    before_storage=await page.evaluate('JSON.stringify({...localStorage})')

    async def select_keyboard():
     # A genuine pointer Range is carried into real Tab/Enter keyboard activation.
     await select_pointer()

    async def select_pointer():
     mark=pre.locator('mark');await mark.scroll_into_view_if_needed();box=await mark.bounding_box();assert box
     await page.mouse.move(box['x']+0.5,box['y']+box['height']/2);await page.mouse.down()
     await page.mouse.move(box['x']+box['width']-0.5,box['y']+box['height']/2,steps=12);await page.mouse.up();await frames(page)
     assert await page.evaluate('getSelection().toString()')==QUOTE,await page.evaluate('getSelection().toString()')

    async def snapshot():
     return await target.evaluate("""n=>{const p=n.querySelector('.history-reader-text'),s=getSelection(),r=s.rangeCount?s.getRangeAt(0):null;return {selected:typeof selected==='undefined'?null:selected,find:document.querySelector('#history-reader-find-query').value,findStatus:document.querySelector('#history-reader-find-status').textContent,window:n.dataset.windowStart,text:s.toString(),start:r?.startOffset,end:r?.endOffset,preScroll:p.scrollTop,preLeft:p.scrollLeft,bodyScroll:document.querySelector('#history-reader-body').scrollTop,outer:document.querySelector('#history-reader').scrollTop,glyphTop:r?.getBoundingClientRect().top}}""")

    await select_keyboard()
    if a.before:
     assert await target.locator('.history-reader-copy-excerpt').count()==0
     await target.locator('.history-reader-copy-text').click();await target.locator('.history-reader-copy-source').click()
     copies=await page.evaluate('window.__artifactCopies');assert len(copies)==2 and copies[0]!=copies[1]
     assert OUTPUT in copies[0] and 'Thread: '+PARENT in copies[1] and QUOTE not in copies[1]
     if not with_b:
      await select_keyboard();await target.locator('.history-reader-review-evidence').click()
      assert not await page.locator('#evidence-review').count() or not await page.locator('#evidence-review').evaluate('n=>n.open')
     record['checks'].append('two-current-clipboard-writes-overwrite-no-single-quote-source-artifact')
     record['separate_clipboard_writes']=2
    else:
     button=target.locator('.history-reader-copy-excerpt');assert await button.count()==1
     # Real Tab navigation retains the source range while reaching the new action.
     saved=await snapshot()
     for _ in range(18):
      await page.keyboard.press('Tab')
      if await button.evaluate('n=>n===document.activeElement'):break
     assert await button.evaluate('n=>n===document.activeElement')
     await page.keyboard.press('Enter');await page.wait_for_function("document.querySelector('.history-reader-copy-status').textContent==='Excerpt with source copied.'")
     await frames(page);after=await snapshot();record['keyboard_before']=saved;record['keyboard_after']=after
     assert after['text']==QUOTE and after['window']==saved['window'] and after['find']==saved['find'] and after['findStatus']==saved['findStatus'] and after['selected']==saved['selected']
     assert abs(after['preScroll']-saved['preScroll'])<=1 and abs(after['glyphTop']-saved['glyphTop'])<=1,(saved,after)
     assert after['start']==saved['start'] and after['end']==saved['end']
     copies=await page.evaluate('window.__artifactCopies');assert len(copies)==1
     parsed=await page.evaluate('DeskEvidencePreparation.parse(window.__artifactCopies[0])')
     assert len(parsed)==1;ref=parsed[0]['reference'];assert ref['quote']==QUOTE
     assert (ref['thread_id'],ref['turn_id'],ref['item_id'])==(PARENT,TURN,ITEM)
     assert ref['projection']=='history-reader-command-output/v1' and ref['quote_start']==OUTPUT.rindex(QUOTE)
     assert format_evidence_block(ref)==copies[0] and parse_evidence_blocks(copies[0])[0]['reference']==ref
     fresh=copy.deepcopy(f.threads[PARENT]);fresh['turns'][0]['status']='failed';fresh['turns'][0]['items'][0].update(status='completed',exitCode=1,command='completed original header changed')
     resolution=await page.evaluate('args=>DeskEvidencePreparation.resolve(args.reference,args.reference.native_home,args.fresh,DeskHistoryReader.textForItem)',{'reference':ref,'fresh':fresh})
     assert resolution['available'] and resolution['state_changed']
     record['artifact_reference']=ref;record['fresh_completed_resolution']=resolution;record['checks'].append('real-keyboard-range-Tab-Enter-single-output-relative-source-artifact')
     # Pointer copy is a separate user action; clipboard holds one complete artifact each time.
     await select_pointer();before=await snapshot();await button.click();await frames(page);after=await snapshot()
     assert after['text']==QUOTE and after['window']==before['window'] and after['find']==before['find']
     copies=await page.evaluate('window.__artifactCopies');assert len(copies)==2 and copies[0]==copies[1]
     record['checks'].append('real-pointer-range-one-complete-artifact-per-click')
     # A pending namespace read belongs to this reader; closing it suppresses the write.
     assert await page.evaluate('JSON.stringify({...localStorage})')==before_storage
     await select_keyboard();gate=asyncio.Event()
     async def held_home(route):
      await gate.wait();await route.continue_()
     await page.route('**/api/native/home',held_home)
     await button.click();await frames(page);old_copies=len(copies)
     await page.locator('#history-reader-close').click();gate.set();await page.wait_for_timeout(100);await page.unroute('**/api/native/home')
     # Unit owner tests cover explicit held reply release; closing here cancels actual UI owner.
     assert len(await page.evaluate('window.__artifactCopies'))==old_copies
     record['checks'].append('actual-reader-close-during-namespace-pending-keeps-clipboard')
    assert f.sql()==state and f.prepared()==prepared and len(f.opens)==opens
    assert f.desk.runtimes=={} and f.desk.admissions=={} and not errors
    assert len(f.calls)==native, (native,f.calls)
    if a.before:assert await page.evaluate('JSON.stringify({...localStorage})')==before_storage
    assert not [r for r in requests[http_start:] if r['method']=='POST']
    record.update(passed=True,extra_native_reads=0,storage_writes=0,draft_writes=0,task_admissions=0,selected_B_unchanged=True,two_ordered_queues_exact=True,sql_all_tables_rows_exact=True,errors=errors)
    await page.screenshot(path=str(a.evidence/f'{width}-B{int(with_b)}.png'))
  except Exception as e:
   import traceback
   record.update(error=str(e),traceback=traceback.format_exc(),errors=errors)
   if context:
    try:await page.screenshot(path=str(a.evidence/f'{width}-B{int(with_b)}-failure.png'))
    except Exception:pass
   raise
  finally:
   (a.evidence/f'{width}-B{int(with_b)}.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
   if context:await context.close()
   f.stop()
 return record

async def main():
 a.evidence.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:records=[await run(browser,width,b) for width in (1250,390) for b in (False,True)]
  finally:await browser.close()
 (a.evidence/'summary.json').write_text(json.dumps({'result':'PASS','before':a.before,'browser':browser.version,'contexts':4,'records':records},ensure_ascii=False,indent=2)+'\n')
 print('actual copy artifact browser PASS',flush=True)
asyncio.run(main())
