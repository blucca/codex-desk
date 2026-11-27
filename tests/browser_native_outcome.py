"""Last native outcome remains readable after actual attach and cold recovery."""
import asyncio,copy,json,os,sys,tempfile,threading
from pathlib import Path
from unittest.mock import patch
from urllib.request import urlopen
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from codex_desk.runtime import Runtime
from codex_desk.server import Desk,ThreadingHTTPServer,handler
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from playwright.async_api import async_playwright

async def check(width,browser,root,evidence):
 with tempfile.TemporaryDirectory(dir=root,prefix='native-outcome-') as tmp:
  folder=Path(tmp);home=folder/'home';home.mkdir();project=folder/'project';project.mkdir()
  desk=Desk('never-executed',home,folder/'state');identifier='saved-task'
  desk.store.create(str(project),'default',identifier=identifier,name='Saved failed task');desk.store.update(identifier,thread_id='native-parent',thread_saved=1,name_pending=0,status='failed',error=json.dumps({'message':'parser test failed','codexErrorInfo':'sandboxError'}),mode='plan')
  save_draft(desk.store,identifier,'Unsent Plan: inspect the remaining failed check.','plan',0);add_followup(desk.store,identifier,'Inspect saved failure evidence','native');add_followup(desk.store,identifier,'Review the final patch','plan')
  preparation=(load_draft(desk.store,identifier),followup_snapshot(desk.store,identifier))
  source={'id':'native-parent','cwd':str(project),'name':'Saved failed task','turns':[{'id':'failed-turn','status':'failed','error':{'message':'parser test failed','codexErrorInfo':'sandboxError'},'items':[]}]}
  calls,http,errors,external=[],[],[],[];current={'runtime':None}
  class Catalog:
   def request(self,method,params):calls.append({'method':method,'params':params});assert method=='thread/list';return {'data':[],'nextCursor':None}
  def start(port=0):
   desk.catalog=lambda:Catalog()
   def open_saved(id):
    assert id==identifier
    live=object.__new__(Runtime);live.store,live.id,live.home=desk.store,id,home;live.closing=False;live.approvals={};live._flush_name=lambda:None
    def request(method,params):calls.append({'method':method,'params':params});assert method=='thread/resume';return {'thread':copy.deepcopy(source),'model':'fixture','modelProvider':'fixture'}
    live.request=request;current['runtime']=live;return live.attach()
   desk.open=open_saved
   server=ThreadingHTTPServer(('127.0.0.1',port),handler(desk));worker=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.01},daemon=True);worker.start();return server,worker
  def stop(server,worker):server.shutdown();server.server_close();worker.join(3);desk.close();desk.store.db.close()
  server,worker=start();context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844});page=await context.new_page();page.set_default_timeout(10000);page.on('pageerror',lambda e:errors.append(str(e)))
  def requested(r):
   from urllib.parse import urlsplit
   p=urlsplit(r.url);http.append({'method':r.method,'path':p.path})
   if p.hostname!='127.0.0.1':external.append(r.url)
  page.on('request',requested);checks=[]
  async def outcome(status):await page.wait_for_function("s=>!$('native-outcome').hidden && $('native-outcome-summary').textContent.includes(s)",arg=status)
  async def unchanged():
   assert (load_draft(desk.store,identifier),followup_snapshot(desk.store,identifier))==preparation
   assert await page.locator('#prompt').input_value()==preparation[0]['text'];assert await page.locator('#turn-mode').input_value()=='plan';assert not errors and not external
  try:
   await page.goto(f'http://127.0.0.1:{server.server_port}');await page.locator('.session-row[data-session="saved-task"] .session').click();await page.wait_for_function("selected==='saved-task' && !opening && !$('task').hidden");await outcome('failed')
   assert desk.store.get(identifier)['status']=='ready' and desk.store.get(identifier)['error'] is None
   assert await page.locator('#native-failure').evaluate('n=>n.hidden');assert 'Turn failed-turn' in await page.locator('#native-outcome-identity').text_content()
   await page.locator('#native-outcome summary').click();assert 'parser test failed' in await page.locator('#native-outcome-body').inner_text();assert not await page.locator('#send').is_disabled();await unchanged();checks.append('actual attach admission ready retains exact failed empty-turn outcome')
   live=current['runtime'];live._message({'method':'turn/started','params':{'threadId':'native-parent','turn':{'id':'next-turn','status':'inProgress'}}});await page.evaluate('pollActivity()');await outcome('inProgress')
   live._message({'method':'error','params':{'threadId':'native-parent','turnId':'next-turn','willRetry':True,'error':{'message':'transient stream failure','codexErrorInfo':'serverOverloaded'}}});await page.evaluate('pollActivity()');await outcome('inProgress');assert 'transient stream failure' not in await page.locator('#native-outcome-body').inner_text();assert await page.locator('#send').is_disabled();checks.append('new native start and retry error are not a completed failure')
   final={'id':'next-turn','status':'failed','error':{'message':'timeout check failed','codexErrorInfo':{'serverOverloaded':{'httpStatusCode':503}}},'items':[]};source['turns'].append(copy.deepcopy(final));live._message({'method':'turn/completed','params':{'threadId':'native-parent','turn':final}});await page.evaluate('pollActivity()');await outcome('failed')
   assert 'Turn next-turn' in await page.locator('#native-outcome-identity').text_content();assert 'timeout check failed' in await page.locator('#native-outcome-body').inner_text();assert 'HTTP 503' in await page.locator('#native-outcome-body').inner_text();await unchanged();checks.append('latest terminal identity and structured native failure replace prior outcome')
   screenshot=evidence/f'{width}-last-native-outcome.png';await page.screenshot(path=str(screenshot));screenshot.chmod(0o600)
   port=server.server_port;stop(server,worker);desk=Desk('never-executed',home,folder/'state');before_calls=len(calls);server,worker=start(port)
   with urlopen(f'http://127.0.0.1:{port}/api/state',timeout=5) as response:cold=json.load(response)
   assert cold['native_outcomes'][identifier]['turn_id']=='next-turn';assert cold['native_outcomes'][identifier]['error']['message']=='timeout check failed';assert len(calls)==before_calls and desk.runtimes=={}
   await page.reload();await page.wait_for_function("selected==='saved-task' && !opening && !$('task').hidden");await outcome('failed');assert desk.store.get(identifier)['status']=='ready';assert 'Turn next-turn' in await page.locator('#native-outcome-identity').text_content();await page.locator('#native-outcome summary').click();assert 'timeout check failed' in await page.locator('#native-outcome-body').inner_text();await unchanged();checks.append('cold read-only state and same-browser return retain outcome without starting work')
   assert all(c['method'] in ('thread/list','thread/resume') for c in calls);assert all(r['path']=='/api/open' for r in http if r['method']=='POST');assert not errors and not external
   return {'width':width,'checks':checks,'native_calls':calls,'model_starts':0,'cold_get_native_calls':0,'plan_two_queues_unchanged':True,'http':http,'javascript_errors':errors}
  finally:await context.close();stop(server,worker)

async def main():
 root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True);out=Path(os.environ['DESK_TEST_EVIDENCE']);out.mkdir(parents=True,exist_ok=True,mode=0o700);out.chmod(0o700)
 with patch('codex_desk.server.Runtime',side_effect=AssertionError('Native process forbidden')):
  async with async_playwright() as p:
   browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
   try:checks=[await check(w,browser,root,out) for w in (1250,390)]
   finally:await browser.close()
 summary=out/'summary.json';summary.write_text(json.dumps({'result':'PASS','groups':8,'checks':checks},indent=2)+'\n');summary.chmod(0o600);print(json.dumps({'result':'PASS','groups':8}),flush=True)
if __name__=='__main__':asyncio.run(main())
