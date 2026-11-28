#!/usr/bin/env python3
"""Physical native-output glyph return across status headers, resize and held Refresh."""
import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from original_character_oracle import probe_character,assert_responsive_character
from check_browser_preview import static_server
from check_browser_preview_links import open_app, reload_app, reset_app
from check_browser_preview_session_reading import B, frames
from check_browser_preview_following_original import VISIBLE

QUOTE='HEADER OUTPUT PASSAGE — café🙂 项目.'
DRAFT='Keep B exact unsent Plan while inspecting original command output.'
VISIBLE=VISIBLE.replace('Child source line ', 'H').replace('Child decisive evidence — café🙂 项目 exact source.',QUOTE)

async def check(p,site,evidence,width,chromium,embedded,rich):
    mode='iframe' if embedded else 'direct';prefix=f'{width}-{mode}';other=390 if width==1250 else 1250
    report={'passed':False,'from_width':width,'to_width':other,'actual_iframe':embedded,'rich':rich,'observations':[],'checks':[]}
    errors=[];external=[]
    with static_server(site) as (url,received,escaped):
        browser=await p.chromium.launch(executable_path=chromium,headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        context=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844})
        page=await context.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)))
        async def isolate(route):
            if urlsplit(route.request.url).netloc!=urlsplit(url).netloc:external.append(route.request.url);await route.abort()
            else:await route.continue_()
        await context.route('**/*',isolate);app=None
        def item():return app.locator('.history-reader-item[data-turn-id="sample-child-turn"][data-item-id="sample-child-evidence"]')
        async def keyboard(locator):
            await locator.evaluate('n=>n.focus({preventScroll:true})');await locator.press('Enter');await frames(app)
        async def ready():
            await app.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'");await frames(app);await frames(app)
        async def browse():
            await app.locator('#browse').click();await app.wait_for_function("!$('history-search-submit').disabled")
            await app.locator('#history-source').select_option('archived');await app.wait_for_function("!$('history-search-submit').disabled")
        async def read():
            await app.locator('#history-id').fill('sample-child-thread');await app.locator('#history-id').press('Enter');await ready()
        async def back():
            await keyboard(app.locator('#history-reader-back'));await app.wait_for_function("!$('history-reader').open")
        async def viewport(w):
            await page.set_viewport_size({'width':w,'height':900 if w==1250 else 844});await frames(app)
        async def observe():
            v=await item().evaluate(VISIBLE)
            boundary=await app.evaluate("()=>{const c=DeskBrowserPreview.headerFixture.command();return DeskHistoryReader.textForItem({...c,aggregatedOutput:''}).length;}")
            v['output_boundary']=boundary
            if v['first_visible']:v['first_visible']['output_offset']=v['first_visible']['offset']-boundary
            return v
        async def passage():
            await app.locator('#history-reader-find-query').fill(QUOTE);await app.locator('#history-reader-find-query').press('Enter')
            await app.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')");await frames(app)
            start=int(await item().get_attribute('data-window-start'));assert 20000<start<40000,start
            rects=await item().locator('mark').evaluate('n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
            first,last=rects[0],rects[-1];a=(last['right']-.5,(last['top']+last['bottom'])/2);b=(first['left']+.5,(first['top']+first['bottom'])/2)
            if embedded:
                box=await page.locator('iframe').bounding_box();a=(a[0]+box['x'],a[1]+box['y']);b=(b[0]+box['x'],b[1]+box['y'])
            await page.mouse.move(*a);await page.mouse.down();await page.mouse.move(*b,steps=12);await page.mouse.up()
            assert await app.evaluate('getSelection().toString()')==QUOTE
            box=await item().locator('pre').bounding_box();x=box['x']+box['width']/2;y=min(box['y']+box['height']/2,750)
            if embedded:
                outer=await page.locator('iframe').bounding_box();x+=outer['x'];y+=outer['y']
            await page.mouse.move(x,y);await page.mouse.wheel(0,35);await page.wait_for_timeout(100);await frames(app)
            v=await observe();assert v['first_visible'] and v['selection']==QUOTE and v['inner']>0,v
            return v
        def same(before,after):
            assert before['first_visible'] and after['first_visible'],(before,after)
            for key in ('output_offset','char'):assert before['first_visible'][key]==after['first_visible'][key],(key,before,after)
            assert before['window_start']-before['output_boundary']==after['window_start']-after['output_boundary'],(before,after)
            assert [[t,i,o] for t,i,o,s in before['disclosures']]==[[t,i,o] for t,i,o,s in after['disclosures']],(before,after)
        async def unchanged(name):
            assert await app.evaluate('DeskBrowserPreview.snapshot()')==expected,name
            assert await app.evaluate('({selected,nativeThreadId,generation})')==owner
            assert await app.locator('#prompt').input_value()==DRAFT
            assert await app.locator('#turn-mode').input_value()=='plan'
            assert await app.evaluate('JSON.stringify(globalThis.DeskPreviewReadingFixture?.events||{})')==events
            assert await app.evaluate('localStorage.getItem(DeskBrowserPreview.reviewKey)')==review
            assert await app.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
            assert not errors and not external and not escaped,(errors,external,escaped)
            report['checks'].append(name);await page.screenshot(path=str(evidence/f'{prefix}-{name}.png'))
        async def held_refresh(to_width=None):
            await app.evaluate('DeskBrowserPreview.headerFixture.hold()')
            await keyboard(app.locator('#history-reader-refresh'))
            await app.wait_for_function('DeskBrowserPreview.headerFixture.held()')
            await keyboard(app.locator('#preview-header-reader-toggle'))
            if to_width:await viewport(to_width)
            await app.evaluate('DeskBrowserPreview.headerFixture.release()')
            await app.wait_for_function("!$('history-reader-refresh').disabled&&$('history-reader-status').textContent.startsWith('Original refreshed.')");await frames(app);await frames(app)
        try:
            app=await open_app(page,context,url,embedded);await app.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            assert await app.evaluate('DeskPreviewThreads.length')==4
            assert await app.evaluate('DeskPreviewThreads.reduce((n,t)=>n+t.turns.reduce((m,u)=>m+u.items.length,0),0)')==(15 if rich else 13)
            assert await app.evaluate('!!DeskBrowserPreview.fixture')==rich
            await app.evaluate("""async data=>{for(const name of ['checkout','docs','mobile'])await api('/api/import',{thread:'sample-'+name+'-thread'});
              await api('/api/draft',{session:data.b,text:data.draft,mode:'plan',revision:0});
              for(const mode of ['native','plan'])await api('/api/followups',{session:data.b,text:'Retained B '+mode,mode});await refresh();}""",{'b':B,'draft':DRAFT})
            await app.locator(f'.session-row[data-session="{B}"] .session').click();await app.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=B);await frames(app)
            expected=await app.evaluate('DeskBrowserPreview.snapshot()');owner=await app.evaluate('({selected,nativeThreadId,generation})')
            events=await app.evaluate('JSON.stringify(globalThis.DeskPreviewReadingFixture?.events||{})');review=await app.evaluate('localStorage.getItem(DeskBrowserPreview.reviewKey)')
            await app.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(10,22,'backward');n.scrollTop=25}");await frames(app)
            editor=await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")
            await app.locator('#preview-header-prepare').click()
            raw='\n'.join(f'H{n:04d}'+(' '+QUOTE if n==6450 else '') for n in range(10000))
            assert await app.evaluate('DeskBrowserPreview.headerFixture.command().aggregatedOutput')==raw
            await browse();await read();before=await passage();before_character=await probe_character(item(),raw,before['first_visible']['output_offset'],before['output_boundary']);await unchanged('in-progress-middle-native-output-with-exact-B')
            await back();await app.locator('#history-close').click();await app.locator('#preview-header-toggle').click()
            await viewport(other);await browse();await read();after=await observe();after_character=await probe_character(item(),raw,before_character['source_offset'],after['output_boundary']);assert_responsive_character(before_character,after_character)
            assert before['window_start']-before['output_boundary']==after['window_start']-after['output_boundary']
            assert [[t,i,o] for t,i,o,s in before['disclosures']]==[[t,i,o] for t,i,o,s in after['disclosures']]
            assert after['output_boundary']==before['output_boundary']-12
            assert after['query']=='' and after['selection']==''
            report['observations'].append({'case':'complete-header-opposite-width-fresh-reopen','before':before,'after':after,'before_character':before_character,'after_character':after_character})
            await unchanged('fresh-reopen-header-only-change-keeps-output-relative-native-glyph')
            before_refresh=await passage();refresh_character=await probe_character(item(),raw,before_refresh['first_visible']['output_offset'],before_refresh['output_boundary'])
            await held_refresh(width);after_refresh=await observe();refreshed_character=await probe_character(item(),raw,refresh_character['source_offset'],after_refresh['output_boundary']);assert_responsive_character(refresh_character,refreshed_character)
            assert before_refresh['window_start']-before_refresh['output_boundary']==after_refresh['window_start']-after_refresh['output_boundary']
            assert [[t,i,o] for t,i,o,s in before_refresh['disclosures']]==[[t,i,o] for t,i,o,s in after_refresh['disclosures']]
            assert after_refresh['output_boundary']==before_refresh['output_boundary']+12
            assert after_refresh['query']==QUOTE and after_refresh['selection']==QUOTE
            report['observations'].append({'case':'held-reverse-header-Refresh-with-opposite-width','before':before_refresh,'after':after_refresh,'before_character':refresh_character,'after_character':refreshed_character})
            await unchanged('held-refresh-resize-keeps-native-glyph-Find-and-backwards-Range')
            before_context=await observe();await keyboard(item().get_by_role('button',name='Read containing task',exact=True))
            await held_refresh();await keyboard(app.locator('#history-reader-task-passage'));after_context=await observe();same(before_context,after_context)
            assert after_context['query']==QUOTE and after_context['selection']==QUOTE
            report['observations'].append({'case':'containing-task-held-header-Refresh-passage-return','before':before_context,'after':after_context})
            await unchanged('containing-task-refresh-return-keeps-output-glyph-and-exact-passage')
            assert await app.evaluate('DeskBrowserPreview.headerFixture.command().aggregatedOutput')==raw
            assert not await app.locator('#history-reader-first-new').is_visible()
            await back();await app.locator('#history-close').click()
            assert await app.evaluate("({text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,mode:$('turn-mode').value})")==editor
            metadata=await app.evaluate('({place:JSON.parse(localStorage.getItem(DeskBrowserPreview.originalReadingKey)),frontier:JSON.parse(localStorage.getItem(DeskBrowserPreview.originalFrontierKey))})')
            serialized=json.dumps(metadata,ensure_ascii=False);assert QUOTE not in serialized and 'H6450' not in serialized and 'command_output_start' in serialized
            app=await reload_app(page,embedded);await app.locator('#prompt').wait_for();await app.wait_for_function('!opening&&!sessionReadingPending')
            assert not await app.locator('#history-reader').evaluate('n=>n.open')
            assert not await app.evaluate("DeskBrowserPreview.requests.some(r=>['/api/native/thread','/api/native/evidence-source','/api/native/task-response'].includes(r.path.split('?')[0]))")
            assert await app.evaluate('DeskBrowserPreview.snapshot()')==expected
            report.update(passed=True,unchanged_native_output=True,initial_histories=4,initial_items=15 if rich else 13,source_only_existing_item=True,native_admissions=0,auto_original_reads=0,metadata=metadata,editor=editor)
        except Exception as error:
            import traceback
            report.update(error=str(error),traceback=traceback.format_exc());await page.screenshot(path=str(evidence/f'{prefix}-failure.png'))
            if app:report['body']=await app.locator('body').inner_text()
        finally:
            if app:await app.evaluate('DeskBrowserPreview.headerFixture.release()')
            await context.close();await browser.close()
    (evidence/f'{prefix}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n');assert report['passed'],report.get('traceback')
    print(json.dumps({'passed':True,'width':width,'other_width':other,'iframe':embedded,'rich':rich,'checks':len(report['checks'])}),flush=True)
    return report

async def main(args):
    from playwright.async_api import async_playwright
    args.evidence.mkdir(parents=True,exist_ok=True)
    async with async_playwright() as p:reports=[await check(p,args.site,args.evidence,int(w),args.chromium,args.embedded,args.rich) for w in args.widths.split(',')]
    (args.evidence/'summary.json').write_text(json.dumps({'result':'PASS','reports':reports},indent=2,ensure_ascii=False)+'\n')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--site',required=True,type=Path);p.add_argument('--evidence',required=True,type=Path);p.add_argument('--embedded',action='store_true');p.add_argument('--rich',action='store_true');p.add_argument('--widths',default='1250,390');p.add_argument('--chromium',default=os.environ.get('DESK_CHROMIUM'));asyncio.run(main(p.parse_args()))
