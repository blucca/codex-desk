"""Replay CLI 0.171 collaboration items through the shipped loopback HTTP UI.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_collaboration.py
DESK_USE_INSTALLED=1 tests an installed wheel. No native process is launched.
"""
import asyncio
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from playwright.async_api import async_playwright


def lifecycle(identifier, kind, path, thread, **extra):
    return {'id': identifier, 'type': 'subAgentActivity', 'kind': kind,
            'agentPath': path, 'agentThreadId': thread, **extra}


def call(identifier, tool, status, receivers, states=None, **extra):
    return {'id': identifier, 'type': 'collabAgentToolCall', 'tool': tool,
            'status': status, 'senderThreadId': 'fixture-thread',
            'receiverThreadIds': receivers, 'agentsStates': states or {}, **extra}


async def check():
    root = Path(os.environ.get('DESK_TEST_TEMP', Path(__file__).resolve().parents[3] / 'temp'))
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-collaboration-') as temporary:
        folder = Path(temporary)
        project, home = folder / 'project', folder / 'native-home'
        project.mkdir()
        home.mkdir()
        (home / 'config.toml').write_text('model = "fixture"\n')
        prompt = 'Set power mode to low and open the typing drill on the A Y Z ASCII character set.'
        public_task = 'Open ascii.printable.short.2.yz.\n<img src="https://collab-fetch.invalid/task" onerror="globalThis.__collabXss=1">'
        public_result = 'Power mode is low.\n<script>globalThis.__collabXss=2</script>'
        first = {'id': 't1', 'status': 'completed', 'error': None, 'items': [
            {'id': 'u1', 'type': 'userMessage', 'content': [{'type': 'text', 'text': prompt}]},
            {'id': 'a1', 'type': 'agentMessage', 'text': "Got it, I'll take care of it."},
            lifecycle('s-power', 'started', '/root/power', 'power-thread', model='fixture', reasoningEffort='low'),
            call('legacy-spawn', 'spawnAgent', 'completed', ['power-thread'],
                 {'power-thread': {'status': 'completed', 'message': public_result},
                  '_meta': {'status': 'errored', 'message': 'private-state-extension'}},
                 prompt=public_task, model='fixture', reasoningEffort='low', _meta={'secret': 'private-collab-meta'},
                 extraPrivate={'credential': 'private-extension-value'}),
            lifecycle('s-drill', 'started', '/root/drill', 'drill-thread', model=None, reasoningEffort=None),
            lifecycle('s-interact', 'interacted', '/root/drill', 'drill-thread'),
            {'id': 'c1', 'type': 'commandExecution', 'command': 'echo retained command',
             'status': 'completed', 'aggregatedOutput': 'Ordinary command evidence', 'exitCode': 0},
            {'id': 'a1-result', 'type': 'agentMessage', 'text': '## Result\n\nThe timed drill is opening with ascii.printable.short.2.yz.'},
            call('legacy-wait', 'wait', 'failed', ['power-thread', 'drill-thread'], {
                'power-thread': {'status': 'completed', 'message': public_result},
                'drill-thread': {'status': 'errored', 'message': 'Public drill failure: window did not open.'}}),
            call('legacy-interrupt', 'interruptAgent', 'interrupted', ['drill-thread'],
                 {'drill-thread': {'status': 'interrupted', 'message': 'Public interruption retained.'}}),
            lifecycle('s-done-power', 'completed', '/root/power', 'power-thread'),
            lifecycle('s-done-drill', 'completed', '/root/drill', 'drill-thread'),
        ]}
        second = {'id': 't2', 'status': 'inProgress', 'error': None, 'items': [
            {'id': 'u2', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Retry the drill on the same project.'}]},
            {'id': 'a2', 'type': 'agentMessage', 'text': 'Checking the saved preset.'},
            lifecycle('s-second', 'started', '/root/drill-2', 'drill-2-thread'),
            call('legacy-live', 'sendInput', 'inProgress', ['drill-2-thread'],
                 {'drill-2-thread': {'status': 'running', 'message': 'Public live progress.'}},
                 prompt='Retry the saved drill; retain the selected project.'),
        ]}
        thread = {'id': 'fixture-thread', 'cwd': str(project), 'name': 'Collaboration replay',
                  'modelProvider': 'fixture', 'turns': [first, second]}
        native_calls, catalog_reads = [], []

        class ControlledRuntime:
            def __init__(self, store, identifier, binary, native_home):
                assert binary == 'never-executed'
                self.store, self.id = store, identifier
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {}

            def attach(self):
                native_calls.append({'method': 'thread/resume', 'threadId': thread['id']})
                self.thread_result = {'thread': thread, 'model': 'fixture', 'modelProvider': 'fixture'}
                self.store.update(self.id, status='ready', thread_id=thread['id'], model='fixture', provider='fixture')
                return self.thread_result

            def request(self, method, params):
                if method == 'thread/list':
                    assert params == {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at'}, params
                    catalog_reads.append({'method': method, **params})
                    return {'data': [], 'nextCursor': None}
                assert method == 'thread/read', method
                assert params == {'threadId': thread['id'], 'includeTurns': True}, params
                native_calls.append({'method': method, **params})
                return {'thread': thread}

            def close(self):
                pass

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk = desk_server.Desk('never-executed', home, folder / 'state')
            identifier = desk.store.create(str(project), 'default', name='Collaboration replay')
            desk.store.update(identifier, status='saved', thread_id=thread['id'])

            def emit(method, turn_id, **params):
                desk.store.event(identifier, {'method': method, 'params': {
                    'threadId': thread['id'], 'turnId': turn_id, **params}})

            def item_event(method, turn_id, item):
                timestamp = 'startedAtMs' if method == 'item/started' else 'completedAtMs'
                emit(method, turn_id, item=deepcopy(item), **{timestamp: 1795620000000})

            # Snapshot plus replay uses identical IDs and native turn IDs. V2
            # lifecycle rows have no invented status; legacy calls do have one.
            for turn in thread['turns']:
                emit('turn/started', turn['id'], turn={'id': turn['id'], 'status': 'inProgress', 'items': [], 'error': None})
                for item in turn['items']:
                    if item['type'] == 'agentMessage':
                        item_event('item/started', turn['id'], {**item, 'text': ''})
                        emit('item/agentMessage/delta', turn['id'], itemId=item['id'], delta='Transient replay text')
                        item_event('item/completed', turn['id'], item)
                    elif item['type'] == 'collabAgentToolCall':
                        item_event('item/started', turn['id'], {**item, 'status': 'inProgress'})
                        if item['status'] != 'inProgress':
                            item_event('item/completed', turn['id'], item)
                    else:
                        item_event('item/started', turn['id'], item)
                        item_event('item/completed', turn['id'], item)
                if turn['status'] == 'completed':
                    emit('turn/completed', turn['id'], turn=deepcopy(turn))
            replay_seq = desk.store.events(identifier)[-1]['seq']
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            url = f'http://127.0.0.1:{server.server_port}'
            try:
                async with async_playwright() as p:
                    browser = await p.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),
                        headless=True, args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = await browser.new_page(viewport={'width': 390, 'height': 844})
                        errors, requests = [], []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        page.on('request', lambda request: requests.append(request.url))
                        await page.goto(url)
                        await page.locator('#sessions .session').click()
                        await page.wait_for_function('!opening && after >= ' + str(replay_seq))

                        def row(item_id):
                            return page.locator('[data-item-id="' + item_id + '"]')

                        def group(turn_id):
                            return page.locator('details.activity-collaboration[data-collaboration-turn="' + turn_id + '"]')

                        async def sync():
                            seq = desk.store.events(identifier)[-1]['seq']
                            await page.wait_for_function('after >= ' + str(seq))

                        reopen_views = []

                        async def reopen_reading(width):
                            # Capture the real click entry after Playwright's
                            # ordinary session-button reveal, before open leaves.
                            await page.evaluate('''() => {
                                const capture = event => {
                                    if (!event.target.closest('#sessions .session')) return;
                                    window.collaborationReopenBefore = {generation, view:DeskSessionReading.capture()};
                                    window.removeEventListener('click', capture, true);
                                };
                                window.addEventListener('click', capture, true);
                            }''')
                            await page.locator('#sessions .session').click()
                            await page.wait_for_function('''s => selected===s.id&&!opening&&
                                generation===collaborationReopenBefore.generation+1&&nativeThreadId==="fixture-thread"&&
                                sessionReadingKey===JSON.stringify([s.id,"fixture-thread"])&&
                                !sessionReadingPending&&!sessionReadingRestoring&&after>=s.seq''',
                                arg={'id': identifier, 'seq': desk.store.events(identifier)[-1]['seq']})
                            before = await page.evaluate('collaborationReopenBefore.view')
                            restored = await page.evaluate('()=>DeskSessionReading.capture()')
                            assert before and restored == before, (before, restored)
                            reopen_views.append({'width': width, 'before': before, 'after': restored})

                        async def assert_groups():
                            assert await page.locator('#activity > details.activity-collaboration').count() == 2
                            for turn in thread['turns']:
                                expected = [item['id'] for item in turn['items'] if item['type'] in ('collabAgentToolCall', 'subAgentActivity')]
                                actual = await group(turn['id']).locator('.activity-collaboration-items > .item').evaluate_all('(rows) => rows.map(row => row.dataset.itemId)')
                                assert actual == expected, (actual, expected)
                            ids = await page.locator('#activity .item').evaluate_all('(rows) => rows.map(row => row.dataset.itemId)')
                            assert len(ids) == len(set(ids))
                            assert await page.locator('.activity-collaboration details,.activity-collaboration button,.activity-collaboration input,.activity-collaboration textarea,.activity-collaboration select,.activity-collaboration audio').count() == 0

                        await assert_groups()
                        assert await page.locator('details.activity-collaboration[open]').count() == 0
                        assert not await row('legacy-live').is_visible()
                        assert not await row('s-power').is_visible()
                        assert await row('u1').inner_text() == prompt
                        assert await row('a1').is_visible() and await row('a1-result').is_visible()
                        assert await row('u2').is_visible() and await row('a2').is_visible()
                        assert 'Result' == await row('a1-result').locator('h2').inner_text()
                        assert 'Transient replay text' not in await page.locator('#activity').text_content()
                        assert await page.locator('#activity > .item').evaluate_all('(rows) => rows.map(row => row.dataset.itemId)') == ['u1', 'a1', 'c1', 'a1-result', 'u2', 'a2']
                        timeline = await page.locator('#activity').evaluate('(activity) => [...activity.children].map(node => node.dataset.collaborationTurn ? "group:" + node.dataset.collaborationTurn : node.dataset.itemId)')
                        assert timeline == ['u1', 'a1', 'group:t1', 'c1', 'a1-result', 'u2', 'a2', 'group:t2'], timeline
                        assert await row('c1').locator('details').get_attribute('open') is None
                        assert 'Started · /root/power' == await row('s-power').locator('.activity-collaboration-label').text_content()
                        assert 'Interacted with · /root/drill' == await row('s-interact').locator('.activity-collaboration-label').text_content()
                        assert 'Failed' in await row('legacy-wait').locator('.activity-collaboration-label').text_content()
                        assert 'Interrupted' in await row('legacy-interrupt').locator('.activity-collaboration-label').text_content()
                        assert 'In progress' in await row('legacy-live').locator('.activity-collaboration-label').text_content()
                        assert 'In progress' not in await row('s-second').locator('.activity-collaboration-label').text_content()
                        assert '2 agents' in await group('t1').locator(':scope > summary').text_content()
                        assert 'agent error' not in await row('legacy-spawn').locator('.activity-collaboration-label').text_content()
                        if os.environ.get('DESK_COLLABORATION_RECEIPT'):
                            destination = Path(os.environ['DESK_COLLABORATION_RECEIPT'])
                            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                            screenshot = destination / 'collaboration-collapsed-390.png'
                            await page.screenshot(path=str(screenshot), full_page=True)
                            screenshot.chmod(0o600)

                        # The one outer keyboard disclosure immediately shows all
                        # public evidence, including failures and literal HTML.
                        await group('t1').locator(':scope > summary').focus()
                        await page.keyboard.press('Enter')
                        first_handle = await group('t1').element_handle()
                        assert await row('legacy-spawn').locator('pre').is_visible()
                        assert public_task in await row('legacy-spawn').inner_text()
                        assert public_result in await row('legacy-spawn').inner_text()
                        assert 'Public drill failure' in await row('legacy-wait').inner_text()
                        assert await page.locator('#activity script,#activity img,#activity iframe,#activity svg,#activity style,#activity object,#activity embed').count() == 0
                        assert not await page.evaluate('globalThis.__collabXss')
                        assert 'private-collab-meta' not in await page.locator('#activity').text_content()
                        assert 'private-extension-value' not in await page.locator('#activity').text_content()
                        assert 'private-state-extension' not in await page.locator('#activity').text_content()

                        # A real state refresh and authoritative item replacement
                        # do not replace the disclosure or change its preference.
                        await page.evaluate('() => refresh()')
                        assert await group('t1').get_attribute('open') is not None
                        replacement = {**first['items'][8], 'agentsStates': {
                            'drill-thread': {'status': 'errored', 'message': 'Updated public failure: retained native output.'}}}
                        first['items'][8] = replacement
                        item_event('item/completed', 't1', replacement)
                        await sync()
                        assert await group('t1').get_attribute('open') is not None
                        assert 'Updated public failure' in await row('legacy-wait').inner_text()
                        assert 'window did not open' not in await row('legacy-wait').text_content()
                        assert await first_handle.evaluate('(node) => node.isConnected')
                        assert await group('t2').get_attribute('open') is None

                        await group('t1').locator(':scope > summary').focus()
                        await page.keyboard.press('Enter')
                        item_event('item/completed', 't1', first['items'][2])
                        emit('item/agentMessage/delta', 't2', itemId='a2', delta='\nPublic main-reply progress.')
                        await sync()
                        assert await group('t1').get_attribute('open') is None
                        assert await group('t2').get_attribute('open') is None
                        assert 'Public main-reply progress.' in await row('a2').inner_text()
                        await group('t2').locator(':scope > summary').click()
                        second_handle = await group('t2').element_handle()
                        # Native app-server also emits child-thread turns on this
                        # connection. They are not parent conversation messages.
                        child_turn = {'id': 'child-turn', 'status': 'inProgress', 'items': [], 'error': None}
                        child_message = {'id': 'foreign-child-message', 'type': 'agentMessage',
                                         'text': 'Foreign child conversation must not enter the parent timeline.'}
                        emit('turn/started', 'child-turn', threadId='drill-2-thread', turn=child_turn)
                        emit('item/started', 'child-turn', threadId='drill-2-thread',
                             item={**child_message, 'text': ''}, startedAtMs=1795620000000)
                        emit('item/agentMessage/delta', 'child-turn', threadId='drill-2-thread',
                             itemId=child_message['id'], delta=child_message['text'])
                        emit('item/completed', 'child-turn', threadId='drill-2-thread',
                             item=child_message, completedAtMs=1795620000001)
                        emit('turn/completed', 'child-turn', threadId='drill-2-thread',
                             turn={**child_turn, 'status': 'completed', 'items': [child_message]})
                        await sync()
                        await assert_groups()
                        assert await row('foreign-child-message').count() == 0
                        assert 'Foreign child conversation' not in await page.locator('#activity').text_content()
                        assert await group('t2').get_attribute('open') is not None
                        assert 'In progress' in await row('legacy-live').locator('.activity-collaboration-label').text_content()
                        progress = {**second['items'][3], 'agentsStates': {
                            'drill-2-thread': {'status': 'running', 'message': 'Updated public live progress.'}}}
                        item_event('item/started', 't2', progress)
                        await sync()
                        assert await group('t2').get_attribute('open') is not None
                        assert 'Updated public live progress.' in await row('legacy-live').inner_text()
                        final = {**progress, 'status': 'failed', 'agentsStates': {
                            'drill-2-thread': {'status': 'errored', 'message': 'Public retry failed; original project retained.'}}}
                        second['items'][3] = final
                        item_event('item/completed', 't2', final)
                        completed = lifecycle('s-second-done', 'completed', '/root/drill-2', 'drill-2-thread')
                        second['items'].append(completed)
                        item_event('item/started', 't2', completed)
                        item_event('item/completed', 't2', completed)
                        second['items'][1]['text'] = '## Retry result\n\nThe retry failed; the same project is retained.'
                        item_event('item/completed', 't2', second['items'][1])
                        second['status'] = 'completed'
                        emit('turn/completed', 't2', turn=deepcopy(second))
                        await sync()
                        await page.evaluate('() => refresh()')
                        await assert_groups()
                        assert await group('t2').get_attribute('open') is not None
                        assert await group('t1').get_attribute('open') is None
                        assert 'Failed' in await row('legacy-live').locator('.activity-collaboration-label').text_content()
                        assert 'Public retry failed' in await row('legacy-live').inner_text()
                        assert 'Updated public live progress' not in await row('legacy-live').text_content()
                        assert 'Public main-reply progress' not in await row('a2').text_content()
                        assert await second_handle.evaluate('(node) => node.isConnected')

                        # Exact enum labels plus missing/null/future kinds and
                        # legacy tool statuses. Malformed values never become JSON
                        # summaries or a fabricated lifecycle execution status.
                        variants = [
                            (lifecycle('variant', kind, '/root/example', 'child'), label)
                            for kind, label in [('started', 'Started'), ('interacted', 'Interacted with'), ('interrupted', 'Interrupted'), ('completed', 'Completed')]
                        ]
                        variants += [(call('variant', tool, 'completed', []), label) for tool, label in [
                            ('spawnAgent', 'Spawn agent'), ('sendInput', 'Send input'), ('resumeAgent', 'Resume agent'),
                            ('wait', 'Wait for agents'), ('closeAgent', 'Close agent'), ('sendMessage', 'Send message'),
                            ('followupTask', 'Follow-up task'), ('interruptAgent', 'Interrupt agent'), ('listAgents', 'List agents')]]
                        for value in [None, 'future-kind', '__proto__', {'raw': 'not-a-kind'}]:
                            variants.append(({'id': 'variant', 'type': 'subAgentActivity', 'kind': value}, 'Subagent activity'))
                        variants.append(({'id': 'variant', 'type': 'subAgentActivity'}, 'Subagent activity'))
                        for value in [None, 'future-tool', '__proto__', {'raw': 'not-a-tool'}]:
                            variants.append(({'id': 'variant', 'type': 'collabAgentToolCall', 'tool': value, 'status': None}, 'Agent tool'))
                        labels = await page.evaluate('''(variants) => variants.map(([item]) => {
                            const node = document.createElement('div');
                            DeskActivity.render(node, item, 'UNSAFE RAW FALLBACK');
                            return node.querySelector('.activity-collaboration-label').textContent;
                        })''', variants)
                        for (item, expected), label in zip(variants, labels):
                            assert label.startswith(expected + ' ·') or label == expected, (item, label)
                            assert all(bad not in label for bad in ('[object Object]', '"raw"', 'UNSAFE RAW', 'function ')), label
                        assert all('Status unknown' in label for label in labels[-4:])
                        states = {state: {'status': state, 'message': 'Public state output: ' + state}
                                  for state in ('pendingInit', 'running', 'interrupted', 'completed', 'errored', 'shutdown', 'notFound')}
                        state_call = call('variant', 'listAgents', 'completed', list(states), states)
                        state_evidence = await page.evaluate('''(item) => {
                            const node = document.createElement('div');
                            DeskActivity.render(node, item, '');
                            return node.querySelector('pre').textContent;
                        }''', state_call)
                        for state in states:
                            assert 'Public state output: ' + state in state_evidence

                        # Read-only handoff uses the real backend formatter, not
                        # browser text scraping. Reopening uses the final snapshot.
                        await page.locator('#handoff').click()
                        await page.locator('#preview').wait_for(state='visible')
                        handoff = await page.locator('#handoff-text').input_value()
                        assert public_task in handoff and public_result in handoff
                        assert '/root/power' in handoff and '/root/drill-2' in handoff
                        assert 'Updated public failure' in handoff and 'Public retry failed' in handoff
                        assert 'private-collab-meta' not in handoff and 'private-extension-value' not in handoff
                        assert 'private-state-extension' not in handoff
                        await page.keyboard.press('Escape')
                        await reopen_reading(390)
                        await assert_groups()
                        assert await group('t1').get_attribute('open') is None
                        assert await group('t2').get_attribute('open') is not None
                        await group('t1').locator(':scope > summary').click()
                        assert 'Public retry failed' in await row('legacy-live').inner_text()
                        assert 'Updated public failure' in await row('legacy-wait').inner_text()
                        for width in (1250, 390, 360):
                            await page.set_viewport_size({'width': width, 'height': 844})
                            await reopen_reading(width)
                            await assert_groups()
                            assert await group('t1').get_attribute('open') is not None
                            assert await group('t2').get_attribute('open') is not None
                            if os.environ.get('DESK_COLLABORATION_RECEIPT'):
                                await page.screenshot(path=str(Path(os.environ['DESK_COLLABORATION_RECEIPT']) / f'collaboration-reopen-{width}.png'))
                            assert await page.evaluate('document.documentElement.scrollWidth <= innerWidth && document.querySelector("#activity").scrollWidth <= document.querySelector("#activity").clientWidth'), width
                        external = [request for request in requests if not request.startswith(url + '/')]
                        assert not external, external
                        assert not errors, errors
                        assert [call['method'] for call in native_calls] == ['thread/resume', 'thread/read'], native_calls
                        receipt = {'httpSource': str(Path(desk_server.__file__).resolve()),
                            'nativeSnapshotAndReplay': True, 'oneCollapsedCollaborationGroupPerTurn': True,
                            'liveAndCompletedDefaultCollapsed': True, 'mainPromptsAndRepliesRemainReadable': True,
                            'v2LifecycleAndLegacyToolStatuses': True, 'childIdsAndNativeEncounterOrder': True,
                            'expansionStableAcrossStreamCompletionAndRefresh': True,
                            'publicPromptsResultsAndFailuresVisibleOnExpansion': True,
                            'readOnlyBackendHandoffAndReopenRetainEvidence': True,
                            'unknownKindsAndMissingFieldsGraceful': True, 'noChildControls': True,
                            'foreignChildTurnsAndMessagesDoNotPolluteParentTimeline': True,
                            'rawHTMLTextOnly': True, 'nativeCalls': native_calls,
                            'ordinaryReopenReadingExact': True, 'reopenViews': reopen_views,
                            'nativeCatalogReads': catalog_reads,
                            'viewportWidths': [1250, 390, 360], 'pageOverflow': False,
                            'externalRequests': external, 'javascriptErrors': errors}
                        if os.environ.get('DESK_COLLABORATION_RECEIPT'):
                            destination = Path(os.environ['DESK_COLLABORATION_RECEIPT'])
                            destination.mkdir(parents=True, exist_ok=True, mode=0o700)
                            report = destination / 'browser-collaboration.json'
                            report.write_text(json.dumps(receipt, indent=2) + '\n')
                            report.chmod(0o600)
                            screenshot = destination / 'collaboration-360.png'
                            await page.screenshot(path=str(screenshot), full_page=True)
                            screenshot.chmod(0o600)
                        print(json.dumps(receipt, indent=2), flush=True)
                    finally:
                        await browser.close()
            finally:
                server.shutdown()
                worker.join(timeout=5)
                server.server_close()
                desk.close()
                desk.store.db.close()


if __name__ == '__main__':
    asyncio.run(check())
