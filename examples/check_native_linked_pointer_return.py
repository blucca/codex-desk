#!/usr/bin/env python3
"""Pointer-selected linked quote from Changed work, local Plan append and exact return."""
import asyncio
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import traceback
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

SPEC=importlib.util.spec_from_file_location('linked_evidence_response_fixture',Path(__file__).with_name('check_native_task_response.py'))
base=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(base)
from codex_desk.drafts import load_draft
from codex_desk.followups import followup_snapshot
from playwright.async_api import async_playwright

CHILD,TURN,ITEM,LINK='linked-child-original','linked-child-turn','linked-child-item','parent-B-linked-child'
QUOTE='CHILD decisive evidence — café🙂 exact source.'
TEXT='CHILD START\n'+'\n'.join(f'Child source line {i:04d}: retain the captured instruction and source identity.'+(' '+QUOTE if i in (50,900) else '') for i in range(1200))+'\nCHILD END'

async def one(browser,width,root,evidence):
    record={'width':width,'passed':False,'checks':[]};errors=[];http=[]
    with tempfile.TemporaryDirectory(dir=root,prefix=f'linked-evidence-{width}-') as temporary:
        f=base.Fixture(Path(temporary));context=None
        child_folder=Path(temporary)/'removed-child-project';child_folder.mkdir();child_folder.rmdir()
        f.threads[CHILD]={'id':CHILD,'cwd':str(child_folder),'name':'Linked child exact source','turns':[{'id':TURN,'status':'completed','items':[base.assistant(ITEM,TEXT,'final_answer')]}]}
        f.threads[base.PARENT]['turns']=[{'id':base.TURN,'status':'failed','items':[
            {'id':'parent-B-user','type':'userMessage','content':[{'type':'text','text':'Inspect the linked child evidence before changing this existing Plan.'}]},
            {'id':LINK,'type':'subAgentActivity','kind':'completed','agentPath':'/root/child','agentThreadId':CHILD},
            base.assistant('parent-B-answer','The parent passage remains independently readable.','commentary')]}]
        f.desk.store.recall_snapshot(base.ORIGINAL,f.threads[base.PARENT])
        preparation=f.prepared();namespace=hashlib.sha256(str(f.home.resolve()).encode()).hexdigest()
        with patch.object(base.product,'_NativeReader',f.reader_type),patch.object(base.product,'Runtime',side_effect=AssertionError('Connected reading must not create a task runtime')):
            try:
                context=await browser.new_context(viewport={'width':width,'height':900 if width>390 else 844})
                page=await context.new_page();page.set_default_timeout(15000)
                page.on('pageerror',lambda error:errors.append(str(error)))
                async def isolated(route):
                    assert urlsplit(route.request.url).hostname=='127.0.0.1',route.request.url
                    await route.continue_()
                await context.route('**/*',isolated)
                page.on('request',lambda request:http.append({'method':request.method,'path':urlsplit(request.url).path,'query':parse_qs(urlsplit(request.url).query)}))
                async def ready():
                    await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                    await base.frames(page)
                async def checkpoint(name):
                    assert not errors,errors
                    assert f.desk.runtimes=={} and not f.desk.store.get(CHILD)
                    assert f.prepared()[base.OTHER]==preparation[base.OTHER]
                    assert followup_snapshot(f.desk.store,base.ORIGINAL)==preparation[base.ORIGINAL]['queue']
                    assert await page.evaluate('selected')==base.ORIGINAL
                    assert await page.locator('#turn-mode').input_value()=='plan'
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth&&[...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)")
                    record['checks'].append(name);await page.screenshot(path=str(evidence/f'{width}-{name}.png'))
                target=lambda:page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')
                async def parent():
                    return await page.evaluate("""()=>({selected,nativeThreadId,generation,window:scrollY,open:$('activity').querySelector('[data-collaboration-turn]').open,
                      top:document.querySelector('.linked-agent-original').getBoundingClientRect().top})""")
                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                await page.locator(f'.session-row[data-session="{base.OTHER}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=base.OTHER)
                await page.locator('#show-changed-work').click()
                await page.locator('#changed-work-mode').select_option('all')
                overview_row=page.locator(f'.changed-work-row[data-session="{base.ORIGINAL}"] .changed-work-open')
                await overview_row.focus()
                overview=await page.evaluate("""()=>({mode:$('changed-work-mode').value,project:$('changed-work-project').value,
                  query:$('session-filter').value,archived:$('show-archived').checked,scroll:$('changed-work-list').scrollTop,
                  row:document.activeElement.closest('.changed-work-row')?.dataset.session})""")
                await overview_row.click()
                await page.wait_for_function('id=>selected===id&&!opening&&!sessionReadingPending',arg=base.ORIGINAL)
                await page.wait_for_function("document.querySelector('.linked-agent-original')&&!document.querySelector('.linked-agent-original').disabled")
                group=page.locator('#activity > details.activity-collaboration')
                await group.locator('summary').click()
                button=page.locator('.linked-agent-original').filter(has_text=CHILD)
                await button.evaluate('n=>n.focus({preventScroll:true})');await base.frames(page)
                retained=await parent();before=f.sql();boundary=len(http)
                await button.press('Enter');await ready()
                assert await page.locator('#history-reader-back').text_content()=='Return to parent activity'
                assert f.sql()==before
                child_gets=[q for q in http[boundary:] if q['path']=='/api/native/evidence-source']
                assert len(child_gets)==1 and child_gets[0]['query']=={'home':[namespace],'thread':[CHILD]}
                await checkpoint('scoped-linked-child-read-keeps-existing-B-plan-two-queues')
                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.keyboard.press('F3')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                rects=await target().locator('mark').evaluate("n=>[...n.getClientRects()].map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))")
                first,last=rects[0],rects[-1]
                start=(first['left']+.5,(first['top']+first['bottom'])/2)
                end=(last['right']-.5,(last['top']+last['bottom'])/2)
                assert 0<start[0]<width and 0<end[0]<width and 0<start[1]<(844 if width==390 else 900) and 0<end[1]<(844 if width==390 else 900),(start,end)
                if width==390:start,end=end,start
                await page.mouse.move(*start);await page.mouse.down()
                await page.mouse.move(*end,steps=12);await page.mouse.up()
                selected_quote=await page.evaluate('getSelection().toString()')
                assert selected_quote==QUOTE,(rects,selected_quote,QUOTE)
                record['pointer_selection']={'direction':'backward' if width==390 else 'forward','rects':len(rects),'quote':selected_quote}
                await checkpoint('genuine-pointer-selects-exact-second-child-quote-after-Find')
                source_view=await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})")
                await target().locator('.history-reader-review-evidence').click()
                await page.wait_for_function("$('evidence-preparation').open&&!DeskEvidencePreparation.state().pending")
                reviewed=await page.evaluate('DeskEvidencePreparation.state()');reference=reviewed['reference']
                assert reviewed['destination']['session']==base.ORIGINAL and reviewed['destination']['mode']=='plan'
                assert reference['thread_id']==CHILD and reference['turn_id']==TURN and reference['item_id']==ITEM and reference['quote']==QUOTE and reference['native_home']==namespace
                assert reference['quote_start']==('Codex\n'+TEXT).rfind(QUOTE)
                await checkpoint('exact-child-quote-captured-for-existing-unsent-B-destination')
                calls_boundary=len(f.calls);http_boundary=len(http)
                await page.locator('#evidence-preparation-append').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                await base.frames(page)
                saved=load_draft(f.desk.store,base.ORIGINAL)
                assert saved['mode']=='plan' and saved['revision']==preparation[base.ORIGINAL]['draft']['revision']+1
                assert saved['text'].startswith(preparation[base.ORIGINAL]['draft']['text']) and saved['text'].count('<!-- codex-desk-evidence:v1 ')==1
                parsed=await page.evaluate('DeskEvidencePreparation.parse($("prompt").value)')
                assert len(parsed)==1 and parsed[0]['reference']==reference
                assert f.calls[calls_boundary:]==[]
                assert [q['path'] for q in http[http_boundary:] if q['method']=='POST']==['/api/draft']
                for table,rows in before.items():
                    if table!='drafts':assert f.sql()[table]==rows,table
                assert await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})")==source_view
                await checkpoint('append-once-local-B-plan-retains-child-selection-and-all-queues')
                await page.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})')
                await page.locator('#history-reader-back').press('Enter')
                await page.wait_for_function("!$('history-reader').open&&!sessionReadingPending")
                await base.frames(page)
                assert await parent()==retained,(retained,await parent())
                await checkpoint('linked-return-to-exact-parent-passage-after-reviewed-local-save')
                if not await page.locator('#draft-evidence').evaluate('n=>n.open'):
                    await page.locator('#draft-evidence summary').evaluate('n=>n.focus({preventScroll:true})')
                    await page.locator('#draft-evidence summary').press('Enter')
                await page.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,24,'backward');n.scrollTop=35}")
                await base.frames(page)
                editor=await page.evaluate("({window:scrollY,text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop})")
                parent_before_reference=await parent();before_reference=f.sql();boundary=len(http)
                source_button=page.locator('#draft-evidence-list button')
                await source_button.evaluate('n=>n.focus({preventScroll:true})');await source_button.press('Enter');await ready()
                assert await page.locator('#history-reader-saved-evidence-quote').text_content()==QUOTE
                assert await target().locator('mark').text_content()==QUOTE
                assert f.sql()==before_reference
                assert [q['query'] for q in http[boundary:] if q['path']=='/api/native/evidence-source']==[{'home':[namespace],'thread':[CHILD]}]
                await checkpoint('actual-B-captured-reference-reopens-exact-second-child-quote')
                await page.locator('#history-reader-back').evaluate('n=>n.focus({preventScroll:true})')
                await page.locator('#history-reader-back').press('Enter')
                await page.wait_for_function("!$('history-reader').open")
                await base.frames(page)
                assert await page.evaluate("({window:scrollY,text:$('prompt').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop})")==editor
                assert await page.evaluate('document.activeElement.id')=='prompt'
                assert await parent()==parent_before_reference
                assert f.sql()==before_reference
                assert {path:path.read_bytes() for path in f.protected}==f.protected
                assert not [q for q in http if q['method']=='POST' and q['path'] not in ('/api/open','/api/draft')]
                assert all(call['method'] in ('thread/read','thread/list') for call in f.calls)
                await checkpoint('child-reference-return-retains-exact-B-editor-and-parent-passage')
                await page.locator('#changed-work-back').click()
                await page.wait_for_function("$('changed-work').open")
                await base.frames(page)
                returned=await page.evaluate("""()=>({mode:$('changed-work-mode').value,project:$('changed-work-project').value,
                  query:$('session-filter').value,archived:$('show-archived').checked,scroll:$('changed-work-list').scrollTop,
                  row:document.activeElement.closest('.changed-work-row')?.dataset.session})""")
                assert returned==overview,(overview,returned)
                assert f.sql()==before_reference
                await checkpoint('ordinary-return-to-same-Changed-overview-row-after-child-evidence')
                record.update(passed=True,native_admissions=0,child_task_rows=0,source_threads_read=[q['params'].get('threadId') for q in f.calls if q['method']=='thread/read'],draft_appends=1)
            except Exception as error:
                record.update(error=str(error),traceback=traceback.format_exc(),javascript_errors=errors)
                if context:await page.screenshot(path=str(evidence/f'{width}-failure.png'))
            finally:
                if context:await context.close()
                f.stop()
    (evidence/f'{width}.json').write_text(json.dumps(record,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({k:record[k] for k in ['width','passed','checks','error'] if k in record}),flush=True)
    return record

async def main():
    root=Path(os.environ['DESK_TEST_TEMP']);root.mkdir(parents=True,exist_ok=True)
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as p:
        browser=await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,args=['--no-sandbox','--disable-dev-shm-usage'])
        try:records=[await one(browser,width,root,evidence) for width in (1250,390)]
        finally:await browser.close()
    summary={'result':'PASS' if all(r['passed'] for r in records) else 'FAIL','version':base.codex_desk.__version__,'package':str(base.PACKAGE),'widths':[1250,390],'results':records}
    (evidence/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    if summary['result']!='PASS':
        for r in records:
            if not r['passed']:print(r['traceback'],flush=True)
        raise SystemExit(1)
if __name__=='__main__':asyncio.run(main())
