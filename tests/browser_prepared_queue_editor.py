"""Prepared queue organization: real Runtime/HTTP/Chromium."""
import asyncio,json,os,sys,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
SOURCE=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(SOURCE/'tests'))
import browser_prepared_request_original as o
c=o.c
async def draft_snapshot(page):
 value=await o.modal_snapshot(page);value.pop('outerScroll');return value
async def check(browser,width):
 f=c.Fixture();f.start('plan',prepared=True);c.add_followup(f.desk.store,f.original,'Second queued Plan stays exact  ','plan');context=None
 result={'width':width,'passed':False,'checks':[]}
 try:
  with patch.object(c.service,'save_draft',side_effect=f.controlled_save):
   context,page,errors,requests,external=await c.make_page(browser,f,width)
   main=await c.prepare_main(page,f)
   await c.overview(page)
   await page.locator(f'.preparation-session[data-session="{f.original}"] button[data-control="review"]').click()
   await page.locator('#preparation-text').fill(c.MODAL_EDIT*20)
   await page.locator('#preparation-mode').select_option('plan')
   await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(7,35,'backward');n.scrollTop=55;}")
   modal=await draft_snapshot(page)
   entries=c.followup_snapshot(f.desk.store,f.original)['entries'];first=entries[0]
   box=page.locator(f'.preparation-followup[data-followup="{first["id"]}"]')
   await box.locator('[data-control="queue-down"]').click()
   await page.wait_for_function("!document.querySelector('[data-control=queue-clear]').disabled")
   assert c.followup_snapshot(f.desk.store,f.original)['entries'][-1]['id']==first['id']
   await box.locator('[data-control="queue-up"]').click()
   await page.wait_for_function("!document.querySelector('[data-control=queue-clear]').disabled")
   assert c.followup_snapshot(f.desk.store,f.original)['entries'][0]['id']==first['id']
   result['checks'].append('actual Move down/up exact captured order round-trip with no native Open or draft changes')
   await box.locator('[data-control="queue-edit"]').click()
   text=box.locator('textarea');mode=box.locator('select')
   await text.fill('Exact prepared correction 保留  \n'+('line for scrolling\n'*60))
   await mode.select_option('plan')
   await text.evaluate("n=>{n.focus();n.setSelectionRange(3,17,'backward');n.scrollTop=70;}")
   before=await text.evaluate('n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})')
   await page.locator('#preparation-refresh').evaluate('n=>n.click()')
   await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
   assert await text.evaluate('n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})')==before, {'before':before,'after':await text.evaluate('n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})')}
   await c.unchanged_main(page,f,main);assert await draft_snapshot(page)==modal
   result['checks'].append('queue edit exact text/mode/caret/scroll survives aggregate Refresh with main+independent Prepared draft exact')
   boundary=len(requests);gate=f.gate('/api/followups/edit',method='POST')
   await box.locator('[data-control="queue-save"]').evaluate('n=>n.click()')
   assert await asyncio.to_thread(gate['entered'].wait,10)
   await text.fill('Newer unsent queue correction 保留  ');await mode.select_option('native')
   async with page.expect_event('requestfinished',predicate=lambda r:urlsplit(r.url).path=='/api/followups/edit') as pending:
    gate['release'].set()
   await pending.value
   await page.wait_for_function("!document.querySelector('[data-control=queue-save]').disabled")
   assert await text.input_value()=='Newer unsent queue correction 保留  '
   assert c.followup_snapshot(f.desk.store,f.original)['entries'][0]['text']==before['text']
   await box.locator('[data-control="queue-save"]').click()
   await page.wait_for_function("!document.querySelector('[data-control=queue-save]').disabled")
   saved=c.followup_snapshot(f.desk.store,f.original)['entries'][0]
   assert saved['text']=='Newer unsent queue correction 保留  ' and saved['mode']=='native'
   posts=[r for r in requests[boundary:] if r['method']=='POST']
   assert len(posts)==2 and all(r['path']=='/api/followups/edit' and r['body']['session']==f.original and r['body']['id']==first['id'] for r in posts)
   await c.unchanged_main(page,f,main);assert await draft_snapshot(page)==modal
   result['checks'].append('held actual local save preserves live newer unsent text/mode; second explicit save uses advanced revision, no draft/native writes')
   # A removed queue row must not discard its independent unsaved edit.
   await text.fill('Locally retained after other-window removal  ')
   await box.locator('[data-control="queue-remove"]').click()
   await page.wait_for_function("!document.querySelector('[data-control=queue-clear]').disabled")
   remaining=c.followup_snapshot(f.desk.store,f.original)['entries'];assert len(remaining)==1 and remaining[0]['id']!=first['id']
   assert await text.input_value()=='Locally retained after other-window removal  '
   await page.locator('[data-control="queue-clear"]').click()
   await page.wait_for_function("!document.querySelector('[data-control=queue-clear]')")
   assert not c.followup_snapshot(f.desk.store,f.original)['entries']
   await page.locator('#preparation-refresh').click();await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
   assert await text.input_value()=='Locally retained after other-window removal  '
   assert await text.is_disabled() and await box.locator('[data-control="queue-save"]').is_disabled()
   await box.locator('[data-control="queue-cancel"]').click();assert await box.count()==0
   await c.unchanged_main(page,f,main);assert await draft_snapshot(page)==modal
   assert not errors and not external and len(f.requests)==1
   result['checks'].append('actual Remove exact saved revision then Clear exact remaining order keep local removed edit until Cancel; selected work untouched')
   result.update(passed=True,native_starts=len(f.requests),extra_native_starts=0,http=requests,errors=errors,external=external)
   await page.screenshot(path=str(c.OUT/f'prepared-queue-{width}.png'))
 except Exception as e:result.update(error=str(e),traceback=traceback.format_exc())
 finally:
  if context:await context.close()
  f.finish()
 print(json.dumps({k:v for k,v in result.items() if k not in ('http','traceback')}),flush=True);return result
async def main():
 async with c.async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:r=[await check(browser,1250),await check(browser,390)]
  finally:await browser.close()
 c.OUT.mkdir(parents=True,exist_ok=True);(c.OUT/'result.json').write_text(json.dumps(dict(passed=all(x['passed'] for x in r),results=r),indent=2,ensure_ascii=False)+'\n')
 if not all(x['passed'] for x in r):
  for x in r:
   if not x['passed']:print(x.get('traceback',''))
  raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
