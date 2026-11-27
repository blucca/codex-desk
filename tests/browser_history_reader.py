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
            'result': {'content': [{'type': 'text', 'text': 'Original MCP evidence keeps the queue.\n'
                    'RESOURCE ORIGINAL TEXT EARLIEST\n' + 'x' * 22000 + '\nRESOURCE ORIGINAL TEXT LATEST'},
                {'type': 'resource_link',
                 'uri': 'https://user:pass@docs.example/migration-report.md?token=LINK READER SECRET#auth',
                 'name': 'migration-report.md', 'title': 'Migration decision ledger',
                 'description': 'Reviewed migration notes', 'mimeType': 'text/markdown', 'size': 1200,
                 'annotations': {'audience': ['user'], 'priority': 0.8, 'lastModified': '2026-11-24',
                                 'private': 'ANNOTATION READER SECRET', '_meta': 'ANNOTATION READER SECRET'},
                 '_meta': 'LINK READER SECRET'},
                {'type': 'image', 'data': 'BINARY READER SECRET'}],
                'structuredContent': {'decision': 'Keep existing queue', '_meta': {'secret': 'HIDDEN READER SECRET'}},
                '_meta': {'secret': 'HIDDEN READER SECRET'}}}
        context[50] = {'id': 'reasoning-only', 'type': 'reasoning', 'text': 'REASONING READER SECRET',
                       'encryptedContent': 'ENCRYPTED READER SECRET'}
        uri_locations = [
            '//reader:URI READER SECRET@docs.example/report?token=URI QUERY SECRET#auth',
            'https://reader:URI READER SECRET@docs.example:bad/report?token=URI QUERY SECRET#auth',
            'data:image/svg+xml,%3Csvg%3EINLINE READER SECRET%3C/svg%3E',
        ]
        context[48] = {'id': 'safe-resource', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'resource',
            'status': 'completed', 'arguments': {}, 'result': {'content': [
                {'type': 'resource', 'resource': {'uri': uri, 'mimeType': 'text/plain',
                                                'text': 'URI RESOURCE ORIGINAL avoids a repeated probe.'}}
                for uri in uri_locations]}}
        context[49] = {'id': 'safe-media', 'type': 'dynamicToolCall', 'tool': 'inspect',
            'status': 'completed', 'success': True, 'arguments': {}, 'contentItems': [
                {'type': 'inputText', 'text': 'URI MEDIA ORIGINAL retains the inspection result.'},
                *[block for uri in uri_locations for block in (
                    {'type': 'inputImage', 'imageUrl': uri}, {'type': 'inputAudio', 'audioUrl': uri})]]}
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
        # Keep the original reader fixtures inside the explicit recent-200 scan,
        # and make the title catalog the only path to these older originals.
        for n in range(194):
            identifier = f'padding-{n:03d}'
            threads[identifier] = source(identifier, [agent(f'Recent retained context {n:03d}',
                f'padding-item-{n}')], active_project)
        catalog_query = 'Catalog + original? Café 项目'
        for n in range(32):
            identifier = f'catalog-old-{n:02d}'
            thread = source(identifier, [agent(f'CATALOG ORIGINAL {n:02d} page evidence {item:02d}',
                f'catalog-item-{n:02d}-{item:02d}') for item in range(42)],
                deleted_project if n in (0, 31) else active_project)
            thread.update(name=f'{catalog_query} {n:02d}', updatedAt=1795624000 - n)
            threads[identifier] = thread
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
                    search = params.get('searchTerm', '').casefold()
                    matches = [t for t in threads.values() if search in t['name'].casefold()
                               and (not params.get('cwd') or params['cwd'] == t['cwd'])]
                    rows = matches[start:start + size]
                    return {'data': [{k: v for k, v in row.items() if k != 'turns'} for row in rows],
                            'nextCursor': str(start + size) if start + size < len(matches) else None}
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

            async def catalog_search(text):
                assert not await page.locator('#history-reader').evaluate('(node)=>node.open')
                await page.locator('#history-search').fill(text)
                await page.locator('#history-search').press('Enter')
                await page.wait_for_function("!$('history-search-submit').disabled")

            def catalog_row(identifier):
                return page.locator('#native-list .native-row').filter(
                    has=page.get_by_text(threads[identifier]['name'], exact=True))

            async def catalog_back():
                await page.locator('#history-reader-back').click()
                await page.wait_for_function("!$('history-reader').open && $('history').open")

            async def catalog_read(identifier):
                row = catalog_row(identifier)
                assert await row.count() == 1
                expected = ['Review handoff', 'Read original conversation']
                if Path(threads[identifier]['cwd']).is_dir():expected.insert(0, 'Resume with current settings')
                assert await row.locator('button').all_text_contents() == expected
                before = len(paths('/api/native/thread'))
                await row.get_by_role('button', name='Read original conversation', exact=True).click()
                await ready()
                assert len(paths('/api/native/thread')) == before + 1
                assert paths('/api/native/thread')[-1]['query'] == {'id': [identifier]}
                assert await page.locator('#history').evaluate('(node)=>node.open')
                assert 'Thread ' + identifier in await page.locator('#history-reader-binding').inner_text()
                assert threads[identifier]['cwd'] in await page.locator('#history-reader-binding').inner_text()
                assert 'Page 1 of' in await page.locator('#history-reader-coverage').inner_text()
                assert await page.locator('.history-reader-target, #history-reader-body mark').count() == 0
                assert 'without opening or resuming a task' in await page.locator('#history-reader-match').inner_text()
                await bounded(); await unchanged()

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
                await page.wait_for_function("$('home-list').children.length===6")
                assert await page.locator('#home-list .native-read').count() == 6
                await page.locator(f'.session-row[data-session="{active_id}"] .session').click()
                await page.wait_for_function("selected==='active-session' && nativeThreadId==='active-thread' && !opening && !$('task').hidden")
                assert await page.locator('#prompt').input_value() == draft_text
                selected_state = await page.evaluate("({selected,nativeThreadId,generation,prompt:$('prompt').value,mode:$('turn-mode').value})")
                await page.locator('#search-saved-content').click()
                await page.wait_for_function("!$('recall-index').disabled")
                await page.locator('#recall-index').click()
                await page.wait_for_function("$('recall-index-status').textContent.includes('scan completed') && !$('recall-index').disabled")
                assert desk.history_scanner.status()['indexed'] == 200
                assert desk.history_scanner.status()['has_more'] is True
                assert not any(c['params'].get('threadId', '').startswith('catalog-old-') for c in calls)
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
                assert await page.locator('#history-reader-body').evaluate('(body)=>body===document.activeElement')
                await bounded()
                await page.locator('#history-reader-next').click()
                assert await page.locator('.history-reader-target mark').inner_text() == 'OLD ANSWER'
                await page.locator('#history-reader-next').click()
                assert await page.locator('.history-reader-item').count() == 15
                assert await page.locator('#history-reader-next').is_disabled()
                assert await page.locator('#history-reader-body').evaluate('(body)=>body===document.activeElement')
                await page.keyboard.press('Tab')
                assert await page.locator('#history-reader-body .history-reader-turn-task').first.evaluate(
                    '(button,action)=>button===document.activeElement && button.tagName==="BUTTON" && button.textContent==="Read task context" && button.dataset.taskAction===action',
                    'turn:'+original['turns'][2]['id'])
                await page.keyboard.press('Tab')
                assert await page.locator('#history-reader-body').evaluate('(body)=>body.contains(document.activeElement) && document.activeElement.tagName==="SUMMARY"')
                assert 'Original neighbouring context 94' in await page.locator('#history-reader-body').text_content()
                await bounded(); await unchanged()
                checkpoint('long original text and neighbouring pages remain bounded and replace rather than accumulate DOM')

                async def find_original(phrase):
                    await page.locator('#history-reader-find-query').fill(phrase)
                    await page.locator('#history-reader-find-query').press('Enter')
                    await page.wait_for_function("$('history-reader-find-form').getAttribute('aria-busy')==='false'")
                native_reads_before=len(paths('/api/native/thread'))
                await find_original('ORIGINAL TEXT LATEST')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='target-command'
                assert await page.locator('.history-reader-target mark').inner_text()=='ORIGINAL TEXT LATEST'
                assert 'ORIGINAL TEXT EARLIEST' not in await page.locator('.history-reader-target pre').inner_text()
                await page.context.grant_permissions(['clipboard-read','clipboard-write'])
                await page.locator('.history-reader-target .history-reader-copy-text').click()
                await page.wait_for_function("document.querySelector('.history-reader-target .history-reader-copy-status').textContent.includes('copied')")
                copied=await page.evaluate('navigator.clipboard.readText()')
                assert 'ORIGINAL TEXT EARLIEST' in copied and 'ORIGINAL TEXT LATEST' in copied
                assert len(copied)>20000 and context[45]['aggregatedOutput'] in copied
                await page.locator('.history-reader-target .history-reader-copy-source').click()
                await page.wait_for_function("document.querySelector('.history-reader-target .history-reader-copy-status').textContent.includes('Source reference copied')")
                copied_source=await page.evaluate('navigator.clipboard.readText()')
                assert all(value in copied_source for value in ('deleted-context','turn-deleted-context-1','target-command',str(deleted_project)))
                await find_original('Cafe\u0301')
                assert await page.locator('.history-reader-target mark').inner_text()=='Café'
                await find_original('Original neighbouring context')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='context-1'
                await page.keyboard.press('F3')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='context-2'
                await page.keyboard.press('Shift+F3')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='context-1'
                await page.keyboard.press('Shift+F3')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='context-94'
                assert 'Page 3 of 3' in await page.locator('#history-reader-coverage').inner_text()
                await find_original('NO READER MATCH HERE')
                assert 'No matches' in await page.locator('#history-reader-find-status').inner_text()
                assert await page.locator('.history-reader-target').count()==0
                await find_original('OLD ANSWER')
                assert await page.locator('.history-reader-target').get_attribute('data-item-id')=='target-command'
                assert len(paths('/api/native/thread'))==native_reads_before
                await bounded();await unchanged()
                await page.screenshot(path=str(evidence / f'original-find-copy-{width}.png'))
                checkpoint('full readable-item Find crosses pages/windows, exact Unicode offsets and F3 wrap; clipboard copies full evidence/source without re-read or preparation change')

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

                for phrase in ('Migration decision ledger', 'text/markdown', 'size: 1200', '2026-11-24'):
                    await read(phrase)
                    target = page.locator('.history-reader-target')
                    assert await target.count() == 1
                    assert await target.get_attribute('data-turn-id') == 'turn-deleted-context-1'
                    assert await target.get_attribute('data-item-id') == 'context-47'
                    assert await target.locator('mark').inner_text() == phrase
                    assert await target.evaluate('(node)=>node.open')
                    assert await page.locator('#history-reader-match').inner_text() == 'Showing the matching original native turn and item.'
                    assert 'Showing items 41–80 of 95. Page 2 of 3.' in await page.locator('#history-reader-coverage').inner_text()
                    text = await target.locator('pre').text_content()
                    for field in ('name: migration-report.md', 'title: Migration decision ledger',
                                  'description: Reviewed migration notes', 'mimeType: text/markdown', 'size: 1200',
                                  'Annotations: {', '"audience": [', '"priority": 0.8', '"lastModified": "2026-11-24"'):
                        assert field in text
                    assert all(secret not in text for secret in ('LINK READER SECRET', 'ANNOTATION READER SECRET',
                                                                 'HIDDEN READER SECRET', 'BINARY READER SECRET',
                                                                 'user:pass', '?token=', '#auth', '_meta'))
                    await bounded(); await unchanged()
                    if phrase == 'Migration decision ledger':
                        assert 'RESOURCE ORIGINAL TEXT LATEST' in text and 'RESOURCE ORIGINAL TEXT EARLIEST' not in text
                        await target.get_by_role('button', name='Earlier text').click()
                        assert 'RESOURCE ORIGINAL TEXT EARLIEST' in await target.locator('pre').text_content()
                        await target.get_by_role('button', name='Later text').click()
                        assert await target.locator('mark').inner_text() == phrase
                        await page.screenshot(path=str(evidence / f'resource-public-match-{width}.png'))
                    await back()
                checkpoint('indexed MCP resource name/title, MIME, numeric size and public annotations remain original-readable and highlighted across bounded text windows')

                for phrase, identifier in (('URI RESOURCE ORIGINAL', 'safe-resource'),
                                           ('URI MEDIA ORIGINAL', 'safe-media')):
                    await read(phrase)
                    target = page.locator('.history-reader-target')
                    assert await target.get_attribute('data-item-id') == identifier
                    assert await target.locator('mark').inner_text() == phrase
                    text = await target.locator('pre').text_content()
                    for descriptor in ('//docs.example/report', 'https://docs.example:bad/report',
                                       'image/svg+xml; inline payload'):
                        assert descriptor in text
                    assert all(secret not in text for secret in ('URI READER SECRET', 'URI QUERY SECRET',
                                                                 'INLINE READER SECRET', '%3Csvg'))
                    assert await page.locator('#history-reader-body img, #history-reader-body audio').count() == 0
                    await page.screenshot(path=str(evidence / f'{identifier}-{width}.png'))
                    await bounded(); await unchanged(); await back()
                checkpoint('original MCP resources and dynamic media retain public addresses and evidence, without URI credentials or semicolon-free inline bytes')

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

                await back()
                await page.locator('#recall-close').click()
                await page.locator('#browse').click()
                await page.wait_for_function("!$('history-search-submit').disabled")
                assert paths('/api/native')[-1]['query'] == {}
                assert await page.locator('#native-list .native-row').count() == 30
                for cursor in range(30, 181, 30):
                    await page.locator('#more').click()
                    await page.wait_for_function(
                        "$('native-list').children.length===%d && !$('more').disabled" % (cursor + 30))
                    assert paths('/api/native')[-1]['query'] == {'cursor': [str(cursor)]}
                assert list(threads).index('catalog-old-00') == 200
                assert desk.history_scanner.status()['seen'] == 200
                await catalog_read('catalog-old-00')
                assert not deleted_project.exists()
                assert 'CATALOG ORIGINAL 00 page evidence 00' in await page.locator('#history-reader-body').inner_text()
                assert 'Showing items 1–40 of 42. Page 1 of 2.' in await page.locator('#history-reader-coverage').inner_text()
                await page.screenshot(path=str(evidence / f'catalog-original-deleted-{width}.png'))
                await catalog_back()
                assert await page.locator('#history-search').input_value() == ''
                assert await page.locator('#native-list .native-row').count() == 210
                assert await page.locator('#more').is_visible()
                checkpoint('Browse all reads an unindexed deleted-folder original beyond the recent-200 boundary without resume or import')

                # The title filter is native-scoped and each page retains the
                # exact punctuation/Unicode query; it never searches messages.
                await catalog_search('  ' + catalog_query + '  ')
                assert await page.locator('#native-list .native-row').count() == 30
                assert paths('/api/native')[-1]['query'] == {'search': [catalog_query]}
                await page.locator('#more').click()
                await page.wait_for_function("$('native-list').children.length===32 && !$('more').disabled")
                assert paths('/api/native')[-1]['query'] == {'search': [catalog_query], 'cursor': ['30']}
                assert await page.locator('#more').is_hidden()
                title_calls = [c['params'] for c in calls if c['method'] == 'thread/list'
                               and c['params'].get('searchTerm') == catalog_query]
                assert len(title_calls) == 2
                assert all(p['modelProviders'] == [] and p['sortKey'] == 'updated_at'
                           and 'cwd' not in p for p in title_calls)
                await catalog_row('catalog-old-31').get_by_role('button', name='Read original conversation').evaluate(
                    '(button)=>{globalThis.__catalogReadButton=button}')
                await catalog_read('catalog-old-31')
                assert 'CATALOG ORIGINAL 31 page evidence 00' in await page.locator('#history-reader-body').inner_text()
                assert 'CATALOG ORIGINAL 00' not in await page.locator('#history-reader-body').text_content()
                await page.screenshot(path=str(evidence / f'catalog-original-title-{width}.png'))
                await page.locator('#history-reader-next').click()
                assert await page.locator('.history-reader-item').count() == 2
                assert 'CATALOG ORIGINAL 31 page evidence 41' in await page.locator('#history-reader-body').inner_text()
                assert await page.locator('#history-reader-next').is_disabled()
                await bounded(); await unchanged(); await catalog_back()
                assert await page.locator('#history-search').input_value() == '  ' + catalog_query + '  '
                assert await page.locator('#native-list .native-row').count() == 32
                assert await page.locator('#more').is_hidden()
                await catalog_row('catalog-old-31').scroll_into_view_if_needed()
                await page.screenshot(path=str(evidence / f'catalog-title-back-{width}.png'))
                checkpoint('title-list Read opens the exact deleted-folder thread on page one and Back retains its query, rows and pagination')

                await catalog_search('page evidence')
                assert await page.locator('#native-list .native-row').count() == 0
                assert 'No saved conversation titles match' in await page.locator('#history-summary').inner_text()
                await catalog_search('Original newer-context')
                before = len(paths('/api/native/thread'))
                await page.evaluate('globalThis.__catalogReadButton.click()')
                assert not await page.locator('#history-reader').evaluate('(node)=>node.open')
                assert len(paths('/api/native/thread')) == before
                assert await page.locator('#native-list .native-row').count() == 1
                await catalog_read('newer-context')
                assert 'NEWER ANSWER' in await page.locator('#history-reader-body').inner_text()
                await catalog_back(); await unchanged()
                checkpoint('title search excludes body-only matches and a detached old row cannot open a reader after the catalog query changes')

                await catalog_search(catalog_query)
                await page.locator('#more').click()
                await page.wait_for_function("$('native-list').children.length===32 && !$('more').disabled")
                entered, release = threading.Event(), threading.Event()
                holds['catalog-old-31'] = entered, release
                await catalog_row('catalog-old-31').get_by_role('button', name='Read original conversation').click()
                assert await asyncio.to_thread(entered.wait, 5)
                assert await page.locator('#history-reader-body').get_attribute('aria-busy') == 'true'
                await catalog_back()
                await page.locator('#history-close').click()
                await page.locator('#browse').click()
                await page.wait_for_function("!$('history-search-submit').disabled")
                await catalog_search('Original retry-context')
                await catalog_read('retry-context')
                async with page.expect_response(lambda response: urlsplit(response.url).path == '/api/native/thread'
                    and parse_qs(urlsplit(response.url).query).get('id') == ['catalog-old-31']):
                    release.set()
                await page.wait_for_timeout(150)
                assert await page.locator('#history-reader').evaluate('(node)=>node.open')
                assert 'RETRY ANSWER' in await page.locator('#history-reader-body').inner_text()
                assert 'CATALOG ORIGINAL 31' not in await page.locator('#history-reader-body').text_content()
                await bounded(); await unchanged(); await catalog_back()
                assert await page.locator('#history-search').input_value() == 'Original retry-context'
                assert await page.locator('#native-list .native-row').count() == 1
                assert list(desk.store.db.iterdump()) == saved_database
                assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                assert all(c['method'] in ('thread/list', 'thread/read') for c in calls)
                assert not errors and not external
                checkpoint('late catalog original read cannot replace a newer reader after Back, close/reopen and a different title query; active work and native settings stay exact')
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
                    diagnostic['page'] = await page.evaluate("({selected,generation,query:$('recall-query').value,catalog:$('history').open,catalogQuery:$('history-search').value,catalogRows:$('native-list').children.length,catalogSummary:$('history-summary').textContent,reader:$('history-reader').open,status:$('history-reader-status').textContent,match:$('history-reader-match').textContent,coverage:$('history-reader-coverage').textContent,error:$('history-reader-error').textContent})")
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


async def check_empty_turns(width, playwright, evidence):
    """Focused original-read acceptance; includes item-free outcomes and a page edge."""
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=f'desk-empty-turns-{width}-') as temporary:
        folder = Path(temporary)
        home, project = folder / 'home', folder / 'project'
        home.mkdir(); project.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        calls, errors, external, completed = [], [], [], []
        empty = [
            {'id': 'empty-completed', 'status': 'completed', 'itemsView': 'full', 'items': [], 'error': None},
            {'id': 'empty-failed', 'status': 'failed', 'itemsView': 'full', 'items': [],
             'error': {'message': 'Provider rejected the original retry.', 'codexErrorInfo': 'usageLimitExceeded'}},
            {'id': 'empty-interrupted', 'status': 'interrupted', 'itemsView': 'full', 'items': [], 'error': None},
        ]
        def source(identifier, turns):
            return {'id': identifier, 'cwd': str(project), 'name': 'Original ' + identifier,
                    'modelProvider': 'fixture-provider', 'updatedAt': 1795720000, 'turns': turns}
        boundary = source('boundary-outcomes', [
            {'id': 'earlier-context', 'status': 'completed', 'items': [
                {'id': f'context-{n}', 'type': 'agentMessage', 'text': f'Original context {n:02d}'}
                for n in range(39)]},
            *copy.deepcopy(empty),
            {'id': 'answer-turn', 'status': 'completed', 'items': [
                {'id': 'boundary-answer', 'type': 'agentMessage', 'text': 'BOUNDARY ANSWER remains exact.'}]},
            {'id': 'invalid-items-turn', 'status': 'failed', 'items': [None, False, 'invalid native item'],
             'error': {'message': 'This original outcome remains visible despite unreadable items.'}},
        ])
        only_empty = source('only-empty-outcomes', copy.deepcopy(empty))
        active = source('active-thread', [{'id': 'active-turn', 'status': 'completed', 'items': [
            {'id': 'active-item', 'type': 'agentMessage', 'text': 'Selected work stays unchanged.'}]}])
        threads = {t['id']: t for t in (boundary, only_empty)}

        class ControlledRuntime:
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {}
                self.thread_result = {'thread': active, 'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
            def request(self, method, params, timeout=30):
                calls.append({'method': method, 'params': dict(params)})
                assert method in ('thread/list', 'thread/read'), 'Unexpected native mutation: ' + method
                if method == 'thread/list':
                    query = params.get('searchTerm', '').casefold()
                    return {'data': [{key: value for key, value in t.items() if key != 'turns'}
                                     for t in threads.values() if query in t['name'].casefold()], 'nextCursor': None}
                assert params == {'threadId': params['threadId'], 'includeTurns': True}
                return {'thread': copy.deepcopy(threads[params['threadId']])}
            def close(self):
                self.process.poll = lambda: 0

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            active_id = desk.store.create(str(project), 'default', identifier='active-session', name='Selected active task')
            desk.store.update(active_id, thread_id=active['id'], status='ready', model='fixture-model',
                              provider='fixture-provider', thread_saved=1, name_pending=0)
            desk.runtimes[active_id] = ControlledRuntime(desk.store, active_id, 'never-executed', home)
            draft_text = 'Unsent selected draft — preserve exactly. 保留'
            save_draft(desk.store, active_id, draft_text, 'plan', 0)
            desk.native_index.replace_snapshot(boundary)
            saved_draft = load_draft(desk.store, active_id)
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
            page = await browser.new_page(viewport={'width': width, 'height': 900 if width > 390 else 844})
            page.set_default_timeout(10_000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: external.append(request.url)
                    if urlsplit(request.url).hostname != '127.0.0.1' else None)
            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function("$('home-list').children.length===2")
                await page.locator(f'.session-row[data-session="{active_id}"] .session').click()
                await page.wait_for_function("selected==='active-session' && nativeThreadId==='active-thread' && !opening && !$('task').hidden")
                assert await page.locator('#prompt').input_value() == draft_text
                selected_state = await page.evaluate("({selected,generation,title:$('title').textContent,prompt:$('prompt').value,mode:$('turn-mode').value})")
                saved_database = list(desk.store.db.iterdump())
                async def unchanged():
                    assert await page.evaluate("({selected,generation,title:$('title').textContent,prompt:$('prompt').value,mode:$('turn-mode').value})") == selected_state
                    assert load_draft(desk.store, active_id) == saved_draft
                    assert list(desk.store.db.iterdump()) == saved_database
                    assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                    assert not errors and not external
                    assert all(c['method'] in ('thread/list', 'thread/read') for c in calls)
                async def ready():
                    await page.wait_for_function("$('history-reader').open && $('history-reader-body').getAttribute('aria-busy')==='false'")
                    assert await page.locator('#history-reader-error').is_hidden()
                    assert await page.locator('.history-reader-item').count() <= 40
                    assert await page.locator('.history-reader-item, .history-reader-turn-only').count() <= 40

                await page.locator('#search-saved-content').click()
                await page.locator('#recall-query').fill('boundary answer')
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("!$('recall-search').disabled")
                assert await page.locator('.recall-result').count() == 1
                await page.locator('.recall-read').click(); await ready()
                target = page.locator('.history-reader-target')
                assert await target.get_attribute('data-turn-id') == 'answer-turn'
                assert await target.get_attribute('data-item-id') == 'boundary-answer'
                assert await target.locator('mark').inner_text() == 'BOUNDARY ANSWER'
                coverage = await page.locator('#history-reader-coverage').inner_text()
                assert 'Showing entries 41–44 of 44. Page 2 of 2.' in coverage
                assert '43 original native items; 3 unsupported or unreadable. 4 turn-only outcomes.' in coverage
                for identifier, status in (('empty-failed', 'failed'), ('empty-interrupted', 'interrupted'),
                                           ('invalid-items-turn', 'failed')):
                    section = page.locator(f'.history-reader-turn-only[data-turn-id="{identifier}"]')
                    assert await section.count() == 1
                    assert status in await section.locator('h3').inner_text()
                    assert await section.locator('.history-reader-item').count() == 0
                assert 'Provider rejected the original retry.' in await page.locator('#history-reader-body').inner_text()
                assert 'This original outcome remains visible' in await page.locator('#history-reader-body').inner_text()
                await page.screenshot(path=str(evidence / f'empty-outcomes-boundary-{width}.png'))
                await unchanged()
                await page.locator('#history-reader-previous').click(); await ready()
                assert 'Showing entries 1–40 of 44. Page 1 of 2.' in await page.locator('#history-reader-coverage').inner_text()
                assert await page.locator('.history-reader-item').count() == 39
                assert await page.locator('.history-reader-item, .history-reader-turn-only').count() == 40
                completed_turn = page.locator('.history-reader-turn-only[data-turn-id="empty-completed"]')
                assert 'completed' in await completed_turn.locator('h3').inner_text()
                assert await completed_turn.locator('.history-reader-item').count() == 0
                await page.locator('#history-reader-next').click(); await ready()
                assert await page.locator('.history-reader-target mark').inner_text() == 'BOUNDARY ANSWER'
                await page.locator('#history-reader-back').click()
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert await page.locator('#recall-query').input_value() == 'boundary answer'
                assert await page.locator('.recall-result').count() == 1
                await unchanged()
                completed.append('exact original answer survives empty completed/failed/interrupted turns at a 40-entry page edge; unreadable-only outcomes retain native IDs and errors without fake items')

                await page.locator('#recall-close').click()
                await page.locator('#browse').click()
                await page.wait_for_function("!$('history-search-submit').disabled")
                await page.locator('#history-search').fill('Original only-empty-outcomes')
                await page.locator('#history-search').press('Enter')
                await page.wait_for_function("!$('history-search-submit').disabled")
                assert await page.locator('#native-list .native-row').count() == 1
                await page.locator('#native-list').get_by_role('button', name='Read original conversation', exact=True).click()
                await ready()
                assert await page.locator('.history-reader-item').count() == 0
                assert await page.locator('.history-reader-turn-only').count() == 3
                assert await page.locator('.history-reader-target').count() == 0
                for turn in empty:
                    section = page.locator(f'.history-reader-turn-only[data-turn-id="{turn["id"]}"]')
                    assert turn['status'] in await section.locator('h3').inner_text()
                assert 'Provider rejected the original retry.' in await page.locator('#history-reader-body').inner_text()
                coverage = await page.locator('#history-reader-coverage').inner_text()
                assert 'Showing entries 1–3 of 3. Page 1 of 1.' in coverage
                assert '0 original native items; 0 unsupported or unreadable. 3 turn-only outcomes.' in coverage
                assert 'contains no readable items' not in await page.locator('#history-reader-body').inner_text()
                await page.screenshot(path=str(evidence / f'only-empty-outcomes-{width}.png'))
                await page.locator('#history-reader-back').click()
                assert await page.locator('#history').evaluate('(node)=>node.open')
                assert await page.locator('#history-search').input_value() == 'Original only-empty-outcomes'
                assert await page.locator('#native-list .native-row').count() == 1
                await unchanged()
                completed.append('an item-free original retains completed/failed/interrupted outcomes and accurate zero-item coverage; Read and Back keep saved work exact')
                (evidence / f'empty-turns-acceptance-{width}.json').write_text(json.dumps({
                    'viewport': width, 'passed': completed, 'javascript_errors': errors,
                    'external_requests': external, 'controlled_model_turns': 0,
                    'native_resume_calls': 0, 'native_calls': calls,
                    'selected_state': selected_state}, ensure_ascii=False, indent=2) + '\n')
                return completed
            except Exception:
                await page.screenshot(path=str(evidence / f'empty-turns-failure-{width}.png'), full_page=True)
                raise
            finally:
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
        results = {}
        for width in (1250, 390):
            results[width] = [] if os.environ.get('DESK_HISTORY_READER_EMPTY_TURNS_ONLY') == '1' else await check(width, playwright, evidence)
            results[width] += await check_empty_turns(width, playwright, evidence)
    print(json.dumps({'original_history_reader_acceptance': 'passed', 'checks': sum(map(len, results.values())),
        'viewports': list(results), 'controlled_model_turns': 0, 'native_resume_calls': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
