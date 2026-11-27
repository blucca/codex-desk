"""Request-only prepared work is scoped, read-only and latest-receipt aware."""
from concurrent.futures import ThreadPoolExecutor
import threading
import json
import os
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import patch

from codex_desk.runtime import Store
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.preparation import preparation_snapshot
from codex_desk import turn_records, preparation

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PreparedTurnRequestTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='prepared-turn-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.store = Store(self.root/'state.sqlite3')
        self.addCleanup(lambda: self.store.db.close())
        self.a = self.store.create(str(self.root/'removed-a'), 'default', identifier='a')
        self.b = self.store.create(str(self.root/'b'), 'sidecar:review', identifier='b')
        self.store.update(self.a, thread_id='original-a', mode='plan')
        save_draft(self.store, self.b, 'Later unsent Plan. 保留', 'plan', 0, writer='later', sequence=1)
        add_followup(self.store, self.b, 'First Work.', 'native')
        add_followup(self.store, self.b, 'Second Plan.', 'plan')

    def intent(self, session='a', status='needs_review', token=None, binding=None):
        token = token or str(uuid.uuid4())
        payload = {'session': session, 'token': token, 'text': 'Exact original task.  保留',
                   'mode': 'plan', 'revision': 1, 'writer': 'original', 'sequence': 1}
        target = binding or {'session': session, 'native_home': '/fixture/native-home',
                             'cwd': self.store.get(session)['cwd'], 'profile': 'default',
                             'thread_id': 'original-a'}
        self.store.event(session, {'method': turn_records.INTENT,
                                  'params': {'token': token, 'payload': payload, 'binding': target}})
        if status is not None:
            self.receipt(token, status, session)
        return token

    def receipt(self, token, status, session='a'):
        self.store.event(session, {'method': turn_records.RECEIPT,
                                  'params': {'token': token, 'status': status, 'attempt': 1}})

    def snapshot(self):
        return list(self.store.db.iterdump())

    def rows(self, **kwargs):
        return {r['id']: r for r in preparation_snapshot(self.store, **kwargs)['sessions']}

    def test_blank_request_only_and_other_plan_queues_read_only(self):
        ordinary = self.rows()['b']
        token = self.intent()
        before = self.snapshot()
        rows = self.rows()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(rows['b'], ordinary)
        self.assertIsNone(rows['a']['draft'])
        self.assertEqual(rows['a']['followups'], {'entries': [], 'reservation': None})
        self.assertEqual(rows['a']['turn_request']['token'], token)
        self.assertEqual(rows['a']['turn_request']['status'], 'needs_review')
        self.assertNotIn('text', rows['a']['turn_request'])

    def test_no_request_preparation_response_shape_unchanged(self):
        self.assertNotIn('turn_request', self.rows()['b'])

    def test_missing_receipt_pending_survives_cold_store(self):
        token = self.intent(status=None)
        other = Store(self.root/'state.sqlite3')
        try:
            before = list(other.db.iterdump())
            rows = {r['id']:r for r in preparation_snapshot(other)['sessions']}
            self.assertEqual(rows['a']['turn_request']['token'], token)
            self.assertEqual(rows['a']['turn_request']['status'], 'pending')
            self.assertEqual(before, list(other.db.iterdump()))
        finally:
            other.db.close()

    def test_latest_receipt_accepted_or_rejected_omits_only_request(self):
        token = self.intent()
        ordinary = self.rows()['b']
        for status in ('accepted', 'rejected'):
            self.receipt(token, status)
            rows = self.rows()
            self.assertNotIn('a', rows)
            self.assertEqual(rows['b'], ordinary)

    def test_latest_receipt_per_token_preserves_older_unresolved(self):
        unresolved = self.intent()
        known = self.intent(status='accepted')
        self.receipt(known, 'rejected')
        self.assertEqual(self.rows()['a']['turn_request']['token'], unresolved)
        self.receipt(unresolved, 'accepted')
        self.assertNotIn('a', self.rows())

    def test_resolve_retains_newer_draft_and_two_queues(self):
        token = self.intent()
        save_draft(self.store, 'a', 'Newer Work stays unsent.', 'native', 0, writer='newer', sequence=1)
        add_followup(self.store, 'a', 'A Work.', 'native')
        add_followup(self.store, 'a', 'A Plan.', 'plan')
        before = self.rows()['a']
        self.receipt(token, 'rejected')
        after = self.rows()['a']
        self.assertEqual(before['draft'], after['draft'])
        self.assertEqual(before['followups'], after['followups'])
        self.assertNotIn('turn_request', after)

    def test_scope_archived_removed_folder_and_native_catalog_excluded(self):
        self.intent()
        self.assertIn('a', self.rows(cwd=str(self.root/'removed-a')))
        self.assertNotIn('a', self.rows(cwd=str(self.root/'b')))
        self.store.update('a', archived=1)
        self.assertNotIn('a', self.rows())
        self.assertIn('a', self.rows(include_archived=True))
        self.store.create(str(self.root/'removed-a'), 'default', identifier='native-catalog')
        self.intent(session='native-catalog')
        self.assertNotIn('native-catalog', self.rows(include_archived=True))

    def test_native_deltas_and_quoted_method_text_not_materialized(self):
        token = self.intent()
        for _ in range(100):
            self.store.event('a', {'method': 'item/agentMessage/delta',
                                  'params': {'delta': 'Quoted desk/turnIntent desk/turnReceipt'}})
        with patch.object(turn_records.json, 'loads', wraps=json.loads) as decode:
            self.assertEqual(self.rows()['a']['turn_request']['token'], token)
            self.assertEqual(decode.call_count, 2)

    def test_last_intent_binding_is_retained_without_current_binding_guess(self):
        token = self.intent(status=None)
        target = {'session': 'a', 'native_home': '/original-home', 'cwd': '/original-folder',
                  'profile': 'default', 'thread_id': 'retained-native'}
        self.intent(status=None, token=token, binding=target)
        self.store.update('a', thread_id='current-native')
        self.assertEqual(self.rows()['a']['turn_request']['binding'], target)

    def test_request_draft_and_queues_share_one_read_transaction(self):
        with self.store.lock:
            self.store.db.execute('PRAGMA journal_mode=WAL')
        token = self.intent()
        before = preparation_snapshot(self.store)
        second = Store(self.root/'state.sqlite3')
        entered, release = threading.Event(), threading.Event()
        original_entries = preparation._entries

        def held_entries(store, session):
            if session == 'a':
                entered.set()
                self.assertTrue(release.wait(5))
            return original_entries(store, session)

        try:
            with patch.object(preparation, '_entries', side_effect=held_entries), ThreadPoolExecutor(max_workers=1) as pool:
                reading = pool.submit(preparation_snapshot, self.store)
                try:
                    self.assertTrue(entered.wait(5))
                    second.event('a', {'method': turn_records.RECEIPT,
                                      'params': {'token': token, 'status': 'rejected', 'attempt': 1}})
                    old = next(row for row in before['sessions'] if row['id'] == 'b')['draft']
                    new_draft = save_draft(second, 'b', 'Newer saved Plan.', 'plan', old['revision'],
                                           writer='second', sequence=1)
                finally:
                    release.set()
                self.assertEqual(reading.result(timeout=5), before)
            rows = self.rows()
            self.assertNotIn('a', rows)
            self.assertEqual(rows['b']['draft'], new_draft)
        finally:
            release.set()
            second.db.close()


if __name__ == '__main__':
    unittest.main()
