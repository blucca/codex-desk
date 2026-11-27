#!/usr/bin/env python3
"""Actual Prepared lookup, exact saved owner and original-source return at 1250/390."""
import asyncio,copy,hashlib,importlib.util,json,os,tempfile,traceback
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
SPEC=importlib.util.spec_from_file_location('find_fixture',Path(__file__).with_name('check_native_task_response.py'))
b=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(b)
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,edit_followup,reserve_followup,followup_snapshot
from codex_desk.evidence_reference import make_evidence_block
from codex_desk.handoff import visible_text
from codex_desk.turn_dispatch import _binding
from playwright.async_api import async_playwright
TOKEN='12345678-1234-4234-8234-123456789abc'
SOURCE,TURN,ITEM='lookup-source','source-turn','source-item'
QUOTE='Straße café🙂 ＦＩＸ retained evidence'

async def one(browser,width,root,evidence):
 r={'width':width,'passed':False,'checks':[]};errors=[];gets=[]
 with tempfile.TemporaryDirectory(dir=root,prefix='find-') as tmp:
  f=b.Fixture(Path(tmp));ctx=None
  source={'id':SOURCE,'name':'Lookup original A','cwd':str(f.project/'removed-A'),'turns':[{'id':TURN,'status':'completed','items':[{'id':ITEM,'type':'agentMessage','phase':'final_answer','text':'Prefix original. '+QUOTE+' Exact source tail.'}]}]}
  f.threads[SOURCE]=source;projected=visible_text(source['turns'][0]['items'][0]);at=projected.index(QUOTE)
  block=make_evidence_block(source,native_home=hashlib.sha256(str(f.home.resolve()).encode()).hexdigest(),thread_id=SOURCE,turn_id=TURN,item_id=ITEM,quote_start=at,quote_end=at+len(QUOTE),text_for_item=visible_text,expected_quote=QUOTE)
  for sid in (b.ORIGINAL,b.OTHER):save_draft(f.desk.store,sid,'Duplicate remembered phrase\n\n'+block,'plan',load_draft(f.desk.store,sid)['revision'])
  first=followup_snapshot(f.desk.store,b.ORIGINAL)['entries'][0]
  entry=edit_followup(f.desk.store,b.ORIGINAL,first['id'],'Queue remembered source\n\n'+block,'plan',first['revision']);reservation=reserve_followup(f.desk.store,b.ORIGINAL,entry['id'],entry['revision'])
  f.desk.store.create(str(f.project),'default',identifier='request-owner',name='Request owner')
  f.desk.store.update('request-owner',thread_id=b.PARENT,thread_saved=1,status='saved')
  f.desk.store.event('request-owner',{'method':'desk/turnIntent','params':{'token':TOKEN,'payload':{'session':'request-owner','token':TOKEN,'text':'Request remembered source\n\n'+block,'mode':'plan','revision':0,'writer':'find-fixture','sequence':0},'binding':_binding(f.desk,'request-owner')}})
  for n in range(33):
   sid='page-'+str(n).zfill(2);f.desk.store.create(str(f.project),'default',identifier=sid,name='Page '+str(n));save_draft(f.desk.store,sid,'Paging needle '+str(n),'plan',0)
  baseline=f.sql()
  with patch.object(b.product,'_NativeReader',f.reader_type),patch.object(b.product,'Runtime',side_effect=AssertionError('No native admission')):
   try:
    ctx=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844});page=await ctx.new_page();page.set_default_timeout(12000)
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda q:gets.append({'method':q.method,'path':urlsplit(q.url).path}))
    await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
    await page.locator(f'.session-row[data-session="{b.OTHER}"] .session').click();await page.wait_for_function('id=>selected===id&&!opening',arg=b.OTHER)
    await page.locator('#prompt').fill('Current C independent investigation: Duplicate remembered phrase')
    for _ in range(40):
     if load_draft(f.desk.store,b.OTHER)['text']=='Current C independent investigation: Duplicate remembered phrase':break
     await asyncio.sleep(.1)
    assert load_draft(f.desk.store,b.OTHER)['text']=='Current C independent investigation: Duplicate remembered phrase'
    baseline=f.sql()
    main=await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
    await page.locator('#show-preparation').click();await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
    async def checkpoint(name):
     assert not errors,errors
     actual=f.sql()
     if actual!=baseline:r['sql_diff']={k:{'before':baseline.get(k),'after':actual.get(k)} for k in set(actual)|set(baseline) if actual.get(k)!=baseline.get(k)}
     assert actual==baseline,name+' changed SQL';assert f.desk.runtimes=={}
     assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")==main,name+' changed C'
     assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"),name+' overflow'
     r['checks'].append(name);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
    async def search(q):
     await page.locator('#preparation-find-query').fill(q);await page.locator('#preparation-find-query').press('Enter');await page.wait_for_function("$('preparation-find-results').getAttribute('aria-busy')==='false' && !$('preparation-find-search').disabled")
     assert not await page.locator('#preparation-error').is_visible(),await page.locator('#preparation-error').inner_text()
    async def hit(owner,kind=None):
     scope=page.locator(f'.preparation-find-match[data-session="{owner}"]')
     if kind:scope=scope.filter(has=page.locator('h3',has_text=kind))
     await scope.locator('button').first.click()
    await page.get_by_role('button',name='Review preparation in Saved '+b.ORIGINAL,exact=True).click();await page.wait_for_function("!$('preparation-save').disabled")
    unsaved='Unsaved B remains\n'+('Pending local reading '+QUOTE+'\n')*20+'\n'+block
    await page.locator('#preparation-text').fill(unsaved);await page.locator('#preparation-text').evaluate("n=>{n.focus();n.setSelectionRange(40,60,'backward');n.scrollTop=90}")
    async def editor():return await page.locator('#preparation-text').evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")
    pending=await editor();await search('Duplicate remembered phrase');assert await page.locator('.preparation-find-match').count()==2
    await hit(b.ORIGINAL);await page.wait_for_function("!$('preparation-saved-match').hidden")
    assert await editor()==pending;assert 'Duplicate remembered phrase' in await page.locator('#preparation-saved-match').inner_text()
    await checkpoint('duplicate-owner-saved-original-preserves-unsaved-B-and-current-C')
    await page.locator('#preparation-evidence-list button').first.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
    assert await page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"] mark').inner_text()==QUOTE
    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
    assert await editor()==pending;await checkpoint('located-retained-source-exact-A-and-editor-return')
    await search('Queue remembered source');assert await page.locator('.preparation-find-match').count()==2
    await hit(b.ORIGINAL,'Saved follow-up');await page.wait_for_function("id=>document.activeElement.tagName==='ARTICLE' && document.activeElement.dataset.followup===id",arg=entry['id'])
    assert await page.evaluate('document.activeElement.dataset.followup')==entry['id']
    await hit(b.ORIGINAL,'Captured');await page.wait_for_function("token=>document.activeElement.tagName==='SECTION' && document.activeElement.dataset.token===token",arg=reservation['token'])
    assert await page.evaluate('document.activeElement.dataset.token')==reservation['token'];assert await editor()==pending
    await checkpoint('queue-and-captured-reservation-exact-identity-no-admission')
    await search('Request remembered source');await hit('request-owner');await page.wait_for_function("$('preparation-request').open && $('preparation-request-captured-text').textContent.includes('Request remembered source')")
    assert TOKEN in await page.locator('#preparation-request').inner_text();assert 'Request remembered source' in await page.locator('#preparation-request-captured-text').inner_text()
    await page.locator('#preparation-request-return').click();await page.wait_for_function("!$('preparation-request').open")
    await checkpoint('current-unresolved-request-exact-UUID-presenter')
    await search('Paging needle');assert await page.locator('.preparation-find-match').count()==30;assert 'of 33' in await page.locator('#preparation-find-status').inner_text()
    await page.locator('#preparation-find-next').click();await page.wait_for_function("$('preparation-find-status').textContent.startsWith('31–33')");assert await page.locator('.preparation-find-match').count()==3
    await page.locator('#preparation-find-previous').click();await page.wait_for_function("$('preparation-find-status').textContent.startsWith('1–30')")
    await checkpoint('explicit-next-previous-pages-retain-unfiltered-scoped-owners')
    await search('Duplicate remembered phrase')
    old=load_draft(f.desk.store,b.ORIGINAL);save_draft(f.desk.store,b.ORIGINAL,old['text']+' Other-tab change','plan',old['revision']);baseline=f.sql()
    await hit(b.ORIGINAL);await page.wait_for_function("!$('preparation-error').hidden")
    assert 'changed' in await page.locator('#preparation-error').inner_text();await checkpoint('stale-saved-revision-does-not-activate-another-owner')
    gate={'started':asyncio.Event(),'release':asyncio.Event()}
    async def held(route):
     response=await route.fetch();gate['started'].set();await gate['release'].wait();await route.fulfill(response=response)
    await page.route('**/api/preparation?*q=*',held)
    await page.locator('#preparation-find-query').fill('Paging needle');await page.locator('#preparation-find-query').press('Enter');await gate['started'].wait()
    await page.locator('#preparation-find-query').fill('Later unsubmitted query');gate['release'].set();await b.frames(page)
    assert await page.locator('#preparation-find-query').input_value()=='Later unsubmitted query';assert not await page.locator('#preparation-find').is_visible()
    await page.unroute('**/api/preparation?*q=*',held);await checkpoint('held-query-reply-cannot-replace-new-unsubmitted-search')
    await page.locator('#preparation-close').click();await page.locator('#show-preparation').click();await page.wait_for_function("$('preparation-list').getAttribute('aria-busy')==='false'")
    await page.get_by_role('button',name='Review preparation in Saved '+b.ORIGINAL,exact=True).click();await page.wait_for_function("!$('preparation-editor').hidden && $('preparation-text').value.startsWith('Unsaved B remains')")
    assert await page.locator('#preparation-text').input_value()==unsaved
    assert await page.locator('#preparation-conflict').is_visible()
    assert await page.locator('#preparation-save').is_disabled()
    await checkpoint('close-reopen-retains-unsaved-owner-without-save-or-native-open')
    await page.locator('#preparation-close').click()
    await page.locator(f'.session-row[data-session="{b.ORIGINAL}"] .session').click();await page.wait_for_function('id=>selected===id&&!opening',arg=b.ORIGINAL)
    baseline=f.sql()
    ordinary=page.locator(f"#followup-list .followup-entry[data-followup=\"{entry['id']}\"]")
    await page.locator('#followups summary').click()
    await ordinary.get_by_role('button',name='Edit',exact=True).click()
    field=ordinary.locator('textarea');await field.fill('Ordinary current unsent instruction remains exactly')
    await field.evaluate("n=>{n.focus();n.setSelectionRange(5,18,'backward');n.scrollTop=25}")
    view=await field.evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")
    await ordinary.locator('.followup-evidence-references button').first.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
    assert await page.locator(f'.history-reader-item[data-item-id="{ITEM}"] mark').inner_text()==QUOTE
    assert await page.locator('#history-reader-back').inner_text()=='Return to saved follow-up'
    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
    assert await field.evaluate("n=>({text:n.value,start:n.selectionStart,end:n.selectionEnd,direction:n.selectionDirection,scroll:n.scrollTop})")==view
    assert f.sql()==baseline;r['checks'].append('ordinary-saved-followup-exact-source-and-unsent-editor-return')
    await page.locator('#followup-review .followup-evidence-references button').first.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
    assert await page.locator('#history-reader-back').inner_text()=='Return to captured instruction'
    await page.locator('#history-reader-back').click();assert f.sql()==baseline;r['checks'].append('ordinary-captured-reservation-source-not-revised-editor')
    await page.locator('.session-row[data-session="request-owner"] .session').click();await page.wait_for_function("selected==='request-owner'&&!opening && $('turn-request-captured-text').textContent.includes('Request remembered source')")
    baseline=f.sql();captured=await page.locator('#turn-request-captured-text').inner_text()
    await page.locator('.ordinary-request-evidence button').first.click();await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
    assert await page.locator(f'.history-reader-item[data-item-id="{ITEM}"] mark').inner_text()==QUOTE
    assert await page.locator('#history-reader-back').inner_text()=='Return to retained Run request'
    await page.locator('#history-reader-back').click();await page.wait_for_function("!$('history-reader').open")
    assert await page.locator('#turn-request-captured-text').inner_text()==captured
    assert f.sql()==baseline;r['checks'].append('ordinary-retained-request-exact-UUID-source-and-captured-return')
    r.update(passed=True,sql_unchanged=True,GET_writes=0,native_admissions=0,errors=errors,requests=gets)
   except Exception as e:r.update(error=str(e),traceback=traceback.format_exc(),errors=errors)
   finally:
    (evidence/f'case-{width}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    if ctx:await ctx.close()
    f.stop()
 return r
async def main():
 root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True);evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True)
 async with async_playwright() as p:
  browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
  try:rows=[await one(browser,w,root,evidence) for w in (1250,390)]
  finally:await browser.close()
 summary={'result':'PASS' if all(r['passed'] for r in rows) else 'FAIL','results':rows};(evidence/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
 print(json.dumps(summary,ensure_ascii=False),flush=True)
 if summary['result']!='PASS':raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
