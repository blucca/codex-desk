"""Existing scoped owners, exact lifecycle lookup and read-only boundaries."""
import os
from pathlib import Path
import tempfile
import unittest
from codex_desk.runtime import Store
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup, reserve_followup, edit_followup
from codex_desk.preparation import preparation_snapshot
from codex_desk.preparation_find import lookup_snapshot
from codex_desk.recall import normalize

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PreparationFindTests(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory(dir=ROOT, prefix='preparation-find-')
        self.addCleanup(t.cleanup)
        self.root = Path(t.name)
        self.store = Store(self.root / 'state.sqlite3')
        self.addCleanup(self.store.db.close)
        for owner in ('a', 'b', 'c'):
            self.store.create(str(self.root / owner), 'default', identifier=owner, name='Task ' + owner)
        self.store.update('a', updated=300)
        self.store.update('b', updated=200)
        self.store.update('c', updated=100)
        self.text = 'Prefix ' + ('unrelated ' * 80) + 'Straße café🙂 ＦＩＸ retained evidence. Tail'
        save_draft(self.store, 'a', self.text, 'plan', 0)
        save_draft(self.store, 'b', self.text, 'native', 0)
        self.entry = add_followup(self.store, 'b', 'Captured older retry evidence', 'plan')
        self.reservation = reserve_followup(self.store, 'b', self.entry['id'], self.entry['revision'])
        edit_followup(self.store, 'b', self.entry['id'], 'Revised current retry evidence', 'native', self.entry['revision'])
        self.store.archive('b', True)
        token = '00000000-0000-4000-8000-000000000003'
        self.token = token
        self.store.event('c', {'method': 'desk/turnIntent', 'params': {
            'token': token, 'payload': {'session': 'c', 'token': token, 'text': 'Pending retry evidence original',
                                      'mode': 'plan', 'revision': 0, 'writer': 'test', 'sequence': 0},
            'binding': {'thread': 'native-c', 'cwd': str(self.root / 'c'), 'profile': 'default'}}})

    def test_no_query_snapshot_is_exact_and_blank_query_keeps_all_scoped_owners(self):
        self.assertEqual(lookup_snapshot(self.store), preparation_snapshot(self.store))
        result = lookup_snapshot(self.store, '')
        self.assertEqual(result['sessions'], preparation_snapshot(self.store)['sessions'])
        self.assertEqual(result['lookup']['results'], [])

    def test_unicode_original_snippet_and_exact_duplicate_owners(self):
        result = lookup_snapshot(self.store, 'STRASSE CAFÉ🙂 fix', True)
        hits = result['lookup']['results']
        expected = [(row['id'], 'draft', row['draft']['mode']) for row in result['sessions'] if row['draft']]
        self.assertEqual([(r['session_id'], r['kind'], r['mode']) for r in hits], expected)
        for hit in hits:
            self.assertEqual(normalize(hit['match_text']), normalize('Straße café🙂 ＦＩＸ'))
            self.assertIn('Straße café🙂 ＦＩＸ', hit['snippet'])
            self.assertLessEqual(len(hit['snippet']), 422)
            self.assertEqual(hit['revision'], 1)
        self.assertEqual(result['sessions'], preparation_snapshot(self.store, True)['sessions'])

    def test_archive_and_project_scope_are_exact_without_losing_inventory(self):
        self.assertEqual(lookup_snapshot(self.store, 'strasse')['lookup']['total'], 1)
        result = lookup_snapshot(self.store, 'strasse', True, str(self.root / 'b'))
        self.assertEqual([r['session_id'] for r in result['lookup']['results']], ['b'])
        self.assertEqual([r['id'] for r in result['sessions']], ['b'])
        self.assertEqual(lookup_snapshot(self.store, 'strasse', True, str(self.root))['sessions'], [])

    def test_queued_edit_and_immutable_reservation_keep_different_revisions(self):
        result = lookup_snapshot(self.store, 'retry evidence', True)
        followup = next(r for r in result['lookup']['results'] if r['kind'] == 'followup')
        captured = next(r for r in result['lookup']['results'] if r['kind'] == 'reservation')
        self.assertEqual(followup['followup_id'], captured['followup_id'])
        self.assertEqual(followup['session_id'], captured['session_id'])
        self.assertGreater(followup['revision'], captured['revision'])
        self.assertEqual(captured['token'], self.reservation['token'])
        self.assertIn('Captured older', captured['snippet'])
        self.assertIn('Revised current', followup['snippet'])

    def test_current_pending_request_found_after_cleared_draft_with_exact_uuid(self):
        result = lookup_snapshot(self.store, 'pending retry')
        hit, = result['lookup']['results']
        self.assertEqual((hit['session_id'], hit['kind'], hit['token'], hit['mode']), ('c', 'turn_request', self.token, 'plan'))
        self.store.event('c', {'method': 'desk/turnReceipt', 'params': {'token': self.token, 'status': 'accepted'}})
        self.assertEqual(lookup_snapshot(self.store, 'pending retry')['lookup']['total'], 0)

    def test_page_counts_are_exact_and_limit_not_a_scan_truncation(self):
        result = lookup_snapshot(self.store, 'retry evidence', True, limit=1)
        self.assertEqual(result['lookup']['total'], 3)
        self.assertTrue(result['lookup']['has_more'])
        later = lookup_snapshot(self.store, 'retry evidence', True, limit=1, offset=2)
        self.assertEqual(later['lookup']['total'], 3)
        self.assertEqual(len(later['lookup']['results']), 1)
        self.assertFalse(later['lookup']['has_more'])

    def test_lookup_never_creates_tables_rows_or_writes_current_store(self):
        before = list(self.store.db.iterdump())
        changes = self.store.db.total_changes
        for query in (None, '', 'retry evidence', 'strasse', 'absent phrase'):
            lookup_snapshot(self.store, query, True)
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertEqual(self.store.db.total_changes, changes)

    def test_invalid_query_and_paging_inputs_are_rejected(self):
        for q in (True, 1, [], 'x', 'a' * 201, '\ud800broken'):
            with self.subTest(q=repr(q)), self.assertRaises(ValueError):
                lookup_snapshot(self.store, q)
        for kwargs in ({'limit': True}, {'limit': 0}, {'limit': 51}, {'offset': True}, {'offset': -1}, {'offset': 2 ** 63}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                lookup_snapshot(self.store, 'valid query', **kwargs)


if __name__ == '__main__':
    unittest.main()
