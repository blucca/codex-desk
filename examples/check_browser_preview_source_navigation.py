#!/usr/bin/env python3
"""Maintained known ID -> supplied instruction -> response -> current Plan source return."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from build_browser_preview import CHILD, CHILD_TURN, CHILD_ITEM, CHILD_QUOTE
from check_browser_preview import static_server
from check_browser_preview_links import open_app
from check_browser_preview_session_reading import A, B, C, frames

QUERY='reported retry result'
DRAFT='Keep B documentation Plan unsent; verify the launch command first.'

async def check(p,site,evidence,width,chromium,embedded):
    mode='iframe' if embedded else 'direct';prefix=f'{width}-{mode}'
    report={'passed':False,'width':width,'actual_iframe':embedded,'checks':[]};errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844},permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None;expected=None
        async def saved():return await app.evaluate('DeskBrowserPreview.snapshot()')
        async def ready():await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app)
        def target(item=CHILD_ITEM):return app.locator(f'.history-reader-item[data-turn-id="{CHILD_TURN}"][data-item-id="{item}"]')
        async def checkpoint(name):
            assert not errors and not external and not escaped,(errors,external,escaped)
            assert await saved()==expected,name+' preparation changed'
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert {s['id'] for s in expected['sessions']}=={A,B,C}
            assert 'desk-'+CHILD not in expected['drafts'] and 'desk-'+CHILD not in expected['followups']
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
            print(json.dumps({'passed':name,'width':width,'mode':mode}),flush=True)
        async def passage():
            return await target().evaluate("""n=>({start:n.dataset.windowStart,inner:n.querySelector('pre').scrollTop,
             outer:$('history-reader').scrollTop,body:$('history-reader-body').scrollTop,
             selection:getSelection().toString(),find:$('history-reader-find-status').textContent})""")
        async def pointer_select():
            mark=target().locator('mark');await mark.evaluate("n=>n.scrollIntoView({block:'center',inline:'nearest'})");await frames(app)
            rects=await mark.evaluate("""n=>{const r=document.createRange();r.selectNodeContents(n);return [...r.getClientRects()].filter(x=>x.width>0&&x.height>0).map(x=>({left:x.left,right:x.right,top:x.top,bottom:x.bottom}));}""")
            assert rects;first,last=rects[0],rects[-1];start=(first['left']+.5,(first['top']+first['bottom'])/2);end=(last['right']-.5,(last['top']+last['bottom'])/2)
            if width==390:start,end=end,start
            if embedded:
                box=await page.locator('iframe').bounding_box();start=(start[0]+box['x'],start[1]+box['y']);end=(end[0]+box['x'],end[1]+box['y'])
            await page.mouse.move(*start);await page.mouse.down();await page.mouse.move(*end,steps=12);await page.mouse.up()
            assert await app.evaluate('getSelection().toString()')==CHILD_QUOTE
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("document.querySelector('#home-list')?.getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==13
            assert not await app.evaluate('!!DeskBrowserPreview.fixture')
            await app.evaluate("""async data=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});
             await api('/api/draft',{session:data.b,text:data.draft,mode:'plan',revision:0});
             for(const mode of ['native','plan'])await api('/api/followups',{session:data.b,text:'Keep existing B '+mode+' instruction',mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            expected=await saved();owner=await app.evaluate('({selected,nativeThreadId,generation})');queue=expected['followups'];home=await app.evaluate('async()=>(await api("/api/native/home")).home_namespace')
            await checkpoint('existing-four-histories-and-current-B-Plan-two-paused-instructions')
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-search').fill('documentation');await app.locator('#history-search').press('Enter');await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#native-list .native-row').count()==1
            title_state=await app.evaluate("({query:$('history-search').value,rows:$('native-list').textContent,summary:$('history-summary').textContent,cursor:nativeCursor})")
            await app.locator('#history-id').fill(CHILD);await app.locator('#history-id').evaluate("n=>{n.focus();n.setSelectionRange(2,8,'backward')}")
            boundary=await app.evaluate('DeskBrowserPreview.requests.length');await app.locator('#history-id').press('Enter');await ready()
            calls=await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary)
            assert [r['path'] for r in calls if urlsplit(r['path']).path=='/api/native/evidence-source']==[f'/api/native/evidence-source?home={home}&thread={CHILD}']
            assert all(r['method']=='GET' for r in calls)
            assert '/sample/projects/checkout-child' in await app.locator('#history-reader-binding').text_content()
            await checkpoint('known-child-ID-one-exact-original-GET-keeps-title-filter-and-current-B')
            await app.locator('#history-reader-copy-native-id').click();await app.locator('#history-reader-native-id-status').filter(has_text='copied').wait_for()
            bare_id=await app.evaluate('navigator.clipboard.readText()');assert bare_id==CHILD
            await app.locator('#history-reader-back').click();await app.wait_for_function("!$('history-reader').open")
            await app.locator('#history-id').fill(bare_id);await app.locator('#history-id').evaluate("n=>{n.focus();n.setSelectionRange(2,8,'backward')}")
            boundary=await app.evaluate('DeskBrowserPreview.requests.length');await app.locator('#history-id').press('Enter');await ready()
            calls=await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary)
            assert [r['path'] for r in calls if urlsplit(r['path']).path=='/api/native/evidence-source']==[f'/api/native/evidence-source?home={home}&thread={CHILD}']
            assert all(r['method']=='GET' for r in calls)
            await checkpoint('actual-bare-native-ID-copy-paste-opens-same-fourth-original')
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')");await page.keyboard.press('F3');await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
            await pointer_select();await target().locator('.history-reader-task-open').scroll_into_view_if_needed();original_passage=await passage()
            await target().locator('.history-reader-task-open').click();await app.locator('#history-reader-instruction-query').fill(QUERY);await app.locator('#history-reader-instruction-query').press('Enter')
            assert await app.locator('.history-reader-instruction-match').count()==1
            matches=await app.locator('.history-reader-instruction-match').text_content();assert CHILD_TURN in matches and 'sample-child-question' in matches
            await app.get_by_role('button',name='Read task for this instruction',exact=True).click()
            await app.get_by_role('button',name='Read full instruction',exact=True).click();await frames(app)
            assert await target('sample-child-question').locator('mark').text_content()==QUERY
            await app.locator('#history-reader-task-return').click();await app.get_by_role('button',name='Read this task response',exact=True).click();await frames(app)
            assert await target().count()==1 and 'Final answer' in await app.locator('#history-reader-task-status').text_content()
            await target().get_by_role('button',name='Copy full item text',exact=True).click();await target().locator('.history-reader-copy-status').filter(has_text='copied').wait_for()
            copied=await app.evaluate('navigator.clipboard.readText()');source=await app.evaluate('id=>DeskPreviewThreads.find(t=>t.id===id).turns[0].items.find(i=>i.type==="agentMessage").text',CHILD)
            assert copied=='Codex\n'+source;report['full_copy_characters']=len(copied)
            await checkpoint('literal-own-instruction-and-full-final-response')
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')");await page.keyboard.press('F3');await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
            await pointer_select();await target().locator('.history-reader-review-evidence').scroll_into_view_if_needed();response_passage=await passage()
            await target().locator('.history-reader-review-evidence').click();await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
            review=await app.evaluate('DeskEvidencePreparation.state()');reference=review['reference']
            assert review['destination']['session']==B and review['destination']['mode']=='plan'
            assert reference['thread_id']==CHILD and reference['turn_id']==CHILD_TURN and reference['item_id']==CHILD_ITEM
            assert reference['quote']==CHILD_QUOTE and reference['native_home']==home and reference['quote_start']==copied.rfind(CHILD_QUOTE)
            boundary=await app.evaluate('DeskBrowserPreview.requests.length');await app.locator('#evidence-preparation-append').click();await app.wait_for_function("!$('evidence-preparation').open");await frames(app)
            updated=await saved();assert updated['drafts'][B]['mode']=='plan' and updated['drafts'][B]['text'].startswith(DRAFT)
            assert updated['drafts'][B]['revision']==expected['drafts'][B]['revision']+1 and updated['followups']==queue
            expected=updated
            parsed=await app.evaluate('DeskEvidencePreparation.parse($("prompt").value)');assert len(parsed)==1 and parsed[0]['reference']==reference
            calls=await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary);assert [urlsplit(r['path']).path for r in calls if r['method']=='POST']==['/api/draft']
            response_after=await passage();report['response_append_view']={'before':response_passage,'after':response_after}
            assert response_after==response_passage,(response_passage,response_after)
            await checkpoint('one-reviewed-second-child-quote-appends-to-existing-B-Plan-without-sending')
            await app.locator('#history-reader-task-return').click();await app.locator('#history-reader-task-instructions-return').click()
            assert await app.locator('#history-reader-instruction-query').input_value()==QUERY
            assert await app.locator('.history-reader-instruction-match').text_content()==matches
            await app.locator('#history-reader-task-passage').click();await frames(app)
            assert await passage()==original_passage,(original_passage,await passage())
            await checkpoint('literal-own-instruction-and-final-response-return-to-matches-and-exact-second-passage')

            await app.locator('#history-reader-back').click();await app.wait_for_function("!$('history-reader').open")
            assert await app.evaluate("({query:$('history-search').value,rows:$('native-list').textContent,summary:$('history-summary').textContent,cursor:nativeCursor})")==title_state
            assert await app.locator('#history-id').input_value()==CHILD
            assert await app.evaluate("document.activeElement===$('history-id')&&$('history-id').selectionStart===2&&$('history-id').selectionEnd===8&&$('history-id').selectionDirection==='backward'")
            await checkpoint('exact-known-ID-title-origin-return-retains-accepted-current-B-preparation')
            await app.locator('#history-close').click()
            if not await app.locator('#draft-evidence').evaluate('n=>n.open'):await app.locator('#draft-evidence summary').click()
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,24,'backward');n.scrollTop=35}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")
            await app.locator('#draft-evidence-list button').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#draft-evidence-list button').press('Enter');await ready()
            assert await app.locator('#history-reader-saved-evidence-quote').text_content()==CHILD_QUOTE and await target().locator('mark').text_content()==CHILD_QUOTE
            await app.locator('#history-reader-back').click();await app.wait_for_function("!$('history-reader').open");await frames(app)
            assert await app.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")==editor
            await checkpoint('actual-saved-child-reference-return-keeps-current-B-editor-caret-scroll')
            calls=await app.evaluate('DeskBrowserPreview.requests');assert not [r for r in calls if r['method']=='POST' and urlsplit(r['path']).path not in ('/api/import','/api/open','/api/draft','/api/followups')]
            assert not [r for r in calls if r['method']=='POST' and (r['data'].get('thread')==CHILD or r['data'].get('session')=='desk-'+CHILD)]
            report.update(passed=True,native_admissions=0,child_task_rows=0,sample_histories=4,sample_items=13,instruction_query=QUERY,quote=CHILD_QUOTE,source_id=CHILD)
        except Exception as e:
            import traceback
            report.update(error=str(e),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
            if app:report['body']=await app.locator('body').inner_text()
        finally:await context.close();await browser.close()
    (evidence/f'{prefix}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');assert report['passed'],report.get('traceback');return report

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:reports=[await check(p,args.site,args.evidence,int(w),args.chromium,args.embedded) for w in args.widths.split(',')]
    (args.evidence/'summary.json').write_text(json.dumps({'result':'PASS','reports':reports},indent=2,ensure_ascii=False)+'\n')
if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--site',required=True,type=Path);parser.add_argument('--evidence',required=True,type=Path);parser.add_argument('--embedded',action='store_true');parser.add_argument('--widths',default='1250,390');parser.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'));asyncio.run(main(parser.parse_args()))
