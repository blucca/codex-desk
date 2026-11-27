"""Pending native question editing through sibling arrivals and held responses."""
import asyncio,json,os,sys,traceback
from pathlib import Path
S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1])).resolve();sys.path.insert(0,str(S/'tests'))
if os.environ.get('DESK_USE_INSTALLED')!='1':sys.path.insert(0,str(S))
import codex_desk
if os.environ.get('DESK_USE_INSTALLED')=='1':assert not Path(codex_desk.__file__).resolve().is_relative_to(S)
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from playwright.async_api import async_playwright
OUT=Path(os.environ['DESK_TEST_EVIDENCE']);OUT.mkdir(parents=True,exist_ok=True)
async def one(browser,width):
 f=NativeHTTPFixture();f.setUp();ctx=None;r={'width':width,'passed':False,'checks':[]};errors=[]
 try:
  sid=f.identifier;f.desk.store.update(sid,status='ready',thread_saved=1,name_pending=0)
  save_draft(f.desk.store,sid,'Plan preparation stays unsent','plan',0,'fixture',1);add_followup(f.desk.store,sid,'Work later','native');add_followup(f.desk.store,sid,'Plan later','plan')
  def saved():return {'draft':load_draft(f.desk.store,sid),'queue':followup_snapshot(f.desk.store,sid)}
  before=saved()
  class Catalog:
   def request(self,m,p):assert m=='thread/list';return {'data':[],'nextCursor':None}
  f.desk.catalog=lambda:Catalog();f.desk.open=lambda target:{'thread':{'id':'native-original','turns':[]},'model':'fixture','modelProvider':'fixture'}
  def receive(message):
   with f.runtime.lifecycle_lock:f.runtime._message(message)
  def question(request_id):receive({'id':request_id,'method':'item/tool/requestUserInput','params':{'threadId':'native-original','turnId':'current-turn','questions':[{'id':'mode','header':'Mode','question':'Which mode?','options':[{'label':'Safe','description':'Read only'},{'label':'Edit','description':'Make changes'}]},{'id':'note','header':'Note','question':'Next parser check?'},{'id':'secret','header':'Private','question':'One-time answer?','isSecret':True}]}})
  ctx=await browser.new_context(viewport={'width':width,'height':900});page=await ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.set_default_timeout(15000)
  await page.goto(f'http://127.0.0.1:{f.server.server_port}');await page.locator(f'.session-row[data-session="{sid}"] .session').click();await page.wait_for_function('(id)=>selected===id&&!opening',arg=sid)
  async def drained():
   seq=f.desk.store.events(sid)[-1]['seq'];await page.wait_for_function('(n)=>after>=n',arg=seq);await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
  question(101);await drained();note=page.get_by_label('Note — Next parser check?');secret=page.get_by_label('Private — One-time answer?');mode=page.get_by_label('Mode — Which mode?')
  await note.fill('Only rerun the parser regression');await secret.fill('Transient-only-秘密');await mode.select_option('Edit');await note.focus()
  await note.evaluate('(e)=>{e.setSelectionRange(5,13);window.originalQuestionNode=e;window.originalQuestionForm=e.form}')
  f.add_approval('102');await drained();await page.evaluate('()=>refresh()')
  assert await note.evaluate('(e)=>e===window.originalQuestionNode&&document.activeElement===e&&e.selectionStart===5&&e.selectionEnd===13')
  assert await note.input_value()=='Only rerun the parser regression';assert await secret.input_value()=='Transient-only-秘密';assert await mode.input_value()=='Edit'
  receive(f.resolved('102'));await drained();assert await note.evaluate('(e)=>e===window.originalQuestionNode')
  assert not await page.evaluate('()=>JSON.stringify({...localStorage,...sessionStorage}).includes("Transient-only-")')
  r['checks'].append('sibling arrival/resolution and native snapshot preserve exact question input, choice, password, caret and focus; no browser storage')
  held=asyncio.Event();release=asyncio.Event()
  async def hold_response(route):
   response=await route.fetch();held.set();await asyncio.wait_for(release.wait(),15);await route.fulfill(response=response)
  await page.route('**/api/answer',hold_response);await page.get_by_role('button',name='Send answers',exact=True).click();await asyncio.wait_for(held.wait(),10)
  f.add_approval('103');await drained();await page.evaluate('()=>{const f=window.originalQuestionForm;f.onsubmit({preventDefault(){}});f.onsubmit({preventDefault(){}})}')
  assert len(f.sent)==1,f.sent;assert f.sent[0]['result']=={'answers':{'mode':{'answers':['Edit']},'note':{'answers':['Only rerun the parser regression']},'secret':{'answers':['Transient-only-秘密']}}}
  release.set();await page.wait_for_function('()=>!requests.has("101")');await page.unroute('**/api/answer',hold_response)
  assert await page.locator('#approvals').get_by_role('button',name='Allow once',exact=True).count()==1
  assert await page.evaluate('()=>window.originalQuestionNode.value')==''
  r['checks'].append('held exact native answers sent once; sibling approval survives accepted answer; retired fields cleared')
  held=asyncio.Event();release=asyncio.Event();await page.route('**/api/approval',hold_response)
  await page.evaluate('()=>window.originalApprovalButtons=[...document.querySelectorAll("#approvals .actions button")]');await page.get_by_role('button',name='Allow once',exact=True).click();await asyncio.wait_for(held.wait(),10)
  await page.evaluate('()=>window.originalApprovalButtons.forEach(b=>b.onclick())')
  assert len(f.sent)==2;assert f.sent[-1]=={'id':103,'result':{'decision':'accept'}}
  release.set();await page.wait_for_function('()=>!requests.has("103")');await page.unroute('**/api/approval',hold_response)
  r['checks'].append('Allow once and Decline share one per-request send lock')
  question(104);await drained();await note.fill('Kept after rejected HTTP response');await secret.fill('Retry review transient')
  f.send_error=OSError('fixture native transport closed');await page.get_by_role('button',name='Send answers',exact=True).click();await page.get_by_text('Response not confirmed:',exact=False).wait_for()
  assert await note.input_value()=='Kept after rejected HTTP response';assert await page.get_by_role('button',name='Send answers',exact=True).is_enabled();assert len(f.sent)==2
  receive(f.resolved('104'));await drained();assert await page.get_by_role('button',name='Send answers',exact=True).count()==0
  assert saved()==before;assert not f.requests;assert not errors,errors
  r['checks'].append('observed native write rejection retains answer for review; native resolution retires it; Plan, two queues and no native task exact')
  await page.screenshot(path=str(OUT/f'case-{width}.png'));r.update(passed=True,native_responses=f.sent)
 except Exception as e:r.update(error=str(e),traceback=traceback.format_exc())
 finally:
  if ctx:await ctx.close()
  f.doCleanups()
 (OUT/f'case-{width}.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps({k:v for k,v in r.items() if k not in ('traceback','native_responses')}),flush=True);return r
async def main():
 async with async_playwright() as p:
  b=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(b,w) for w in (1250,390)]
  finally:await b.close()
 (OUT/'result.json').write_text(json.dumps({'passed':all(x['passed'] for x in rows),'cases':rows},indent=2)+'\n');assert all(x['passed'] for x in rows),[(x.get('error'),x.get('traceback')) for x in rows if not x['passed']]
if __name__=='__main__':asyncio.run(main())
