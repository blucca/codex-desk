"""Index completed outside-Desk results while retaining today's Plan/queues.

Controlled native reads, real loopback HTTP/SQLite, and ephemeral Chromium.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, ThreadingHTTPServer, handler
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright


async def check(width, browser, root, evidence, refine=None):
    with tempfile.TemporaryDirectory(dir=root, prefix='bound-completion-') as tmp:
        folder = Path(tmp)
        yesterday, today, home = folder / 'yesterday', folder / 'today', folder / 'home'
        for path in (yesterday, today, home):
            path.mkdir()
        pending = [
            {'id': 'command', 'type': 'commandExecution', 'command': 'pytest tests/test_retry.py -q',
             'status': 'inProgress', 'exitCode': None, 'aggregatedOutput': 'Collecting retry tests\n'},
            {'id': 'mcp', 'type': 'mcpToolCall', 'server': 'local_tests', 'tool': 'inspect',
             'status': 'inProgress', 'arguments': {'case': 'cursor'}, 'result': None},
            {'id': 'dynamic', 'type': 'dynamicToolCall', 'namespace': 'local_tests', 'tool': 'inspect',
             'status': 'inProgress', 'arguments': {'case': 'replay'}, 'contentItems': None},
            {'id': 'plan', 'type': 'plan', 'text': 'Investigate checkout retry behavior'},
        ]
        finished = copy.deepcopy(pending)
        finished[0].update(status='completed', exitCode=0,
            aggregatedOutput='Collecting retry tests\nretry budget remains three attempts: 12 passed.\n')
        finished[1].update(status='completed', result={'content': [
            {'type': 'text', 'text': 'Retry cursor is stable; skip rebuilding cursor validation.'}]})
        finished[2].update(status='completed', success=True, contentItems=[
            {'type': 'inputText', 'text': 'Checkout replay deduplication is verified; skip repeating that investigation.'}])
        finished[3]['text'] = 'Skip retry reconstruction; inspect only timeout handling.'
        source = {'id': 'yesterday-native', 'name': 'Yesterday checkout checks', 'cwd': str(yesterday),
                  'modelProvider': 'fixture', 'updatedAt': 1795600010, 'status': {'type': 'active'},
                  'turns': [{'id': 'checks-turn', 'status': 'inProgress', 'startedAt': 1795600010,
                             'items': copy.deepcopy(pending)}]}
        calls, http, errors, external = [], [], [], []
        class Catalog:
            def request(self, method, params):
                calls.append({'method': method, 'params': copy.deepcopy(params)})
                if method == 'thread/list':
                    return {'data': [{k: v for k, v in source.items() if k != 'turns'}], 'nextCursor': None}
                assert method == 'thread/read' and params == {'threadId': source['id'], 'includeTurns': True}
                return {'thread': copy.deepcopy(source)}
        desk = Desk('never-executed', home, folder / 'state')
        desk.catalog = lambda: Catalog()
        for identifier, project, native in (('yesterday', yesterday, source['id']), ('today', today, 'today-native')):
            desk.store.create(str(project), 'default', identifier=identifier, name=identifier.title())
            desk.store.update(identifier, thread_id=native, status='saved', thread_saved=1, name_pending=0)
        desk.store.recall_snapshot('yesterday', source)
        desk.native_index.replace_snapshot(source)
        save_draft(desk.store, 'today', 'Unsent Plan: inspect remaining timeout behavior.', 'plan', 0)
        add_followup(desk.store, 'today', 'Check timeout behavior only.', 'native')
        add_followup(desk.store, 'today', 'Review the final patch.', 'plan')
        preparation = (load_draft(desk.store, 'today'), followup_snapshot(desk.store, 'today'))
        def open_saved(identifier):
            assert identifier == 'today'
            desk.store.update(identifier, status='ready', provider='fixture', model='fixture')
            return {'thread': {'id': 'today-native', 'cwd': str(today), 'name': 'Today', 'turns': []},
                    'model': 'fixture', 'modelProvider': 'fixture'}
        desk.open = open_saved
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()
        context = await browser.new_context(viewport={'width': width, 'height': 900 if width > 390 else 844})
        page = await context.new_page()
        page.set_default_timeout(10000)
        page.on('pageerror', lambda error: errors.append(str(error)))
        def requested(request):
            parsed = urlsplit(request.url)
            http.append({'method': request.method, 'path': parsed.path, 'query': parse_qs(parsed.query)})
            if parsed.hostname != '127.0.0.1':
                external.append(request.url)
        page.on('request', requested)
        try:
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.locator('.session-row[data-session="today"] .session').click()
            await page.wait_for_function("selected==='today' && !opening && !$('task').hidden")
            await page.locator('#prompt').evaluate("n=>{n.focus();n.setSelectionRange(12,35,'backward')}")
            selected = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
            await page.locator('#search-saved-content').evaluate('n=>n.click()')
            phrase = 'retry budget remains three attempts'
            await page.locator('#recall-query').fill(phrase)
            await page.locator('#recall-query').press('Enter')
            await page.wait_for_function("!$('recall-search').disabled")
            assert await page.locator('.recall-result').count() == 0
            source['turns'][0].update(status='completed', completedAt=1795600010, items=copy.deepcopy(finished))
            source['status'] = {'type': 'idle'}
            await page.wait_for_function("!$('recall-index').disabled")
            await page.locator('#recall-index').click()
            await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed') && !$('recall-search').disabled && $('recall-results').children.length===1")
            job = desk.history_scanner.status()
            assert (job['indexed'], job['failed']) == (1, 0)
            # Reading still works after the original folder disappears.
            yesterday.rmdir()
            checks = []
            for item, query in zip(finished, (phrase, 'Retry cursor is stable', 'Checkout replay deduplication is verified', 'inspect only timeout handling')):
                if query != phrase:
                    await page.locator('#recall-query').fill(query)
                    await page.locator('#recall-query').press('Enter')
                    await page.wait_for_function("!$('recall-search').disabled && $('recall-results').children.length===1")
                row = page.locator('.recall-result')
                assert await row.get_attribute('data-session') == 'yesterday'
                assert await row.get_attribute('data-thread') == source['id']
                assert await row.get_attribute('data-item') == item['id']
                saved_results = await page.locator('#recall-results').inner_text()
                saved_summary = await page.locator('#recall-summary').inner_text()
                lookups = sum(r['path'] == '/api/recall' for r in http)
                await row.locator('.recall-read').click()
                await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                target = page.locator('.history-reader-target')
                assert await target.get_attribute('data-turn-id') == 'checks-turn'
                assert await target.get_attribute('data-item-id') == item['id']
                assert await target.locator('mark').inner_text() == query
                assert await target.evaluate('n=>n.open')
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth")
                screenshot = evidence / f'{width}-{item["id"]}-original.png'
                await page.screenshot(path=str(screenshot)); screenshot.chmod(0o600)
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open && $('recall').open")
                assert await row.locator('.recall-read').evaluate('n=>document.activeElement===n')
                assert await page.locator('#recall-query').input_value() == query
                assert await page.locator('#recall-results').inner_text() == saved_results
                assert await page.locator('#recall-summary').inner_text() == saved_summary
                assert sum(r['path'] == '/api/recall' for r in http) == lookups
                assert await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})") == selected
                assert (load_draft(desk.store, 'today'), followup_snapshot(desk.store, 'today')) == preparation
                checks.append({'item': item['id'], 'type': item['type'], 'query': query, 'exact_original': True,
                               'back_retains_query_page_results_focus': True, 'current_plan_two_queues_unchanged': True})
            refinement = await refine(page, desk, source, width, evidence) if refine else None
            assert [r['path'] for r in http if r['method'] == 'POST'] == ['/api/open', '/api/history/index']
            assert all(c['method'] in ('thread/list', 'thread/read') for c in calls)
            assert not errors and not external and desk.runtimes == {}
            return {'width': width, 'job': job, 'checks': checks, 'javascript_errors': errors,
                    'model_calls': 0, 'native_calls': calls, 'http': http, 'refinement': refinement}
        finally:
            await context.close()
            server.shutdown(); server.server_close(); worker.join(3)
            desk.close(); desk.store.db.close()


async def main():
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']); evidence.mkdir(parents=True, exist_ok=True, mode=0o700); evidence.chmod(0o700)
    with patch('codex_desk.server.Runtime', side_effect=AssertionError('Native runtime forbidden')):
        async with async_playwright() as p:
            browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                args=['--no-sandbox', '--disable-dev-shm-usage'])
            try:
                checks = [await check(width, browser, root, evidence) for width in (1250, 390)]
            finally:
                await browser.close()
    result = {'result': 'PASS', 'groups': 8, 'checks': checks}
    summary = evidence / 'summary.json'; summary.write_text(json.dumps(result, indent=2) + '\n'); summary.chmod(0o600)
    print(json.dumps({'result': 'PASS', 'groups': 8, 'widths': [1250, 390]}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
