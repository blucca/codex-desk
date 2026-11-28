#!/usr/bin/env python3
"""Previous fresh original → supplied identities → exact first new → responsive passage return."""
import argparse
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from build_browser_preview import CHILD,CHILD_TURN,CHILD_ITEM,CHILD_QUOTE
from check_browser_preview import static_server
from check_browser_preview_links import open_app,reload_app,reset_app
from check_browser_preview_session_reading import A,B,C,frames

TITLE='linked retry original'
DRAFT='Keep B documentation Plan unsent while following newly supplied original items.'

# Measure actual literal UTF16 positions with text-node Ranges, never inferred lines/pixels.
VISIBLE=r'''n=>{
 const p=n.querySelector('pre'),reader=$('history-reader'),body=$('history-reader-body');
 const pr=p.getBoundingClientRect(),br=body.getBoundingClientRect(),rr=reader.getBoundingClientRect();
 const clip={left:Math.max(pr.left,br.left,rr.left,0),right:Math.min(pr.right,br.right,rr.right,innerWidth),
   top:Math.max(pr.top,br.top,rr.top,0),bottom:Math.min(pr.bottom,br.bottom,rr.bottom,innerHeight)};
 const text=p.textContent,start=Number(n.dataset.windowStart),walker=document.createTreeWalker(p,NodeFilter.SHOW_TEXT),nodes=[];
 let offset=0,node;while(node=walker.nextNode()){nodes.push({node,start:offset,end:offset+node.data.length});offset+=node.data.length;}
 function point(at,right=false){for(const q of nodes)if(at<q.end||!right&&at===q.end)return [q.node,at-q.start];
   const last=nodes.at(-1);return last?[last.node,last.node.data.length]:null;}
 function rects(a,b){const first=point(a,true),last=point(b);if(!first||!last)return [];
   const r=document.createRange();r.setStart(...first);r.setEnd(...last);return [...r.getClientRects()];}
 const inside=r=>r.width>0&&r.height>0&&r.right>clip.left&&r.left<clip.right&&r.bottom>clip.top&&r.top<clip.bottom;
 let first=null;for(const match of text.matchAll(/Child source line (\d{4})[^\n]*/g)){
   if(!rects(match.index,match.index+match[0].length).some(inside))continue;
   let at=match.index;for(const char of match[0]){const end=at+char.length,r=rects(at,end).find(inside);
     if(r){first={offset:start+at,char,line:Number(match[1]),top:r.top};break;}at=end;}if(first)break;}
 const quote='Child decisive evidence — café🙂 项目 exact source.',at=text.indexOf(quote),boxes=at<0?[]:rects(at,at+quote.length);
 return {width:innerWidth,first_visible:first,window_start:start,inner:p.scrollTop,body:body.scrollTop,outer:reader.scrollTop,
   top:n.getBoundingClientRect().top,query:$('history-reader-find-query').value,selection:getSelection().toString(),
   quote_visible:boxes.some(inside),quote_fully_visible:boxes.length>0&&boxes.every(r=>r.left>=clip.left&&r.right<=clip.right&&r.top>=clip.top&&r.bottom<=clip.bottom),
   disclosures:[...body.querySelectorAll('.history-reader-item')].map(e=>[e.dataset.turnId,e.dataset.itemId,e.open,e.dataset.windowStart])};
}'''

async def check(p,site,evidence,width,chromium,embedded,rich):
    mode='iframe' if embedded else 'direct';prefix=f'{width}-{mode}';other=390 if width==1250 else 1250
    report={'passed':False,'from_width':width,'to_width':other,'actual_iframe':embedded,'rich':rich,'checks':[]};errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844},permissions=['clipboard-read','clipboard-write'])
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None;expected=None;owner=None
        def item():return app.locator(f'.history-reader-item[data-turn-id="{CHILD_TURN}"][data-item-id="{CHILD_ITEM}"]')
        async def visible():return await item().evaluate(VISIBLE)
        async def state():return await app.evaluate('DeskBrowserPreview.snapshot()')
        async def ready():
            await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app);await frames(app)
        async def calls(boundary=0):
            return [r for r in await app.evaluate('n=>DeskBrowserPreview.requests.slice(n)',boundary) if urlsplit(r['path']).path in ('/api/native/thread','/api/native/evidence-source','/api/native/task-response')]
        async def read():
            boundary=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#native-list .native-read').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#native-list .native-read').press('Enter');await ready()
            reads=await calls(boundary);assert len(reads)==1 and reads[0]['path']==f'/api/native/thread?id={CHILD}',reads
        async def back():
            await app.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#history-reader-back').press('Enter')
            await app.wait_for_function("!$('history-reader').open");await frames(app)
        async def browse():
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-source').select_option('archived');await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-search').fill(TITLE);await app.locator('#history-search').press('Enter');await app.wait_for_function("!$('history-search-submit').disabled")
            assert await app.locator('#native-list .native-read').count()==1
        async def quote(occurrence):
            await app.locator('#history-reader-find-query').fill(CHILD_QUOTE);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
            if occurrence==2:await page.keyboard.press('F3');await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
            await item().locator('mark').evaluate("n=>n.scrollIntoView({block:'center',inline:'nearest'})");await frames(app)
        async def pointer_select():
            rects=await item().locator('mark').evaluate("n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))")
            first,last=rects[0],rects[-1];start=(last['right']-.5,(last['top']+last['bottom'])/2);end=(first['left']+.5,(first['top']+first['bottom'])/2)
            if embedded:
                box=await page.locator('iframe').bounding_box();start=(start[0]+box['x'],start[1]+box['y']);end=(end[0]+box['x'],end[1]+box['y'])
            await page.mouse.move(*start);await page.mouse.down();await page.mouse.move(*end,steps=12);await page.mouse.up()
            assert await app.evaluate('getSelection().toString()')==CHILD_QUOTE
        async def checkpoint(name):
            assert not errors and not external and not escaped,(errors,external,escaped)
            assert await state()==expected,name+' preparation changed'
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert await app.locator('#prompt').input_value()==expected['drafts'][B]['text']
            assert await app.locator('#turn-mode').input_value()=='plan'
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
            print(json.dumps({'passed':name,'width':width,'mode':mode,'rich':rich}),flush=True)
        def same_native(before,after):
            assert before['window_start']==after['window_start'] and before['disclosures']==after['disclosures'][:len(before['disclosures'])],(before,after)
            assert before['first_visible'] and after['first_visible'],(before,after)
            assert before['first_visible']['offset']==after['first_visible']['offset'],(before,after)
            assert before['first_visible']['char']==after['first_visible']['char'],(before,after)
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
            assert set(s['id'] for s in expected['sessions'])=={A,B,C}
            await browse();await read();assert not await app.locator('#history-reader-first-new').is_visible()
            # Exact saved first occurrence remains explicit; ordinary reading memory will be later.
            await quote(1);await pointer_select()
            await item().locator('.history-reader-review-evidence').evaluate('n=>n.focus({preventScroll:true})');await item().locator('.history-reader-review-evidence').press('Enter')
            await app.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
            ref=await app.evaluate('DeskEvidencePreparation.state().reference');assert ref['quote']==CHILD_QUOTE
            await app.locator('#evidence-preparation-append').click();await app.wait_for_function("!$('evidence-preparation').open");await frames(app)
            expected=await state();assert expected['drafts'][B]['revision']==2 and expected['followups']==queues
            await quote(2);await pointer_select();previous=await visible();assert previous['window_start']>20000 and previous['first_visible'] and previous['quote_fully_visible']
            await back()
            previous_frontier=await app.evaluate("JSON.parse(localStorage.getItem(DeskBrowserPreview.originalFrontierKey))")
            assert previous_frontier['snapshots'][0]['snapshot']=={'item_count':3,'boundary':{'turn_id':CHILD_TURN,'item_id':'sample-child-evidence'}}
            await checkpoint('previous-fresh-original-later-native-passage-with-B-Plan-two-queues')
            # User explicitly supplies sample items while no original is open. No source read/action admission.
            await app.locator('#history-close').click()
            boundary=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#preview-supply-original').click();assert await calls(boundary)==[]
            assert await app.evaluate('DeskPreviewThreads.at(-1).turns.length')==3
            await page.set_viewport_size({'width':other,'height':900 if other==1250 else 844});await frames(app)
            await browse();await read();reopened=await visible();same_native(previous,reopened)
            assert reopened['query']=='' and reopened['selection']==''
            assert 'New since previous fresh original read · 5 newly supplied native items.'==await app.locator('#history-reader-new-status').inner_text()
            assert await app.locator('#history-reader-first-new').is_visible()
            report.update(previous_view=previous,reopened_view=reopened)
            await checkpoint('deliberate-fresh-read-after-supply-resize-keeps-actual-first-visible-character')
            # New intent/Find/real backwards Range is restored by existing item/passage return.
            await quote(2);await pointer_select();before_new=await visible();boundary=await app.evaluate('DeskBrowserPreview.requests.length')
            await app.locator('#history-reader-first-new').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#history-reader-first-new').press('Enter');await frames(app)
            target=app.locator('.history-reader-target');assert await target.get_attribute('data-turn-id')=='sample-child-supplied-turn'
            assert await target.get_attribute('data-item-id')=='sample-child-supplied-question'
            assert 'FIRST NEW SAMPLE ORIGINAL ITEM' in await target.inner_text()
            assert await calls(boundary)==[]
            await checkpoint('read-first-newly-supplied-exact-native-instruction-not-later-final')
            await app.locator('#history-reader-task-passage').click();await frames(app);returned=await visible();same_native(before_new,returned)
            for field in ('inner','body','outer','top'):assert abs(before_new[field]-returned[field])<=2,(field,before_new,returned)
            assert returned['query']==CHILD_QUOTE and returned['selection']==CHILD_QUOTE
            assert await calls(boundary)==[]
            await checkpoint('return-to-original-passage-keeps-native-window-Find-Range-and-B')
            await back();await app.locator('#history-close').click()
            if not await app.locator('#draft-evidence').evaluate('n=>n.open'):await app.locator('#draft-evidence summary').click()
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(15,26,'backward');n.scrollTop=35}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value,window:scrollY})")
            frontier_raw=await app.evaluate('localStorage.getItem(DeskBrowserPreview.originalFrontierKey)')
            await app.locator('#draft-evidence-list button').evaluate('n=>n.focus({preventScroll:true})');await app.locator('#draft-evidence-list button').press('Enter');await ready()
            assert await app.locator('#history-reader-saved-evidence-quote').text_content()==CHILD_QUOTE
            assert await item().locator('mark').text_content()==CHILD_QUOTE
            assert (await visible())['window_start']<reopened['window_start']
            assert not await app.locator('#history-reader-first-new').is_visible()
            assert await app.evaluate('localStorage.getItem(DeskBrowserPreview.originalFrontierKey)')==frontier_raw
            await back();assert await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value,window:scrollY})")==editor
            await checkpoint('exact-saved-first-quote-outranks-later-place-keeps-B-editor-and-frontier')
            meta=await app.evaluate('({place:JSON.parse(localStorage.getItem(DeskBrowserPreview.originalReadingKey)),frontier:JSON.parse(localStorage.getItem(DeskBrowserPreview.originalFrontierKey))})')
            raw=json.dumps(meta,ensure_ascii=False);assert CHILD_QUOTE not in raw and 'Child source line' not in raw and 'findQuery' not in raw
            assert meta['frontier']['snapshots'][0]['snapshot']['item_count']==8
            assert 'visible_character' in raw
            before_reload=expected;app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function('!opening&&!sessionReadingPending')
            assert not await app.locator('#history-reader').evaluate('n=>n.open') and await calls()==[]
            if await app.evaluate('selected')!=B:
                await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B)
            assert await state()==before_reload
            owner=await app.evaluate('({selected,nativeThreadId,generation})')
            await checkpoint('ordinary-reload-keeps-metadata-and-B-with-zero-automatic-original-read-run')
            allcalls=await app.evaluate('DeskBrowserPreview.requests');assert not [r for r in allcalls if r['method']=='POST' and urlsplit(r['path']).path not in ('/api/open',)]
            # Reset deletes own frontier/place/preparation keys, never unrelated installed keys.
            await app.evaluate("localStorage.setItem('codex-desk-original-frontiers-v1','installed unchanged');localStorage.setItem('independent-sample-key','same origin unchanged')")
            app=await reset_app(page,app,embedded)
            assert await app.evaluate('localStorage.getItem(DeskBrowserPreview.originalFrontierKey)') is None
            assert await app.evaluate('localStorage.getItem(DeskBrowserPreview.originalReadingKey)') is None
            assert await app.evaluate("localStorage.getItem('codex-desk-original-frontiers-v1')")=='installed unchanged'
            assert await app.evaluate("localStorage.getItem('independent-sample-key')")=='same origin unchanged'
            assert not errors and not external and not escaped,(errors,external,escaped)
            report.update(passed=True,sample_histories=4,initial_sample_items=15 if rich else 13,explicit_supplied_items=5,native_admissions=0,auto_original_reads=0,metadata_only=True,reset_preview_namespace_only=True)
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
