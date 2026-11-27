"""Saved preparation remains readable before any native session starts."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_desk import preparation
from codex_desk.drafts import save_draft
from codex_desk.followups import (add_followup, edit_followup, followup_snapshot,
                                 record_followup_receipt, reorder_followups, reserve_followup)
from codex_desk.preparation import preparation_snapshot
from codex_desk.runtime import Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-preparation-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'state' / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.alpha, self.beta = self.root / 'alpha', self.root / 'removed-beta'
        self.alpha.mkdir(); self.beta.mkdir()
        self.a = self.store.create(str(self.alpha), 'default', identifier='alpha-task', name='Today’s checkout task')
        self.b = self.store.create(str(self.beta), 'sidecar:review', identifier='beta-task', name='Retained follow-ups')
        self.store.update(self.a, thread_id='alpha-native', status='failed', mode='plan')
        self.store.update(self.b, thread_id='beta-native', status='saved')

    def seed(self):
        self.draft = save_draft(self.store, self.a, 'Review the original retry decision.\n保留计划', 'plan', 0,
                                writer='private-page-lineage', sequence=1)
        self.one = add_followup(self.store, self.b, 'Run the retained checkout check', 'native')
        self.two = add_followup(self.store, self.b, 'Apply the remaining Work patch', 'native')
        reordered = reorder_followups(self.store, self.b, [self.two['id'], self.one['id']])
        self.pending = reserve_followup(self.store, self.b, reordered[0]['id'], reordered[0]['revision'])
        record_followup_receipt(self.store, self.b, self.pending['token'], self.pending['entry_id'],
                                self.pending['revision'], 'unknown')
        edit_followup(self.store, self.b, reordered[0]['id'], 'Revised remaining Work patch', 'native',
                      reordered[0]['revision'])
        self.queue = followup_snapshot(self.store, self.b)
        self.store.archive(self.b, True)
        self.beta.rmdir()
        with self.store.lock, self.store.db:
            self.store.db.execute('UPDATE sessions SET updated=100 WHERE id=?', (self.a,))
            self.store.db.execute('UPDATE sessions SET updated=200 WHERE id=?', (self.b,))

    def test_two_projects_preserve_plan_queue_order_pending_versions_archive_and_removed_folder(self):
        self.seed()
        before = list(self.store.db.iterdump())
        visible = preparation_snapshot(self.store)
        self.assertEqual([row['id'] for row in visible['sessions']], [self.a])
        self.assertEqual(visible['sessions'][0]['draft'], self.draft)
        self.assertEqual(visible['sessions'][0]['followups'], {'entries': [], 'reservation': None})
        self.assertEqual(visible['sessions'][0]['status'], 'failed')
        all_saved = preparation_snapshot(self.store, include_archived=True)
        self.assertEqual([row['id'] for row in all_saved['sessions']], [self.b, self.a])
        row = all_saved['sessions'][0]
        self.assertEqual((row['name'], row['cwd'], row['profile'], row['archived'], row['status']),
                         ('Retained follow-ups', str(self.beta), 'sidecar:review', True, 'saved'))
        self.assertIsNone(row['draft'])
        self.assertEqual(row['followups'], self.queue)
        self.assertEqual([entry['id'] for entry in row['followups']['entries']], [self.two['id'], self.one['id']])
        self.assertEqual([entry['mode'] for entry in row['followups']['entries']], ['native', 'native'])
        self.assertEqual(row['followups']['reservation']['state'], 'unknown')
        self.assertGreater(row['followups']['entries'][0]['revision'], row['followups']['reservation']['revision'])
        self.assertNotEqual(row['followups']['entries'][0]['text'], row['followups']['reservation']['text'])
        self.assertEqual(preparation_snapshot(self.store, cwd=str(self.beta))['sessions'], [])
        scoped = preparation_snapshot(self.store, include_archived=True, cwd=str(self.beta / '..' / 'removed-beta'))
        self.assertEqual(scoped['sessions'], [row])
        self.assertEqual(preparation_snapshot(self.store, include_archived=True, cwd=str(self.root))['sessions'], [])
        self.assertEqual(preparation_snapshot(self.store, include_archived=True, cwd=str(self.beta / 'child'))['sessions'], [])
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertFalse(self.beta.exists())

    def test_cold_reopen_preserves_exact_preparation_and_stable_session_tie_order(self):
        self.seed()
        with self.store.lock, self.store.db:
            self.store.db.execute('UPDATE sessions SET updated=100')
        expected = preparation_snapshot(self.store, include_archived=True)
        self.assertEqual([row['id'] for row in expected['sessions']], [self.a, self.b])
        self.store.db.close()
        self.store = Store(self.path)
        before = list(self.store.db.iterdump())
        self.assertEqual(preparation_snapshot(self.store, include_archived=True), expected)
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertNotIn('private-page-lineage', json.dumps(expected))

    def test_read_only_overview_does_not_create_tables_start_native_or_read_cached_activity_body(self):
        before = list(self.store.db.iterdump())
        changes = self.store.db.total_changes
        with patch('codex_desk.runtime.subprocess.Popen') as spawned, \
                patch('codex_desk.runtime.Runtime.request') as requested:
            self.assertEqual(preparation_snapshot(self.store), {'sessions': []})
            spawned.assert_not_called(); requested.assert_not_called()
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertEqual(self.store.db.total_changes, changes)
        tables = {row[0] for row in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertNotIn('drafts', tables)
        self.assertNotIn('followups', tables)
        self.assertNotIn('followup_reservations', tables)
        save_draft(self.store, self.a, 'Only this saved preparation is needed', 'plan', 0)
        self.store.event(self.a, {'method': 'item/completed', 'params': {'threadId': 'alpha-native',
            'turnId': 'old-turn', 'item': {'id': 'old-body', 'type': 'agentMessage',
            'text': 'UNUSED CACHED BODY ' * 12000}}})
        self.store.update(self.a, usage='UNUSED USAGE BODY ' * 12000, error='UNUSED ERROR BODY ' * 12000)
        before = list(self.store.db.iterdump()); changes = self.store.db.total_changes
        statements = []
        self.store.db.set_trace_callback(statements.append)
        try:
            snapshot = preparation_snapshot(self.store)
        finally:
            self.store.db.set_trace_callback(None)
        self.assertEqual(len(snapshot['sessions']), 1)
        self.assertNotIn('UNUSED', json.dumps(snapshot))
        self.assertTrue(all(statement.lstrip().upper().startswith(('SELECT', 'SAVEPOINT', 'RELEASE'))
                            for statement in statements))
        self.assertFalse(any(name in statement for statement in statements
                             for name in ('events', 'recall_items', 'native_recall_items')))
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertEqual(self.store.db.total_changes, changes)

    def test_empty_and_whitespace_drafts_and_consumed_followups_are_not_prepared_work(self):
        save_draft(self.store, self.a, '', 'plan', 0)
        save_draft(self.store, self.b, ' \n\t\u3000 ', 'native', 0)
        entry = add_followup(self.store, self.a, 'A consumed preparation', 'native')
        pending = reserve_followup(self.store, self.a, entry['id'], entry['revision'])
        record_followup_receipt(self.store, self.a, pending['token'], pending['entry_id'],
                                pending['revision'], 'accepted')
        before = list(self.store.db.iterdump())
        self.assertEqual(preparation_snapshot(self.store, include_archived=True), {'sessions': []})
        self.assertEqual(list(self.store.db.iterdump()), before)
        self.assertEqual(self.store.db.execute('SELECT revision FROM drafts WHERE session_id=?',
                                               (self.b,)).fetchone()[0], 1)

    def test_snapshot_remains_source_consistent_while_another_store_saves_new_draft_and_queue_revisions(self):
        with self.store.lock:
            self.store.db.execute('PRAGMA journal_mode=WAL')
        draft = save_draft(self.store, self.a, 'Original Plan draft', 'plan', 0)
        entry = add_followup(self.store, self.a, 'Original Work follow-up', 'native')
        before = preparation_snapshot(self.store)
        second = Store(self.path)
        self.addCleanup(second.db.close)
        entered, release = threading.Event(), threading.Event()
        original_entries = preparation._entries

        def held_entries(store, session):
            if session == self.a:
                entered.set()
                self.assertTrue(release.wait(5), 'Snapshot reader was not released')
            return original_entries(store, session)

        with patch.object(preparation, '_entries', side_effect=held_entries), ThreadPoolExecutor(max_workers=1) as pool:
            reading = pool.submit(preparation_snapshot, self.store)
            try:
                self.assertTrue(entered.wait(5), 'Snapshot reader did not reach the queue')
                new_draft = save_draft(second, self.a, 'New Plan draft', 'plan', draft['revision'])
                new_entry = edit_followup(second, self.a, entry['id'], 'New Work follow-up', 'native', entry['revision'])
            finally:
                release.set()
            self.assertEqual(reading.result(timeout=5), before)
        after = preparation_snapshot(self.store)
        self.assertEqual(after['sessions'][0]['draft'], new_draft)
        self.assertEqual(after['sessions'][0]['followups']['entries'], [new_entry])

    def test_legacy_draft_shape_is_read_without_schema_upgrade_and_invalid_filters_do_not_write(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('''CREATE TABLE drafts(session_id TEXT PRIMARY KEY,
                                     text TEXT NOT NULL,mode TEXT NOT NULL,revision INTEGER NOT NULL)''')
            self.store.db.execute('INSERT INTO drafts VALUES(?,?,?,?)', (self.a, 'Legacy Plan preparation', 'plan', 2))
        before = list(self.store.db.iterdump())
        snapshot = preparation_snapshot(self.store)
        self.assertEqual(snapshot['sessions'][0]['draft'], {'text': 'Legacy Plan preparation', 'mode': 'plan', 'revision': 2})
        self.assertEqual(snapshot['sessions'][0]['followups'], {'entries': [], 'reservation': None})
        for archived in ('false', 0, 1, None):
            with self.subTest(archived=archived), self.assertRaises(ValueError):
                preparation_snapshot(self.store, include_archived=archived)
        for cwd in ('', ' \n ', 4):
            with self.subTest(cwd=cwd), self.assertRaises(ValueError):
                preparation_snapshot(self.store, cwd=cwd)
        self.assertEqual(list(self.store.db.iterdump()), before)


if __name__ == '__main__':
    unittest.main()
