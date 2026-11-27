"""Binding recovery, no-token discovery and long-stream ordinary admission.

The native no-rollout transition uses actual Runtime.attach; only native RPC and
process transport are controlled. All JS, HTTP, persistence and reducers ship.
"""
import copy
import json
import os
from pathlib import Path
import statistics
import threading
import time
import unittest
import uuid
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import followup_snapshot
from codex_desk.runtime import Runtime, NativeRequestRejected
from codex_desk.server import Desk
from codex_desk.turn_dispatch import _records, turn_status, turn_cursor
import test_turn_request_integration as ordinary_tests
from test_turn_request_integration import TEXT, NEWER


class TurnRecoveryIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.f = ordinary_tests.TurnRequestIntegrationTests()
        self.f.setUp()
        self.f._testMethodName = self._testMethodName
        self.addCleanup(self.f.doCleanups)
        self.transport = []

    def record(self, name, result):
        output = os.environ.get('DESK_TURN_ACCEPTANCE_EVIDENCE')
        if output:
            path = Path(output);path.mkdir(parents=True, exist_ok=True)
            (path / (name + '.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')

    def cold(self):
        f = self.f
        port = f.server.server_port
        f.close_server()
        f.desk = Desk('controlled-native-only', f.path, f.path / 'state')
        f.addCleanup(f.desk.store.db.close)
        f.start_server(port)

    def runtime_factory(self, store, identifier, binary, home):
        f = self.f
        runtime = object.__new__(Runtime)
        runtime.store, runtime.id, runtime.home = store, identifier, Path(home)
        runtime.approvals, runtime.pending = {}, {}
        runtime.persisted, runtime.closing = False, False
        runtime.lifecycle_lock, runtime.turn_lock = threading.Lock(), threading.Lock()
        runtime.name_lock, runtime.lock, runtime.write_lock = threading.RLock(), threading.Lock(), threading.Lock()
        runtime.process = Mock(); runtime.process.poll.return_value = None
        runtime.reader, runtime.stderr_reader = Mock(), Mock()
        def request(method, params):
            self.transport.append({'method': method, 'params': copy.deepcopy(params)})
            if method == 'thread/resume':
                self.assertEqual(params['threadId'], 'native-original')
                raise NativeRequestRejected('no rollout found for never-used native-original')
            if method == 'thread/start':
                return {'thread': {'id': 'native-replacement', 'turns': []},
                        'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
            self.assertEqual(method, 'turn/start')
            self.assertEqual(params['threadId'], 'native-replacement')
            turn = 'replacement-accepted'
            with runtime.lifecycle_lock:
                runtime._message({'method': 'turn/started', 'params': {'threadId': 'native-replacement', 'turn': {'id': turn, 'status': 'inProgress'}}})
                runtime._message({'method': 'turn/completed', 'params': {'threadId': 'native-replacement', 'turn': {'id': turn, 'status': 'completed'}}})
            return {'turn': {'id': turn, 'status': 'inProgress'}}
        runtime.request = request
        return runtime

    def blank_fallback(self, unknown=False):
        f = self.f
        f.native_mode = 'unknown' if unknown else 'rejected'
        original = f.capture()
        status, receipt = f.request('/api/turn', original)
        self.assertEqual((status, receipt['request']['status']), (200, 'needs_review' if unknown else 'rejected'))
        self.assertFalse(f.desk.store.get(f.identifier)['thread_saved'])
        self.assertFalse(any(r['event'].get('method') == 'turn/started' for r in f.desk.store.events(f.identifier)))
        self.cold()
        with patch('codex_desk.server.Runtime', side_effect=self.runtime_factory):
            if unknown:
                status, _ = f.request('/api/open', {'session': f.identifier})
                self.assertEqual(status, 200)
            else:
                status, receipt = f.request('/api/turn', {**original, 'retry': True})
                self.assertEqual((status, receipt['request']['status']), (200, 'rejected'))
                self.assertTrue(receipt['request']['binding_mismatch'])
                self.assertEqual(receipt['request']['attempt'], 2)
        self.assertEqual([r['method'] for r in self.transport], ['thread/resume', 'thread/start'])
        self.assertEqual(f.desk.store.get(f.identifier)['thread_id'], 'native-replacement')
        self.assertEqual(len(f.requests), 1)
        self.assertEqual(followup_snapshot(f.desk.store, f.identifier), f.preparation)
        return original

    def test_actual_attach_fallback_cold_mismatch_receipt_visible_read_only_and_original_actions_blocked(self):
        f = self.f; original = self.blank_fallback()
        self.cold()
        before = (f.desk.store.sessions(), f.desk.store.events(f.identifier), load_draft(f.desk.store, f.identifier), followup_snapshot(f.desk.store, f.identifier))
        with patch('codex_desk.server.Runtime', side_effect=AssertionError('Cold receipt invoked native transport')):
            status, retained = f.read_request(original)
            self.assertEqual((status, retained['request']['status']), (200, 'rejected'))
            self.assertTrue(retained['request']['binding_mismatch'])
            self.assertEqual(retained['request']['binding']['thread_id'], 'native-original')
            self.assertEqual(retained['request']['current_binding']['thread_id'], 'native-replacement')
            self.assertEqual(retained['request']['payload'], original)
            self.assertEqual(f.request('/api/turn', original), (200, retained))
            status, blocked = f.request('/api/turn', {**original, 'retry': True})
            self.assertEqual(status, 409);self.assertEqual(blocked['current'], retained)
            for outcome in ('accepted', 'rejected'):
                status, blocked = f.request('/api/turn/resolve', {'session': f.identifier, 'token': original['token'], 'outcome': outcome})
                self.assertEqual(status, 409);self.assertEqual(blocked['current'], retained)
            f.node_case(r'''
await open(session,{revealLatest:false});
const request=turnRequest(session);assert.equal(request.status,'rejected');assert(request.result.request.binding_mismatch);
assert(!$('turn-request-binding').hidden);assert($('turn-request-original-binding').textContent.includes('native-original'));assert($('turn-request-current-binding').textContent.includes('native-replacement'));
assert($('turn-request-retry').disabled);assert(!$('turn-request-new').hidden);
const before=net.length;await $('turn-request-retry').onclick();await $('turn-request-accepted').onclick();await $('turn-request-rejected').onclick();
assert.equal(net.length,before,'Original native retry and admission decisions must be guarded on mismatch');
assert(net.every(r=>r.method==='GET'));assert(!net.some(r=>r.path==='/api/open'));
assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');
''', retained=[{'session': original['session'], 'token': original['token']}])
        self.assertEqual((f.desk.store.sessions(), f.desk.store.events(f.identifier), load_draft(f.desk.store, f.identifier), followup_snapshot(f.desk.store, f.identifier)), before)
        self.assertEqual(len(self.transport), 2)
        self.record(self._testMethodName + '-attach', {'native_transport': self.transport, 'retained': retained, 'readonly': True})

    def test_actual_rejected_target_review_is_get_only_then_new_uuid_targets_current_native_and_preserves_plan_queues(self):
        f = self.f; original = self.blank_fallback()
        with patch('codex_desk.server.Runtime', side_effect=self.runtime_factory):
            f.node_case(r'''
await open(session,{revealLatest:false});const original=turnRequest(session);assert(original.result.request.binding_mismatch);
$('prompt').value=newer;$('turn-mode').value='plan';$('prompt').oninput();await persistDraft(session);$('prompt').focus();const edit=draftEdits.get(session),body=original.body;
const posts=net.filter(r=>r.method==='POST').length,reads=net.filter(r=>r.method==='GET'&&r.path.startsWith('/api/turn/request')).length;
assert.equal($('turn-request-new').textContent,'Use current target for a new task');
await $('turn-request-new').onclick();
assert.equal(turnRequest(session),undefined);assert.equal(net.filter(r=>r.method==='POST').length,posts,'Explicit target review must not send any task or rewrite the draft');
assert.equal(net.filter(r=>r.method==='GET'&&r.path.startsWith('/api/turn/request')).length,reads+1);
assert.equal($('prompt').value,newer);assert.equal($('turn-mode').value,'plan');assert.equal(draftEdits.get(session),edit);assert.equal(document.activeElement,$('prompt'));
assert.equal((await api('/api/draft?session='+encodeURIComponent(session))).text,newer);
await $('task').onsubmit({preventDefault(){}});await pollActivity();
const sent=net.filter(r=>r.method==='POST'&&r.path==='/api/turn').at(-1).body;
assert.notEqual(sent.token,body.token);assert(!sent.retry);assert.equal(sent.text,newer);assert.equal(sent.mode,'plan');
assert.equal(currentTurn,'replacement-accepted');assert.equal($('prompt').value,'');assert.equal(document.activeElement,$('prompt'));
''', retained=[{'session': original['session'], 'token': original['token']}])
        self.assertEqual([r['method'] for r in self.transport], ['thread/resume', 'thread/start', 'turn/start'])
        self.assertEqual(self.transport[-1]['params']['input'][0]['text'], NEWER)
        self.assertEqual(self.transport[-1]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual(f.desk.store.get(f.identifier)['status'], 'completed')
        self.assertEqual(followup_snapshot(f.desk.store, f.identifier), f.preparation)

    def test_unknown_mismatch_discovered_from_blank_fresh_page_cannot_resolve_send_or_open_native(self):
        f = self.f; original = self.blank_fallback(unknown=True)
        current = load_draft(f.desk.store, f.identifier)
        save_draft(f.desk.store, f.identifier, '', 'plan', current['revision'], str(uuid.uuid4()), 1)
        f.request('/api/followups/clear', {'session': f.identifier, 'order': [r['id'] for r in f.preparation['entries']]})
        self.cold()
        before = (f.desk.store.sessions(), f.desk.store.events(f.identifier), load_draft(f.desk.store, f.identifier), followup_snapshot(f.desk.store, f.identifier))
        javascript = f.javascript
        f.javascript = lambda body, retained=None: javascript(body, retained).replace("assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');", "assert.equal($('prompt').value,'');assert.equal($('turn-mode').value,'plan');", 1)
        with patch('codex_desk.server.Runtime', side_effect=AssertionError('Unknown mismatch discovery invoked native')):
            f.node_case(r'''
assert.equal(turnRequest(session),undefined);assert.equal($('prompt').value,'');
await open(session,{revealLatest:false});const request=turnRequest(session);
assert.equal(request.token,ORIGINAL_TOKEN);assert.equal(request.status,'needs_review');assert(request.result.request.binding_mismatch);
assert.equal(request.body.text,text);assert.equal($('prompt').value,'','Discovering old work must not invent or replace the blank current Plan');
assert(!$('turn-request').hidden);assert(!$('turn-request-binding').hidden);assert($('turn-request-new').hidden);assert($('turn-request-retry').disabled);
assert($('turn-request-accepted').hidden&&$('turn-request-rejected').hidden);assert($('followup-send').disabled);
await $('turn-request-new').onclick();await $('turn-request-retry').onclick();await $('turn-request-accepted').onclick();await $('turn-request-rejected').onclick();await $('task').onsubmit({preventDefault(){}});await $('followup-send').onclick();
assert(net.every(r=>r.method==='GET'));assert(!net.some(r=>r.path==='/api/open'));assert(net.some(r=>r.path==='/api/turn/request?session='+encodeURIComponent(session)));
assert.equal($('prompt').value,'');assert.equal($('turn-mode').value,'plan');assert.equal(document.activeElement,$('prompt'));
'''.replace('ORIGINAL_TOKEN', json.dumps(original['token'])))
            for outcome in ('accepted', 'rejected'):
                self.assertEqual(f.request('/api/turn/resolve', {'session': f.identifier, 'token': original['token'], 'outcome': outcome})[0], 409)
            self.assertEqual(f.request('/api/turn', {**original, 'retry': True})[0], 409)
            self.assertEqual(f.request('/api/turn', {**original, 'token': str(uuid.uuid4())})[0], 409)
        self.assertEqual((f.desk.store.sessions(), f.desk.store.events(f.identifier), load_draft(f.desk.store, f.identifier), followup_snapshot(f.desk.store, f.identifier)), before)
        self.assertEqual(len(self.transport), 2)

    def test_blank_fresh_page_discovers_same_target_unknown_and_normal_none_404_opens_normally(self):
        f = self.f; original = f.capture();f.native_mode='unknown'
        self.assertEqual(f.request('/api/turn', original)[1]['request']['status'], 'needs_review')
        current=load_draft(f.desk.store,f.identifier);save_draft(f.desk.store,f.identifier,'','plan',current['revision'],str(uuid.uuid4()),1)
        f.request('/api/followups/clear', {'session':f.identifier,'order':[e['id'] for e in f.preparation['entries']]})
        self.cold();before=f.desk.store.events(f.identifier)
        javascript=f.javascript
        f.javascript=lambda body,retained=None:javascript(body,retained).replace("assert.equal($('prompt').value,text);assert.equal($('turn-mode').value,'plan');", "assert.equal($('prompt').value,'');assert.equal($('turn-mode').value,'plan');",1)
        with patch('codex_desk.server.Runtime',side_effect=AssertionError('Cold blank discovery attached native')):
            f.node_case(r'''
await open(session,{revealLatest:false});const request=turnRequest(session);
assert.equal(request.token,ORIGINAL_TOKEN);assert.equal(request.status,'needs_review');assert(!request.result.request.binding_mismatch);
assert(!$('turn-request-accepted').hidden&&!$('turn-request-rejected').hidden);assert(!$('turn-request').hidden);
assert.equal($('prompt').value,'');assert(net.every(r=>r.method==='GET'));assert(!net.some(r=>r.path==='/api/open'));
'''.replace('ORIGINAL_TOKEN',json.dumps(original['token'])))
        self.assertEqual(f.desk.store.events(f.identifier),before)
        self.assertEqual(f.request('/api/turn/request?session='+f.identifier)[1]['token'],original['token'])
        self.assertEqual(f.request('/api/turn/resolve',{'session':f.identifier,'token':original['token'],'outcome':'rejected'})[0],200)
        self.assertEqual(f.request('/api/turn/request?session='+f.identifier)[0],404,'Discovery must not auto-adopt known rejected history')
        f.remount_native_transport()
        f.node_case(r'''
await open(session,{revealLatest:false});assert.equal(turnRequest(session),undefined);
assert(net.some(r=>r.method==='GET'&&r.path==='/api/turn/request?session='+encodeURIComponent(session)));
assert.equal(net.filter(r=>r.method==='POST'&&r.path==='/api/open').length,1);
assert(!net.some(r=>r.method==='POST'&&r.path==='/api/turn'));assert.equal($('prompt').value,'');
''')
        self.assertEqual(len(f.requests),1)

    def test_projection_is_legacy_equal_for_50000_native_deltas_reordered_escaped_records_and_false_positive_quotes(self):
        f=self.f;original=f.capture();f.native_mode='rejected';f.request('/api/turn',original)
        intent,receipt=_records(f.desk,f.identifier)
        logical_receipt={**receipt[original['token']],'attempt':7,'error':'Imported reordered escaped receipt'}
        raw_receipt=json.dumps({'params':logical_receipt,'method':'desk/turnReceipt'}).replace('desk/turnReceipt',r'desk\/turn\u0052eceipt')
        raw_intent=json.dumps({'params':intent[original['token']],'method':'desk/turnIntent'},ensure_ascii=False)
        quoted=json.dumps({'method':'item/agentMessage/delta','params':{'threadId':'native-original','itemId':'stream','delta':json.dumps({'method':'desk/turnReceipt','params':{'token':original['token'],'status':'accepted','attempt':999}})}})
        native=json.dumps({'params':{'threadId':'native-original','turnId':'large-history','itemId':'stream','delta':'x'*145},'method':'item/agentMessage/delta'})
        with f.desk.store.lock,f.desk.store.db:
            f.desk.store.db.executemany('INSERT INTO events(session_id,payload) VALUES(?,?)',[(f.identifier,native)]*50_000)
            f.desk.store.db.executemany('INSERT INTO events(session_id,payload) VALUES(?,?)',[(f.identifier,raw_intent),(f.identifier,raw_receipt),(f.identifier,quoted)])
        schema=f.desk.store.db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall()
        expected_intents,expected_receipts={},{}
        def legacy_records():
            one,two={},{}
            for r in f.desk.store.events(f.identifier):
                event=r['event'];params=event.get('params',{})
                if event.get('method')=='desk/turnIntent':one[params['token']]=params
                elif event.get('method')=='desk/turnReceipt':two[params['token']]=params
            return one,two
        expected_intents,expected_receipts=legacy_records()
        self.assertEqual(_records(f.desk,f.identifier),(expected_intents,expected_receipts))
        self.assertEqual(turn_status(f.desk,f.identifier,original['token'])['request']['attempt'],7)
        self.assertEqual(turn_status(f.desk,f.identifier,original['token'])['request']['status'],'rejected')
        bytes_total=f.desk.store.db.execute('SELECT sum(length(CAST(payload AS BLOB))) FROM events WHERE session_id=?',(f.identifier,)).fetchone()[0]
        self.assertGreater(bytes_total,12_000_000)
        calls=[];loads=json.loads
        def counted(raw,*args,**kwargs):calls.append(len(raw));return loads(raw,*args,**kwargs)
        with patch.object(f.desk.store,'events',side_effect=AssertionError('Admission read materialized the native event stream')),patch('codex_desk.turn_dispatch.json.loads',side_effect=counted):
            status=turn_status(f.desk,f.identifier,original['token']);cursor=turn_cursor(f.desk,f.identifier)
            self.assertEqual(status['request']['attempt'],7);self.assertEqual(len(calls),5)
            self.assertLess(sum(calls),10_000)
        self.assertEqual(cursor,f.desk.store.db.execute('SELECT max(seq) FROM events WHERE session_id=?',(f.identifier,)).fetchone()[0])
        timings=[];baseline=[]
        for _ in range(7):
            start=time.perf_counter();turn_status(f.desk,f.identifier,original['token']);timings.append((time.perf_counter()-start)*1000)
        for _ in range(3):
            start=time.perf_counter();legacy_records();baseline.append((time.perf_counter()-start)*1000)
        self.assertLess(statistics.median(timings),statistics.median(baseline)/2)
        self.assertEqual(f.desk.store.db.execute('SELECT type,name,sql FROM sqlite_master ORDER BY type,name').fetchall(),schema)
        self.record(self._testMethodName,{'native_deltas':50_000,'stream_bytes':bytes_total,'projection_equal':True,'quoted_false_positive_excluded':True,'reordered_escaped_admission_preserved':True,'python_decoded_records':len(calls),'python_decoded_bytes':sum(calls),'tail_seq':cursor,'projected_status_ms':timings,'legacy_full_records_ms':baseline,'projection_median_ms':statistics.median(timings),'legacy_median_ms':statistics.median(baseline),'schema_unchanged':True})


if __name__=='__main__':unittest.main()
