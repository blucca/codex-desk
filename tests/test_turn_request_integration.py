"""Ordinary Run acceptance through shipped JS, HTTP admission and Runtime reducer.

Only the native request transport is controlled. Browser controllers and Desk
admission/persistence methods are the actual product source.
"""
import copy
import http.client
import json
import os
from pathlib import Path
import shutil
import subprocess
import threading
import unittest
import uuid
from urllib.parse import urlencode
from unittest.mock import Mock

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.runtime import Runtime, NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import Desk, handler
from http.server import ThreadingHTTPServer
from test_approval_lifecycle import NativeHTTPFixture, ROOT
from test_navigation_controllers import DOM

PRODUCT = Path(__file__).resolve().parents[1]
ACCESS = 'ordinary-controlled-access'
TEXT = 'Review exactly one project decision — 保留  '
NEWER = 'Newer unsent Plan — résumé 保留  '


class TurnRequestIntegrationTests(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.close_server()
        self.desk.store.update(self.identifier, status='ready')
        self.runtime.lock = threading.Lock()
        self.runtime.pending = {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()
        self.native_mode = 'completed'
        self.native_hold = threading.Event()
        self.native_hold.set()
        self.native_entered = threading.Event()
        self.reply_hold = threading.Event()
        self.reply_hold.set()
        self.reply_entered = threading.Event()
        self.drop_reply = False
        self.http, self.replies = [], []
        self.runtime.request = self.controlled_native
        self.start_server()
        self.addCleanup(self.native_hold.set)
        self.addCleanup(self.reply_hold.set)
        save_draft(self.desk.store, self.identifier, TEXT, 'plan', 0)
        add_followup(self.desk.store, self.identifier, 'Paused Work — exact  ', 'native')
        add_followup(self.desk.store, self.identifier, 'Paused Plan — exact  ', 'plan')
        self.preparation = followup_snapshot(self.desk.store, self.identifier)

    def start_server(self, port=0):
        owner = self
        class Handler(handler(self.desk, ACCESS)):
            def do_GET(self):
                owner.http.append({'method': 'GET', 'path': self.path})
                super().do_GET()
            def do_POST(self):
                owner.http.append({'method': 'POST', 'path': self.path})
                super().do_POST()
            def reply(self, value, status=200):
                if self.path == '/api/turn' and status == 200:
                    owner.replies.append(copy.deepcopy(value))
                    owner.reply_entered.set()
                    assert owner.reply_hold.wait(20), 'Unreleased local admission reply'
                    if owner.drop_reply:
                        owner.drop_reply = False
                        self.close_connection = True
                        return
                super().reply(value, status)
        self.server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def controlled_native(self, method, params):
        self.assertEqual(method, 'turn/start')
        self.requests.append({'method': method, 'params': copy.deepcopy(params)})
        turn = 'ordinary-turn-' + str(len(self.requests))
        self.native_entered.set()
        self.assertTrue(self.native_hold.wait(20), 'Unreleased native transport')
        if self.native_mode == 'rejected':
            raise NativeRequestRejected('Controlled known rejection')
        if self.native_mode in ('unknown', 'other-thread'):
            if self.native_mode == 'other-thread':
                self.native_event('turn/started', 'owned-child', {'turn': {'id': 'unrelated', 'status': 'inProgress'}})
            raise NativeRequestUnknown('Controlled no-event unknown admission')
        self.native_event('turn/started', params['threadId'], {'turn': {'id': turn, 'status': 'inProgress'}})
        if self.native_mode == 'completed':
            self.native_event('item/completed', params['threadId'], {'turnId': turn, 'item': {
                'id': 'user-' + turn, 'type': 'userMessage', 'content': params['input']}})
            self.native_event('item/completed', params['threadId'], {'turnId': turn, 'item': {
                'id': 'answer-' + turn, 'type': 'agentMessage', 'text': 'Controlled result ' + turn}})
            self.native_event('turn/completed', params['threadId'], {'turn': {'id': turn, 'status': 'completed'}})
        return {'turn': {'id': turn, 'status': 'inProgress'}}

    def remount_native_transport(self):
        self.runtime = object.__new__(Runtime)
        runtime = self.runtime
        runtime.store, runtime.id, runtime.home = self.desk.store, self.identifier, self.path
        runtime.approvals, runtime.pending = {}, {}
        runtime.persisted, runtime.closing = False, False
        runtime.lifecycle_lock, runtime.turn_lock = threading.Lock(), threading.Lock()
        runtime.name_lock, runtime.lock, runtime.write_lock = threading.RLock(), threading.Lock(), threading.Lock()
        runtime.process = Mock()
        runtime.process.poll.return_value = None
        runtime.reader, runtime.stderr_reader = Mock(), Mock()
        runtime.thread_result = {'thread': {'id': 'native-original', 'turns': []}}
        runtime.send, runtime.request = self.send_native, self.controlled_native
        self.desk.runtimes[self.identifier] = runtime

    def native_event(self, method, thread, fields):
        with self.runtime.lifecycle_lock:
            self.runtime._message({'method': method, 'params': {'threadId': thread, **fields}})

    def request(self, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=25)
        headers = {'X-Codex-Desk-Access': ACCESS}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        try:
            connection.request('GET' if data is None else 'POST', path,
                               None if data is None else json.dumps(data), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def capture(self, text=TEXT, mode='plan'):
        current = load_draft(self.desk.store, self.identifier)
        writer = str(uuid.uuid4())
        saved = save_draft(self.desk.store, self.identifier, text, mode, current['revision'], writer, 1)
        return {'session': self.identifier, 'token': str(uuid.uuid4()), 'text': text,
                'mode': mode, 'revision': saved['revision'], 'writer': writer, 'sequence': 1}

    def read_request(self, payload):
        return self.request('/api/turn/request?' + urlencode({'session': payload['session'], 'token': payload['token']}))

    def assert_preparation(self):
        self.assertEqual(followup_snapshot(self.desk.store, self.identifier), self.preparation)

    def test_pending_duplicate_and_completed_same_words_new_identity(self):
        data = self.capture()
        self.native_hold.clear()
        responses = []
        worker = threading.Thread(target=lambda: responses.append(self.request('/api/turn', data)))
        worker.start()
        try:
            self.assertTrue(self.native_entered.wait(3))
            status, duplicate = self.request('/api/turn', data)
            self.assertEqual(status, 200)
            self.assertEqual(duplicate['request']['status'], 'pending')
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.read_request(data), (200, duplicate))
            self.assertEqual(self.request('/api/turn', {**data, 'token': str(uuid.uuid4())})[0], 409)
        finally:
            self.native_hold.set()
            worker.join(5)
        self.assertFalse(worker.is_alive())
        self.assertEqual(responses[0][1]['request']['status'], 'accepted')
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], '')
        self.assertEqual(self.request('/api/turn', data), responses[0])
        fresh = self.capture()
        self.assertNotEqual(fresh['token'], data['token'])
        status, response = self.request('/api/turn', fresh)
        self.assertEqual((status, response['request']['status']), (200, 'accepted'))
        self.assertEqual(len(self.requests), 2)
        self.assert_preparation()

    def test_no_event_unknown_blocks_ordinary_and_send_next_until_explicit_review(self):
        data = self.capture()
        self.native_mode = 'unknown'
        status, response = self.request('/api/turn', data)
        self.assertEqual((status, response['request']['status']), (200, 'needs_review'))
        self.assertEqual(self.read_request(data), (200, response))
        self.assertEqual(self.request('/api/turn', data), (200, response))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.request('/api/turn', {**data, 'token': str(uuid.uuid4())})[0], 409)
        entry = self.preparation['entries'][0]
        status, _ = self.request('/api/followups/send', {'session': self.identifier, 'id': entry['id'], 'revision': entry['revision']})
        self.assertEqual(status, 409)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], TEXT)
        self.assert_preparation()
        status, reviewed = self.request('/api/turn/resolve', {'session': self.identifier, 'token': data['token'], 'outcome': 'accepted'})
        self.assertEqual((status, reviewed['request']['status']), (200, 'accepted'))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.read_request(data), (200, reviewed))

    def test_known_rejection_retry_is_explicit_and_same_target(self):
        data = self.capture()
        self.native_mode = 'rejected'
        status, response = self.request('/api/turn', data)
        self.assertEqual((status, response['request']['status']), (200, 'rejected'))
        self.native_mode = 'completed'
        self.assertEqual(self.request('/api/turn', data), (200, response))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.request('/api/turn', {**data, 'text': 'Changed task', 'retry': True})[0], 409)
        self.assertEqual(len(self.requests), 1)
        old_cwd = self.desk.store.get(self.identifier)['cwd']
        self.desk.store.update(self.identifier, cwd=str(self.path / 'different-target'))
        self.assertEqual(self.request('/api/turn', {**data, 'retry': True})[0], 409)
        self.assertEqual(len(self.requests), 1)
        self.desk.store.update(self.identifier, cwd=old_cwd)
        status, retried = self.request('/api/turn', {**data, 'retry': True})
        self.assertEqual((status, retried['request']['status']), (200, 'accepted'))
        self.assertEqual(retried['request']['attempt'], 2)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0], self.requests[1])
        self.assert_preparation()

    def test_older_start_and_owned_child_event_are_not_admission_proof(self):
        self.native_event('turn/started', 'native-original', {'turn': {'id': 'old', 'status': 'inProgress'}})
        self.native_event('turn/completed', 'native-original', {'turn': {'id': 'old', 'status': 'completed'}})
        data = self.capture()
        self.native_mode = 'other-thread'
        status, response = self.request('/api/turn', data)
        self.assertEqual((status, response['request']['status']), (200, 'needs_review'))
        self.assertNotIn('turn', response['request'])
        self.assertEqual(len(self.requests), 1)
        self.assert_preparation()

    def test_cold_same_state_opaque_read_only_and_retained_home_mismatch_blocked(self):
        data = self.capture()
        self.native_mode = 'rejected'
        status, retained = self.request('/api/turn', data)
        self.assertEqual((status, retained['request']['status']), (200, 'rejected'))
        port = self.server.server_port
        self.close_server()
        cold = Desk('must-not-run-native', self.path, self.path / 'state')
        old_desk = self.desk
        self.desk = cold
        self.addCleanup(cold.store.db.close)
        cold.open = lambda identifier: self.fail('Request read opened native work')
        cold.runtime = lambda identifier: self.fail('Request read dispatched native work')
        self.start_server(port)
        before_http = len(self.http)
        before = (cold.store.sessions(), cold.store.events(self.identifier), load_draft(cold.store, self.identifier), followup_snapshot(cold.store, self.identifier))
        self.assertEqual(self.read_request(data), (200, retained))
        self.assertEqual(self.server.server_port, port)
        self.assertEqual(self.http[before_http:], [{'method': 'GET', 'path': '/api/turn/request?' + urlencode({'session': data['session'], 'token': data['token']})}])
        self.node_case(r'''
assert.equal(turnRequest(session).body,null,'Cold browser retention must not include private captured text');
assert.deepStrictEqual(JSON.parse(storage.get(turnRequestKey)),[{session,token:turnRequest(session).token}]);
assert.equal(await open(session,{revealLatest:false}),true);
assert.equal(turnRequest(session).result.request.status,'rejected');
assert.equal(turnRequest(session).body.text,text);assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');
await $('task').onsubmit({preventDefault(){}});await $('turn-request-recover').onclick();
assert(net.every(r=>r.method==='GET'),'Cold recovery must be GET-only, never native open or ordinary POST');
assert(!net.some(r=>r.path==='/api/open'));
assert(JSON.parse(storage.get(turnRequestKey)).every(entry=>Object.keys(entry).sort().join(',')==='session,token'));
''', retained=[{'session': data['session'], 'token': data['token']}])
        cold.home = self.path / 'other-native-home'
        self.assertEqual(self.request('/api/turn', {**data, 'retry': True})[0], 409)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual((cold.store.sessions(), cold.store.events(self.identifier), load_draft(cold.store, self.identifier), followup_snapshot(cold.store, self.identifier)), before)
        status, mismatch = self.read_request(data)
        self.assertEqual(status, 200)
        self.assertTrue(mismatch['request']['binding_mismatch'])
        self.assertEqual(mismatch['request']['binding'], retained['request']['binding'])
        self.assertEqual(mismatch['request']['status'], 'rejected')
        self.assertEqual(old_desk.store.events(self.identifier), before[1])

    def javascript(self, body, retained=None):
        source = (PRODUCT / 'codex_desk/static/app.js').read_text()
        def fragment(begin, end):
            return source[source.index(begin):source.index(end)]
        dom = DOM[:DOM.index('let state=')]
        setup = r'''
const crypto=require('node:crypto'),base=BASE,session=SESSION,text=TEXT,newer=NEWER;
const networkFetch=globalThis.fetch;const net=[];
globalThis.fetch=(path,options)=>{net.push({method:options?.method||'GET',path,body:options?.body?JSON.parse(options.body):null});return networkFetch(new URL(path,base),options);};
const storage=new Map([['codex-desk-access',ACCESS],['codex-desk-turn-requests',JSON.stringify(RETAINED)]]);
const sessionStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,String(value)),removeItem:key=>storage.delete(key)};
const localStorage={getItem(){return null;},setItem(){}};
const window={addEventListener(){}};document.getElementById=$;
const archiving=new Set(),frames=[];const requestAnimationFrame=callback=>frames.push(callback);
const DeskHome={sync(){},selectionChanged(){}},DeskRecall={stateChanged(){},selectionChanged(){}};
const DeskNativeState={usage(){return '';},card(){return new Element();}};
function drawSidebar(){}function syncSelectedOriginal(){}function approvals(){}
function nearLatest(){return false;}function latestLabel(){}function goLatest(){throw Error('Automatic reading movement is forbidden');}
function renderItem(item,turn){items.set(item.id,item);itemTurns.set(item.id,turn);}
function profileLabel(value){return value;}
function nap(ms=20){return new Promise(resolve=>setTimeout(resolve,ms));}
async function until(fn,message){for(let i=0;i<150;i++){if(await fn())return;await nap();}throw Error(message);}
'''
        for key, value in {'BASE': f'http://127.0.0.1:{self.server.server_port}', 'SESSION': self.identifier,
                           'TEXT': TEXT, 'NEWER': NEWER, 'ACCESS': ACCESS, 'RETAINED': retained or []}.items():
            setup = setup.replace(key, json.dumps(value, ensure_ascii=False))
        chunks = [fragment('function deskAccessHeaders(', 'function nearLatest('),
                  fragment('async function api(', 'function make('),
                  fragment('function activeSession(', 'function sidebarGroups('),
                  fragment('function draw()', 'function itemText('),
                  fragment('function consume(m)', 'function profileInfo('),
                  fragment("$('task').onsubmit=", "$('stop').onclick="),
                  fragment('async function pollActivity()', 'async function tick()'),
                  '\n'.join(line for line in source.splitlines() if line.startswith("$('prompt').oninput=") or line.startswith("$('turn-mode').onchange=") or line.startswith('DeskFollowups.configure('))]
        followups = (PRODUCT / 'codex_desk/static/followups.js').read_text()
        presentation = (PRODUCT / 'codex_desk/static/preparation.js').read_text()
        native_readouts = (PRODUCT / 'codex_desk/static/native-steps.js').read_text() + '\nDeskNativeSteps.configure({$,make});\n'
        native_readouts += (PRODUCT / 'codex_desk/static/turn-changes.js').read_text() + '\nDeskTurnChanges.configure({$,writeText:async()=>{}});\nconst DeskSteering={select(){},sync(){},consume(){},restoreThread(){},opened(){},reading:()=>false};\n'
        return dom + setup + '\n' + native_readouts + presentation + '\n' + followups + '\n' + '\n'.join(chunks) + '\n' + r'''
(async()=>{
selected=session;generation=3;nativeThreadId='native-original';state=await api('/api/state');
await loadDraft(session,generation);DeskFollowups.select(session);await DeskFollowups.refresh(session);$('prompt').focus();draw();
assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');
''' + body + r'''
for(const timer of draftTimers.values())clearTimeout(timer);
process.stdout.write(JSON.stringify({passed:true,net,prompt:$('prompt').value,mode:$('turn-mode').value,focusedPrompt:document.activeElement===$('prompt')}));
})().catch(error=>{process.stderr.write(error.stack+'\n');process.exit(1);});
'''

    def node_case(self, body, during=None, retained=None):
        if not shutil.which('node'):
            self.skipTest('Node.js is required for actual Run controller integration')
        path = self.path / 'actual-run.js'
        path.write_text(self.javascript(body, retained))
        process = subprocess.Popen(['node', str(path)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, stdin=subprocess.PIPE, text=True)
        try:
            if during:
                during(process)
            stdout, stderr = process.communicate(timeout=25)
            parsed = [json.loads(line) for line in stdout.splitlines() if line.strip()]
            result = parsed[-1] if parsed else None
            evidence = os.environ.get('DESK_TURN_ACCEPTANCE_EVIDENCE')
            if evidence:
                out = Path(evidence)
                out.mkdir(parents=True, exist_ok=True)
                (out / (self._testMethodName + '.json')).write_text(json.dumps({
                    'returncode': process.returncode, 'stdout': stdout, 'stderr': stderr,
                    'browser': result, 'http': self.http, 'native_starts': self.requests,
                    'replies': self.replies, 'events': self.desk.store.events(self.identifier),
                    'draft': load_draft(self.desk.store, self.identifier),
                    'preparation': followup_snapshot(self.desk.store, self.identifier)}, ensure_ascii=False, indent=2) + '\n')
            self.assertEqual(process.returncode, 0, stderr + '\n' + stdout)
            self.assertTrue(result['passed'])
            return result
        finally:
            self.reply_hold.set()
            self.native_hold.set()
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=5)

    def test_actual_run_dropped_completed_reply_preserves_newer_exact_plan_edit_focus_and_two_paused_queues(self):
        self.drop_reply = True
        self.reply_hold.clear()
        def release_after_newer_saved(process):
            self.assertTrue(self.reply_entered.wait(8), 'Actual task handler did not reach HTTP acceptance')
            phase = json.loads(process.stdout.readline())
            self.assertEqual(phase['phase'], 'newer-plan-saved')
            self.assertEqual(phase['text'], NEWER)
            self.reply_hold.set()
        result = self.node_case(r'''
const preparationBefore=await api('/api/followups?session='+encodeURIComponent(session));
const pending=$('task').onsubmit({preventDefault(){}});
await until(async()=> (await api('/api/state')).sessions.find(s=>s.id===session).status==='completed','Native task did not finish');
await pollActivity();
$('prompt').value=newer;$('turn-mode').value='plan';$('prompt').oninput();$('turn-mode').onchange();
await persistDraft(session);const newerEdit=draftEdits.get(session);$('prompt').focus();
process.stdout.write(JSON.stringify({phase:'newer-plan-saved',text:$('prompt').value})+'\n');
await pending;await pollActivity();await DeskFollowups.refresh(session);
assert.equal(state.sessions.find(s=>s.id===session).status,'completed');assert.equal(currentTurn,'ordinary-turn-1');
assert.equal($('prompt').value,newer);assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),newerEdit);
assert.equal(selected,session);assert.equal(generation,3);assert.equal(document.activeElement,$('prompt'));
assert.equal((await api('/api/draft?session='+encodeURIComponent(session))).text,newer);
assert.deepStrictEqual(await api('/api/followups?session='+encodeURIComponent(session)),preparationBefore);
const posts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length;
await $('task').onsubmit({preventDefault(){}});await pollActivity();
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts,'Checking the retained Run request replayed native work');
assert.equal($('prompt').value,newer);assert.equal(draftEdits.get(session),newerEdit);assert.equal(document.activeElement,$('prompt'));
assert.equal(turnRequest(session).result.request.status,'accepted');
''', release_after_newer_saved)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]['params']['input'][0]['text'], TEXT)
        self.assertEqual(self.requests[0]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual(result['prompt'], NEWER)
        self.assertTrue(result['focusedPrompt'])
        self.assert_preparation()

    def test_actual_dropped_reply_retains_newer_same_words_plan_by_edit_identity(self):
        self.drop_reply = True
        self.reply_hold.clear()
        def release_after_same_words_saved(process):
            self.assertTrue(self.reply_entered.wait(8))
            phase = json.loads(process.stdout.readline())
            self.assertEqual(phase['phase'], 'newer-same-words-plan-saved')
            self.assertEqual(phase['text'], TEXT)
            self.reply_hold.set()
        self.node_case(r'''
const pending=$('task').onsubmit({preventDefault(){}});
await until(async()=> (await api('/api/state')).sessions.find(s=>s.id===session).status==='completed','Native task did not finish');
await pollActivity();
$('prompt').value='';$('prompt').oninput();$('prompt').value=text;$('turn-mode').value='plan';$('prompt').oninput();
const edit=draftEdits.get(session);await persistDraft(session);$('prompt').focus();
process.stdout.write(JSON.stringify({phase:'newer-same-words-plan-saved',text:$('prompt').value})+'\n');
await pending;await pollActivity();
assert.equal(turnRequest(session).result.request.status,'accepted');
assert.equal($('prompt').value,text,'An accepted receipt must not clear newer same-word intent');
assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
const posts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length;
await $('task').onsubmit({preventDefault(){}});assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts);
await $('turn-request-new').onclick();
assert.equal($('prompt').value,text);assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts,'New preparation acknowledgement must not admit a task');
''', release_after_same_words_saved)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], TEXT)
        self.assert_preparation()

    def test_actual_run_completed_same_words_can_be_deliberately_fresh_after_exact_clear(self):
        self.drop_reply = True
        self.node_case(r'''
await $('task').onsubmit({preventDefault(){}});await pollActivity();
await $('turn-request-recover').onclick();
assert.equal(turnRequest(session),undefined,'Exact accepted draft clear should release only the captured editor');
const firstToken=net.find(r=>r.method==='POST'&&r.path==='/api/turn').body.token;
assert.equal($('prompt').value,'');
const posts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length;
await $('task').onsubmit({preventDefault(){}});
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts);
await $('turn-request-new').onclick();
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts,'New preparation must not start work');
$('prompt').value=text;$('turn-mode').value='plan';$('prompt').oninput();$('turn-mode').onchange();$('prompt').focus();
await $('task').onsubmit({preventDefault(){}});await pollActivity();
assert.notEqual(net.filter(r=>r.method==='POST'&&r.path==='/api/turn')[1].body.token,firstToken);
assert.equal(turnRequest(session),undefined);assert.equal(currentTurn,'ordinary-turn-2');
assert.equal($('prompt').value,'');assert.equal(document.activeElement,$('prompt'));
''')
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0], self.requests[1])
        self.assert_preparation()

    def test_actual_unknown_run_blocks_both_controls_and_explicit_review_does_not_send(self):
        self.native_mode = 'unknown'
        self.node_case(r'''
const preparationBefore=await api('/api/followups?session='+encodeURIComponent(session));
await $('task').onsubmit({preventDefault(){}});await pollActivity();await DeskFollowups.refresh(session);draw();
assert.equal(turnRequest(session).result.request.status,'needs_review');
assert.equal($('send').textContent,'Check Run request','Unknown ordinary Run may only check its receipt');
assert($('followup-send').disabled,'Unknown ordinary Run must block Send next');
assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');assert.equal(document.activeElement,$('prompt'));
const posts=net.filter(r=>r.method==='POST'&&(r.path==='/api/turn'||r.path==='/api/followups/send')).length;
await $('task').onsubmit({preventDefault(){}});await $('followup-send').onclick();await $('turn-request-recover').onclick();
assert.equal(net.filter(r=>r.method==='POST'&&(r.path==='/api/turn'||r.path==='/api/followups/send')).length,posts);
assert.deepStrictEqual(await api('/api/followups?session='+encodeURIComponent(session)),preparationBefore);
const retained=turnRequest(session);await $('turn-request-accepted').onclick();
assert.equal(retained.result.request.status,'accepted');
assert.equal(net.filter(r=>r.method==='POST'&&(r.path==='/api/turn'||r.path==='/api/followups/send')).length,posts);
assert.equal(document.activeElement,$('prompt'));
''')
        self.assertEqual(len(self.requests), 1)
        self.assert_preparation()

    def test_actual_fresh_page_adopts_other_ordinary_unknown_receipt_without_replacing_newer_plan(self):
        original = self.capture()
        self.native_mode = 'unknown'
        status, response = self.request('/api/turn', original)
        self.assertEqual((status, response['request']['status']), (200, 'needs_review'))
        body = r'''
assert.equal(turnRequest(session),undefined,'Fresh page must begin without the other page token');
$('prompt').value=newer;$('turn-mode').value='plan';$('prompt').oninput();const edit=draftEdits.get(session);$('prompt').focus();
await $('task').onsubmit({preventDefault(){}});await pollActivity();await DeskFollowups.refresh(session);draw();
const request=turnRequest(session);
process.stdout.write(JSON.stringify({phase:'fresh-page-other-unknown',expectedToken:ORIGINAL_TOKEN,actualToken:request?.token,status:request?.status,notFound:request?.notFound,prompt:$('prompt').value,mode:$('turn-mode').value,edit:draftEdits.get(session),focused:document.activeElement===$('prompt')})+'\n');
assert.equal(request.token,ORIGINAL_TOKEN,'Fresh Run conflict must adopt the original same-session review receipt, not retain a nonexistent token');
assert.equal(request.status,'needs_review');assert(!$('turn-request-accepted').hidden);assert(!$('turn-request-rejected').hidden);
assert.equal($('prompt').value,newer);assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
assert($('followup-send').disabled);
const posts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length;
await $('task').onsubmit({preventDefault(){}});await $('turn-request-recover').onclick();
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts);
await $('turn-request-accepted').onclick();
assert.equal(request.result.request.status,'accepted');assert.equal($('prompt').value,newer);assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
'''.replace('ORIGINAL_TOKEN', json.dumps(original['token']))
        self.node_case(body)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], NEWER)
        self.assert_preparation()

    def test_actual_stale_page_followup_unknown_gets_durable_rejection_then_explicit_original_retry(self):
        self.native_mode = 'unknown'
        def after_followup_review(process):
            phase = json.loads(process.stdout.readline())
            self.assertEqual(phase['phase'], 'stale-followup-durable-rejection')
            self.assertEqual(len(self.requests), 1)
            phase = json.loads(process.stdout.readline())
            self.assertEqual(phase['phase'], 'followup-reviewed-ready')
            self.native_mode = 'completed'
            self.remount_native_transport()
            process.stdin.write('controlled-native-remounted\n')
            process.stdin.flush()
        self.node_case(r'''
const queue=await api('/api/followups?session='+encodeURIComponent(session)),entry=queue.entries[0];
try{await api('/api/followups/send',{session,id:entry.id,revision:entry.revision});assert.fail('Controlled other page follow-up must be unknown');}catch(e){assert.equal(e.status,400);}
// The view has not received the other page's preparation/state refresh yet.
assert(!$('send').disabled);
$('prompt').value=newer;$('turn-mode').value='plan';$('prompt').oninput();const edit=draftEdits.get(session);$('prompt').focus();
await $('task').onsubmit({preventDefault(){}});await pollActivity();await DeskFollowups.refresh(session);draw();
const request=turnRequest(session);
process.stdout.write(JSON.stringify({phase:'stale-followup-durable-rejection',token:request?.token,status:request?.status,notFound:request?.notFound,prompt:$('prompt').value,followupReviewHidden:$('followup-review').hidden})+'\n');
assert.equal(request.status,'rejected','A known predispatch follow-up blocker must leave a durable rejected ordinary receipt');assert(!request.notFound);
assert.equal(request.body.text,newer);assert.equal(request.body.mode,'plan');
assert(!$('followup-review').hidden);assert($('followup-send').disabled);
assert.equal($('prompt').value,newer);assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
const posts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length;
const eventsBefore=await api('/api/events?session='+encodeURIComponent(session)+'&after=0');
await $('task').onsubmit({preventDefault(){}});await $('turn-request-recover').onclick();
assert.deepStrictEqual(await api('/api/events?session='+encodeURIComponent(session)+'&after=0'),eventsBefore,'Duplicate rejected receipt recovery must write nothing');
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts);
await $('followup-confirm-started').onclick();await DeskFollowups.refresh(session);draw();
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,posts);
assert.equal(turnRequest(session).status,'rejected');assert.equal($('prompt').value,newer);assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
process.stdout.write(JSON.stringify({phase:'followup-reviewed-ready'})+'\n');await new Promise(resolve=>process.stdin.once('data',resolve));
await $('turn-request-retry').onclick();await pollActivity();
assert.equal(request.result.request.status,'accepted');assert.equal(request.result.request.attempt,2);
const starts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn');assert.equal(starts.length,2);assert(starts[1].body.retry);
assert.equal(starts[1].body.token,starts[0].body.token);assert.equal(starts[1].body.text,newer);assert.equal(starts[1].body.mode,'plan');
assert.equal($('prompt').value,'');assert.equal(document.activeElement,$('prompt'));
''', after_followup_review)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0]['params']['input'][0]['text'], self.preparation['entries'][0]['text'])
        self.assertEqual(self.requests[1]['params']['input'][0]['text'], NEWER)
        self.assertEqual(self.requests[1]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual(followup_snapshot(self.desk.store, self.identifier)['entries'], [{**self.preparation['entries'][1], 'order': 1}])

    def test_actual_cold_missing_opaque_receipt_remains_get_only_and_blocks_send_next(self):
        token = str(uuid.uuid4())
        self.node_case(r'''
assert.equal(turnRequest(session).body,null);
assert.equal(await open(session,{revealLatest:false}),true);
assert(turnRequest(session).notFound);assert.equal(turnRequest(session).status,null);
assert.equal($('send').textContent,'Check Run request');assert($('followup-send').disabled);
assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');
await $('task').onsubmit({preventDefault(){}});await $('followup-send').onclick();await pollActivity();
assert(net.every(r=>r.method==='GET'),'Missing retained receipt must not fallback to resending visible draft');
assert(!net.some(r=>r.path==='/api/open'));
assert.equal($('prompt').value,text);assert.equal(document.activeElement,$('prompt'));
''', retained=[{'session': self.identifier, 'token': token}])
        self.assertEqual(self.requests, [])
        self.assert_preparation()

    def test_actual_known_rejection_explicit_retry_captures_original_not_newer_editor(self):
        self.native_mode = 'rejected'
        self.reply_hold.clear()
        def allow_retry(process):
            self.assertTrue(self.reply_entered.wait(8))
            self.reply_hold.set()
            phase = json.loads(process.stdout.readline())
            self.assertEqual(phase['phase'], 'known-rejection-with-newer-editor')
            self.native_mode = 'completed'
            process.stdin.write('controlled-native-accepted\n')
            process.stdin.flush()
        self.node_case(r'''
await $('task').onsubmit({preventDefault(){}});await pollActivity();
assert.equal(turnRequest(session).result.request.status,'rejected');
const token=turnRequest(session).token;
$('prompt').value=newer;$('turn-mode').value='plan';$('prompt').oninput();await persistDraft(session);$('prompt').focus();const edit=draftEdits.get(session);
process.stdout.write(JSON.stringify({phase:'known-rejection-with-newer-editor'})+'\n');await new Promise(resolve=>process.stdin.once('data',resolve));
await $('turn-request-recover').onclick();assert.equal(turnRequest(session).result.request.status,'rejected');
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/turn').length,1);
await $('turn-request-retry').onclick();await pollActivity();
assert.equal(turnRequest(session).token,token);assert.equal(turnRequest(session).result.request.status,'accepted');
assert.equal($('prompt').value,newer);assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
const starts=net.filter(r=>r.method==='POST'&&r.path==='/api/turn');assert.equal(starts.length,2);
assert(starts[1].body.retry);assert.equal(starts[1].body.token,starts[0].body.token);assert.equal(starts[1].body.text,text);
''', allow_retry)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.requests[0], self.requests[1])
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], NEWER)
        self.assert_preparation()


if __name__ == '__main__':
    unittest.main()
