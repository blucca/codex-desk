"""Persisted next-task preparation and optimistic multi-page saving."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from codex_desk import drafts
from codex_desk.drafts import DraftConflict, load_draft, save_draft
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

if __name__ == '__main__':
    unittest.main()
