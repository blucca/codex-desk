"""Native task steps through Runtime._message, SQLite/HTTP and isolated Chromium."""
import asyncio,copy,json,os,sys,traceback
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve();sys.path.insert(0,str(S/'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(S))
import codex_desk
PACKAGE=Path(codex_desk.__file__).resolve()
if os.environ.get('DESK_USE_INSTALLED')=='1':
 assert not PACKAGE.is_relative_to(S), 'Installed acceptance imported the source package'
if os.environ.get('DESK_INSTALLED_ROOT'):
 assert PACKAGE.is_relative_to(Path(os.environ['DESK_INSTALLED_ROOT']).resolve())
if os.environ.get('DESK_EXPECT_VERSION'):
 assert codex_desk.__version__==os.environ['DESK_EXPECT_VERSION']
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.followups import add_followup,followup_snapshot
from codex_desk.drafts import save_draft,load_draft
from playwright.async_api import async_playwright
OUT=Path(os.environ.get('DESK_TEST_EVIDENCE',Path(os.environ.get('DESK_TEST_TEMP',Path.cwd()/'temp'))/'native-steps'));OUT.mkdir(parents=True,exist_ok=True)
STEPS=[{'step':'Inspect original failure 保留 <script>','status':'inProgress'},{'step':'Fix parser','status':'pending'},{'step':'Run verification','status':'pending'}]
async def one(browser,width):
 f=NativeHTTPFixture();f.setUp();context=None;r={'width':width,'passed':False,'checks':[]};requests=[];errors=[]
 try:
  original=f.identifier;other='other-plan';f.desk.store.update(original,status='ready',thread_saved=1)
  f.desk.store.create(str(f.path),'default',identifier=other,name='Other selected Plan');f.desk.store.update(other,thread_id='native-other',status='ready',thread_saved=1)
  for sid in [original,other]:
   save_draft(f.desk.store,sid,'Retained unsent Plan '+sid,'plan',0,'fixture',1);add_followup(f.desk.store,sid,'Retained next verification '+sid,'native')
  threads={original:{'id':'native-original','turns':[]},other:{'id':'native-other','turns':[]}}
  class Catalog:
   def request(self,m,p):assert m=='thread/list';return {'data':[],'nextCursor':None}
  f.desk.catalog=lambda:Catalog();opened=[]
  def opened_task(sid):opened.append(sid);return {'thread':copy.deepcopy(threads[sid]),'model':'fixture','modelProvider':'fixture'}
  f.desk.open=opened_task
  def event(method,params):
   with f.runtime.lifecycle_lock:f.runtime._message({'method':method,'params':params})
  def start(turn):event('turn/started',{'threadId':'native-original','turn':{'id':turn,'status':'inProgress','items':[]}})
  def plan(turn,steps,thread='native-original',explanation='Reported native work — exact résumé  '):event('turn/plan/updated',{'threadId':thread,'turnId':turn,'explanation':explanation,'plan':copy.deepcopy(steps)})
  def finish(turn,status):event('turn/completed',{'threadId':'native-original','turn':{'id':turn,'status':status,'items':[]}})
  context=await browser.new_context(viewport={'width':width,'height':900});page=await context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda q:requests.append({'method':q.method,'path':urlsplit(q.url).path}))
  await page.goto(f'http://127.0.0.1:{f.server.server_port}/');await page.locator(f'.session-row[data-session="{original}"] .session').click();await page.wait_for_function('(s)=>selected===s&&!opening',arg=original)
  before={sid:{'draft':load_draft(f.desk.store,sid),'queue':followup_snapshot(f.desk.store,sid)} for sid in [original,other]};boundary=len(requests)
  start('turn-one');plan('turn-one',STEPS);await page.wait_for_function("$('native-steps-current').textContent.includes('Inspect original failure')")
  assert await page.locator('#native-steps').evaluate('n=>n.open') is False
  await page.locator('#native-steps summary').click();assert await page.locator('#native-steps-list li').count()==3
  assert '<script>' in await page.locator('#native-steps-list').inner_text();assert await page.locator('#native-steps-list script').count()==0
  r['checks'].append('actual Runtime plan updates reach local eventlog and visible exact safe native checklist without auto-opening')
  long_steps=copy.deepcopy(STEPS)+[{'step':'Retained reported checklist row '+str(i),'status':'pending'} for i in range(50)]
  plan('turn-one',long_steps);await page.wait_for_function("$('native-steps-list').children.length===53")
  await page.locator('#native-steps-body').evaluate('n=>{n.focus({preventScroll:true});n.scrollTop=160;}')
  await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
  reading=await page.evaluate("()=>({focus:document.activeElement.id,inner:$('native-steps-body').scrollTop,window:scrollY,open:$('native-steps').open})")
  long_steps[0]['status']='completed';long_steps[1]['status']='inProgress';plan('turn-one',long_steps)
  await page.wait_for_function("$('native-steps-current').textContent.includes('Fix parser')")
  assert await page.evaluate("()=>({focus:document.activeElement.id,inner:$('native-steps-body').scrollTop,window:scrollY,open:$('native-steps').open})")==reading
  r['checks'].append('actual expanded checklist update preserves keyboard focus, inner scroll, window reading position and disclosure')
  updated=copy.deepcopy(STEPS);updated[0]['status']='completed';updated[1]['status']='inProgress';plan('turn-one',updated)
  await page.wait_for_function("$('native-steps-current').textContent.includes('Fix parser')");assert await page.locator('#native-steps').evaluate('n=>n.open') is True
  finish('turn-one','interrupted');await page.wait_for_function("$('native-steps-status').textContent.toLowerCase().includes('interrupted')")
  body=await page.locator('#native-steps-list').inner_text();plan('turn-one',[{'step':'LATE OLD TURN MUST NOT APPEAR','status':'completed'}]);plan('turn-one',[{'step':'CHILD MUST NOT APPEAR','status':'inProgress'}],thread='native-child')
  await page.wait_for_timeout(850);assert await page.locator('#native-steps-list').inner_text()==body
  r['checks'].append('terminal interruption retains last actually reported step statuses; retired/child plan cannot overwrite them')
  start('turn-two');await page.wait_for_function("$('native-steps').hidden")
  assert await page.locator('#native-steps').evaluate('n=>n.open&&n.hidden')
  seq=f.desk.store.events(original)[-1]['seq'];await page.wait_for_function('(seq)=>after>=seq',arg=seq)
  await page.locator('#latest-output').click();assert await page.evaluate('nearLatest()')
  event('item/completed',{'threadId':'native-original','turnId':'turn-two','item':{'id':'quiet-new-turn-output','type':'agentMessage','text':'\n\n'.join('Ordinary quiet-turn output '+str(i) for i in range(40))}})
  seq=f.desk.store.events(original)[-1]['seq'];await page.wait_for_function('(seq)=>after>=seq',arg=seq)
  await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
  assert await page.evaluate('latestUpdates')==0 and await page.evaluate('nearLatest()')
  assert await page.evaluate('Math.abs(scrollY-(document.documentElement.scrollHeight-innerHeight))')<=1
  r['checks'].append('hidden-open native checklist after a new turn no longer blocks near-latest ordinary output following')
  plan('turn-two',[{'step':'Second real verification','status':'inProgress'}]);await page.wait_for_function("$('native-steps-current').textContent.includes('Second real verification')")
  await page.locator(f'.session-row[data-session="{other}"] .session').click();await page.wait_for_function('(s)=>selected===s&&!opening',arg=other);assert await page.locator('#native-steps').is_hidden()
  plan('turn-two',[{'step':'Original continues while another Plan selected','status':'inProgress'}]);await page.wait_for_timeout(650);assert await page.locator('#native-steps').is_hidden()
  await page.locator(f'.session-row[data-session="{original}"] .session').click();await page.wait_for_function("$('native-steps-current').textContent.includes('Original continues')")
  finish('turn-two','completed');await page.wait_for_function("$('native-steps-status').textContent.toLowerCase().includes('completed')")
  r['checks'].append('new turn clears prior plan; different session stays quiet; same-session replay restores latest native plan and actual completion')
  # Hold the actual opening receipt, choose a different Plan, then release it.
  # A late old-generation receipt must not bind its checklist to that Plan.
  threads[original]['turns']=[{'id':'turn-two','status':'completed','items':[]}]
  await page.locator(f'.session-row[data-session="{other}"] .session').click()
  await page.wait_for_function('(s)=>selected===s&&!opening',arg=other)
  held=asyncio.Event();release=asyncio.Event();delivered=asyncio.Event()
  async def hold_open(route):
   if route.request.post_data_json.get('session')!=original:
    await route.continue_();return
   response=await route.fetch();held.set()
   await asyncio.wait_for(release.wait(),15)
   await route.fulfill(response=response);delivered.set()
  await page.route('**/api/open',hold_open)
  await page.locator(f'.session-row[data-session="{original}"] .session').click()
  await asyncio.wait_for(held.wait(),10)
  await page.locator(f'.session-row[data-session="{other}"] .session').click()
  await page.wait_for_function('(s)=>selected===s&&!opening',arg=other)
  release.set();await asyncio.wait_for(delivered.wait(),10);await page.unroute('**/api/open',hold_open);await page.wait_for_timeout(650)
  assert await page.evaluate('selected')==other
  assert await page.locator('#native-steps').is_hidden()
  r['checks'].append('actual held old-generation /api/open receipt cannot bind native steps after another Plan wins')
  # While an older native snapshot is held, the native stream advances a turn.
  # Replay must establish the new turn before accepting the snapshot boundary.
  held=asyncio.Event();release=asyncio.Event();delivered=asyncio.Event()
  await page.route('**/api/open',hold_open)
  await page.locator(f'.session-row[data-session="{original}"] .session').click()
  await asyncio.wait_for(held.wait(),10)
  start('turn-three');plan('turn-three',long_steps,explanation='New streamed turn after captured older snapshot')
  release.set();await asyncio.wait_for(delivered.wait(),10);await page.unroute('**/api/open',hold_open)
  await page.wait_for_function('(s)=>selected===s&&!opening&&DeskNativeSteps.state().turn==="turn-three"',arg=original)
  assert await page.locator('#native-steps-list li').count()==53
  assert await page.locator('#native-steps-status').text_content()=='Task in progress'
  assert 'New streamed turn' in await page.locator('#native-steps-explanation').text_content()
  r['checks'].append('actual held older native snapshot cannot replace a newer streamed turn/checklist during same-session return')
  await page.locator('#native-steps summary').click()
  await page.locator('#native-steps-body').evaluate('n=>{n.focus({preventScroll:true});n.scrollTop=180;}')
  await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
  reading=await page.evaluate("()=>({focus:document.activeElement.id,inner:$('native-steps-body').scrollTop,window:scrollY,open:$('native-steps').open})")
  # Read within the page, not at its bottom clamp: terminal queue controls
  # can shorten the document below the reader when the task becomes idle.
  # Expanded native-step reading also disables scroll anchoring: terminal
  # controls above it must not shift an otherwise reachable window position.
  await page.evaluate("()=>window.scrollTo({top:Math.max(0,scrollY-140),behavior:'instant'})")
  reading=await page.evaluate("()=>({focus:document.activeElement.id,inner:$('native-steps-body').scrollTop,window:scrollY,open:$('native-steps').open})")
  r['failure_reading_before']=reading
  finish('turn-three','failed')
  await page.wait_for_function("$('native-steps-status').textContent==='Task failed'")
  r['failure_reading_after']=await page.evaluate("()=>({focus:document.activeElement.id,inner:$('native-steps-body').scrollTop,window:scrollY,open:$('native-steps').open})")
  assert r['failure_reading_after']==reading,(reading,r['failure_reading_after'])
  last_report=await page.evaluate('()=>DeskNativeSteps.state().reported')
  plan('turn-three',[{'step':'Late post-failure must not replace unfinished rows','status':'completed'}])
  await page.wait_for_timeout(650)
  assert await page.evaluate('()=>DeskNativeSteps.state().reported')==last_report
  assert last_report['plan'][1]['status']=='inProgress' and last_report['plan'][2]['status']=='pending'
  r['checks'].append('actual failure preserves unfinished statuses, expanded disclosure/body focus/scroll/window and ignores late post-failure plan')
  # Ordinary cold return: release the actual HTTP/SQLite owner, then open
  # the same state with a new Desk and let the page restore its saved session.
  from codex_desk.server import Desk,handler
  from http.server import ThreadingHTTPServer
  import threading
  retained_events=f.desk.store.events(original);port=f.server.server_port
  f.close_server();f.desk.store.db.close()
  f.desk=Desk('unused-fake-native',f.path,f.path/'state')
  f.addCleanup(f.desk.store.db.close);f.desk.catalog=lambda:Catalog();f.desk.open=opened_task
  f.server=ThreadingHTTPServer(('127.0.0.1',port),handler(f.desk))
  f.server_thread=threading.Thread(target=f.server.serve_forever,daemon=True);f.server_thread.start()
  assert f.desk.store.events(original)==retained_events
  await page.reload();await page.wait_for_function("$('native-steps-status').textContent==='Task failed'")
  r['cold_report']=await page.evaluate('()=>DeskNativeSteps.state()')
  await page.locator('#native-steps summary').click()
  assert 'Fix parser' in await page.locator('#native-steps-list').inner_text();assert await page.evaluate('()=>DeskNativeSteps.state().reported')==last_report
  r['checks'].append('actual HTTP and SQLite cold owner replacement/reload restores same native terminal/checklist from exact retained events')
  assert {sid:{'draft':load_draft(f.desk.store,sid),'queue':followup_snapshot(f.desk.store,sid)} for sid in [original,other]}==before
  assert not [q for q in requests[boundary:] if q['method']=='POST' and q['path'] not in ['/api/open']]
  assert not f.requests and not f.sent and not errors
  r['checks'].append('two saved Plans and queues exact; no native requests/model sends or unexpected mutation; zero browser errors')
  await page.screenshot(path=str(OUT/f'native-steps-{width}.png'));r.update(passed=True,http=requests,native_requests=0,native_sends=0,errors=errors)
 except Exception as e:r.update(error=str(e),traceback=traceback.format_exc())
 finally:
  if context:await context.close()
  f.doCleanups()
 (OUT/f'case-{width}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n');print(json.dumps({k:v for k,v in r.items() if k not in ['http','traceback']}),flush=True);return r
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM','/usr/bin/chromium'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(b,1250),await one(b,390)]
  finally:await b.close()
 (OUT/'result.json').write_text(json.dumps({'passed':all(r['passed'] for r in rows),'results':rows},indent=2)+'\n')
 for r in rows:
  if not r['passed']:print(r.get('traceback'))
 assert all(r['passed'] for r in rows)
if __name__=='__main__':asyncio.run(main())
