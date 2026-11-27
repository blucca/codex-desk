#!/usr/bin/env python3
"""Reproduce actual selected native output following underneath Prepared reading."""
import asyncio
import copy
import json
import os
from unittest.mock import patch
import browser_prepared_request as c

async def check(browser,width,surface):
    f=c.Fixture();f.start('plan');context=None;page=None
    result={'width':width,'surface':surface,'reproduced':False,'passed':False}
    try:
        with patch.object(c.service,'save_draft',side_effect=f.controlled_save):
            context,page,errors,http,external=await c.make_page(browser,f,width)
            await c.prepare_main(page,f)
            live=copy.copy(f.runtime);live.id=c.SELECTED;live.closing=False
            def emit(item,text):
                with live.lifecycle_lock:
                    live._message({'method':'item/completed','params':{'threadId':'native-later','turnId':'live-selected-turn','item':{'id':item,'type':'agentMessage','text':text}}})
            with live.lifecycle_lock:
                live._message({'method':'turn/started','params':{'threadId':'native-later','turn':{'id':'live-selected-turn','status':'inProgress'}}})
            emit('initial-live-output','Existing selected native activity.\n'*45)
            await page.evaluate('pollActivity()')
            await page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            await page.evaluate('goLatest()')
            assert await page.evaluate('nearLatest()')
            await c.overview(page)
            if surface=='request':
                await c.open_review(page,f.original)
                await c.exact_view(page,f)
                await page.locator('#preparation-request-captured-text').evaluate("""n=>{
                    n.focus({preventScroll:true});n.scrollTop=190;
                    const r=document.createRange();r.setStart(n.firstChild,10);r.setEnd(n.firstChild,40);
                    const s=getSelection();s.removeAllRanges();s.addRange(r);
                }""")
            else:
                await page.locator(f'.preparation-session[data-session="{c.SELECTED}"] button[data-control="review"]').click()
                await page.locator('#preparation-text').fill(c.MODAL_EDIT+'\nLocal Prepared Plan. '*80)
                await page.locator('#preparation-mode').select_option('plan')
                await page.locator('#preparation-text').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,44,'backward');n.scrollTop=90;}")
            async def snapshot():
                return await page.evaluate("""s=>({windowScroll:scrollY,height:document.documentElement.scrollHeight,nearLatest:nearLatest(),
                    mainText:$('prompt').value,mainMode:$('turn-mode').value,mainCaret:[$('prompt').selectionStart,$('prompt').selectionEnd,$('prompt').selectionDirection],
                    mainScroll:$('prompt').scrollTop,focus:document.activeElement.id,
                    dialogScroll:$(s==='request'?'preparation-request':'preparation').scrollTop,
                    textScroll:$(s==='request'?'preparation-request-captured-text':'preparation-text').scrollTop,
                    localText:s==='request'?getSelection().toString():$('preparation-text').value,
                    localCaret:s==='request'?null:[$('preparation-text').selectionStart,$('preparation-text').selectionEnd,$('preparation-text').selectionDirection],
                    disclosure:$('preparation-request-captured').open,
                    latestUpdates})""",surface)
            before=await snapshot();assert before['nearLatest'],before
            emit('additional-live-output','Additional actual native selected output while another request is read.\n'*95)
            await page.evaluate('pollActivity()')
            await page.evaluate('() => new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            after=await snapshot()
            assert before['height'] < after['height']
            for key in ('mainText','mainMode','mainCaret','mainScroll','focus','dialogScroll','textScroll','localText','localCaret','disclosure'):
                assert before[key]==after[key],key
            assert f.other_before=={'draft':c.load_draft(f.desk.store,c.SELECTED),'queues':c.followup_snapshot(f.desk.store,c.SELECTED)}
            assert len(f.requests)==1 and not errors and not external
            result.update(reproduced=before['windowScroll']!=after['windowScroll'],passed=before['windowScroll']==after['windowScroll'] and after['latestUpdates']>0,before=before,after=after,
                delta_scroll=after['windowScroll']-before['windowScroll'],height_growth=after['height']-before['height'],http=http,
                actual_native_events=True,native_starts=1,additional_native_starts=0,javascriptErrors=errors)
            await page.screenshot(path=str(c.OUT/f'{width}-{surface}-live-output.png'))
            if surface=='request':await page.locator('#preparation-request-return').click()
            await page.locator('#preparation-close').evaluate('n=>n.click()')
            await page.wait_for_function("!$('preparation').open")
            result['returned_window_scroll']=await page.evaluate('scrollY')
            result['returned_main_caret']=await page.locator('#prompt').evaluate('n=>[n.selectionStart,n.selectionEnd,n.selectionDirection]')
    except Exception as e:
        result.update(error=repr(e),traceback=c.traceback.format_exc())
    finally:
        f.draft_release.set()
        if context:await context.close()
        f.finish()
    return result

async def main():
    async with c.async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        results=[]
        for width in (1250,390):
            for surface in ('request','editor'):
                r=await check(browser,width,surface);results.append(r)
                print(json.dumps({k:r.get(k) for k in ('width','surface','passed','reproduced','delta_scroll','height_growth','returned_window_scroll','error')}),flush=True)
        await browser.close()
    (c.OUT/'live-output-scroll.json').write_text(json.dumps(results,indent=2,ensure_ascii=False)+'\n')
    if c.os.environ.get('DESK_EXPECT_SCROLL_SHIFT') == '1':
        assert all(r['reproduced'] and not r.get('error') for r in results)
    else:
        assert all(r['passed'] and not r.get('error') for r in results), 'Selected live output scrolled underneath an independent Prepared reader'

if __name__=='__main__':asyncio.run(main())
