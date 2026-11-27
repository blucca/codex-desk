"""Ordinary captured Stop, delayed/lost response and cold receipt via real HTTP."""
import asyncio,copy,json,os,sys,threading,traceback
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import urlsplit
S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve();sys.path.insert(0,str(S/'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(S))
import codex_desk
if os.environ.get('DESK_USE_INSTALLED')=='1':assert not Path(codex_desk.__file__).resolve().is_relative_to(S)
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.runtime import NativeRequestUnknown
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from playwright.async_api import async_playwright
OUT=Path(os.environ['DESK_TEST_EVIDENCE']);OUT.mkdir(parents=True,exist_ok=True)
async def one(browser,width):
 f=NativeHTTPFixture();f.setUp();ctx=None;r={'width':width,'passed':False,'checks':[]};http=[];errors=[]
 try:
  sid=f.identifier;f.desk.store.update(sid,status='ready',thread_saved=1,name_pending=0)
  save_draft(f.desk.store,sid,'Unsent Plan stays exact résumé','plan',0,'fixture',1)
  add_followup(f.desk.store,sid,'Prepared Work stays paused','native');add_followup(f.desk.store,sid,'Prepared Plan stays paused','plan')
  def saved():return {'draft':load_draft(f.desk.store,sid),'queue':followup_snapshot(f.desk.store,sid)}
  before=saved();opens=[]
  class Catalog:
   def request(self,m,p):assert m=='thread/list';return {'data':[],'nextCursor':None}
  f.desk.catalog=lambda:Catalog()
  def open_task(target):opens.append(target);return {'thread':{'id':'native-original','turns':[]},'model':'fixture','modelProvider':'fixture'}
  f.desk.open=open_task
  def event(m,p):
   with f.runtime.lifecycle_lock:f.runtime._message({'method':m,'params':p})
  def start(t):event('turn/started',{'threadId':'native-original','turn':{'id':t,'status':'inProgress','items':[]}})
  def finish(t):event('turn/completed',{'threadId':'native-original','turn':{'id':t,'status':'interrupted','items':[]}})
  behavior={'unknown':False}
  def transport(m,p):
   assert m=='turn/interrupt';f.requests.append({'method':m,'params':copy.deepcopy(p)})
   if behavior['unknown']:raise NativeRequestUnknown('The native Stop response was lost')
   return {}
  f.runtime.request=transport
  ctx=await browser.new_context(viewport={'width':width,'height':900});page=await ctx.new_page();page.set_default_timeout(15000)
  page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda q:http.append({'method':q.method,'path':urlsplit(q.url).path}))
  async def drained():
   seq=f.desk.store.events(sid)[-1]['seq'];await page.wait_for_function('(s)=>after>=s',arg=seq);await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
  async def status(word):
   want={'requested':['accepted'],'rejected':['rejected'],'unconfirmed':['pending','needs_review']}[word]
   await page.wait_for_function('(v)=>{const r=DeskStopTask.state().request;return r&&v.includes(r.status)&&!r.writing&&!r.reading}',arg=want)
  await page.goto(f'http://127.0.0.1:{f.server.server_port}');await page.locator(f'.session-row[data-session="{sid}"] .session').click();await page.wait_for_function('(s)=>selected===s&&!opening',arg=sid)
  start('turn-A');await drained();assert await page.locator('#stop').is_enabled()
  held=asyncio.Event();release=asyncio.Event()
  async def hold_ack(route):
   response=await route.fetch();held.set();await asyncio.wait_for(release.wait(),15);await route.fulfill(response=response)
  await page.route('**/api/stop',hold_ack);await page.locator('#stop').click();await asyncio.wait_for(held.wait(),10)
  finish('turn-A');start('turn-B');f.add_approval('77');await drained()
  approval=await page.locator('#approvals').inner_text();assert approval.strip(),approval
  async def fail_state(route):await route.abort('failed')
  await page.route('**/api/state',fail_state);release.set();await status('requested');await page.wait_for_timeout(100)
  assert await page.locator('#approvals').inner_text()==approval
  await page.unroute('**/api/state',fail_state);await page.unroute('**/api/stop',hold_ack)
  assert f.requests==[{'method':'turn/interrupt','params':{'threadId':'native-original','turnId':'turn-A'}}]
  assert 'turn-A' in await page.locator('#stop-request-target').inner_text();r['checks'].append('captured A exactly once; delayed ACK cannot clear B approval even with state read failure; native terminal authority')
  # B is explicitly distinct; lose genuinely accepted local response, check same receipt only.
  async def lose_ack(route):await route.fetch();await route.abort('failed')
  events_held=asyncio.Event();events_release=asyncio.Event()
  async def hold_events(route):
   response=await route.fetch();events_held.set();await asyncio.wait_for(events_release.wait(),15);await route.fulfill(response=response)
  await page.route('**/api/events?*',hold_events);await asyncio.wait_for(events_held.wait(),10)
  await page.route('**/api/stop',lose_ack);await page.locator('#stop').click();await status('unconfirmed');assert len(f.requests)==2
  await page.unroute('**/api/stop',lose_ack);boundary=len(http);await page.locator('#stop-request-check').click();await status('requested')
  assert len(f.requests)==2 and not any(q['method']=='POST' for q in http[boundary:]);r['checks'].append('new B Stop explicit; accepted response lost then private GET recovers without resend');events_release.set();await page.unroute_all(behavior='wait')
  finish('turn-B');start('turn-C');await drained()
  # Hold before admission so the real POST arrives only after C retires and D starts.
  held2=asyncio.Event();release2=asyncio.Event()
  async def hold_post(route):held2.set();await asyncio.wait_for(release2.wait(),15);await route.continue_()
  await page.route('**/api/stop',hold_post);await page.locator('#stop').click();await asyncio.wait_for(held2.wait(),10);finish('turn-C');start('turn-D');await drained();release2.set();await status('rejected');await page.unroute('**/api/stop',hold_post)
  assert len(f.requests)==2;r['checks'].append('captured C delivered after D starts is rejected; native D never interrupted')
  # Explicit D unknown native response; cold recovery must not acquire native runtime.
  behavior['unknown']=True;await page.locator('#stop').click();await status('unconfirmed');assert len(f.requests)==3
  f.desk.runtimes.clear();f.desk.open=Mock(side_effect=AssertionError('Cold Stop must not open'));f.desk.runtime=Mock(side_effect=AssertionError('Cold Stop must not start native'))
  boundary=len(http);await page.reload();await status('unconfirmed');assert await page.locator('#stop').is_disabled()
  await page.locator('#stop-request-check').click();await status('unconfirmed');assert len(f.requests)==3
  assert not any(q['method']=='POST' for q in http[boundary:]);f.desk.open.assert_not_called();f.desk.runtime.assert_not_called()
  assert saved()==before;r['checks'].append('cold unknown Stop discover/check GET only; no native/open/Run/queues, original Plan and two queues exact')
  assert not errors,errors;await page.screenshot(path=str(OUT/f'case-{width}.png'));r.update(passed=True,native=f.requests,http=http)
 except Exception as e:r.update(error=str(e),traceback=traceback.format_exc(),http=http)
 finally:
  if ctx:await ctx.close()
  f.doCleanups()
 (OUT/f'case-{width}.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k not in ('http','native','traceback')}),flush=True);return r
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(b,w) for w in (1250,390)]
  finally:await b.close()
 (OUT/'result.json').write_text(json.dumps({'passed':all(x['passed'] for x in rows),'cases':rows},indent=2)+'\n')
 assert all(x['passed'] for x in rows),[(x.get('error'),x.get('traceback')) for x in rows if not x['passed']]
if __name__=='__main__':asyncio.run(main())
