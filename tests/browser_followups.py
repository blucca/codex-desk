"""Session-bound follow-ups through real loopback HTTP and native-shaped events.

DESK_TEST_TEMP=/your/workspace/temp DESK_CHROMIUM=/path/to/chromium \
  python tests/browser_followups.py

The fixture subclasses Runtime, retaining its attachment/turn/approval lifecycle.
Only request/send transport is controlled; it starts no native process or inference.
DESK_FOLLOWUP_CASES=unknown runs only the retirement/restart/review acceptance.
DESK_FOLLOWUP_CASES=edit-return runs only saved-entry edit/return acceptance.
"""
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

if not os.environ.get('DESK_USE_INSTALLED'):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from codex_desk import server as desk_server
from codex_desk.followups import list_followups, pending_followup
from codex_desk.runtime import Runtime, save_profile
from playwright.async_api import async_playwright


async def check():
    root = Path(os.environ['DESK_TEST_TEMP'])
    root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root, prefix='desk-followups-') as temporary:
        folder = Path(temporary)
        evidence = Path(os.environ.get('DESK_TEST_EVIDENCE', str(folder / 'evidence')))
        evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
        home, state_dir = folder / 'native-home', folder / 'state'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture-model"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        profile = save_profile(home, 'retained', 'https://fixture.example/v1',
                               'fixture-model', 'synthetic-only-key')['id']
        settings = {p.name: p.read_bytes() for p in home.iterdir()}
        projects = {id: folder / project for id, project in (
            ('session-a', 'project-a'), ('session-b', 'project-b-接口'))}
        for cwd in projects.values():
            cwd.mkdir()
        threads = {id: {'id': 'native-' + id, 'cwd': str(cwd),
            'name': 'Project ' + id[-1].upper(), 'turns': [{'id': 'prior-turn', 'items': [{
                'id': 'prior-message-' + id, 'type': 'agentMessage',
                'text': 'Earlier session evidence retained.'}]}]}
            for id, cwd in projects.items()}
        native_calls, sent, http_calls, external, errors, completed = [], [], [], [], [], []
        holds, outcomes = {}, {}
        pages = []

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
                if method == 'thread/resume':
                    return {'thread': threads[self.id], 'model': 'fixture-model',
                            'modelProvider': 'desk_provider'}
                if method == 'thread/name/set':
                    return {}
                if method == 'turn/interrupt':
                    terminal(self.id, 'interrupted')
                    return {}
                assert method == 'turn/start', 'Unexpected native request: ' + method
                text = params['input'][0]['text']
                if text in holds:
                    entered, release = holds[text]
                    entered.set()
                    assert release.wait(25), 'Held native request was not released: ' + text
                outcome = outcomes.get(text, 'inProgress')
                if outcome == 'rejected':
                    from codex_desk.runtime import NativeRequestRejected
                    raise NativeRequestRejected('Fixture native turn rejected; retain preparation')
                if outcome == 'unknown':
                    raise RuntimeError('Native Codex request timed out; stop Desk and reopen the session')
                turn = {'id': 'fixture-turn-' + str(len(turns())), 'status': outcome}
                if outcome == 'inProgress':
                    with self.lifecycle_lock:
                        self._message({'method': 'turn/started', 'params': {
                            'threadId': threads[self.id]['id'], 'turn': turn}})
                return {'turn': turn}

            def send(self, payload):
                sent.append({'session': self.id, 'payload': payload})

            def close(self):
                with self.lifecycle_lock:
                    self.closing = True
                    self._mark_exited()
                    self.process.poll = lambda: 0

        def turns():
            return [call for call in native_calls if call['method'] == 'turn/start']

        def terminal(identifier, status='completed'):
            runtime = desk.runtimes[identifier]
            with runtime.lifecycle_lock:
                runtime._message({'method': 'turn/completed', 'params': {
                    'threadId': threads[identifier]['id'], 'turn': {
                        'id': 'fixture-turn-' + str(len(turns())), 'status': status}}})

        def interaction(identifier, question=False, request=71):
            message = {'id': request, 'method': 'item/tool/requestUserInput' if question
                else 'item/commandExecution/requestApproval', 'params': {
                'threadId': threads[identifier]['id'], 'turnId': 'fixture-active-turn'}}
            if question:
                message['params']['questions'] = [{'id': 'choice', 'header': 'Check scope',
                    'question': 'Which verification should run?', 'isOther': False,
                    'isSecret': False, 'options': [
                        {'label': 'Existing test', 'description': 'Use only the existing fixture'},
                        {'label': 'Inspect result', 'description': 'Read retained output only'}]}]
            else:
                message['params']['command'] = 'fixture-read-only-verification'
            runtime = desk.runtimes[identifier]
            with runtime.lifecycle_lock:
                runtime._message(message)

        def start_server(port=0, seed=False):
            desk = desk_server.Desk('never-executed', home, state_dir)
            if seed:
                for identifier, cwd in projects.items():
                    desk.store.create(str(cwd), profile, identifier=identifier,
                                      name=threads[identifier]['name'])
                    desk.store.update(identifier, thread_id=threads[identifier]['id'],
                        status='completed', thread_saved=1, model='fixture-model',
                        provider='desk_provider', name_pending=0)
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', port), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever,
                kwargs={'poll_interval': .01}, daemon=True)
            worker.start()
            return desk, server, worker

        def stop_server(desk, server, worker):
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)
            desk.close()
            desk.store.db.close()

        def checkpoint(name):
            completed.append(name)
            print(json.dumps({'passed': name, 'controlled_turns': len(turns())}), flush=True)

        with patch.object(desk_server, 'Runtime', ControlledRuntime):
            desk, server, worker = start_server(seed=True)
            port = server.server_port
            url = f'http://127.0.0.1:{port}'
            bindings = {id: {field: desk.store.get(id)[field]
                for field in ('cwd', 'profile', 'thread_id')} for id in projects}
            try:
                async with async_playwright() as playwright:
                    browser = await playwright.chromium.launch(
                        executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage'])
                    context = await browser.new_context(viewport={'width': 1250, 'height': 900})

                    async def new_page():
                        page = await context.new_page()
                        page.set_default_timeout(10_000)
                        page.on('pageerror', lambda error: errors.append(str(error)))

                        def requested(request):
                            parsed = urlsplit(request.url)
                            http_calls.append({'method': request.method, 'path': parsed.path})
                            if parsed.hostname != '127.0.0.1':
                                external.append(request.url)

                        page.on('request', requested)
                        pages.append(page)
                        await page.goto(url)
                        await page.wait_for_function('state.sessions.length===2')
                        return page

                    async def open_session(page, identifier):
                        await page.locator(f'.session-row[data-session="{identifier}"] .session').click()
                        await page.wait_for_function(
                            'id=>selected===id && !opening && !$("task").hidden', arg=identifier)

                    async def refresh(page):
                        await page.evaluate('refresh()')

                    async def layout(page, width, label):
                        await page.set_viewport_size({'width': width,
                            'height': 900 if width == 1250 else 844})
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth'), width
                        await page.screenshot(path=str(evidence / f'{label}-{width}.png'), full_page=True)

                    try:
                        page = await new_page()
                        await open_session(page, 'session-a')
                        assert not turns()

                        def queue(identifier='session-a'):
                            return list_followups(desk.store, identifier)

                        def row(page, identifier):
                            return page.locator(f'.followup-entry[data-followup="{identifier}"]')

                        async def queue_refresh(page):
                            await page.evaluate('DeskFollowups.refresh()')
                            await page.locator('#followups').evaluate('(n)=>n.open=true')

                        async def add(page, identifier, text, mode='native'):
                            before = {entry['id'] for entry in queue(identifier)}
                            await page.locator('#prompt').fill(text)
                            await page.locator('#turn-mode').select_option(mode)
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups') as response:
                                await page.locator('#prepare-followup').click()
                            assert (await response.value).status == 200
                            await page.wait_for_function('submitting.size===0')
                            added = [entry for entry in queue(identifier) if entry['id'] not in before]
                            assert len(added) == 1, added
                            assert (added[0]['text'], added[0]['mode']) == (text, mode)
                            return added[0]

                        async def edit(page, entry, text, mode):
                            await row(page, entry['id']).get_by_role('button', name='Edit', exact=True).click()
                            await row(page, entry['id']).get_by_role('textbox', name='Follow-up task').fill(text)
                            await row(page, entry['id']).get_by_role('combobox', name='Follow-up mode').select_option(mode)
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/edit') as response:
                                await row(page, entry['id']).get_by_role('button', name='Save changes', exact=True).click()
                            assert (await response.value).status == 200
                            await row(page, entry['id']).get_by_role('button', name='Edit', exact=True).wait_for()
                            return next(e for e in queue() if e['id'] == entry['id'])

                        async def send_next(page, status=200):
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/send') as response:
                                await page.locator('#followup-send').click()
                            actual = await response.value
                            assert actual.status == status, (actual.status, await actual.text())
                            await queue_refresh(page)
                            await refresh(page)
                            return await actual.json()

                        async def clear(page):
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/clear') as response:
                                await page.locator('#followup-clear').click()
                            assert (await response.value).status == 200
                            await queue_refresh(page)

                        async def run_original(page, text):
                            await page.locator('#prompt').fill(text)
                            await page.locator('#turn-mode').select_option('native')
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/turn') as response:
                                await page.locator('#send').click()
                            assert (await response.value).status == 200
                            await page.wait_for_function('submitting.size===0')
                            await refresh(page)

                        only_unknown = os.environ.get('DESK_FOLLOWUP_CASES') == 'unknown'
                        if not only_unknown:
                            first = await add(page, 'session-a', 'Inspect parser behavior', 'native')
                            second = await add(page, 'session-a', 'Run saved verification', 'plan')
                            await page.reload()
                            await page.wait_for_function('selected==="session-a" && !opening && !$("task").hidden')
                            await queue_refresh(page)
                            for width in (1250, 390):
                                await page.set_viewport_size({'width': width, 'height': 900 if width == 1250 else 844})
                                candidate = f'Inspect parser behavior\nKeep API compatibility and verify empty input at {width}px.'
                                mode = 'plan' if first['mode'] == 'native' else 'native'
                                await row(page, first['id']).get_by_role('button', name='Edit', exact=True).click()
                                await row(page, first['id']).get_by_role('textbox', name='Follow-up task').fill(candidate)
                                await row(page, first['id']).get_by_role('combobox', name='Follow-up mode').select_option(mode)
                                other_edit = row(page, second['id']).get_by_role('button', name='Edit', exact=True)
                                if await other_edit.is_enabled():
                                    await other_edit.click()
                                    await row(page, first['id']).get_by_role('button', name='Edit', exact=True).click()
                                actual = await row(page, first['id']).get_by_role('textbox', name='Follow-up task').input_value()
                                assert actual == candidate, {'width': width, 'expected': candidate, 'actual': actual}
                                assert await other_edit.is_disabled()
                                await queue_refresh(page)
                                await open_session(page, 'session-b')
                                await open_session(page, 'session-a')
                                await queue_refresh(page)
                                assert await row(page, first['id']).get_by_role('textbox', name='Follow-up task').input_value() == candidate
                                assert await row(page, first['id']).get_by_role('combobox', name='Follow-up mode').input_value() == mode
                                assert queue() == [first, second]
                                await layout(page, width, 'edit-return')
                                async with page.expect_response(lambda response:
                                        urlsplit(response.url).path == '/api/followups/edit') as response:
                                    await row(page, first['id']).get_by_role('button', name='Save changes', exact=True).click()
                                assert (await response.value).status == 200
                                await other_edit.wait_for(state='visible')
                                await page.wait_for_function('document.querySelectorAll("#followup-list textarea").length===0')
                                first = queue()[0]
                                assert (first['text'], first['mode']) == (candidate, mode)
                                assert await other_edit.is_enabled()
                                await row(page, first['id']).get_by_role('button', name='Edit', exact=True).click()
                                await row(page, first['id']).get_by_role('textbox', name='Follow-up task').fill('Explicitly cancelled candidate')
                                await row(page, first['id']).get_by_role('button', name='Cancel edit', exact=True).click()
                                assert queue() == [first, second]
                                await other_edit.click()
                                await row(page, second['id']).get_by_role('button', name='Cancel edit', exact=True).click()
                                await page.reload()
                                await page.wait_for_function('selected==="session-a" && !opening && !$("task").hidden')
                                await queue_refresh(page)
                                assert await row(page, first['id']).locator('pre').inner_text() == candidate
                                assert queue() == [first, second]
                                checkpoint(f'{width}px edit survives entry-switch attempt and project return; Save/Cancel unlock other edits')
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/remove') as response:
                                await row(page, first['id']).get_by_role('button', name='Remove', exact=True).click()
                            assert (await response.value).status == 200
                            await queue_refresh(page)
                            assert [entry['id'] for entry in queue()] == [second['id']]
                            await row(page, second['id']).get_by_role('button', name='Edit', exact=True).click()
                            await clear(page)
                            replacement = await add(page, 'session-a', 'Preparation after explicit Clear', 'native')
                            replacement_edit = row(page, replacement['id']).get_by_role('button', name='Edit', exact=True)
                            assert await replacement_edit.is_enabled(), 'An explicitly cleared editor must not block a new preparation'
                            await replacement_edit.click()
                            await row(page, replacement['id']).get_by_role('button', name='Cancel edit', exact=True).click()
                            await clear(page)
                            checkpoint('explicit Clear of an edited entry permits editing a new preparation')
                            assert not queue() and not queue('session-b') and not turns()
                            assert not errors and not external, (errors, external)
                            assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                            if os.environ.get('DESK_FOLLOWUP_CASES') == 'edit-return':
                                result = {'passed': completed, 'controlled_turns': 0,
                                    'native_processes': 0, 'provider_inference_turns': 0,
                                    'javascript_errors': errors, 'external_requests': external,
                                    'overflow_1250': False, 'overflow_390': False}
                                (evidence / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
                                print(json.dumps(result, indent=2), flush=True)
                                return
                        if only_unknown:
                            await open_session(page, 'session-b')
                            other = await add(page, 'session-b', 'Only project B verification', 'plan')
                            other_new = await add(page, 'session-b', 'A different project B follow-up', 'native')
                            await open_session(page, 'session-a')
                            second_page = await new_page()
                            await open_session(second_page, 'session-a')
                        else:
                            await run_original(page, 'Original active project A task')
                            assert desk.store.get('session-a')['status'] == 'running'
                            first = await add(page, 'session-a', '  Review parser "接口" next\nKeep exact spacing. 🔧  ', 'plan')
                            second = await add(page, 'session-a', 'Run the existing verification', 'native')
                            third_text = 'Explain retained result <img src="https://invalid.example/pixel">\n' + 'long-unbroken-token-' * 20
                            third = await add(page, 'session-a', third_text, 'plan')
                            assert await page.locator('#followup-send').is_disabled()
                            assert len(turns()) == 1
                            checkpoint('active-turn Work/Plan preparation is saved without native dispatch')

                            await open_session(page, 'session-b')
                            other = await add(page, 'session-b', 'Only project B verification', 'plan')
                            assert len(queue('session-b')) == 1
                            await open_session(page, 'session-a')
                            await queue_refresh(page)
                            first = await edit(page, first, first['text'] + '\nReviewed as Work', 'native')
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/reorder') as response:
                                await row(page, third['id']).get_by_role('button', name='Move up', exact=True).click()
                            assert (await response.value).status == 200
                            await queue_refresh(page)
                            assert [e['id'] for e in queue()] == [first['id'], third['id'], second['id']]
                            async with page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/remove') as response:
                                await row(page, second['id']).get_by_role('button', name='Remove', exact=True).click()
                            assert (await response.value).status == 200
                            await queue_refresh(page)
                            assert [(e['id'], e['mode'], e['order']) for e in queue()] == [
                                (first['id'], 'native', 1), (third['id'], 'plan', 2)]
                            assert queue('session-b') == [other]
                            assert len(turns()) == 1 and not external
                            await layout(page, 1250, 'prepared')
                            await layout(page, 390, 'prepared')
                            checkpoint('session-scoped editing/removal/reordering preserves Work/Plan and literal text')

                            terminal('session-a')
                            await refresh(page)
                            assert await page.locator('#followup-send').is_enabled()
                            assert len(turns()) == 1
                            await send_next(page)
                            assert len(turns()) == 2 and turns()[-1]['session'] == 'session-a'
                            assert turns()[-1]['params']['threadId'] == threads['session-a']['id']
                            assert turns()[-1]['params']['input'][0]['text'] == first['text']
                            assert [e['id'] for e in queue()] == [third['id']]
                            assert queue('session-b') == [other]
                            assert await page.locator('#followup-send').is_disabled()
                            terminal('session-a')
                            await refresh(page)
                            assert len(turns()) == 2
                            await send_next(page)
                            assert turns()[-1]['params']['collaborationMode']['mode'] == 'plan'
                            assert not queue() and len(turns()) == 3
                            checkpoint('terminal events do not auto-send; manual Send next admits one bound Work/Plan task')

                            terminal('session-a')
                            await refresh(page)
                            concurrent = await add(page, 'session-a', 'Only one cross-tab admission', 'native')
                            await add(page, 'session-a', 'Later task stays prepared', 'plan')
                            second_page = await new_page()
                            await open_session(second_page, 'session-a')
                            await queue_refresh(second_page)
                            holds[concurrent['text']] = (threading.Event(), threading.Event())
                            both_routes, release_routes = asyncio.Event(), asyncio.Event()
                            arrived = []

                            async def simultaneous(route):
                                arrived.append(route)
                                if len(arrived) == 2:
                                    both_routes.set()
                                await release_routes.wait()
                                await route.continue_()

                            await page.route('**/api/followups/send', simultaneous)
                            await second_page.route('**/api/followups/send', simultaneous)
                            before_turns = len(turns())
                            await asyncio.gather(page.locator('#followup-send').click(),
                                                 second_page.locator('#followup-send').click())
                            await asyncio.wait_for(both_routes.wait(), 10)
                            release_routes.set()
                            assert await asyncio.to_thread(holds[concurrent['text']][0].wait, 10)
                            deadline = asyncio.get_running_loop().time() + 10
                            while not pending_followup(desk.store, 'session-a'):
                                assert asyncio.get_running_loop().time() < deadline
                                await asyncio.sleep(.02)
                            assert len(turns()) == before_turns + 1
                            holds[concurrent['text']][1].set()
                            await page.wait_for_function('document.querySelector("#followup-status").textContent.includes("accepted") || !document.querySelector("#followup-error").hidden')
                            await second_page.wait_for_function('document.querySelector("#followup-status").textContent.includes("accepted") || !document.querySelector("#followup-error").hidden')
                            await page.unroute('**/api/followups/send', simultaneous)
                            await second_page.unroute('**/api/followups/send', simultaneous)
                            await queue_refresh(page)
                            await refresh(page)
                            assert len(turns()) == before_turns + 1
                            assert len(queue()) == 1 and queue()[0]['text'] == 'Later task stays prepared'
                            assert pending_followup(desk.store, 'session-a') is None
                            checkpoint('two actual browser tabs race to one native admission without sending the next entry')

                            terminal('session-a')
                            await refresh(page)
                            await clear(page)
                            rejected = await add(page, 'session-a', 'Definitely rejected prepared task', 'plan')
                            outcomes[rejected['text']] = 'rejected'
                            await send_next(page, 400)
                            assert queue() == [rejected]
                            assert pending_followup(desk.store, 'session-a') is None
                            assert await page.locator('#followup-send').is_enabled()
                            checkpoint('definite native rejection retains the exact preparation and permits explicit retry')

                            repeated_text = 'Same words, newly reviewed preparation'
                            repeated = await edit(page, rejected, repeated_text, 'plan')
                            holds[repeated_text] = (threading.Event(), threading.Event())
                            before_turns = len(turns())
                            await page.locator('#followup-send').click()
                            assert await asyncio.to_thread(holds[repeated_text][0].wait, 10)
                            await queue_refresh(second_page)
                            assert await second_page.locator('#followup-send').is_disabled()
                            live_reservation = pending_followup(desk.store, 'session-a')
                            async with second_page.expect_response(lambda response:
                                    urlsplit(response.url).path == '/api/followups/resolve') as response:
                                await second_page.locator('#followup-confirm-not-started').click()
                            assert (await response.value).status in (400, 409)
                            assert pending_followup(desk.store, 'session-a') == live_reservation
                            newer = await edit(second_page, repeated, repeated_text, 'plan')
                            assert newer['revision'] == repeated['revision'] + 1
                            holds[repeated_text][1].set()
                            await queue_refresh(page)
                            deadline = asyncio.get_running_loop().time() + 10
                            while pending_followup(desk.store, 'session-a'):
                                assert asyncio.get_running_loop().time() < deadline
                                await asyncio.sleep(.02)
                            await queue_refresh(page)
                            assert len(turns()) == before_turns + 1
                            assert queue() == [{**newer, 'state': 'queued'}]
                            checkpoint('live receipt cannot be released; newer identical-text edit survives delayed acceptance')

                            terminal('session-a')
                            await refresh(page)
                            holds[repeated_text] = (threading.Event(), threading.Event())
                            before_turns = len(turns())
                            await page.locator('#followup-send').click()
                            assert await asyncio.to_thread(holds[repeated_text][0].wait, 10)
                            await open_session(page, 'session-b')
                            await queue_refresh(page)
                            other_new = await add(page, 'session-b', 'A different project B follow-up', 'native')
                            holds[repeated_text][1].set()
                            deadline = asyncio.get_running_loop().time() + 10
                            while pending_followup(desk.store, 'session-a'):
                                assert asyncio.get_running_loop().time() < deadline
                                await asyncio.sleep(.02)
                            await queue_refresh(page)
                            assert await page.evaluate('selected') == 'session-b'
                            assert queue('session-b') == [other, other_new]
                            assert not queue() and len(turns()) == before_turns + 1
                            assert turns()[-1]['session'] == 'session-a'
                            assert turns()[-1]['params']['threadId'] == threads['session-a']['id']
                            checkpoint('changing project during delayed Send next never reroutes or clears B preparation')

                            await open_session(page, 'session-a')
                            terminal('session-a')
                            await refresh(page)
                            approval_task = await add(page, 'session-a', 'After approval, verify this result', 'native')
                            question_task = await add(page, 'session-a', 'After the next completion, explain the plan', 'plan')
                            await run_original(page, 'Original task needing native interaction')
                            interaction('session-a')
                            interaction('session-a', question=True, request=72)
                            await refresh(page)
                            assert await page.locator('#followup-send').is_disabled()
                            before_turns = len(turns())
                            await page.locator('#approvals').get_by_role('button', name='Allow once', exact=True).click()
                            await refresh(page)
                            assert desk.store.get('session-a')['status'] == 'approval'
                            assert len(desk.runtimes['session-a'].approvals) == 1
                            assert await page.locator('#followup-send').is_disabled()
                            await page.locator('#approvals select').select_option('Existing test')
                            await page.locator('#approvals').get_by_role('button', name='Send answers', exact=True).click()
                            await refresh(page)
                            assert desk.store.get('session-a')['status'] == 'running'
                            assert await page.locator('#followup-send').is_disabled()
                            assert len(turns()) == before_turns
                            terminal('session-a')
                            await refresh(page)
                            assert len(turns()) == before_turns
                            await send_next(page)
                            assert turns()[-1]['params']['input'][0]['text'] == approval_task['text']
                            terminal('session-a')
                            await refresh(page)
                            await send_next(page)
                            assert turns()[-1]['params']['input'][0]['text'] == question_task['text']
                            assert turns()[-1]['params']['collaborationMode']['mode'] == 'plan'
                            assert not queue()
                            checkpoint('approval and question both block queue admission until terminal and explicit Send next')

                        terminal('session-a')
                        await refresh(page)
                        uncertain = await add(page, 'session-a', 'Unconfirmed request\n' + 'retained-unknown-' * 18, 'native')
                        later = await add(page, 'session-a', 'Later task cannot bypass uncertainty', 'plan')
                        outcomes[uncertain['text']] = 'unknown'
                        retired_runtime = desk.runtimes['session-a']
                        await send_next(page, 400)
                        reservation = pending_followup(desk.store, 'session-a')
                        assert reservation and reservation['state'] == 'unknown'
                        assert queue()[0]['state'] == 'needs_review'
                        assert await page.locator('#send').is_disabled()
                        assert 'Start unconfirmed' in await page.locator('#followup-status').inner_text()
                        assert retired_runtime.closing
                        before_late = desk.store.get('session-a')
                        events_before_late = desk.store.events('session-a')
                        with retired_runtime.lifecycle_lock:
                            retired_runtime._message({'method': 'turn/started', 'params': {
                                'threadId': threads['session-a']['id'], 'turn': {
                                    'id': 'late-unconfirmed-turn', 'status': 'inProgress'}}})
                            retired_runtime._message({'method': 'item/agentMessage/delta', 'params': {
                                'threadId': threads['session-a']['id'], 'itemId': 'late-output',
                                'delta': 'retired output must stay retired'}})
                        assert desk.store.get('session-a') == before_late
                        assert desk.store.events('session-a') == events_before_late
                        checkpoint('late events from an unknown-retired runtime cannot revive or change the session')
                        assert await page.locator('#followup-send').is_disabled()
                        uncertain_newer = await edit(page, queue()[0], 'Newer goal after uncertain start', 'plan')
                        assert await page.locator('#send').is_disabled()
                        assert 'Start unconfirmed' in await page.locator('#followup-status').inner_text()
                        await layout(page, 1250, 'unknown-review')
                        await layout(page, 390, 'unknown-review')
                        before_turns = len(turns())
                        for current_page in (page, second_page):
                            await current_page.goto('about:blank')
                        await asyncio.to_thread(stop_server, desk, server, worker)
                        desk, server, worker = start_server(port=port)
                        await page.goto(url)
                        await page.wait_for_function('selected==="session-a" && !opening && !$("task").hidden')
                        await queue_refresh(page)
                        assert pending_followup(desk.store, 'session-a') == reservation
                        assert queue() == [uncertain_newer, later]
                        assert await page.locator('#followup-send').is_disabled()
                        assert await page.locator('#send').is_disabled()
                        assert 'Start unconfirmed' in await page.locator('#followup-status').inner_text()
                        assert len(turns()) == before_turns
                        await page.reload()
                        await page.wait_for_function('selected==="session-a" && !opening && !$("task").hidden')
                        await queue_refresh(page)
                        assert await page.locator('#followup-send').is_disabled()
                        assert await page.locator('#send').is_disabled()
                        assert 'Start unconfirmed' in await page.locator('#followup-status').inner_text()
                        assert len(turns()) == before_turns
                        checkpoint('unknown receipt and newer preparation survive actual Desk/SQLite/page restart without replay')

                        async with page.expect_response(lambda response:
                                urlsplit(response.url).path == '/api/followups/resolve') as response:
                            await page.locator('#followup-confirm-not-started').click()
                        assert (await response.value).status == 200
                        await queue_refresh(page)
                        assert pending_followup(desk.store, 'session-a') is None
                        assert queue()[0] == {**uncertain_newer, 'state': 'queued'}
                        assert len(turns()) == before_turns
                        await send_next(page)
                        assert turns()[-1]['params']['input'][0]['text'] == uncertain_newer['text']
                        assert turns()[-1]['params']['collaborationMode']['mode'] == 'plan'
                        assert [e['id'] for e in queue()] == [later['id']]
                        checkpoint('explicit not-started review retains newest revision; manual retry sends only that reviewed goal')

                        terminal('session-a')
                        await refresh(page)
                        await clear(page)
                        accepted_unknown = await add(page, 'session-a', 'Already started elsewhere; record the outcome', 'native')
                        outcomes[accepted_unknown['text']] = 'unknown'
                        await send_next(page, 400)
                        before_turns = len(turns())
                        async with page.expect_response(lambda response:
                                urlsplit(response.url).path == '/api/followups/resolve') as response:
                            await page.locator('#followup-confirm-started').click()
                        assert (await response.value).status == 200
                        await queue_refresh(page)
                        assert not queue() and pending_followup(desk.store, 'session-a') is None
                        assert len(turns()) == before_turns
                        assert queue('session-b') == [other, other_new]
                        checkpoint('explicit started review consumes exact captured revision without another native turn')

                        await layout(page, 1250, 'resolved')
                        await layout(page, 390, 'resolved')
                        assert not errors, errors
                        assert not external, external
                        assert {p.name: p.read_bytes() for p in home.iterdir()} == settings
                        assert {id: {field: desk.store.get(id)[field] for field in bindings[id]}
                                for id in projects} == bindings
                        result = {'passed': completed, 'controlled_turns': len(turns()),
                            'native_processes': 0, 'provider_inference_turns': 0,
                            'javascript_errors': errors, 'external_requests': external,
                            'overflow_1250': False, 'overflow_390': False,
                            'queues': {id: queue(id) for id in projects}, 'bindings_unchanged': True,
                            'native_calls': native_calls, 'native_responses': sent}
                        (evidence / 'result.json').write_text(json.dumps(result,
                            indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps(result, indent=2, ensure_ascii=False), flush=True)
                    except Exception:
                        diagnostic = {'passed': completed, 'javascript_errors': errors,
                            'recent_http_calls': http_calls[-30:], 'controlled_turns': turns(),
                            'queues': {id: list_followups(desk.store, id) for id in projects},
                            'reservations': {id: pending_followup(desk.store, id) for id in projects}}
                        if pages:
                            try:
                                diagnostic['page'] = await pages[0].evaluate('({selected, status:$("status").textContent})')
                                await pages[0].screenshot(path=str(evidence / 'failure.png'), full_page=True)
                            except Exception:
                                pass
                        (evidence / 'failure.json').write_text(json.dumps(diagnostic,
                            indent=2, ensure_ascii=False) + '\n')
                        print(json.dumps({'failure': diagnostic}, ensure_ascii=False), flush=True)
                        raise
                    finally:
                        for _, release in holds.values():
                            release.set()
                        await context.close()
                        await browser.close()
                        for path in evidence.iterdir():
                            if path.is_file():
                                path.chmod(0o600)
            finally:
                for _, release in holds.values():
                    release.set()
                stop_server(desk, server, worker)


if __name__ == '__main__':
    asyncio.run(check())
