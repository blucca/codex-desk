"""Inspect a Prepared request's captured native original without leaving another task."""
import asyncio
import json
import os
from pathlib import Path
import sys
import traceback
import uuid
from urllib.parse import parse_qs,urlsplit
from unittest.mock import patch

SOURCE=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0,str(SOURCE/'tests'))
import browser_prepared_request as c
from codex_desk.turn_dispatch import _binding

READ='#preparation-request-read-original'
READ_STATUS='#preparation-request-read-status'
ORIGINAL_TEXT=('Original captured native activity — 保留 résumé  \n'*35)+'CAPTURED ORIGINAL ACTIVITY END  '


class Fixture(c.Fixture):
    def install_store_only_catalog(self):
        super().install_store_only_catalog()
        owner=self
        class Catalog:
            def request(self, method, params):
                owner.catalog_calls.append({'method':method,'params':params.copy(),'home':str(owner.desk.home)})
                if method=='thread/list':return {'data':[],'nextCursor':None}
                assert method=='thread/read' and params=={'threadId':'native-original','includeTurns':True},params
                if owner.missing:raise FileNotFoundError('Captured original native rollout missing')
                return {'thread':{'id':'native-original','cwd':str(owner.path),'name':'Captured original activity','turns':[
                    {'id':'earlier','status':'completed','items':[{'id':'prior-'+str(i),'type':'agentMessage','text':'Earlier original '+str(i)} for i in range(45)]},
                    {'id':'captured-run','status':'completed','items':[{'id':'captured-task','type':'userMessage','content':[{'type':'text','text':owner.captured['text']}]},
                        {'id':'captured-result','type':'agentMessage','text':ORIGINAL_TEXT}]}]}}
        self.desk.catalog=lambda:Catalog()

    def start(self,mode):
        self.missing=False
        super().start(mode)


def history_gets(requests):
    return [r for r in requests if r['path']=='/api/native/thread']


async def captured_snapshot(page):
    return await page.evaluate("""()=>({text:$('preparation-request-captured-text').textContent,
        selection:getSelection().toString(),scroll:$('preparation-request-captured-text').scrollTop,
        disclosure:$('preparation-request-captured').open,viewerScroll:$('preparation-request').scrollTop,
        original:$('preparation-request-original-binding').textContent,current:$('preparation-request-current-binding').textContent})""")


async def modal_snapshot(page):
    return await page.locator('#preparation-text').evaluate("""n=>({text:n.value,mode:$('preparation-mode').value,
        caret:[n.selectionStart,n.selectionEnd,n.selectionDirection],scroll:n.scrollTop,outerScroll:$('preparation').scrollTop})""")


async def read_original(page):
    await page.locator(READ).focus();await page.keyboard.press('Enter')
    await page.wait_for_function("$('history-reader').open")
    await page.wait_for_function("$('history-reader-body').getAttribute('aria-busy')==='false'")


async def back_to_request(page):
    assert await page.locator('#history-reader-back').inner_text()=='Return to task request'
    await page.locator('#history-reader-back').focus();await page.keyboard.press('Enter')
    await page.wait_for_function("!$('history-reader').open && $('preparation-request').open")
    assert await page.evaluate('document.activeElement.id')=='preparation-request-read-original'


async def acceptance(browser,width,mode):
    f=Fixture();f.start(mode);context=page=None
    result={'width':width,'mode':mode,'passed':False,'checks':[]}
    try:
        with patch.object(c.service,'save_draft',side_effect=f.controlled_save):
            context,page,errors,requests,external=await c.make_page(browser,f,width)
            main=await c.prepare_main(page,f)
            await c.overview(page)
            await page.locator(f'.preparation-session[data-session="{c.SELECTED}"] button[data-control="review"]').click()
            await page.locator('#preparation-text').fill(c.MODAL_EDIT*40)
            await page.locator('#preparation-mode').select_option('plan')
            await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(7,35,'backward');n.scrollTop=61;}")
            modal=await modal_snapshot(page)
            await c.open_review(page,f.original);await c.exact_view(page,f)
            assert await page.locator(READ).count()==1 and await page.locator(READ).is_enabled()
            await page.locator('#preparation-request-captured-text').evaluate("""n=>{
                n.focus({preventScroll:true});n.scrollTop=160;const r=document.createRange();r.setStart(n.firstChild,11);r.setEnd(n.firstChild,47);
                const s=getSelection();s.removeAllRanges();s.addRange(r);
            }""")
            capture=await captured_snapshot(page);writes=f.desk.store.db.total_changes;boundary=len(requests)
            await read_original(page)
            assert 'native-original' in await page.locator('#history-reader-binding').inner_text()
            assert ORIGINAL_TEXT in await page.locator('#history-reader-body').text_content()
            assert 'Page 2 of 2' in await page.locator('#history-reader-coverage').inner_text()
            assert history_gets(requests)[-1]['query']=={'id':['native-original']}
            assert all(r['method']=='GET' for r in requests[boundary:])
            assert f.desk.store.db.total_changes==writes
            await c.unchanged_main(page,f,main);assert await modal_snapshot(page)==modal
            await back_to_request(page);assert await captured_snapshot(page)==capture
            await c.unchanged_main(page,f,main);assert await modal_snapshot(page)==modal
            result['checks'].append('exact captured native-original read at last item page; keyboard Return keeps Range/disclosure/scroll and both other editors')
            await page.screenshot(path=str(c.OUT/f'original-return-{width}.png'))

            # Current replacement is distinct, but a same-home original remains readable.
            f.desk.store.update(f.original,thread_id='native-replacement')
            await page.locator('#preparation-request-refresh').click()
            await page.wait_for_function("!$('preparation-request-status').textContent.startsWith('Reading')")
            assert await page.locator(READ).is_enabled()
            assert await page.locator('#preparation-request-accepted').is_disabled()
            assert await page.locator('#preparation-request-rejected').is_disabled()
            await read_original(page);assert history_gets(requests)[-1]['query']=={'id':['native-original']}
            assert ORIGINAL_TEXT in await page.locator('#history-reader-body').text_content()
            await back_to_request(page)
            assert 'native-replacement' in await page.locator('#preparation-request-current-binding').inner_text()
            result['checks'].append('same native home with current replacement reads captured original, never replacement, without enabling resolution')

            f.missing=True;capture=await captured_snapshot(page);await read_original(page)
            assert await page.locator('#history-reader-error').is_visible()
            assert 'Captured original native rollout missing' in await page.locator('#history-reader-error').inner_text()
            await back_to_request(page);assert await captured_snapshot(page)==capture
            await c.unchanged_main(page,f,main);assert await modal_snapshot(page)==modal;f.missing=False
            result['checks'].append('missing native original uses existing reader error/Return while exact request and other preparation stay intact')

            # A held native body returned after both readers were left owns no current UI.
            gate=f.gate('/api/native/thread',method='GET')
            await page.locator(READ).evaluate('n=>n.click()')
            assert await asyncio.to_thread(gate['entered'].wait,10)
            await page.locator('#history-reader-back').click()
            assert await page.evaluate('document.activeElement.id')=='preparation-request-read-original'
            assert await page.locator(READ).is_enabled()
            # A fresh original read can begin while the superseded native body waits.
            newer_gate=f.gate('/api/native/thread',method='GET')
            await page.locator(READ).evaluate('n=>n.click()')
            assert await asyncio.to_thread(newer_gate['entered'].wait,10)
            async with page.expect_event('requestfinished',predicate=lambda r:urlsplit(r.url).path=='/api/native/thread') as superseded:
                gate['release'].set()
            await superseded.value;await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            assert await page.locator('#history-reader').evaluate('n=>n.open')
            assert await page.locator('#history-reader-body').get_attribute('aria-busy')=='true'
            assert await page.locator(READ).is_disabled()
            result['checks'].append('superseded native body cannot clear a newer original read busy state; pending Return re-enables and focuses its own Read button')
            await page.locator('#history-reader-back').click()
            assert await page.evaluate('document.activeElement.id')=='preparation-request-read-original'
            await page.locator('#preparation-request-return').click()
            await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(7,35,'backward');}")
            delayed_modal=await modal_snapshot(page)
            async with page.expect_event('requestfinished',predicate=lambda r:urlsplit(r.url).path=='/api/native/thread') as late:
                newer_gate['release'].set()
            await late.value;await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
            assert not await page.locator('#history-reader').evaluate('n=>n.open')
            assert not await page.locator('#preparation-request').evaluate('n=>n.open')
            assert await page.evaluate('document.activeElement.id')=='preparation-text'
            assert await modal_snapshot(page)==delayed_modal;await c.unchanged_main(page,f,main)
            result['checks'].append('late captured-history GET after Return cannot reopen either modal or steal other editor focus')

            await c.open_review(page,f.original)
            current_home=f.desk.home;f.desk.home=current_home/'other-native-home'
            await page.locator('#preparation-request-refresh').click()
            await page.wait_for_function("!$('preparation-request-status').textContent.startsWith('Reading')")
            before_history=len(history_gets(requests))
            assert await page.locator(READ).is_disabled()
            assert 'home' in (await page.locator(READ_STATUS).inner_text()).lower()
            await page.locator(READ).evaluate('n=>n.onclick()')
            assert len(history_gets(requests))==before_history
            assert not await page.locator('#history-reader').evaluate('n=>n.open')
            f.desk.home=current_home
            result['checks'].append('different current native home explains unavailable read and forced activation makes no catalog history request')

            await page.locator('#preparation-request-return').click()
            no_id='captured-no-native-id';token=str(uuid.uuid4())
            f.desk.store.create(str(f.path),'default',identifier=no_id,name='Captured before native attachment')
            f.desk.store.update(no_id,status='failed')
            body=dict(session=no_id,token=token,text='Unattached exact Plan 保留  ',mode='plan',revision=0,writer='captured',sequence=1)
            f.desk.store.event(no_id,{'method':'desk/turnIntent','params':dict(token=token,payload=body,binding=_binding(f.desk,no_id))})
            await page.locator('#preparation-refresh').click()
            await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
            await c.open_review(page,no_id);assert await page.locator(READ).is_disabled()
            assert 'native' in (await page.locator(READ_STATUS).inner_text()).lower()
            await page.locator(READ).evaluate('n=>n.onclick()')
            assert len(history_gets(requests))==before_history
            assert not await page.locator('#history-reader').evaluate('n=>n.open')
            assert await page.locator('#preparation-request-captured-text').text_content()==body['text']
            result['checks'].append('captured request without native attachment explains no original, never guesses selected/current history')
            await c.unchanged_main(page,f,main)
            assert not errors and not external
            assert all(call['method'] in ('thread/list','thread/read') for call in f.catalog_calls)
            assert all(call['params'].get('threadId')=='native-original' for call in f.catalog_calls if call['method']=='thread/read')
            assert f.native_open==[c.SELECTED] and len(f.requests)==1
            assert not any(r['method']=='POST' for r in requests[boundary:])
            result.update(passed=True,http=requests,catalog=f.catalog_calls,native_starts=1,additional_native_starts=0,
                          browser_errors=errors,external=external,package=str(c.PACKAGE),installed=os.environ.get('DESK_USE_INSTALLED')=='1')
    except Exception as error:
        result.update(error=repr(error),traceback=traceback.format_exc(),http=f.http)
        if page:await page.screenshot(path=str(c.OUT/f'original-failure-{width}.png'))
    finally:
        f.draft_release.set()
        for gate in f.gates:gate['release'].set()
        if context:await context.close()
        f.finish()
    return result


async def main():
    async with c.async_playwright() as pw:
        browser=await pw.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,
                                        args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            results=[await acceptance(browser,1250,'native'),await acceptance(browser,390,'plan')]
        finally:await browser.close()
    (c.OUT/'result.json').write_text(json.dumps({'results':results,'passed':all(r['passed'] for r in results)},indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'passed':all(r['passed'] for r in results),'cases':len(results),'checks':sum(len(r['checks']) for r in results)}),flush=True)
    if not all(r['passed'] for r in results):
        for r in results:
            if not r['passed']:print(r.get('traceback',''))
        raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
