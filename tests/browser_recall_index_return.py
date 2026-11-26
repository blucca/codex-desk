"""An explicit native scan refreshes only the unchanged, active submitted query.

DESK_TEST_TEMP=/workspace/temp DESK_TEST_EVIDENCE=/workspace/.private/index-return \
  DESK_CHROMIUM=/usr/bin/chromium python tests/browser_recall_index_return.py
DESK_USE_INSTALLED=1 tests installed assets. Native history is controlled; no
native executable, import, task, provider or external request is used.
DESK_RECALL_INDEX_CASES and DESK_RECALL_INDEX_WIDTHS select comma-separated cases
and viewport widths for focused acceptance.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk.server import Desk, handler, ThreadingHTTPServer
from codex_desk.drafts import load_draft, save_draft
from playwright.async_api import async_playwright


async def check(width, case, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP']); root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-index-return-') as temporary:
        folder = Path(temporary)
        home = folder / 'native-home'; home.mkdir()
        projects = {name: folder / name for name in ('alpha-project', 'beta-project')}
        for path in projects.values(): path.mkdir()
        (home / 'config.toml').write_text('model="fixture-only"\n')
        settings = (home / 'config.toml').read_bytes()
        def thread(identifier, project, text):
            return {'id': identifier, 'cwd': str(projects[project]), 'name': identifier,
                    'updatedAt': 1000, 'modelProvider': 'fixture-provider', 'turns': [
                        {'id': 'turn-' + identifier, 'status': 'completed', 'items': [
                            {'id': 'item-' + identifier, 'type': 'agentMessage', 'text': text}]}]}
        threads = [thread('ready-history', 'beta-project', 'READY EVIDENCE stays readable.'),
                   thread('alpha-history', 'alpha-project', 'ALPHA DECISION: retain the original retry budget.'),
                   thread('beta-history', 'beta-project', 'BETA DECISION: retain the next project choice.')]
        original = copy.deepcopy(threads)
        calls, http, queries, errors, external = [], [], [], [], []
        entered, release = threading.Event(), threading.Event()
        query_entered, query_release = threading.Event(), threading.Event()
        poll_release = asyncio.Event()
        immediate_jobs = []
        desk = Desk('never-executed', home, folder / 'desk-state')
        saved = desk.store.create(str(projects['alpha-project']), 'default',
                                  identifier='saved-preparation', name='Prepared existing work')
        desk.store.update(saved, thread_id='existing-prepared-thread', status='saved',
                          thread_saved=1, name_pending=0)
        save_draft(desk.store, saved, 'Preserved unsent preparation.', 'plan', 0)
        saved_sessions, saved_draft = desk.store.sessions(), load_draft(desk.store, saved)
        desk.native_index.replace_snapshot(threads[0])

        class Catalog:
            def request(self, method, params):
                calls.append({'method': method, 'params': copy.deepcopy(params)})
                assert method in ('thread/list', 'thread/read'), method
                if method == 'thread/list':
                    return {'data': [{k: v for k, v in t.items() if k != 'turns'} for t in threads],
                            'nextCursor': None}
                identifier = params['threadId']
                if identifier == 'alpha-history':
                    entered.set(); assert release.wait(30), 'Unreleased controlled native read'
                return {'thread': copy.deepcopy(next(t for t in threads if t['id'] == identifier))}

        desk.catalog = lambda: Catalog()
        if case == 'immediate-completion':
            release.set()
            ordinary_start = desk.history_scanner.start
            def start(limit=200):
                ordinary_start(limit)
                desk.history_scanner.worker.join(10)
                job = desk.history_scanner.status()
                assert job['status'] == 'completed'
                immediate_jobs.append(job)
                return job
            desk.history_scanner.start = start
        ordinary_recall = desk.recall
        def recall(q, cwd=None, include_archived=False, limit=30):
            data = ordinary_recall(q, cwd, include_archived, limit)
            queries.append({'q': q, 'cwd': cwd, 'archived': include_archived,
                            'total': data['total'], 'native_coverage': data['coverage']['native']})
            count = sum(row['q'] == q for row in queries)
            if q == 'alpha decision' and ((case == 'pending-search' and count == 1)
                                         or (case == 'newer-query' and count == 2)):
                query_entered.set(); assert query_release.wait(30), 'Unreleased controlled search'
            return data
        desk.recall = recall
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start(); browser = None
        try:
            browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width, 'height': 900 if width > 390 else 844})
            page.set_default_timeout(10_000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            def requested(request):
                parsed = urlsplit(request.url)
                http.append({'path': parsed.path, 'method': request.method,
                             'query': parse_qs(parsed.query)})
                if parsed.hostname != '127.0.0.1': external.append(request.url)
            page.on('request', requested)
            await page.goto(f'http://127.0.0.1:{server.server_port}')
            await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            await page.locator('#home-content').click()
            await page.wait_for_function("!$('recall-index').disabled")
            async def submit(q, wait=True):
                await page.locator('#recall-query').fill(q)
                await page.locator('#recall-query').press('Enter')
                if wait: await page.wait_for_function("!$('recall-search').disabled")
            async def scan_done():
                await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed')")
            async def wait_event(event):
                assert await asyncio.to_thread(event.wait, 10), 'Controlled operation was not reached'
            def recall_count(): return sum(row['path'] == '/api/recall' for row in http)
            if case in ('reader', 'result-focus', 'changed-scope'): await submit('ready evidence')
            if case == 'immediate-completion':
                await submit('alpha decision')
                assert await page.locator('.recall-result').count() == 0
                async def hold_poll(route):
                    if route.request.method == 'GET':
                        response = await route.fetch()
                        await poll_release.wait()
                        await route.fulfill(response=response)
                    else: await route.continue_()
                await page.route('**/api/history/index', hold_poll)
            before = recall_count()
            await page.locator('#recall-index').click(); await wait_event(entered)
            if case == 'reader':
                await page.locator('.recall-read').focus(); await page.keyboard.press('Enter')
                await page.wait_for_function("$('history-reader-body').getAttribute('aria-busy')==='false'")
                reader_before = await page.locator('#history-reader-body').inner_text()
            elif case == 'result-focus':
                await page.locator('.recall-read').focus()
                await page.locator('.recall-result').evaluate('(n)=>globalThis.keptRecallRow=n')
            elif case != 'immediate-completion':
                await submit('alpha decision', wait=case != 'pending-search')
                if case == 'pending-search': await wait_event(query_entered)
                else: assert await page.locator('.recall-result').count() == 0
            if case == 'edited-query': await page.locator('#recall-query').fill('unsubmitted different phrase')
            if case == 'edit-undo':
                await page.locator('#recall-query').fill('unsubmitted different phrase')
                await page.locator('#recall-query').fill('alpha decision')
            if case == 'changed-scope': await page.locator('#recall-project').select_option(str(projects['beta-project']))
            if case == 'changed-archived': await page.locator('#recall-archived').check()
            if case == 'new-submission': await submit('beta decision')
            if case == 'closed':
                # Chromium clears a focused type=search field on its first Escape.
                await page.locator('#recall-close').focus()
                await page.keyboard.press('Escape')
                await page.wait_for_function("!$('recall').open")
            if case == 'navigation':
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
            if case == 'cancel-retry':
                await page.locator('#recall-index-cancel').click()
                await page.wait_for_function("!$('recall-index-cancel').disabled")
                assert desk.history_scanner.cancelled.is_set()
                release.set()
                await asyncio.to_thread(desk.history_scanner.worker.join, 10)
                assert desk.history_scanner.status()['status'] == 'cancelled'
                await page.wait_for_function("$('recall-index-status').textContent.includes('Indexing cancelled')")
                before_cancel = recall_count()
                await page.wait_for_timeout(850)
                assert recall_count() == before_cancel and desk.native_index.search('alpha decision')['total'] == 0
                assert await page.locator('#recall-query').input_value() == 'alpha decision'
                before = recall_count()
                await page.locator('#recall-index-retry').click()
            if case not in ('immediate-completion', 'cancel-retry'): before = recall_count()
            release.set()
            await asyncio.to_thread(desk.history_scanner.worker.join, 10)
            assert desk.history_scanner.status()['status'] == 'completed'
            cache = desk.native_index.search('alpha decision')
            assert cache['total'] == 1, 'Actual native cache did not contain the newly indexed answer'
            if case == 'closed':
                await page.wait_for_timeout(1000)
                assert not await page.locator('#recall').evaluate('(n)=>n.open')
                assert recall_count() == before
                await page.locator('#home-content').click(); await scan_done()
                await page.wait_for_timeout(1000)
                assert recall_count() == before and await page.locator('.recall-result').count() == 0
            elif case == 'navigation':
                assert not await page.locator('#recall').evaluate('(n)=>n.open')
                await page.locator('#home-content').click(); await scan_done()
                await page.wait_for_timeout(1000)
                assert recall_count() == before and await page.locator('.recall-result').count() == 0
                assert await page.locator('#recall-query').input_value() == ''
            elif case == 'reader':
                await scan_done(); await page.wait_for_timeout(1000)
                assert recall_count() == before
                assert await page.locator('#history-reader').evaluate('(n)=>n.open')
                assert await page.locator('#history-reader-body').inner_text() == reader_before
                await page.keyboard.press('Escape')
                assert await page.locator('.recall-read').evaluate('(n)=>n===document.activeElement')
            elif case == 'result-focus':
                await scan_done(); await page.wait_for_timeout(1000)
                assert recall_count() == before
                assert await page.locator('.recall-read').evaluate('(n)=>n===document.activeElement')
                assert await page.locator('.recall-result').evaluate('(n)=>n===globalThis.keptRecallRow')
            elif case in ('edited-query', 'edit-undo', 'changed-scope', 'changed-archived'):
                await scan_done(); await page.wait_for_timeout(1000)
                assert recall_count() == before and await page.locator('.recall-result').count() == 0
                if case == 'edited-query': assert await page.locator('#recall-query').input_value() == 'unsubmitted different phrase'
                elif case == 'edit-undo': assert await page.locator('#recall-query').input_value() == 'alpha decision'
                elif case == 'changed-scope': assert await page.locator('#recall-project').input_value() == str(projects['beta-project'])
                else: assert await page.locator('#recall-archived').is_checked()
            elif case == 'pending-search':
                await scan_done(); await page.wait_for_timeout(150)
                assert recall_count() == before, 'Index completion superseded its in-flight user search'
                query_release.set()
                await page.wait_for_function("$('recall-results').children.length===1 && !$('recall-search').disabled", timeout=3500)
                assert recall_count() == before + 1
            elif case == 'newer-query':
                await scan_done(); await wait_event(query_entered)
                await submit('beta decision')
                assert 'BETA DECISION' in await page.locator('#recall-results').inner_text()
                query_release.set(); await page.wait_for_timeout(400)
                assert 'BETA DECISION' in await page.locator('#recall-results').inner_text()
                assert 'ALPHA DECISION' not in await page.locator('#recall-results').inner_text()
                assert await page.locator('#recall-query').input_value() == 'beta decision'
                assert recall_count() == before + 2
            elif case == 'new-submission':
                await scan_done()
                await page.wait_for_function("$('recall-results').children.length===1 && !$('recall-search').disabled", timeout=3500)
                assert 'BETA DECISION' in await page.locator('#recall-results').inner_text()
                assert await page.locator('#recall-query').input_value() == 'beta decision'
                assert recall_count() == before + 1
            else:
                await scan_done()
                await page.wait_for_function("$('recall-results').children.length===1 && !$('recall-search').disabled", timeout=3500)
                assert 'ALPHA DECISION' in await page.locator('#recall-results').inner_text()
                assert recall_count() == before + 1
                if case == 'immediate-completion':
                    assert immediate_jobs[0]['status'] == 'completed'
                    poll_release.set()
                await page.locator('.recall-read').focus(); await page.keyboard.press('Enter')
                await page.wait_for_function("$('history-reader-body').getAttribute('aria-busy')==='false'")
                assert 'original retry budget' in await page.locator('#history-reader-body').inner_text()
                await page.keyboard.press('Escape')
                assert await page.locator('.recall-read').evaluate('(n)=>n===document.activeElement')
            await page.wait_for_timeout(800)
            expected = before + (1 if case in ('first-use', 'pending-search', 'new-submission', 'immediate-completion', 'cancel-retry') else 2 if case == 'newer-query' else 0)
            assert recall_count() == expected, 'Completion refresh repeated'
            assert desk.store.sessions() == saved_sessions and load_draft(desk.store, saved) == saved_draft
            assert await page.evaluate('selected===null && generation===0')
            assert not any(row['method'] == 'POST' and row['path'] not in ('/api/history/index', '/api/history/index/cancel') for row in http)
            assert sum(row['method'] == 'POST' for row in http) == (3 if case == 'cancel-retry' else 1)
            assert not errors and not external
            assert threads == original and (home / 'config.toml').read_bytes() == settings
            assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('recall').scrollWidth<=$('recall').clientWidth")
            result = {'viewport': width, 'case': case, 'passed': True, 'native_cache_total': cache['total'],
                      'queries': queries, 'http_calls': http, 'native_calls': calls,
                      'javascript_errors': errors, 'external_requests': external,
                      'immediate_completion_jobs': immediate_jobs,
                      'native_model_turns': 0, 'imports': 0, 'saved_preparation': saved_draft}
            (evidence / f'{case}-{width}.json').write_text(json.dumps(result, indent=2) + '\n')
            (evidence / f'{case}-{width}.json').chmod(0o600)
            if case in ('first-use', 'cancel-retry', 'immediate-completion'):
                await page.screenshot(path=str(evidence / f'{case}-{width}.png'))
                (evidence / f'{case}-{width}.png').chmod(0o600)
            print(json.dumps({'viewport': width, 'case': case, 'passed': True, 'search_requests': recall_count()}), flush=True)
            return result
        except Exception:
            diagnostic = {'viewport': width, 'case': case, 'queries': queries, 'native_calls': calls,
                          'javascript_errors': errors, 'http_calls': http}
            try:
                diagnostic['page'] = await page.evaluate("({query:$('recall-query').value,scope:$('recall-project').value,summary:$('recall-summary').textContent,index:$('recall-index-status').textContent,rows:$('recall-results').children.length,recall:$('recall').open,reader:$('history-reader').open})")
                await page.screenshot(path=str(evidence / f'failure-{case}-{width}.png'))
            except Exception: pass
            (evidence / f'failure-{case}-{width}.json').write_text(json.dumps(diagnostic, indent=2) + '\n')
            raise
        finally:
            release.set(); query_release.set(); poll_release.set()
            if browser is not None: await browser.close()
            server.shutdown(); server.server_close(); worker.join(timeout=5)
            desk.close(); desk.store.db.close()


async def main():
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(Path(os.environ['DESK_TEST_TEMP']) / 'index-return-evidence')))
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    cases = ('first-use', 'edited-query', 'edit-undo', 'changed-scope', 'changed-archived',
             'pending-search', 'new-submission', 'newer-query', 'closed', 'navigation',
             'reader', 'result-focus', 'immediate-completion', 'cancel-retry')
    if os.environ.get('DESK_RECALL_INDEX_CASES'):
        cases = tuple(os.environ['DESK_RECALL_INDEX_CASES'].split(','))
    widths = tuple(int(width) for width in os.environ.get('DESK_RECALL_INDEX_WIDTHS', '1250,390').split(','))
    async with async_playwright() as playwright:
        results = [await check(width, case, playwright, evidence) for width in widths for case in cases]
    print(json.dumps({'recall_index_completion': 'PASS', 'checks': len(results),
                      'native_model_turns': 0, 'imports': 0}), flush=True)


if __name__ == '__main__': asyncio.run(main())
