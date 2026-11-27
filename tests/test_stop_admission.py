"""Captured Stop through actual HTTP/SQLite and controlled native boundaries."""
import http.client
import json
import socket
import threading
import unittest
import uuid
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from unittest.mock import Mock, patch

from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import Desk, handler
from codex_desk.stop_dispatch import _binding, INTENT, RECEIPT
from codex_desk.turn_records import request_records

THREAD, TURN = 'native-original', 'turn-A'


class StopFixture(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        spawn = patch('codex_desk.runtime.subprocess.Popen',
                      side_effect=AssertionError('Stop must not create a native process'))
        spawn.start()
        self.addCleanup(spawn.stop)
        self.other = 'other-plan'
        self.desk.store.create(str(self.path), 'default', identifier=self.other, name='Other Plan')
        self.desk.store.update(self.other, thread_id='native-other', status='ready', mode='plan')
        for sid in (self.identifier, self.other):
            save_draft(self.desk.store, sid, 'Exact unsent Plan ' + sid + ' 保留  ', 'plan', 0)
            add_followup(self.desk.store, sid, 'Prepared Work ' + sid, 'native')
            add_followup(self.desk.store, sid, 'Prepared Plan ' + sid, 'plan')
        self.start(TURN)
        self.initial = self.preparation()
        self.schema = self.table_schema()
        self.mode = 'accept'
        self.entered, self.release = threading.Event(), threading.Event()
        self.release.set()
        self.addCleanup(self.release.set)
        self.runtime.request = self.native_stop
        self.no_automatic_work()

    def no_automatic_work(self):
        self.desk.open = Mock(side_effect=AssertionError('Stop must not open or resume'))
        self.desk.runtime = Mock(side_effect=AssertionError('Stop must not auto-acquire runtime'))
        self.desk.retire_runtime = Mock(side_effect=AssertionError('Stop must not kill the native reader'))

    def emit(self, method, params):
        with self.runtime.lifecycle_lock:
            self.runtime._message({'method': method, 'params': params})

    def start(self, turn):
        self.emit('turn/started', {'threadId': THREAD, 'turn': {'id': turn, 'status': 'inProgress'}})

    def finish(self, turn, status='completed'):
        self.emit('turn/completed', {'threadId': THREAD, 'turn': {'id': turn, 'status': status}})

    def preparation(self):
        return {sid: {'draft': load_draft(self.desk.store, sid),
                      'queue': followup_snapshot(self.desk.store, sid),
                      'mode': self.desk.store.get(sid)['mode']}
                for sid in (self.identifier, self.other)}

    def table_schema(self):
        return [list(row) for row in self.desk.store.db.execute(
            'SELECT type,name,tbl_name,sql FROM sqlite_master WHERE sql IS NOT NULL ORDER BY type,name')]

    def unchanged(self):
        self.assertEqual(self.preparation(), self.initial)
        self.assertEqual(self.table_schema(), self.schema)
        self.assertEqual(request_records(self.desk.store, self.identifier), {})
        self.assertFalse(self.sent)
        self.desk.open.assert_not_called()
        self.desk.runtime.assert_not_called()
        self.desk.retire_runtime.assert_not_called()

    def body(self, **extra):
        return {'session': self.identifier, 'token': str(uuid.uuid4()),
                'threadId': THREAD, 'expectedTurnId': TURN, **extra}

    def native_stop(self, method, params):
        self.requests.append({'method': method, 'params': params})
        self.assertEqual(method, 'turn/interrupt')
        self.entered.set()
        self.assertTrue(self.release.wait(5), 'Controlled native Stop was not released')
        if self.mode == 'reject':
            raise NativeRequestRejected('Captured turn is no longer active')
        if self.mode == 'unknown':
            raise NativeRequestUnknown('Native Stop transport timed out')
        if self.mode == 'malformed':
            return None
        return {}

    def call(self, path, body=None):
        request = Request(f'http://127.0.0.1:{self.server.server_port}' + path,
                          data=json.dumps(body).encode() if body is not None else None,
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=7) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def send(self, body, expected='accepted'):
        status, result = self.call('/api/stop', body)
        self.assertEqual(status, 200, result)
        self.assertEqual((result['session'], result['token']), (body['session'], body['token']))
        self.assertEqual(result['request']['payload'], body)
        self.assertEqual(result['request']['status'], expected)
        return result

    def read(self, body):
        status, result = self.call('/api/stop?' + urlencode({'session': body['session'], 'token': body['token']}))
        self.assertEqual(status, 200, result)
        return result

    def cold_owner(self):
        self.close_server()
        self.desk = Desk('unused-fake-native', self.path, self.path / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.no_automatic_work()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()


class StopAdmissionTests(StopFixture):
    def test_ack_is_exact_parent_interrupt_not_synthetic_terminal_or_approval_clear(self):
        # Request IDs distinguish native approvals from ordinary notifications.
        with self.runtime.lifecycle_lock:
            self.runtime._message({'id': 17, 'method': 'item/fileChange/requestApproval',
                                   'params': {'threadId': THREAD, 'turnId': TURN}})
        before, approvals = self.desk.store.get(self.identifier), dict(self.runtime.approvals)
        result = self.send(self.body())['request']
        self.assertEqual(self.requests, [{'method': 'turn/interrupt', 'params': {'threadId': THREAD, 'turnId': TURN}}])
        self.assertEqual(result['result'], {})
        self.assertTrue(result['target_current'])
        self.assertIsNone(result['terminal_status'])
        self.assertEqual(self.desk.store.get(self.identifier), before)
        self.assertEqual(self.runtime.approvals, approvals)
        self.assertFalse(self.desk.stop_sends)
        self.unchanged()

    def test_duplicate_uuid_and_private_get_never_resend_or_write(self):
        body = self.body()
        first = self.send(body)
        before = self.desk.store.events(self.identifier)
        self.assertEqual(self.send(body), first)
        self.assertEqual(self.read(body), first)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_genuinely_lost_http_reply_recovers_same_receipt_without_resend(self):
        body = self.body()
        base = self.server.RequestHandlerClass

        class LoseReply(base):
            def reply(self, value, status=200):
                if isinstance(value, dict) and value.get('token') == body['token']:
                    self.close_connection = True
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                return super().reply(value, status)

        self.server.RequestHandlerClass = LoseReply
        with self.assertRaises((http.client.RemoteDisconnected, URLError)):
            self.call('/api/stop', body)
        self.server.RequestHandlerClass = base
        result = self.read(body)
        self.assertEqual(result['request']['status'], 'accepted')
        self.assertEqual(result['request']['result'], {})
        before = self.desk.store.events(self.identifier)
        self.send(body)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_held_reply_allows_native_terminal_and_does_not_stop_new_turn_or_approval(self):
        body, results, errors = self.body(), [], []
        self.release.clear()

        def first():
            try:
                results.append(self.send(body))
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=first)
        worker.start()
        try:
            self.assertTrue(self.entered.wait(2))
            self.finish(TURN, 'interrupted')
            self.start('turn-B')
            with self.runtime.lifecycle_lock:
                self.runtime._message({'id': 18, 'method': 'item/fileChange/requestApproval',
                                       'params': {'threadId': THREAD, 'turnId': 'turn-B'}})
            self.assertEqual(self.desk.store.get(self.identifier)['status'], 'approval')
        finally:
            self.release.set()
            worker.join(8)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        request = results[0]['request']
        self.assertFalse(request['target_current'])
        self.assertEqual(request['terminal_status'], 'interrupted')
        self.assertEqual(request['current_binding']['turn_id'], 'turn-B')
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'approval')
        self.assertEqual(set(self.runtime.approvals), {'18'})
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_pending_duplicate_get_and_other_identity_do_not_dispatch(self):
        body, errors = self.body(), []
        self.release.clear()

        def first():
            try:
                self.send(body)
            except BaseException as error:
                errors.append(error)

        worker = threading.Thread(target=first)
        worker.start()
        try:
            self.assertTrue(self.entered.wait(2))
            before = self.desk.store.events(self.identifier)
            self.assertEqual(self.read(body)['request']['status'], 'pending')
            self.send(body, 'pending')
            self.assertEqual(self.call('/api/stop', self.body())[0], 409)
            self.assertEqual(self.desk.store.events(self.identifier), before)
            self.assertEqual(len(self.requests), 1)
        finally:
            self.release.set()
            worker.join(8)
        self.assertFalse(worker.is_alive())
        self.assertFalse(errors, errors)
        self.unchanged()

    def test_captured_A_rejects_when_B_is_active_at_http_arrival(self):
        body = self.body()
        self.finish(TURN)
        self.start('turn-B')
        result = self.send(body, 'rejected')['request']
        self.assertFalse(result['target_current'])
        self.assertEqual(result['terminal_status'], 'completed')
        self.assertEqual(result['current_binding']['turn_id'], 'turn-B')
        self.assertFalse(self.requests)
        self.unchanged()

    def test_runtime_rechecks_boundary_after_local_dispatch_admission(self):
        original = self.runtime.interrupt

        def changed(thread, turn):
            self.finish(TURN)
            self.start('turn-B')
            return original(thread, turn)

        self.runtime.interrupt = changed
        self.send(self.body(), 'rejected')
        self.assertFalse(self.requests)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')
        self.unchanged()

    def test_native_race_receives_only_captured_turnId_and_rejection_is_retained(self):
        def native(method, params):
            self.requests.append({'method': method, 'params': params})
            self.finish(TURN)
            self.start('turn-B')
            raise NativeRequestRejected('turnId A is not active')

        self.runtime.request = native
        body = self.body()
        self.send(body, 'rejected')
        self.send(body, 'rejected')
        self.assertEqual(self.requests, [{'method': 'turn/interrupt', 'params': {'threadId': THREAD, 'turnId': TURN}}])
        self.assertEqual(self.read(body)['request']['terminal_status'], 'completed')
        self.unchanged()

    def test_completed_turn_cannot_be_interrupted_by_captured_or_legacy_route(self):
        self.finish(TURN)
        self.send(self.body(), 'rejected')
        self.assertEqual(self.call('/api/stop', {'session': self.identifier})[0], 400)
        with self.assertRaises(ValueError):
            self.runtime.interrupt()
        self.assertFalse(self.requests)
        self.unchanged()

    def test_response_only_or_child_turn_is_not_an_established_parent(self):
        self.finish(TURN)
        self.desk.store.update(self.identifier, status='running')
        self.desk.store.event(self.identifier, {'id': 77, 'method': 'turn/started',
                                               'params': {'threadId': THREAD, 'turn': {'id': 'response-only'}}})
        self.desk.store.event(self.identifier, {'method': 'turn/started',
                                               'params': {'threadId': 'native-child', 'turn': {'id': 'child-turn'}}})
        self.send(self.body(expectedTurnId='response-only'), 'rejected')
        self.send(self.body(threadId='native-child', expectedTurnId='child-turn'), 'rejected')
        self.assertFalse(self.requests)
        self.unchanged()

    def test_child_cached_boundaries_do_not_replace_parent_stop_target(self):
        self.desk.store.event(self.identifier, {'method': 'turn/started',
                                               'params': {'threadId': 'native-child', 'turn': {'id': 'child-turn'}}})
        self.desk.store.event(self.identifier, {'method': 'turn/completed',
                                               'params': {'threadId': 'native-child', 'turn': {'id': TURN, 'status': 'failed'}}})
        result = self.send(self.body())['request']
        self.assertIsNone(result['terminal_status'])
        self.assertEqual(self.requests[0]['params'], {'threadId': THREAD, 'turnId': TURN})
        self.unchanged()

    def test_changed_target_same_token_and_cross_session_token_are_conflicts(self):
        body = self.body()
        self.send(body)
        self.assertEqual(self.call('/api/stop', {**body, 'expectedTurnId': 'turn-B'})[0], 409)
        self.assertEqual(self.call('/api/stop', {**body, 'session': self.other, 'threadId': 'native-other'})[0], 409)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_changed_owner_reports_mismatch_and_duplicate_keeps_original_receipt(self):
        body = self.body()
        self.send(body)
        row = self.desk.store.get(self.identifier)
        for key, changed in (('cwd', str(self.path / 'other')), ('profile', 'other-profile'), ('thread_id', 'other-thread')):
            with self.subTest(owner=key):
                self.desk.store.update(self.identifier, **{key: changed})
                request = self.read(body)['request']
                self.assertTrue(request['binding_mismatch'])
                self.assertFalse(request['target_current'])
                self.send(body)
                self.desk.store.update(self.identifier, **{key: row[key]})
        home = self.desk.home
        self.desk.home = home / 'other-native-home'
        self.assertTrue(self.read(body)['request']['binding_mismatch'])
        self.send(body)
        self.desk.home = home
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_missing_disconnected_and_replaced_runtime_reject_without_open(self):
        runtime = self.desk.runtimes.pop(self.identifier)
        self.send(self.body(), 'rejected')
        self.desk.runtimes[self.identifier] = runtime
        runtime.process.poll.return_value = 0
        self.send(self.body(), 'rejected')
        runtime.process.poll.return_value = None
        for key, value in (('id', self.other), ('home', self.path / 'other-home'), ('store', Mock())):
            with self.subTest(runtime_owner=key):
                old = getattr(runtime, key)
                setattr(runtime, key, value)
                self.send(self.body(), 'rejected')
                setattr(runtime, key, old)
        self.assertFalse(self.requests)
        self.unchanged()

    def test_unknown_and_malformed_ack_need_review_and_never_resend_same_target(self):
        for mode in ('unknown', 'malformed'):
            with self.subTest(native=mode):
                turn = 'turn-' + mode
                self.start(turn)
                self.mode = mode
                body = self.body(expectedTurnId=turn)
                self.send(body, 'needs_review')
                before = self.desk.store.events(self.identifier)
                self.assertEqual(self.read(body)['request']['status'], 'needs_review')
                self.send(body, 'needs_review')
                self.assertEqual(self.call('/api/stop', self.body(expectedTurnId=turn))[0], 409)
                self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 2)
        self.unchanged()

    def test_unknown_A_is_not_inferred_accepted_by_terminal_or_new_B_and_B_uses_fresh_id(self):
        self.mode = 'unknown'
        body = self.body()
        self.send(body, 'needs_review')
        self.finish(TURN, 'interrupted')
        self.start('turn-B')
        request = self.read(body)['request']
        self.assertEqual(request['status'], 'needs_review')
        self.assertEqual(request['terminal_status'], 'interrupted')
        self.assertFalse(request['target_current'])
        self.send(body, 'needs_review')
        self.mode = 'accept'
        self.send(self.body(expectedTurnId='turn-B'))
        self.assertEqual([r['params']['turnId'] for r in self.requests], [TURN, 'turn-B'])
        self.unchanged()

    def test_native_rejection_is_recoverable_and_does_not_clear_current_approval(self):
        with self.runtime.lifecycle_lock:
            self.runtime._message({'id': 19, 'method': 'item/fileChange/requestApproval',
                                   'params': {'threadId': THREAD, 'turnId': TURN}})
        self.mode = 'reject'
        body = self.body()
        self.send(body, 'rejected')
        before = self.desk.store.get(self.identifier)
        self.send(body, 'rejected')
        self.assertEqual(self.read(body)['request']['status'], 'rejected')
        self.assertEqual(self.desk.store.get(self.identifier), before)
        self.assertEqual(set(self.runtime.approvals), {'19'})
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_actual_cold_owner_preserves_accepted_receipt_and_native_terminal(self):
        body = self.body()
        self.send(body)
        self.finish(TURN, 'interrupted')
        self.cold_owner()
        before = self.desk.store.events(self.identifier)
        request = self.read(body)['request']
        self.assertEqual(request['status'], 'accepted')
        self.assertEqual(request['terminal_status'], 'interrupted')
        self.send(body)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.assertFalse(self.desk.runtimes)
        self.unchanged()

    def test_abandoned_pending_cold_discovery_and_duplicate_are_store_only(self):
        body = self.body()
        self.desk.store.event(self.identifier, {'method': INTENT, 'params':
                                               {'token': body['token'], 'payload': body, 'binding': _binding(self.desk, self.identifier)}})
        self.desk.store.event(self.identifier, {'method': RECEIPT, 'params': {'token': body['token'], 'status': 'pending'}})
        self.cold_owner()
        before = self.desk.store.events(self.identifier)
        status, result = self.call('/api/stop?' + urlencode({'session': self.identifier}))
        self.assertEqual(status, 200)
        self.assertEqual(result['token'], body['token'])
        self.assertEqual(result['request']['status'], 'needs_review')
        self.send(body, 'needs_review')
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertFalse(self.requests)
        self.unchanged()

    def test_legacy_ack_shape_and_unknown_discovery_without_runtime_creation(self):
        self.assertEqual(self.call('/api/stop', {'session': self.identifier}), (200, {}))
        self.mode = 'unknown'
        self.assertEqual(self.call('/api/stop', {'session': self.identifier})[0], 400)
        status, result = self.call('/api/stop?' + urlencode({'session': self.identifier}))
        self.assertEqual(status, 200)
        self.assertEqual(result['request']['status'], 'needs_review')
        self.assertEqual(self.call('/api/stop', {'session': self.identifier})[0], 409)
        self.assertEqual(len(self.requests), 2)
        self.unchanged()

    def test_stop_is_available_during_unrelated_task_or_steer_admission(self):
        gate = self.desk.admission_lock(self.identifier)
        self.assertTrue(gate.acquire(blocking=False))
        self.desk.steer_sends[self.identifier] = 'held-steer'
        try:
            self.send(self.body())
        finally:
            gate.release()
            self.desk.steer_sends.clear()
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_body_and_query_validation_never_silently_ignore_target_fields(self):
        body = self.body()
        invalid = [{**body, 'token': 'bad'}, {**body, 'threadId': ''}, {**body, 'extra': True},
                   {'session': self.identifier, 'thread_id': THREAD, 'expected_turn_id': TURN},
                   {k: value for k, value in body.items() if k != 'expectedTurnId'}]
        before = self.desk.store.events(self.identifier)
        for value in invalid:
            self.assertEqual(self.call('/api/stop', value)[0], 400)
        for query in ('session=' + self.identifier + '&token=bad',
                      'session=' + self.identifier + '&session=other',
                      'session=' + self.identifier + '&extra=value'):
            self.assertEqual(self.call('/api/stop?' + query)[0], 400)
        self.assertEqual(self.call('/api/stop?' + urlencode({'session': self.identifier, 'token': body['token']}))[0], 404)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertFalse(self.requests)
        self.unchanged()


if __name__ == '__main__':
    unittest.main(verbosity=2)
