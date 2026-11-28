#!/usr/bin/env python3
"""Installed A→existing unsent B→exact A evidence workflow at 1250/390.

Uses the maintained synthetic native transport/SQLite fixture from task-response
acceptance. No native executable, source import or model task is admitted.
"""
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

SPEC = importlib.util.spec_from_file_location('native_response_fixture', Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1]))/'examples/check_native_task_response.py')
base = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(base)
from codex_desk.drafts import load_draft
from codex_desk.followups import followup_snapshot, edit_followup, reserve_followup
from playwright.async_api import async_playwright

SOURCE, TURN, ITEM = 'source-A', 'source-tool-turn', 'source-long-tool'
KIND=os.environ.get('DESK_TEST_TOOL_KIND','mcpToolCall')
QUOTE = 'DECISIVE retry budget — café🙂 retained exactly.'
OUTPUT = 'ORIGINAL OUTPUT START\n' + '\n'.join(
    f'Original command line {i:04d}: retained source reasoning and retry evidence.' +
    (' ' + QUOTE if i in (50, 1300) else '') for i in range(1800)) + '\nORIGINAL OUTPUT END'


def source_thread(folder):
    return {'id': SOURCE, 'cwd': str(folder), 'name': 'Source A retry budget', 'source': 'cli',
            'modelProvider': 'fixture-provider', 'updatedAt': 1795800000,
            'turns': [{'id': TURN, 'status': 'failed', 'items': [
                {'id': 'source-proposed-plan', 'type': 'plan', 'text': 'Clarify the proposed retry policy before changing the queue.'},
                {'id':ITEM,'type':KIND,'server':'fixture','namespace':'fixture','tool':'read_retry','status':'inProgress','arguments':{},**({'result':{'content':[{'type':'text','text':OUTPUT}]}} if KIND=='mcpToolCall' else {'contentItems':[{'type':'text','text':OUTPUT}]})},
                {'id': 'source-commentary', 'type': 'agentMessage', 'phase': 'commentary',
                 'text': 'Commentary keeps the failed check visible; this is not an accepted plan.'}]}]}


async def one(browser, width, root, evidence):
    r = {'width': width, 'passed': False, 'checks': []}; http, errors, external = [], [], []
    with tempfile.TemporaryDirectory(dir=root, prefix=f'evidence-preparation-{width}-') as temporary:
        f = base.Fixture(Path(temporary)); context = None
        folder = Path(temporary) / 'removed-source-A'; folder.mkdir(); f.threads[SOURCE] = source_thread(folder); folder.rmdir()
        original = copy.deepcopy(f.threads[SOURCE]); namespace = hashlib.sha256(str(f.home.resolve()).encode()).hexdigest()

        class Catalog:
            def request(self, method, params, timeout=30):
                if method == 'thread/read':
                    return f.reader_type('never-executed', f.home, f.state).request(method, params, timeout)
                assert method == 'thread/list', method
                f.calls.append({'method': method, 'params': copy.deepcopy(params)})
                row = {k: v for k, v in original.items() if k != 'turns'}
                search = params.get('searchTerm', '').casefold()
                return {'data': [row] if search in row['name'].casefold() else [], 'nextCursor': None}

        f.catalog_type = Catalog
        preparation = f.prepared(); source_sql = None
        with patch.object(base.product, '_NativeReader', f.reader_type), patch.object(
                base.product, 'Runtime', side_effect=AssertionError('Task runtime forbidden')):
            try:
                context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
                page = await context.new_page(); page.set_default_timeout(12000)
                page.on('pageerror', lambda e: errors.append(str(e)))

                async def isolated(route):
                    if urlsplit(route.request.url).hostname != '127.0.0.1':
                        external.append(route.request.url); await route.abort()
                    else:
                        await route.continue_()

                await context.route('**/*', isolated)
                page.on('request', lambda q: http.append({'method': q.method, 'path': urlsplit(q.url).path, 'query': parse_qs(urlsplit(q.url).query)}))

                async def ready():
                    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                    await base.frames(page)

                def target():
                    return page.locator(f'.history-reader-item[data-turn-id="{TURN}"][data-item-id="{ITEM}"]')

                async def checkpoint(name):
                    assert not errors and not external, (errors, external)
                    assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && [...document.querySelectorAll('dialog[open]')].every(n=>n.scrollWidth<=n.clientWidth)"), name + ' overflow'
                    assert f.desk.runtimes == {} and not f.desk.store.get(SOURCE)
                    assert followup_snapshot(f.desk.store, base.ORIGINAL) == preparation[base.ORIGINAL]['queue']
                    assert f.prepared()[base.OTHER] == preparation[base.OTHER]
                    assert await page.evaluate('selected') == base.ORIGINAL
                    assert await page.locator('#turn-mode').input_value() == 'plan'
                    r['checks'].append(name); await page.screenshot(path=str(evidence / f'{width}-{name}.png'))

                async def close_reader():
                    await page.locator('#history-reader-back').click()
                    await page.wait_for_function("!$('history-reader').open")
                    if await page.locator('#history').evaluate('n=>n.open'):
                        await page.locator('#history-close').click()
                    await base.frames(page)

                await page.goto(f'http://127.0.0.1:{f.server.server_port}/')
                await page.locator(f'.session-row[data-session="{base.ORIGINAL}"] .session').click()
                await page.wait_for_function('id=>selected===id&&!opening', arg=base.ORIGINAL)
                initial_view = await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})")
                source_sql = f.sql(); calls_before = len(f.calls)
                await page.locator('#browse').click()
                await page.wait_for_function("$('history').open && $('native-list').querySelector('.native-read')")
                await page.locator('#native-list .native-read').click(); await ready()
                assert f.sql() == source_sql
                assert await page.evaluate("({selected,nativeThreadId,generation,text:$('prompt').value,mode:$('turn-mode').value})") == initial_view
                assert any(x['method'] == 'thread/read' and x['params']['threadId'] == SOURCE for x in f.calls[calls_before:])
                await checkpoint('read-removed-source-A-with-existing-B-unchanged')

                await page.locator('#history-reader-find-query').fill(QUOTE)
                await page.locator('#history-reader-find-query').press('Enter')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 2')")
                await page.keyboard.press('F3')
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 2 of 2')")
                await base.frames(page)
                assert int(await target().get_attribute('data-window-start')) > 20000
                rects=await target().locator('mark').evaluate('n=>[...n.getClientRects()].filter(r=>r.width&&r.height).map(r=>({left:r.left,right:r.right,top:r.top,bottom:r.bottom}))')
                first,last=rects[0],rects[-1]
                await page.mouse.move(last['right']-.5,(last['top']+last['bottom'])/2);await page.mouse.down()
                await page.mouse.move(first['left']+.5,(first['top']+first['bottom'])/2,steps=12);await page.mouse.up()
                assert await page.evaluate('getSelection().toString()') == QUOTE
                source_view = await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})")
                calls_before, boundary = len(f.calls), len(http)
                await target().locator('.history-reader-review-evidence').click()
                await page.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
                reviewed = await page.evaluate('DeskEvidencePreparation.state()')
                assert reviewed['reference']['quote'] == QUOTE and reviewed['reference']['native_home'] == namespace
                assert reviewed['reference']['thread_id'] == SOURCE and reviewed['reference']['turn_id'] == TURN and reviewed['reference']['item_id'] == ITEM
                projection = ('MCP · fixture / read_retry' if KIND=='mcpToolCall' else 'Tool · fixture / read_retry')+'\nStatus: inProgress\nArguments\n{}\n'+OUTPUT
                expected_start = OUTPUT.rfind(QUOTE)
                assert reviewed['reference']['projection']=='history-reader-tool-result/v1'
                assert reviewed['reference']['quote_start'] == expected_start
                assert reviewed['reference']['quote_end'] == expected_start + len(QUOTE)
                assert KIND in await page.locator('#evidence-preparation-source').inner_text()
                assert 'Native tool: read_retry' in await page.locator('#evidence-preparation-source').inner_text()
                assert 'Item status: inProgress' in await page.locator('#evidence-preparation-source').inner_text()
                assert reviewed['destination']['session'] == base.ORIGINAL and reviewed['destination']['mode'] == 'plan'
                assert await page.locator('#evidence-preparation-quote').text_content() == QUOTE
                assert f.calls[calls_before:] == [] and f.sql() == source_sql
                assert [x for x in http[boundary:] if x['path'] == '/api/native/home']
                await checkpoint('exact-later-window-quote-source-facts-destination-review')

                # Cancel restores source selection/window and cannot save anything.
                await page.locator('#evidence-preparation-cancel').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                assert await target().evaluate("n=>({start:n.dataset.windowStart,scroll:n.querySelector('pre').scrollTop,selection:getSelection().toString()})") == source_view
                assert f.sql() == source_sql
                await target().locator('.history-reader-review-evidence').click()
                await page.wait_for_function("$('evidence-preparation').open && !DeskEvidencePreparation.state().pending")
                await page.locator('#evidence-preparation-note').fill('Inspect the retry budget before the next edit.')
                native_boundary, boundary = len(f.calls), len(http)
                await page.locator('#evidence-preparation-append').click()
                await page.wait_for_function("!$('evidence-preparation').open")
                await page.wait_for_function("$('draft-status').textContent.includes('saved') || $('draft-status').textContent.includes('Saved')")
                saved = load_draft(f.desk.store, base.ORIGINAL)
                assert saved['text'].startswith(preparation[base.ORIGINAL]['draft']['text'] + '\n\nNext-step note:')
                assert saved['mode'] == 'plan' and saved['revision'] == preparation[base.ORIGINAL]['draft']['revision'] + 1
                assert saved['text'].count('<!-- codex-desk-evidence:v1 ') == 1
                parsed = await page.evaluate('DeskEvidencePreparation.parse($("prompt").value)')
                assert len(parsed) == 1 and parsed[0]['reference'] == reviewed['reference']
                assert f.calls[native_boundary:] == []
                assert [x['path'] for x in http[boundary:] if x['method'] == 'POST'] == ['/api/draft']
                for table, rows in source_sql.items():
                    if table != 'drafts':
                        assert f.sql()[table] == rows, table
                await close_reader(); await checkpoint('reviewed-source-appended-once-existing-plan-two-queues-intact')

                f.threads[SOURCE]['turns'][0]['items'][1].update(status='completed',durationMs=1537,**({'success':True} if KIND=='dynamicToolCall' else {}))
                projection = ('MCP · fixture / read_retry' if KIND=='mcpToolCall' else 'Tool · fixture / read_retry')+'\nStatus: completed'+(' · success: true' if KIND=='dynamicToolCall' else '')+' · 1537 ms\nArguments\n{}\n'+OUTPUT
                # Actual stored-draft action reveals the second identical phrase,
                # not its earlier equal occurrence, then returns exact editor view.
                if not await page.locator('#draft-evidence').evaluate('n=>n.open'):
                    await page.locator('#draft-evidence > summary').click()
                await page.locator('#draft-evidence-list button').scroll_into_view_if_needed()
                await page.locator('#prompt').evaluate("n=>{n.focus({preventScroll:true});n.setSelectionRange(12,30,'backward');n.scrollTop=45}")
                await base.frames(page)
                owner_view = await page.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")
                before, boundary, native_boundary = f.sql(), len(http), len(f.calls)
                await page.locator('#draft-evidence-list button').focus()
                await page.locator('#draft-evidence-list button').press('Enter'); await ready()
                assert await target().locator('mark').text_content() == QUOTE
                target_start = int(await target().get_attribute('data-window-start'))
                expected_utf16 = len(projection[:projection.rfind(QUOTE)].encode('utf-16-le')) // 2
                assert expected_utf16 - 11000 <= target_start <= expected_utf16
                assert await page.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
                assert 'still at this exact' in await page.locator('#history-reader-response').inner_text()
                assert f.sql() == before
                assert f.calls[native_boundary:] == [{'method': 'thread/read', 'params': {'threadId': SOURCE, 'includeTurns': True}}]
                assert not [x for x in http[boundary:] if x['path'] in ('/api/native/thread', '/api/open') or x['method'] != 'GET']
                await checkpoint('saved-preparation-reopens-exact-second-occurrence-read-only')
                await target().locator('mark').evaluate("n=>{const r=document.createRange();r.selectNodeContents(n);const s=getSelection();s.removeAllRanges();s.addRange(r)}")
                old_start=int(await target().get_attribute('data-window-start'))
                before_refresh=f.sql();native_before=len(f.calls)
                refreshed=f.threads[SOURCE]['turns'][0]['items'][1];refreshed['status']='inProgress';refreshed.pop('durationMs',None);refreshed.pop('success',None)
                initial_projection=('MCP · fixture / read_retry' if KIND=='mcpToolCall' else 'Tool · fixture / read_retry')+'\nStatus: inProgress\nArguments\n{}\n'+OUTPUT
                await page.locator('#history-reader-refresh').evaluate('n=>n.focus({preventScroll:true})');await page.locator('#history-reader-refresh').press('Enter')
                await page.wait_for_function("!$('history-reader-refresh').disabled&&$('history-reader-status').textContent.startsWith('Original refreshed.')");await base.frames(page)
                assert await target().locator('mark').text_content()==QUOTE and await page.evaluate('getSelection().toString()')==QUOTE
                assert int(await target().get_attribute('data-window-start'))==old_start+len(initial_projection)-len(projection)
                assert 'still at this exact' in await page.locator('#history-reader-response').inner_text()
                assert f.sql()==before_refresh and len(f.calls)==native_before+1
                await checkpoint('saved-tool-Refresh-metadata-keeps-exact-result-quote-window-and-Range')
                await close_reader()
                after_view = await page.evaluate("({text:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection,scroll:$('prompt').scrollTop,window:scrollY})")
                assert after_view == owner_view, (owner_view, after_view)
                assert await page.evaluate('document.activeElement.id') == 'prompt'
                await checkpoint('source-return-exact-unsent-editor-caret-scroll-mode')

                # Lost/changed original never consumes an equal phrase as replacement.
                for unavailable in ('changed', 'missing'):
                    f.threads[SOURCE] = copy.deepcopy(original)
                    if unavailable == 'changed':
                        command = f.threads[SOURCE]['turns'][0]['items'][1]
                        content=command['result']['content'][0] if KIND=='mcpToolCall' else command['contentItems'][0]
                        at=content['text'].rfind(QUOTE)
                        content['text']=content['text'][:at]+'X'+content['text'][at+1:]
                    else:
                        f.threads[SOURCE]['turns'][0]['items'].pop(1)
                    before = f.sql(); await page.locator('#draft-evidence-list button').click(); await ready()
                    expected = 'quote_changed' if unavailable == 'changed' else 'source_unavailable'
                    assert expected in await page.locator('#history-reader-response').inner_text()
                    assert 'No other item or occurrence' in await page.locator('#history-reader-response').inner_text()
                    assert await page.locator('#history-reader-saved-evidence-quote').text_content() == QUOTE
                    assert await page.locator('#history-reader-body mark').count() == 0
                    assert f.sql() == before and load_draft(f.desk.store, base.ORIGINAL) == saved
                    await checkpoint(unavailable + '-source-saved-excerpt-kept-no-substitution')
                    await close_reader()
                f.threads[SOURCE] = copy.deepcopy(original)

                r.update(passed=True,http=http,native_calls=f.calls,reviewed_reference=reviewed['reference'],javascript_errors=errors,native_admissions=0)
            except Exception as error:
                r.update(error=str(error), traceback=traceback.format_exc(), http=http, native_calls=f.calls, javascript_errors=errors)
                if 'page' in locals():
                    try:
                        r['observed'] = await page.evaluate("({selected,opening,error:$('error').textContent,review:DeskEvidencePreparation.state(),status:$('draft-status').textContent,sourceStatus:$('draft-evidence-status').textContent,reader:$('history-reader').open,readerStatus:$('history-reader-status').textContent})")
                        await page.screenshot(path=str(evidence / f'{width}-failed.png'))
                    except Exception as diagnostic:
                        r['diagnostic_error'] = str(diagnostic)
            finally:
                if context:
                    await context.close()
                f.stop()
                (evidence / f'case-{width}.json').write_text(json.dumps(r,indent=2,ensure_ascii=False)+'\n')
    (evidence / f'case-{width}.json').write_text(json.dumps(r, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: r[key] for key in ('width', 'passed', 'checks', 'error') if key in r}), flush=True)
    return r


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']).resolve(); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']).resolve(); evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as p:
        browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                                          args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            rows = [await one(browser, width, root, evidence) for width in (1250, 390)]
        finally:
            await browser.close()
    summary = {'result': 'PASS' if all(x['passed'] for x in rows) else 'FAIL', 'package': str(base.PACKAGE),
               'version': base.codex_desk.__version__, 'installed': os.environ.get('DESK_USE_INSTALLED') == '1',
               'widths': [1250, 390], 'results': rows}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: summary[key] for key in ('result', 'version', 'package', 'installed', 'widths')}), flush=True)
    for row in rows:
        if not row['passed']:
            print(row.get('traceback'), flush=True)
    if summary['result'] != 'PASS':
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
