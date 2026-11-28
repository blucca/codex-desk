#!/usr/bin/env python3
"""Archived native title and known-ID revisit through maintained sample assets."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from build_browser_preview import CHILD,CHILD_TURN,CHILD_ITEM,CHILD_QUOTE
from check_browser_preview import static_server
from check_browser_preview_links import open_app,reload_app
from check_browser_preview_session_reading import A,B,C,frames

TITLE='linked retry original'
DRAFT='Keep existing B documentation Plan unsent while revisiting its native source.'

async def check(p,site,evidence,width,chromium,embedded,rich):
    mode='iframe' if embedded else 'direct';prefix=f'{width}-{mode}'
    report={'passed':False,'width':width,'actual_iframe':embedded,'rich':rich,'checks':[]};errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844},permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None;expected=None;owner=None
        def item():return app.locator(f'.history-reader-item[data-turn-id="{CHILD_TURN}"][data-item-id="{CHILD_ITEM}"]')
        async def state():return await app.evaluate('DeskBrowserPreview.snapshot()')
        async def ready():
            await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app);await frames(app)
        async def click_read():
            before=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#native-list .native-read').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#native-list .native-read').press('Enter');await ready()
            reads=await original_calls(before);assert len(reads)==1 and reads[0]['path']==f'/api/native/thread?id={CHILD}',reads
        async def original_calls(boundary=0):
            return [r for r in await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary) if urlsplit(r['path']).path in ('/api/native/thread','/api/native/evidence-source','/api/native/task-response')]
        async def back():
            await app.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#history-reader-back').press('Enter')
            await app.wait_for_function("!$('history-reader').open");await frames(app)
        async def checkpoint(name):
            assert not errors and not external and not escaped,(errors,external,escaped)
            assert await state()==expected,name+' preparation changed'
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert {s['id'] for s in expected['sessions']}=={A,B,C}
            assert 'desk-'+CHILD not in expected['drafts'] and 'desk-'+CHILD not in expected['followups']
            assert await app.locator('#prompt').input_value()==expected['drafts'][B]['text']
            assert await app.locator('#turn-mode').input_value()=='plan'
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
            print(json.dumps({'passed':name,'width':width,'mode':mode,'rich':rich}),flush=True)
        async def passage():
            return await item().evaluate("""n=>({turn:n.dataset.turnId,item:n.dataset.itemId,start:Number(n.dataset.windowStart),open:n.open,
              inner:n.querySelector('pre').scrollTop,innerLeft:n.querySelector('pre').scrollLeft,top:n.getBoundingClientRect().top,
              outer:$('history-reader').scrollTop,body:$('history-reader-body').scrollTop})""")
        def same_place(before,after):
            for key in ('turn','item','start','open'):assert before[key]==after[key],(before,after)
            for key in ('inner','innerLeft','top','body'):assert abs(before[key]-after[key])<=2,(before,after)
        async def choose_quote(occurrence):
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
            if occurrence==2:await page.keyboard.press('F3');await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
            await frames(app)
        async def pointer_select():
            mark=item().locator('mark');await mark.evaluate("n=>n.scrollIntoView({block:'center',inline:'nearest'})");await frames(app)
            rects=await mark.evaluate("n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))")
            first,last=rects[0],rects[-1];start=(first['left']+.5,(first['top']+first['bottom'])/2);end=(last['right']-.5,(last['top']+last['bottom'])/2)
            if width==390:start,end=end,start
            if embedded:
                box=await page.locator('iframe').bounding_box();start=(start[0]+box['x'],start[1]+box['y']);end=(end[0]+box['x'],end[1]+box['y'])
            await page.mouse.move(*start);await page.mouse.down();await page.mouse.move(*end,steps=12);await page.mouse.up()
            assert await app.evaluate('getSelection().toString()')==CHILD_QUOTE
        async def catalog():
            return await app.evaluate("({source:$('history-source').value,query:$('history-search').value,rows:$('native-list').textContent,summary:$('history-summary').textContent,cursor:nativeCursor,scroll:$('history').scrollTop})")
        async def known_id():
            before=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#history-id').fill(CHILD);await app.locator('#history-id').press('Enter');await ready()
            reads=await original_calls(before);assert len(reads)==1 and urlsplit(reads[0]['path']).path=='/api/native/evidence-source' and parse_qs(urlsplit(reads[0]['path']).query)['thread']==[CHILD],reads
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==(15 if rich else 13)
            assert await app.evaluate('!!DeskBrowserPreview.fixture')==rich
            await app.evaluate("""async data=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});
               await api('/api/draft',{session:data.b,text:data.draft,mode:'plan',revision:0});
               for(const mode of ['native','plan'])await api('/api/followups',{session:data.b,text:'Retained B '+mode+' next instruction',mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            expected=await state();owner=await app.evaluate('({selected,nativeThreadId,generation})');queues=expected['followups']
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#history-source').input_value()=='current'
            await app.locator('#history-search').fill(TITLE);await app.locator('#history-search').press('Enter');await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#native-list .native-row').count()==0
            await app.locator('#history-source').select_option('archived');await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#native-list .native-row').count()==1
            assert await app.locator('#native-list button').all_text_contents()==['Read original conversation']
            assert await app.locator('#native-list').locator('[data-native-source="archived"]').count()==1
            before_catalog=await catalog();await checkpoint('current-title-miss-explicit-native-archive-title-read-only-preserves-B')
            await click_read();assert await app.locator('#history-reader-back').text_content()=='Back to archived conversations'
            await choose_quote(1);await pointer_select()
            await item().locator('.history-reader-review-evidence').evaluate('n=>n.focus({preventScroll:true})');await item().locator('.history-reader-review-evidence').press('Enter')
            await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
            reference=await app.evaluate('DeskEvidencePreparation.state().reference');assert reference['quote']==CHILD_QUOTE and reference['thread_id']==CHILD
            first_start=reference['quote_start'];boundary=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#evidence-preparation-append').click();await app.wait_for_function("!$('evidence-preparation').open");await frames(app)
            expected=await state();assert expected['drafts'][B]['text'].startswith(DRAFT) and expected['drafts'][B]['revision']==2 and expected['followups']==queues
            writes=[r for r in await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary) if r['method']=='POST'];assert [r['path'] for r in writes]==['/api/draft']
            await checkpoint('one-reviewed-first-occurrence-quote-saved-in-existing-B-Plan-with-two-queues')
            await choose_quote(2);await item().locator('mark').evaluate("n=>n.scrollIntoView({block:'center',inline:'nearest'})");await frames(app)
            remembered=await passage();assert remembered['start']>20000
            await back();after_catalog=await catalog();assert after_catalog==before_catalog,(before_catalog,after_catalog)
            meta=await app.evaluate("JSON.parse(localStorage.getItem(DeskBrowserPreview.originalReadingKey))")
            assert len(meta['checkpoints'])==1
            entry=meta['checkpoints'][0];assert set(entry['owner'])=={'native_home','thread_id'} and entry['owner']['thread_id']==CHILD
            assert entry['view']['anchor']['item_id']==CHILD_ITEM
            raw=json.dumps(meta,ensure_ascii=False);assert CHILD_QUOTE not in raw and 'Child source line' not in raw and 'match_text' not in raw and 'findQuery' not in raw
            await click_read();same_place(remembered,await passage())
            assert await app.locator('#history-reader-find-query').input_value()==''
            await checkpoint('archived-title-explicit-fresh-reopen-retains-later-window-and-place-not-Find-or-body')
            await back();await known_id();same_place(remembered,await passage())
            await checkpoint('known-ID-fresh-read-uses-same-native-home-original-checkpoint')
            await back();await app.locator('#history-close').click()
            before_reload=expected;app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function("!opening&&!sessionReadingPending")
            assert not await app.locator('#history-reader').evaluate('n=>n.open')
            assert await original_calls()==[]
            if await app.evaluate('selected')!=B:
                await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B)
            expected=await state();assert expected==before_reload;assert expected['followups']==queues and expected['drafts'][B]['text'].startswith(DRAFT);owner=await app.evaluate('({selected,nativeThreadId,generation})')
            await checkpoint('reload-keeps-B-preparation-and-original-metadata-with-no-automatic-original-read')
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#history-source').input_value()=='current'
            await app.locator('#history-source').select_option('archived');await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-search').fill(TITLE);await app.locator('#history-search').press('Enter');await app.wait_for_function("!$('history-search-submit').disabled")
            await click_read();same_place(remembered,await passage())
            await checkpoint('reload-then-deliberate-archived-title-reopen-returns-to-fresh-later-original')
            await back();await app.locator('#history-close').click()
            if not await app.locator('#draft-evidence').evaluate('n=>n.open'):await app.locator('#draft-evidence summary').click()
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(15,26,'backward');n.scrollTop=35}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value,window:scrollY})")
            boundary=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#draft-evidence-list button').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#draft-evidence-list button').press('Enter');await ready()
            assert len(await original_calls(boundary))==1
            assert await app.locator('#history-reader-saved-evidence-quote').text_content()==CHILD_QUOTE
            assert await item().locator('mark').text_content()==CHILD_QUOTE
            assert await app.evaluate("DeskEvidencePreparation.parse($('prompt').value)[0].reference.quote_start")==first_start
            assert (await passage())['start']<remembered['start']
            await checkpoint('explicit-saved-first-quote-outranks-remembered-later-original-place')
            await back();assert await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value,window:scrollY})")==editor
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled");await known_id();same_place(remembered,await passage())
            await back();await app.locator('#history-close').click()
            await checkpoint('saved-quote-return-keeps-B-editor-and-does-not-replace-normal-original-checkpoint')
            calls=await app.evaluate('DeskBrowserPreview.requests');assert not [r for r in calls if r['method']=='POST' and urlsplit(r['path']).path not in ('/api/import','/api/open','/api/draft','/api/followups')]
            assert not [r for r in calls if r['method']=='POST' and (r['data'].get('thread')==CHILD or r['data'].get('session')=='desk-'+CHILD)]
            report.update(passed=True,native_admissions=0,child_task_rows=0,sample_histories=4,sample_items=15 if rich else 13,remembered_view=remembered,saved_quote_start=first_start,source_id=CHILD,metadata_only=True,fresh_original_reads_only=True)
        except Exception as e:
            import traceback
            report.update(error=str(e),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
            if app:report['body']=await app.locator('body').inner_text()
        finally:await context.close();await browser.close()
    (evidence/f'{prefix}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');assert report['passed'],report.get('traceback');return report

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:reports=[await check(p,args.site,args.evidence,int(w),args.chromium,args.embedded,args.rich) for w in args.widths.split(',')]
    (args.evidence/'summary.json').write_text(json.dumps({'result':'PASS','reports':reports},indent=2,ensure_ascii=False)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--site',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path);p.add_argument('--embedded',action='store_true');p.add_argument('--rich',action='store_true');p.add_argument('--widths',default='1250,390');p.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'));asyncio.run(main(p.parse_args()))
