import sqlite3
import threading
import unittest
from types import SimpleNamespace
from codex_desk.history_scan import NativeHistoryScanner
from codex_desk.native_recall import NativeRecallIndex


class HistoryScanTests(unittest.TestCase):
    def scanner(self, pages, failed=(), fresh=()):
        calls, saved = [], []
        def request(method, params):
            calls.append((method, params))
            return pages.get(params.get('cursor'), {'data': [], 'nextCursor': None})
        def history(identifier):
            calls.append(('thread/read', identifier))
            if identifier in failed:
                raise ValueError('Read unavailable')
            return {'id': identifier, 'turns': []}
        store = SimpleNamespace(db=sqlite3.connect(':memory:', check_same_thread=False), lock=threading.RLock())
        self.addCleanup(store.db.close)
        index = SimpleNamespace(store=store, needs_snapshot=lambda m: m['id'] not in fresh,
                                replace_snapshot=lambda t: saved.append(t),
                                catch_up_bindings=lambda identifier: None)
        desk = SimpleNamespace(home='/fixture/native-home', catalog=lambda: SimpleNamespace(request=request), history=history)
        scan = NativeHistoryScanner(desk, index)
        self.addCleanup(scan.close)
        return scan, calls, saved

    def finish(self, scan, limit=200):
        scan.start(limit)
        scan.worker.join(3)
        self.assertFalse(scan.worker.is_alive())
        return scan.status()

    def test_metadata_list_read_only_paging_and_no_resume_or_turn(self):
        scan, calls, saved = self.scanner({None: {'data':[{'id':'a','name':'Existing A'}],'nextCursor':'next'},
                                         'next':{'data':[{'id':'b'}],'nextCursor':None}})
        result = self.finish(scan)
        self.assertEqual((result['status'], result['seen'], result['indexed']), ('completed',2,2))
        self.assertEqual([c[0] for c in calls], ['thread/list','thread/read','thread/list','thread/read'])
        self.assertEqual(saved[0]['name'], 'Existing A')

    def test_unchanged_skips_and_one_read_failure_does_not_discard_other_work(self):
        scan, calls, saved = self.scanner({None:{'data':[{'id':v} for v in ['old','missing','good']], 'nextCursor':None}}, failed=['missing'], fresh=['old'])
        result = self.finish(scan)
        self.assertEqual((result['skipped'],result['failed'],result['indexed']), (1,1,1))
        self.assertEqual([t['id'] for t in saved], ['good'])
        self.assertNotIn(('thread/read','old'), calls)

    def test_fresh_and_skipped_scans_catch_up_bindings_but_failed_reads_do_not(self):
        scan, calls, saved = self.scanner(
            {None: {'data': [{'id': v} for v in ('old', 'missing', 'good')], 'nextCursor': None}},
            failed=['missing'], fresh=['old'])
        copied = []
        def catch_up(identifier):
            if identifier == 'good':
                self.assertEqual([thread['id'] for thread in saved], ['good'])
            copied.append(identifier)
        scan.index.catch_up_bindings = catch_up
        result = self.finish(scan)
        self.assertEqual((result['skipped'], result['failed'], result['indexed']), (1, 1, 1))
        self.assertEqual(copied, ['old', 'good'])
        self.assertNotIn(('thread/read', 'old'), calls)

    def test_default_pass_pages_exactly_200_and_repeated_pass_only_lists_unchanged(self):
        fresh = set()
        scan, calls, saved = self.scanner({}, fresh=fresh)
        rows = [{'id': f'thread-{i}'} for i in range(231)]
        def request(method, params):
            calls.append((method, params))
            start = int(params.get('cursor', '0'))
            end = min(start + params['limit'], len(rows))
            return {'data': rows[start:end],
                    'nextCursor': str(end) if end < len(rows) else None}
        def replace(thread):
            saved.append(thread)
            fresh.add(thread['id'])
        scan.desk.catalog = lambda: SimpleNamespace(request=request)
        scan.index.replace_snapshot = replace
        first = self.finish(scan)
        self.assertEqual((first['seen'], first['indexed'], first['has_more']), (200, 200, True))
        self.assertEqual([params['limit'] for method, params in calls if method == 'thread/list'],
                         [30, 30, 30, 30, 30, 30, 20])
        self.assertEqual([thread['id'] for thread in saved], [row['id'] for row in rows[:200]])
        calls.clear()
        second = self.finish(scan)
        self.assertEqual((second['seen'], second['indexed'], second['skipped'], second['has_more']),
                         (200, 0, 200, True))
        self.assertEqual([method for method, _ in calls], ['thread/list'] * 7)
        self.assertEqual(len(saved), 200)

    def test_cancel_single_worker_and_limit(self):
        scan, calls, saved = self.scanner({})
        entered, release = threading.Event(), threading.Event()
        def request(method, params):
            entered.set(); release.wait(3)
            return {'data':[{'id':'never-read'}], 'nextCursor':'next'}
        scan.desk.catalog=lambda:SimpleNamespace(request=request)
        scan.start(1); self.assertTrue(entered.wait(1)); worker=scan.worker
        scan.start(20); self.assertIs(scan.worker,worker)
        scan.cancel(); release.set(); worker.join(3)
        self.assertEqual(scan.status()['status'], 'cancelled')
        self.assertFalse(saved)
        for invalid in (0,1001,True,'20'):
            with self.assertRaises(ValueError): scan.start(invalid)

    def test_limit_reports_remaining_history_and_repeated_cursor_stops(self):
        scan, calls, saved = self.scanner({None:{'data':[{'id':'a'},{'id':'b'}], 'nextCursor':'next'}})
        result=self.finish(scan,1)
        self.assertEqual(result['indexed'],1);self.assertTrue(result['has_more'])
        scan, calls, saved=self.scanner({None:{'data':[],'nextCursor':'again'}, 'again':{'data':[],'nextCursor':'again'}})
        self.assertEqual(self.finish(scan)['status'],'failed')

    def real_index(self):
        store = SimpleNamespace(db=sqlite3.connect(':memory:', check_same_thread=False),
                                lock=threading.RLock())
        self.addCleanup(store.db.close)
        return NativeRecallIndex(store)

    def test_read_metadata_is_authoritative_when_list_becomes_stale(self):
        old = {'id': 'changing', 'name': 'Old title', 'cwd': '/old-project',
               'modelProvider': 'old-provider', 'updatedAt': 1795625000}
        current = {**old, 'name': 'Current title', 'cwd': '/current-project',
                   'modelProvider': 'current-provider', 'updatedAt': 1795625010}
        scan, calls, saved = self.scanner({None: {'data': [old], 'nextCursor': None}})
        scan.index = self.real_index()
        scan.desk.history = lambda _: {**current, 'turns': [
            {'id': 'turn', 'items': [{'id': 'item', 'type': 'agentMessage',
                                      'text': 'Current accepted decision'}]}]}
        self.assertEqual(self.finish(scan)['indexed'], 1)
        hit = scan.index.search('accepted decision')['results'][0]
        self.assertEqual((hit['title'], hit['cwd'], hit['provider'], hit['updated']),
                         ('Current title', '/current-project', 'current-provider', current['updatedAt']))
        self.assertFalse(scan.index.needs_snapshot(current))
        self.assertTrue(scan.index.needs_snapshot(old))

    def test_older_read_is_not_marked_fresh_at_newer_list_timestamp(self):
        metadata = {'id': 'changing', 'name': 'Saved title', 'updatedAt': 1795625010}
        scan, calls, saved = self.scanner({None: {'data': [metadata], 'nextCursor': None}})
        scan.index = self.real_index()
        reads = []
        def history(identifier):
            reads.append(identifier)
            return {'id': identifier, 'updatedAt': metadata['updatedAt'] - (10 if len(reads) == 1 else 0),
                    'turns': [{'id': 'turn', 'items': [{'id': 'item', 'type': 'agentMessage',
                        'text': 'Older proof' if len(reads) == 1 else 'Current proof'}]}]}
        scan.desk.history = history
        self.assertEqual(self.finish(scan)['indexed'], 1)
        self.assertTrue(scan.index.needs_snapshot(metadata))
        self.assertEqual(self.finish(scan)['indexed'], 1)
        self.assertEqual(scan.index.search('older proof')['total'], 0)
        self.assertEqual(scan.index.search('current proof')['total'], 1)
        self.assertFalse(scan.index.needs_snapshot(metadata))
        self.assertEqual(self.finish(scan)['skipped'], 1)
        self.assertEqual(len(reads), 2)

    def test_missing_read_metadata_uses_list_and_skips_next_scan(self):
        metadata = {'id': 'partial', 'name': 'Catalog title', 'cwd': '/deleted-project',
                    'modelProvider': 'catalog-provider', 'updatedAt': 1795625000}
        scan, calls, saved = self.scanner({None: {'data': [metadata], 'nextCursor': None}})
        scan.index = self.real_index()
        scan.desk.history = lambda _: {'id': 'partial', 'name': None, 'updatedAt': None,
            'turns': [{'id': 'turn', 'items': [{'id': 'item', 'type': 'agentMessage',
                                              'text': 'Preserved catalog proof'}]}]}
        self.assertEqual(self.finish(scan)['indexed'], 1)
        hit = scan.index.search('catalog proof')['results'][0]
        self.assertEqual((hit['title'], hit['cwd'], hit['provider']),
                         ('Catalog title', '/deleted-project', 'catalog-provider'))
        self.assertEqual(self.finish(scan)['skipped'], 1)

    def test_active_full_read_stays_refreshable_for_same_second_new_completed_answer(self):
        metadata = {'id': 'same-second', 'name': 'Saved decision', 'updatedAt': 1795625000,
                    'status': {'type': 'active', 'activeFlags': []}}
        page = {'data': [metadata], 'nextCursor': None}
        scan, calls, saved = self.scanner({None: page})
        scan.index = self.real_index()
        current = {**metadata, 'turns': [{'id': 'turn', 'status': 'inProgress', 'items': []}]}
        def history(identifier):
            calls.append(('thread/read', identifier))
            return current
        scan.desk.history = history
        self.assertEqual(self.finish(scan)['indexed'], 1)
        self.assertEqual(scan.index.stats()['indexed_threads'], 1)
        self.assertEqual(scan.index.search('same-second choice')['total'], 0)
        metadata['status'] = {'type': 'idle'}
        current = {**metadata, 'turns': [{'id': 'turn', 'status': 'completed', 'items': [
            {'id': 'new-answer', 'type': 'agentMessage', 'text': 'Keep the same-second choice'}]}]}
        second = self.finish(scan)
        self.assertEqual((second['status'], second['indexed'], second['skipped'], second['failed']),
                         ('completed', 1, 0, 0))
        hit = scan.index.search('same-second choice')['results'][0]
        self.assertEqual((hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('same-second', 'turn', 'new-answer'))
        calls.clear()
        self.assertEqual(self.finish(scan)['skipped'], 1)
        self.assertEqual([method for method, _ in calls], ['thread/list'])
        self.assertEqual(scan.index.stats()['indexed_items'], 1)

    def test_active_listing_forces_read_with_same_timestamp_as_previous_completed_cache(self):
        metadata = {'id': 'newly-active', 'name': 'Saved decision', 'updatedAt': 1795625000,
                    'status': {'type': 'active', 'activeFlags': []}}
        scan, calls, saved = self.scanner({None: {'data': [metadata], 'nextCursor': None}})
        scan.index = self.real_index()
        scan.index.replace_snapshot({**metadata, 'status': {'type': 'idle'}, 'turns': [
            {'id': 'old-turn', 'status': 'completed', 'items': [
                {'id': 'old-answer', 'type': 'agentMessage', 'text': 'Earlier choice'}]}]})
        def history(identifier):
            calls.append(('thread/read', identifier))
            return {**metadata, 'status': {'type': 'idle'}, 'turns': [
                {'id': 'new-turn', 'status': 'completed', 'items': [
                    {'id': 'new-answer', 'type': 'agentMessage', 'text': 'New completed choice'}]}]}
        scan.desk.history = history
        self.assertEqual(self.finish(scan)['indexed'], 1)
        self.assertEqual([method for method, _ in calls], ['thread/list', 'thread/read'])
        self.assertEqual(scan.index.search('earlier choice')['total'], 0)
        self.assertEqual(scan.index.search('new completed choice')['total'], 1)
        metadata['status'] = {'type': 'idle'}
        calls.clear()
        self.assertEqual(self.finish(scan)['skipped'], 1)
        self.assertEqual([method for method, _ in calls], ['thread/list'])

    def test_cancel_during_failed_listing_finishes_cancelled_without_error(self):
        scan, calls, saved = self.scanner({})
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def request(method, params):
            entered.set()
            if not release.wait(3):
                raise AssertionError('Fixture wait expired')
            raise TimeoutError('Native listing timed out')
        scan.desk.catalog = lambda: SimpleNamespace(request=request)
        scan.start()
        self.assertTrue(entered.wait(1))
        scan.cancel()
        release.set()
        scan.worker.join(3)
        self.assertFalse(scan.worker.is_alive())
        self.assertEqual(scan.status()['status'], 'cancelled')
        self.assertNotIn('error', scan.status())
        self.assertFalse(saved)


if __name__=='__main__': unittest.main()
