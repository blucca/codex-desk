"""Read original native history through real loopback HTTP, SQLite and Chromium.

DESK_TEST_TEMP=/workspace/temp DESK_CHROMIUM=/usr/bin/chromium \
  python tests/browser_history_reader.py
DESK_USE_INSTALLED=1 exercises an installed product instead of the source checkout.
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
from codex_desk.drafts import load_draft, save_draft
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Runtime
from playwright.async_api import async_playwright


async def check(width, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=f'desk-history-reader-{width}-') as temporary:
        folder = Path(temporary)
        home, active_project, deleted_project = (folder / name for name in
                                                 ('native-home', 'active-project', 'deleted-project-接口'))
        home.mkdir(); active_project.mkdir(); deleted_project.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        calls, http, errors, external, completed, holds, failures = [], [], [], [], [], {}, set()

        def agent(text, identifier):
            return {'id': identifier, 'type': 'agentMessage', 'text': text}

        def source(identifier, items, project=deleted_project):
            return {'id': identifier, 'cwd': str(project), 'name': 'Original ' + identifier,
                    'modelProvider': 'fixture-provider', 'updatedAt': 1795625000,
                    'turns': [{'id': 'turn-' + identifier, 'status': 'completed', 'items': items}]}

        unsafe = '<img src="https://history-reader.invalid/x" onerror="globalThis.__readerXss=1">'
        context = [agent(f'Original neighbouring context {n:02d}', f'context-{n}') for n in range(95)]
        context[0] = {'id': 'context-0', 'type': 'userMessage', 'content': [
            {'type': 'text', 'text': 'Original earliest request: inspect the queue.'}]}
        context[5] = agent('Same native item ID, different original turn; not the requested item.', 'target-command')
        context[44] = agent('NEIGHBOUR BEFORE: keep the queue rationale.', 'context-44')
        context[45] = {'id': 'target-command', 'type': 'commandExecution',
            'command': 'fixture inspect original queue', 'status': 'completed', 'exitCode': 0,
            'aggregatedOutput': 'ORIGINAL TEXT EARLIEST\n' + '\n'.join(
                f'Original command line {n:04d}: retained queue verification and context.' for n in range(800)) +
                '\nOLD ANSWER — use a queue for Café 项目. ' + unsafe + '\n' + '\n'.join(
                f'Original command line {n:04d}: later queue verification and context.' for n in range(800, 1200)) +
                '\nORIGINAL TEXT LATEST'}
        context[46] = agent('NEIGHBOUR AFTER: apply this answer to the next patch.', 'context-46')
        context[47] = {'id': 'context-47', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'inspect',
            'status': 'completed', 'arguments': {'path': 'queue.py', '_meta': {'secret': 'HIDDEN READER SECRET'}},
            'result': {'content': [{'type': 'text', 'text': 'Original MCP evidence keeps the queue.'},
                {'type': 'image', 'data': 'BINARY READER SECRET'}],
                'structuredContent': {'decision': 'Keep existing queue', '_meta': {'secret': 'HIDDEN READER SECRET'}},
                '_meta': {'secret': 'HIDDEN READER SECRET'}}}
        context[50] = {'id': 'reasoning-only', 'type': 'reasoning', 'text': 'REASONING READER SECRET',
                       'encryptedContent': 'ENCRYPTED READER SECRET'}
        context[51] = {'id': 'media-only', 'type': 'imageGeneration', 'data': 'BINARY READER SECRET'}
        original = source('deleted-context', [])
        original['turns'] = [{'id': f'turn-deleted-context-{n}', 'status': 'completed',
                              'items': context[n * 30:(n + 1) * 30]} for n in range(4)]
        threads = {'deleted-context': original,
            'retry-context': source('retry-context', [agent('RETRY ANSWER keeps retained evidence.', 'retry-item')]),
            'slow-context': source('slow-context', [agent('DELAYED ANSWER must not replace newer reading.', 'slow-item')]),
            'newer-context': source('newer-context', [agent('NEWER ANSWER remains the current reader.', 'newer-item')]),
            'bound-context': source('bound-context', [agent('BOUND ANSWER stays readable in imported history.', 'bound-item')]),
            'vanished-context': source('vanished-context', [agent('VANISHED ANSWER preserve the cached result.', 'vanished-item')])}
        active = source('active-thread', [agent('Active selected work stays in place.', 'active-item')], active_project)

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.pending, self.approvals = {}, {}
                self.lock, self.write_lock = threading.Lock(), threading.Lock()
                self.name_lock = threading.RLock()
                self.lifecycle_lock, self.turn_lock = threading.Lock(), threading.Lock()
                self.closing, self.persisted, self.counter = False, True, 0

            def request(self, method, params, timeout=30):
                calls.append({'method': method, 'session': self.id, 'params': dict(params)})
                assert method in ('thread/list', 'thread/read'), 'Unexpected native mutation: ' + method
                if method == 'thread/list':
                    start, size = int(params.get('cursor') or 0), params.get('limit', 30)
                    rows = list(threads.values())[start:start + size]
                    return {'data': [{k: v for k, v in row.items() if k != 'turns'} for row in rows],
                            'nextCursor': str(start + size) if start + size < len(threads) else None}
                identifier = params['threadId']
                assert params.get('includeTurns') is True
                if identifier in holds:
                    entered, release = holds[identifier]
                    entered.set()
                    assert release.wait(30), 'Unreleased original-history fixture: ' + identifier
                if identifier in failures:
                    raise RuntimeError('Controlled original history unavailable')
                return {'thread': copy.deepcopy(threads[identifier])}

            def close(self):
                self.closing = True
                self.process.poll = lambda: 0

        def checkpoint(name):
            completed.append(name)
            print(json.dumps({'viewport': width, 'passed': name}), flush=True)

        def paths(path, method=None):
            return [c for c in http if c['path'] == path and (method is None or c['method'] == method)]

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            desk.native_index = NativeRecallIndex(desk.store, max_thread_chars=120000, max_thread_items=80)
            desk.history_scanner.index = desk.native_index
            active_id = desk.store.create(str(active_project), 'default', identifier='active-session', name='Active selected task')
            desk.store.update(active_id, thread_id=active['id'], status='ready', model='fixture-model',
                              provider='fixture-provider', thread_saved=1, name_pending=0)
            # Model an already connected task. Desk.open returns this retained
            # runtime result without a new native resume, start or executable.
            connected = ControlledRuntime(desk.store, active_id, 'never-executed', home)
            connected.thread_result = {'thread': active, 'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
            desk.runtimes[active_id] = connected
            draft_text = 'Unsent active project draft — keep exactly. 补充任务'
            save_draft(desk.store, active_id, draft_text, 'plan', 0)
            bound_id = desk.store.create(str(deleted_project), 'default', identifier='bound-session',
                                         name='Previously imported task')
            desk.store.update(bound_id, thread_id='bound-context', status='saved', thread_saved=1, name_pending=0)
            desk.store.recall_snapshot(bound_id, threads['bound-context'])
            deleted_project.rmdir()
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

            async def search(text):
                assert not await page.locator('#history-reader').evaluate('(node)=>node.open')
                if not await page.locator('#recall').evaluate('(node)=>node.open'):
                    await page.locator('#search-saved-content').click()
                await page.locator('#recall-query').fill(text)
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("!$('recall-search').disabled")
                assert await page.locator('.recall-result').count() == 1

            async def ready():
                await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")

            async def read(text):
                await search(text)
                button = page.locator('.recall-read')
                assert await button.inner_text() == 'Read original conversation'
                assert await page.locator('.recall-open').count() == 1
                await button.click()
                await ready()

            async def back():
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open && $('recall').open")

            async def unchanged():
                current = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
                assert current == selected_state
                assert desk.store.sessions() == saved_sessions
                assert load_draft(desk.store, active_id) == saved_draft
                assert len(paths('/api/open')) == 1
                assert not any(paths(path) for path in ('/api/import', '/api/turn', '/api/sessions',
                    '/api/handoff/start', '/api/followups/send'))

            async def bounded():
                assert await page.locator('.history-reader-item').count() <= 40
                assert await page.locator('.history-reader-text').evaluate_all('(nodes)=>nodes.every(n=>n.textContent.length<=20000)')
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && $('history-reader').scrollWidth<=$('history-reader').clientWidth && $('history-reader-body').scrollWidth<=$('history-reader-body').clientWidth")

            try:
                await page.goto(url)
                await page.locator(f'.session-row[data-session="{active_id}"] .session').click()
                await page.wait_for_function("selected==='active-session' && nativeThreadId==='active-thread' && !opening && !$('task').hidden")
                assert await page.locator('#prompt').input_value() == draft_text
                selected_state = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
                await page.locator('#search-saved-content').click()
                await page.wait_for_function("!$('recall-index').disabled")
                await page.locator('#recall-index').click()
                await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed') && !$('recall-index').disabled")
                assert desk.history_scanner.status()['indexed'] == 6
                assert desk.native_index.stats()['truncated_threads'] == 1
                saved_sessions, saved_draft = desk.store.sessions(), load_draft(desk.store, active_id)
                saved_database = list(desk.store.db.iterdump())
                checkpoint('explicit indexing retains deleted-folder history without binding or native resume')

                await read('old answer')
                assert not deleted_project.exists()
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert str(deleted_project) in await page.locator('#history-reader-binding').inner_text()
                target = page.locator('.history-reader-target')
                assert await target.count() == 1
                assert await target.get_attribute('data-turn-id') == 'turn-deleted-context-1'
                assert await target.get_attribute('data-item-id') == 'target-command'
                assert await target.evaluate('(node)=>node.open')
                assert await target.locator('mark').inner_text() == 'OLD ANSWER'
                await page.wait_for_function("document.querySelector('.history-reader-target pre').scrollTop>0")
                assert 'Showing items 41–80 of 95. Page 2 of 3.' in await page.locator('#history-reader-coverage').inner_text()
                text = await page.locator('#history-reader-body').text_content()
                assert 'NEIGHBOUR BEFORE' in text and 'NEIGHBOUR AFTER' in text
                assert 'Original MCP evidence' in text
                assert all(secret not in text for secret in ('HIDDEN READER SECRET', 'BINARY READER SECRET',
                                                             'REASONING READER SECRET', 'ENCRYPTED READER SECRET'))
                assert await page.locator('#history-reader-body img, #history-reader-body script').count() == 0
                assert not await page.evaluate('globalThis.__readerXss')
                await bounded(); await unchanged()
                await page.screenshot(path=str(evidence / f'original-match-{width}.png'))
                checkpoint('deleted-project answer opens exact original turn/item, highlighted with neighbouring evidence')

                assert 'ORIGINAL TEXT EARLIEST' not in await target.locator('pre').inner_text()
                earlier, later = target.get_by_role('button', name='Earlier text'), target.get_by_role('button', name='Later text')
                for _ in range(8):
                    if await earlier.is_disabled():
                        break
                    await earlier.click(); await bounded()
                assert await earlier.is_disabled()
                assert 'ORIGINAL TEXT EARLIEST' in await target.locator('pre').inner_text()
                for _ in range(8):
                    if await later.is_disabled():
                        break
                    await later.click(); await bounded()
                assert await later.is_disabled()
                assert 'ORIGINAL TEXT LATEST' in await target.locator('pre').inner_text()
                await page.locator('#history-reader-previous').click()
                assert await page.locator('.history-reader-target').count() == 0
                assert 'Original earliest request' in await page.locator('#history-reader-body').text_content()
                assert await page.locator('#history-reader-previous').is_disabled()
                await bounded()
                await page.locator('#history-reader-next').click()
                assert await page.locator('.history-reader-target mark').inner_text() == 'OLD ANSWER'
                await page.locator('#history-reader-next').click()
                assert await page.locator('.history-reader-item').count() == 15
                assert await page.locator('#history-reader-next').is_disabled()
                assert 'Original neighbouring context 94' in await page.locator('#history-reader-body').text_content()
                await bounded(); await unchanged()
                checkpoint('long original text and neighbouring pages remain bounded and replace rather than accumulate DOM')

                await back()
                assert await page.locator('#recall-query').input_value() == 'old answer'
                assert await page.locator('.recall-result[data-thread="deleted-context"] [class="recall-read"]').count() == 1
                assert 'OLD ANSWER' in await page.locator('#recall-results').inner_text()
                await unchanged()
                checkpoint('Back retains the same query, cached hit, selected task and unsent draft')

                await page.locator('#recall-close').click()
                await page.locator('#search-saved-content').click()
                assert await page.locator('#recall-query').input_value() == 'old answer'
                assert await page.locator('.recall-result[data-thread="deleted-context"]').count() == 1
                await page.locator('.recall-read').click(); await ready()
                assert await page.locator('.history-reader-target mark').inner_text() == 'OLD ANSWER'
                await unchanged(); await back()
                checkpoint('closing and reopening retained recall results keeps Read original conversation usable')

                await read('bound answer')
                row = page.locator('.recall-result')
                assert await row.get_attribute('data-kind') == 'activity'
                assert await row.get_attribute('data-session') == bound_id
                assert await row.get_attribute('data-thread') == 'bound-context'
                assert await page.locator('.history-reader-target').get_attribute('data-turn-id') == 'turn-bound-context'
                assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'bound-item'
                assert await page.locator('.history-reader-target mark').inner_text() == 'BOUND ANSWER'
                assert str(deleted_project) in await page.locator('#history-reader-binding').inner_text()
                assert not deleted_project.exists() and bound_id not in desk.runtimes
                await unchanged(); await back()
                assert await page.locator('#recall-query').input_value() == 'bound answer'
                await page.locator('#recall-close').click()
                await page.locator('#search-saved-content').click()
                await page.locator('.recall-read').click(); await ready()
                assert await page.locator('.history-reader-target mark').inner_text() == 'BOUND ANSWER'
                await unchanged(); await bounded(); await back()
                checkpoint('bound activity reads its original deleted-folder history without duplicate native hit, resume or active draft mutation')

                failures.add('retry-context')
                await read('retry answer')
                assert await page.locator('#history-reader-error').is_visible()
                assert await page.locator('#history-reader-retry').is_visible()
                assert await page.locator('.history-reader-item').count() == 0
                failures.clear()
                await page.locator('#history-reader-retry').click(); await ready()
                assert await page.locator('#history-reader-error').is_hidden()
                assert await page.locator('.history-reader-target mark').inner_text() == 'RETRY ANSWER'
                await unchanged(); await back()
                checkpoint('failed original read keeps its cached hit and explicit Retry recovers readable history')

                await search('delayed answer')
                entered, release = threading.Event(), threading.Event()
                holds['slow-context'] = entered, release
                await page.locator('.recall-read').click()
                assert await asyncio.to_thread(entered.wait, 5)
                assert await page.locator('#history-reader-body').get_attribute('aria-busy') == 'true'
                await back()
                await read('newer answer')
                async with page.expect_response(lambda response: urlsplit(response.url).path == '/api/native/thread'
                    and parse_qs(urlsplit(response.url).query).get('id') == ['slow-context']):
                    release.set()
                await page.wait_for_timeout(150)
                assert await page.locator('#history-reader').evaluate('(node)=>node.open')
                assert 'NEWER ANSWER' in await page.locator('#history-reader-body').inner_text()
                assert 'DELAYED ANSWER' not in await page.locator('#history-reader-body').text_content()
                assert await page.locator('.history-reader-target').get_attribute('data-item-id') == 'newer-item'
                await unchanged(); await bounded(); await back()
                checkpoint('a delayed original read cannot replace a newer reader after Back and another query')

                await search('vanished answer')
                moved = threads['vanished-context']['turns'][0]['items'].pop()
                threads['vanished-context']['turns'][0]['items'].append(agent('Other original evidence stays readable.', 'other-readable'))
                threads['vanished-context']['turns'].append({'id': 'different-turn', 'status': 'completed', 'items': [moved]})
                await page.locator('.recall-read').click(); await ready()
                assert 'requested native turn/item is not present' in await page.locator('#history-reader-match').inner_text()
                assert await page.locator('.history-reader-target').count() == 0
                assert 'Other original evidence stays readable' in await page.locator('#history-reader-body').inner_text()
                assert 'VANISHED ANSWER' in await page.locator('#history-reader-body').text_content()
                await page.screenshot(path=str(evidence / f'original-missing-match-{width}.png'))
                await unchanged(); await bounded(); await back()
                assert await page.locator('#recall-query').input_value() == 'vanished answer'
                assert await page.locator('.recall-result[data-item="vanished-item"]').count() == 1
                checkpoint('missing exact native match gives an accurate notice while other original evidence and cached hit remain readable')

                # The same native IDs can also survive while their text changes.
                threads['vanished-context']['turns'] = [{'id': 'turn-vanished-context', 'items': [
                    agent('Corrected original evidence remains readable.', 'vanished-item')]}]
                await page.locator('.recall-read').click(); await ready()
                assert 'saved phrase is no longer' in await page.locator('#history-reader-match').inner_text()
                assert await page.locator('.history-reader-target').count() == 0
                assert 'Corrected original evidence' in await page.locator('#history-reader-body').inner_text()
                await unchanged()
                assert list(desk.store.db.iterdump()) == saved_database
                assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                assert all(c['method'] in ('thread/list', 'thread/read') for c in calls)
                assert not errors and not external
                checkpoint('changed original text is reported accurately; reader leaves SQLite, native settings and active work untouched')
                (evidence / f'acceptance-{width}.json').write_text(json.dumps({'viewport': width, 'passed': completed,
                    'javascript_errors': errors, 'external_requests': external, 'controlled_model_turns': 0,
                    'native_resume_calls': 0, 'native_calls': calls, 'http_calls': http,
                    'selected_state': selected_state, 'job': desk.history_scanner.status(),
                    'coverage': desk.native_index.stats()}, ensure_ascii=False, indent=2) + '\n')
                return completed
            except Exception:
                diagnostic = {'viewport': width, 'passed': completed, 'javascript_errors': errors,
                    'recent_native_calls': calls[-15:], 'recent_http_calls': http[-30:]}
                try:
                    diagnostic['page'] = await page.evaluate("({selected,generation,query:$('recall-query').value,reader:$('history-reader').open,status:$('history-reader-status').textContent,match:$('history-reader-match').textContent,coverage:$('history-reader-coverage').textContent,error:$('history-reader-error').textContent})")
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
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(Path(os.environ['DESK_TEST_TEMP']) / 'history-reader-evidence')))
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700); evidence.chmod(0o700)
    async with async_playwright() as playwright:
        results = {width: await check(width, playwright, evidence) for width in (1250, 390)}
    print(json.dumps({'original_history_reader_acceptance': 'passed', 'checks': sum(map(len, results.values())),
        'viewports': list(results), 'controlled_model_turns': 0, 'native_resume_calls': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
