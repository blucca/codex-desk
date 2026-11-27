"""Explicit same-turn instructions via actual Runtime/HTTP/SQLite and Chromium."""
import asyncio,copy,json,os,sys,threading,traceback
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit
S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve();sys.path.insert(0,str(S/'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(S))
import codex_desk
if os.environ.get('DESK_USE_INSTALLED')=='1':assert not Path(codex_desk.__file__).resolve().is_relative_to(S)
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from codex_desk.runtime import NativeRequestRejected,NativeRequestUnknown
from codex_desk.server import Desk,handler
from playwright.async_api import async_playwright
OUT=Path(os.environ.get('DESK_TEST_EVIDENCE',Path(os.environ.get('DESK_TEST_TEMP',Path.cwd()/'temp'))/'steering-browser'));OUT.mkdir(mode=0o700,parents=True,exist_ok=True);OUT.chmod(0o700)
TEXT='Skip the slow integration suite; run parser unit tests only. 保留 <script>window.__steerExecuted=true</script>  '
NEWER='Newer correction remains unsent — exact résumé 👩🏽‍💻'

async def one(browser,width):
 f=NativeHTTPFixture();f.setUp();context=None;result={'width':width,'passed':False,'checks':[]};http=[];errors=[]
 try:
  original=f.identifier;other='other-project';f.desk.store.update(original,status='ready',thread_saved=1,name_pending=0)
  other_path=f.path/'other';other_path.mkdir();f.desk.store.create(str(other_path),'default',identifier=other,name='Other Plan');f.desk.store.update(other,thread_id='native-other',status='ready',thread_saved=1,name_pending=0)
  for sid in (original,other):save_draft(f.desk.store,sid,'Original unsent Plan '+sid+' 保留','plan',0,'fixture',1);add_followup(f.desk.store,sid,'Prepared next instruction '+sid,'native')
  def saved():return {sid:{'draft':load_draft(f.desk.store,sid),'queue':followup_snapshot(f.desk.store,sid)} for sid in (original,other)}
  class Catalog:
   def request(self,m,p):assert m=='thread/list';return {'data':[],'nextCursor':None}
  threads={original:{'id':'native-original','turns':[]},other:{'id':'native-other','turns':[]}}
  f.desk.catalog=lambda:Catalog();f.desk.open=lambda sid:{'thread':copy.deepcopy(threads[sid]),'model':'fixture','modelProvider':'fixture'}
  def event(method,params):
   with f.runtime.lifecycle_lock:f.runtime._message({'method':method,'params':params})
  def start(turn):event('turn/started',{'threadId':'native-original','turn':{'id':turn,'status':'inProgress','items':[]}})
  def finish(turn):event('turn/completed',{'threadId':'native-original','turn':{'id':turn,'status':'completed','items':[]}})
  behavior={'kind':'accept'};arrived=threading.Event();release=threading.Event()
  def transport(method,params):
   assert method=='turn/steer';f.requests.append({'method':method,'params':copy.deepcopy(params)})
   kind=behavior['kind']
   if kind.startswith('held'):
    arrived.set();assert release.wait(15)
   if kind in ('reject','held-reject'):raise NativeRequestRejected('Native turn is unsteerable; captured target retained')
   if kind=='unknown':raise NativeRequestUnknown('Native response could not be confirmed')
   event('item/completed',{'threadId':'native-original','turnId':params['expectedTurnId'],'item':{'id':'continued-'+str(len(f.requests)),'type':'agentMessage','text':'Continuing the SAME native task with the explicitly received correction.'}})
   return {'turnId':params['expectedTurnId']}
  f.runtime.request=transport
  context=await browser.new_context(viewport={'width':width,'height':900});page=await context.new_page();page.set_default_timeout(12000);page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda q:http.append({'method':q.method,'path':urlsplit(q.url).path,'body':q.post_data_json if q.method=='POST' else None}))
  async def select(sid):
   await page.locator(f'.session-row[data-session="{sid}"] .session').click();await page.wait_for_function('(s)=>selected===s&&!opening',arg=sid)
  async def settled(status):await page.wait_for_function('(v)=>DeskSteering.state().request?.status===v&&!DeskSteering.state().request?.writing&&!DeskSteering.state().request?.reading',arg=status)
  async def drained():
   seq=f.desk.store.events(original)[-1]['seq'];await page.wait_for_function('(s)=>after>=s',arg=seq);await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
  await page.goto(f'http://127.0.0.1:{f.server.server_port}/');await select(original);before=saved();boundary=len(http)
  assert await page.locator('#steering').is_hidden()
  start('turn-one');event('turn/plan/updated',{'threadId':'native-original','turnId':'turn-one','plan':[{'step':'Inspect, edit, test current native task','status':'inProgress'}]})
  event('turn/diff/updated',{'threadId':'native-original','turnId':'turn-one','diff':'diff --git a/parser.py b/parser.py\n-old\n+new 保留\n'})
  event('item/completed',{'threadId':'native-original','turnId':'turn-one','item':{'id':'older-output','type':'agentMessage','text':'\n\n'.join('Earlier native inspection output '+str(i) for i in range(70))}})
  await page.wait_for_function('DeskSteering.state().active');await drained()
  native_before=await page.evaluate('()=>({steps:DeskNativeSteps.state(),diff:DeskTurnChanges.state()})')
  assert await page.locator('#send').is_disabled();assert await page.locator('#stop').is_enabled()
  await page.locator('#steering-input').fill(TEXT);await page.locator('#steering-send').click();await settled('accepted');await drained()
  assert f.requests==[{'method':'turn/steer','params':{'threadId':'native-original','expectedTurnId':'turn-one','input':[{'type':'text','text':TEXT}]}}]
  assert await page.locator('#steering-input').input_value()=='';assert await page.locator('#steering-captured-text').text_content()==TEXT;assert await page.locator('#steering-captured-text script').count()==0;assert await page.evaluate('window.__steerExecuted===undefined')
  assert await page.evaluate('()=>({steps:DeskNativeSteps.state(),diff:DeskTurnChanges.state()})')==native_before
  assert len([r for r in f.desk.store.events(original) if r['event'].get('method')=='turn/started'])==1
  result['checks'].append('actual native inspect/edit/test gets exactly one turn/steer expectedTurnId and continues same turn; exact literal receipt; only correction clears, native steps/diff exact')

  # Capture a real empty events reply, then lose a genuinely accepted POST
  # receipt. An explicit receipt GET recovers proof without another steer.
  events_held=asyncio.Event();events_release=asyncio.Event();events_delivered=asyncio.Event()
  async def hold_events(route):
   response=await route.fetch();events_held.set();await asyncio.wait_for(events_release.wait(),15);await route.fulfill(response=response);events_delivered.set()
  async def lose_reply(route):
   await route.fetch();await route.abort('failed')
  await page.route('**/api/events?*',hold_events);await asyncio.wait_for(events_held.wait(),10);await page.route('**/api/steer',lose_reply)
  await page.locator('#steering-input').fill(TEXT);await page.locator('#steering-send').click();await settled('pending')
  assert await page.locator('#steering-input').input_value()==TEXT;assert await page.locator('#steering-send').is_disabled();assert len(f.requests)==2
  await page.unroute('**/api/steer',lose_reply);await page.locator('#steering-check').click();await settled('accepted');assert await page.locator('#steering-input').input_value()=='';assert len(f.requests)==2
  events_release.set();await asyncio.wait_for(events_delivered.wait(),10);await page.unroute('**/api/events?*',hold_events);await drained()
  result['checks'].append('genuinely accepted HTTP reply lost: captured correction stays pending; explicit private GET confirms same turn and clears exact version with zero resend')

  behavior['kind']='held-accept';arrived.clear();release.clear();await page.locator('#steering-input').fill(TEXT);await page.locator('#steering-send').click();assert await asyncio.to_thread(arrived.wait,10)
  await page.evaluate("$('steering-send').click()");assert len(f.requests)==3
  await page.locator('#steering-input').fill(NEWER);await page.locator('#steering-input').evaluate('n=>{n.focus({preventScroll:true});n.setSelectionRange(3,12);}')
  await page.evaluate("()=>window.scrollTo(0,$('steering').getBoundingClientRect().top+scrollY-260)")
  await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
  reading=await page.evaluate("()=>({focus:document.activeElement.id,selection:[$('steering-input').selectionStart,$('steering-input').selectionEnd],window:scrollY})")
  release.set();await settled('accepted');await drained()
  assert await page.locator('#steering-input').input_value()==NEWER
  assert await page.evaluate("()=>({focus:document.activeElement.id,selection:[$('steering-input').selectionStart,$('steering-input').selectionEnd],window:scrollY})")==reading
  result['reading_before']=reading;result['reading_after']=await page.evaluate("()=>({focus:document.activeElement.id,selection:[$('steering-input').selectionStart,$('steering-input').selectionEnd],window:scrollY})")
  result['checks'].append('held real native steer reply prevents duplicate click; newer correction caret/focus/window and main Plan survive acceptance/continuing output')

  behavior['kind']='reject';f.add_approval('88');await drained();await page.locator('#steering-input').fill(TEXT);await page.locator('#steering-send').click();await settled('rejected')
  assert await page.locator('#steering-input').input_value()==TEXT;assert await page.locator('#steering-error').text_content()=='Native turn is unsteerable; captured target retained'
  assert await page.locator('#stop').is_enabled();assert await page.get_by_role('button',name='Allow once',exact=True).is_enabled();assert await page.locator('#send').is_disabled();assert f.runtime.approvals
  count=len(f.requests);await page.locator('#steering-check').click();await settled('rejected');assert len(f.requests)==count
  result['checks'].append('actual native rejection retains captured correction and active Stop/approval/Run-disabled controls; receipt check is GET-only')

  behavior['kind']='unknown';await page.locator('#steering-input').fill(TEXT);await page.locator('#steering-send').click();await settled('needs_review');unknown=await page.evaluate('()=>DeskSteering.state().request.body')
  assert await page.locator('#steering-send').is_disabled();count=len(f.requests);await page.locator('#steering-check').click();await settled('needs_review');assert len(f.requests)==count
  await page.reload();await page.wait_for_function('(s)=>selected===s&&!opening',arg=original);await settled('needs_review');assert await page.locator('#steering-input').input_value()==TEXT;assert len(f.requests)==count
  storage=await page.evaluate("sessionStorage.getItem('codex-desk-steer-requests')");assert TEXT not in storage and NEWER not in storage;assert set(json.loads(storage)[0])=={'session','token'}
  result['checks'].append('unknown response and cold browser return restore captured instruction using opaque identity and private GET; no automatic resend or main draft mutation')

  finish('turn-one');start('turn-two');await page.wait_for_function('DeskSteering.state().turn==="turn-two"');await drained()
  assert await page.locator('#steering-send').is_disabled();assert await page.locator('#steering-prepare').is_visible()
  await page.locator('#steering-prepare').click();assert len(f.requests)==count;await page.locator('#steering-input').fill('Fresh explicit correction for turn two')
  behavior['kind']='accept';await page.locator('#steering-send').click();await settled('accepted');assert f.requests[-1]['params']['expectedTurnId']=='turn-two';assert len(f.requests)==count+1
  assert (await page.evaluate('()=>DeskSteering.state().request.body.token'))!=unknown['token']
  result['checks'].append('completion/new turn never rebases unknown instruction; explicit Prepare then fresh Send targets only current native turn')

  behavior['kind']='held-reject';arrived.clear();release.clear();await page.locator('#steering-input').fill('Old turn-two target must reject');await page.locator('#steering-send').click();assert await asyncio.to_thread(arrived.wait,10)
  finish('turn-two');start('turn-three');release.set();await settled('rejected');await drained();assert await page.locator('#steering-input').input_value()=='Old turn-two target must reject';assert f.requests[-1]['params']['expectedTurnId']=='turn-two'
  count=len(f.requests);await select(other);assert await page.locator('#steering').is_hidden();await page.locator('#prompt').focus();await select(original);await settled('rejected');assert len(f.requests)==count;assert await page.locator('#steering-input').input_value()=='Old turn-two target must reject';assert await page.evaluate('()=>DeskSteering.state().turn')=='turn-three'
  result['checks'].append('native expected-turn race rejection and selection return retain old capture, never fall back to new Run/queue/open or resend')

  # Replace the real HTTP/SQLite owner. The receipt remains read-only without
  # a connected runtime; normal fixture opening returns its retained snapshot.
  threads[original]['turns']=[{'id':'turn-three','status':'inProgress','items':[]}]
  events=f.desk.store.events(original);port=f.server.server_port;f.close_server();f.desk.store.db.close();f.desk=Desk('unused-fake-native',f.path,f.path/'state');f.addCleanup(f.desk.store.db.close);f.desk.catalog=lambda:Catalog();cold_open=[]
  def cold_native_open(sid):cold_open.append(sid);raise RuntimeError('Cold instruction receipt must stay disconnected')
  f.desk.open=cold_native_open
  f.server=ThreadingHTTPServer(('127.0.0.1',port),handler(f.desk));f.server_thread=threading.Thread(target=f.server.serve_forever,daemon=True);f.server_thread.start();assert f.desk.store.events(original)==events
  cold_mark=len(http);await page.reload();await page.wait_for_function('(s)=>selected===s&&!opening',arg=original);await settled('rejected');assert not cold_open;assert not [r for r in http[cold_mark:] if r['method']=='POST'];assert await page.locator('#steering-send').is_disabled();assert await page.locator('#steering-check').is_enabled();count=len(f.requests);mark=len(http);await page.locator('#steering-check').click();await settled('rejected');assert len(f.requests)==count;assert not [r for r in http[mark:] if r['method']=='POST'];assert f.desk.store.events(original)==events
  result['checks'].append('real HTTP+SQLite owner reopen restores exact receipt using zero POST/open calls; disconnected Send disabled, Check enabled and GET-only, events exact')
  assert saved()==before;assert not f.sent and not errors;assert all(r['method']=='turn/steer' for r in f.requests)
  assert not [r for r in http[boundary:] if r['method']=='POST' and r['path'] not in ('/api/steer','/api/open')]
  assert await page.locator('#prompt').input_value()==before[original]['draft']['text'];assert await page.locator('#turn-mode').input_value()=='plan'
  await page.screenshot(path=str(OUT/f'steering-{width}.png'));result.update(passed=True,http=http,native=f.requests,native_turn_starts=0,native_sends=0,errors=errors,main_before=before,main_after=saved())
 except Exception as e:
  result.update(error=str(e),traceback=traceback.format_exc(),http=http,native=f.requests,errors=errors)
  if context:
   try:result['observed']=await page.evaluate('()=>({selected,opening,after,steering:DeskSteering.state()})');await page.screenshot(path=str(OUT/f'failure-{width}.png'))
   except Exception:pass
 finally:
  release.set() if 'release' in locals() else None
  if context:await context.close()
  f.doCleanups()
 path=OUT/f'case-{width}.json';path.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');path.chmod(0o600)
 for p in OUT.glob('*.png'):p.chmod(0o600)
 print(json.dumps({k:v for k,v in result.items() if k not in ('http','traceback','observed','native','main_before','main_after')},ensure_ascii=False),flush=True);return result

async def main():
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(browser,width) for width in (1250,390)]
  finally:await browser.close()
 path=OUT/'result.json';path.write_text(json.dumps({'passed':all(r['passed'] for r in rows),'results':rows},indent=2,ensure_ascii=False)+'\n');path.chmod(0o600)
 for r in rows:
  if not r['passed']:print(r.get('traceback'),flush=True)
 assert all(r['passed'] for r in rows)
if __name__=='__main__':asyncio.run(main())
