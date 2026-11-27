"""Focused native older-history persistence and read-only acceptance."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest

from codex_desk.history_scan import NativeHistoryScanner
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class NativeSource:
    def __init__(self, home, prefix='native', count=260):
        self.home = Path(home)
        self.prefix = prefix
        self.calls, self.list_hold, self.read_hold = [], None, None
        self.failed_reads = set()
        self.cursors = {}
        self.rows = []
        self.threads = {}
        for position in range(1, count + 1):
            identifier = f'{prefix}-{position:03}'
            text = 'OLDER-230 retry budget decision' if position == 230 else f'Original evidence {position}'
            thread = {'id': identifier, 'name': f'Conversation {position}', 'cwd': '/missing/retained-project',
                      'modelProvider': 'fixture', 'updatedAt': 1795601000 - position,
                      'turns': [{'id': f'turn-{position}', 'status': 'completed',
                                 'items': [{'id': f'answer-{position}', 'type': 'agentMessage', 'text': text}]}]}
            self.rows.append({key: value for key, value in thread.items() if key != 'turns'})
            self.threads[identifier] = thread

    def catalog(self):
        return self

    def token(self, offset):
        token = f'{self.prefix} / opaque+页 ={offset}'
        self.cursors[token] = offset
        return token

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        assert method == 'thread/list', 'Native mutation requested: ' + method
        assert params['modelProviders'] == [] and params['sortKey'] == 'updated_at'
        cursor = params.get('cursor')
        offset = self.cursors[cursor] if cursor else 0
        if self.list_hold is not None and offset == self.list_hold[0]:
            _, entered, release = self.list_hold
            entered.set()
            assert release.wait(5), 'Listing hold was not released'
        size = params['limit']
        rows = self.rows[offset:offset + size]
        return {'data': copy.deepcopy(rows),
                'nextCursor': self.token(offset + len(rows)) if offset + len(rows) < len(self.rows) else None}

    def history(self, identifier):
        self.calls.append(('thread/read', {'threadId': identifier, 'includeTurns': True}))
        if self.read_hold is not None and identifier == self.read_hold[0]:
            _, entered, release = self.read_hold
            entered.set()
            assert release.wait(5), 'Read hold was not released'
        if identifier in self.failed_reads:
            raise RuntimeError('Controlled original history read unavailable')
        return copy.deepcopy(self.threads[identifier])


class OlderScanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='older-scan-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'state' / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.index = NativeRecallIndex(self.store)
        self.source = NativeSource(self.root / 'home-a')
        self.scanner = NativeHistoryScanner(self.source, self.index)
        self.addCleanup(lambda: self.scanner.close())

    def run_pass(self, scanner=None, **options):
        scanner = scanner or self.scanner
        scanner.start(**options)
        scanner.worker.join(10)
        self.assertFalse(scanner.worker.is_alive())
        return scanner.status()

    def reopen(self):
        self.scanner.close()
        self.store.db.close()
        self.store = Store(self.path)
        self.index = NativeRecallIndex(self.store)
        self.scanner = NativeHistoryScanner(self.source, self.index)

    def test_late_cancel_after_recent_last_row_persists_complete_boundary_and_home_isolation(self):
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-200', entered, release)
        self.scanner.start()
        try:
            self.assertTrue(entered.wait(10))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        status = self.scanner.status()
        self.assertEqual((status['status'], status['seen'], status['indexed'], status['older_available']),
                         ('completed', 200, 200, True))
        self.reopen()
        other = NativeSource(self.root / 'late-cancel-other-home', prefix='other')
        other_scan = NativeHistoryScanner(other, self.index)
        self.addCleanup(other_scan.close)
        self.assertFalse(other_scan.status()['older_available'])
        self.assertEqual(other.calls, [])
        self.source.read_hold = None
        self.run_pass(op='older')
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)

    def test_recent_200_then_explicit_older_finds_230th_exact_original_without_native_task_calls(self):
        recent = self.run_pass()
        self.assertEqual((recent['status'], recent['seen'], recent['indexed'], recent['older_available']),
                         ('completed', 200, 200, True))
        self.assertEqual(self.index.search('OLDER-230')['total'], 0)
        before = len(self.source.calls)
        self.reopen()
        self.assertEqual(len(self.source.calls), before)
        self.scanner.status()
        self.assertEqual(len(self.source.calls), before)
        older = self.run_pass(op='older')
        self.assertEqual((older['status'], older['seen'], older['indexed'], older['older_available']),
                         ('completed', 60, 60, False))
        hit = self.index.search('OLDER-230')['results'][0]
        self.assertEqual((hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('native-230', 'turn-230', 'answer-230'))
        self.assertEqual(self.index.stats()['indexed_threads'], 260)
        self.assertEqual(self.store.sessions(), [])
        self.assertTrue(all(method in ('thread/list', 'thread/read') for method, _ in self.source.calls))
        self.assertTrue(all(1 <= params['limit'] <= 30 for method, params in self.source.calls if method == 'thread/list'))

    def test_cancel_midpage_commits_current_read_keeps_every_unread_row_and_restart_resumes_it(self):
        self.run_pass()
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-203', entered, release)
        self.scanner.start(limit=30, op='older')
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        self.assertEqual((self.scanner.status()['status'], self.scanner.status()['seen']), ('cancelled', 3))
        state = self.scanner._load()
        self.assertEqual([row['id'] for row in state['continuation']['pending']],
                         [f'native-{position:03}' for position in range(204, 231)])
        self.assertEqual(state['continuation']['cursor'], self.source.token(200))
        self.assertEqual(state['continuation']['next_cursor'], self.source.token(230))
        before_calls = len(self.source.calls)
        self.reopen()
        self.assertEqual(len(self.source.calls), before_calls)
        self.source.read_hold = None
        continued = self.run_pass(op='older')
        self.assertEqual((continued['status'], continued['seen'], continued['limit']), ('completed', 30, 30))
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)
        self.assertEqual([method for method, _ in self.source.calls[before_calls:]], ['thread/read'] * 27)
        self.run_pass(op='older')
        self.assertEqual(self.index.stats()['indexed_threads'], 260)
        read_ids = [params['threadId'] for method, params in self.source.calls if method == 'thread/read']
        self.assertEqual(len(read_ids), len(set(read_ids)))

    def test_cancel_during_listing_persists_whole_unread_page_before_any_history_read(self):
        self.run_pass()
        entered, release = threading.Event(), threading.Event()
        self.source.list_hold = (200, entered, release)
        before = len(self.source.calls)
        self.scanner.start(limit=30, op='older')
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        self.assertEqual(self.scanner.status()['seen'], 0)
        self.assertEqual(len(self.scanner._load()['continuation']['pending']), 30)
        self.assertEqual([method for method, _ in self.source.calls[before:]], ['thread/list'])
        self.reopen()
        self.source.list_hold = None
        self.run_pass(op='older')
        self.assertEqual(self.index.stats()['indexed_threads'], 230)
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)

    def test_home_change_cannot_reuse_opaque_cursor_and_returning_home_preserves_its_boundary(self):
        self.run_pass(limit=100)
        boundary = self.scanner._load()['continuation']['cursor']
        other = NativeSource(self.root / 'home-b', prefix='other')
        other_scanner = NativeHistoryScanner(other, self.index)
        self.addCleanup(other_scanner.close)
        self.assertFalse(other_scanner.status()['older_available'])
        with self.assertRaises(ValueError):
            other_scanner.start(op='older')
        self.assertEqual(other.calls, [])
        self.run_pass(other_scanner, limit=200)
        first_options = next(params for method, params in other.calls if method == 'thread/list')
        self.assertNotIn('cursor', first_options)
        self.assertEqual(self.scanner._load()['continuation']['cursor'], boundary)
        self.run_pass(op='older')
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM native_history_scan_state').fetchone()[0], 2)

    def test_recent_refresh_never_rewinds_older_boundary_and_native_list_changes_skip_cached_rows(self):
        self.run_pass()
        self.run_pass(limit=30, op='older')
        boundary = copy.deepcopy(self.scanner._load()['continuation'])
        newest = copy.deepcopy(self.source.threads['native-001'])
        newest.update(id='native-new', name='Newest task', updatedAt=1795602000)
        self.source.threads['native-new'] = newest
        self.source.rows.insert(0, {key: value for key, value in newest.items() if key != 'turns'})
        refreshed = self.run_pass(op='recent')
        self.assertEqual((refreshed['indexed'], refreshed['skipped']), (1, 199))
        self.assertEqual(self.scanner._load()['continuation'], boundary)
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)
        continued = self.run_pass(op='older')
        self.assertEqual(continued['skipped'], 1)
        self.assertEqual(self.index.stats()['indexed_threads'], 261)

    def test_explicit_recent_refresh_rearms_exhausted_tail_for_newly_restored_old_history(self):
        self.run_pass()
        self.run_pass(op='older')
        self.assertFalse(self.scanner.status()['older_available'])
        restored = copy.deepcopy(self.source.threads['native-260'])
        restored.update(id='restored-old', name='Restored old conversation', updatedAt=1795600500)
        restored['turns'][0]['items'][0]['text'] = 'RESTORED OLD ANSWER'
        self.source.threads[restored['id']] = restored
        self.source.rows.append({key: value for key, value in restored.items() if key != 'turns'})
        refreshed = self.run_pass(op='recent')
        self.assertEqual((refreshed['indexed'], refreshed['skipped'], refreshed['older_available']), (0, 200, True))
        self.assertEqual(self.index.stats()['indexed_threads'], 260)
        self.assertEqual(self.index.search('RESTORED OLD ANSWER')['total'], 0)
        self.run_pass(op='older')
        self.assertEqual(self.index.stats()['indexed_threads'], 261)
        self.assertEqual(self.index.search('RESTORED OLD ANSWER')['results'][0]['thread_id'], 'restored-old')

    def test_cached_snapshot_replay_skips_read_and_catches_up_existing_bound_evidence(self):
        self.run_pass()
        # A cache commit can precede durable row advancement. Replay uses that
        # full snapshot rather than rereading it or losing its local binding.
        thread = self.source.threads['native-201']
        self.index.replace_snapshot(thread)
        binding = self.store.create('/missing/retained-project', 'default', identifier='bound-201', name='Retained task')
        self.store.update(binding, thread_id=thread['id'], status='saved')
        self.assertEqual(self.store.recall('Original evidence 201')['total'], 0)
        before = len(self.source.calls)
        older = self.run_pass(limit=30, op='older')
        self.assertEqual((older['indexed'], older['skipped']), (29, 1))
        self.assertNotIn('native-201', [params['threadId'] for method, params in self.source.calls[before:]
                                       if method == 'thread/read'])
        hit = self.store.recall('Original evidence 201')['results'][0]
        self.assertEqual((hit['session_id'], hit['turn_id'], hit['item_id']), ('bound-201', 'turn-201', 'answer-201'))
        self.assertEqual(self.store.get(binding)['status'], 'saved')

    def test_failed_older_read_survives_completed_pass_and_restart_for_explicit_retry(self):
        self.run_pass()
        self.source.failed_reads.add('native-230')
        older = self.run_pass(limit=30, op='older')
        self.assertEqual((older['status'], older['indexed'], older['failed'], older['retryable_failures']),
                         ('completed', 29, 1, 1))
        self.assertEqual(self.index.search('OLDER-230')['total'], 0)
        boundary = copy.deepcopy(self.scanner._load()['continuation'])
        self.reopen()
        self.source.failed_reads.clear()
        before = len(self.source.calls)
        retried = self.run_pass(op='retry')
        self.assertEqual((retried['seen'], retried['indexed'], retried['retryable_failures']), (1, 1, 0))
        self.assertEqual([method for method, _ in self.source.calls[before:]], ['thread/read'])
        self.assertEqual(self.scanner._load()['continuation'], boundary)
        self.assertEqual(self.index.search('OLDER-230')['total'], 1)

    def test_saved_running_job_is_paused_on_reopen_until_explicit_continue(self):
        self.run_pass()
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-202', entered, release)
        self.scanner.start(op='older')
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        state = self.scanner._load()
        state['job']['status'] = 'running'  # Persisted checkpoint left by process exit.
        self.scanner._save(state)
        before = len(self.source.calls)
        self.reopen()
        status = self.scanner.status()
        self.assertEqual((status['status'], status['seen'], status['resumable']), ('paused', 2, True))
        self.assertIsNone(self.scanner.worker)
        self.assertEqual(len(self.source.calls), before)
        self.source.read_hold = None
        self.run_pass(op='retry')
        resumed = self.source.calls[before:]
        self.assertEqual([params['threadId'] for method, params in resumed[:28]],
                         [f'native-{i:03}' for i in range(203, 231)])
        self.assertEqual(resumed[28], ('thread/list', {'limit': 30, 'modelProviders': [],
                          'sortKey': 'updated_at', 'cursor': self.source.token(230)}))
        self.assertEqual(self.index.stats()['indexed_threads'], 260)

    def test_older_project_scope_is_complete_beyond_first_100_projects_and_never_requires_cwd(self):
        for position, row in enumerate(self.source.rows, 1):
            row['cwd'] = f'/missing/project-{position:03}'
            self.source.threads[row['id']]['cwd'] = row['cwd']
        self.run_pass()
        self.assertEqual(len(self.index.projects()), 200)
        self.assertNotIn('/missing/project-230', self.index.projects())
        self.assertEqual(self.index.search('OLDER-230', '/missing/project-230')['total'], 0)
        self.run_pass(op='older')
        self.assertEqual(self.index.projects(), sorted(f'/missing/project-{i:03}' for i in range(1, 261)))
        hit = self.index.search('OLDER-230', '/missing/project-230')['results'][0]
        self.assertEqual(hit['thread_id'], 'native-230')
        self.assertEqual(self.index.search('OLDER-230', '/missing/project-229')['total'], 0)
        self.reopen()
        before = len(self.source.calls)
        self.assertEqual(len(self.index.projects()), 260)
        self.assertEqual(self.index.search('OLDER-230', '/missing/project-230')['total'], 1)
        self.assertEqual(len(self.source.calls), before)

    def test_failed_older_listing_retries_saved_cursor_after_restart(self):
        self.run_pass()
        ordinary = self.source.request
        fail = [True]
        def request(method, params):
            if fail[0] and params.get('cursor') == self.source.token(200):
                fail[0] = False
                raise TimeoutError('Controlled older listing interruption')
            return ordinary(method, params)
        self.source.request = request
        status = self.run_pass(op='older')
        self.assertEqual((status['status'], status['seen'], status['resumable'], status['older_available']),
                         ('failed', 0, True, True))
        boundary = copy.deepcopy(self.scanner._load()['continuation'])
        before = len(self.source.calls)
        self.reopen()
        self.assertEqual(len(self.source.calls), before)
        self.assertEqual(self.scanner._load()['continuation'], boundary)
        self.run_pass(op='retry')
        first = self.source.calls[before]
        self.assertEqual(first, ('thread/list', {'limit': 30, 'modelProviders': [],
                          'sortKey': 'updated_at', 'cursor': self.source.token(200)}))
        self.assertEqual(self.index.stats()['indexed_threads'], 260)

    def test_incomplete_initial_recent_pass_keeps_page_and_seeds_older_only_after_continue(self):
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-003', entered, release)
        self.scanner.start()
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        status = self.scanner.status()
        self.assertEqual((status['seen'], status['older_available'], status['resumable']), (3, False, True))
        with self.assertRaises(ValueError):
            self.scanner.start(op='older')
        before = len(self.source.calls)
        self.reopen()
        self.source.read_hold = None
        continued = self.run_pass(op='retry')
        self.assertEqual((continued['seen'], continued['indexed'], continued['older_available']), (200, 200, True))
        self.assertEqual([params['threadId'] for method, params in self.source.calls[before:before+27]],
                         [f'native-{i:03}' for i in range(4, 31)])
        self.assertEqual(self.index.stats()['indexed_threads'], 200)
        self.run_pass(op='older')
        self.assertEqual(self.index.stats()['indexed_threads'], 260)




    def test_cancelled_older_pending_survives_recent_refresh(self):
        self.source.rows = self.source.rows[:35]
        self.run_pass(limit=10)
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-012', entered, release)
        self.scanner.start(limit=10, op='older')
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        boundary = copy.deepcopy(self.scanner._load()['continuation'])
        self.assertEqual([row['id'] for row in boundary['pending']],
                         [f'native-{i:03}' for i in range(13, 21)])
        self.source.read_hold = None
        newest = copy.deepcopy(self.source.threads['native-001'])
        newest.update(id='native-new', name='New recent', updatedAt=1795602000)
        self.source.threads[newest['id']] = newest
        self.source.rows.insert(0, {k:v for k,v in newest.items() if k != 'turns'})
        recent = self.run_pass(limit=10, op='recent')
        self.assertEqual((recent['indexed'], recent['skipped']), (1, 9))
        self.assertEqual(self.scanner._load()['continuation'], boundary)
        self.reopen()
        before = len(self.source.calls)
        self.run_pass(limit=10, op='older')
        self.assertEqual([params['threadId'] for method, params in self.source.calls[before:8+before]],
                         [f'native-{i:03}' for i in range(13, 21)])
        self.run_pass(op='older')
        self.assertEqual(self.index.stats()['indexed_threads'], 36)
        reads = [params['threadId'] for method, params in self.source.calls if method == 'thread/read']
        self.assertEqual(len(reads), len(set(reads)))

    def test_cancelled_retry_survives_restart_and_does_not_change_older_boundary(self):
        self.source.rows = self.source.rows[:35]
        self.source.failed_reads.update(('native-003', 'native-005', 'native-009'))
        self.run_pass(limit=10)
        boundary = copy.deepcopy(self.scanner._load()['continuation'])
        self.source.failed_reads.clear()
        entered, release = threading.Event(), threading.Event()
        self.source.read_hold = ('native-003', entered, release)
        self.scanner.start(op='retry')
        try:
            self.assertTrue(entered.wait(5))
            self.scanner.cancel()
        finally:
            release.set()
        self.scanner.worker.join(10)
        status = self.scanner.status()
        self.assertEqual((status['status'], status['seen'], status['retryable_failures']), ('cancelled', 1, 2))
        self.assertEqual(self.scanner._load()['continuation'], boundary)
        self.reopen()
        self.source.read_hold = None
        before = len(self.source.calls)
        status = self.run_pass(op='retry')
        self.assertEqual((status['status'], status['seen'], status['indexed'], status['retryable_failures']),
                         ('completed', 3, 3, 0))
        self.assertEqual(self.source.calls[before:], [
            ('thread/read', {'threadId': 'native-005', 'includeTurns': True}),
            ('thread/read', {'threadId': 'native-009', 'includeTurns': True})])
        self.assertEqual(self.scanner._load()['continuation'], boundary)

    def test_failure_on_second_page_of_initial_recent_preserves_cursor_and_resumes_without_replay(self):
        self.source.rows = self.source.rows[:35]
        base = self.source.request
        fail = [True]
        def request(method, params):
            if fail[0] and params.get('cursor') == self.source.token(30):
                fail[0] = False
                raise TimeoutError('Controlled second-page failure')
            return base(method, params)
        self.source.request = request
        status = self.run_pass()
        self.assertEqual((status['status'], status['seen'], status['resumable'], status['older_available']),
                         ('failed', 30, True, False))
        self.assertEqual(self.scanner._load()['job']['checkpoint']['cursor'], self.source.token(30))
        self.reopen()
        before = len(self.source.calls)
        status = self.run_pass(op='retry')
        self.assertEqual((status['status'], status['seen'], status['indexed']), ('completed', 35, 35))
        self.assertEqual(self.source.calls[before], ('thread/list', {
            'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at', 'cursor': self.source.token(30)}))
        self.assertEqual(self.index.stats()['indexed_threads'], 35)

if __name__ == '__main__':
    unittest.main()
