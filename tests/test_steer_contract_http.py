"""Immutable steering receipts across concurrent actions and cold HTTP return."""
import os
import threading
from urllib.parse import urlencode

from codex_desk.runtime import NativeRequestUnknown
from test_steer_contract import INSTRUCTION, PARENT, TURN, SteerContractFixture


class SteerReceiptHTTPTests(SteerContractFixture):
    def test_held_send_duplicate_read_and_mismatched_body_cannot_dispatch_twice(self):
        body = self.body()
        self.release.clear()
        receipts, errors = [], []
        def first_send():
            try:
                receipts.append(self.send(body))
            except BaseException as error:
                errors.append(error)
        worker = threading.Thread(target=first_send)
        worker.start()
        try:
            self.assertTrue(self.entered.wait(2))
            before = self.desk.store.events(self.identifier)
            status, current = self.read(body)
            self.assertEqual(status, 200)
            self.assertEqual(current['request']['status'], 'pending')
            self.send(body, 'pending')
            self.assertEqual(self.call('/api/steer', {**body, 'text': 'Different instruction'})[0], 409)
            self.assertEqual(self.call('/api/steer', self.body())[0], 409)
            self.assertEqual(self.desk.store.events(self.identifier), before)
            self.assertEqual(len(self.requests), 1)
        finally:
            self.release.set()
            worker.join(8)
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])
        self.assertEqual(len(receipts), 1)
        self.send(body)
        self.assertEqual(len(self.requests), 1)
        self.send(self.body(text='A second deliberate correction to the same task'))
        self.assertEqual(len(self.requests), 2)
        self.unchanged()

    def test_uuid_is_immutable_across_session_thread_turn_and_instruction(self):
        body = self.body()
        self.send(body)
        before = self.desk.store.events(self.identifier)
        for changes in [{'text': 'Different correction'}, {'expectedTurnId': 'another-turn'},
                        {'threadId': 'native-child'}, {'session': self.other, 'threadId': 'other-native-parent'}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.call('/api/steer', {**body, **changes})[0], 409)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_missing_or_noncurrent_runtime_and_foreign_parent_reject_without_opening(self):
        self.send(self.body(threadId='native-child'), 'rejected')
        self.assertEqual(self.requests, [])
        self.runtime.process.poll.return_value = 1
        self.send(self.body(), 'rejected')
        self.assertEqual(self.requests, [])
        self.runtime.process.poll.return_value = None
        self.runtime.closing = True
        self.send(self.body(), 'rejected')
        self.runtime.closing = False
        self.runtime.id = self.other
        self.send(self.body(), 'rejected')
        self.runtime.id = self.identifier
        self.runtime.home = self.path / 'another-native-home'
        self.send(self.body(), 'rejected')
        self.runtime.home = self.path
        original_store = self.runtime.store
        self.runtime.store = object()
        self.send(self.body(), 'rejected')
        self.runtime.store = original_store
        self.desk.runtimes.pop(self.identifier)
        self.send(self.body(), 'rejected')
        self.assertEqual(self.requests, [])
        self.unchanged()

    def test_cold_native_home_mismatch_keeps_original_instruction_read_only(self):
        body = self.body()
        self.send(body)
        self.cold_owner(home=self.path / 'replacement-native-home')
        before = self.desk.store.events(self.identifier)
        status, current = self.read(body)
        self.assertEqual(status, 200)
        self.assertEqual(current['request']['status'], 'accepted')
        self.assertTrue(current['request']['binding_mismatch'])
        self.assertFalse(current['request']['target_current'])
        self.assertNotEqual(current['request']['binding']['native_home'],
                            current['request']['current_binding']['native_home'])
        self.send(body)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.desk.runtimes, {})
        self.unchanged()

    def test_receipt_reads_are_exact_session_scoped_and_never_discover_accepted_work(self):
        body = self.body()
        self.send(body)
        before = self.desk.store.events(self.identifier)
        self.assertEqual(self.call('/api/steer/request?' + urlencode({
            'session': self.other, 'token': body['token'],
        }))[0], 404)
        self.assertEqual(self.call('/api/steer/request?' + urlencode({'session': self.identifier}))[0], 404)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_unconfirmed_instruction_is_not_proven_by_matching_text_or_a_new_turn(self):
        self.native_failure = NativeRequestUnknown('Native steer response lost')
        body = self.body()
        self.send(body, 'needs_review')
        self.emit('item/completed', {'threadId': PARENT, 'turnId': TURN, 'item': {
            'id': 'native-user-message', 'type': 'userMessage', 'content': [{'type': 'text', 'text': INSTRUCTION}],
        }})
        before = self.desk.store.events(self.identifier)
        status, current = self.read(body)
        self.assertEqual(status, 200)
        self.assertEqual(current['request']['status'], 'needs_review')
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(self.call('/api/steer', self.body())[0], 409)
        self.emit('turn/completed', {'threadId': PARENT, 'turn': {'id': TURN, 'status': 'completed'}})
        self.emit('turn/started', {'threadId': PARENT, 'turn': {'id': 'next-real-turn', 'status': 'inProgress'}})
        status, current = self.read(body)
        self.assertEqual(status, 200)
        self.assertEqual(current['request']['status'], 'needs_review')
        self.assertFalse(current['request']['target_current'])
        self.assertEqual(len(self.requests), 1)
        self.native_failure = None
        self.send(self.body(expectedTurnId='next-real-turn', text='Explicit instruction for the genuinely new turn'))
        self.assertEqual(self.requests[-1]['params']['expectedTurnId'], 'next-real-turn')
        self.send(body, 'needs_review')
        self.assertEqual(len(self.requests), 2)
        self.unchanged()

    def test_completed_capture_and_new_turn_never_rebase_or_start_work(self):
        accepted = self.body()
        self.send(accepted)
        self.emit('turn/completed', {'threadId': PARENT, 'turn': {'id': TURN, 'status': 'interrupted'}})
        self.send(self.body(), 'rejected')
        self.emit('turn/started', {'threadId': PARENT, 'turn': {'id': 'next-active', 'status': 'inProgress'}})
        old_target = self.send(self.body(), 'rejected')
        self.assertFalse(old_target['request']['target_current'])
        restored = self.send(accepted)
        self.assertEqual(restored['request']['result'], {'turnId': TURN})
        self.assertFalse(restored['request']['target_current'])
        self.assertEqual(len(self.requests), 1)
        self.send(self.body(expectedTurnId='next-active'))
        self.assertEqual(len(self.requests), 2)
        self.assertEqual([request['method'] for request in self.requests], ['turn/steer', 'turn/steer'])
        self.unchanged()

    def test_accepted_cold_return_and_duplicate_read_without_runtime_or_database_write(self):
        body = self.body()
        self.send(body)
        self.cold_owner()
        before = self.desk.store.events(self.identifier)
        status, restored = self.read(body)
        self.assertEqual(status, 200)
        self.assertEqual(restored['request']['status'], 'accepted')
        self.assertEqual(restored['request']['result'], {'turnId': TURN})
        self.send(body)
        self.assertEqual(self.desk.runtimes, {})
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.unchanged()

    def test_orphan_pending_cold_receipt_is_unknown_and_discovery_is_get_only(self):
        body = self.body()
        binding = {'session': self.identifier, 'native_home': os.path.normcase(str(self.desk.home)),
                   'profile': 'default', 'cwd': str(self.path), 'thread_id': PARENT, 'turn_id': TURN}
        self.desk.store.event(self.identifier, {'method': 'desk/steerIntent', 'params': {
            'token': body['token'], 'payload': body, 'binding': binding,
        }})
        self.desk.store.event(self.identifier, {'method': 'desk/steerReceipt', 'params': {
            'token': body['token'], 'status': 'pending',
        }})
        self.cold_owner()
        before = self.desk.store.events(self.identifier)
        status, current = self.read(body)
        self.assertEqual(status, 200)
        self.assertEqual(current['request']['status'], 'needs_review')
        self.send(body, 'needs_review')
        status, discovered = self.call('/api/steer/request?' + urlencode({'session': self.identifier}))
        self.assertEqual(status, 200)
        self.assertEqual(discovered['token'], body['token'])
        self.assertEqual(discovered['request']['status'], 'needs_review')
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(self.requests, [])
        self.unchanged()

    def test_invalid_capture_has_no_native_or_run_mode_fallback(self):
        for changes in [{'token': 'not-a-uuid'}, {'text': ''}, {'text': '  \n\t'}, {'text': 7},
                        {'threadId': ''}, {'expectedTurnId': ''}, {'mode': 'plan'}, {'retry': True}]:
            with self.subTest(changes=changes):
                self.assertEqual(self.call('/api/steer', self.body(**changes))[0], 400)
        self.assertEqual(self.requests, [])
        self.unchanged()
