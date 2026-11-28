#!/usr/bin/env python3
"""Exercise same-page native activity reading returns through the actual workbench.

DESK_TEST_TEMP and DESK_TEST_EVIDENCE must point inside the workspace. The fixture
supplies native-shaped history and events to the actual loopback server; every
Run, Send next and approval response is trapped. Both viewport widths use the
ordinary sidebar Enter action with focus kept at the reading origin.
"""
import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import traceback
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit

if os.environ.get('DESK_USE_INSTALLED') != '1':
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import codex_desk
from codex_desk import server as desk_server
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from playwright.async_api import async_playwright

A, B, C = 'reading-A', 'reading-B', 'reading-C'
PRIOR, LIVE = 'A-prior-native-turn', 'A-live-native-turn'
COMMAND, MCP = 'A-native-command', 'A-native-mcp'
DRAFT = 'Keep this A preparation unsent — Plan the remaining verification.'
ANSWER = 'B pending answer remains unsent — keep its own native request.'
CHOICE = 'Keep existing scope'
C_DRAFT = 'C newest unsent draft must win the delayed A open.'


async def frames(page):
    await page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    await page.wait_for_function("!opening && !sessionReadingPending")


async def one(browser, width, scratch, evidence, cold=False):
    report = {'width': width, 'cold': cold, 'passed': False, 'checks': []}
    with tempfile.TemporaryDirectory(dir=scratch, prefix=f'session-reading-{width}-') as temporary:
        folder = Path(temporary)
        home, state_dir = folder / 'native-home', folder / 'state'
        home.mkdir()
        (home / 'config.toml').write_text('model="fixture-only"\n')
        (home / 'auth.json').write_text('{"synthetic":"unchanged"}\n')
        settings = {path.name: path.read_bytes() for path in home.iterdir()}
        projects = {session: folder / ('project-' + session) for session in (A, B, C)}
        for project in projects.values():
            project.mkdir()

        def agent(identifier, text):
            return {'id': identifier, 'type': 'agentMessage', 'text': text, 'phase': 'commentary'}

        lines = '\n'.join(f'Native command line {n:04d} — Café 项目 🌱 retains its original output.' for n in range(950))
        mcp_lines = '\n'.join(f'Native MCP line {n:04d} — exact saved result for the same task.' for n in range(650))
        threads = {
            A: {'id': 'native-reading-A', 'name': 'Reading project A', 'cwd': str(projects[A]),
                'turns': [
                    {'id': PRIOR, 'status': 'completed', 'items': [
                        {'id': 'A-native-user', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Read command and MCP evidence before the next check.'}]},
                        agent('A-native-preface', '# Original task evidence\n\n' + '\n'.join('Earlier context paragraph ' + str(n) for n in range(12))),
                        {'id': COMMAND, 'type': 'commandExecution', 'command': 'fixture verify original output',
                         'status': 'completed', 'exitCode': 0, 'aggregatedOutput': lines},
                        {'id': MCP, 'type': 'mcpToolCall', 'server': 'fixture', 'tool': 'read_saved_result',
                         'status': 'completed', 'arguments': {'project': 'A'}, 'result': {'content': [{'type': 'text', 'text': mcp_lines}]}},
                        {'id': 'A-native-collaboration', 'type': 'collabAgentToolCall', 'tool': 'spawnAgent',
                         'status': 'completed', 'senderThreadId': 'native-reading-A', 'receiverThreadIds': ['native-A-child'],
                         'prompt': 'Inspect the source result only.', 'agentsStates': {'native-A-child': {'status': 'completed', 'message': 'Child inspection retained its reported result.'}}},
                        agent('A-native-conclusion', 'Prior task answer keeps the command and MCP evidence together.')
                    ]},
                    {'id': LIVE, 'status': 'inProgress', 'items': [
                        {'id': 'A-current-user', 'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Continue the next controlled native task.'}]},
                        agent('A-current-output', '\n'.join('Current native output paragraph ' + str(n) for n in range(60)))
                    ]}
                ]},
            B: {'id': 'native-reading-B', 'name': 'Reading project B', 'cwd': str(projects[B]),
                'turns': [{'id': 'B-native-turn', 'status': 'inProgress', 'items': [agent('B-native-output', 'B waits for its own native answers.')]}]},
            C: {'id': 'native-reading-C', 'name': 'Reading project C', 'cwd': str(projects[C]),
                'turns': [{'id': 'C-native-turn', 'status': 'completed', 'items': [agent('C-native-output', 'Newest selected C evidence owns the workbench.')]}]}
        }
        question = {'id': 801, 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': threads[B]['id'], 'turnId': 'B-native-turn', 'itemId': 'B-native-question', 'questions': [
                {'id': 'B-answer', 'header': 'B native answer', 'question': 'What check should remain?', 'isOther': True},
                {'id': 'B-choice', 'header': 'B native choice', 'question': 'Which scope?', 'isOther': False,
                 'options': [{'label': CHOICE, 'description': 'Retain the existing check'}, {'label': 'Different scope', 'description': 'Separate next work'}]}
            ]}}
        calls, http, errors, holds = [], [], [], {}

        class ControlledRuntime:
            def __init__(self, store, identifier, binary, native_home, **options):
                assert binary == 'never-executed'
                self.store, self.id = store, identifier
                self.process = SimpleNamespace(poll=lambda: None)
                self.approvals = {'801': copy.deepcopy(question)} if identifier == B else {}

            def attach(self):
                calls.append({'method': 'thread/resume', 'session': self.id})
                self.thread_result = {'thread': copy.deepcopy(threads[self.id]), 'model': 'fixture-only', 'modelProvider': 'fixture'}
                self.store.update(self.id, thread_id=threads[self.id]['id'], status='approval' if self.id == B else 'running' if self.id == A else 'ready',
                                  model='fixture-only', provider='fixture')
                return self.thread_result

            def request(self, method, params):
                calls.append({'method': method, 'session': self.id})
                if method == 'thread/list':
                    return {'data': copy.deepcopy(list(threads.values())), 'nextCursor': None}
                if method == 'thread/read':
                    return {'thread': copy.deepcopy(next(thread for thread in threads.values() if thread['id'] == params['threadId']))}
                raise AssertionError('Unexpected native request: ' + method)

            def turn(self, *args, **kwargs):
                raise AssertionError('Reading must not admit a native task')

            def answer(self, *args, **kwargs):
                raise AssertionError('Reading must not send native answers')

            def approve(self, *args, **kwargs):
                raise AssertionError('Reading must not respond to a native approval')

            def close(self):
                self.process.poll = lambda: 0

        original_open = desk_server.Desk.open
        def controlled_open(desk, identifier):
            result = original_open(desk, identifier)
            held = holds.get(identifier)
            if held:
                entered, release = held
                entered.set()
                assert release.wait(30), 'Held original open was not released'
            return result

        with patch.object(desk_server, 'Runtime', ControlledRuntime), patch.object(desk_server.Desk, 'open', controlled_open):
            desk = desk_server.Desk('never-executed', home, state_dir)
            for session, project in projects.items():
                desk.store.create(str(project), 'default', identifier=session, name=threads[session]['name'])
                desk.store.update(session, thread_id=threads[session]['id'], thread_saved=1, status='saved', name_pending=0)
            saved = load_draft(desk.store, A)
            save_draft(desk.store, A, DRAFT, 'plan', saved['revision'])
            add_followup(desk.store, A, 'A first queued instruction — keep paused.', 'native')
            add_followup(desk.store, A, 'A second queued instruction — keep Plan.', 'plan')
            if cold:
                desk.store.event(A, {'method': 'turn/started', 'params': {'threadId': threads[A]['id'], 'turn': {'id': LIVE, 'status': 'inProgress'}}})
                desk.store.event(A, {'method': 'turn/plan/updated', 'params': {'threadId': threads[A]['id'], 'turnId': LIVE,
                    'explanation': 'Reported native steps remain distinct from the saved Plan draft.',
                    'plan': [{'step': 'Native verification step ' + str(n), 'status': 'inProgress' if n == 3 else 'pending'} for n in range(55)]}})
                desk.store.event(A, {'method': 'turn/diff/updated', 'params': {'threadId': threads[A]['id'], 'turnId': LIVE,
                    'diff': '\n'.join('+ Retained native patch line ' + str(n) for n in range(150))}})
            original_queue = followup_snapshot(desk.store, A)
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            worker.start()
            context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844})
            page = await context.new_page()
            page.set_default_timeout(12_000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: http.append({'path': urlsplit(request.url).path, 'method': request.method}))

            def local_preparation():
                with desk.store.lock:
                    return {'draft': dict(load_draft(desk.store, A)), 'queue': copy.deepcopy(followup_snapshot(desk.store, A))}

            async def checkpoint(name):
                report['checks'].append(name)
                await page.screenshot(path=str(evidence / f'{width}-{name}.png'))
                print(json.dumps({'width': width, 'passed': name}), flush=True)

            async def navigate(session):
                button = page.locator(f'.session-row[data-session="{session}"] .session')
                await button.evaluate('node => node.focus({preventScroll:true})')
                await button.press('Enter')
                await page.wait_for_function("session => selected===session && !opening && !$('task').hidden", arg=session)
                await frames(page)

            async def state():
                return await page.evaluate('''ids => {
                    const read = id => {const row=nodes.get(id),detail=row.querySelector('.activity-tool'),pre=row.querySelector('.activity-evidence');
                        return {turn:row.dataset.turnId,item:row.dataset.itemId,open:detail?.open ?? null,top:pre?.scrollTop || 0,left:pre?.scrollLeft || 0,screenTop:row.getBoundingClientRect().top};};
                    const group=collaborationGroups.get(ids.prior),pending=interactionCards.get(ids.b)?.get('801');
                    return {session:selected,thread:nativeThreadId,command:read(ids.command),mcp:read(ids.mcp),collaborationOpen:group?.node.open,
                        windowTop:scrollY,windowLeft:scrollX,latest:DeskSessionReading.follow(),
                        draft:$('prompt').value,mode:$('turn-mode').value,
                        pendingB:pending?Object.fromEntries([...pending.fields].map(([key,input])=>[key,input.value])):null,
                        readouts:{steps:{turn:DeskNativeSteps.state().turn,open:$('native-steps').open,top:$('native-steps-body').scrollTop},
                            changes:{turn:DeskTurnChanges.state().turn,open:$('turn-changes').open,top:$('turn-changes-body').scrollTop}}};
                }''', {'prior': PRIOR, 'command': COMMAND, 'mcp': MCP, 'b': B})

            def same_reading(before, after):
                for key in ('session', 'thread', 'collaborationOpen', 'windowLeft', 'latest', 'draft', 'mode', 'readouts'):
                    assert after[key] == before[key], (key, before, after)
                for key in ('command', 'mcp'):
                    for field in ('turn', 'item', 'open', 'top', 'left'):
                        assert after[key][field] == before[key][field], (key, field, before, after)
                    assert abs(after[key]['screenTop'] - before[key]['screenTop']) <= 1, (key, before, after)
                assert abs(after['windowTop'] - before['windowTop']) <= 1, (before, after)

            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function('state.sessions.length===3')
                await page.wait_for_function('!!globalThis.DeskReadingCheckpoint && !!globalThis.DeskSessionReading')
                await navigate(A)
                assert await page.locator('#prompt').input_value() == DRAFT
                assert await page.locator('#turn-mode').input_value() == 'plan'
                await page.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
                await page.locator(f'#activity [data-item-id="{MCP}"] summary').click()
                await page.locator(f'.activity-collaboration[data-collaboration-turn="{PRIOR}"] > summary').click()
                if cold:
                    await page.locator('#native-steps > summary').click()
                    await page.locator('#turn-changes > summary').click()
                    await page.evaluate("$('native-steps-body').scrollTop=95;$('turn-changes-body').scrollTop=137")
                await page.evaluate('''ids => {
                    nodes.get(ids.command).querySelector('.activity-evidence').scrollTop=283;
                    nodes.get(ids.mcp).querySelector('.activity-evidence').scrollTop=431;
                    const node=nodes.get(ids.command);window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});
                }''', {'command': COMMAND, 'mcp': MCP})
                await frames(page)
                baseline = await state()
                assert baseline['command']['top'] == 283 and baseline['mcp']['top'] == 431
                assert not baseline['latest'] and baseline['collaborationOpen'] and baseline['command']['turn'] == PRIOR
                prepared = local_preparation()
                if not cold:
                    await checkpoint('saved-plan-twoqueues-long-native-command-mcp-collaboration')

                if cold:
                    # The ordinary pagehide save must survive a new document and a
                    # fresh native attach, including updated text at the same IDs.
                    assert baseline['readouts']['steps'] == {'turn': LIVE, 'open': True, 'top': 95}
                    assert baseline['readouts']['changes'] == {'turn': LIVE, 'open': True, 'top': 137}
                    fresh_text = 'FRESH NATIVE MCP RESULT supplied for this reload.'
                    threads[A]['turns'][0]['items'][3]['result']['content'][0]['text'] += '\n' + fresh_text
                    desk.runtimes.pop(A).close()
                    await page.reload()
                    await page.wait_for_function('id => selected===id && !opening', arg=A)
                    await frames(page)
                    reloaded = await state()
                    same_reading(baseline, reloaded)
                    assert fresh_text in await page.locator(f'#activity [data-item-id="{MCP}"] pre').text_content()
                    assert local_preparation() == prepared
                    metadata = await page.evaluate("""() => {
                        const raw=localStorage.getItem(DeskReadingCheckpoint.STORAGE_KEY);
                        return {raw,value:JSON.parse(raw),limits:DeskReadingCheckpoint.LIMITS};
                    }""")
                    stored = metadata['value']
                    assert set(stored) == {'version', 'checkpoints'} and stored['version'] == 1
                    assert len(stored['checkpoints']) <= metadata['limits']['owners']
                    assert len(metadata['raw']) <= metadata['limits']['characters']
                    for entry in stored['checkpoints']:
                        assert set(entry) == {'version', 'owner', 'saved_at', 'view'}
                        assert set(entry['owner']) == {'native_home', 'session', 'thread_id'}
                        view = entry['view']
                        assert set(view) == {'latest', 'anchor', 'window_scroll', 'item_views', 'turn_views'}
                        assert len(view['item_views']) <= metadata['limits']['item_views']
                        assert len(view['turn_views']) <= metadata['limits']['turn_views']
                        for item in view['item_views']:
                            assert set(item) == {'turn_id', 'item_id', 'open', 'window_start', 'scroll_top', 'scroll_left'}
                        for turn in view['turn_views']:
                            assert set(turn) == {'turn_id', 'kind', 'open', 'scroll_top', 'scroll_left'}
                    for text in (DRAFT, ANSWER, CHOICE, lines[:100], mcp_lines[:100], str(home)):
                        assert text not in metadata['raw'], text
                    assert any(entry['owner']['session'] == A and entry['owner']['thread_id'] == threads[A]['id'] for entry in stored['checkpoints'])
                    report['cold_reload'] = {'before': baseline, 'after': reloaded, 'metadata': metadata}
                    await checkpoint('cold-pagehide-fresh-source-exact-tools-collaboration-readouts-metadata-only')

                    # A delayed launch namespace belongs to the old intent, not
                    # whichever source or editor the user chooses while waiting.
                    entered, release = threading.Event(), threading.Event()
                    async def hold_namespace(route):
                        response = await route.fetch()
                        entered.set()
                        assert await asyncio.to_thread(release.wait, 30), 'Held native home HTTP response was not released'
                        await route.fulfill(response=response)

                    await page.route('**/api/native/home', hold_namespace)
                    desk.runtimes.pop(A).close()
                    await page.reload()
                    assert await asyncio.to_thread(entered.wait, 12), 'Initial native namespace HTTP response did not enter its hold'
                    state_home = await page.evaluate("async () => (await api('/api/state')).native_material.native_home")
                    c_button = page.locator(f'.session-row[data-session="{C}"] .session')
                    await c_button.evaluate('node => node.focus({preventScroll:true})')
                    await c_button.press('Enter')
                    await page.wait_for_function('id => selected===id && !opening && nativeThreadId===state.sessions.find(row=>row.id===id).thread_id', arg=C)
                    await page.locator('#prompt').click()
                    await page.locator('#prompt').fill(C_DRAFT)
                    await page.wait_for_function('value => draftSaved.get(selected)?.text===value', arg=C_DRAFT)
                    c_before = await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                    async with page.expect_response(lambda response: urlsplit(response.url).path == '/api/native/home') as held_namespace:
                        release.set()
                    namespace_response = await held_namespace.value
                    assert namespace_response.ok, 'Held native namespace response failed'
                    namespace_body = await namespace_response.json()
                    assert set(namespace_body) == {'home_namespace'}
                    assert isinstance(namespace_body['home_namespace'], str) and len(namespace_body['home_namespace']) == 64
                    assert namespace_body['home_namespace'] == state_home
                    await page.unroute('**/api/native/home', hold_namespace)
                    await frames(page)
                    c_after = await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                    assert c_after == c_before, (c_before, c_after)
                    assert local_preparation() == prepared
                    await navigate(A)
                    await page.evaluate("""async ids => {
                        await open(ids.a,{revealLatest:false,readingTarget:{turn_id:ids.turn,item_id:ids.item}});
                        const node=nodes.get(ids.item);node.scrollIntoView({block:'start'});
                        DeskSessionReading.target();
                    }""", {'a': A, 'turn': PRIOR, 'item': MCP})
                    await frames(page)
                    assert await page.locator(f'#activity [data-item-id="{COMMAND}"] details').get_attribute('open') is None
                    assert not await page.evaluate('DeskSessionReading.follow()')
                    await page.locator('#latest-output').click()
                    await frames(page)
                    assert await page.evaluate('nearLatest() && DeskSessionReading.follow()')
                    desk.runtimes.pop(A).close()
                    await page.reload()
                    await page.wait_for_function('id => selected===id && !opening', arg=A)
                    await frames(page)
                    assert await page.evaluate('nearLatest() && DeskSessionReading.follow()')
                    assert local_preparation() == prepared
                    report['namespace_intent'] = {'before': c_before, 'after': c_after,
                        'held_response_completed': True, 'held_response_status': namespace_response.status}
                    await checkpoint('cold-namespace-latency-current-c-source-target-and-explicit-latest-win')

                    # Missing captured triple identity cannot use an equal item
                    # ID in a later native turn as the remembered source.
                    await page.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
                    await page.evaluate("""id => {
                        const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=283;
                        window.scrollTo({top:scrollY+node.getBoundingClientRect().top+30,behavior:'instant'});
                    }""", COMMAND)
                    await frames(page)
                    captured = await page.evaluate('DeskSessionReading.capture()')
                    assert captured['anchor']['turn_id'] == PRIOR and captured['anchor']['item_id'] == COMMAND
                    original = next(item for item in threads[A]['turns'][0]['items'] if item['id'] == COMMAND)
                    threads[A]['turns'][0]['items'] = [item for item in threads[A]['turns'][0]['items'] if item['id'] != COMMAND]
                    threads[A]['turns'][1]['items'].append(copy.deepcopy(original))
                    desk.runtimes.pop(A).close()
                    await page.reload()
                    await page.wait_for_function('id => selected===id && !opening', arg=A)
                    await frames(page)
                    assert 'Previous reading place unavailable' in await page.locator('#latest-output').inner_text()
                    assert not await page.evaluate('DeskSessionReading.follow()')
                    assert await page.locator(f'#activity [data-item-id="{COMMAND}"]').get_attribute('data-turn-id') == LIVE
                    assert await page.locator(f'#activity [data-item-id="{COMMAND}"] details').get_attribute('open') is None
                    assert await page.locator(f'#activity [data-item-id="{COMMAND}"] pre').evaluate('node => node.scrollTop') == 0
                    assert local_preparation() == prepared
                    report['missing_source'] = {'captured': captured, 'current_turn': LIVE}
                    await checkpoint('cold-missing-exact-anchor-does-not-borrow-equal-later-turn-item')
                else:
                    await navigate(B)
                    await page.get_by_label('B native answer — What check should remain?').fill(ANSWER)
                    await page.get_by_label('B native choice — Which scope?').select_option(CHOICE)
                    await navigate(A)
                    returned = await state()
                    same_reading(baseline, returned)
                    assert returned['pendingB'] == {'B-answer': ANSWER, 'B-choice': CHOICE}
                    assert local_preparation() == prepared
                    assert desk.runtimes[B].approvals['801'] == question
                    report['original_return'] = {'before': baseline, 'after': returned}
                    await checkpoint('a-b-a-exact-item-disclosures-pre-scroll-viewport-and-own-answers')

                    event = {'method': 'item/started', 'params': {'threadId': threads[A]['id'], 'turnId': LIVE,
                        'item': agent('A-new-native-output', 'New native output waits below the reviewed evidence.')}}
                    desk.store.event(A, event)
                    sequence = desk.store.events(A)[-1]['seq']
                    await page.wait_for_function('sequence => after>=sequence', arg=sequence)
                    await frames(page)
                    updated = await state()
                    same_reading(returned, updated)
                    assert await page.locator('#latest-output').inner_text() != 'Latest output ↓'
                    assert await page.locator('#activity [data-item-id="A-new-native-output"]').count() == 1
                    assert local_preparation() == prepared
                    report['native_update'] = {'before': returned, 'after': updated}
                    await checkpoint('new-native-output-keeps-reading-place-until-explicit-latest')

                    await page.locator('#latest-output').click()
                    await frames(page)
                    assert await page.evaluate('nearLatest() && DeskSessionReading.follow()')
                    await navigate(B)
                    assert await page.get_by_label('B native answer — What check should remain?').input_value() == ANSWER
                    assert await page.get_by_label('B native choice — Which scope?').input_value() == CHOICE
                    await navigate(A)
                    assert await page.evaluate('nearLatest() && DeskSessionReading.follow()')
                    assert local_preparation() == prepared
                    await checkpoint('explicit-latest-intent-survives-ordinary-task-return')

                    await navigate(B)
                    entered, release = threading.Event(), threading.Event()
                    holds[A] = (entered, release)
                    button = page.locator(f'.session-row[data-session="{A}"] .session')
                    await button.evaluate('node => node.focus({preventScroll:true})')
                    await button.press('Enter')
                    assert await asyncio.to_thread(entered.wait, 12), 'Original A open did not enter its hold'
                    await navigate(C)
                    await page.locator('#prompt').fill(C_DRAFT)
                    await page.wait_for_function('value => draftSaved.get(selected)?.text===value', arg=C_DRAFT)
                    c_view = await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                    release.set()
                    holds.pop(A)
                    await page.wait_for_timeout(400)
                    await frames(page)
                    after_c = await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                    assert after_c == c_view, (c_view, after_c)
                    assert local_preparation() == prepared
                    await checkpoint('held-original-a-open-cannot-replace-newer-c-draft-or-view')

                assert followup_snapshot(desk.store, A) == original_queue
                assert {path.name: path.read_bytes() for path in home.iterdir()} == settings
                assert not errors, errors
                assert not [call for call in calls if call['method'] in ('turn/start', 'turn/interrupt', 'turn/steer')]
                prohibited = [request for request in http if request['method'] == 'POST' and request['path'] in (
                    '/api/turn', '/api/followups/send', '/api/answer', '/api/approval', '/api/steer', '/api/stop')]
                assert not prohibited, prohibited
                report.update(passed=True, javascript_errors=errors, native_calls=calls, native_admissions=0, response_posts=prohibited,
                              retained_preparation=prepared, http_requests=http)
            except Exception:
                report['traceback'] = traceback.format_exc()
                report['javascript_errors'] = errors
                report['native_calls'] = calls
                await page.screenshot(path=str(evidence / f'{width}-failure.png'))
            finally:
                for _, release in holds.values():
                    release.set()
                if 'release' in locals():
                    release.set()
                await context.close()
                server.shutdown()
                server.server_close()
                worker.join(timeout=5)
                desk.close()
                desk.store.db.close()
        (evidence / f'{width}.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
        return report


async def main():
    scratch = Path(os.environ['DESK_TEST_TEMP']).resolve()
    evidence = Path(os.environ['DESK_TEST_EVIDENCE']).resolve()
    scratch.mkdir(parents=True, exist_ok=True)
    evidence.mkdir(parents=True, exist_ok=True, mode=0o700)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'), headless=True,
            args=['--no-sandbox', '--disable-dev-shm-usage'])
        try:
            records = [await one(browser, width, scratch, evidence, cold='--cold' in sys.argv) for width in (1250, 390)]
        finally:
            await browser.close()
    summary = {'result': 'PASS' if all(row['passed'] for row in records) else 'FAIL', 'version': codex_desk.__version__,
               'package': str(Path(codex_desk.__file__).resolve()), 'widths': [1250, 390], 'results': records}
    (evidence / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({key: summary[key] for key in ('result', 'version', 'package', 'widths')}), flush=True)
    if summary['result'] != 'PASS':
        for row in records:
            if not row['passed']:
                print(row.get('traceback', ''), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    asyncio.run(main())
