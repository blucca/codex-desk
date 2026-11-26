"""Explicit prepared-task HTTP admission with controlled native transport."""
import http.client
import json
import queue
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

from codex_desk.runtime import Runtime, NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import Desk, handler
from codex_desk.drafts import load_draft, save_draft
from http.server import ThreadingHTTPServer
from test_approval_lifecycle import NativeHTTPFixture, ROOT
from pathlib import Path


class FollowupApiTests(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.desk.store.update(self.identifier, status='ready')
        self.runtime.lock = threading.Lock()
        self.runtime.pending = {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()

    def get(self, session=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('GET', '/api/followups?session=' + (session or self.identifier))
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def add(self, text='Next exact verification', mode='native'):
        status, snapshot = self.post('/api/followups', text=text, mode=mode)
        self.assertEqual(status, 200)
        return snapshot['entries'][-1]

    def send(self, entry):
        return self.post('/api/followups/send', id=entry['id'], revision=entry['revision'])

    def resolve(self, reservation, outcome):
        return self.post('/api/followups/resolve', token=reservation['token'],
                         id=reservation['entry_id'], revision=reservation['revision'], outcome=outcome)

    def finish(self):
        with self.runtime.lifecycle_lock:
            self.runtime._message(self.completed())

    def test_prepare_edit_order_remove_clear_is_a_snapshot_without_native_work(self):
        before = self.desk.store.get(self.identifier)
        one, two = self.add('  Exact first task\nwith spaces  ', 'plan'), self.add('Second task')
        self.assertEqual(self.get()[1], {'entries': [one, two], 'reservation': None})
        status, snapshot = self.post('/api/followups/edit', id=one['id'], text='Edited task',
                                     mode='native', revision=one['revision'])
        self.assertEqual(status, 200)
        edited = snapshot['entries'][0]
        self.assertEqual(edited['revision'], one['revision'] + 1)
        self.assertEqual(self.post('/api/followups/edit', id=one['id'], text='Stale', mode='plan', revision=1)[0], 409)
        self.assertEqual(self.post('/api/followups/send', id=two['id'], revision=two['revision'])[0], 409)
        status, snapshot = self.post('/api/followups/reorder', ids=[two['id'], one['id']],
                                     order=[one['id'], two['id']])
        self.assertEqual(status, 200)
        self.assertEqual([entry['id'] for entry in snapshot['entries']], [two['id'], one['id']])
        self.assertEqual(self.post('/api/followups/clear', order=[one['id'], two['id']])[0], 409)
        self.assertEqual(self.post('/api/followups/clear', order=None)[0], 400)
        status, snapshot = self.post('/api/followups/remove', id=two['id'], revision=snapshot['entries'][0]['revision'])
        self.assertEqual(status, 200)
        self.assertEqual(self.post('/api/followups/clear', order=[one['id']]),
                         (200, {'entries': [], 'reservation': None}))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.desk.store.get(self.identifier), before)

    def test_explicit_first_send_admits_one_captured_session_mode_and_leaves_next_paused(self):
        one, two = self.add('Plan this exact project', 'plan'), self.add('Later task')
        status, snapshot = self.send(one)
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['receipt']['outcome'], 'accepted')
        self.assertTrue(snapshot['receipt']['consumed'])
        self.assertIsNone(snapshot['reservation'])
        self.assertEqual(snapshot['entries'][0]['id'], two['id'])
        request = self.requests[0]
        self.assertEqual(request['params']['threadId'], 'native-original')
        self.assertEqual(request['params']['input'], [{'type': 'text', 'text': one['text']}])
        self.assertEqual(request['params']['collaborationMode']['mode'], 'plan')
        self.finish()
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.get()[1]['entries'][0]['state'], 'queued')

    def test_live_send_cannot_be_resolved_or_duplicated_and_newer_same_text_survives(self):
        entry = self.add('Same words, newer intent')
        entered, release = threading.Event(), threading.Event()
        results = []

        def held(method, params):
            self.requests.append({'method': method, 'params': params})
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture start response not released')
            return {'turn': {'id': 'captured-task', 'status': 'inProgress'}}

        self.runtime.request = held
        worker = threading.Thread(target=lambda: results.append(self.send(entry)))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            reservation = self.get()[1]['reservation']
            self.assertEqual(self.resolve(reservation, 'rejected')[0], 409)
            self.assertEqual(self.resolve(reservation, 'accepted')[0], 409)
            self.assertEqual(self.send(entry)[0], 409)
            self.assertEqual(self.post('/api/turn', text='Other tab ordinary task')[0], 400)
            status, newer = self.post('/api/followups/edit', id=entry['id'], text=entry['text'],
                                      mode='plan', revision=entry['revision'])
            self.assertEqual(status, 200)
            self.assertEqual(newer['entries'][0]['revision'], entry['revision'] + 1)
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        status, snapshot = results[0]
        self.assertEqual(status, 200)
        self.assertFalse(snapshot['receipt']['consumed'])
        self.assertEqual(snapshot['entries'][0]['mode'], 'plan')
        self.assertEqual(snapshot['entries'][0]['state'], 'queued')
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]['params']['input'][0]['text'], entry['text'])
        self.assertNotIn('collaborationMode', self.requests[0]['params'])

    def test_definite_native_rejection_retains_queue_and_retry_is_explicit(self):
        entry = self.add('Keep until admitted', 'plan')

        def reject(method, params):
            self.requests.append({'method': method, 'params': params})
            raise NativeRequestRejected('Native fixture rejected this start')

        self.runtime.request = reject
        status, snapshot = self.send(entry)
        self.assertEqual(status, 400)
        self.assertEqual(snapshot['receipt']['outcome'], 'rejected')
        self.assertIsNone(snapshot['reservation'])
        self.assertEqual(snapshot['entries'], [entry])
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'ready')
        self.assertEqual(self.desk.store.get(self.identifier)['mode'], 'native')
        self.runtime.request = self.native_request
        self.assertEqual(self.send(entry)[0], 200)
        self.assertEqual(len(self.requests), 2)

    def test_timeout_is_unknown_blocks_normal_tasks_and_requires_exact_review(self):
        entry = self.add('Unconfirmed task', 'plan')

        def unknown(method, params):
            self.requests.append({'method': method, 'params': params})
            raise RuntimeError('Native Codex request timed out; stop Desk and reopen the session')

        self.runtime.request = unknown
        status, snapshot = self.send(entry)
        self.assertEqual(status, 400)
        self.assertEqual(snapshot['receipt']['outcome'], 'unknown')
        reservation = snapshot['reservation']
        self.assertEqual(reservation['state'], 'unknown')
        self.assertEqual(snapshot['entries'][0]['state'], 'needs_review')
        self.assertEqual(self.desk.store.get(self.identifier)['mode'], 'native')
        self.assertTrue(self.runtime.closing)
        self.assertNotIn(self.identifier, self.desk.runtimes)
        before = self.desk.store.get(self.identifier)
        self.native_request('turn/start', {'threadId': 'native-original'})
        self.assertEqual(self.desk.store.get(self.identifier), before)
        self.assertEqual(self.send(entry)[0], 409)
        self.assertEqual(self.post('/api/turn', text='Unsafe replay')[0], 409)
        self.assertEqual(self.post('/api/followups/resolve', token='old-token', id=entry['id'],
                                   revision=entry['revision'], outcome='rejected')[0], 409)
        self.assertEqual(self.resolve(reservation, 'unknown')[0], 400)
        self.assertEqual(self.resolve(reservation, 'rejected')[1]['entries'], [entry])
        self.assertEqual(self.desk.store.get(self.identifier)['mode'], 'native')
        self.assertEqual(len(self.requests), 2)  # Explicit late fixture event was ignored.

    def test_started_notification_proves_admission_when_response_is_lost(self):
        entry = self.add('One admitted turn')

        def started_then_lost(method, params):
            self.native_request(method, params)
            raise NativeRequestUnknown('Response transport lost')

        self.runtime.request = started_then_lost
        status, snapshot = self.send(entry)
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['receipt']['outcome'], 'accepted')
        self.assertEqual(snapshot['entries'], [])
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')
        self.assertEqual(len(self.requests), 1)

    def test_unknown_review_cannot_reject_a_later_proven_active_turn(self):
        entry = self.add('Possibly admitted')
        self.runtime.request = Mock(side_effect=NativeRequestUnknown('Unconfirmed response'))
        _, snapshot = self.send(entry)
        # Model an explicitly reopened, currently active native conversation.
        self.runtime.closing = False
        self.desk.runtimes[self.identifier] = self.runtime
        self.native_request('turn/start', {'threadId': 'native-original'})
        self.assertEqual(self.resolve(snapshot['reservation'], 'rejected')[0], 409)
        status, snapshot = self.resolve(snapshot['reservation'], 'accepted')
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['entries'], [])
        self.assertEqual(snapshot['receipt']['outcome'], 'accepted')

    def test_ordinary_unknown_task_retires_transport_and_ignores_late_native_start(self):
        self.runtime.request = Mock(side_effect=NativeRequestUnknown('Request timed out'))
        status, result = self.post('/api/turn', text='Ordinary unconfirmed task', mode='plan')
        self.assertEqual((status, result), (400, {'error': 'Request timed out'}))
        self.assertTrue(self.runtime.closing)
        self.assertNotIn(self.identifier, self.desk.runtimes)
        before = self.desk.store.get(self.identifier)
        self.assertEqual(before['mode'], 'native')
        self.native_request('turn/start', {'threadId': 'native-original'})
        self.assertEqual(self.desk.store.get(self.identifier), before)
        self.assertEqual(self.get()[1], {'entries': [], 'reservation': None})

    def test_ordinary_lost_reply_with_start_evidence_returns_admitted_turn(self):
        def started_then_lost(method, params):
            self.native_request(method, params)
            raise NativeRequestUnknown('Lost response')

        self.runtime.request = started_then_lost
        status, result = self.post('/api/turn', text='Known admitted task')
        self.assertEqual(status, 200)
        self.assertEqual(result['turn']['id'], 'follow-up-turn')
        self.assertFalse(self.runtime.closing)
        self.assertIs(self.desk.runtimes[self.identifier], self.runtime)

    def check_lost_plan_reply_preserves_next_work(self, queued, terminal):
        draft = save_draft(self.desk.store, self.identifier, 'Separate saved Plan draft', 'plan', 0)
        first = self.add('Review the project before implementing', 'plan') if queued else None
        later = self.add('Implement the reviewed change', 'native')
        native_outcome = {}

        def started_then_lost(method, params):
            self.native_request(method, params)
            with self.runtime.lifecycle_lock:
                self.runtime._message({'method': 'thread/tokenUsage/updated', 'params': {
                    'threadId': 'native-original', 'tokenUsage': {'total': {'totalTokens': 42}}}})
                completed = self.completed(terminal)
                if terminal == 'failed':
                    completed['params']['turn']['error'] = {'message': 'Fixture task failed'}
                self.runtime._message(completed)
                native_outcome.update(self.desk.store.get(self.identifier))
            raise NativeRequestUnknown('Lost native reply after Plan task')

        self.runtime.request = started_then_lost
        status, result = (self.send(first) if queued else
                          self.post('/api/turn', text='Review the project before implementing', mode='plan'))
        self.assertEqual(status, 200)
        self.assertEqual(self.requests[0]['params']['collaborationMode']['mode'], 'plan')
        recovered = self.desk.store.get(self.identifier)
        self.assertEqual(recovered['mode'], 'plan')
        for field in ('id', 'cwd', 'profile', 'thread_id', 'name', 'created', 'status', 'usage', 'error'):
            self.assertEqual(recovered[field], native_outcome[field], field)
        self.assertTrue(recovered['thread_saved'])
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)
        self.assertEqual(self.get()[1], {'entries': [dict(later, order=1)], 'reservation': None})
        if queued:
            self.assertEqual(result['receipt']['outcome'], 'accepted')
            self.assertTrue(result['receipt']['consumed'])
        self.runtime.request = self.native_request
        self.assertEqual(self.send(later)[0], 200)
        self.assertEqual(self.requests[-1]['params']['collaborationMode'], {
            'mode': 'default', 'settings': {'model': 'fixture-model', 'developer_instructions': None}})
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)

    def test_ordinary_lost_plan_reply_keeps_mode_after_fast_completion(self):
        self.check_lost_plan_reply_preserves_next_work(False, 'completed')

    def test_followup_lost_plan_reply_keeps_mode_and_native_failure(self):
        self.check_lost_plan_reply_preserves_next_work(True, 'failed')

    def test_accepted_review_records_captured_plan_not_newer_work_mode(self):
        draft = save_draft(self.desk.store, self.identifier, 'Separate saved Plan draft', 'plan', 0)
        first = self.add('Review the implementation approach', 'plan')
        later = self.add('Later Work task', 'native')
        self.runtime.request = Mock(side_effect=NativeRequestUnknown('Native reply unavailable'))
        _, unknown = self.send(first)
        captured = unknown['reservation']
        self.assertEqual(captured['mode'], 'plan')
        self.assertEqual(self.desk.store.get(self.identifier)['mode'], 'native')
        _, edited = self.post('/api/followups/edit', id=first['id'], text='Newer Work preparation',
                              mode='native', revision=first['revision'])
        before = self.desk.store.get(self.identifier)
        status, reviewed = self.resolve(captured, 'accepted')
        self.assertEqual(status, 200)
        self.assertFalse(reviewed['receipt']['consumed'])
        self.assertEqual(reviewed['entries'], [dict(edited['entries'][0], state='queued'), later])
        recovered = self.desk.store.get(self.identifier)
        self.assertEqual(recovered['mode'], 'plan')
        for field in ('id', 'cwd', 'profile', 'thread_id', 'name', 'created', 'status', 'usage', 'error'):
            self.assertEqual(recovered[field], before[field], field)
        self.assertTrue(recovered['thread_saved'])
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)
        # Match the existing explicit reopen fixture; confirmation itself starts no task.
        self.assertEqual(self.requests, [])
        self.runtime.closing = False
        self.desk.runtimes[self.identifier] = self.runtime
        self.desk.store.update(self.identifier, status='ready')
        self.runtime.request = self.native_request
        self.assertEqual(self.send(reviewed['entries'][0])[0], 200)
        self.assertEqual(self.requests[-1]['params']['collaborationMode']['mode'], 'default')
        self.assertEqual(self.get()[1]['entries'], [dict(later, order=1)])
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)

    def test_approval_or_question_retains_queue_without_dispatch(self):
        entry = self.add()
        for method in ('item/commandExecution/requestApproval', 'item/tool/requestUserInput'):
            with self.subTest(method=method):
                self.add_approval(method=method)
                status, snapshot = self.send(entry)
                self.assertEqual(status, 400)
                self.assertEqual(snapshot['receipt']['outcome'], 'rejected')
                self.assertIsNone(snapshot['reservation'])
                self.assertEqual(snapshot['entries'], [entry])
                self.assertEqual(self.desk.store.get(self.identifier)['status'], 'approval')
                self.assertEqual(len(self.runtime.approvals), 1)
                self.finish()
        self.assertEqual(self.requests, [])

    def test_resume_start_event_is_prior_work_not_this_queue_admission(self):
        entry = self.add('Prepared after existing work')
        original = self.desk.runtime

        def resume_active(identifier):
            with self.runtime.lifecycle_lock:
                self.runtime._message({'method': 'turn/started', 'params': {
                    'threadId': 'native-original', 'turn': {'id': 'resumed-prior-task', 'status': 'inProgress'}}})
            return original(identifier)

        self.desk.runtime = resume_active
        status, snapshot = self.send(entry)
        self.assertEqual(status, 400)
        self.assertEqual(snapshot['receipt']['outcome'], 'rejected')
        self.assertEqual(snapshot['entries'], [entry])
        self.assertEqual(self.requests, [])

    def test_other_session_or_invalid_scope_cannot_admit_this_entry(self):
        entry = self.add()
        other = self.desk.store.create(str(self.path), 'default', name='Other project')
        self.desk.store.update(other, status='ready', thread_id='native-other')
        self.assertEqual(self.post('/api/followups/send', session=other, id=entry['id'], revision=1)[0], 400)
        for identifier in ('missing', 'native-catalog'):
            self.assertEqual(self.get(identifier)[0], 400)
            self.assertEqual(self.post('/api/followups', session=identifier, text='Wrong project', mode='native')[0], 400)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.get()[1], {'entries': [entry], 'reservation': None})

    def test_plain_task_vs_queue_share_nonblocking_admission(self):
        entry = self.add()
        entered, release = threading.Event(), threading.Event()
        result = []

        def held(method, params):
            self.requests.append({'method': method, 'params': params})
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture not released')
            return {'turn': {'id': 'ordinary-turn', 'status': 'inProgress'}}

        self.runtime.request = held
        worker = threading.Thread(target=lambda: result.append(self.post('/api/turn', text='Ordinary task')))
        worker.start()
        try:
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.send(entry)[0], 409)
            self.assertIsNone(self.get()[1]['reservation'])
        finally:
            release.set()
            worker.join(3)
        self.assertEqual(result[0][0], 200)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.get()[1]['entries'], [entry])

    def test_unknown_snapshot_survives_actual_desk_restart_without_replay(self):
        entry = self.add('Revisit after restart', 'plan')
        self.runtime.request = Mock(side_effect=NativeRequestUnknown('Native app-server exited'))
        _, original = self.send(entry)
        status, snapshot = self.post('/api/followups/edit', id=entry['id'], text='Later edited goal',
                                     mode='native', revision=entry['revision'])
        self.assertEqual(status, 200)
        self.desk.store.db.close()
        restarted = Desk('never-launched', self.path, self.path / 'state')
        self.addCleanup(restarted.store.db.close)
        self.addCleanup(restarted.close)
        old = self.desk
        self.server.RequestHandlerClass = handler(restarted)
        self.desk = restarted
        try:
            self.assertEqual(self.get()[1], snapshot)
            self.assertEqual(restarted.runtimes, {})
            self.assertEqual(self.send(snapshot['entries'][0])[0], 409)
            self.assertEqual(self.post('/api/turn', text='Do not replay')[0], 409)
            status, resolved = self.resolve(original['reservation'], 'accepted')
            self.assertEqual(status, 200)
            self.assertFalse(resolved['receipt']['consumed'])
            self.assertEqual(resolved['entries'][0]['text'], 'Later edited goal')
            self.assertEqual(resolved['entries'][0]['state'], 'queued')
            self.assertEqual(restarted.runtimes, {})
        finally:
            self.desk = old


class NativeAdmissionErrorTests(unittest.TestCase):
    def fixture(self, message=None, fail=False):
        runtime = object.__new__(Runtime)
        runtime.lock = threading.Lock()
        runtime.pending, runtime.counter = {}, 0

        def send(payload):
            if fail:
                raise BrokenPipeError('Closed native pipe')
            if message is not None:
                runtime.pending[payload['id']].put(message)

        runtime.send = send
        return runtime

    def test_only_actual_native_error_is_a_definite_rejection(self):
        rejected = self.fixture({'error': {'code': -32000, 'message': 'Native start rejected'}})
        with self.assertRaisesRegex(NativeRequestRejected, 'Native start rejected'):
            rejected.request('turn/start', {})
        for runtime in (self.fixture(), self.fixture(fail=True), self.fixture({'unexpected': True})):
            with self.assertRaises(NativeRequestUnknown):
                runtime.request('turn/start', {}, timeout=.01)
            self.assertEqual(runtime.pending, {})

    def test_exited_waiter_is_unknown_with_existing_error_shape_retained(self):
        runtime = self.fixture()
        pending = queue.Queue()
        runtime.pending['old-waiter'] = pending
        runtime._fail_pending()
        message = pending.get_nowait()
        self.assertEqual(message['error']['message'], 'Codex app-server exited')
        runtime = self.fixture(message)
        with self.assertRaisesRegex(NativeRequestUnknown, 'Codex app-server exited'):
            runtime.request('turn/start', {})


class FollowupStdioTests(unittest.TestCase):
    def test_real_http_and_native_stdio_admission_rejection_exit_restart(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        home = root / 'home'
        home.mkdir()
        config, auth = home / 'config.toml', home / 'auth.json'
        config.write_text('model="original-model"\n')
        auth.write_text('{"fixture":"original auth"}\n')
        originals = config.read_bytes(), auth.read_bytes()
        launcher = root / 'native-fixture'
        launcher.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
for line in sys.stdin:
    message = json.loads(line)
    with (home / 'requests.jsonl').open('a') as log:
        log.write(json.dumps(message) + '\\n')
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        result = {}
    elif method == 'thread/resume':
        result = {'thread': {'id': params['threadId'], 'turns': []},
                  'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
    elif method == 'turn/start':
        text = params['input'][0]['text']
        if text == 'Exit without reply':
            sys.exit(0)
        if text == 'Reject this task':
            print(json.dumps({'id': message['id'], 'error': {
                'code': -32602, 'message': 'Definite native fixture rejection'}}), flush=True)
            continue
        turn = {'id': 'fixture-turn', 'status': 'inProgress'}
        print(json.dumps({'method': 'turn/started', 'params': {
            'threadId': params['threadId'], 'turn': turn}}), flush=True)
        print(json.dumps({'id': message['id'], 'result': {'turn': turn}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {
            'threadId': params['threadId'], 'turn': {**turn, 'status': 'completed'}}}), flush=True)
        continue
    elif method == 'thread/name/set':
        result = {}
    else:
        continue
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
        launcher.chmod(0o700)
        desk = Desk(str(launcher), home, root / 'state')
        self.addCleanup(desk.store.db.close)
        self.addCleanup(desk.close)
        identifier = desk.store.create(str(root), 'default', name='Fixture project')
        desk.store.update(identifier, thread_id='native-original', thread_saved=1,
                          status='saved', name_pending=0)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join(2)

        self.addCleanup(stop_server)

        def call(path, fields=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                if fields is None:
                    connection.request('GET', path + '?session=' + identifier)
                else:
                    connection.request('POST', path, json.dumps({'session': identifier, **fields}),
                                       {'Content-Type': 'application/json'})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        self.assertEqual(call('/api/followups'), (200, {'entries': [], 'reservation': None}))
        self.assertEqual(desk.runtimes, {})
        _, snapshot = call('/api/followups', {'text': 'Plan one project task', 'mode': 'plan'})
        first = snapshot['entries'][0]
        status, snapshot = call('/api/followups/send', {'id': first['id'], 'revision': first['revision']})
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['receipt']['outcome'], 'accepted')
        self.assertEqual(snapshot['entries'], [])
        _, snapshot = call('/api/followups', {'text': 'Reject this task', 'mode': 'native'})
        second = snapshot['entries'][0]
        status, rejected = call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})
        self.assertEqual(status, 400)
        self.assertEqual(rejected['receipt']['outcome'], 'rejected')
        self.assertEqual(rejected['entries'], [second])
        _, snapshot = call('/api/followups/edit', {'id': second['id'], 'revision': second['revision'],
                                                  'text': 'Exit without reply', 'mode': 'native'})
        second = snapshot['entries'][0]
        original_runtime = desk.runtimes[identifier]
        status, unknown = call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})
        self.assertEqual(status, 400)
        self.assertEqual(unknown['receipt']['outcome'], 'unknown')
        self.assertTrue(original_runtime.closing)
        self.assertIsNotNone(original_runtime.process.poll())
        self.assertEqual(desk.runtimes, {})
        self.assertEqual(call('/api/turn', {'text': 'No replay'})[0], 409)
        desk.close()
        desk.store.db.close()
        restarted = Desk(str(launcher), home, root / 'state')
        self.addCleanup(restarted.store.db.close)
        self.addCleanup(restarted.close)
        server.RequestHandlerClass = handler(restarted)
        self.assertEqual(call('/api/followups')[1]['reservation'], unknown['reservation'])
        self.assertEqual(restarted.runtimes, {})
        self.assertEqual(call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})[0], 409)
        reservation = unknown['reservation']
        status, reviewed = call('/api/followups/resolve', {'token': reservation['token'],
            'id': reservation['entry_id'], 'revision': reservation['revision'], 'outcome': 'rejected'})
        self.assertEqual(status, 200)
        self.assertEqual(reviewed['entries'][0]['state'], 'queued')
        self.assertIsNone(reviewed['reservation'])
        requests = [json.loads(line) for line in (home / 'requests.jsonl').read_text().splitlines()]
        turns = [request for request in requests if request.get('method') == 'turn/start']
        self.assertEqual(len(turns), 3)
        self.assertTrue(all(turn['params']['threadId'] == 'native-original' for turn in turns))
        self.assertEqual(turns[0]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual((config.read_bytes(), auth.read_bytes()), originals)


if __name__ == '__main__':
    unittest.main()
