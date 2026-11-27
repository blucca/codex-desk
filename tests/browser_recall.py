"""Saved-content recall and exact-target navigation through real loopback HTTP.

DESK_TEST_TEMP=/workspace/temp DESK_TEST_EVIDENCE=/workspace/.private/recall \
  DESK_CHROMIUM=/usr/bin/chromium python tests/browser_recall.py
DESK_USE_INSTALLED=1 uses an installed wheel instead of the source checkout.
DESK_RECALL_CASES=undo runs only the saved-equal edit/undo debounce acceptance.
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
from codex_desk.followups import add_followup, edit_followup, list_followups
from codex_desk.runtime import Runtime, save_profile
from playwright.async_api import async_playwright


async def check(width, playwright, evidence):
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix=f'desk-recall-{width}-') as temporary:
        folder = Path(temporary)
        home = folder / 'native-home'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        profile = save_profile(home, 'retained', 'https://fixture.example/v1',
                               'fixture-model', 'synthetic-only-key')['id']
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        projects = {name: folder / name for name in ('project-a', 'project-b-接口', 'background-project')}
        for path in projects.values():
            path.mkdir()
        safety = '<img src="https://recall-fetch.invalid/payload" onerror="globalThis.__recallXss=1"> safety decision <script>globalThis.__recallXss=2</script>'
        saved_items = [
            {'id': 'a-safety', 'type': 'agentMessage', 'text': safety},
            {'id': 'a-scope', 'type': 'agentMessage', 'text': 'Scope decision alpha. Slow scope first. Straße Ａ café.'},
            {'id': 'a-command', 'type': 'commandExecution', 'command': 'fixture inspect retained work',
             'status': 'completed', 'exitCode': 0,
             'aggregatedOutput': '\n'.join(f'Preserved output line {n}' for n in range(300)) + '\nCOMMAND DECISION kept.'},
            {'id': 'a-mcp', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'inspect', 'status': 'completed',
             'arguments': {'path': 'src/project.py'}, 'result': {'content': [
                 {'type': 'text', 'text': 'MCP DECISION verified locally.'}]}},
            {'id': 'a-collab', 'type': 'collabAgentToolCall', 'tool': 'wait', 'status': 'completed',
             'senderThreadId': 'native-session-a', 'receiverThreadIds': ['fixture-child'],
             'agentsStates': {'fixture-child': {'status': 'completed', 'message': 'COLLAB DECISION retains parent scope.'}}},
            {'id': 'a-lifecycle', 'type': 'subAgentActivity', 'kind': 'completed',
             'agentThreadId': 'fixture-child', 'agentPath': 'fixture-reader', 'model': 'fixture-model'},
        ]

        def thread(identifier, project, items):
            return {'id': 'native-' + identifier, 'cwd': str(projects[project]), 'name': identifier,
                    'modelProvider': 'fixture-provider', 'turns': [{'id': 'turn-' + identifier,
                    'status': 'completed', 'items': items}]}

        threads = {
            'session-a': thread('session-a', 'project-a', saved_items),
            'session-b': thread('session-b', 'project-b-接口', [
                {'id': 'b-scope', 'type': 'agentMessage', 'text': 'Scope decision beta. Cancel scope existing work.'}]),
            'session-archived': thread('session-archived', 'project-a', [
                {'id': 'archived-scope', 'type': 'agentMessage', 'text': 'Scope decision archived. ARCHIVED CHOICE work.'}]),
            'session-missing': thread('session-missing', 'project-b-接口', [
                {'id': 'missing-item', 'type': 'agentMessage', 'text': 'MISSING TARGET cached decision.'}]),
            'session-slow': thread('session-slow', 'project-a', [
                {'id': 'slow-item', 'type': 'agentMessage', 'text': 'OPEN DELAY preserved choice.'}]),
            'session-bulk': thread('session-bulk', 'project-b-接口', [
                {'id': f'bulk-{n:02}', 'type': 'agentMessage', 'text': f'BULK DECISION item {n}.'} for n in range(34)]),
        }
        native_calls, http_calls, recalls, errors, external, completed = [], [], [], [], [], []
        holds = {}

        def hold(kind, identifier):
            entered, release = threading.Event(), threading.Event()
            holds[(kind, identifier)] = (entered, release)
            return entered, release

        def wait_hold(kind, identifier):
            if (kind, identifier) in holds:
                entered, release = holds[(kind, identifier)]
                entered.set()
                assert release.wait(25), f'Held fixture was not released: {kind} {identifier}'

        class ControlledRuntime(Runtime):
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id, self.home = store, identifier, native_home
                self.process = SimpleNamespace(poll=lambda: None)
                self.pending, self.approvals = {}, {}
                self.lock, self.write_lock = threading.Lock(), threading.Lock()
                self.name_lock = threading.RLock()
                self.lifecycle_lock, self.turn_lock = threading.Lock(), threading.Lock()
                self.closing, self.persisted = False, False
                self.counter = 0

            def request(self, method, params, timeout=30):
                native_calls.append({'method': method, 'session': self.id, 'params': params})
                if method == 'thread/list':
                    return {'data': [], 'nextCursor': None}
                assert method == 'thread/resume', 'Recall must not start a native task or new thread: ' + method
                wait_hold('open', self.id)
                return {'thread': copy.deepcopy(threads[self.id]), 'model': 'fixture-model',
                        'modelProvider': 'fixture-provider'}

            def close(self):
                self.closing = True
                self.process.poll = lambda: 0

        def checkpoint(name):
            completed.append(name)
            print(json.dumps({'viewport': width, 'passed': name}), flush=True)

        def recall_requests():
            return [c for c in http_calls if c['path'] == '/api/recall']

        def open_requests():
            return [c for c in http_calls if c['path'] == '/api/open']

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            for identifier, source in threads.items():
                desk.store.create(source['cwd'], profile, identifier=identifier, name=source['name'])
                desk.store.update(identifier, thread_id=source['id'], thread_saved=1, status='completed',
                                  model='fixture-model', provider='fixture-provider', name_pending=0)
                desk.store.recall_snapshot(identifier, source)
            desk.store.archive('session-archived', True)
            save_draft(desk.store, 'session-a', 'DRAFT CHOICE inspect the retained decision.', 'plan', 0)
            save_draft(desk.store, 'session-b', 'B retained editor preparation.', 'native', 0)
            followup = add_followup(desk.store, 'session-a', 'PREPARED CHOICE verify the existing decision.', 'plan')
            add_followup(desk.store, 'session-a', 'Second instruction remains paused.', 'native')
            bindings = {identifier: {k: desk.store.get(identifier)[k] for k in ('cwd', 'profile', 'thread_id')}
                        for identifier in threads}
            queues = list_followups(desk.store, 'session-a')
            threads['session-missing']['turns'] = []
            native_before = json.dumps(threads, sort_keys=True)
            actual_recall = desk.recall

            def controlled_recall(q, cwd=None, include_archived=False, limit=30, offset=0):
                recalls.append({'q': q, 'cwd': cwd, 'archived': include_archived, 'limit': limit})
                wait_hold('query', q)
                if q == 'fixture-error':
                    raise RuntimeError('Fixture saved-content store unavailable')
                return actual_recall(q, cwd, include_archived, limit, offset)

            desk.recall = controlled_recall
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
                http_calls.append({'path': parsed.path, 'method': request.method, 'query': parse_qs(parsed.query)})
                if parsed.hostname != '127.0.0.1':
                    external.append(request.url)

            page.on('request', requested)

            async def dialog():
                if not await page.locator('#recall').evaluate('(node)=>node.open'):
                    await page.locator('#search-saved-content').click()

            async def search(text, project=None, archived=None):
                await dialog()
                if project is not None:
                    await page.locator('#recall-project').select_option(project)
                if archived is not None:
                    await page.locator('#recall-archived').set_checked(archived)
                await page.locator('#recall-query').fill(text)
                await page.locator('#recall-query').press('Enter')
                await page.wait_for_function("!$('recall-search').disabled")

            async def reveal(selector):
                row = page.locator(selector)
                expected = {'kind': await row.get_attribute('data-kind'),
                            'item': await row.get_attribute('data-item'),
                            'followup': await row.get_attribute('data-followup')}
                await page.locator(selector + ' .recall-open').click()
                await page.wait_for_function("""expected=>{
                    const node=document.querySelector('.recall-target');
                    return !$('recall').open && node && (expected.kind==='activity'
                        ? node.dataset.itemId===expected.item : expected.kind==='draft'
                        ? node.id==='prompt' : node.closest('.followup-entry')?.dataset.followup===expected.followup);
                }""", arg=expected)

            async def no_horizontal_overflow():
                assert await page.evaluate("document.documentElement.scrollWidth<=innerWidth && (!$('recall').open || $('recall').scrollWidth<=$('recall').clientWidth)")

            async def saved_equal_undo():
                saved_before = load_draft(desk.store, 'session-a')
                frontend_before = await page.evaluate("({revision:draftRevisions.get(selected),text:drafts.get(selected),mode:draftModes.get(selected),saved:draftSaved.get(selected)})")
                calls_before = len([c for c in http_calls if c['path'] == '/api/draft'])
                await page.locator('#prompt').fill('A short-lived edit that is deliberately undone.')
                assert await page.locator('#draft-status').inner_text() == 'Unsaved draft…'
                await page.locator('#prompt').fill(saved_before['text'])
                await page.wait_for_function("!draftTimers.has(selected) && !draftSaves.has(selected) && $('draft-status').textContent==='Draft saved locally. Nothing has been sent.'")
                assert await page.locator('#prompt').input_value() == saved_before['text']
                assert await page.locator('#turn-mode').input_value() == saved_before['mode']
                assert load_draft(desk.store, 'session-a') == saved_before
                assert await page.evaluate("({revision:draftRevisions.get(selected),text:drafts.get(selected),mode:draftModes.get(selected),saved:draftSaved.get(selected)})") == frontend_before
                assert len([c for c in http_calls if c['path'] == '/api/draft']) == calls_before
                checkpoint('edit/undo before debounce reports saved with unchanged payload/revision and no draft request')

            def response_for(response, q):
                parsed = urlsplit(response.url)
                return parsed.path == '/api/recall' and parse_qs(parsed.query).get('q') == [q]

            try:
                await page.goto(url)
                await page.wait_for_function('state.sessions.length===6')
                await page.wait_for_function('document.querySelector("#home-list").getAttribute("aria-busy")==="false"')
                assert all(c['method']=='thread/list' for c in native_calls)
                native_calls.clear()  # Home discovery is separate from cold SQLite recall.
                assert not native_calls and not {k:v for k,v in desk.runtimes.items() if k!='native-catalog'}
                if os.environ.get('DESK_RECALL_CASES') == 'undo':
                    await page.locator('.session-row[data-session="session-a"] .session').click()
                    await page.wait_for_function("selected==='session-a' && !opening && !$('task').hidden")
                    await saved_equal_undo()
                    assert not errors and not external
                    assert all(c['method'] == 'thread/resume' for c in native_calls)
                    assert not [c for c in http_calls if c['path'] in ('/api/turn', '/api/followups/send', '/api/handoff/start')]
                    assert list_followups(desk.store, 'session-a') == queues
                    assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                    (evidence / f'undo-acceptance-{width}.json').write_text(json.dumps({
                        'viewport': width, 'passed': completed, 'javascript_errors': errors,
                        'external_requests': external, 'native_calls': native_calls, 'http_calls': http_calls,
                        'saved_draft': load_draft(desk.store, 'session-a'), 'controlled_model_turns': 0,
                        'draft_request_count': len([c for c in http_calls if c['path'] == '/api/draft']),
                    }, ensure_ascii=False, indent=2) + '\n')
                    return completed
                await dialog()
                assert await page.locator('#recall').get_attribute('aria-labelledby') == 'recall-title'
                assert await page.locator('#recall-query').evaluate('(node)=>node===document.activeElement')
                assert 'Other native Codex conversations are not scanned' in await page.locator('#recall-scope-info').inner_text()
                await search('SAFETY DECISION')
                assert await page.locator('.recall-result').count() == 1
                assert await page.locator('.recall-snippet mark').inner_text() == 'safety decision'
                assert '<script>globalThis.__recallXss=2</script>' in await page.locator('.recall-snippet').inner_text()
                assert await page.locator('#recall-results img, #recall-results script').count() == 0
                assert not await page.evaluate('globalThis.__recallXss')
                assert not native_calls and not {k:v for k,v in desk.runtimes.items() if k!='native-catalog'} and not open_requests()
                assert await page.evaluate('selected===null')
                await no_horizontal_overflow()
                await page.screenshot(path=str(evidence / f'recall-safety-{width}.png'))
                await search('strasse a CAFÉ')
                assert await page.locator('.recall-snippet mark').inner_text() == 'Straße Ａ café'
                checkpoint('cold cached literal/Unicode search and safe highlighted snippets')

                await search('scope decision', str(projects['project-a']), False)
                assert await page.locator('.recall-result').count() == 1
                assert recalls[-1] == {'q': 'scope decision', 'cwd': str(projects['project-a']), 'archived': False, 'limit': 30}
                await search('scope decision', str(projects['project-a']), True)
                assert await page.locator('.recall-result').count() == 2
                assert await page.locator('.recall-result[data-session="session-archived"]').count() == 1
                assert 'cached activity items' in await page.locator('#recall-coverage').inner_text()
                assert not native_calls
                checkpoint('exact project and archive scope with truthful coverage')

                entered, release = hold('query', 'slow scope')
                await page.locator('#recall-query').fill('slow scope')
                await page.locator('#recall-query').press('Enter')
                assert await asyncio.to_thread(entered.wait, 5)
                assert 'Searching saved content' in await page.locator('#recall-summary').inner_text()
                await search('scope decision', str(projects['project-b-接口']), False)
                async with page.expect_response(lambda r: response_for(r, 'slow scope')) as response:
                    release.set()
                await (await response.value).body()
                await page.wait_for_timeout(100)
                assert await page.locator('.recall-result').count() == 1
                assert 'Scope decision beta' in await page.locator('#recall-results').inner_text()
                checkpoint('delayed old query cannot replace a newer query/project result')

                entered, release = hold('query', 'cancel scope')
                await page.locator('#recall-query').fill('cancel scope')
                await page.locator('#recall-query').press('Enter')
                assert await asyncio.to_thread(entered.wait, 5)
                await page.locator('#recall-query').press('Escape')
                # A search input may clear on Escape before the dialog cancels.
                if await page.locator('#recall').evaluate('(node)=>node.open'):
                    await page.locator('#recall-close').click()
                await search('safety decision', '', False)
                async with page.expect_response(lambda r: response_for(r, 'cancel scope')) as response:
                    release.set()
                await (await response.value).body()
                await page.wait_for_timeout(100)
                assert 'safety decision' in await page.locator('#recall-results').inner_text()
                assert 'Cancel scope' not in await page.locator('#recall-results').inner_text()
                checkpoint('canceled dialog rejects its late search response')

                await reveal('.recall-result[data-item="a-safety"]')
                assert await page.evaluate("selected==='session-a' && nativeThreadId==='native-session-a'")
                assert await page.locator('.recall-target').get_attribute('data-item-id') == 'a-safety'
                assert len(open_requests()) == 1 and len(native_calls) == 1
                assert await page.locator('#prompt').input_value() == 'DRAFT CHOICE inspect the retained decision.'
                assert await page.locator('#turn-mode').input_value() == 'plan'
                assert await page.locator('#preview').evaluate('(node)=>!node.open')
                # Retained result actions remain usable after closing/reopening.
                await dialog()
                assert await page.locator('#recall-query').input_value() == 'safety decision'
                count = len(recall_requests())
                await reveal('.recall-result[data-item="a-safety"]')
                assert len(recall_requests()) == count and len(open_requests()) == 1
                checkpoint('saved native binding opens once; retained current hit navigates without reopen')

                before = len(open_requests())
                for text, identifier, disclosure in (
                    ('command decision', 'a-command', '.activity-tool'),
                    ('mcp decision', 'a-mcp', '.activity-tool'),
                    ('collab decision', 'a-collab', None),
                ):
                    await search(text)
                    await reveal(f'.recall-result[data-item="{identifier}"]')
                    assert await page.locator('.recall-target').get_attribute('data-item-id') == identifier
                    if disclosure:
                        assert await page.locator(f'[data-item-id="{identifier}"] {disclosure}').evaluate('(node)=>node.open')
                    else:
                        assert await page.locator('.activity-collaboration').evaluate('(node)=>node.open')
                    if identifier == 'a-command':
                        assert await page.locator('[data-item-id="a-command"] pre').evaluate('(node)=>node.scrollTop>0')
                assert len(open_requests()) == before
                assert await page.locator('.recall-target').evaluate('(node)=>node===document.activeElement')
                await no_horizontal_overflow()
                await page.screenshot(path=str(evidence / f'recall-collaboration-{width}.png'))
                checkpoint('exact command/MCP/collaboration targets expand, focus and scroll without reopen')

                await search('draft choice')
                await reveal('.recall-result[data-kind="draft"]')
                assert await page.locator('#prompt').evaluate('(node)=>node===document.activeElement && node.classList.contains("recall-target")')
                assert await page.locator('#prompt').input_value() == 'DRAFT CHOICE inspect the retained decision.'
                await search('prepared choice')
                await reveal('.recall-result[data-followup="' + followup['id'] + '"]')
                assert await page.locator('#followups').evaluate('(node)=>node.open')
                assert await page.locator('.recall-target').inner_text() == followup['text']
                assert list_followups(desk.store, 'session-a') == queues
                assert len(open_requests()) == before
                checkpoint('draft and exact prepared follow-up focus preserve preparation and never send')
                await saved_equal_undo()

                await search('draft choice')
                await page.evaluate("$('prompt').value='A newer local draft without the searched phrase.'; $('prompt').dispatchEvent(new Event('input'))")
                await page.locator('.recall-result[data-kind="draft"] .recall-open').click()
                await page.wait_for_function("$('recall-results').textContent.includes('saved phrase is no longer')")
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert await page.locator('#prompt').input_value() == 'A newer local draft without the searched phrase.'
                await page.evaluate("$('prompt').value='DRAFT CHOICE inspect the retained decision.'; $('prompt').dispatchEvent(new Event('input'))")
                assert await page.evaluate('persistDraft(selected)')
                assert load_draft(desk.store, 'session-a')['text'] == 'DRAFT CHOICE inspect the retained decision.'

                await search('prepared choice')
                edit_followup(desk.store, 'session-a', followup['id'], 'Revised preparation without that phrase.', 'plan', 1)
                await page.locator('.recall-result[data-kind="followup"] .recall-open').click()
                await page.wait_for_function("$('recall-results').textContent.includes('saved phrase is no longer')")
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert list_followups(desk.store, 'session-a')[0]['text'] == 'Revised preparation without that phrase.'
                edit_followup(desk.store, 'session-a', followup['id'], followup['text'], 'plan', 2)
                queues = list_followups(desk.store, 'session-a')

                await search('collab decision')
                await page.evaluate("renderItem({...items.get('a-collab'),agentsStates:{'fixture-child':{status:'completed',message:'Revised native evidence without that phrase.'}}},'turn-session-a')")
                await page.locator('.recall-result[data-item="a-collab"] .recall-open').click()
                await page.wait_for_function("$('recall-results').textContent.includes('not in the freshly loaded native activity')")
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                await page.evaluate('(item)=>renderItem(item,"turn-session-a")', saved_items[4])
                assert len(open_requests()) == before
                checkpoint('changed draft/follow-up/same-ID activity keeps results without overwriting current text')

                await page.locator('#recall-close').click()
                await page.locator('#prompt').fill('DRAFT CHOICE newer local preparation stays intact.')
                await page.locator('#turn-mode').select_option('native')
                await page.wait_for_function("$('draft-status').textContent==='Draft saved locally. Nothing has been sent.'")
                await page.locator('#session-filter').fill('retained title scope')
                await page.locator('#show-archived').set_checked(True)
                await page.evaluate("$('history-search').value='native-title-scope'")
                await search('prepared choice', str(projects['project-a']), True)
                text_before = await page.locator('#recall-results').inner_text()
                desk.store.create(str(projects['background-project']), profile, identifier='background-session', name='Background saved work')
                await page.evaluate('refresh()')
                assert await page.locator('#recall-project').input_value() == str(projects['project-a'])
                assert await page.locator('#recall-query').input_value() == 'prepared choice'
                assert await page.locator('#recall-archived').is_checked()
                assert await page.locator('#recall-results').inner_text() == text_before
                assert await page.locator('#session-filter').input_value() == 'retained title scope'
                assert await page.locator('#show-archived').is_checked()
                assert await page.locator('#history-search').input_value() == 'native-title-scope'
                assert await page.locator('#prompt').input_value() == 'DRAFT CHOICE newer local preparation stays intact.'
                assert await page.locator('#turn-mode').input_value() == 'native'
                checkpoint('background project state refresh preserves search/draft/title/history scopes')

                await search('archived choice', '', True)
                await reveal('.recall-result[data-session="session-archived"]')
                assert not desk.store.get('session-archived')['archived']
                assert await page.evaluate("selected==='session-archived' && nativeThreadId==='native-session-archived'")
                assert load_draft(desk.store, 'session-a')['text'] == 'DRAFT CHOICE newer local preparation stays intact.'
                assert any(c['path'] == '/api/archive' and c['method'] == 'POST' for c in http_calls)
                checkpoint('archived result restores and reuses its original binding')

                await search('missing target', '', False)
                await page.locator('.recall-result[data-item="missing-item"] .recall-open').click()
                await page.wait_for_function("$('recall-results').textContent.includes('not in the freshly loaded native activity')")
                assert await page.locator('#recall').evaluate('(node)=>node.open')
                assert await page.locator('.recall-result[data-item="missing-item"]').count() == 1
                assert await page.locator('.recall-result-status').is_visible()
                assert await page.locator('#preview').evaluate('(node)=>!node.open')
                assert await page.evaluate("selected==='session-missing' && nativeThreadId==='native-session-missing'")
                checkpoint('missing fresh-native target keeps its cached result with an explicit explanation')

                entered, release = hold('open', 'session-slow')
                await search('open delay')
                await page.locator('.recall-open').click()
                assert await asyncio.to_thread(entered.wait, 5)
                assert await page.locator('.recall-open').is_disabled()
                await search('safety decision')
                await page.locator('.recall-result[data-item="a-safety"] .recall-open').click()
                release.set()
                await page.wait_for_function("!$('recall').open && selected==='session-a' && document.querySelector('.recall-target')?.dataset.itemId==='a-safety'")
                await page.wait_for_timeout(150)
                assert await page.evaluate("selected==='session-a' && nativeThreadId==='native-session-a'")
                assert await page.locator('.recall-target').get_attribute('data-item-id') == 'a-safety'
                checkpoint('overlapping query/open generations reject stale target navigation')

                await search('bulk decision', '', False)
                assert await page.locator('.recall-result').count() == 30
                assert 'Showing 30 of 34' in await page.locator('#recall-summary').inner_text()
                assert await page.locator('#recall-next').is_visible()
                first_page=await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")
                await page.locator('#recall-next').click()
                await page.wait_for_function("!$('recall-search').disabled && $('recall-summary').textContent.includes('Items 31–34')")
                assert await page.locator('.recall-result').count()==4
                second_page=await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")
                assert not set(first_page).intersection(second_page)
                assert await page.locator('#recall-next').is_disabled()
                await page.locator('#recall-previous').click()
                await page.wait_for_function("!$('recall-search').disabled && $('recall-summary').textContent.includes('Items 1–30')")
                assert await page.locator('.recall-result').evaluate_all("ns=>ns.map(n=>JSON.stringify(n.dataset))")==first_page
                checkpoint('all later matching items are reachable through stable nonoverlapping result pages without task execution')
                await search('no-match-anywhere')
                assert await page.locator('.recall-result').count() == 0
                assert 'Native history is not indexed yet' in await page.locator('#recall-summary').inner_text()
                assert await page.locator('#recall-index').count() == 1
                assert await page.locator('#recall-index').evaluate("n=>n.parentElement.id==='recall-actions'")
                await search('fixture-error')
                assert 'Fixture saved-content store unavailable' in await page.locator('#recall-error').inner_text()
                assert await page.locator('#recall-search').is_enabled()
                await search('safety decision')
                assert await page.locator('#recall-error').is_hidden()
                await no_horizontal_overflow()
                checkpoint('bounded total/truncation, empty results and retryable search errors')

                assert not errors, errors
                assert not external, external
                assert not [c for c in http_calls if c['path'] in ('/api/turn', '/api/handoff', '/api/handoff/start', '/api/followups/send', '/api/sessions', '/api/import')]
                assert all(c['method'] == 'thread/resume' for c in native_calls)
                assert list_followups(desk.store, 'session-a') == queues
                assert json.dumps(threads, sort_keys=True) == native_before
                assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                for identifier, binding in bindings.items():
                    assert {k: desk.store.get(identifier)[k] for k in binding} == binding
                checkpoint('zero JS errors/external requests/model turns; bindings/config/queues preserved')
                result = {'viewport': width, 'passed': completed, 'javascript_errors': errors,
                          'external_requests': external, 'native_calls': native_calls, 'recall_requests': recalls,
                          'http_calls': http_calls, 'controlled_model_turns': 0, 'bindings': bindings}
                (evidence / f'acceptance-{width}.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
                return completed
            except Exception:
                diagnostic = {'viewport': width, 'passed': completed, 'javascript_errors': errors,
                              'native_calls': native_calls, 'recalls': recalls, 'recent_http_calls': http_calls[-35:]}
                try:
                    diagnostic['page'] = await page.evaluate('({selected,opening,query:$("recall-query").value,summary:$("recall-summary").textContent,results:$("recall-results").textContent})')
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
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                desk.close()
                desk.store.db.close()
                for path in evidence.iterdir():
                    if path.is_file():
                        path.chmod(0o600)


async def main():
    evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(Path(os.environ['DESK_TEST_TEMP']) / 'recall-evidence')))
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    evidence.chmod(0o700)
    async with async_playwright() as playwright:
        results = {width: await check(width, playwright, evidence) for width in (1250, 390)}
    print(json.dumps({'recall_acceptance': 'passed', 'checks': sum(map(len, results.values())),
                      'viewports': list(results), 'controlled_model_turns': 0}), flush=True)


if __name__ == '__main__':
    asyncio.run(main())
