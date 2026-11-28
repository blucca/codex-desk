#!/usr/bin/env python3
"""Original-only Find overview → exact occurrence → containing task → same overview/F3."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from build_browser_preview import CHILD,CHILD_TURN,CHILD_ITEM,CHILD_QUOTE
from check_browser_preview import static_server
from check_browser_preview_links import open_app,reload_app
from check_browser_preview_session_reading import B,frames
DRAFT='Keep B Plan exact while choosing original Find occurrences.'

async def check(p,site,evidence,width,chromium,embedded,rich):
    prefix=f'{width}-'+('iframe' if embedded else 'direct');report={'passed':False,'width':width,'actual_iframe':embedded,'rich':rich,'checks':[]}
    errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844})
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None
        def item():return app.locator(f'.history-reader-item[data-turn-id="{CHILD_TURN}"][data-item-id="{CHILD_ITEM}"]')
        def row(n):return app.locator(f'.history-reader-find-match[data-match-index="{n}"]')
        async def keyboard(locator):await locator.evaluate('n=>n.focus({preventScroll:true})');await locator.press('Enter');await frames(app)
        async def ready():await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app)
        async def view():
            return await item().evaluate("n=>({start:n.dataset.windowStart,open:n.open,inner:n.querySelector('pre').scrollTop,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,top:n.getBoundingClientRect().top,query:$('history-reader-find-query').value,selection:getSelection().toString(),disclosures:[...$('history-reader-body').querySelectorAll('.history-reader-item')].map(e=>[e.dataset.turnId,e.dataset.itemId,e.open,e.dataset.windowStart])})")
        async def select():
            boxes=await item().locator('mark').evaluate('n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
            first,last=boxes[0],boxes[-1];a=(last['right']-.5,(last['top']+last['bottom'])/2);b=(first['left']+.5,(first['top']+first['bottom'])/2)
            if embedded:
                outer=await page.locator('iframe').bounding_box();a=(a[0]+outer['x'],a[1]+outer['y']);b=(b[0]+outer['x'],b[1]+outer['y'])
            await page.mouse.move(*a);await page.mouse.down();await page.mouse.move(*b,steps=12);await page.mouse.up();assert await app.evaluate('getSelection().toString()')==CHILD_QUOTE
        async def unchanged(name):
            assert await app.evaluate('DeskBrowserPreview.snapshot()')==expected
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert await app.locator('#prompt').input_value()==DRAFT and await app.locator('#turn-mode').input_value()=='plan'
            assert await app.evaluate('JSON.stringify(DeskPreviewThreads)')==source
            assert await app.evaluate('JSON.stringify(globalThis.DeskPreviewReadingFixture?.events||{})')==events
            assert await app.evaluate('localStorage.getItem(DeskBrowserPreview.reviewKey)')==review
            native=await app.evaluate("DeskBrowserPreview.requests.filter(r=>['/api/native/thread','/api/native/evidence-source','/api/native/task-response'].includes(r.path.split('?')[0]))")
            assert len(native)==1 and native[0]['method']=='GET',native
            path=urlsplit(native[0]['path']);query=parse_qs(path.query)
            assert path.path in ['/api/native/thread','/api/native/evidence-source'] and query.get('thread',query.get('id'))==[CHILD],native
            if path.path=='/api/native/evidence-source':
                home=query.get('home',[''])[0];assert len(home)==64 and all(c in '0123456789abcdef' for c in home),native
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            assert not errors and not external and not escaped,(errors,external,escaped)
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
        async def match(number):
            await app.wait_for_function('n=>$("history-reader-find-status").textContent.includes("Match "+n+" of 2")',arg=number);await frames(app)
            assert await item().locator('mark').text_content()==CHILD_QUOTE
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==(15 if rich else 13)
            assert await app.evaluate('!!DeskBrowserPreview.fixture')==rich
            await app.evaluate("""async d=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});
              await api('/api/draft',{session:d.b,text:d.draft,mode:'plan',revision:0});for(const mode of ['native','plan'])await api('/api/followups',{session:d.b,text:'Retained B '+mode,mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            expected=await app.evaluate('DeskBrowserPreview.snapshot()');owner=await app.evaluate('({selected,nativeThreadId,generation})');source=await app.evaluate('JSON.stringify(DeskPreviewThreads)');events=await app.evaluate('JSON.stringify(globalThis.DeskPreviewReadingFixture?.events||{})');review=await app.evaluate('localStorage.getItem(DeskBrowserPreview.reviewKey)')
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(9,20,'backward');n.scrollTop=25}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-id').fill(CHILD);await app.locator('#history-id').press('Enter');await ready()
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE);await app.locator('#history-reader-find-query').press('Enter');await match(1)
            await keyboard(app.locator('#history-reader-find-matches-show'));await app.locator('#history-reader-find-matches').wait_for(state='visible')
            assert await app.locator('.history-reader-find-match').count()==2
            spans=[]
            for n in (0,1):
                assert await row(n).get_attribute('data-turn-id')==CHILD_TURN and await row(n).get_attribute('data-item-id')==CHILD_ITEM
                spans.append([int(await row(n).get_attribute('data-match-start')),int(await row(n).get_attribute('data-match-end'))])
            assert spans[1][0]>spans[0][1]
            await unchanged('two-exact-same-item-Unicode-occurrences-in-original-only-overview')
            await keyboard(row(1).locator('button'));await match(2);assert int(await item().get_attribute('data-window-start'))>20000
            await select();before=await view();await unchanged('Enter-selects-second-global-occurrence-with-backwards-Range')
            await keyboard(item().get_by_role('button',name='Read containing task',exact=True));await keyboard(app.locator('#history-reader-task-passage'))
            after=await view()
            for k in ('start','open','query','selection','disclosures'):assert before[k]==after[k],(k,before,after)
            for k in ('inner','body','outer','top'):assert abs(before[k]-after[k])<=2,(k,before,after)
            await unchanged('containing-task-return-keeps-exact-second-source-passage')
            await keyboard(app.locator('#history-reader-find-matches-return'));await app.locator('#history-reader-find-matches').wait_for(state='visible')
            assert await row(1).get_attribute('data-match-start')==str(spans[1][0])
            await row(0).locator('button').click();await match(1);assert int(await item().get_attribute('data-window-start'))<20000
            await unchanged('Return-Find-matches-pointer-selects-first-exact-occurrence')
            await page.keyboard.press('F3');await match(2);assert int(await item().get_attribute('data-window-start'))>20000
            await unchanged('immediate-F3-continues-from-selected-global-ordinal')
            await keyboard(app.locator('#history-reader-back'));await app.locator('#history-close').click();await frames(app)
            assert await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")==editor
            metadata=await app.evaluate('localStorage.getItem(DeskBrowserPreview.originalReadingKey)');assert CHILD_QUOTE not in metadata and 'findQuery' not in metadata
            app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function('!opening&&!sessionReadingPending')
            assert not await app.locator('#history-reader').evaluate('n=>n.open') and await app.evaluate('DeskBrowserPreview.snapshot()')==expected
            report.update(passed=True,native_admissions=0,native_original_reads=1,source_unchanged=True,initial_histories=4,initial_items=15 if rich else 13,occurrence_spans=spans,editor=editor)
        except Exception as e:
            import traceback
            report.update(error=str(e),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
            if app:report['body']=await app.locator('body').inner_text()
        finally:await context.close();await browser.close()
    (evidence/f'{prefix}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');assert report['passed'],report.get('traceback')
    print(json.dumps({'passed':True,'width':width,'iframe':embedded,'rich':rich,'checks':len(report['checks'])}),flush=True);return report
async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:reports=[await check(p,args.site,args.evidence,int(w),args.chromium,args.embedded,args.rich) for w in args.widths.split(',')]
    (args.evidence/'summary.json').write_text(json.dumps({'result':'PASS','reports':reports},indent=2,ensure_ascii=False)+'\n')
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--site',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path);p.add_argument('--embedded',action='store_true');p.add_argument('--rich',action='store_true');p.add_argument('--widths',default='1250,390');p.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'));asyncio.run(main(p.parse_args()))
