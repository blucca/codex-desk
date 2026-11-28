#!/usr/bin/env python3
"""Exercise captured linked-agent original reading and exact parent passage return.

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
B_DRAFT = 'B independent unsent Plan must retain two paused instructions.'


async def frames(page):
    await page.evaluate('() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)))')
    await page.wait_for_function("!opening && !sessionReadingPending")


async def one(browser, width, scratch, evidence):
    report = {'width': width, 'passed': False, 'checks': []}
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
        CHILD, CHILD2, LINK = 'native-A-child', 'native-A-second-child', 'A-native-collaboration'
        child_lines = '\n'.join(f'Child original line {n:04d} — Café 项目 🌱 exact supplied command evidence.' for n in range(1600))
        linked_threads = {child: {'id': child, 'name': 'Captured linked agent original '+child,
            'cwd': str(folder/'removed-child-project'), 'modelProvider': 'fixture', 'turns': [{'id': child+'-turn', 'status': 'failed',
            'error': {'message': 'Reported child failure remains a native source fact.'}, 'items': [
                {'id': child+'-command', 'type': 'commandExecution', 'command': 'fixture inspect child original', 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': child_lines},
                agent(child+'-response', 'Child original commentary stays separate from parent completion.')]}]} for child in (CHILD, CHILD2)}
        collaboration = next(item for item in threads[A]['turns'][0]['items'] if item['id'] == LINK)
        collaboration['agentsStates'][CHILD]['message'] = '\n'.join(f'Parent retained agent-result line {n:04d}.' for n in range(700))
        child_holds, child_errors, namespace_override = {}, set(), [None]
        question = {'id': 801, 'method': 'item/tool/requestUserInput', 'params': {
            'threadId': threads[B]['id'], 'turnId': 'B-native-turn', 'itemId': 'B-native-question', 'questions': [
                {'id': 'B-answer', 'header': 'B native answer', 'question': 'What check should remain?', 'isOther': True},
                {'id': 'B-choice', 'header': 'B native choice', 'question': 'Which scope?', 'isOther': False,
                 'options': [{'label': CHOICE, 'description': 'Retain the existing check'}, {'label': 'Different scope', 'description': 'Separate next work'}]}
            ]}}
        calls, http, errors, holds = [], [], [], {}
        namespace_hold = [None]

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
                    identifier=params['threadId'];calls[-1]['thread']=identifier
                    if identifier in child_errors:raise RuntimeError('Captured linked native source is unavailable.')
                    originals={**{thread['id']:thread for thread in threads.values()},**linked_threads}
                    if identifier not in originals:raise RuntimeError('Captured linked native source is missing.')
                    result={'thread':copy.deepcopy(originals[identifier])}
                    held=child_holds.get(identifier)
                    if held:
                        entered,release=held;entered.set();assert release.wait(30),'Linked original hold was not released'
                    return result
                raise AssertionError('Unexpected native request: ' + method)

            def turn(self, *args, **kwargs):
                raise AssertionError('Reading must not admit a native task')

            def answer(self, *args, **kwargs):
                raise AssertionError('Reading must not send native answers')

            def approve(self, *args, **kwargs):
                raise AssertionError('Reading must not respond to a native approval')

            def close(self):
                self.process.poll = lambda: 0

        class ControlledReader:
            def __init__(self, binary, native_home, cwd):
                assert binary == 'never-executed' and Path(native_home) == home
                self.id = 'native-original-reader'
                self.process = SimpleNamespace(poll=lambda: None)
                self.closing = False

            def request(self, method, params, timeout=30):
                assert method == 'thread/read' and params.get('includeTurns') is True
                return ControlledRuntime.request(self, method, params)

            def close(self):
                self.closing = True
                self.process.poll = lambda: 0

        original_open = desk_server.Desk.open
        original_namespace = desk_server.Desk.native_home_namespace
        original_events = desk_server.Store.events
        events_hold = [None]
        held_event_releases = []

        def controlled_events(store, identifier, after=0):
            result = original_events(store, identifier, after)
            held = events_hold[0]
            if held and identifier == A and after >= held[0] and result:
                events_hold[0] = None
                _, entered, release = held
                entered.set()
                held_event_releases.append(release)
                assert release.wait(30), 'Held events response was not released'
            return result

        def controlled_namespace(desk):
            held = namespace_hold[0]
            if held:
                entered, release = held
                entered.set()
                assert release.wait(30), 'Held native home namespace was not released'
            return namespace_override[0] or original_namespace(desk)

        def controlled_open(desk, identifier):
            result = original_open(desk, identifier)
            held = holds.get(identifier)
            if held:
                entered, release = held
                entered.set()
                assert release.wait(30), 'Held original open was not released'
            return result

        with patch.object(desk_server, '_NativeReader', ControlledReader), patch.object(desk_server, 'Runtime', ControlledRuntime), patch.object(desk_server.Desk, 'open', controlled_open), patch.object(desk_server.Desk, 'native_home_namespace', controlled_namespace), patch.object(desk_server.Store, 'events', controlled_events):
            desk = desk_server.Desk('never-executed', home, state_dir)
            for session, project in projects.items():
                desk.store.create(str(project), 'default', identifier=session, name=threads[session]['name'])
                desk.store.update(session, thread_id=threads[session]['id'], thread_saved=1, status='saved', name_pending=0)
            saved = load_draft(desk.store, A)
            save_draft(desk.store, A, DRAFT, 'plan', saved['revision'])
            add_followup(desk.store, A, 'A first queued instruction — keep paused.', 'native')
            add_followup(desk.store, A, 'A second queued instruction — keep Plan.', 'plan')
            b_saved = load_draft(desk.store, B)
            save_draft(desk.store, B, B_DRAFT, 'plan', b_saved['revision'])
            add_followup(desk.store, B, 'B first independent queued instruction.', 'native')
            add_followup(desk.store, B, 'B second independent queued Plan.', 'plan')
            desk.store.event(A, {'method': 'item/completed', 'params': {'threadId': threads[A]['id'],
                'turnId': PRIOR, 'item': copy.deepcopy(threads[A]['turns'][0]['items'][2])}})
            desk.store.event(A, {'method': 'turn/started', 'params': {'threadId': threads[A]['id'],
                'turn': {'id': LIVE, 'status': 'inProgress'}}})
            initial_seq = original_events(desk.store, A)[-1]['seq']
            original_queue = followup_snapshot(desk.store, A)
            original_b_queue = followup_snapshot(desk.store, B)
            server = desk_server.ThreadingHTTPServer(('127.0.0.1', 0), desk_server.handler(desk))
            worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': 0.01}, daemon=True)
            worker.start()
            context = await browser.new_context(viewport={'width': width, 'height': 900 if width == 1250 else 844})
            page = await context.new_page()
            await page.add_init_script('''const fixtureRequestFrame=globalThis.requestAnimationFrame;
                globalThis.requestAnimationFrame=callback=>{if(globalThis.fixtureCaptureNextFrame){globalThis.fixtureCaptureNextFrame=false;globalThis.fixtureLatestFrame=callback;return -1;}
                    return fixtureRequestFrame.call(globalThis,callback);};''')
            await context.grant_permissions(['clipboard-read','clipboard-write'])
            page.set_default_timeout(12_000)
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: http.append({'path': urlsplit(request.url).path, 'method': request.method}))

            def local_preparation():
                with desk.store.lock:
                    return {session: {'draft': dict(load_draft(desk.store, session)), 'queue': copy.deepcopy(followup_snapshot(desk.store, session))} for session in (A, B)}

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

            async def review_state():
                return await page.evaluate('''() => {
                    const raw=localStorage.getItem(DeskNewActivity.STORAGE_KEY),value=raw?JSON.parse(raw):null;
                    const saved=value?.reviews.find(row=>row.owner.session===selected && row.owner.thread_id===nativeThreadId);
                    const capture=DeskNewActivityView.snapshot();
                    return {selected,thread:nativeThreadId,reviewed:saved?.reviewed_seq ?? null,raw,value,
                        readingIntent:DeskSessionReading.intent(),follow:DeskSessionReading.follow(),nearLatest:nearLatest(),
                        status:$('native-activity-status').textContent,firstDisabled:$('native-activity-first').disabled,
                        markDisabled:$('native-activity-mark').disabled,capture,
                        pending:capture?DeskNewActivity.pending(capture.owner,capture.batch,saved.reviewed_seq):null};
                }''')

            async def consume_through(sequence):
                await page.wait_for_function('sequence => after>=sequence', arg=sequence)
                await frames(page)

            def emit(event):
                desk.store.event(A, event)
                return original_events(desk.store, A)[-1]['seq']

            def material(identifier, text, turn=LIVE):
                item=agent(identifier, text)
                target=next(row for row in threads[A]['turns'] if row['id']==turn)
                target['items'].append(copy.deepcopy(item))
                return emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':turn,'item':item}})

            async def hold_one_frame(action):
                # Hold only the actual controller's one queued Latest-review frame,
                # not Chromium's animation loop or the application's other frames.
                await page.evaluate('''() => {const original=DeskNewActivityView.reviewLatest;
                    globalThis.fixtureLatestOriginal=original;
                    DeskNewActivityView.reviewLatest=capture=>{globalThis.fixtureLatestFrame=null;
                        globalThis.fixtureCaptureNextFrame=true;return original(capture);};}
                ''')
                await action()
                assert await page.evaluate('typeof fixtureLatestFrame === "function"')
                await page.evaluate('DeskNewActivityView.reviewLatest=fixtureLatestOriginal')

            async def release_frame():
                await page.evaluate('''() => {const callback=fixtureLatestFrame;fixtureLatestFrame=null;callback(performance.now());}''')
                await frames(page)

            async def parent_view():
                return await page.evaluate('''ids=>{const node=nodes.get(ids.link),pre=node.querySelector('pre'),pending=interactionCards.get(ids.b)?.get('801');
                    return {session:selected,thread:nativeThreadId,turn:node.dataset.turnId,item:node.dataset.itemId,
                        preTop:pre.scrollTop,screenTop:node.getBoundingClientRect().top,windowTop:scrollY,
                        groupOpen:collaborationGroups.get(ids.turn).node.open,draft:$('prompt').value,mode:$('turn-mode').value,
                        bAnswers:pending?Object.fromEntries([...pending.fields].map(([key,input])=>[key,input.value])):null};}''',{'link':LINK,'turn':PRIOR,'b':B})

            async def exact_return(before):
                await page.locator('#history-reader-back').click();await frames(page)
                after=await parent_view()
                assert after==before,(before,after)
                assert await page.evaluate('''ids=>document.activeElement===Array.from(nodes.get(ids.link).querySelectorAll('.linked-agent-original')).find(button=>button.dataset.childThread===ids.child)''',{'link':LINK,'child':CHILD})
                assert local_preparation()==prepared
                assert (await review_state())['reviewed']==initial_seq

            async def activate_linked(selector):
                button = page.locator(selector)
                await button.evaluate('node=>node.focus({preventScroll:true})')
                await button.press('Enter')

            async def read_child():
                button=page.locator(f'#activity [data-item-id="{LINK}"] .linked-agent-original[data-child-thread="{CHILD}"]')
                await button.evaluate('node=>node.focus({preventScroll:true})');await button.press('Enter')
                await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                assert CHILD in await page.locator('#history-reader-binding').inner_text()
                assert await page.locator('#history-reader-back').inner_text()=='Return to parent activity'

            def reads():return sum(call['method']=='thread/read' and call.get('thread')==CHILD for call in calls)

            def publish_collaboration():
                return emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'item':copy.deepcopy(collaboration)}})

            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function('state.sessions.length===3 && !!globalThis.DeskLinkedAgentView')
                await navigate(B)
                await page.get_by_label('B native answer — What check should remain?').fill(ANSWER)
                await page.get_by_label('B native choice — Which scope?').select_option(CHOICE)
                await navigate(A)
                await page.wait_for_function('!!DeskLinkedAgentView.state().catalog && !!sessionReadingHomeValue')
                initial_seq=(await review_state())['reviewed'];prepared=local_preparation()
                assert (await review_state())['capture'] is None
                collaboration['agentsStates'][CHILD]['message']+='\nNEW parent collaboration result links its exact reported native child.'
                sequence=publish_collaboration();await consume_through(sequence)
                assert (await review_state())['pending']['first']['item_id']==LINK
                await page.locator('#native-activity-first').click();await frames(page)
                assert await page.evaluate('id=>document.activeElement===nodes.get(id)',LINK)
                await page.evaluate('''id=>{const node=nodes.get(id);node.querySelector('pre').scrollTop=217;
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});}''',LINK)
                await frames(page)
                before=await parent_view();assert before['preTop']==217 and before['groupOpen']
                assert before['bAnswers']=={'B-answer':ANSWER,'B-choice':CHOICE}
                assert not (folder/'removed-child-project').exists()
                await checkpoint('first-new-parent-item-offers-only-reported-linked-original')

                count=reads();sql_before=list(desk.store.db.iterdump())
                await read_child();assert reads()==count+1
                assert not await page.locator('#history-reader button').filter(has_text='Run task').count()
                child_item=page.locator(f'#history-reader-body [data-item-id="{CHILD}-command"]')
                await child_item.locator('summary').click()
                assert 'Child original line 0000' in await child_item.inner_text()
                await child_item.get_by_role('button',name='Copy full item text',exact=True).click()
                copied=await page.evaluate('navigator.clipboard.readText()')
                expected='Command\nfixture inspect child original\nStatus: completed\nExit: 0\n'+child_lines
                assert copied==expected,(len(copied),len(expected))
                assert 'Child original line 1599' in copied and reads()==count+1
                assert list(desk.store.db.iterdump())==sql_before
                await exact_return(before)
                await checkpoint('one-scoped-get-full-child-copy-and-exact-parent-return-b-plan-queues-answers')

                child_errors.add(CHILD);await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-original')
                await page.wait_for_function('DeskLinkedAgentView.state().reading.failed')
                assert not await page.locator('#history-reader').evaluate('node=>node.open')
                assert local_preparation()==prepared and (await review_state())['reviewed']==initial_seq
                child_errors.clear();await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-retry')
                await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                await exact_return(before)
                await checkpoint('missing-child-keeps-captured-target-retry-and-parent-reading')

                await read_child()
                await page.locator('#history-reader-find-query').fill('Child original line 1300')
                await page.locator('#history-reader-find-submit').click()
                await page.wait_for_function("$('history-reader-find-status').textContent.includes('Match 1 of 1')")
                window_before=await page.locator('#history-reader-body').inner_text()
                count=reads();namespace_override[0]='b'*64
                await page.locator('#history-reader-refresh').click()
                await page.wait_for_function("$('history-reader-status').textContent.includes('Refresh failed')")
                assert await page.locator('#history-reader-body').inner_text()==window_before
                assert reads()==count
                namespace_override[0]=None;await page.locator('#history-reader-retry').click()
                await page.wait_for_function("$('history-reader-status').textContent.includes('Original refreshed')")
                assert reads()==count+1
                assert '1300' in await page.locator('#history-reader-body').inner_text()
                await exact_return(before)
                await checkpoint('explicit-refresh-retry-stays-home-scoped-retains-child-window-parent-return')

                entered,release=threading.Event(),threading.Event();child_holds[CHILD]=(entered,release)
                await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-original')
                assert await asyncio.to_thread(entered.wait,12)
                await navigate(C);await page.locator('#prompt').fill(C_DRAFT)
                await page.wait_for_function('text=>draftSaved.get(selected)?.text===text',arg=C_DRAFT)
                c_before=await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                release.set();child_holds.clear();await page.wait_for_timeout(150);await frames(page)
                assert await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")==c_before
                assert not await page.locator('#history-reader').evaluate('node=>node.open')
                await navigate(A);assert local_preparation()==prepared
                before=await parent_view()
                await checkpoint('held-child-response-cannot-replace-new-c-source-editor-viewport')

                entered,release=threading.Event(),threading.Event();child_holds[CHILD]=(entered,release)
                await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-original')
                assert await asyncio.to_thread(entered.wait,12)
                await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-cancel')
                release.set();child_holds.clear();await page.wait_for_timeout(150);await frames(page)
                assert not await page.locator('#history-reader').evaluate('node=>node.open')
                after_cancel=await parent_view()
                assert after_cancel==before,(before,after_cancel)
                await checkpoint('cancelled-captured-read-cannot-open-on-late-source')

                entered,release=threading.Event(),threading.Event();child_holds[CHILD]=(entered,release)
                await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-original')
                assert await asyncio.to_thread(entered.wait,12)
                collaboration['receiverThreadIds']=[CHILD2];collaboration['agentsStates']={CHILD2:{'status':'completed','message':'Different explicitly reported child.'}}
                sequence=publish_collaboration();await consume_through(sequence)
                release.set();child_holds.clear();await page.wait_for_function('DeskLinkedAgentView.state().reading.failed')
                assert not await page.locator('#history-reader').evaluate('node=>node.open')
                assert 'relationship_unavailable' in await page.locator(f'#activity [data-item-id="{LINK}"] .linked-agent-status').inner_text()
                collaboration['receiverThreadIds']=[CHILD];collaboration['agentsStates']={CHILD:{'status':'completed','message':'Restored actual parent relationship.'}}
                sequence=publish_collaboration();await consume_through(sequence)
                await activate_linked(f'#activity [data-item-id="{LINK}"] .linked-agent-retry')
                await page.wait_for_function("$('history-reader').open&&$('history-reader-body').getAttribute('aria-busy')==='false'")
                # The earlier captured item view is restored, even after native relationship changes.
                await page.locator('#history-reader-back').click();await frames(page)
                assert local_preparation()==prepared and (await review_state())['reviewed']==initial_seq
                await checkpoint('fresh-parent-relationship-change-defeats-held-child-original-and-retry-remains-exact')

                # A cached collab replay must not reconstruct a removed fresh parent item.
                threads[A]['turns'][0]['items']=[item for item in threads[A]['turns'][0]['items'] if item['id']!=LINK]
                threads[A]['turns'][1]['items'].append(copy.deepcopy(collaboration))
                desk.runtimes.pop(A).close();await page.evaluate('id=>open(id,{revealLatest:false})',A);await frames(page)
                assert await page.locator(f'#activity [data-item-id="{LINK}"] .linked-agent-original').count()==0
                await page.locator(f'#activity [data-item-id="{LINK}"]').locator('xpath=ancestor::details[1]').locator('summary').click()
                assert 'unavailable' in await page.locator(f'#activity [data-item-id="{LINK}"] .linked-agent-status').inner_text()
                assert local_preparation()==prepared and (await review_state())['reviewed']==initial_seq
                await checkpoint('fresh-moved-parent-item-cached-replay-never-recreates-linked-source')

                assert not errors,errors
                prohibited=[request for request in http if request['method']=='POST' and request['path'] in
                    ['/api/turn','/api/followups/send','/api/answer','/api/approval','/api/steer','/api/stop']]
                assert not prohibited,prohibited
                assert all(call.get('session') in (A,B,C) for call in calls if call['method']=='thread/resume')
                assert {path.name:path.read_bytes() for path in home.iterdir()}==settings
                report.update(passed=True,javascript_errors=errors,native_calls=calls,native_admissions=0,
                    response_posts=prohibited,retained_preparation=prepared,http_requests=http,initial_child_read_count=1,
                    full_child_copy_characters=len(copied))
            except Exception:
                report['traceback']=traceback.format_exc()
                report['javascript_errors']=errors
                report['native_calls']=calls
                report['http_requests']=http
                report['linked_state']=await page.evaluate('DeskLinkedAgentView.state()')
                report['linked_notices']=await page.locator('.linked-agent-status').all_text_contents()
                await page.screenshot(path=str(evidence/f'{width}-failure.png'))
            finally:
                for _,release in child_holds.values():release.set()
                for _,release in holds.values():release.set()
                if namespace_hold[0]:namespace_hold[0][1].set()
                if events_hold[0]:events_hold[0][2].set()
                for release in held_event_releases:release.set()
                await context.close()
                server.shutdown();server.server_close();worker.join(timeout=5)
                desk.close();desk.store.db.close()
        (evidence/f'{width}.json').write_text(json.dumps(report,indent=2,ensure_ascii=False)+'\n')
        return report


async def main():
    scratch=Path(os.environ['DESK_TEST_TEMP']).resolve()
    evidence=Path(os.environ['DESK_TEST_EVIDENCE']).resolve()
    scratch.mkdir(parents=True,exist_ok=True);evidence.mkdir(parents=True,exist_ok=True,mode=0o700)
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(executable_path=os.environ.get('DESK_CHROMIUM'),headless=True,
            args=['--no-sandbox','--disable-dev-shm-usage'])
        try:records=[await one(browser,width,scratch,evidence) for width in (1250,390)]
        finally:await browser.close()
    summary={'result':'PASS' if all(row['passed'] for row in records) else 'FAIL','version':codex_desk.__version__,
             'package':str(Path(codex_desk.__file__).resolve()),'widths':[1250,390],'results':records}
    (evidence/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({key:summary[key] for key in ('result','version','package','widths')}),flush=True)
    if summary['result']!='PASS':
        for row in records:
            if not row['passed']:print(row.get('traceback',''),flush=True)
        raise SystemExit(1)


if __name__=='__main__':asyncio.run(main())
