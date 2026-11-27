"""Independent same-turn native steering contracts through real Desk admission."""
import copy
import json
from http.server import ThreadingHTTPServer
import threading
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from unittest.mock import Mock
import uuid

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import Desk, handler
from codex_desk.turn_records import request_records
from test_approval_lifecycle import NativeHTTPFixture


PARENT = 'native-original'
TURN = 'active-parser-tests'
INSTRUCTION = 'Skip integration tests; run parser unit tests — 保留 <&>  '


class SteerContractFixture(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.other = self.desk.store.create(str(self.path), 'default', name='Other retained Plan')
        self.desk.store.update(self.other, thread_id='other-native-parent', status='ready', mode='plan')
        self.desk.store.update(self.identifier, status='ready', mode='plan')
        for session in [self.identifier, self.other]:
            save_draft(self.desk.store, session, 'Retained main Plan — ' + session + '  ', 'plan', 0)
            add_followup(self.desk.store, session, 'Prepared Work — ' + session, 'native')
            add_followup(self.desk.store, session, 'Prepared Plan — ' + session, 'plan')
        self.emit('turn/started', {'threadId': PARENT, 'turn': {'id': TURN, 'status': 'inProgress'}})
        self.emit('item/completed', {'threadId': PARENT, 'turnId': TURN, 'item': {
            'id': 'inspect', 'type': 'commandExecution', 'command': 'Inspect parser tests',
            'aggregatedOutput': 'parser tests inspected', 'status': 'completed', 'exitCode': 0,
        }})
        self.emit('turn/plan/updated', {'threadId': PARENT, 'turnId': TURN, 'plan': [
            {'step': 'Inspect parser', 'status': 'completed'}, {'step': 'Run focused tests', 'status': 'inProgress'},
        ]})
        self.initial_preparation = self.preparation()
        self.initial_tables = self.table_names()
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.addCleanup(self.release.set)
        self.native_failure = None
        self.native_result = None
        self.before_native_reply = None
        self.runtime.request = self.controlled_native
        self.forbid_work(self.desk)

    def forbid_work(self, desk):
        desk.open = Mock(side_effect=AssertionError('Steering must not open a conversation'))
        desk.runtime = Mock(side_effect=AssertionError('Steering must use an existing runtime'))
        desk.retire_runtime = Mock(side_effect=AssertionError('Steering must not stop the native task'))

    def emit(self, method, params):
        with self.runtime.lifecycle_lock:
            self.runtime._message({'method': method, 'params': params})

    def preparation(self):
        return {session: {
            'draft': load_draft(self.desk.store, session),
            'queue': followup_snapshot(self.desk.store, session),
            'mode': self.desk.store.get(session)['mode'],
            'run_requests': request_records(self.desk.store, session),
        } for session in [self.identifier, self.other]}

    def table_names(self):
        return [row[0] for row in self.desk.store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]

    def body(self, **changes):
        return {'session': self.identifier, 'token': str(uuid.uuid4()), 'threadId': PARENT,
                'expectedTurnId': TURN, 'text': INSTRUCTION, **changes}

    def controlled_native(self, method, params):
        self.requests.append({'method': method, 'params': copy.deepcopy(params)})
        self.assertEqual(method, 'turn/steer')
        self.entered.set()
        self.assertTrue(self.release.wait(5), 'Native reply was not released')
        if self.before_native_reply:
            done = threading.Event()
            def receive():
                try:
                    self.before_native_reply()
                except Exception as error:
                    self.native_errors.append(error)
                finally:
                    done.set()
            worker = threading.Thread(target=receive, daemon=True)
            self.native_threads.append(worker)
            worker.start()
            self.assertTrue(done.wait(2), 'Steering blocked native notifications while waiting for its reply')
        if self.native_failure:
            raise self.native_failure
        return copy.deepcopy(self.native_result) if self.native_result is not None else {'turnId': params['expectedTurnId']}

    def call(self, path, body=None):
        request = Request(f'http://127.0.0.1:{self.server.server_port}' + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=8) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def send(self, body, expected='accepted'):
        status, receipt = self.call('/api/steer', body)
        self.assertEqual(status, 200, receipt)
        self.assertEqual((receipt['session'], receipt['token']), (body['session'], body['token']))
        self.assertEqual(receipt['request']['status'], expected)
        self.assertEqual(receipt['request']['payload'], body)
        return receipt

    def read(self, body):
        return self.call('/api/steer/request?' + urlencode({'session': body['session'], 'token': body['token']}))

    def unchanged(self):
        self.assertEqual(self.preparation(), self.initial_preparation)
        self.assertEqual(self.table_names(), self.initial_tables)
        self.assertEqual(self.sent, [])
        self.desk.open.assert_not_called()
        self.desk.runtime.assert_not_called()
        self.desk.retire_runtime.assert_not_called()

    def cold_owner(self, home=None):
        self.close_server()
        self.desk = Desk('unused-fake-native', home or self.path, self.path / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.forbid_work(self.desk)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()


class SteerNativeContractTests(SteerContractFixture):
    def test_active_parent_turn_projection_ignores_child_requests_and_steer_receipts(self):
        from codex_desk.runtime import active_turn_id
        self.assertEqual(active_turn_id(self.desk.store, self.identifier, PARENT), TURN)
        for event in [
            {'method': 'turn/started', 'params': {'threadId': 'native-child', 'turn': {'id': 'child'}}},
            {'method': 'turn/completed', 'params': {'threadId': 'native-child', 'turn': {'id': TURN, 'status': 'completed'}}},
            {'id': 17, 'method': 'turn/started', 'params': {'threadId': PARENT, 'turn': {'id': 'request-not-notification'}}},
            {'method': 'desk/steerReceipt', 'params': {'status': 'accepted', 'result': {'turnId': 'not-a-turn-boundary'}}},
        ]:
            self.desk.store.event(self.identifier, event)
        self.assertEqual(active_turn_id(self.desk.store, self.identifier, PARENT), TURN)
        self.desk.store.event(self.identifier, {'method': 'turn/started', 'params': {
            'threadId': PARENT, 'turn': {'id': 'new-parent-turn'},
        }})
        self.desk.store.event(self.identifier, {'method': 'turn/completed', 'params': {
            'threadId': PARENT, 'turn': {'id': TURN, 'status': 'completed'},
        }})
        self.assertEqual(active_turn_id(self.desk.store, self.identifier, PARENT), 'new-parent-turn')
        self.desk.store.event(self.identifier, {'method': 'turn/completed', 'params': {
            'threadId': PARENT, 'turn': {'id': 'new-parent-turn', 'status': 'interrupted'},
        }})
        self.assertIsNone(active_turn_id(self.desk.store, self.identifier, PARENT))
        self.unchanged()

    def test_runtime_rechecks_parent_current_turn_and_live_process_before_native_dispatch(self):
        for thread, expected in [('native-child', TURN), (PARENT, 'old-turn')]:
            with self.subTest(thread=thread, expected=expected):
                with self.assertRaises(ValueError):
                    self.runtime.steer(thread, expected, INSTRUCTION)
        self.runtime.process.poll.return_value = 1
        with self.assertRaises(ValueError):
            self.runtime.steer(PARENT, TURN, INSTRUCTION)
        self.runtime.process.poll.return_value = None
        self.runtime.closing = True
        with self.assertRaises(ValueError):
            self.runtime.steer(PARENT, TURN, INSTRUCTION)
        self.assertEqual(self.requests, [])
        self.unchanged()

    def test_exact_same_turn_request_during_approval_leaves_main_work_unchanged(self):
        self.add_approval('19')
        before = self.desk.store.get(self.identifier)
        before_events = self.desk.store.events(self.identifier)
        approvals = copy.deepcopy(self.runtime.approvals)
        body = self.body()
        receipt = self.send(body)
        self.assertEqual(receipt['request']['result'], {'turnId': TURN})
        self.assertTrue(receipt['request']['target_current'])
        self.assertFalse(receipt['request']['binding_mismatch'])
        self.assertEqual(receipt['request']['binding']['turn_id'], TURN)
        self.assertEqual(receipt['request']['current_binding']['turn_id'], TURN)
        self.assertEqual(self.requests, [{'method': 'turn/steer', 'params': {
            'threadId': PARENT, 'expectedTurnId': TURN, 'input': [{'type': 'text', 'text': INSTRUCTION}],
        }}])
        self.assertEqual(self.desk.store.get(self.identifier), before)
        self.assertEqual(self.runtime.approvals, approvals)
        additions = self.desk.store.events(self.identifier)[len(before_events):]
        self.assertTrue(additions)
        self.assertTrue(all(row['event']['method'].startswith('desk/steer') for row in additions))
        self.unchanged()

    def test_known_native_rejection_and_unknown_transport_remain_distinct(self):
        for failure, expected in [(NativeRequestRejected('activeTurnNotSteerable: approval pending'), 'rejected'),
                                  (NativeRequestUnknown('Native reply unavailable'), 'needs_review')]:
            with self.subTest(status=expected):
                self.native_failure = failure
                body = self.body()
                before = self.desk.store.get(self.identifier)
                receipt = self.send(body, expected)
                self.assertIn(str(failure), receipt['request']['error'])
                count = len(self.requests)
                self.send(body, expected)
                self.assertEqual(len(self.requests), count)
                self.assertEqual(self.desk.store.get(self.identifier), before)
                self.unchanged()

    def test_turn_start_shaped_or_wrong_turn_native_success_is_unconfirmed(self):
        for result in [{'turn': {'id': TURN}}, {'turnId': 'another-turn'}, {'turnId': ''}, {'turnId': 7}]:
            with self.subTest(reply=result):
                # Each malformed reply belongs to a separately captured native turn.
                current_turn = 'validation-' + str(len(self.requests))
                self.emit('turn/started', {'threadId': PARENT, 'turn': {'id': current_turn, 'status': 'inProgress'}})
                self.native_result = result
                body = self.body(expectedTurnId=current_turn)
                receipt = self.send(body, 'needs_review')
                count = len(self.requests)
                self.send(body, 'needs_review')
                self.assertEqual(len(self.requests), count)
                self.assertNotEqual(receipt['request']['status'], 'accepted')
                self.unchanged()

    def test_real_completion_during_reply_retains_native_terminal_not_steer_status(self):
        self.before_native_reply = lambda: self.emit('turn/completed', {
            'threadId': PARENT, 'turn': {'id': TURN, 'status': 'completed'},
        })
        body = self.body()
        receipt = self.send(body)
        self.assertEqual(receipt['request']['result'], {'turnId': TURN})
        self.assertFalse(receipt['request']['target_current'])
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        self.send(body)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()
