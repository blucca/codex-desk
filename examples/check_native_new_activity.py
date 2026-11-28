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
            return original_namespace(desk)

        def controlled_open(desk, identifier):
            result = original_open(desk, identifier)
            held = holds.get(identifier)
            if held:
                entered, release = held
                entered.set()
                assert release.wait(30), 'Held original open was not released'
            return result

        with patch.object(desk_server, 'Runtime', ControlledRuntime), patch.object(desk_server.Desk, 'open', controlled_open), patch.object(desk_server.Desk, 'native_home_namespace', controlled_namespace), patch.object(desk_server.Store, 'events', controlled_events):
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

            try:
                await page.goto(f'http://127.0.0.1:{server.server_port}')
                await page.wait_for_function('state.sessions.length===3 && !!globalThis.DeskNewActivityView')
                await navigate(A)
                await page.wait_for_function('''() => {const value=JSON.parse(localStorage.getItem(DeskNewActivity.STORAGE_KEY)||'null');
                    return value?.reviews.some(row=>row.owner.session===selected && row.owner.thread_id===nativeThreadId);}''')
                initial=await review_state()
                assert initial['reviewed']==original_events(desk.store,A)[-1]['seq'] and initial['firstDisabled'] and initial['markDisabled'], initial
                initial_seq=initial['reviewed']
                assert initial['capture'] is None
                prepared=local_preparation()
                await checkpoint('first-successful-owned-attach-seeds-backlog-once')

                # Manual reading stays at an earlier source while native material
                # updates that existing item. Unrelated native event traffic is not
                # a reviewable item and does not advance the material frontier.
                await page.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
                await page.locator(f'#activity [data-item-id="{MCP}"] summary').click()
                await page.evaluate('''id => {const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=283;
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});}''',COMMAND)
                await frames(page)
                baseline=await state()
                command=next(item for item in threads[A]['turns'][0]['items'] if item['id']==COMMAND)
                command['aggregatedOutput']+='\nNew material updates the earlier exact native command.'
                first_seq=emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'item':copy.deepcopy(command)}})
                ignored=[
                    {'method':'item/completed','params':{'threadId':'native-owned-child','turnId':'child-turn','item':agent('child-answer','Owned child must not be the selected parent.')}},
                    {'method':'thread/name/updated','params':{'threadId':threads[A]['id'],'threadName':'Fixture native status-only title'}},
                    {'method':'thread/tokenUsage/updated','params':{'threadId':threads[A]['id'],'tokenUsage':{'total':{'totalTokens':22}}}},
                    {'id':990,'method':'item/tool/requestUserInput','params':{'threadId':threads[A]['id'],'turnId':LIVE,'itemId':'A-approval-only','questions':[]}},
                    {'method':'serverRequest/resolved','params':{'threadId':threads[A]['id'],'requestId':990}},
                    {'method':'item/plan/delta','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'itemId':'missing-final-plan','delta':'Must be dropped by current plan render gate.'}},
                    {'method':'desk/nativeTaskSnapshot','params':{'threadId':threads[A]['id'],'turnId':LIVE}},
                ]
                for event in ignored:last_seq=emit(event)
                await consume_through(last_seq)
                pending=await review_state()
                controls=await page.evaluate('''() => {const ids=['activity-controls','native-activity-status','latest-output','native-activity-first','native-activity-mark'];
                    return Object.fromEntries(ids.map(id=>{const n=$(id),r=n.getBoundingClientRect(),s=getComputedStyle(n);return [id,{left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:r.width,height:r.height,background:s.backgroundColor,position:s.position,display:s.display}];}));}''')
                panel=controls['activity-controls'];status=controls['native-activity-status']
                assert panel['left']>=0 and panel['right']<=width and panel['top']>=0 and panel['bottom']<= (900 if width==1250 else 844),controls
                assert panel['background'] not in ('rgba(0, 0, 0, 0)','transparent'),controls
                assert status['top']>=controls['latest-output']['bottom'] and status['bottom']<=controls['native-activity-first']['top'],controls
                for identifier in ('latest-output','native-activity-first','native-activity-mark'):
                    assert controls[identifier]['left']>=panel['left'] and controls[identifier]['right']<=panel['right'],controls
                report['controls_geometry']=controls
                assert pending['reviewed']==initial_seq and pending['pending']['frontier']==first_seq, pending
                assert [(row['turn_id'],row['item_id']) for row in pending['pending']['targets']]==[(PRIOR,COMMAND)], pending
                current=await state()
                for field in ('windowTop','command','mcp','draft','mode'):
                    assert current[field]==baseline[field], (field,baseline,current)
                assert local_preparation()==prepared
                await checkpoint('manual-reading-earlier-command-update-ignores-child-status-approval-and-dropped-plan')

                await navigate(B)
                assert await page.locator('#prompt').input_value()==B_DRAFT
                assert await page.locator('#turn-mode').input_value()=='plan'
                await page.get_by_label('B native answer — What check should remain?').fill(ANSWER)
                await page.get_by_label('B native choice — Which scope?').select_option(CHOICE)
                await navigate(A)
                assert (await review_state())['reviewed']==initial_seq
                # Read first must win over old reading and reveal the earlier
                # changed item's exact disclosure, not append/transcript order.
                later_seq=material('A-later-new-answer','Later new answer follows the earlier changed command.')
                await consume_through(later_seq)
                await page.locator('#native-activity-first').evaluate('node=>node.focus({preventScroll:true})')
                await page.locator('#native-activity-first').press('Enter')
                await frames(page)
                revealed=await state()
                assert revealed['command']['turn']==PRIOR and revealed['command']['open']
                assert abs(revealed['command']['screenTop'])<=1, revealed
                assert await page.evaluate('document.activeElement===nodes.get("A-native-command")')
                assert (await review_state())['reviewed']==initial_seq
                assert revealed['pendingB']=={'B-answer':ANSWER,'B-choice':CHOICE}, revealed
                assert local_preparation()==prepared
                await checkpoint('first-new-reveals-exact-updated-earlier-item-without-reviewing')

                # Review-boundary persistence and manual reading-place persistence
                # are separate browser documents with different whitelists.
                await page.evaluate('''id => {const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=283;
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top+30,behavior:'instant'});}''',COMMAND)
                await frames(page)
                before_cold=await state()
                desk.runtimes.pop(A).close()
                await page.reload()
                await page.wait_for_function('id=>selected===id && !opening',arg=A)
                await frames(page)
                after_cold=await state()
                assert after_cold['command']==before_cold['command'] and after_cold['windowTop']==before_cold['windowTop'], (before_cold,after_cold)
                cold=await review_state()
                assert cold['reviewed']==initial_seq and cold['pending']['first']['item_id']==COMMAND, cold
                raw=cold['raw'];saved=cold['value']
                assert set(saved)=={'version','reviews'} and len(saved['reviews'])<=100
                for entry in saved['reviews']:
                    assert set(entry)=={'owner','reviewed_seq'} and set(entry['owner'])=={'native_home','session','thread_id'}
                for secret in (DRAFT,B_DRAFT,ANSWER,CHOICE,command['aggregatedOutput'][:100],str(home)):
                    assert secret not in raw,secret
                assert local_preparation()==prepared
                report['cold']={'before':before_cold,'after':after_cold,'review':cold}
                await checkpoint('cold-review-sequence-and-manual-reading-anchor-retain-independently')

                # Exact fresh native catalog, not after=0 cached item replay, owns
                # the first-new destination. Keep replay intact while moving the ID.
                old_command=next(item for item in threads[A]['turns'][0]['items'] if item['id']==COMMAND)
                threads[A]['turns'][0]['items']=[item for item in threads[A]['turns'][0]['items'] if item['id']!=COMMAND]
                threads[A]['turns'][1]['items'].append(copy.deepcopy(old_command))
                desk.runtimes.pop(A).close()
                await page.evaluate('id=>open(id,{revealLatest:false})',A)
                await frames(page)
                await page.locator('#native-activity-first').click()
                assert 'unavailable' in await page.locator('#native-activity-status').inner_text()
                assert (await review_state())['reviewed']==initial_seq
                assert local_preparation()==prepared
                await checkpoint('missing-exact-fresh-triple-not-resurrected-by-cached-event-or-equal-other-turn')
                threads[A]['turns'][1]['items']=[item for item in threads[A]['turns'][1]['items'] if item['id']!=COMMAND]
                threads[A]['turns'][0]['items'].insert(2,copy.deepcopy(old_command))
                desk.runtimes.pop(A).close()
                await page.evaluate('id=>open(id,{revealLatest:false})',A)
                await frames(page)

                # The displayed aggregate is frozen while another actual events
                # response is held. Mark does not review material not yet displayed.
                mark_before=await review_state()
                entered,release=threading.Event(),threading.Event()
                events_hold[0]=(last_seq,entered,release)
                held_seq=material('A-held-after-mark','New source delivered only after the captured displayed mark.')
                assert await asyncio.to_thread(entered.wait,12),'Events response never entered hold'
                await page.locator('#native-activity-mark').evaluate('node=>node.focus({preventScroll:true})')
                await page.locator('#native-activity-mark').press('Enter')
                marked=await review_state()
                assert marked['reviewed']==later_seq, (mark_before,marked)
                async with page.expect_response(lambda response:urlsplit(response.url).path=='/api/events') as held_response:
                    release.set()
                response=await held_response.value
                assert response.ok
                await response.json()
                await consume_through(held_seq)
                after_mark=await review_state()
                assert after_mark['reviewed']==later_seq and after_mark['pending']['first']['first_seq']==held_seq,after_mark
                await checkpoint('held-event-response-after-mark-remains-new-beyond-frozen-material-frontier')

                # Deliberate Latest is the only Latest review action. A late new
                # material item enters a later aggregate; automatic follow never marks.
                await hold_one_frame(lambda:page.locator('#latest-output').click())
                latest_capture=await review_state()
                newer_seq=material('A-new-during-latest-frame','Arrived after explicit Latest captured its displayed frontier.')
                await consume_through(newer_seq)
                before_latest_release=await review_state()
                await release_frame()
                after_latest=await review_state()
                report['explicit_latest']={'captured':latest_capture,'before_release':before_latest_release,'after':after_latest}
                assert after_latest['reviewed']==held_seq and after_latest['pending']['first']['first_seq']==newer_seq,after_latest
                assert await page.evaluate('nearLatest() && DeskSessionReading.follow()')
                auto_seq=material('A-automatic-follow-item','Automatic following must retain its unreviewed boundary.')
                await consume_through(auto_seq)
                automatic=await review_state()
                assert automatic['reviewed']==held_seq and automatic['pending']['first']['first_seq']==newer_seq,automatic
                await checkpoint('explicit-latest-reviews-only-frozen-frontier-and-automatic-follow-never-marks')

                # Same-owner manual intent cancels the captured Latest frame;
                # a different selected task owns its own editor/source/viewport.
                await hold_one_frame(lambda:page.locator('#latest-output').click())
                await page.locator('#prompt').fill(DRAFT)
                await release_frame()
                assert (await review_state())['reviewed']==held_seq
                assert local_preparation()==prepared
                await hold_one_frame(lambda:page.locator('#latest-output').click())
                await page.evaluate('''id=>{DeskSessionReading.target();const node=nodes.get(id);
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});}''',COMMAND)
                await release_frame()
                assert (await review_state())['reviewed']==held_seq
                await hold_one_frame(lambda:page.locator('#latest-output').click())
                await navigate(C)
                await page.locator('#prompt').fill(C_DRAFT)
                await page.wait_for_function('text=>draftSaved.get(selected)?.text===text',arg=C_DRAFT)
                c_before=await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                await release_frame()
                c_after=await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                assert c_after==c_before,(c_before,c_after)
                await navigate(B)
                assert await page.locator('#prompt').input_value()==B_DRAFT
                assert await page.locator('#turn-mode').input_value()=='plan'
                # Cold page intentionally drops unsent native response editor state;
                # fresh B answers entered here remain independent through A/C returns.
                await page.get_by_label('B native answer — What check should remain?').fill(ANSWER)
                await page.get_by_label('B native choice — Which scope?').select_option(CHOICE)
                await navigate(A)
                assert (await review_state())['reviewed']==held_seq
                await navigate(C)
                await navigate(B)
                assert await page.get_by_label('B native answer — What check should remain?').input_value()==ANSWER
                assert await page.get_by_label('B native choice — Which scope?').input_value()==CHOICE
                assert local_preparation()==prepared
                assert followup_snapshot(desk.store,A)==original_queue
                assert followup_snapshot(desk.store,B)==original_b_queue
                assert desk.runtimes[B].approvals['801']==question
                await checkpoint('same-owner-manual-and-new-c-intents-defeat-late-latest-b-plan-queues-answers-retain')

                # A delayed native-open response is still A-owned after C wins.
                entered,release=threading.Event(),threading.Event()
                holds[A]=(entered,release)
                a_button=page.locator(f'.session-row[data-session="{A}"] .session')
                await a_button.evaluate('node=>node.focus({preventScroll:true})')
                await a_button.press('Enter')
                assert await asyncio.to_thread(entered.wait,12),'Held A open did not enter'
                await navigate(C)
                await page.locator('#prompt').fill(C_DRAFT)
                await page.wait_for_function('text=>draftSaved.get(selected)?.text===text',arg=C_DRAFT)
                held_c=await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                async with page.expect_response(lambda response:urlsplit(response.url).path=='/api/open') as open_response:
                    release.set()
                    holds.pop(A)
                response=await open_response.value
                assert response.ok
                await response.json()
                await frames(page)
                final_c=await page.evaluate("({selected,thread:nativeThreadId,text:$('activity').textContent,prompt:$('prompt').value,top:scrollY})")
                assert final_c==held_c,(held_c,final_c)
                await navigate(B)
                assert await page.get_by_label('B native answer — What check should remain?').input_value()==ANSWER
                assert await page.get_by_label('B native choice — Which scope?').input_value()==CHOICE
                assert local_preparation()==prepared
                await checkpoint('held-a-open-cannot-replace-new-c-source-editor-or-b-owned-preparation')

                assert {path.name:path.read_bytes() for path in home.iterdir()}==settings
                assert not errors,errors
                prohibited=[request for request in http if request['method']=='POST' and request['path'] in (
                    '/api/turn','/api/followups/send','/api/answer','/api/approval','/api/steer','/api/stop')]
                assert not prohibited,prohibited
                report.update(passed=True,javascript_errors=errors,native_calls=calls,native_admissions=0,
                              response_posts=prohibited,retained_preparation=prepared,http_requests=http)
            except Exception:
                report['traceback']=traceback.format_exc()
                report['javascript_errors']=errors
                report['native_calls']=calls
                await page.screenshot(path=str(evidence/f'{width}-failure.png'))
            finally:
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
