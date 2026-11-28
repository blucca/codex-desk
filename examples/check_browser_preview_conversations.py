#!/usr/bin/env python3
"""Maintained source-first discovery and live same-result reentry from exact sample items."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import unicodedata
from urllib.parse import parse_qs,urlsplit
from check_browser_preview import static_server
from check_browser_preview_links import open_app
from check_browser_preview_session_reading import A,B,C,frames

QUERY='Retry discovery Cafe\u0301 项目 😀'
DRAFT='Keep B documentation Plan unsent; verify the launch command first.'

def folded(text):return unicodedata.normalize('NFKC',unicodedata.normalize('NFKC',text).casefold())
def oracle(threads,saved,query):
    """Derive matched-item counts from frozen supplied fields, not adapter results."""
    result={}
    for t in threads:
        count=0
        for turn in t['turns']:
            for item in turn['items']:
                if not isinstance(item,dict):continue
                text=item.get('text','') if item['type']=='agentMessage' else '\n'.join([item.get('command',''),item.get('aggregatedOutput','')]) if item['type']=='commandExecution' else '\n'.join(c.get('text','') for c in item.get('content',[]) if c.get('type')=='text')
                count+=int(folded(query) in folded(text))
        if count:
            owners=[s for s in saved['sessions'] if s['thread_id']==t['id']]
            for owner in owners or [None]:result[('session',owner['id']) if owner else ('native',t['id'])]=count
    return result

async def check(p,site,evidence,width,chromium,embedded,rich):
    prefix=f'{width}-'+('iframe' if embedded else 'direct');report={'passed':False,'width':width,'actual_iframe':embedded,'rich':rich,'checks':[],'reentry':[]};errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage']);context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844})
        report['browser']=browser.version
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)));app=None
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate)
        async def ready():await app.wait_for_function("!$('recall-search').disabled&&$('recall-results').getAttribute('aria-busy')==='false'");await frames(app)
        async def search():await app.locator('#recall-query').press('Enter');await ready()
        async def saved():return await app.evaluate('DeskBrowserPreview.snapshot()')
        async def native():return await app.evaluate("DeskBrowserPreview.requests.filter(r=>['/api/native/thread','/api/native/evidence-source','/api/native/task-response'].includes(r.path.split('?')[0]))")
        async def picked_place():
            return await app.evaluate('''() => {const node=document.activeElement,row=node.closest('.recall-result');
                return {query:$('recall-query').value,project:$('recall-project').value,archived:$('recall-archived').checked,
                    grouped:$('recall-grouped').checked,source:$('recall-source-label').textContent,
                    summary:$('recall-summary').textContent,focus:node.className,
                    row:row?{kind:row.dataset.kind??null,session:row.dataset.session??null,thread:row.dataset.thread??null,
                        item:row.dataset.item??null,group:row.dataset.group??null,groupKind:row.dataset.groupKind??null}:null,
                    scroll:$('recall').scrollTop,resultsScroll:$('recall-results').scrollTop};}''')
        async def same_result_reentry(name,button=False,paged=False):
            before=await picked_place();assert before['row'] is not None and before['focus'] in ('recall-read','recall-group'),before
            if paged:assert 'Items 31–60' in before['summary'] and before['scroll']>100,before
            reads=len(await native());lookups=await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.path.startsWith("/api/recall?")).length')
            picked_scroll=before['scroll']
            if button:
                # A pointer click first brings the header into view. Measure the
                # real preclose position rather than demanding an earlier viewport.
                await app.locator('#recall-close').evaluate('''node=>node.addEventListener('pointerdown',()=>{
                    window.__recallClosePlace={scroll:$('recall').scrollTop,resultsScroll:$('recall-results').scrollTop};
                },{once:true,capture:true})''')
                await app.locator('#recall-close').click()
                before.update(await app.evaluate('window.__recallClosePlace'))
            else:await page.keyboard.press('Escape')
            await frames(app);assert not await app.locator('#recall').evaluate('node=>node.open')
            await app.locator('#search-saved-content').focus();await page.keyboard.press('Enter');await ready()
            after=await picked_place();receipt={'check':name,'method':'Close button' if button else 'Escape','before':before,'after':after,
                'same_row':before['row']==after['row'],'same_focus':before['focus']==after['focus'],
                'scroll_delta':after['scroll']-before['scroll'],'results_scroll_delta':after['resultsScroll']-before['resultsScroll'],
                'picked_before_close_scroll':picked_scroll,'new_original_reads':len(await native())-reads,
                'new_search_reads':await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.path.startsWith("/api/recall?")).length')-lookups}
            report['reentry'].append(receipt)
            assert receipt['same_row'] and receipt['same_focus'],receipt
            assert abs(receipt['scroll_delta'])<=1 and abs(receipt['results_scroll_delta'])<=1,receipt
            assert {k:v for k,v in before.items() if k not in ('scroll','resultsScroll')}=={k:v for k,v in after.items() if k not in ('scroll','resultsScroll')},receipt
            assert receipt['new_original_reads']==receipt['new_search_reads']==0,receipt
            await checkpoint(name)
        async def pick_thirteenth_read():
            # Paging deliberately focuses the first read. Traverse real controls
            # to a later remembered item instead of assigning a selection variable.
            assert await app.locator('.recall-read').first.evaluate('node=>node===document.activeElement')
            for _ in range(24):await page.keyboard.press('Tab')
            assert await app.locator('.recall-read').nth(12).evaluate('node=>node===document.activeElement')
            item=await app.locator('.recall-read').nth(12).evaluate('node=>node.closest("article").dataset.item')
            n=len(await native());await page.keyboard.press('Enter')
            await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
            assert len(await native())==n+1 and await app.locator('.history-reader-target').get_attribute('data-item-id')==item
            await app.locator('#history-reader-back').focus();await page.keyboard.press('Enter');await frames(app)
            assert await app.locator('.recall-read').nth(12).evaluate('node=>node===document.activeElement')
            return item

        async def checkpoint(name):
            assert await saved()==expected
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert await app.locator('#prompt').input_value()==DRAFT and await app.locator('#turn-mode').input_value()=='plan'
            assert await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.method==="POST").length')==posts
            assert await app.evaluate('JSON.stringify(DeskPreviewThreads)')==source
            assert not errors and not external and not escaped,(errors,external,escaped)
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'));print(json.dumps({'width':width,'mode':prefix,'passed':name}),flush=True)
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==(15 if rich else 13)
            assert await app.evaluate('!!DeskBrowserPreview.fixture')==rich
            await app.evaluate("""async d=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});await api('/api/draft',{session:d.b,text:d.draft,mode:'plan',revision:0});for(const mode of ['native','plan'])await api('/api/followups',{session:d.b,text:'Retained B '+mode,mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            before=await saved();boundary=await app.evaluate('DeskBrowserPreview.requests.length');await app.locator('#preview-group-prepare').click()
            assert await saved()==before;assert await app.evaluate('DeskBrowserPreview.requests.length')==boundary
            await app.locator('#search-saved-content').click();await app.locator('#recall-index').click();await ready();await app.wait_for_function('DeskBrowserPreview.snapshot().indexed')
            expected=await saved();owner=await app.evaluate('({selected,nativeThreadId,generation})');posts=await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.method==="POST").length');source=await app.evaluate('JSON.stringify(DeskPreviewThreads)')
            supplied=json.loads(source);counts=oracle(supplied,expected,QUERY);assert sum(counts.values())==66 and len(counts)==2
            await app.locator('#recall-query').fill(QUERY);await search()
            assert await app.locator('.recall-result').count()==30
            assert set(await app.locator('.recall-result').evaluate_all('ns=>ns.map(n=>n.dataset.thread)'))=={'sample-checkout-thread'}
            await checkpoint('unchanged-B-and-item-only-domination')
            await app.locator('#recall-grouped').check();await search();rows=await app.locator('.recall-result').evaluate_all('ns=>ns.map(n=>({kind:n.dataset.groupKind,id:n.dataset.group,label:n.querySelector(".recall-kind").textContent}))')
            assert len(rows)==len(counts)
            for row in rows:assert row['label'].startswith(str(counts[row['kind'],row['id']])+' matching item'),(row,counts)
            assert '66 matching items' in await app.locator('#recall-summary').inner_text();await checkpoint('independent-exact-matched-item-groups-not-occurrences')
            await app.locator('.recall-group').first.focus();await page.keyboard.press('Tab');assert await app.evaluate("document.activeElement.closest('article').dataset.group==='sample-child-thread'")
            await page.keyboard.press('Enter');await ready();assert await app.locator('.recall-result').count()==1
            assert (await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.path.startsWith("/api/recall?")).at(-1)'))['path'].endswith('source_thread=sample-child-thread')
            n=len(await native());await app.locator('.recall-read').click();await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
            assert len(await native())==n+1;assert 'Retry discovery Café 项目 😀' in await app.locator('.history-reader-target mark').inner_text()
            assert await app.locator('.history-reader-target').get_attribute('data-item-id')=='sample-discovery-distinct-command'
            await app.locator('#history-reader-back').click();await frames(app);assert await app.evaluate('document.activeElement.classList.contains("recall-read")')
            assert await app.locator('#recall-query').input_value()==QUERY;await app.locator('#recall-source-back').click();await ready()
            assert await app.evaluate("document.activeElement.closest('article').dataset.group==='sample-child-thread'");await checkpoint('genuine-keyboard-distinct-source-and-same-group-return')
            await app.locator(f'[data-group="{A}"] .recall-group').click();await ready();await app.locator('#recall-next').click();await ready()
            assert 'Items 31–60' in await app.locator('#recall-summary').inner_text()
            last=await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.path.startsWith("/api/recall?")).at(-1)');assert parse_qs(urlsplit(last['path']).query)['source_session']==[A]
            item=await pick_thirteenth_read()
            await same_result_reentry('source-page-picked-original-Escape-reopen-exact-live-place',paged=True)
            await same_result_reentry('source-page-picked-original-Close-button-reopen-exact-live-place',button=True,paged=True)
            await app.locator('#recall-source-back').click();await ready();assert await app.evaluate(f"document.activeElement.closest('article').dataset.group==='{A}'")
            calls=await native();assert len(calls)==2 and all(c['method']=='GET' for c in calls);await checkpoint('exact-saved-source-item-page-original-and-group-return')
            await same_result_reentry('grouped-picked-conversation-Escape-reopen-exact-live-place')
            await app.locator('#recall-grouped').uncheck();await search();await app.locator('#recall-next').click();await ready()
            assert 'Items 31–60' in await app.locator('#recall-summary').inner_text()
            assert await pick_thirteenth_read()==item
            await same_result_reentry('all-item-page-picked-original-Escape-reopen-exact-live-place',paged=True)
            await same_result_reentry('all-item-page-picked-original-Close-button-reopen-exact-live-place',button=True,paged=True)
            calls=await native();assert len(calls)==3 and all(c['method']=='GET' for c in calls)
            report.update(passed=True,oracle=[{'kind':k[0],'id':k[1],'matched_items':v} for k,v in counts.items()],native_reads=len(calls),native_admissions=0,reentry_cases=len(report['reentry']),new_original_reads_on_reentry=0,new_search_reads_on_reentry=0)
        except Exception as e:
            import traceback
            report.update(error=str(e),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
        finally:await context.close();await browser.close()
    (evidence/f'{prefix}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');assert report['passed'],report.get('traceback');return report

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:reports=[await check(p,args.site,args.evidence,int(width),args.chromium,args.embedded,args.rich) for width in args.widths.split(',')]
    (args.evidence/'summary.json').write_text(json.dumps({'result':'PASS','reports':reports},ensure_ascii=False,indent=2)+'\n')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--site',required=True,type=Path);parser.add_argument('--evidence',required=True,type=Path);parser.add_argument('--rich',action='store_true');parser.add_argument('--embedded',action='store_true');parser.add_argument('--widths',default='1250,390');parser.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'));asyncio.run(main(parser.parse_args()))
