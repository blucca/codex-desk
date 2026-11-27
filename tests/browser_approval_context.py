"""Read exact child native approval context without leaving the selected task."""
import asyncio,json,os,sys,traceback
from pathlib import Path
S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve();sys.path.insert(0,str(S/'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(S))
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from playwright.async_api import async_playwright
OUT=Path(os.environ['DESK_TEST_EVIDENCE']);OUT.mkdir(parents=True,exist_ok=True)
async def one(browser,width):
 f=NativeHTTPFixture();f.setUp();ctx=None;checks=[];errors=[];posts=[];reads=[]
 try:
  sid=f.identifier;f.desk.store.update(sid,status='ready',thread_saved=1,name_pending=0)
  save_draft(f.desk.store,sid,'Unsent parent Plan remains','plan',0);add_followup(f.desk.store,sid,'Work later','native');add_followup(f.desk.store,sid,'Plan later','plan')
  def saved():return (load_draft(f.desk.store,sid),followup_snapshot(f.desk.store,sid))
  before=saved()
  class Catalog:
   def request(self,m,p):assert m=='thread/list';return {'data':[],'nextCursor':None}
  f.desk.catalog=lambda:Catalog();f.desk.open=lambda target:{'thread':{'id':'native-original','turns':[]},'model':'fixture','modelProvider':'fixture'}
  cwd=str(f.path/'child-验证');command='pytest parser --label résumé';reason='Read the original child parser result before deciding.'
  source={'id':'related-child','name':'Original child task','cwd':cwd,'turns':[{'id':'child-turn','status':'inProgress','items':[{'id':'child-item','type':'commandExecution','command':command,'cwd':cwd,'status':'inProgress','aggregatedOutput':'Retained original command context.','commandActions':[]}]}]}
  def history(identifier):reads.append(identifier);assert identifier=='related-child';return source
  f.desk.history=history
  def receive(m):
   with f.runtime.lifecycle_lock:f.runtime._message(m)
  def request(identifier=201):return {'id':identifier,'method':'item/commandExecution/requestApproval','params':{'threadId':'related-child','turnId':'child-turn','itemId':'child-item','command':command,'cwd':cwd,'reason':reason}}
  receive(request());receive({'id':202,'method':'item/tool/requestUserInput','params':{'threadId':'native-original','turnId':'parent-turn','itemId':'question-item','questions':[{'id':'secret','header':'Private','question':'One-time answer?','isSecret':True}]}})
  ctx=await browser.new_context(viewport={'width':width,'height':900 if width==1250 else 844});page=await ctx.new_page();page.set_default_timeout(15000);page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:posts.append(r.url) if r.method=='POST' else None)
  await page.goto(f'http://127.0.0.1:{f.server.server_port}');await page.locator(f'.session-row[data-session="{sid}"] .session').click();await page.wait_for_function('(id)=>selected===id&&!opening',arg=sid)
  secret=page.get_by_label('Private — One-time answer?');await secret.fill('Transient-only-秘密');await secret.evaluate('n=>{n.setSelectionRange(2,6);window.secretNode=n}')
  card=page.locator('.approval').filter(has=page.locator('.approval-context-identity',has_text='Native request 201\n'));await card.locator('.approval-context summary').click();text=await card.inner_text()
  for value in (command,cwd,reason,'related-child','child-turn','child-item','native-original'):assert value in text,value
  assert 'question-item' in await page.locator('.approval').filter(has_text='Questions for this task').inner_text() or 'question-item' in await page.locator('.approval').filter(has_text='Questions for this task').text_content()
  assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  checks.append('exact supplied command cwd reason and parent-child thread turn item request identity')
  read=card.get_by_role('button',name='Read related native activity',exact=True);await read.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
  assert 'Thread related-child' in await page.locator('#history-reader-binding').inner_text();assert 'matching original native turn and item' in await page.locator('#history-reader-match').inner_text();assert await page.locator('.history-reader-item[data-item-id="child-item"]').count()==1
  assert await page.evaluate('selected')==sid;assert saved()==before and not f.sent and not f.requests
  receive(request(203));await page.evaluate('pollActivity()');assert await page.locator('#history-reader').evaluate('n=>n.open')
  await page.get_by_role('button',name='Return to native request',exact=True).click();assert await read.evaluate('n=>document.activeElement===n')
  assert await secret.evaluate('n=>n===window.secretNode&&n.value==="Transient-only-秘密"&&n.selectionStart===2&&n.selectionEnd===6');checks.append('exact child original reading and sibling arrival keep parent draft two queues secret and return focus')
  held=asyncio.Event();release=asyncio.Event();finished=asyncio.Event()
  async def held_read(route):
   response=await route.fetch();held.set();await asyncio.wait_for(release.wait(),15);await route.fulfill(response=response);finished.set()
  await page.route('**/api/native/thread?id=related-child',held_read);await read.click();await asyncio.wait_for(held.wait(),10)
  receive({'method':'serverRequest/resolved','params':{'threadId':'related-child','requestId':201}});await page.evaluate('pollActivity()');await page.wait_for_function("!$('history-reader').open")
  release.set();await asyncio.wait_for(finished.wait(),10);await page.unroute('**/api/native/thread?id=related-child',held_read);await page.evaluate('new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))');assert not await page.locator('#history-reader').evaluate('n=>n.open');assert not await page.evaluate('requests.has("201")');assert saved()==before and not f.sent
  checks.append('native resolution closes its pending reader and late original response cannot resurrect it')
  remaining=page.locator('.approval').filter(has_text=command);await remaining.get_by_role('button',name='Allow once',exact=True).click();await page.wait_for_function('!requests.has("203")');assert f.sent==[{'id':203,'result':{'decision':'accept'}}];assert await secret.input_value()=='Transient-only-秘密';assert saved()==before
  assert not await page.evaluate('JSON.stringify({...localStorage,...sessionStorage}).includes("Transient-only-")');assert not errors and not f.requests;assert reads==['related-child','related-child'];assert all('/api/open' in u or '/api/approval' in u for u in posts)
  checks.append('only explicit existing one-time decision responds; reading starts no task and persists no answers')
  await page.screenshot(path=str(OUT/f'{width}-native-context.png'));return {'width':width,'checks':checks,'read_threads':reads,'native_responses':f.sent,'native_tasks':0,'draft_two_queues_exact':True,'javascript_errors':errors}
 finally:
  if ctx:await ctx.close()
  f.doCleanups()
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(b,w) for w in (1250,390)]
  finally:await b.close()
 (OUT/'summary.json').write_text(json.dumps({'result':'PASS','groups':8,'checks':rows},indent=2)+'\n');print(json.dumps({'result':'PASS','groups':8}),flush=True)
if __name__=='__main__':asyncio.run(main())
