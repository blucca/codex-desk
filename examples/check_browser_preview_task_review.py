#!/usr/bin/env python3
"""Skim supplied tasks, inspect exact task evidence, return to original/B at 1250/390."""
import argparse,asyncio,json,os
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from check_browser_preview import static_server
from check_browser_preview_links import open_app,reload_app
from check_browser_preview_session_reading import B,frames

SOURCE='sample-child-thread';TURN='sample-review-task-41';ITEM='sample-review-long-command';RESPONSE='sample-review-reused-answer'
QUOTE='TASK EVIDENCE — Straße Café 项目 😀';QUERY='TASK EVIDENCE — STRASSE Cafe\u0301 项目 😀'
DRAFT='Keep B exact unsent Plan while skimming supplied tasks and their own evidence.'

async def check(p,site,evidence,width,chromium,embedded,rich):
    prefix=f'{width}-'+('iframe' if embedded else 'direct');report={'passed':False,'width':width,'actual_iframe':embedded,'rich':rich,'checks':[]}
    errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844},permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None
        def item():return app.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
        def task(n):return app.locator(f'.history-reader-task-overview-row[data-task-index="{n}"]')
        async def keyboard(locator):await locator.evaluate('n=>n.focus({preventScroll:true})');await locator.press('Enter');await frames(app)
        async def ready():await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app)
        async def find(count):
            await app.locator('#history-reader-find-query').fill(QUERY);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function('n=>$('+'"history-reader-find-status"'+').textContent.includes("Match 1 of "+n)',arg=count);await frames(app)
        async def passage():
            return await item().evaluate("n=>({start:n.dataset.windowStart,open:n.open,inner:n.querySelector('pre').scrollTop,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,top:n.getBoundingClientRect().top,query:$('history-reader-find-query').value,status:$('history-reader-find-status').textContent,selection:getSelection().toString(),backward:getSelection().anchorNode===getSelection().focusNode&&getSelection().anchorOffset>getSelection().focusOffset,disclosures:[...$('history-reader-body').querySelectorAll('.history-reader-item')].map(e=>[e.dataset.turnId,e.dataset.itemId,e.open,e.dataset.windowStart])})")
        async def listing(kind):
            return await app.evaluate("kind=>({first:Number(document.querySelector('.history-reader-task-'+kind+'-row')?.dataset[kind==='overview'?'taskIndex':'itemIndex']),count:document.querySelectorAll('.history-reader-task-'+kind+'-row').length,coverage:$('history-reader-coverage').textContent,body:$('history-reader-body').scrollTop,outer:$('history-reader').scrollTop,focus:document.activeElement.dataset.taskAction})",kind)
        def same_list(a,b):
            for k in ('first','count','coverage','focus'):assert a[k]==b[k],(k,a,b)
            for k in ('body','outer'):assert abs(a[k]-b[k])<2,(k,a,b)
        def same_passage(a,b):
            for k in ('start','open','query','status','selection','backward','disclosures'):assert a[k]==b[k],(k,a,b)
            for k in ('inner','body','outer','top'):assert abs(a[k]-b[k])<2,(k,a,b)
        async def select():
            boxes=await item().locator('mark').evaluate('n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
            first,last=boxes[0],boxes[-1];a=(last['right']-.5,(last['top']+last['bottom'])/2);b=(first['left']+.5,(first['top']+first['bottom'])/2)
            if embedded:
                outer=await page.locator('iframe').bounding_box();a=(a[0]+outer['x'],a[1]+outer['y']);b=(b[0]+outer['x'],b[1]+outer['y'])
            await page.mouse.move(*a);await page.mouse.down();await page.mouse.move(*b,steps=12);await page.mouse.up()
            assert await app.evaluate('getSelection().toString()')==QUOTE
            assert await app.evaluate('getSelection().anchorNode===getSelection().focusNode&&getSelection().anchorOffset>getSelection().focusOffset')
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
            assert query.get('thread',query.get('id'))==[SOURCE],native
            assert await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.method==="POST").length')==posts
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            assert not errors and not external and not escaped,(errors,external,escaped)
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==(15 if rich else 13)
            assert await app.evaluate('!!DeskBrowserPreview.fixture')==rich
            assert await app.evaluate('typeof DeskHistoryTasks.overview==="function"&&typeof DeskTaskEvidence.list==="function"')
            await app.evaluate("""async d=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});await api('/api/draft',{session:d.b,text:d.draft,mode:'plan',revision:0});for(const mode of ['native','plan'])await api('/api/followups',{session:d.b,text:'Retained B '+mode,mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            expected=await app.evaluate('DeskBrowserPreview.snapshot()');owner=await app.evaluate('({selected,nativeThreadId,generation})');events=await app.evaluate('JSON.stringify(globalThis.DeskPreviewReadingFixture?.events||{})');review=await app.evaluate('localStorage.getItem(DeskBrowserPreview.reviewKey)')
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(9,20,'backward');n.scrollTop=25}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")
            before_prepare=await app.evaluate('DeskBrowserPreview.requests.length');await app.locator('#preview-tasks-prepare').click()
            assert await app.evaluate('DeskBrowserPreview.requests.length')==before_prepare
            assert await app.evaluate('DeskPreviewThreads.find(t=>t.id==="sample-child-thread").turns.length')==61
            assert await app.evaluate('DeskBrowserPreview.snapshot()')==expected
            source=await app.evaluate('JSON.stringify(DeskPreviewThreads)')
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-id').fill(SOURCE);await app.locator('#history-id').press('Enter');await ready()
            posts=await app.evaluate('DeskBrowserPreview.requests.filter(r=>r.method==="POST").length')
            await find(3);await keyboard(app.locator('#history-reader-find-matches-show'))
            assert await app.locator('.history-reader-find-match').count()==3
            for n,turn in enumerate(('sample-review-task-40',TURN,'sample-review-task-42')):
                row=app.locator(f'.history-reader-find-match[data-match-index="{n}"]');assert await row.get_attribute('data-turn-id')==turn and await row.get_attribute('data-item-id')==ITEM
            await keyboard(app.locator('.history-reader-find-match[data-match-index="1"] button'));await select();original=await passage();assert int(original['start'])>20000
            await unchanged('original-wide-three-exact-tasks-late-Unicode-backwards-Range')
            await keyboard(app.locator('#history-reader-task-overview-show'))
            assert await app.locator('.history-reader-task-overview-row').count()==20
            for _ in range(2):await keyboard(app.get_by_role('button',name='Next tasks',exact=True))
            assert (await listing('overview'))['first']==40
            assert 'Native turn status: failed' in await task(41).inner_text()
            assert 'Final answer' in await task(41).inner_text() and 'Own supplied task 41 final response.' in await task(41).inner_text()
            assert 'Later commentary' not in await task(41).inner_text()
            assert 'Phase: unreported' in await task(42).inner_text()
            assert 'No readable assistant response' in await task(45).inner_text() and 'interrupted' in await task(45).inner_text()
            assert 'No user instruction was supplied' in await task(46).inner_text()
            chosen=task(41).get_by_role('button',name='Read task',exact=True);await chosen.scroll_into_view_if_needed();await chosen.focus();await frames(app);overview=await listing('overview');await chosen.click();await frames(app)
            assert TURN in await app.locator('#history-reader-task-status').inner_text()
            await keyboard(app.get_by_role('button',name='Read this task response',exact=True))
            response=app.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{RESPONSE}"]');assert await response.locator('pre').inner_text()=='Codex\nOwn supplied task 41 final response.'
            await keyboard(app.locator('#history-reader-task-overview-return'));same_list(overview,await listing('overview'))
            await unchanged('bounded-task-overview-exact-own-final-pointer-and-return')
            target_action=await task(42).get_by_role('button',name='Read task',exact=True).get_attribute('data-task-action')
            assert target_action and await task(42).get_attribute('data-turn-id')=='sample-review-task-42'
            await app.locator('.history-reader-task-overview h3').evaluate('n=>n.focus({preventScroll:true})')
            for _ in range(60):
                if await app.evaluate('document.activeElement.dataset.taskAction')==target_action:break
                await page.keyboard.press('Tab')
            assert await app.evaluate('document.activeElement.dataset.taskAction')==target_action;keyboard_overview=await listing('overview');await page.keyboard.press('Enter');await frames(app)
            await keyboard(app.get_by_role('button',name='Read this task response',exact=True));assert await app.locator(f'.history-reader-item[data-turn-id="sample-review-task-42"][data-item-id="{RESPONSE}"] pre').inner_text()=='Codex\nTask 42 supplied assistant message with phase unreported.'
            await keyboard(app.locator('#history-reader-task-overview-return'));same_list(keyboard_overview,await listing('overview'))
            await unchanged('genuine-Tab-Enter-task-own-unreported-phase-return')
            await task(41).get_by_role('button',name='Read task',exact=True).click();await frames(app)
            await keyboard(app.get_by_role('button',name='Read this task’s evidence',exact=True))
            assert await app.locator('#history-reader-find-scope').input_value()=='task'
            assert await app.locator('.history-reader-task-evidence-row').count()==20
            assert 'mcpToolCall' in await app.locator('.history-reader-task-evidence').inner_text() and 'fileChange' in await app.locator('.history-reader-task-evidence').inner_text()
            await keyboard(app.get_by_role('button',name='Next task evidence',exact=True));assert (await listing('evidence'))['first']==20
            evidence_row=app.locator(f'.history-reader-task-evidence-row[data-turn-id="{TURN}"][data-item-id="{ITEM}"]');chosen=evidence_row.get_by_role('button',name='Read full original item',exact=True);await chosen.scroll_into_view_if_needed();await chosen.focus();await frames(app);evidence_view=await listing('evidence');await chosen.click();await frames(app)
            assert await app.locator('.history-reader-item').count()==1
            await find(1);assert await item().locator('mark').text_content()==QUOTE;await select();scoped=await passage();assert int(scoped['start'])>20000
            await keyboard(item().get_by_role('button',name='Copy full item text',exact=True));await app.wait_for_function('document.querySelector(".history-reader-copy-status").textContent==="Full item text copied."')
            copied=await app.evaluate('navigator.clipboard.readText()');assert QUOTE in copied and 'Task source line 1899' in copied and 'task 40 only' not in copied
            await select();await keyboard(item().get_by_role('button',name='Review evidence for task',exact=True));await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
            assert await app.locator('#evidence-preparation-quote').inner_text()==QUOTE
            reference=await app.evaluate('DeskEvidencePreparation.state().reference');assert reference['thread_id']==SOURCE and reference['turn_id']==TURN and reference['item_id']==ITEM and reference['quote']==QUOTE
            await app.locator('#evidence-preparation-cancel').click();await frames(app)
            assert await item().locator('mark').text_content()==QUOTE and await app.evaluate('getSelection().toString()')==QUOTE
            await unchanged('task-scoped-single-exact-tool-full-Copy-quote-review-without-save')
            await keyboard(app.locator('#history-reader-task-evidence-return'));same_list(evidence_view,await listing('evidence'))
            await app.locator('#history-reader-find-scope').select_option('original');await find(3)
            await keyboard(app.locator('#history-reader-find-matches-show'));assert await app.locator('.history-reader-find-match').count()==3
            await unchanged('explicit-original-wide-Find-retains-all-three-task-occurrences')
            await keyboard(app.locator('#history-reader-task-overview-return'));assert (await listing('overview'))['first']==40
            await keyboard(app.locator('#history-reader-task-passage'));same_passage(original,await passage())
            await unchanged('same-overview-page-and-original-Find-Range-window-return')
            await keyboard(app.locator('#history-reader-back'));await app.locator('#history-close').click();await frames(app)
            assert await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")==editor
            app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function('!opening&&!sessionReadingPending')
            assert not await app.locator('#history-reader').evaluate('n=>n.open') and await app.evaluate('DeskBrowserPreview.snapshot()')==expected
            assert await app.evaluate('DeskPreviewThreads.find(t=>t.id==="sample-child-thread").turns.length')==1
            assert not await app.evaluate("DeskBrowserPreview.requests.some(r=>['/api/native/thread','/api/native/evidence-source','/api/native/task-response'].includes(r.path.split('?')[0]))")
            report.update(passed=True,initial_histories=4,initial_items=15 if rich else 13,supplied_tasks_after_deliberate_prepare=61,evidence_rows=45,native_original_reads=1,native_admissions=0,preparation_posts_during_navigation=0,source_unchanged_after_prepare=True,scope_matches={'task':1,'original':3},exact_quote_reference=reference,editor=editor)
        except Exception as error:
            import traceback
            report.update(error=str(error),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
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
