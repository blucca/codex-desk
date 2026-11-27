"""Ordinary Run browser acceptance: actual HTTP, Runtime.turn and event reduction.

Only native RPC transport is controlled. Scratch and evidence are workspace scoped.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import threading
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit
if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_approval_lifecycle import NativeHTTPFixture
from unittest.mock import Mock
from codex_desk.server import handler
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

TEXT='Review exactly one project decision — 保留  '
NEWER='Newer unsent Plan — 保留  '
ACCESS='controlled-local-turn-access'

class Fixture(NativeHTTPFixture):
    def runTest(self): pass
    def start(self):
        self.setUp(); self.close_server()
        self.desk.store.update(self.identifier,status='ready',thread_saved=1)
        save_draft(self.desk.store,self.identifier,TEXT,'plan',0)
        add_followup(self.desk.store,self.identifier,'Paused exact Work','native')
        add_followup(self.desk.store,self.identifier,'Paused exact Plan','plan')
        self.preparation=followup_snapshot(self.desk.store,self.identifier)
        self.http=[]; self.replies=[]; self.behavior='accepted'; self.drop=False; self.hold_reply=False
        self.release=threading.Event(); self.release.set(); self.entered=threading.Event()
        self.native_release=threading.Event(); self.native_release.set(); self.native_entered=threading.Event()
        self.runtime.lock=threading.Lock(); self.runtime.pending={}
        self.runtime.reader=Mock(); self.runtime.stderr_reader=Mock()
        self.runtime.request=self.transport
        owner=self
        class Handler(handler(self.desk,ACCESS)):
            def do_GET(self):
                owner.http.append({'method':'GET','path':self.path}); super().do_GET()
            def do_POST(self):
                owner.http.append({'method':'POST','path':self.path}); super().do_POST()
            def reply(self,value,status=200):
                if self.path=='/api/turn' and status==200:
                    owner.replies.append(copy.deepcopy(value)); owner.entered.set()
                    if owner.hold_reply: assert owner.release.wait(25),'Reply gate was not released'
                    if owner.drop: owner.drop=False; self.close_connection=True; return
                super().reply(value,status)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.server_thread=threading.Thread(target=self.server.serve_forever,kwargs={'poll_interval':.01},daemon=True)
        self.server_thread.start()
    def transport(self,method,params):
        assert method=='turn/start',method
        self.requests.append({'method':method,'params':copy.deepcopy(params)})
        self.native_entered.set(); assert self.native_release.wait(25),'Native gate was not released'
        if self.behavior=='rejected': raise NativeRequestRejected('Controlled known native rejection')
        if self.behavior=='unknown': raise NativeRequestUnknown('Controlled no-event unknown admission')
        turn='accepted-'+str(len(self.requests))
        with self.runtime.lifecycle_lock:
            for event in (
                {'method':'turn/started','params':{'threadId':'native-original','turn':{'id':turn,'status':'inProgress'}}},
                {'method':'item/completed','params':{'threadId':'native-original','turnId':turn,'item':{'id':'user-'+turn,'type':'userMessage','content':[{'type':'text','text':params['input'][0]['text']}]}}},
                {'method':'item/completed','params':{'threadId':'native-original','turnId':turn,'item':{'id':'answer-'+turn,'type':'agentMessage','text':'Controlled result '+turn}}},
                {'method':'turn/completed','params':{'threadId':'native-original','turn':{'id':turn,'status':'completed'}}},
            ): self.runtime._message(event)
        if self.behavior=='started-unknown': raise NativeRequestUnknown('Lost native reply after proven completion')
        return {'turn':{'id':turn,'status':'inProgress'}}

async def acceptance(browser,width,evidence):
    fixture=Fixture(); fixture.start(); session=fixture.identifier
    url=f'http://127.0.0.1:{fixture.server.server_port}'
    result={'width':width,'checks':[],'javascriptErrors':[]}
    context=await browser.new_context(viewport={'width':width,'height':844})
    page=await context.new_page(); page.set_default_timeout(12000)
    page.on('pageerror',lambda e:result['javascriptErrors'].append(str(e)))
    posts=[]
    page.on('request',lambda r:posts.append(r.post_data_json) if r.method=='POST' and urlsplit(r.url).path=='/api/turn' else None)
    async def settled():
        await page.wait_for_function('s=>!submitting.has(s)',arg=session)
    async def click_run():
        await page.locator('#send').click(); await settled()
    async def queue_exact():
        assert followup_snapshot(fixture.desk.store,session)==fixture.preparation
    async def receipt():
        token=posts[-1]['token']
        return await page.evaluate('p=>api("/api/turn/request?session="+encodeURIComponent(p.session)+"&token="+encodeURIComponent(p.token))',{'session':session,'token':token})
    try:
        await page.goto(url+'/#access='+ACCESS)
        await page.wait_for_function('state.sessions.length===1')
        await page.locator('.session-row .session').click()
        await page.wait_for_function('s=>selected===s && !opening',arg=session)
        assert await page.locator('#prompt').input_value()==TEXT
        assert await page.locator('#turn-mode').input_value()=='plan'
        fixture.drop=True
        await page.locator('#prompt').focus()
        await page.locator('#task').evaluate('n=>n.requestSubmit()'); await settled()
        await page.wait_for_function('currentTurn==="accepted-1"')
        first=await receipt(); assert first['request']['status']=='accepted'
        await page.evaluate('pollActivity()')
        assert len(fixture.requests)==1
        # Recovery can be automatic GET reconciliation or explicit Check request;
        # in either case the same captured request never becomes another start.
        if await page.locator('#prompt').input_value():
            await click_run()
        assert len(fixture.requests)==1
        assert await page.locator('#prompt').input_value()==''
        await queue_exact()
        result['checks'].append({'case':'completed accepted local reply dropped','native_starts':1,'original_cleared':True})

        # Normal successful next task, even identical words, is a fresh identity.
        await page.locator('#prompt').fill(TEXT)
        await click_run()
        assert len(fixture.requests)==2
        assert posts[0]['token']!=posts[-1]['token']
        assert await page.locator('#prompt').input_value()==''
        result['checks'].append({'case':'deliberate same words next task','fresh_identity':True,'additional_starts':1})

        # Accepted HTTP reply held while actual events complete and editor changes.
        await page.locator('#prompt').fill(TEXT)
        fixture.hold_reply=True; fixture.drop=True; fixture.release.clear(); fixture.entered.clear()
        await page.locator('#task').evaluate('n=>n.requestSubmit()')
        assert await asyncio.to_thread(fixture.entered.wait,10)
        await page.locator('#prompt').fill(NEWER)
        await page.locator('#turn-mode').select_option('plan')
        await page.locator('#prompt').focus()
        await page.locator('#prompt').evaluate('n=>n.setSelectionRange(2,9)')
        await page.evaluate('s=>persistDraft(s)',session)
        fixture.release.set(); fixture.hold_reply=False
        await settled(); await page.evaluate('pollActivity()')
        assert len(fixture.requests)==3
        assert await page.locator('#prompt').input_value()==NEWER
        assert await page.locator('#turn-mode').input_value()=='plan'
        assert await page.evaluate('document.activeElement.id')=='prompt'
        assert await page.locator('#prompt').evaluate('n=>[n.selectionStart,n.selectionEnd]')==[2,9]
        assert load_draft(fixture.desk.store,session)['text']==NEWER
        await queue_exact()
        storage=await page.evaluate('Object.fromEntries(Object.keys(localStorage).map(k=>[k,localStorage.getItem(k)]))')
        assert all(TEXT not in str(v) and NEWER not in str(v) for k,v in storage.items() if 'turn' in k or 'request' in k)
        await page.screenshot(path=str(evidence/f'{width}-lost-reply-newer-plan.png'))
        result['checks'].append({'case':'later exact Plan during lost reply','native_starts':1,'newer_text_mode_focus_selection_queue_preserved':True,'opaque_storage':True})

        boundary=len(posts)
        await page.reload(); await page.wait_for_function('s=>selected===s && !opening',arg=session)
        await page.evaluate('pollActivity()')
        assert len(posts)==boundary and len(fixture.requests)==3
        assert await page.locator('#prompt').input_value()==NEWER
        await queue_exact()
        result['checks'].append({'case':'cold same browser receipt recovery','additional_native_starts':0,'turn_posts':0,'newer_draft_preserved':True})
        # Explicit retry always sends the original captured task, not later input.
        await page.locator('#turn-request-new').click()
        fixture.behavior='rejected'
        await page.locator('#prompt').fill(TEXT)
        await click_run()
        rejected=await receipt(); assert rejected['request']['status']=='rejected'
        rejected_body=posts[-1].copy(); count=len(fixture.requests)
        await page.locator('#prompt').fill(NEWER+' rejection retry')
        await page.locator('#prompt').focus()
        await page.evaluate('s=>persistDraft(s)',session)
        fixture.behavior='accepted'
        await page.locator('#turn-request-retry').click()
        await page.wait_for_function('!turnRequest()?.writing')
        assert len(fixture.requests)==count+1
        assert posts[-1]=={**rejected_body,'retry':True}
        assert fixture.requests[-1]['params']['input'][0]['text']==TEXT
        assert await page.locator('#prompt').input_value()==NEWER+' rejection retry'
        await queue_exact()
        result['checks'].append({'case':'known rejection explicit original retry','same_token_body_mode':True,'later_input_unsent':True})

        # Held admission accepts duplicate HTTP as read-only receipt, one RPC.
        await page.locator('#turn-request-new').click()
        await page.locator('#prompt').fill(TEXT)
        fixture.native_release.clear(); fixture.native_entered.clear()
        before=len(fixture.requests)
        await page.locator('#task').evaluate('n=>n.requestSubmit()')
        assert await asyncio.to_thread(fixture.native_entered.wait,10)
        held_body=posts[-1].copy()
        duplicate=await page.evaluate('body=>api("/api/turn",body)',held_body)
        assert duplicate['request']['status']=='pending'
        assert len(fixture.requests)==before+1
        assert await page.locator('#send').is_disabled()
        fixture.native_release.set(); await settled()
        assert len(fixture.requests)==before+1
        await queue_exact()
        result['checks'].append({'case':'pending duplicate request','native_starts':1,'second_http_readonly':True})

        # No native event proof stays review-blocked, including cold restore.
        await page.locator('#prompt').fill(TEXT)
        fixture.behavior='unknown'
        await click_run()
        unknown=await receipt(); assert unknown['request']['status']=='needs_review'
        before=len(fixture.requests); boundary=len(posts)
        await page.locator('#followups').evaluate('n=>n.open=true')
        await page.wait_for_function('$("followup-send").disabled')
        await page.locator('#turn-request-recover').click()
        await page.wait_for_function('!turnRequest()?.reading')
        assert len(fixture.requests)==before and len(posts)==boundary
        await page.reload(); await page.wait_for_function('s=>selected===s && !opening',arg=session)
        assert len(fixture.requests)==before and len(posts)==boundary
        # A second browser has no opaque token but recovers the existing blocker.
        fixture.desk.open=lambda identifier:fixture.runtime.thread_result
        fresh=await browser.new_context(viewport={'width':width,'height':844})
        other=await fresh.new_page(); other.set_default_timeout(12000)
        await other.goto(url+'/#access='+ACCESS)
        await other.wait_for_function('state.sessions.length===1')
        await other.locator('.session-row .session').click()
        await other.wait_for_function('s=>selected===s && !opening',arg=session)
        await other.locator('#prompt').fill(NEWER+' fresh browser')
        await other.locator('#prompt').focus()
        await other.locator('#task').evaluate('n=>n.requestSubmit()')
        await other.wait_for_function('s=>!submitting.has(s) && turnRequest()?.status==="needs_review"',arg=session)
        assert await other.evaluate('turnRequest().token')==unknown['token']
        assert await other.locator('#prompt').input_value()==NEWER+' fresh browser'
        assert await other.locator('#turn-request-rejected').is_visible()
        assert len(fixture.requests)==before
        await other.screenshot(path=str(evidence/f'{width}-fresh-browser-existing-request.png'))
        await fresh.close()
        result['checks'].append({'case':'fresh browser adopts existing unknown different-token receipt','native_starts':0,'newer_plan_unsent':True})
        await page.locator('#turn-request-rejected').click()
        await page.wait_for_function('turnRequest()?.status==="rejected"')
        assert len(fixture.requests)==before and len(posts)==boundary
        await queue_exact()
        result['checks'].append({'case':'unknown review plus cold GET-only and explicit rejected review','additional_starts':0,'send_next_blocked':True})
        await page.screenshot(path=str(evidence/f'{width}-unknown-reviewed.png'))
        assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert not result['javascriptErrors'],result['javascriptErrors']
    finally:
        fixture.release.set(); fixture.native_release.set()
        await context.close(); fixture.doCleanups()
        result['posts']=posts; result['native_requests']=fixture.requests; result['http']=fixture.http
        (evidence/f'result-{width}.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

async def check():
    root=Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:
            results=[await acceptance(browser,width,evidence) for width in (390,1250)]
            (evidence/'result.json').write_text(json.dumps({'result':'PASS','cases':results},ensure_ascii=False,indent=2)+'\n')
            print(json.dumps({'result':'PASS','widths':[390,1250],'cases':sum(len(r['checks']) for r in results)}),flush=True)
        finally: await browser.close()
if __name__=='__main__': asyncio.run(check())
