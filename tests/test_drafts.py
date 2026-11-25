"""Persisted next-task preparation and optimistic multi-page saving."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_desk import drafts
from codex_desk.drafts import DraftConflict, MAX_DRAFT_CHARS, load_draft, save_draft
from codex_desk.runtime import Store

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class DraftTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-drafts-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(self.store.db.close)
        self.a = self.store.create(str(Path(self.folder.name) / 'project-a'), 'default')
        self.b = self.store.create(str(Path(self.folder.name) / 'project-b'), 'sidecar:retained')
        self.store.update(self.a, thread_id='native-a', mode='plan')
        self.store.update(self.b, thread_id='native-b')
        self.store.event(self.a, {'method': 'fixture/prior-activity', 'params': {}})

    def test_project_drafts_modes_and_bindings_persist_after_store_reopen(self):
        sessions = self.store.sessions()
        events = self.store.events(self.a)
        self.assertEqual(load_draft(self.store, self.a),
                         {'text': '', 'mode': 'plan', 'revision': 0})
        a = save_draft(self.store, self.a, '  Plan the next\nverification  ', 'plan', 0)
        b = save_draft(self.store, self.b, 'Continue the other project', 'native', 0)
        reopened = Store(self.path)
        try:
            self.assertEqual(load_draft(reopened, self.a), a)
            self.assertEqual(load_draft(reopened, self.b), b)
            self.assertEqual(reopened.sessions(), sessions)
            self.assertEqual(reopened.events(self.a), events)
            self.assertEqual(reopened.events(self.b), [])
        finally:
            reopened.db.close()

    def test_stale_second_page_conflict_returns_current_without_overwriting(self):
        first_view = load_draft(self.store, self.a)
        second_view = load_draft(self.store, self.a)
        saved = save_draft(self.store, self.a, 'First page preparation',
                           'native', first_view['revision'])
        with self.assertRaises(DraftConflict) as conflict:
            save_draft(self.store, self.a, 'Stale page preparation',
                       'plan', second_view['revision'])
        self.assertEqual(conflict.exception.current, saved)
        self.assertNotIn('First page preparation', str(conflict.exception))
        conflict.exception.current['text'] = 'Caller changes its conflict copy'
        self.assertEqual(load_draft(self.store, self.a), saved)
        self.assertEqual(load_draft(self.store, self.b)['revision'], 0)

    def test_invalid_requests_leave_drafts_bindings_and_events_untouched(self):
        self.store.create('/catalog', 'default', identifier='native-catalog')
        for invalid in ('missing', 'native-catalog', '', None, 1):
            with self.subTest(load=invalid), self.assertRaises(ValueError):
                load_draft(self.store, invalid)
        self.assertIsNone(self.store.db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='drafts'").fetchone())
        saved = save_draft(self.store, self.a, 'Keep this preparation', 'native', 0)
        sessions, events = self.store.sessions(), self.store.events(self.a)
        invalid_saves = [
            ('missing', 'text', 'native', 0), ('native-catalog', 'text', 'native', 0),
            ('', 'text', 'native', 0), (None, 'text', 'native', 0),
            (self.a, None, 'native', 1), (self.a, 1, 'native', 1),
            (self.a, 'x' * (MAX_DRAFT_CHARS + 1), 'native', 1),
            (self.a, 'text', 'unknown', 1), (self.a, 'text', None, 1),
            (self.a, 'text', 'native', -1), (self.a, 'text', 'native', True),
            (self.a, 'text', 'native', '1'), (self.a, 'text', 'native', 1.0),
            (self.a, 'text', 'native', None),
            (self.a, 'text', 'native', 1, None, 1),
            (self.a, 'text', 'native', 1, 'page', None),
            (self.a, 'text', 'native', 1, '', 1),
            (self.a, 'text', 'native', 1, 'x' * 129, 1),
            (self.a, 'text', 'native', 1, 'page', True),
            (self.a, 'text', 'native', 1, 'page', -1),
            (self.a, 'text', 'native', 1, 'page', 2**63),
        ]
        for values in invalid_saves:
            with self.subTest(session=values[0], mode=values[2], revision=values[3]):
                with self.assertRaises(ValueError):
                    save_draft(self.store, *values)
                self.assertEqual(load_draft(self.store, self.a), saved)
                self.assertEqual(self.store.sessions(), sessions)
                self.assertEqual(self.store.events(self.a), events)
        exact = '\u9a8c' * MAX_DRAFT_CHARS
        self.assertEqual(save_draft(self.store, self.b, exact, 'plan', 0)['text'], exact)

    def test_empty_clear_advances_revision_and_cannot_be_revived_by_stale_page(self):
        empty = save_draft(self.store, self.a, '', 'plan', 0)
        self.assertEqual(empty, {'text': '', 'mode': 'plan', 'revision': 1})
        prepared = save_draft(self.store, self.a, 'Prepared next task', 'native', 1)
        cleared = save_draft(self.store, self.a, '', 'native', prepared['revision'])
        self.assertEqual(cleared, {'text': '', 'mode': 'native', 'revision': 3})
        with self.assertRaises(DraftConflict) as conflict:
            save_draft(self.store, self.a, 'Late older text', 'plan', prepared['revision'])
        self.assertEqual(conflict.exception.current, cleared)
        reopened = Store(self.path)
        try:
            self.assertEqual(load_draft(reopened, self.a), cleared)
        finally:
            reopened.db.close()

    def test_two_store_connections_claim_only_one_revision_transactionally(self):
        second = Store(self.path)
        self.addCleanup(second.db.close)
        entered, release, second_begin = threading.Event(), threading.Event(), threading.Event()
        self.addCleanup(release.set)
        original_read = drafts._read

        def held_read(store, session, initial_mode):
            result = original_read(store, session, initial_mode)
            if store is self.store and not entered.is_set():
                entered.set()
                if not release.wait(5):
                    raise RuntimeError('Draft transaction fixture was not released')
            return result

        second.db.set_trace_callback(
            lambda sql: second_begin.set() if sql == 'BEGIN IMMEDIATE' else None)

        with patch.object(drafts, '_read', side_effect=held_read), ThreadPoolExecutor(max_workers=2) as pool:
            first_save = pool.submit(save_draft, self.store, self.a, 'First transaction', 'plan', 0)
            self.assertTrue(entered.wait(3))
            other_save = pool.submit(save_draft, second, self.a, 'Second transaction', 'native', 0)
            try:
                self.assertTrue(second_begin.wait(3))
            finally:
                release.set()
            saved = first_save.result(timeout=3)
            with self.assertRaises(DraftConflict) as conflict:
                other_save.result(timeout=3)
        self.assertEqual(conflict.exception.current, saved)
        self.assertEqual(load_draft(second, self.a), saved)

    def test_newer_same_page_edit_recovers_committed_save_with_delayed_response(self):
        first = save_draft(self.store, self.a, 'First prepared version', 'native', 0,
                           'page-a', 1)
        # The browser still knows revision zero while that save's reply is delayed.
        latest = save_draft(self.store, self.a, 'Latest before closing', 'plan', 0,
                            'page-a', 2)
        self.assertEqual(latest['revision'], first['revision'] + 1)
        self.assertEqual(save_draft(self.store, self.a, latest['text'], latest['mode'],
                                    0, 'page-a', 2), latest)
        # Older in-flight edits cannot revive earlier text, even with a fresh revision.
        with self.assertRaises(DraftConflict):
            save_draft(self.store, self.a, first['text'], first['mode'],
                       latest['revision'], 'page-a', 1)
        with self.assertRaises(DraftConflict):
            save_draft(self.store, self.a, 'Different payload at the same sequence',
                       'plan', latest['revision'], 'page-a', 2)
        with self.assertRaises(DraftConflict):
            save_draft(self.store, self.a, 'Unobserved future revision', 'plan',
                       latest['revision'] + 1, 'page-a', 3)
        self.assertEqual(load_draft(self.store, self.a), latest)

    def test_same_page_recovery_never_overwrites_another_page_or_legacy_save(self):
        first = save_draft(self.store, self.a, 'Page A', 'plan', 0, 'page-a', 1)
        other = save_draft(self.store, self.a, 'Page B', 'native', first['revision'], 'page-b', 1)
        with self.assertRaises(DraftConflict) as conflict:
            save_draft(self.store, self.a, 'Late A edit', 'plan', first['revision'], 'page-a', 2)
        self.assertEqual(conflict.exception.current, other)
        # Explicitly selecting the current revision permits a new page owner.
        chosen = save_draft(self.store, self.a, 'Explicit A choice', 'plan', other['revision'], 'page-a', 3)
        legacy = save_draft(self.store, self.a, 'Legacy client choice', 'native', chosen['revision'])
        with self.assertRaises(DraftConflict) as conflict:
            save_draft(self.store, self.a, 'Late identified A', 'plan', chosen['revision'], 'page-a', 4)
        self.assertEqual(conflict.exception.current, legacy)
        self.assertEqual(load_draft(self.store, self.a), legacy)

    def test_existing_draft_table_upgrade_keeps_preparation_bindings_and_activity(self):
        with self.store.lock, self.store.db:
            self.store.db.execute('''CREATE TABLE drafts(
                session_id TEXT PRIMARY KEY NOT NULL,text TEXT NOT NULL,
                mode TEXT NOT NULL,revision INTEGER NOT NULL)''')
            self.store.db.execute('INSERT INTO drafts VALUES(?,?,?,?)',
                                  (self.a, 'Existing private preparation', 'plan', 7))
        sessions, events = self.store.sessions(), self.store.events(self.a)
        self.assertEqual(load_draft(self.store, self.a),
                         {'text': 'Existing private preparation', 'mode': 'plan', 'revision': 7})
        self.assertEqual(self.store.db.execute(
            'SELECT writer,edit_sequence FROM drafts WHERE session_id=?', (self.a,)).fetchone(), (None, None))
        self.assertEqual(self.store.sessions(), sessions)
        self.assertEqual(self.store.events(self.a), events)
        self.assertEqual(save_draft(self.store, self.a, 'Next edited preparation', 'plan',
                                    7, 'page-a', 1)['revision'], 8)


if __name__ == '__main__':
    unittest.main()
