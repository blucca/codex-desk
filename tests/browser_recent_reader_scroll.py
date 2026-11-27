"""390px long-binding original reading reaches text and Back by real gestures."""
import asyncio
import copy
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading

if os.environ.get('DESK_USE_INSTALLED') != '1':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def main():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    label=os.environ.get('DESK_SCROLL_LABEL','after')
    with tempfile.TemporaryDirectory(dir=root,prefix='recent-reader-scroll-') as tmp:
        folder=Path(tmp);home=folder/'home';home.mkdir();active=folder/'active';active.mkdir()
        (home/'config.toml').write_text('model="fixture"\n')
        missing=folder/'removed-original-project-with-a-retained-descriptive-folder-name'
        original={'id':'original-missing','name':'Removed-folder original decision','cwd':str(missing),'modelProvider':'fixture',
            'turns':[{'id':'original-turn','status':'completed','items':[
                {'id':'original-item','type':'agentMessage','text':'ORIGINAL EVIDENCE: keep three retries. This saved decision remains readable.'}]}]}
        desk=Desk('never-executed',home,folder/'state')
        desk.store.create(str(active),'default',identifier='active',name='Exact active Plan')
        desk.store.update('active',thread_id='active-native',status='saved',thread_saved=1,mode='plan',name_pending=0)
        save_draft(desk.store,'active','Exact unsent Plan stays here.','plan',0)
        add_followup(desk.store,'active','First prepared instruction.','native')
        add_followup(desk.store,'active','Second prepared instruction.','plan')
        saved=load_draft(desk.store,'active');queue=followup_snapshot(desk.store,'active');calls=[];errors=[]
        class Catalog:
            def request(self,method,params):
                calls.append(method);assert method in ('thread/list','thread/read')
                if method=='thread/list':return {'data':[{k:v for k,v in original.items() if k!='turns'}],'nextCursor':None}
                assert params=={'threadId':'original-missing','includeTurns':True};return {'thread':copy.deepcopy(original)}
        desk.catalog=lambda:Catalog()
        def opened(id):
            calls.append('explicit-open');assert id=='active';desk.store.update(id,status='running',provider='fixture',model='fixture')
            return {'thread':{'id':'active-native','cwd':str(active),'turns':[]},'model':'fixture','modelProvider':'fixture'}
        desk.open=opened;token=secrets.token_urlsafe(32)
        server=ThreadingHTTPServer(('127.0.0.1',0),handler(desk,access_token=token))
        worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start()
        async with async_playwright() as p:
            browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
            context=await browser.new_context(viewport={'width':390,'height':844},has_touch=True,is_mobile=True)
            page=await context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
            cdp=await context.new_cdp_session(page)
            async def state():return await page.evaluate("({selected,generation,nativeThreadId,prompt:$('prompt').value,mode:$('turn-mode').value,caret:[$('prompt').selectionStart,$('prompt').selectionEnd]})")
            async def unchanged():
                assert await state()==before
                assert load_draft(desk.store,'active')==saved and followup_snapshot(desk.store,'active')==queue
                assert calls.count('explicit-open')==1 and not errors
            async def metrics():return await page.evaluate("""()=>{
                const reader=$('history-reader'),r=reader.getBoundingClientRect(),back=$('history-reader-back').getBoundingClientRect();
                const text=reader.querySelector('.history-reader-text'),t=text.getBoundingClientRect(),body=$('history-reader-body').getBoundingClientRect();
                return {overflowY:getComputedStyle(reader).overflowY,scrollTop:reader.scrollTop,
                    scrollHeight:reader.scrollHeight,clientHeight:reader.clientHeight,backTop:back.top,backBottom:back.bottom,
                    backVisible:back.top>=r.top && back.bottom<=r.bottom && back.bottom<=innerHeight,
                    originalText:text.textContent,textFullyVisible:t.top>=Math.max(r.top,body.top) && t.bottom<=Math.min(r.bottom,body.bottom),
                    textTop:t.top,textBottom:t.bottom,bodyTop:body.top,bodyBottom:body.bottom,
                    bodyX:body.left+body.width/2,bodyY:body.top+body.height/2,x:r.left+4,y:Math.min(r.bottom-50,r.top+r.height*.55),readerTop:r.top,readerBottom:r.bottom};
            }""")
            async def swipe(x,y,distance):
                await cdp.send('Input.dispatchTouchEvent',{'type':'touchStart','touchPoints':[{'x':x,'y':y}]})
                for step in range(1,9):
                    await cdp.send('Input.dispatchTouchEvent',{'type':'touchMove','touchPoints':[{'x':x,'y':y-distance*step/8}]})
                    await page.wait_for_timeout(45)
                await page.wait_for_timeout(250)
                await cdp.send('Input.dispatchTouchEvent',{'type':'touchEnd','touchPoints':[]})
            async def gesture(kind):
                box=await metrics()
                if kind=='wheel':
                    await page.mouse.move(box['x'],box['y']);await page.mouse.wheel(0,850)
                else:await swipe(box['x'],box['y'],340)
                await page.wait_for_timeout(350)
                outer=await metrics()
                if label!='before':
                    # Read the evidence in the reader's existing inner body.
                    # Use a real gesture, not focus or a scrollTop assignment.
                    distance=max(0,outer['textTop']-outer['bodyTop']-8)
                    if kind=='wheel':
                        await page.mouse.move(outer['bodyX'],outer['bodyY']);await page.mouse.wheel(0,distance)
                    else:await swipe(outer['bodyX'],outer['bodyY'],distance+12)
                    await page.wait_for_timeout(350)
                result=await metrics();result['outerGestureBackVisible']=outer['backVisible'];return result
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}#access={token}')
                await page.locator('.session-row[data-session="active"] .session').click()
                await page.wait_for_function("selected==='active' && !opening && $('followup-count').textContent==='2'")
                before=await state();await page.locator('#show-recent').click()
                await page.wait_for_function("$('recent-work').open && $('home-list').getAttribute('aria-busy')==='false'")
                read=page.locator('#home-list [data-thread="original-missing"] .native-read')
                await read.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                initial=await metrics();await page.screenshot(path=str(evidence/f'{label}-initial-390.png'))
                wheel=await gesture('wheel');await unchanged();await page.screenshot(path=str(evidence/f'{label}-wheel-390.png'))
                # Reopen the same retained source; do not use a DOM scrollTop
                # assignment or focus scrolling to simulate the touch gesture.
                await page.keyboard.press('Escape');assert await read.evaluate('(n)=>n===document.activeElement')
                await read.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                touch=await gesture('touch');await unchanged();await page.screenshot(path=str(evidence/f'{label}-touch-390.png'))
                receipt={'label':label,'width':390,'initial':initial,'wheel':wheel,'touch':touch,
                    'selected_plan_native_caret_and_two_queues_unchanged':True,'browser_errors':errors}
                (evidence/f'{label}.json').write_text(json.dumps(receipt,indent=2)+'\n')
                if label=='before':
                    assert not wheel['backVisible'] and not touch['backVisible'],receipt
                    assert wheel['scrollTop']==0 and touch['scrollTop']==0,receipt
                    print(json.dumps({'result':'OBSERVED_BLOCKED','label':label,'wheel_back_visible':False,'touch_back_visible':False}),flush=True)
                else:
                    assert wheel['backVisible'] and touch['backVisible'],receipt
                    assert wheel['textFullyVisible'] and touch['textFullyVisible'],receipt
                    assert wheel['scrollTop']>0 and touch['scrollTop']>0,receipt
                    assert 'ORIGINAL EVIDENCE' in wheel['originalText'] and 'ORIGINAL EVIDENCE' in touch['originalText']
                    await page.locator('#history-reader-back').click();assert await read.evaluate('(n)=>n===document.activeElement')
                    await page.locator('#recent-return').click();assert await page.locator('#show-recent').evaluate('(n)=>n===document.activeElement')
                    await unchanged();print(json.dumps({'result':'PASS','label':label,'wheel_and_touch_reach_text_and_back':True}),flush=True)
            finally:
                await context.close();await browser.close();server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()


if __name__=='__main__':asyncio.run(main())
