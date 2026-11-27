"""Ordinary retained admissions use real HTTP, Store and native reducer paths."""
import copy
import json
import threading
import time
import uuid
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import urlopen
from unittest.mock import Mock, patch

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot, reserve_followup, record_followup_receipt
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import Desk
from codex_desk.turn_dispatch import turn_status, turn_cursor, _records
from test_approval_lifecycle import NativeHTTPFixture


class TurnDispatchTests(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.runtime.lock = threading.Lock()
        self.runtime.pending = {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()
        self.desk.store.update(self.identifier, status='ready')
        self.payload = self.capture('  Exact Plan — 保留\n  ', 'plan')
        add_followup(self.desk.store, self.identifier, 'Paused Work', 'native')
        add_followup(self.desk.store, self.identifier, 'Paused Plan', 'plan')
        self.preparation = followup_snapshot(self.desk.store, self.identifier)

    def capture(self, text, mode='native', writer='page-one', sequence=1):
        current = load_draft(self.desk.store, self.identifier)
        saved = save_draft(self.desk.store, self.identifier, text, mode, current['revision'], writer, sequence)
        return {'session': self.identifier, 'token': str(uuid.uuid4()), 'text': text, 'mode': mode,
                'revision': saved['revision'], 'writer': writer, 'sequence': sequence}

    def get(self, payload=None):
        payload = payload or self.payload
        url = f'http://127.0.0.1:{self.server.server_port}/api/turn/request?' + urlencode(
            {'session': payload['session'], 'token': payload['token']})
        try:
            with urlopen(url, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

    def dispatch(self, **changes):
        return self.post('/api/turn', **{**self.payload, **changes})

    def complete(self, method, params):
        result = self.native_request(method, params)
        with self.runtime.lifecycle_lock:
            self.runtime._message(self.completed())
        return result

    def assert_queues_paused(self):
        self.assertEqual(followup_snapshot(self.desk.store, self.identifier), self.preparation)

    def test_completed_acceptance_duplicate_recovers_original_and_new_identity_same_words_is_allowed(self):
        self.runtime.request = self.complete
        status, first = self.dispatch()
        self.assertEqual(status, 200)
        self.assertEqual(first['request']['status'], 'accepted')
        self.assertEqual(first['request']['payload'], self.payload)
        self.assertEqual(first['request']['draft'], {'text': '', 'mode': 'plan', 'revision': 2})
        self.assertEqual(self.requests[0]['params']['input'][0]['text'], self.payload['text'])
        self.assertEqual(self.requests[0]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        before = self.desk.store.events(self.identifier)
        self.assertEqual(self.dispatch(), (200, first))
        self.assertEqual(self.get(), (200, first))
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(len(self.requests), 1)
        self.payload = self.capture(self.payload['text'], 'plan', sequence=2)
        self.assertEqual(self.dispatch()[1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 2)
        self.assert_queues_paused()

    def test_live_pending_duplicate_returns_receipt_and_blocks_other_run_or_send_next(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def held(method, params):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('fixture did not release')
            return self.complete(method, params)
        self.runtime.request = held
        result = []
        worker = threading.Thread(target=lambda: result.append(self.dispatch()))
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            self.assertEqual(self.get()[1]['request']['status'], 'pending')
            self.assertEqual(self.dispatch()[1]['request']['status'], 'pending')
            self.assertEqual(self.dispatch(token=str(uuid.uuid4()))[0], 409)
            self.assertEqual(self.post('/api/turn', text='Anonymous competing run')[0], 400)
            first = self.preparation['entries'][0]
            self.assertEqual(self.post('/api/followups/send', id=first['id'], revision=first['revision'])[0], 409)
            self.assertEqual(self.post('/api/turn/resolve', token=self.payload['token'], outcome='accepted')[0], 409)
            self.assertEqual(self.requests, [])
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0][1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 1)
        self.assert_queues_paused()

    def test_busy_tokenless_admission_gives_fresh_request_a_durable_rejected_receipt(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def held(method, params):
            entered.set()
            if not release.wait(3):
                raise RuntimeError('fixture did not release')
            return self.complete(method, params)
        self.runtime.request = held
        result = []
        worker = threading.Thread(target=lambda: result.append(self.post('/api/turn', text='Explicit script native task')))
        worker.start()
        self.assertTrue(entered.wait(2))
        try:
            rejected = self.dispatch()
            self.assertEqual((rejected[0], rejected[1]['request']['status']), (200, 'rejected'))
            self.assertEqual(rejected[1]['request']['payload'], self.payload)
            events = self.desk.store.events(self.identifier)
            self.assertEqual(self.get(), rejected)
            self.assertEqual(self.dispatch(), rejected)
            self.assertEqual(self.desk.store.events(self.identifier), events)
            self.assertEqual(self.requests, [])
        finally:
            release.set()
            worker.join(3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0][0], 200)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.dispatch(), rejected)
        self.assertEqual(self.dispatch(retry=True)[1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 2)
        self.assert_queues_paused()

    def test_held_followup_reservation_retains_fresh_known_rejection_without_consuming_queue(self):
        first = self.preparation['entries'][0]
        reservation = reserve_followup(self.desk.store, self.identifier, first['id'], first['revision'])
        before = followup_snapshot(self.desk.store, self.identifier)
        rejected = self.dispatch()
        self.assertEqual((rejected[0], rejected[1]['request']['status']), (200, 'rejected'))
        self.assertEqual(self.get(), rejected)
        self.assertEqual(self.dispatch(), rejected)
        self.assertEqual(followup_snapshot(self.desk.store, self.identifier), before)
        self.assertEqual(self.requests, [])
        record_followup_receipt(self.desk.store, self.identifier, reservation['token'],
                                first['id'], first['revision'], 'rejected')
        self.runtime.request = self.complete
        self.assertEqual(self.dispatch(retry=True)[1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 1)
        self.assert_queues_paused()

    def test_wrong_home_handoff_precheck_retains_known_rejection_without_native_dispatch(self):
        target = self.desk.store.create(str(self.path), 'default', identifier='handoff-' + uuid.uuid4().hex)
        self.desk.store.update(target, thread_id='native-handoff-original', status='ready')
        self.desk.store.event(target, {'method': 'desk/handoffIntent', 'params': {
            'identity': {'native_home': str(self.path / 'original-home')}}})
        payload = {**self.payload, 'session': target, 'token': str(uuid.uuid4())}
        rejected = self.post('/api/turn', **payload)
        self.assertEqual((rejected[0], rejected[1]['request']['status']), (200, 'rejected'))
        self.assertIn('original Codex home', rejected[1]['request']['error'])
        self.assertEqual(self.get(payload), rejected)
        self.assertEqual(self.post('/api/turn', **payload), rejected)
        self.assertEqual(self.requests, [])
        self.assertNotIn(target, self.desk.runtimes)

    def test_known_rejection_duplicate_is_read_only_and_only_exact_explicit_retry_dispatches(self):
        def rejected(method, params):
            self.requests.append({'method': method, 'params': params})
            raise NativeRequestRejected('Native refused this reviewed task')
        self.runtime.request = rejected
        first = self.dispatch()
        self.assertEqual(first[1]['request']['status'], 'rejected')
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], self.payload['text'])
        before = self.desk.store.events(self.identifier)
        self.assertEqual(self.dispatch(), first)
        self.assertEqual(self.get(), first)
        self.assertEqual(self.desk.store.events(self.identifier), before)
        for change in ({'text': self.payload['text'] + ' '}, {'mode': 'native'}, {'revision': 2},
                       {'writer': 'page-two'}, {'sequence': 2}):
            with self.subTest(change=change):
                self.assertEqual(self.dispatch(retry=True, **change)[0], 409)
        self.assertEqual(len(self.requests), 1)
        self.runtime.request = self.complete
        retried = self.dispatch(retry=True)
        self.assertEqual(retried[1]['request']['status'], 'accepted')
        self.assertEqual(retried[1]['request']['attempt'], 2)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(self.dispatch(retry=True)[0], 409)
        self.assert_queues_paused()

    def test_retry_and_cold_read_never_accept_changed_home_profile_cwd_or_thread(self):
        self.runtime.request = lambda *args: (_ for _ in ()).throw(NativeRequestRejected('Rejected'))
        self.assertEqual(self.dispatch()[1]['request']['status'], 'rejected')
        row = self.desk.store.get(self.identifier)
        for field, value in (('profile', 'sidecar:other'), ('cwd', '/different/project'), ('thread_id', 'native-other')):
            with self.subTest(field=field):
                self.desk.store.update(self.identifier, **{field: value})
                events = self.desk.store.events(self.identifier)
                mismatch = self.get()
                self.assertEqual(mismatch[0], 200)
                self.assertTrue(mismatch[1]['request']['binding_mismatch'])
                self.assertEqual(mismatch[1]['request']['binding'][field], row[field])
                self.assertEqual(mismatch[1]['request']['current_binding'][field], value)
                self.assertEqual(self.dispatch(retry=True)[0], 409)
                self.assertEqual(self.desk.store.events(self.identifier), events)
                self.desk.store.update(self.identifier, **{field: row[field]})
        home = self.desk.home
        self.desk.home = self.path / 'different-home'
        try:
            self.assertTrue(self.get()[1]['request']['binding_mismatch'])
            self.assertEqual(self.dispatch(retry=True)[0], 409)
        finally:
            self.desk.home = home
        other = self.desk.store.create(str(self.path), 'default')
        self.desk.store.update(other, thread_id='other-thread', status='ready')
        self.assertEqual(self.dispatch(session=other)[0], 409)
        self.assert_queues_paused()

    def test_fresh_null_binding_is_captured_on_attach_but_nonempty_binding_cannot_move(self):
        original_open = self.desk.open
        self.desk.store.update(self.identifier, thread_id=None)
        def first_binding(identifier):
            self.desk.store.update(identifier, thread_id='native-original')
            return original_open(identifier)
        self.runtime.request = self.complete
        with patch.object(self.desk, 'open', side_effect=first_binding):
            first = self.dispatch()
        self.assertEqual(first[1]['request']['binding']['thread_id'], 'native-original')
        self.assertEqual(len(self.requests), 1)
        self.payload = self.capture('Review same bound native thread only', sequence=2)
        def moved_binding(identifier):
            self.desk.store.update(identifier, thread_id='different-native-thread')
            return original_open(identifier)
        with patch.object(self.desk, 'open', side_effect=moved_binding):
            moved = self.dispatch()
            self.assertEqual((moved[0], moved[1]['request']['status']), (200, 'rejected'))
            self.assertTrue(moved[1]['request']['binding_mismatch'])
        self.assertEqual(len(self.requests), 1)
        receipts = [r['event']['params'] for r in self.desk.store.events(self.identifier)
                    if r['event'].get('method') == 'desk/turnReceipt']
        self.assertEqual(receipts[-1]['status'], 'rejected')
        self.desk.store.update(self.identifier, thread_id='native-original')
        self.assertEqual(self.get()[1]['request']['status'], 'rejected')
        self.assertEqual(self.dispatch()[1]['request']['status'], 'rejected')
        self.assertEqual(self.dispatch(retry=True)[1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 2)
        self.assert_queues_paused()

    def test_clearing_keeps_writer_sequence_without_resurrecting_delayed_captured_save(self):
        self.runtime.request = self.complete
        admitted = self.dispatch()[1]
        self.assertEqual(self.post('/api/draft', **{key: self.payload[key] for key in
                         ('text', 'mode', 'revision', 'writer', 'sequence')})[0], 409)
        self.assertEqual(load_draft(self.desk.store, self.identifier), admitted['request']['draft'])
        next_edit = self.post('/api/draft', text=self.payload['text'], mode='plan',
                              revision=self.payload['revision'], writer=self.payload['writer'], sequence=2)
        self.assertEqual(next_edit[0], 200)
        self.assertEqual(next_edit[1]['text'], self.payload['text'])
        self.assertEqual(next_edit[1]['revision'], 3)
        self.assertEqual(self.get()[1]['request']['draft'], next_edit[1])
        self.assertEqual(len(self.requests), 1)

    def test_unknown_retires_writer_blocks_all_admissions_and_explicit_review_does_not_resend(self):
        self.runtime.request = lambda *args: (_ for _ in ()).throw(NativeRequestUnknown('Lost native response'))
        status, unknown = self.dispatch()
        self.assertEqual((status, unknown['request']['status']), (200, 'needs_review'))
        self.assertTrue(self.runtime.closing)
        self.assertNotIn(self.identifier, self.desk.runtimes)
        before = self.desk.store.events(self.identifier)
        self.native_request('turn/start', {'threadId': 'native-original'})
        self.assertEqual(self.desk.store.events(self.identifier), before)
        self.assertEqual(self.get(), (200, unknown))
        self.assertEqual(self.dispatch(), (200, unknown))
        self.assertEqual(self.dispatch(retry=True)[0], 409)
        self.assertEqual(self.dispatch(token=str(uuid.uuid4()))[0], 409)
        self.assertEqual(self.post('/api/turn', text='Unsafe anonymous replay')[0], 409)
        first = self.preparation['entries'][0]
        self.assertEqual(self.post('/api/followups/send', id=first['id'], revision=first['revision'])[0], 409)
        count = len(self.requests)
        status, reviewed = self.post('/api/turn/resolve', token=self.payload['token'], outcome='accepted')
        self.assertEqual((status, reviewed['request']['status']), (200, 'accepted'))
        self.assertTrue(reviewed['request']['reviewed'])
        self.assertEqual(reviewed['request']['draft']['text'], '')
        self.assertEqual(len(self.requests), count)
        self.assertEqual(self.dispatch(), (200, reviewed))
        self.assert_queues_paused()

    def test_explicit_rejected_unknown_requires_retry_and_preserves_saved_body(self):
        self.runtime.request = lambda *args: (_ for _ in ()).throw(NativeRequestUnknown('Unconfirmed'))
        self.dispatch()
        self.assertEqual(self.post('/api/turn/resolve', token=self.payload['token'], outcome='rejected')[1]['request']['status'], 'rejected')
        self.assertEqual(self.dispatch()[1]['request']['status'], 'rejected')
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], self.payload['text'])
        self.runtime.closing = False
        self.runtime.request = self.complete
        self.desk.runtimes[self.identifier] = self.runtime
        self.desk.store.update(self.identifier, status='ready')
        self.assertEqual(self.dispatch(retry=True)[1]['request']['status'], 'accepted')
        self.assertEqual(len(self.requests), 1)
        self.assert_queues_paused()

    def test_review_cannot_reject_a_reopened_proven_active_native_turn(self):
        self.runtime.request = lambda *args: (_ for _ in ()).throw(NativeRequestUnknown('Unconfirmed'))
        self.dispatch()
        self.runtime.closing = False
        self.desk.runtimes[self.identifier] = self.runtime
        self.native_request('turn/start', {'threadId': 'native-original'})
        self.assertEqual(self.post('/api/turn/resolve', token=self.payload['token'], outcome='rejected')[0], 409)
        accepted = self.post('/api/turn/resolve', token=self.payload['token'], outcome='accepted')
        self.assertEqual(accepted[1]['request']['status'], 'accepted')
        self.assertFalse(self.runtime.closing)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')

    def test_genuine_start_proves_lost_native_reply_even_after_fast_completion(self):
        def lost(method, params):
            self.complete(method, params)
            raise NativeRequestUnknown('Reply lost after completion')
        self.runtime.request = lost
        self.assertEqual(self.dispatch()[1]['request']['status'], 'accepted')
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        self.assertEqual(self.desk.store.get(self.identifier)['mode'], 'plan')
        self.assertFalse(self.runtime.closing)
        self.assertEqual(self.dispatch()[1]['request']['turn']['turn']['id'], 'follow-up-turn')
        self.assertEqual(len(self.requests), 1)
        self.assert_queues_paused()

    def test_resume_or_foreign_start_is_not_new_request_proof(self):
        original_open = self.desk.open
        def resumed(identifier):
            self.desk.store.event(identifier, {'method': 'turn/started', 'params': {
                'threadId': 'native-original', 'turn': {'id': 'prior-resume-turn', 'status': 'completed'}}})
            return original_open(identifier)
        def foreign(method, params):
            self.desk.store.event(self.identifier, {'method': 'turn/started', 'params': {
                'threadId': 'foreign-thread', 'turn': {'id': 'foreign-turn', 'status': 'completed'}}})
            raise NativeRequestUnknown('No new native proof')
        self.runtime.request = foreign
        with patch.object(self.desk, 'open', side_effect=resumed):
            self.assertEqual(self.dispatch()[1]['request']['status'], 'needs_review')
        self.assertEqual(load_draft(self.desk.store, self.identifier)['text'], self.payload['text'])
        self.assert_queues_paused()

    def test_acceptance_preserves_newer_body_same_words_new_revision_and_other_writer(self):
        for changed_text, writer, sequence in (
                ('Newer exact Plan — 保留  ', 'page-one', 2),
                (self.payload['text'], 'page-one', 3),
                (self.payload['text'], 'page-two', 1)):
            with self.subTest(writer=writer, sequence=sequence):
                expected = {}
                def newer(method, params):
                    current = load_draft(self.desk.store, self.identifier)
                    expected.update(save_draft(self.desk.store, self.identifier, changed_text, 'plan',
                                               current['revision'], writer, sequence))
                    return self.complete(method, params)
                self.runtime.request = newer
                self.payload['token'] = str(uuid.uuid4())
                result = self.dispatch()[1]
                self.assertEqual(result['request']['status'], 'accepted')
                self.assertEqual(result['request']['draft'], expected)
                self.assertEqual(load_draft(self.desk.store, self.identifier), expected)
        self.assert_queues_paused()

    def test_legacy_saved_writer_is_not_cleared_by_unidentified_restored_request(self):
        current = load_draft(self.desk.store, self.identifier)
        saved = save_draft(self.desk.store, self.identifier, self.payload['text'], 'plan', current['revision'])
        self.payload['revision'] = saved['revision']
        self.runtime.request = self.complete
        self.assertEqual(self.dispatch()[1]['request']['draft'], saved)
        self.assertEqual(load_draft(self.desk.store, self.identifier), saved)

    def test_cold_accepted_or_abandoned_pending_receipts_are_read_only_and_never_attach(self):
        self.runtime.request = self.complete
        accepted = self.dispatch()[1]
        other = self.capture('No native dispatch after retained pending', sequence=2)
        binding = copy.deepcopy(accepted['request']['binding'])
        self.desk.store.event(self.identifier, {'method': 'desk/turnIntent', 'params': {
            'token': other['token'], 'payload': other, 'binding': binding}})
        self.desk.store.event(self.identifier, {'method': 'desk/turnReceipt', 'params': {
            'token': other['token'], 'status': 'pending', 'attempt': 1}})
        before = self.desk.store.db.total_changes
        cold = Desk('must-not-run', self.path, self.path / 'state')
        self.addCleanup(cold.store.db.close)
        events = cold.store.events(self.identifier)
        sessions = cold.store.sessions()
        with patch.object(cold, 'open', side_effect=AssertionError('cold read opened native')):
            self.assertEqual(turn_status(cold, self.identifier, self.payload['token'])['request']['status'], 'accepted')
            review = turn_status(cold, self.identifier, other['token'])
            self.assertEqual(review['request']['status'], 'needs_review')
            self.assertEqual(review['request']['payload'], other)
            self.assertIsNone(turn_status(cold, self.identifier, str(uuid.uuid4())))
        self.assertEqual(cold.store.events(self.identifier), events)
        self.assertEqual(cold.store.sessions(), sessions)
        self.assertEqual(self.desk.store.db.total_changes, before)
        self.assertEqual(cold.runtimes, {})
        self.assert_queues_paused()

    def test_invalid_identity_and_empty_task_do_not_create_intent_or_dispatch(self):
        events = self.desk.store.events(self.identifier)
        for change in ({'token': 'not-a-uuid'}, {'text': '  \n '}, {'revision': True},
                       {'sequence': -1}, {'writer': ''}, {'mode': 'bad'}, {'retry': 'true'}):
            with self.subTest(change=change):
                self.assertEqual(self.dispatch(**change)[0], 400)
        self.assertEqual(self.desk.store.events(self.identifier), events)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.get()[0], 404)

    def test_session_only_discovers_unknown_even_blank_draft_and_mismatch_but_not_known_outcomes(self):
        self.assertIsNone(turn_status(self.desk, self.identifier))
        self.runtime.request = lambda *args: (_ for _ in ()).throw(NativeRequestUnknown('Unconfirmed'))
        self.dispatch()
        current = load_draft(self.desk.store, self.identifier)
        save_draft(self.desk.store, self.identifier, '', 'native', current['revision'], 'new-page', 1)
        self.desk.store.update(self.identifier, thread_id='different-native')
        events, before = self.desk.store.events(self.identifier), self.desk.store.db.total_changes
        with patch.object(self.desk, 'open', side_effect=AssertionError('Read opened native')):
            discovered = turn_status(self.desk, self.identifier)
            self.assertEqual(discovered['token'], self.payload['token'])
            self.assertEqual(discovered['request']['status'], 'needs_review')
            self.assertTrue(discovered['request']['binding_mismatch'])
            for outcome in ('accepted', 'rejected'):
                self.assertEqual(self.post('/api/turn/resolve', token=self.payload['token'], outcome=outcome)[0], 409)
            self.assertEqual(self.dispatch(token=str(uuid.uuid4()))[0], 409)
        self.assertEqual(self.desk.store.events(self.identifier), events)
        self.assertEqual(self.desk.store.db.total_changes, before)
        self.desk.store.update(self.identifier, thread_id='native-original')
        self.post('/api/turn/resolve', token=self.payload['token'], outcome='rejected')
        self.assertIsNone(turn_status(self.desk, self.identifier))
        self.assertEqual(self.get()[1]['request']['status'], 'rejected')
        self.assert_queues_paused()

    def test_50k_native_stream_projection_preserves_import_shape_and_is_materially_faster(self):
        rows = []
        for n in range(50000):
            event = {'method': 'item/agentMessage/delta', 'params': {
                'threadId': 'native-original', 'itemId': 'answer-' + str(n // 100),
                'delta': 'Native project output 保留 ' + str(n) + ' desk/turnIntent is documentation, not admission'}}
            rows.append((self.identifier, json.dumps(event)))
        token = self.payload['token']
        binding = {'session': self.identifier, 'native_home': str(self.path.resolve()),
                   'profile': 'default', 'cwd': str(self.path), 'thread_id': 'native-original'}
        # Imported valid JSON can reorder keys and escape the method slash.
        intent = json.dumps({'params': {'token': token, 'payload': self.payload, 'binding': binding},
                             'method': 'desk/turnIntent'}, indent=2).replace('desk/turnIntent', 'desk\\/turnIntent')
        receipt = json.dumps({'params': {'token': token, 'status': 'needs_review', 'attempt': 1},
                              'method': 'desk/turnReceipt'}, separators=(',', ':'))
        rows.extend(((self.identifier, intent), (self.identifier, receipt)))
        with self.desk.store.lock, self.desk.store.db:
            self.desk.store.db.executemany('INSERT INTO events(session_id,payload) VALUES(?,?)', rows)
        before = self.desk.store.db.total_changes
        start = time.process_time()
        intents, receipts = {}, {}
        records = self.desk.store.events(self.identifier)
        for record in records:
            event = record['event']
            if event.get('method') in ('desk/turnIntent', 'desk/turnReceipt'):
                (intents if event['method'] == 'desk/turnIntent' else receipts)[event['params']['token']] = event['params']
        baseline = time.process_time() - start
        start = time.process_time()
        selected = _records(self.desk, self.identifier)
        projected = time.process_time() - start
        self.assertEqual(selected, (intents, receipts))
        self.assertLess(projected, baseline * 0.6)
        self.assertEqual(turn_cursor(self.desk, self.identifier), records[-1]['seq'])
        self.assertEqual(turn_cursor(self.desk, 'no-events-session'), 0)
        with patch.object(self.desk, 'open', side_effect=AssertionError('Projection opened native')):
            self.assertEqual(turn_status(self.desk, self.identifier)['token'], token)
        self.assertEqual(self.desk.store.db.total_changes, before)
