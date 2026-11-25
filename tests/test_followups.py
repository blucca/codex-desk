"""Prepared follow-ups stay session-bound and require explicit admission receipts."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_desk import followups
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import (
    FollowupConflict, MAX_FOLLOWUP_CHARS, add_followup, clear_followups,
    edit_followup, list_followups, pending_followup, record_followup_receipt,
    remove_followup, reorder_followups, reserve_followup,
)
from codex_desk.runtime import Store

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class FollowupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='followup-test-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.store.db.close)
        self.a = self.store.create('/projects/a', 'sidecar:retained', name='Project A')
        self.b = self.store.create('/projects/b', 'default', name='Project B')
        for identifier, thread in ((self.a, 'native-a'), (self.b, 'native-b')):
            self.store.update(identifier, thread_id=thread, status='ready',
                              model='fixture-model', provider='fixture-provider')
        self.store.event(self.a, {'method': 'fixture/prior-result', 'params': {'exit': 0}})
        self.draft = save_draft(self.store, self.a, 'Existing next-task draft', 'plan', 0)
        self.sessions = self.store.sessions()
        self.events = self.store.events(self.a)

    def assert_bindings_unchanged(self, store=None):
        store = store or self.store
        self.assertEqual(store.sessions(), self.sessions)
        self.assertEqual(store.events(self.a), self.events)
        self.assertEqual(store.events(self.b), [])
        self.assertEqual(load_draft(store, self.a), self.draft)

    def receipt(self, reservation, outcome, store=None):
        return record_followup_receipt(store or self.store, reservation['session_id'],
                                       reservation['token'], reservation['entry_id'],
                                       reservation['revision'], outcome)

    def test_crud_order_modes_and_private_preparation_survive_store_reopen(self):
        one = add_followup(self.store, self.a, '  Verify README\nwithout edits  ', 'plan')
        two = add_followup(self.store, self.a, 'Run the documented check', 'native')
        other = add_followup(self.store, self.b, 'Separate project task', 'native')
        edited = edit_followup(self.store, self.a, one['id'], 'Review the exact result',
                                'native', one['revision'])
        ordered = reorder_followups(self.store, self.a, [two['id'], one['id']],
                                     [one['id'], two['id']])
        self.assertEqual([entry['order'] for entry in ordered], [1, 2])
        self.assertGreater(ordered[1]['revision'], edited['revision'])
        remove_followup(self.store, self.a, two['id'], ordered[0]['revision'])
        expected = list_followups(self.store, self.a)
        self.assertEqual(expected[0]['order'], 1)
        self.store.db.close()
        reopened = Store(self.path)
        try:
            self.assertEqual(list_followups(reopened, self.a), expected)
            self.assertEqual(list_followups(reopened, self.b), [other])
            self.assertIsNone(pending_followup(reopened, self.a))
            self.assert_bindings_unchanged(reopened)
        finally:
            reopened.db.close()

    def test_two_store_connections_reserve_only_one_entry_per_session(self):
        first_entry = add_followup(self.store, self.a, 'Next verification', 'plan')
        add_followup(self.store, self.a, 'Later explanation', 'native')
        other_entry = add_followup(self.store, self.b, 'Other project', 'native')
        second = Store(self.path)
        self.addCleanup(second.db.close)
        entered, release, second_begin = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original = followups._reservation

        def held_reservation(store, session):
            current = original(store, session)
            if store is self.store and not entered.is_set():
                self.assertTrue(store.db.in_transaction)
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Reservation fixture was not released')
            return current

        second.db.set_trace_callback(lambda sql: second_begin.set() if sql == 'BEGIN IMMEDIATE' else None)
        with patch.object(followups, '_reservation', side_effect=held_reservation), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(reserve_followup, self.store, self.a)
            self.assertTrue(entered.wait(3))
            other = pool.submit(reserve_followup, second, self.a)
            try:
                self.assertTrue(second_begin.wait(3))
            finally:
                release.set()
            reservation = first.result(timeout=3)
            self.assertIsNone(other.result(timeout=3))
        self.assertEqual(reservation['entry_id'], first_entry['id'])
        self.assertEqual(reservation['revision'], first_entry['revision'])
        self.assertEqual(reserve_followup(second, self.b)['entry_id'], other_entry['id'])
        self.assert_bindings_unchanged(second)

    def test_accepted_exact_revision_consumes_one_without_reserving_the_next(self):
        first = add_followup(self.store, self.a, 'Verify once', 'native')
        second = add_followup(self.store, self.a, 'Explain next', 'plan')
        reservation = reserve_followup(self.store, self.a, first['id'], first['revision'])
        accepted = self.receipt(reservation, 'accepted')
        self.assertTrue(accepted['consumed'])
        self.assertIsNone(accepted['entry'])
        self.assertIsNone(pending_followup(self.store, self.a))
        queued = list_followups(self.store, self.a)
        self.assertEqual([(e['id'], e['revision'], e['order'], e['state']) for e in queued],
                         [(second['id'], second['revision'], 1, 'queued')])
        self.assert_bindings_unchanged()

    def test_rejection_retains_preparation_and_old_receipt_cannot_consume_new_reservation(self):
        entry = add_followup(self.store, self.a, 'Keep this rejected preparation', 'plan')
        first = reserve_followup(self.store, self.a)
        rejected = self.receipt(first, 'rejected')
        self.assertFalse(rejected['consumed'])
        self.assertEqual(rejected['entry'], entry)
        second = reserve_followup(self.store, self.a)
        self.assertNotEqual(first['token'], second['token'])
        with self.assertRaises(FollowupConflict):
            self.receipt(first, 'accepted')
        self.assertEqual(pending_followup(self.store, self.a), second)
        self.assertEqual(list_followups(self.store, self.a)[0]['text'], entry['text'])
        self.assert_bindings_unchanged()

    def test_same_text_newer_edited_revision_is_not_deleted_by_old_acceptance(self):
        entry = add_followup(self.store, self.a, 'Same words, newer preparation', 'native')
        reservation = reserve_followup(self.store, self.a)
        edited = edit_followup(self.store, self.a, entry['id'], entry['text'],
                                entry['mode'], entry['revision'])
        self.assertEqual(edited['revision'], entry['revision'] + 1)
        self.assertEqual(edited['state'], 'reserved')
        accepted = self.receipt(reservation, 'accepted')
        self.assertFalse(accepted['consumed'])
        self.assertEqual(accepted['entry'], {**edited, 'state': 'queued'})
        self.assertEqual(list_followups(self.store, self.a), [accepted['entry']])
        self.assertIsNone(pending_followup(self.store, self.a))

    def test_unknown_and_newer_edit_survive_reopen_and_require_explicit_review(self):
        entry = add_followup(self.store, self.a, 'Unconfirmed task', 'native')
        add_followup(self.store, self.a, 'Later task', 'plan')
        reservation = reserve_followup(self.store, self.a)
        unknown = self.receipt(reservation, 'unknown')
        self.assertEqual(unknown['entry']['state'], 'needs_review')
        edited = edit_followup(self.store, self.a, entry['id'], 'New goal after uncertainty',
                                'plan', entry['revision'])
        self.store.db.close()
        reopened = Store(self.path)
        try:
            with patch('codex_desk.runtime.Runtime') as native, patch('subprocess.Popen') as process:
                self.assertEqual(pending_followup(reopened, self.a)['state'], 'unknown')
                self.assertEqual(list_followups(reopened, self.a)[0], edited)
                self.assertIsNone(reserve_followup(reopened, self.a))
                with self.assertRaises(ValueError):
                    remove_followup(reopened, self.a, entry['id'], edited['revision'])
                accepted = self.receipt(reservation, 'accepted', reopened)
                self.assertFalse(accepted['consumed'])
                self.assertEqual(accepted['entry']['text'], edited['text'])
                self.assertEqual(accepted['entry']['state'], 'queued')
                self.assertIsNone(pending_followup(reopened, self.a))
                native.assert_not_called()
                process.assert_not_called()
            self.assert_bindings_unchanged(reopened)
        finally:
            reopened.db.close()

    def test_unconfirmed_reservation_after_reopen_cannot_be_replayed(self):
        entry = add_followup(self.store, self.a, 'Review after restarting', 'plan')
        reservation = reserve_followup(self.store, self.a)
        self.store.db.close()
        reopened = Store(self.path)
        try:
            self.assertEqual(pending_followup(reopened, self.a), reservation)
            self.assertEqual(list_followups(reopened, self.a)[0]['state'], 'reserved')
            self.assertIsNone(reserve_followup(reopened, self.a))
            self.receipt(reservation, 'unknown', reopened)
            self.assertIsNone(reserve_followup(reopened, self.a))
            rejected = self.receipt(reservation, 'rejected', reopened)
            self.assertEqual(rejected['entry'], entry)
            self.assertIsNone(pending_followup(reopened, self.a))
            self.assert_bindings_unchanged(reopened)
        finally:
            reopened.db.close()

    def test_reorder_clear_and_stale_edit_keep_reserved_preparation_reviewable(self):
        entries = [add_followup(self.store, self.a, 'Task ' + str(i), 'native') for i in range(3)]
        reservation = reserve_followup(self.store, self.a)
        before = list_followups(self.store, self.a)
        with self.assertRaises(ValueError):
            reorder_followups(self.store, self.a, [entries[1]['id'], entries[0]['id'], entries[2]['id']])
        self.assertEqual(list_followups(self.store, self.a), before)
        order = [entries[0]['id'], entries[2]['id'], entries[1]['id']]
        moved = reorder_followups(self.store, self.a, order, [e['id'] for e in before])
        with self.assertRaises(FollowupConflict):
            edit_followup(self.store, self.a, entries[1]['id'], 'Stale text', 'plan', entries[1]['revision'])
        with self.assertRaises(FollowupConflict):
            clear_followups(self.store, self.a, [e['id'] for e in before])
        cleared = clear_followups(self.store, self.a, [e['id'] for e in moved])
        self.assertEqual(cleared['removed'], [entries[2]['id'], entries[1]['id']])
        self.assertEqual(cleared['reservation'], reservation)
        self.assertEqual(cleared['entries'][0]['id'], entries[0]['id'])
        self.assert_bindings_unchanged()

    def test_invalid_fields_scope_and_receipt_identity_leave_state_unchanged(self):
        self.store.create('/catalog', 'default', identifier='native-catalog')
        self.sessions = self.store.sessions()
        for session in ('missing', 'native-catalog', '', None, 1):
            with self.subTest(session=session), self.assertRaises(ValueError):
                list_followups(self.store, session)
        self.assertIsNone(self.store.db.execute(
            "SELECT name FROM sqlite_master WHERE name='followups'").fetchone())
        entry = add_followup(self.store, self.a, 'Keep the valid preparation', 'native')
        other = add_followup(self.store, self.b, 'Only project B', 'plan')
        before = list_followups(self.store, self.a)
        invalid = [('', 'native'), (' \n ', 'native'), (None, 'native'),
                   ('x' * (MAX_FOLLOWUP_CHARS + 1), 'native'), ('text', 'unknown')]
        for text, mode in invalid:
            with self.assertRaises(ValueError):
                add_followup(self.store, self.a, text, mode)
        for revision in (0, -1, True, None, '1'):
            with self.assertRaises(ValueError):
                edit_followup(self.store, self.a, entry['id'], 'text', 'native', revision)
        with self.assertRaises(ValueError):
            remove_followup(self.store, self.a, other['id'], other['revision'])
        with self.assertRaises(ValueError):
            reserve_followup(self.store, self.a, other['id'], other['revision'])
        with self.assertRaises(ValueError):
            reserve_followup(self.store, self.a, entry['id'])
        for order in ([entry['id'], entry['id']], [], [other['id']], 'not-a-list'):
            with self.assertRaises(ValueError):
                reorder_followups(self.store, self.a, order)
        self.assertEqual(list_followups(self.store, self.a), before)
        reservation = reserve_followup(self.store, self.a)
        for token, identifier, revision in [('old-token', entry['id'], 1),
                                             (reservation['token'], other['id'], 1),
                                             (reservation['token'], entry['id'], 2)]:
            with self.assertRaises(FollowupConflict):
                record_followup_receipt(self.store, self.a, token, identifier, revision, 'accepted')
        self.assertEqual(pending_followup(self.store, self.a), reservation)
        self.assertEqual(list_followups(self.store, self.b), [other])
        self.assert_bindings_unchanged()


if __name__ == '__main__':
    unittest.main()
