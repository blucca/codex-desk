#!/usr/bin/env python3
"""Exercise compact changed-work overview and its ordinary native-reading returns."""
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
                await page.wait_for_function('state.sessions.length===3 && !!globalThis.DeskChangedWorkView && !!globalThis.DeskNewActivityView')
                await navigate(A)
                await page.wait_for_function('''() => DeskNewActivityView.reviewMetadata().reviews.some(row=>row.owner.session===selected && row.owner.thread_id===nativeThreadId)''')
                initial=await review_state();initial_seq=initial['reviewed']
                assert initial_seq is not None and initial['firstDisabled'],initial
                await page.locator(f'#activity [data-item-id="{COMMAND}"] summary').click()
                await page.evaluate('''id=>{const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=283;
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top-145,behavior:'instant'});}''',COMMAND)
                await frames(page);anchor=await state()
                prepared=local_preparation()
                await navigate(B)
                assert await page.locator('#prompt').input_value()==B_DRAFT
                assert await page.locator('#turn-mode').input_value()=='plan'
                await page.get_by_label('B native answer — What check should remain?').fill(ANSWER)
                await page.evaluate("$('prompt').setSelectionRange(12,36,'backward')")
                b_before=await page.evaluate("({selected,thread:nativeThreadId,prompt:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection})")
                command=next(item for item in threads[A]['turns'][0]['items'] if item['id']==COMMAND)
                command['aggregatedOutput']+='\nChanged A command while B preparation remains independent.'
                first_seq=emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'item':copy.deepcopy(command)}})
                ignored=[
                    {'method':'item/completed','params':{'threadId':'native-owned-child','turnId':'child-turn','item':agent('child-only','Not parent material')}},
                    {'method':'thread/tokenUsage/updated','params':{'threadId':threads[A]['id'],'tokenUsage':{'total':{'totalTokens':99}}}},
                    {'method':'turn/diff/updated','params':{'threadId':threads[A]['id'],'turnId':LIVE,'diff':'Native aggregate is separate'}},
                    {'id':990,'method':'item/tool/requestUserInput','params':{'threadId':threads[A]['id'],'turnId':LIVE,'itemId':'question-only','questions':[]}},
                    {'method':'item/plan/delta','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'itemId':'absent-streaming-plan','delta':'Dropped stale plan'}},
                    {'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':LIVE,'item':agent('empty-answer',' \u00a0 ')}},
                    {'method':'desk/nativeTaskSnapshot','params':{'threadId':threads[A]['id'],'turn':{'id':LIVE,'status':'completed'}}},
                ]
                http_at=len(http)
                for event in ignored:last_seq=emit(event)
                await page.evaluate('refresh()');await frames(page)
                metadata=await page.evaluate('state.native_material')
                compact=next(row for row in metadata['summaries'] if row['owner']['session']==A)
                assert compact['material_seq']==first_seq and compact['received_seq']==last_seq,compact
                assert len(await page.locator(f'.session-row[data-session="{A}"] .native-material-dot').all())==1
                assert await page.locator(f'.session-row[data-session="{B}"] .native-material-dot').count()==0
                assert await page.locator(f'.session-row[data-session="{C}"] .native-material-dot').count()==0
                b_after=await page.evaluate("({selected,thread:nativeThreadId,prompt:$('prompt').value,mode:$('turn-mode').value,start:$('prompt').selectionStart,end:$('prompt').selectionEnd,direction:$('prompt').selectionDirection})")
                assert b_after==b_before,(b_before,b_after)
                assert local_preparation()==prepared
                assert not [request for request in http[http_at:] if request['path']=='/api/open'],http[http_at:]
                await checkpoint('background-a-material-only-dot-keeps-b-plan-two-queues-answer-and-caret')

                review_before=await page.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())')
                changes=desk.store.db.total_changes
                await page.locator('#show-changed-work').click()
                await page.wait_for_function("$('changed-work').open")
                rows=page.locator('#changed-work-list .changed-work-row')
                assert await rows.count()==2
                assert await page.locator(f'#changed-work-list [data-session="{A}"]').count()==1
                assert await page.locator(f'#changed-work-list [data-session="{B}"]').count()==1
                assert '1 changed' in await page.locator('#changed-work-status').inner_text()
                assert '1 without a review baseline' in await page.locator('#changed-work-status').inner_text()
                geometry=await page.locator('#changed-work').evaluate('node=>{const r=node.getBoundingClientRect();return {left:r.left,right:r.right,top:r.top,bottom:r.bottom,width:innerWidth,height:innerHeight};}')
                assert geometry['left']>=0 and geometry['right']<=geometry['width'] and geometry['top']>=0 and geometry['bottom']<=geometry['height'],geometry
                report['overview_geometry']=geometry
                await page.locator('#changed-work-mode').select_option('all')
                assert await page.locator(f'#changed-work-list [data-session="{C}"]').count()==1
                assert 'Review baseline unavailable' in await page.locator(f'#changed-work-list [data-session="{C}"]').inner_text()
                value=await page.locator('#changed-work-project').evaluate('''(node,path)=>Array.from(node.options).find(option=>option.textContent.includes(path)).value''',str(projects[B]))
                await page.locator('#changed-work-project').select_option(value)
                assert await rows.count()==1 and await page.locator(f'#changed-work-list [data-session="{B}"]').count()==1
                await page.locator('#changed-work-project').select_option('')
                await page.locator('#changed-work-mode').select_option('changed')
                assert await page.evaluate('JSON.stringify(DeskNewActivityView.reviewMetadata())')==review_before
                assert desk.store.db.total_changes==changes
                assert local_preparation()==prepared
                await checkpoint('grouped-overview-unknown-baseline-explicit-project-and-get-only-review')

                await page.locator(f'#changed-work-list [data-session="{A}"] button').click()
                await page.wait_for_function('id=>selected===id && !opening && !sessionReadingPending',arg=A)
                await frames(page);returned=await state()
                assert returned['command']['open'] and returned['command']['top']==anchor['command']['top'],(anchor,returned)
                assert abs(returned['command']['screenTop']-anchor['command']['screenTop'])<=1,(anchor,returned)
                a_review=await review_state();assert a_review['reviewed']==initial_seq,a_review
                assert a_review['pending']['first']['item_id']==COMMAND and a_review['pending']['first']['first_seq']==first_seq,a_review
                await page.locator('#changed-work-back').click()
                assert await page.evaluate('id=>document.activeElement?.closest(".changed-work-row")?.dataset.session===id',A)
                await page.locator('#changed-work-close').click()
                await page.locator('#native-activity-first').click();await frames(page)
                first_revealed=await state();report['first_revealed']=first_revealed
                assert abs(first_revealed['command']['screenTop'])<=1,first_revealed
                assert (await review_state())['reviewed']==initial_seq
                assert local_preparation()==prepared
                await checkpoint('overview-open-restores-old-anchor-return-focus-and-explicit-first-is-separate')

                await page.locator('#native-activity-mark').click();await frames(page)
                marked=await review_state();assert marked['reviewed']==first_seq,marked
                await page.evaluate('refresh()');await frames(page)
                assert await page.locator(f'.session-row[data-session="{A}"] .native-material-dot').count()==0
                command['aggregatedOutput']+='\nNew native command material after explicit Mark.'
                next_seq=emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':PRIOR,'item':copy.deepcopy(command)}})
                await consume_through(next_seq);await page.evaluate('refresh()');await frames(page)
                newer=await review_state();assert newer['reviewed']==first_seq and newer['pending']['first']['first_seq']==next_seq,newer
                assert await page.locator(f'.session-row[data-session="{A}"] .native-material-dot').count()==1
                assert local_preparation()==prepared
                await checkpoint('explicit-mark-clears-only-captured-frontier-next-parent-update-remains-new')

                await navigate(B)
                threads[A]['turns'][0]['items']=[item for item in threads[A]['turns'][0]['items'] if item['id']!=COMMAND]
                desk.runtimes.pop(A).close()
                await page.locator('#show-changed-work').click()
                await page.locator(f'#changed-work-list [data-session="{A}"] button').click()
                await page.wait_for_function('id=>selected===id && !opening && !sessionReadingPending',arg=A)
                await frames(page)
                assert await page.locator(f'#activity [data-item-id="{COMMAND}"]').count()==1
                await page.locator('#native-activity-first').click();await frames(page)
                unavailable=await review_state();assert 'unavailable' in unavailable['status'] and unavailable['reviewed']==first_seq,unavailable
                await page.locator('#native-activity-mark').click();await frames(page)
                assert (await review_state())['reviewed']==first_seq
                await page.evaluate('refresh()');assert await page.locator(f'.session-row[data-session="{A}"] .native-material-dot').count()==1
                assert local_preparation()==prepared
                await checkpoint('fresh-source-missing-cached-triple-stays-new-and-cannot-auto-review')
                threads[A]['turns'][0]['items'].insert(2,copy.deepcopy(command))
                desk.runtimes.pop(A).close()

                await navigate(B)
                entered,release=threading.Event(),threading.Event();holds[A]=(entered,release)
                await page.locator('#show-changed-work').click()
                await page.locator(f'#changed-work-list [data-session="{A}"] button').click()
                assert await asyncio.to_thread(entered.wait,12),'Held overview A open never entered'
                await navigate(C)
                await page.locator('#prompt').fill(C_DRAFT)
                await page.wait_for_function('text=>draftSaved.get(selected)?.text===text',arg=C_DRAFT)
                held=await page.evaluate("({selected,thread:nativeThreadId,prompt:$('prompt').value,activity:$('activity').textContent,top:scrollY})")
                async with page.expect_response(lambda response:urlsplit(response.url).path=='/api/open') as response_wait:
                    release.set();holds.pop(A)
                response=await response_wait.value;assert response.ok;await response.json();await frames(page)
                after=await page.evaluate("({selected,thread:nativeThreadId,prompt:$('prompt').value,activity:$('activity').textContent,top:scrollY})")
                assert after==held,(held,after)
                await navigate(B)
                assert await page.locator('#prompt').input_value()==B_DRAFT
                assert await page.locator('#turn-mode').input_value()=='plan'
                assert await page.get_by_label('B native answer — What check should remain?').input_value()==ANSWER
                assert local_preparation()==prepared
                await checkpoint('held-old-overview-open-cannot-replace-new-owner-or-b-owned-preparation')

                # A review can empty the sole last-page row without changing
                # the human's captured scope/page or its exact return identity.
                pagination=folder/'pagination-project';pagination.mkdir()
                page_owners=[]
                for index in range(31):
                    session='page-session-'+str(index);native='native-'+session;turn='page-turn-'+str(index)
                    item=agent('page-item-'+str(index),'Native saved response '+str(index))
                    threads[session]={'id':native,'name':'Paged native task '+str(index),'cwd':str(pagination),
                        'turns':[{'id':turn,'status':'completed','items':[item]}]}
                    desk.store.create(str(pagination),'default',identifier=session,name=threads[session]['name'])
                    desk.store.update(session,thread_id=native,thread_saved=1,status='completed',name_pending=0)
                    desk.store.event(session,{'method':'item/completed','params':{'threadId':native,'turnId':turn,'item':copy.deepcopy(item)}})
                    page_owners.append({'native_home':desk.native_home_namespace(),'session':session,'thread_id':native})
                await page.evaluate('''owners=>{const fixture=DeskNewActivity.create(localStorage);
                    for(const owner of owners)fixture.seed(owner,DeskNewActivity.capture(owner,[]));}''',page_owners)
                await page.evaluate('refresh()');await frames(page)
                await page.locator('#show-changed-work').click()
                project_value=await page.locator('#changed-work-project').evaluate('''(node,path)=>Array.from(node.options).find(option=>option.textContent.includes(path)).value''',str(pagination))
                await page.locator('#changed-work-project').select_option(project_value)
                assert await page.locator('#changed-work-list .changed-work-row').count()==30
                await page.locator('#changed-work-next').click()
                last_row=page.locator('#changed-work-list .changed-work-row');assert await last_row.count()==1
                last_session=await last_row.get_attribute('data-session')
                await last_row.locator('button').evaluate('node=>globalThis.fixtureLastPageButton=node')
                await last_row.locator('button').click()
                await page.wait_for_function('id=>selected===id && !opening && !sessionReadingPending',arg=last_session)
                await frames(page);assert not await page.locator('#native-activity-mark').is_disabled()
                await page.locator('#native-activity-mark').click();await frames(page)
                await page.locator('#changed-work-back').click()
                assert await page.locator('#changed-work-list .changed-work-row').count()==1
                assert await page.evaluate('document.activeElement===fixtureLastPageButton && fixtureLastPageButton.isConnected')
                assert 'No new recorded material' in await page.locator('#changed-work-list').inner_text()
                assert '30 changed' in await page.locator('#changed-work-status').inner_text()
                await page.locator('#changed-work-previous').click()
                assert await page.locator('#changed-work-list .changed-work-row').count()==30
                assert await page.locator(f'#changed-work-list [data-session="{last_session}"]').count()==0
                assert local_preparation()==prepared
                await checkpoint('reviewed-sole-page-two-row-keeps-exact-focus-until-explicit-page-change')

                await page.locator('#changed-work-close').click()
                running_id='A-default-open-running-command'
                running={'id':running_id,'type':'commandExecution','command':'fixture verify running output',
                    'status':'inProgress','aggregatedOutput':lines}
                threads[A]['turns'][1]['items'].append(running)
                emit({'method':'item/started','params':{'threadId':threads[A]['id'],'turnId':LIVE,'item':copy.deepcopy(running)}})
                if A in desk.runtimes:desk.runtimes.pop(A).close()
                await navigate(A)
                running_state=await page.evaluate('''id=>{const node=nodes.get(id),detail=node.querySelector('.activity-tool');
                    return {open:detail.open,status:items.get(id).status};}''',running_id)
                assert running_state=={'open':True,'status':'inProgress'},running_state
                # Read the already-open running body without clicking its summary.
                await page.evaluate('''id=>{const node=nodes.get(id);node.querySelector('.activity-evidence').scrollTop=177;
                    window.scrollTo({top:scrollY+node.getBoundingClientRect().top-140,behavior:'instant'});}''',running_id)
                await frames(page)
                async def running_view():
                    return await page.evaluate('''id=>{const node=nodes.get(id),detail=node.querySelector('.activity-tool'),pre=node.querySelector('.activity-evidence');
                        return {open:detail.open,top:pre.scrollTop,screenTop:node.getBoundingClientRect().top,status:items.get(id).status};}''',running_id)
                running_anchor=await running_view();await navigate(B)
                running.update(status='completed',exitCode=0);running['aggregatedOutput']+='\nCompleted while B remains prepared.'
                emit({'method':'item/completed','params':{'threadId':threads[A]['id'],'turnId':LIVE,'item':copy.deepcopy(running)}})
                desk.runtimes.pop(A).close();await page.evaluate('refresh()');await frames(page)
                await page.locator('#show-changed-work').click();await page.locator('#changed-work-project').select_option('')
                await page.locator(f'#changed-work-list [data-session="{A}"] button').click()
                await page.wait_for_function('id=>selected===id && !opening && !sessionReadingPending',arg=A);await frames(page)
                completed=await running_view()
                assert completed['status']=='completed' and completed['open'] and completed['top']==running_anchor['top'],(running_anchor,completed)
                assert abs(completed['screenTop']-running_anchor['screenTop'])<=1,(running_anchor,completed)
                assert local_preparation()==prepared
                report['running_tool']={'before':running_anchor,'after':completed}
                await checkpoint('default-open-running-tool-completion-keeps-saved-body-and-viewport')

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
