#!/usr/bin/env python3
"""Reader-header plain native-ID copy across current, linked and direct originals."""
import asyncio,copy,importlib.util,json,os,tempfile,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
SPEC=importlib.util.spec_from_file_location('copy_id_fixture',Path(__file__).with_name('check_native_task_response.py'))
base=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(base)
from playwright.async_api import async_playwright
CHILD,DIRECT,LINK='linked-child/接口?+plain','known-original/接口?+plain','B-linked-child'
QUOTE='EXACT ID quote — café🙂 source.'
TEXT='\n'.join(f'Supplied child line {i:04d} keeps its exact source.'+(' '+QUOTE if i in (15,900) else '') for i in range(1200))

async def one(browser,width,root,evidence):
    record={'width':width,'passed':False,'checks':[]};errors=[];http=[]
    with tempfile.TemporaryDirectory(dir=root,prefix=f'copy-id-{width}-') as temporary:
        f=base.Fixture(Path(temporary));context=None
        f.threads[base.PARENT]={'id':base.PARENT,'cwd':str(f.project),'name':'Current B parent','turns':[{'id':base.TURN,'status':'completed','items':[
            {'id':'B-user','type':'userMessage','content':[{'type':'text','text':'Read the linked native original before changing this Plan.'}]},
            {'id':LINK,'type':'subAgentActivity','kind':'completed','agentThreadId':CHILD,'agentPath':'/root/child'},
            base.assistant('B-answer','Current B own source stays selected.','final_answer')]}]}
        for identifier in (CHILD,DIRECT):f.threads[identifier]={'id':identifier,'cwd':str(Path(temporary)/'removed-original'),'name':identifier,'turns':[{'id':'original-turn','status':'completed','items':[base.assistant('original-item',TEXT,'final_answer')]}]}
        f.desk.store.recall_snapshot(base.ORIGINAL,f.threads[base.PARENT]);prepared=f.prepared()
        with patch.object(base.product,'_NativeReader',f.reader_type),patch.object(base.product,'Runtime',side_effect=AssertionError('Copy ID must not create a task runtime')):
            try:
                context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844},permissions=['clipboard-read','clipboard-write'])
                await context.add_init_script("""(()=>{const later=setTimeout;window.setTimeout=function(callback,...args){if(callback?.name==='tick')return 0;return later.call(this,callback,...args);};})();""")
                page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
                page.on('request',lambda r:http.append({'method':r.method,'path':urlsplit(r.url).path,'host':urlsplit(r.url).hostname}))
                async def frames():await base.frames(page)
                async def ready():
                    await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                    await frames()
                async def checkpoint(name):
                    assert not errors,errors
                    assert f.prepared()==prepared and f.desk.runtimes=={} and not f.desk.store.get(CHILD)
                    assert f.sql()==baseline
                    assert await page.evaluate('selected')==base.ORIGINAL
                    assert await page.locator('#prompt').input_value()==prepared[base.ORIGINAL]['draft']['text']
                    assert await page.locator('#turn-mode').input_value()=='plan'
                    assert all(q['host']=='127.0.0.1' for q in http)
                    assert not [q for q in http if q['method']=='POST' and q['path']!='/api/open']
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
                    record['checks'].append(name);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
                async def copy_id(identifier):
                    boundary=len(f.calls)
                    await page.locator('#history-reader-copy-native-id').evaluate('n=>n.focus({preventScroll:true})')
                    await page.locator('#history-reader-copy-native-id').press('Enter')
                    await page.wait_for_function("$('history-reader-native-id-status').textContent==='Native conversation ID copied.'")
                    assert await page.evaluate('navigator.clipboard.readText()')==identifier
                    assert f.calls[boundary:]==[]
                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                assert await page.locator('#history-reader-copy-native-id').is_disabled()
                await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=base.ORIGINAL);await frames()
                baseline=f.sql()
                await page.locator('#read-original').click();await ready();await copy_id(base.PARENT)
                await checkpoint('current-B-original-copies-exact-plain-native-ID-twoqueues-Plan-unchanged')
                await page.locator('#history-reader-back').click();await frames()
                assert await page.locator('#history-reader-copy-native-id').is_disabled()
                group=page.locator('#activity > details.activity-collaboration')
                if not await group.evaluate('n=>n.open'):await group.locator('summary').click()
                linked=page.locator('.linked-agent-original').filter(has_text=CHILD)
                await linked.evaluate('n=>n.focus({preventScroll:true})');await linked.press('Enter');await ready()
                await page.locator('#history-reader-find-query').fill(QUOTE);await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.keyboard.press('F3');await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')");await frames()
                target=page.locator('.history-reader-target');rects=await target.locator('mark').evaluate("n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))")
                first,last=rects[0],rects[-1]
                await page.mouse.move(last['right']-.5,(last['top']+last['bottom'])/2);await page.mouse.down()
                await page.mouse.move(first['left']+.5,(first['top']+first['bottom'])/2,steps=12);await page.mouse.up()
                assert await page.evaluate('getSelection().toString()')==QUOTE
                async def source_view():
                    return await target.evaluate("""n=>{const r=getSelection().getRangeAt(0);return {windowStart:n.dataset.windowStart,pre:n.querySelector('pre').scrollTop,
                      body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,window:scrollY,top:n.getBoundingClientRect().top,
                      selected:getSelection().toString(),backward:getSelection().anchorNode===r.endContainer&&getSelection().anchorOffset===r.endOffset,
                      query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent};}""")
                retained=await source_view();await copy_id(CHILD);await frames();assert await source_view()==retained,(retained,await source_view())
                await checkpoint('linked-child-plain-ID-retains-genuine-backward-Range-second-Find-and-viewport')
                await target.locator('.history-reader-copy-source').click()
                await page.wait_for_function("document.querySelector('.history-reader-copy-status').textContent.includes('Source reference copied')")
                metadata=await page.evaluate('navigator.clipboard.readText()')
                expected=f'Conversation: {CHILD}\nThread: {CHILD}\nTurn: original-turn\nItem: original-item\nProject folder: '+str(Path(temporary)/'removed-original')
                assert metadata==expected,(metadata,expected)
                await page.locator('#history-reader-back').click();await frames()
                await checkpoint('ordinary-multiline-source-reference-copy-unchanged-parent-return')
                await page.locator('#browse').click();await page.wait_for_function("!$('history-search-submit').disabled")
                async def direct(identifier):
                    await page.locator('#history-id').fill(identifier);await page.locator('#history-id').press('Enter');await ready()
                await direct(DIRECT);await copy_id(DIRECT)
                await checkpoint('direct-ID-header-copies-full-exact-plain-ID-not-parent-or-label')
                await page.locator('#history-reader-back').click();await frames()
                f.failures.add(DIRECT);await page.evaluate("navigator.clipboard.writeText('UNCHANGED FAILURE SENTINEL')")
                await direct(DIRECT)
                assert await page.locator('#history-reader-copy-native-id').is_disabled()
                assert await page.evaluate('navigator.clipboard.readText()')=='UNCHANGED FAILURE SENTINEL'
                f.failures.clear();await page.locator('#history-reader-retry').click();await ready();await copy_id(DIRECT)
                await checkpoint('source-failure-disables-copy-until-same-original-retry-succeeds')
                await page.evaluate("""()=>{window.__nativeWrite=navigator.clipboard.writeText.bind(navigator.clipboard);navigator.clipboard.writeText=async value=>{
                  window.__heldCopy=value;await new Promise(resolve=>window.__releaseCopy=resolve);return window.__nativeWrite(value);};}""")
                await page.locator('#history-reader-copy-native-id').focus();await page.locator('#history-reader-copy-native-id').press('Enter')
                await page.wait_for_function('!!window.__releaseCopy');assert await page.evaluate('window.__heldCopy')==DIRECT
                await page.locator('#history-reader-back').click();await frames();await direct(CHILD)
                assert not await page.locator('#history-reader-copy-native-id').is_disabled()
                await page.evaluate('window.__releaseCopy()');await page.wait_for_timeout(100);await frames()
                assert await page.locator('#history-reader-native-id-status').text_content()==''
                assert not await page.locator('#history-reader-copy-native-id').is_disabled()
                assert await page.evaluate('window.__heldCopy')==DIRECT
                await page.evaluate('navigator.clipboard.writeText=window.__nativeWrite');await copy_id(CHILD)
                await checkpoint('late-closed-copy-keeps-captured-ID-and-cannot-mark-or-disable-new-source')
                await page.locator('#history-reader-back').click();await page.locator('#history-close').click();await frames()
                assert await page.locator('#history-reader-copy-native-id').is_disabled()
                assert {p:p.read_bytes() for p in f.protected}==f.protected
                record.update(passed=True,copied_plain_ids=[base.PARENT,CHILD,DIRECT],source_reference_unchanged=True,sqlite_exact=True,native_admissions=0,package=str(base.PACKAGE))
            except Exception as error:
                record.update(error=str(error),traceback=traceback.format_exc(),javascript_errors=errors)
                if context:await page.screenshot(path=str(evidence/f'{width}-failure.png'))
            finally:
                if context:await context.close()
                f.stop()
    (evidence/f'{width}.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n');print(json.dumps({k:record[k] for k in ('width','passed','checks','error') if k in record}),flush=True)
    return record

async def main():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:
        browser=await p.chromium.launch(headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:records=[await one(browser,width,root,evidence) for width in (1250,390)]
        finally:await browser.close()
    result='PASS' if all(r['passed'] for r in records) else 'FAIL';(evidence/'summary.json').write_text(json.dumps({'result':result,'results':records,'widths':[1250,390],'version':base.codex_desk.__version__},indent=2,ensure_ascii=False)+'\n')
    if result!='PASS':
        for r in records:
            if not r['passed']:print(r['traceback'],flush=True)
        raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
