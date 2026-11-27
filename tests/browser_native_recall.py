"""Explicit native-history recall through real loopback HTTP and SQLite.

DESK_TEST_TEMP=/workspace/temp DESK_TEST_EVIDENCE=/workspace/.private/native-recall \
  DESK_CHROMIUM=/usr/bin/chromium python tests/browser_native_recall.py
Native list/read/resume methods are controlled; no executable or provider is used.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Runtime
from playwright.async_api import async_playwright


async def check(width, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=f'desk-native-recall-{width}-') as temporary:
        folder = Path(temporary)
        home, project = folder / 'native-home', folder / 'project-接口'
        home.mkdir(); project.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        calls, http, errors, external, completed, holds = [], [], [], [], [], {}
        flags = {'list_error': False}

        def source(identifier, items):
            return {'id': identifier, 'cwd': str(project), 'name': 'Existing ' + identifier,
                    'updatedAt': 1000, 'modelProvider': 'fixture-provider', 'turns': [
                        {'id': 'turn-' + identifier, 'status': 'completed', 'items': items}]}

        unsafe = '<img src="https://recall-fetch.invalid/x" onerror="globalThis.__nativeXss=1">'
        threads = {
            'native-decision': source('native-decision', [
                {'id': 'decision-item', 'type': 'commandExecution', 'command': 'fixture inspect decision',
                 'status': 'completed', 'exitCode': 0,
                 'aggregatedOutput': '\n'.join(f'Retained command line {n}' for n in range(200)) + '\nUNOPENED DECISION use a queue. ' + unsafe}]),
            'native-other': source('native-other', [
                {'id': 'other-item', 'type': 'agentMessage', 'text': 'ALTERNATIVE DECISION keep the current scope.'}]),
            'native-missing': source('native-missing', [
                {'id': 'missing-item', 'type': 'agentMessage', 'text': 'DISAPPEARING DECISION preserve this hit.'}]),
            'native-slow': source('native-slow', [
                {'id': 'slow-item', 'type': 'agentMessage', 'text': 'DELAYED DECISION has a guarded navigation.'}]),
            'native-bulk': source('native-bulk', [
                {'id': f'bulk-{n}', 'type': 'agentMessage', 'text': f'BULK NATIVE CHOICE {n}'} for n in range(50)]),
        }
        # A native item ID may recur in a different turn; matching text alone is insufficient.
        threads['native-missing']['turns'].append({'id': 'different-turn', 'status': 'completed', 'items': []})
        for n in range(200):
            identifier = f'native-empty-{n:03}'
            threads[identifier] = source(identifier, [])

        def hold(kind, identifier):
            entered, release = threading.Event(), threading.Event()
            holds[(kind, identifier)] = entered, release
            return entered, release

        def wait_hold(kind, identifier):
            pair = holds.get((kind, identifier))
            if pair:
                pair[0].set()
                assert pair[1].wait(30), f'Unreleased native fixture: {kind} {identifier}'

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.pending, self.approvals = {}, {}
                self.lock, self.write_lock = threading.Lock(), threading.Lock()
                self.name_lock = threading.RLock()
                self.lifecycle_lock, self.turn_lock = threading.Lock(), threading.Lock()
                self.closing, self.persisted, self.counter = False, False, 0

            def request(self, method, params, timeout=30):
                calls.append({'method': method, 'session': self.id, 'params': params})
                assert method in ('thread/list', 'thread/read', 'thread/resume'), 'Unexpected model/new-thread method: ' + method
                if method == 'thread/list':
                    if flags['list_error']:
                        raise RuntimeError('Controlled native listing unavailable')
                    offset = int(params.get('cursor') or 0)
                    size = params.get('limit', 30)
                    rows = list(threads.values())[offset:offset + size]
                    return {'data': [{k: v for k, v in row.items() if k != 'turns'} for row in rows],
                            'nextCursor': str(offset + size) if offset + size < len(threads) else None}
                identifier = params['threadId'] if method == 'thread/read' else self.store.get(self.id)['thread_id']
                wait_hold('read' if method == 'thread/read' else 'resume', identifier)
                return {'thread': copy.deepcopy(threads[identifier]), 'model': 'fixture-model', 'modelProvider': 'fixture-provider'}

            def close(self):
                self.closing = True
                self.process.poll = lambda: 0

        def checkpoint(name):
            completed.append(name)
            print(json.dumps({'viewport': width, 'passed': name}), flush=True)

        def paths(path, method=None):
            return [c for c in http if c['path'] == path and (not method or c['method'] == method)]

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            # Exercise real cache limits and omissions with a compact controlled native read.
            desk.native_index = NativeRecallIndex(desk.store, max_thread_chars=7000, max_thread_items=40)
            desk.history_scanner.index = desk.native_index
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'
            browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width, 'height': 900 if width > 390 else 844})
            page.set_default_timeout(10_000)
            page.on('pageerror', lambda error: errors.append(str(error)))

            def requested(request):
                parsed = urlsplit(request.url)
                http.append({'path': parsed.path, 'method': request.method, 'query': parse_qs(parsed.query)})
                if parsed.hostname != '127.0.0.1':
                    external.append(request.url)
            page.on('request', requested)

            async def dialog():
                if not await page.locator('#recall').evaluate('(node)=>node.open'):
                    if await page.locator('#home-content').is_visible():
                        await page.locator('#home-content').click()
                    else:
                        await page.locator('#search-saved-content').click()
                await page.wait_for_function("!$('recall-index').disabled || !$('recall-index-cancel').hidden || !$('recall-index-retry').hidden")

            async def search(text):
                await dialog()
                await page.locator('#recall-query').fill(text)
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("!$('recall-search').disabled")

            async def scan_done(status='completed'):
                await page.wait_for_function("status=>$('recall-index-status').textContent.includes(status) && !$('recall-index').disabled", arg={'completed': 'scan completed', 'cancelled': 'cancelled', 'failed': 'indexing failed'}[status])

            async def reveal(identifier):
                await page.locator(f'.recall-result[data-item="{identifier}"] .recall-open').click()
                await page.wait_for_function("id=>!$('recall').open && document.querySelector('.recall-target')?.dataset.itemId===id", arg=identifier)

            async def no_overflow():
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && (!$('recall').open || $('recall').scrollWidth<=$('recall').clientWidth)")

            try:
                await page.goto(url)
                await page.wait_for_function("$('home-list').getAttribute('aria-busy')==='false'")
                assert await page.locator('#session-tools').is_hidden()
                assert await page.locator('#home-content').is_visible()
                await search('unopened decision')
                assert not [s for s in desk.store.sessions() if s['id'] != 'native-catalog']
                assert await page.locator('.recall-result').count() == 0
                assert not paths('/api/history/index', 'POST') and not paths('/api/import') and not paths('/api/open')
                assert all(c['method'] == 'thread/list' for c in calls)
                checkpoint('first-use Home content search leaves unopened native history unbound and unscanned')

                entered, release = hold('read', 'native-decision')
                await page.locator('#recall-index').click()
                assert await asyncio.to_thread(entered.wait, 5)
                await page.wait_for_function("$('recall-index-status').textContent.includes('1 seen')")
                await page.evaluate("$('recall-index').click();$('recall-index').click()")
                assert len(paths('/api/history/index', 'POST')) == 1
                assert await page.locator('#recall-index-cancel').is_visible()
                await page.locator('#recall-close').click()
                status_reads = len(paths('/api/history/index', 'GET'))
                await page.wait_for_timeout(1100)
                assert len(paths('/api/history/index', 'GET')) == status_reads
                assert desk.history_scanner.status()['status'] == 'running'
                await dialog()
                assert len(paths('/api/history/index', 'POST')) == 1
                release.set()
                await scan_done()
                job = desk.history_scanner.status()
                assert job['seen'] == 200 and job['indexed'] == 200 and job['has_more']
                assert '200 native conversations' in await page.locator('#recall-index-status').inner_text()
                assert 'beyond this pass' in await page.locator('#recall-index-status').inner_text()
                await page.locator('#recall-index-coverage summary').click()
                assert '10 omitted items' in await page.locator('#recall-native-coverage').inner_text()
                assert '40 items per conversation' in await page.locator('#recall-native-coverage').inner_text()
                await page.locator('#recall-index-coverage summary').click()
                assert not [s for s in desk.store.sessions() if s['id'] != 'native-catalog']
                checkpoint('explicit single scan shows progress, stops polling when closed, and reports bounded/truncated coverage')

                await search('unopened decision')
                assert await page.locator('.recall-result[data-kind="native-activity"]').count() == 1
                assert await page.locator('.recall-result').get_attribute('data-session') is None
                assert await page.locator('.recall-result').get_attribute('data-thread') == 'native-decision'
                assert 'fixture-provider' in await page.locator('.recall-binding').inner_text()
                assert not paths('/api/import') and not paths('/api/open')
                assert await page.locator('#recall-results img, #recall-results script').count() == 0
                assert not await page.evaluate('globalThis.__nativeXss')
                await no_overflow()
                await page.screenshot(path=str(evidence / f'native-hit-{width}.png'))
                await reveal('decision-item')
                binding = next(s for s in desk.store.sessions() if s['id'] != 'native-catalog')
                assert binding['thread_id'] == 'native-decision' and binding['profile'] == 'default'
                assert await page.evaluate("nativeThreadId==='native-decision' && itemTurns.get('decision-item')==='turn-native-decision'")
                assert len(paths('/api/import')) == 1 and len(paths('/api/open')) == 1
                assert await page.locator('.recall-target .activity-tool').evaluate('(node)=>node.open')
                assert await page.locator('.recall-target pre').evaluate('(node)=>node.scrollTop>0')
                assert await page.locator('#prompt').input_value() == ''
                checkpoint('explicit native hit imports its exact existing thread and focuses matching command/turn evidence')

                await dialog()
                reads = len([c for c in calls if c['method'] == 'thread/read'])
                await page.locator('#recall-index').click()
                await scan_done()
                assert desk.history_scanner.status()['skipped'] == 200
                assert len([c for c in calls if c['method'] == 'thread/read']) == reads
                checkpoint('repeat indexing skips unchanged native snapshots without rereads or duplicate bindings')

                threads['native-other']['updatedAt'] += 1
                entered, release = hold('read', 'native-other')
                await page.locator('#recall-index').click()
                assert await asyncio.to_thread(entered.wait, 5)
                await page.locator('#recall-index-cancel').click()
                release.set()
                await scan_done('cancelled')
                assert await page.locator('#recall-index-retry').is_visible()
                assert desk.native_index.search('unopened decision')['total'] == 1
                await page.locator('#recall-index-retry').click()
                await scan_done()
                assert desk.history_scanner.status()['indexed'] == 1
                flags['list_error'] = True
                await page.locator('#recall-index').click()
                await scan_done('failed')
                assert await page.locator('#recall-index-error').is_visible()
                flags['list_error'] = False
                await page.locator('#recall-index-retry').click()
                await scan_done()
                assert await page.locator('#recall-index-error').is_hidden()
                checkpoint('cancel preserves cached evidence; explicit retry recovers cancelled and failed scans')

                await search('disappearing decision')
                # Same item ID and same phrase now exist only in a different native turn.
                item = threads['native-missing']['turns'][0]['items'].pop()
                threads['native-missing']['turns'][1]['items'].append(item)
                await page.locator('.recall-open').click()
                await page.wait_for_function("$('recall-results').textContent.includes('not in the freshly loaded native activity')")
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert await page.locator('.recall-result[data-item="missing-item"]').count() == 1
                assert await page.evaluate("nativeThreadId==='native-missing' && itemTurns.get('missing-item')==='different-turn'")
                checkpoint('stale native hit with same item/phrase in a different turn keeps result rather than navigating incorrectly')

                await search('delayed decision')
                entered, release = hold('read', 'native-slow')
                await page.locator('.recall-open').click()
                assert await asyncio.to_thread(entered.wait, 5)
                await search('alternative decision')
                release.set()
                await page.wait_for_timeout(200)
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert await page.evaluate("nativeThreadId==='native-missing'")
                assert 'ALTERNATIVE DECISION' in await page.locator('#recall-results').inner_text()
                checkpoint('late native import response cannot open or replace a newer query')

                await search('delayed decision')
                entered, release = hold('resume', 'native-slow')
                await page.locator('.recall-open').click()
                assert await asyncio.to_thread(entered.wait, 5)
                await search('unopened decision')
                await page.locator('.recall-open').click()
                release.set()
                await page.wait_for_function("!$('recall').open && nativeThreadId==='native-decision' && document.querySelector('.recall-target')?.dataset.itemId==='decision-item'")
                await page.wait_for_timeout(150)
                assert await page.evaluate("nativeThreadId==='native-decision'")
                checkpoint('overlapping native resume/query generations reject stale navigation')

                await search('bulk native choice')
                assert await page.locator('.recall-result').count() == 30
                assert 'Showing 30 of 40' in await page.locator('#recall-summary').inner_text()
                assert await page.locator('#recall-next').is_visible()
                first_page=await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")
                await page.locator('#recall-next').click()
                await page.wait_for_function("!$('recall-search').disabled && $('recall-summary').textContent.includes('Items 31–40')")
                assert await page.locator('.recall-result').count()==10
                second_page=await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")
                assert not set(first_page).intersection(second_page)
                assert await page.locator('#recall-next').is_disabled()
                await page.locator('#recall-previous').click()
                await page.wait_for_function("!$('recall-search').disabled && $('recall-summary').textContent.includes('Items 1–30')")
                assert await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")==first_page
                checkpoint('all later matching items are reachable through stable nonoverlapping result pages without task execution')
                await no_overflow()
                await page.screenshot(path=str(evidence / f'native-bounded-{width}.png'))
                assert not errors and not external
                assert not paths('/api/turn') and not paths('/api/sessions') and not paths('/api/handoff/start') and not paths('/api/followups/send')
                assert all(c['method'] in ('thread/list', 'thread/read', 'thread/resume') for c in calls)
                assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                checkpoint('bounded results, zero browser errors/external requests/model turns/new threads, unchanged native settings')
                (evidence / f'acceptance-{width}.json').write_text(json.dumps({'viewport': width,
                    'passed': completed, 'javascript_errors': errors, 'external_requests': external,
                    'controlled_model_turns': 0, 'native_calls': calls, 'http_calls': http,
                    'job': desk.history_scanner.status(), 'coverage': desk.native_index.stats()}, ensure_ascii=False, indent=2) + '\n')
                return completed
            except Exception:
                diagnostic = {'viewport': width, 'passed': completed, 'javascript_errors': errors,
                              'job': desk.history_scanner.status(), 'recent_native_calls': calls[-15:], 'recent_http_calls': http[-30:]}
                try:
                    diagnostic['page'] = await page.evaluate('({selected,opening,query:$("recall-query").value,index:$("recall-index-status").textContent,summary:$("recall-summary").textContent,results:$("recall-results").textContent})')
                    await page.screenshot(path=str(evidence / f'failure-{width}.png'), full_page=True)
                except Exception:
                    pass
                (evidence / f'failure-{width}.json').write_text(json.dumps(diagnostic, ensure_ascii=False, indent=2) + '\n')
                print(json.dumps({'failure': diagnostic}, ensure_ascii=False), flush=True)
                raise
            finally:
                for _, release in holds.values():
                    release.set()
                await browser.close()
                server.shutdown(); server.server_close(); worker.join(timeout=5)
                desk.close(); desk.store.db.close()
                for path in evidence.iterdir():
                    if path.is_file():
                        path.chmod(0o600)


async def main():
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(Path(os.environ['DESK_TEST_TEMP']) / 'native-recall-evidence')))
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700); evidence.chmod(0o700)
    async with async_playwright() as playwright:
        results = {width: await check(width, playwright, evidence) for width in (1250, 390)}
    print(json.dumps({'native_recall_acceptance': 'passed', 'checks': sum(map(len, results.values())),
                      'viewports': list(results), 'controlled_model_turns': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
