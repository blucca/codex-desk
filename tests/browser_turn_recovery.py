"""Private original-target review and blank/no-token recovery in a real browser."""
import asyncio
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from browser_turn_request import Fixture,ACCESS,TEXT,NEWER
from codex_desk.followups import followup_snapshot
from playwright.async_api import async_playwright

async def acceptance(browser,width,evidence):
    fixture=Fixture();fixture.start();s=fixture.identifier
    original_transport=fixture.transport
    # Genuine matching native event scope follows the explicitly reviewed target.
    def transport(method,params):
        original=fixture.runtime.store.get(s)['thread_id']
        if original=='native-original':return original_transport(method,params)
        fixture.requests.append({'method':method,'params':params})
        turn={'id':'reviewed-target-'+str(len(fixture.requests)),'status':'completed'}
        fixture.runtime._message({'method':'turn/started','params':{'threadId':original,'turn':turn}})
        fixture.runtime._message({'method':'turn/completed','params':{'threadId':original,'turn':turn}})
        return {'turn':turn}
    fixture.runtime.request=transport
    url=f'http://127.0.0.1:{fixture.server.server_port}'
    result={'width':width,'checks':[],'javascriptErrors':[]}
    context=await browser.new_context(viewport={'width':width,'height':844})
    page=await context.new_page();page.set_default_timeout(12000)
    page.on('pageerror',lambda e:result['javascriptErrors'].append(str(e)))
    posts=[]
    page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and urlsplit(r.url).path=='/api/turn' else None)
    async def selected():await page.wait_for_function('s=>selected===s && !opening',arg=s)
    async def settle():await page.wait_for_function('s=>!submitting.has(s) && !turnRequest()?.writing && !turnRequest()?.reading',arg=s)
    try:
        await page.goto(url+'/#access='+ACCESS);await page.wait_for_function('state.sessions.length===1')
        await page.locator('.session-row .session').click();await selected()
        fixture.behavior='rejected';await page.locator('#send').click();await settle()
        original=posts[-1].copy();assert len(fixture.requests)==1
        assert await page.evaluate('turnRequest().status')=='rejected'
        fixture.desk.store.update(s,thread_id='native-replacement',status='ready')
        fixture.runtime.thread_result={'thread':{'id':'native-replacement','turns':[]}}
        before=len(fixture.http);await page.reload();await selected()
        assert await page.evaluate('turnRequest().result.request.binding_mismatch')
        assert await page.locator('#turn-request-binding').is_visible()
        assert 'native-original' in await page.locator('#turn-request-original-binding').inner_text()
        assert 'native-replacement' in await page.locator('#turn-request-current-binding').inner_text()
        assert await page.locator('#turn-request-retry').is_disabled()
        assert len(fixture.requests)==1 and len(posts)==1
        assert not any(r['method']=='POST' for r in fixture.http[before:])
        await page.locator('#prompt').fill(NEWER)
        await page.locator('#prompt').focus();await page.locator('#prompt').evaluate('n=>n.setSelectionRange(1,8)')
        await page.evaluate('s=>persistDraft(s)',s)
        await page.screenshot(path=str(evidence/f'{width}-original-current-target-review.png'))
        await page.locator('#turn-request-new').click();await settle()
        assert await page.evaluate('!turnRequest()')
        assert await page.locator('#prompt').input_value()==NEWER
        assert len(fixture.requests)==1 and len(posts)==1
        fixture.behavior='accepted';await page.locator('#send').click();await settle()
        assert posts[-1]['token']!=original['token'] and len(fixture.requests)==2
        assert fixture.requests[-1]['params']['threadId']=='native-replacement'
        assert fixture.requests[-1]['params']['input'][0]['text']==NEWER
        assert followup_snapshot(fixture.desk.store,s)==fixture.preparation
        result['checks'].append({'case':'cold changed native target visible, reviewed new identity','original_retry_starts':0,'explicit_current_target_starts':1,'cold_get_only':True,'paused_queues_exact':True})

        # Original unknown is recoverable with a blank draft and no opaque token.
        fixture.desk.store.update(s,thread_id='native-original',status='ready')
        fixture.runtime.thread_result={'thread':{'id':'native-original','turns':[]}}
        fixture.behavior='unknown';await page.locator('#prompt').fill(TEXT)
        await page.locator('#send').click();await settle()
        assert await page.evaluate('turnRequest().status')=='needs_review'
        unknown=posts[-1].copy();count=len(fixture.requests)
        await page.locator('#prompt').fill('');await page.evaluate('s=>persistDraft(s)',s)
        await page.locator('#followups').evaluate('n=>n.open=true')
        await page.locator('#followup-clear').click()
        await page.wait_for_function('$("followup-count").textContent==="0"')
        fresh=await browser.new_context(viewport={'width':width,'height':844});other=await fresh.new_page()
        other.set_default_timeout(12000);boundary=len(fixture.http)
        await other.goto(url+'/#access='+ACCESS);await other.wait_for_function('state.sessions.length===1')
        await other.locator('.session-row .session').click();await other.wait_for_function('s=>selected===s && !opening',arg=s)
        assert await other.evaluate('turnRequest().token')==unknown['token']
        assert await other.locator('#prompt').input_value()==''
        assert await other.locator('#turn-request-rejected').is_visible()
        assert await other.locator('#send').is_enabled()
        assert len(fixture.requests)==count
        assert not any(r['method']=='POST' for r in fixture.http[boundary:])
        fixture.desk.home=fixture.path/'changed-home'
        await other.locator('#turn-request-recover').click()
        await other.wait_for_function('!turnRequest()?.reading')
        assert await other.evaluate('turnRequest().result.request.binding_mismatch')
        assert await other.locator('#turn-request-accepted').is_disabled()
        assert await other.locator('#turn-request-rejected').is_disabled()
        assert await other.locator('#turn-request-new').is_hidden()
        assert len(fixture.requests)==count
        await other.screenshot(path=str(evidence/f'{width}-blank-no-token-unknown-original-target.png'))
        assert not await other.evaluate('document.documentElement.scrollWidth>innerWidth')
        await fresh.close()
        result['checks'].append({'case':'blank fresh browser discovers unknown with no token or native open','turn_posts':0,'native_starts':0,'changed_home_review_and_new_task_blocked':True})
        assert not result['javascriptErrors'],result['javascriptErrors']
    finally:
        await context.close();fixture.doCleanups()
        result['posts']=posts;result['native_requests']=fixture.requests
        (evidence/f'result-{width}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

async def check():
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            results=[await acceptance(browser,w,evidence) for w in (390,1250)]
            (evidence/'result.json').write_text(json.dumps({'result':'PASS','cases':results},ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'result':'PASS','widths':[390,1250],'cases':4}),flush=True)
        finally:await browser.close()
if __name__=='__main__':asyncio.run(check())
