"""Remembered captured requests: actual HTTP/Runtime, scoped pages, original/Return.
DESK_USE_INSTALLED=1 checks delivered wheel without importing source package.
"""
import asyncio,copy,json,os,sys,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs,urlsplit
SOURCE=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(SOURCE/'tests'))
import browser_prepared_request_original as o
c=o.c
Q='Captured exact'

async def recall(page,query=Q):
    if not await page.locator('#recall').evaluate('n=>n.open'):
        await page.locator('#search-saved-content').evaluate('n=>n.click()')
    await page.locator('#recall-query').fill(query)
    await page.locator('#recall-form').evaluate('n=>n.requestSubmit()')
    await page.wait_for_function("$('recall-results').getAttribute('aria-busy')==='false'")

async def open_hit(page,f):
    hit=page.locator(f'.recall-result[data-kind="turn_request"][data-session="{f.original}"][data-token="{f.captured["token"]}"] .recall-open')
    await hit.focus();await page.keyboard.press('Enter')
    await page.wait_for_function("$('preparation-request').open && !$('preparation-request-status').textContent.startsWith('Reading')")
    return hit

async def results_snapshot(page):
    return await page.evaluate("""()=>({query:$('recall-query').value,project:$('recall-project').value,archived:$('recall-archived').checked,
        summary:$('recall-summary').textContent,ids:[...$('recall-results').children].map(n=>[n.dataset.session,n.dataset.kind,n.dataset.item,n.dataset.token]),
        scroll:$('recall').scrollTop,resultsScroll:$('recall-results').scrollTop,previous:$('recall-previous').disabled,next:$('recall-next').disabled})""")

async def acceptance(browser,width,mode,outcome):
    f=o.Fixture();f.start(mode);context=page=None
    result={'width':width,'mode':mode,'outcome':outcome,'passed':False,'checks':[]}
    try:
      with patch.object(c.service,'save_draft',side_effect=f.controlled_save):
        context,page,errors,requests,external=await c.make_page(browser,f,width)
        main=await c.prepare_main(page,f)
        # A separate Prepared editor remains retained through recall, not its owner.
        await c.overview(page)
        await page.locator(f'.preparation-session[data-session="{c.SELECTED}"] button[data-control="review"]').click()
        await page.locator('#preparation-text').fill(c.MODAL_EDIT*30)
        await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(7,35,'backward');n.scrollTop=61;}")
        await page.locator('#preparation-close').evaluate('n=>n.click()')
        modal=await o.modal_snapshot(page)
        await page.locator('#prompt').evaluate("n=>{n.focus();n.setSelectionRange(9,42,'backward');n.scrollTop=184;}")
        main=await c.snapshot_main(page)
        # Real cache corpus large enough for second-page identity/Return acceptance.
        thread={'id':'native-later','cwd':str(f.other_project),'name':'Earlier matched notes','turns':[
          {'id':'notes','status':'completed','items':[{'id':f'note-{i}','type':'agentMessage','text':Q+' earlier retained note '+str(i)} for i in range(35)]}]}
        f.desk.store.recall_snapshot(c.SELECTED,thread)
        # Keep captured request last by its actual session update order.
        f.desk.store.db.execute('UPDATE sessions SET updated=1 WHERE id=?',(f.original,));f.desk.store.db.commit()
        boundary=len(requests);writes=f.desk.store.db.total_changes
        await recall(page)
        assert 'Showing 30 of 36' in await page.locator('#recall-summary').inner_text()
        await page.locator('#recall-next').click()
        await page.wait_for_function("$('recall-results').getAttribute('aria-busy')==='false' && $('recall-summary').textContent.includes('Items 31–36')")
        await page.locator('#recall').evaluate('n=>n.scrollTop=143')
        hit=page.locator(f'.recall-result[data-kind="turn_request"] .recall-open');await hit.focus()
        origin=await results_snapshot(page);hit=await open_hit(page,f)
        assert not await page.locator('#preparation').evaluate('n=>n.open')
        await c.exact_view(page,f)
        assert 'Return to results' in await page.locator('#preparation-request-return').inner_text()
        assert all(r['method']=='GET' for r in requests[boundary:]) and f.desk.store.db.total_changes==writes
        await c.unchanged_main(page,f,main);assert await o.modal_snapshot(page)==modal
        result['checks'].append('second-page captured request exact UUID/body/Work-Plan with separate main+Prepared editor; GET-only')
        await o.read_original(page)
        assert o.ORIGINAL_TEXT in await page.locator('#history-reader-body').text_content()
        assert o.history_gets(requests)[-1]['query']=={'id':['native-original']}
        await o.back_to_request(page)
        await page.locator('#preparation-request-return').focus();await page.keyboard.press('Enter')
        await page.wait_for_function("!$('preparation-request').open")
        assert await hit.evaluate('n=>n===document.activeElement')
        assert await results_snapshot(page)==origin, {'before':origin,'after':await results_snapshot(page)}
        await c.unchanged_main(page,f,main);assert await o.modal_snapshot(page)==modal
        result['checks'].append('captured original reader Return then keyboard Return exact submitted page/result/focus/scroll')
        await page.screenshot(path=str(c.OUT/f'captured-recall-return-{width}.png'))
        # Late authoritative GET after Return cannot reopen or steal another editor.
        gate=f.gate(session=f.original)
        await hit.evaluate('n=>n.click()');assert await asyncio.to_thread(gate['entered'].wait,10)
        await page.locator('#preparation-request-return').click()
        await page.locator('#recall-close').click()
        await page.locator('#prompt').evaluate("n=>{n.focus();n.setSelectionRange(9,42,'backward');n.scrollTop=184;}")
        async with page.expect_event('requestfinished',predicate=lambda r:urlsplit(r.url).path=='/api/turn/request') as event:
            gate['release'].set()
        await event.value;await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
        assert not await page.locator('#preparation-request').evaluate('n=>n.open')
        assert await page.evaluate('document.activeElement.id')=='prompt'
        await c.unchanged_main(page,f,main)
        result['checks'].append('late request GET after Return/Close cannot steal main editor or reopen viewers')
        # Reopen retains same submitted page; explicit resolution changes no preparation.
        await page.locator('#search-saved-content').evaluate('n=>n.click()')
        hit=await open_hit(page,f);await c.exact_view(page,f)
        before=copy.deepcopy({'draft':c.load_draft(f.desk.store,f.original),'queue':c.followup_snapshot(f.desk.store,f.original)})
        resolve_boundary=len(requests)
        await page.locator('#preparation-request-'+outcome).click()
        await page.wait_for_function("!$('preparation-request-refresh').disabled && $('preparation-request-status').textContent.toLowerCase().includes('"+outcome+"')")
        await page.locator('#preparation-request-return').click()
        assert await hit.count()==1
        await page.locator('#recall-form').evaluate('n=>n.requestSubmit()')
        await page.wait_for_function("$('recall-results').getAttribute('aria-busy')==='false' && !$('recall-results').querySelector('[data-kind=turn_request]')")
        assert 'Items 31–35' in await page.locator('#recall-summary').inner_text()
        posts=[r for r in requests[resolve_boundary:] if r['method']=='POST']
        assert len(posts)==1 and posts[0]['path']=='/api/turn/resolve' and posts[0]['body']==dict(session=f.original,token=f.captured['token'],outcome=outcome)
        assert before=={'draft':c.load_draft(f.desk.store,f.original),'queue':c.followup_snapshot(f.desk.store,f.original)}
        await c.unchanged_main(page,f,main);assert await o.modal_snapshot(page)==modal
        await page.locator('#recall-close').click()
        await page.wait_for_function("!$('recall').open")
        assert await page.evaluate('document.activeElement.id')=='prompt'
        await c.unchanged_main(page,f,main)
        assert not errors and not external and len(f.requests)==1
        result['checks'].append('manual accepted/rejected exact UUID; same-query Search retains offset/drops only request; no starts/editor/queue changes')
        result.update(passed=True,package=str(c.PACKAGE),version=c.codex_desk.__version__,http=requests,native_calls=f.catalog_calls,native_starts=len(f.requests),errors=errors,external=external)
    except Exception as e:
      result.update(error=str(e),traceback=traceback.format_exc())
    finally:
      if context:await context.close()
      f.finish()
    print(json.dumps({k:v for k,v in result.items() if k not in ('http','native_calls','traceback')}),flush=True)
    return result

async def main():
    c.OUT.mkdir(parents=True,exist_ok=True)
    async with c.async_playwright() as p:
      browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
      try:results=[await acceptance(browser,1250,'native','rejected'),await acceptance(browser,390,'plan','accepted')]
      finally:await browser.close()
    passed=all(r['passed'] for r in results)
    (c.OUT/'result.json').write_text(json.dumps(dict(passed=passed,results=results),indent=2,ensure_ascii=False)+'\n')
    if not passed:
      for r in results:
        if not r['passed']:print(r.get('traceback',''))
      raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
