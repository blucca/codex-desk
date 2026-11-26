"""Explicit history indexing and cold literal recall through real loopback HTTP."""
import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


def snapshot(identifier, text='Saved unopened phrase', *, updated=1795625000, count=1):
    return {'id': identifier, 'updatedAt': updated, 'turns': [
        {'id': 'turn-' + identifier, 'completedAt': updated, 'items': [
            {'id': 'item-' + str(i), 'type': 'agentMessage', 'text': text}
            for i in range(count)]}]}


class NativeHistoryApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-native-history-api-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        runtime = patch('codex_desk.server.Runtime', side_effect=AssertionError('Unexpected native runtime'))
        self.runtime = runtime.start()
        self.addCleanup(runtime.stop)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.pages = {None: {'data': [], 'nextCursor': None}}
        self.histories, self.calls = {}, []
        self.catalog = Mock(spec=['request'])
        self.catalog.request.side_effect = self.native_request
        catalog = patch.object(self.desk, 'catalog', return_value=self.catalog)
        self.catalog_factory = catalog.start()
        self.addCleanup(catalog.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def native_request(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            return self.pages[params.get('cursor')]
        if method == 'thread/read':
            self.assertEqual(set(params), {'threadId', 'includeTurns'})
            self.assertIs(params['includeTurns'], True)
            result = self.histories[params['threadId']]
            if isinstance(result, Exception):
                raise result
            return {'thread': result}
        raise AssertionError('Unexpected native method: ' + method)

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        payload = json.dumps(data).encode() if method == 'POST' else None
        request_headers = {'Content-Type': 'application/json'} if payload is not None else {}
        request_headers.update(headers or {})
        try:
            conn.request(method, path, body=payload, headers=request_headers)
            response = conn.getresponse()
            body = response.read()
            if response.getheader('Content-Type', '').startswith('application/json'):
                body = json.loads(body)
            return response.status, body, response.getheader('Cache-Control')
        finally:
            conn.close()

    def recall(self, **query):
        return self.request('GET', '/api/recall?' + urlencode(query))

    def finish(self):
        worker = self.desk.history_scanner.worker
        self.assertIsNotNone(worker)
        worker.join(3)
        self.assertFalse(worker.is_alive())
        status, result, cache = self.request('GET', '/api/history/index')
        self.assertEqual((status, cache), (200, 'no-store'))
        return result

    def native(self, identifier, text='Saved unopened phrase', *, updated=1795625000,
               project=None, count=1):
        metadata = {'id': identifier, 'name': 'Saved ' + identifier, 'modelProvider': 'fixture-provider',
                    'cwd': str(project or self.root / 'project'), 'updatedAt': updated}
        self.histories[identifier] = snapshot(identifier, text, updated=updated, count=count)
        return metadata

    def index(self, rows, limit=200):
        self.pages = {None: {'data': rows, 'nextCursor': None}}
        status, _, _ = self.request('POST', '/api/history/index', {'limit': limit})
        self.assertEqual(status, 200)
        return self.finish()

    def test_startup_page_state_status_and_recall_do_not_index_or_contact_native(self):
        before = list(self.desk.store.db.iterdump())
        self.runtime.assert_not_called()
        self.assertIsNone(self.desk.history_scanner.worker)
        for path in ('/', '/api/state', '/api/history/index'):
            self.assertEqual(self.request('GET', path)[0], 200)
        status, result, cache = self.recall(q='unopened phrase')
        self.assertEqual((status, cache, result['total']), (200, 'no-store', 0))
        self.assertEqual(result['coverage']['native']['indexed_threads'], 0)
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.desk.runtimes, {})
        self.catalog_factory.assert_not_called()
        self.assertIsNone(self.desk.history_scanner.worker)

    def test_explicit_default_start_pages_read_only_and_searches_unopened_with_private_cache(self):
        first = self.native('unopened-a', 'Literal 项目验证 + RÉSUMÉ [accepted].')
        second = self.native('unopened-b', 'Independent saved verification.')
        self.pages = {None: {'data': [first], 'nextCursor': 'page-2'},
                      'page-2': {'data': [second], 'nextCursor': None}}
        before = self.desk.store.sessions()
        self.assertEqual(self.recall(q='项目验证 + résumé [accepted]')[1]['total'], 0)
        with patch.object(self.desk, 'open') as opened, patch.object(self.desk, 'import_thread') as imported:
            status, job, _ = self.request('POST', '/api/history/index', {})
            self.assertEqual((status, job['limit'], job['status']), (200, 200, 'running'))
            finished = self.finish()
            status, result, _ = self.recall(q='项目验证 + résumé [accepted]')
            opened.assert_not_called()
            imported.assert_not_called()
        self.assertEqual((finished['job']['status'], finished['job']['seen'],
                          finished['job']['indexed'], finished['job']['failed']), ('completed', 2, 2, 0))
        self.assertEqual(finished['coverage']['indexed_threads'], 2)
        self.assertEqual(status, 200)
        hit = result['results'][0]
        self.assertEqual((hit['kind'], hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('native-activity', 'unopened-a', 'turn-unopened-a', 'item-0'))
        self.assertEqual((hit['name'], hit['profile'], hit['archived']), ('Saved unopened-a', 'default', False))
        self.assertEqual(hit['provider'], 'fixture-provider')
        self.assertNotIn('session_id', hit)
        self.assertEqual(hit['match_text'], '项目验证 + RÉSUMÉ [accepted]')
        self.assertEqual(self.desk.store.sessions(), before)
        self.assertEqual(self.desk.store.db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
        self.assertEqual(self.desk.runtimes, {})
        self.runtime.assert_not_called()
        self.assertEqual(self.calls, [
            ('thread/list', {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at'}),
            ('thread/read', {'threadId': 'unopened-a', 'includeTurns': True}),
            ('thread/list', {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at', 'cursor': 'page-2'}),
            ('thread/read', {'threadId': 'unopened-b', 'includeTurns': True})])
        path = self.root / 'state' / 'desk.sqlite3'
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)

    def test_combined_activity_preparation_and_native_total_limit_order_preserve_local_shapes(self):
        project = self.root / 'project'
        identifier = self.desk.store.create(str(project), 'default', name='Opened work')
        self.desk.store.update(identifier, thread_id='opened', status='saved')
        base = int(time.time()) - 100
        opened = {'id': 'opened', 'turns': [
            {'id': 'turn-' + str(i), 'completedAt': base + i * 2, 'items': [
                {'id': 'local-' + str(i), 'type': 'agentMessage', 'text': 'combined phrase local'}]}
            for i in range(40)]}
        self.desk.store.recall_snapshot(identifier, opened)
        save_draft(self.desk.store, identifier, 'combined phrase saved draft', 'plan', 0)
        add_followup(self.desk.store, identifier, 'combined phrase follow-up', 'native')
        rows = [self.native('unopened-' + str(i), 'combined phrase native', updated=base + i * 2 + 1)
                for i in range(40)]
        self.index(rows)
        local = self.desk.store.recall('combined phrase', limit=50)
        status, result, _ = self.recall(q='combined phrase', limit=50)
        self.assertEqual((status, result['total'], len(result['results']), result['truncated']), (200, 82, 50, True))
        self.assertEqual([hit['updated'] for hit in result['results']],
                         sorted((hit['updated'] for hit in result['results']), reverse=True))
        self.assertEqual({hit['kind'] for hit in result['results'][:2]}, {'draft', 'followup'})
        self.assertEqual({hit['kind'] for hit in result['results']}, {'activity', 'native-activity', 'draft', 'followup'})
        for hit in result['results']:
            if hit['kind'] != 'native-activity':
                original = {key: value for key, value in hit.items() if key != 'thread_id'}
                self.assertIn(original, local['results'])
                if hit['kind'] == 'activity':
                    self.assertEqual(hit['thread_id'], 'opened')
                else:
                    self.assertNotIn('thread_id', hit)
        for key, value in local['coverage'].items():
            self.assertEqual(result['coverage'][key], value)
        self.assertEqual(result['coverage']['native']['indexed_threads'], 40)
        limited = self.recall(q='combined phrase', limit=1)[1]
        self.assertEqual((limited['total'], len(limited['results']), limited['truncated']), (82, 1, True))

    def test_all_profile_bindings_exclude_native_duplicates_even_when_archived_or_outside_scope(self):
        project, other = self.root / 'project', self.root / 'other'
        local_ids = []
        for folder, profile in ((project, 'default'), (other, 'sidecar:work')):
            identifier = self.desk.store.create(str(folder), profile)
            self.desk.store.update(identifier, thread_id='bound', status='saved')
            self.desk.store.recall_snapshot(identifier, snapshot('bound', 'scope phrase', count=60))
            local_ids.append(identifier)
        # Exact identities, not just a shared thread, duplicate the saved rows.
        # More duplicates than the recall limit must be excluded before LIMIT/count.
        self.index([self.native('bound', 'scope phrase cached duplicate', count=60),
                    self.native('unbound', 'scope phrase unopened', updated=100, project=project)])
        self.assertEqual(self.recall(q='scope phrase')[1]['total'], 121)
        self.assertEqual(self.recall(q='scope phrase', cwd=str(project), limit=1)[1]['total'], 61)
        self.desk.store.archive(local_ids[0], True)
        scoped = self.recall(q='scope phrase', cwd=str(project))[1]
        self.assertEqual(scoped['total'], 1)
        self.assertEqual(scoped['results'][0]['thread_id'], 'unbound')
        archived = self.recall(q='scope phrase', cwd=str(project), archived='true')[1]
        self.assertEqual(archived['total'], 61)
        self.assertTrue(next(hit for hit in archived['results'] if hit['kind'] == 'activity')['archived'])
        self.desk.store.archive(local_ids[1], True)
        self.assertEqual(self.recall(q='scope phrase')[1]['total'], 1)
        self.assertEqual(self.recall(q='scope phrase', archived='true')[1]['total'], 121)
        self.assertEqual(self.recall(q='scope phrase', cwd=str(other))[1]['total'], 0)
        self.assertEqual(len(self.desk.store.sessions()), 2)

    def test_bound_activity_keeps_original_thread_for_deleted_project_read_without_archive_leak(self):
        project = self.root / 'deleted-imported-project'
        project.mkdir()
        metadata = self.native('bound-original', 'Bound retained answer', project=project)
        original = {**self.histories['bound-original'], 'cwd': str(project), 'name': metadata['name']}
        self.histories['bound-original'] = original
        identifier = self.desk.store.create(str(project), 'default', name='Previously imported work')
        self.desk.store.update(identifier, thread_id='bound-original', status='saved', thread_saved=1)
        self.desk.store.recall_snapshot(identifier, original)
        save_draft(self.desk.store, identifier, 'Bound preparation phrase', 'plan', 0)
        add_followup(self.desk.store, identifier, 'Bound preparation phrase', 'native')
        project.rmdir()
        self.index([metadata])
        self.calls.clear()
        before = list(self.desk.store.db.iterdump())
        local = self.desk.store.recall('Bound retained answer')['results'][0]
        with patch.object(self.desk, 'open') as opened, patch.object(self.desk, 'import_thread') as imported:
            status, result, _ = self.recall(q='Bound retained answer', cwd=str(project))
            self.assertEqual((status, result['total']), (200, 1))
            self.assertEqual(result['results'], [{**local, 'thread_id': 'bound-original'}])
            hit = result['results'][0]
            self.assertEqual((hit['kind'], hit['session_id'], hit['thread_id'], hit['turn_id'], hit['item_id']),
                             ('activity', identifier, 'bound-original', 'turn-bound-original', 'item-0'))
            preparation = self.recall(q='Bound preparation phrase')[1]['results']
            self.assertEqual({hit['kind'] for hit in preparation}, {'draft', 'followup'})
            self.assertTrue(all('thread_id' not in hit for hit in preparation))
            status, read, cache = self.request('GET', '/api/native/thread?id=' + hit['thread_id'])
            self.assertEqual((status, cache, read), (200, 'no-store', original))
            opened.assert_not_called()
            imported.assert_not_called()
        self.assertFalse(project.exists())
        self.assertEqual(self.calls, [('thread/read', {'threadId': 'bound-original', 'includeTurns': True})])
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.runtime.assert_not_called()
        self.desk.store.archive(identifier, True)
        self.assertEqual(self.recall(q='Bound retained answer')[1]['total'], 0)
        archived = self.recall(q='Bound retained answer', archived='true')[1]
        self.assertEqual(archived['total'], 1)
        self.assertEqual((archived['results'][0]['kind'], archived['results'][0]['thread_id'],
                          archived['results'][0]['archived']), ('activity', 'bound-original', True))

    def test_repeated_index_skips_fresh_reads_replaces_same_ids_and_cold_reopen_keeps_cache(self):
        meta = self.native('stable-id', 'Old saved decision')
        first = self.index([meta])
        self.assertEqual(first['job']['indexed'], 1)
        self.calls.clear()
        second = self.index([meta])
        self.assertEqual((second['job']['indexed'], second['job']['skipped']), (0, 1))
        self.assertEqual([method for method, _ in self.calls], ['thread/list'])
        meta['updatedAt'] += 1
        self.histories['stable-id'] = snapshot('stable-id', 'Corrected saved decision', updated=meta['updatedAt'])
        self.assertEqual(self.index([meta])['job']['indexed'], 1)
        self.assertEqual(self.recall(q='Old saved decision')[1]['total'], 0)
        fresh = self.recall(q='Corrected saved decision')[1]
        self.assertEqual(fresh['total'], 1)
        self.assertEqual(self.desk.native_index.stats()['indexed_items'], 1)
        self.assertEqual(self.desk.store.sessions(), [])
        cold = Desk('never-executed', self.root / 'home', self.root / 'state')
        try:
            with patch.object(cold, 'catalog') as catalog, patch.object(cold, 'open') as opened:
                self.assertEqual(cold.recall('Corrected saved decision')['results'], fresh['results'])
                self.assertIsNone(cold.history_scanner.worker)
                catalog.assert_not_called()
                opened.assert_not_called()
            self.assertFalse(cold.native_index.needs_snapshot(meta))
        finally:
            cold.close()
            cold.store.db.close()

    def test_failed_read_mismatched_id_and_metadata_only_continue_without_losing_good_cache(self):
        rows = [self.native(identifier, 'retained phrase ' + identifier)
                for identifier in ('missing', 'wrong-id', 'metadata-only', 'good')]
        self.histories['missing'] = RuntimeError('Fixture unavailable')
        self.histories['wrong-id'] = snapshot('different-id', 'foreign phrase')
        self.histories['metadata-only'] = {'id': 'metadata-only', 'cwd': str(self.root)}
        result = self.index(rows)
        self.assertEqual((result['job']['status'], result['job']['seen'], result['job']['failed'],
                          result['job']['indexed']), ('completed', 4, 3, 1))
        self.assertEqual(result['coverage']['indexed_threads'], 1)
        self.assertEqual(self.recall(q='retained phrase')[1]['total'], 1)
        self.assertEqual(self.recall(q='foreign phrase')[1]['total'], 0)
        self.assertEqual(self.desk.store.sessions(), [])
        self.calls.clear()
        retried = self.index(rows)
        self.assertEqual((retried['job']['failed'], retried['job']['skipped']), (3, 1))
        self.assertNotIn(('thread/read', {'threadId': 'good', 'includeTurns': True}), self.calls)

    def test_cancel_single_worker_no_late_snapshot_and_explicit_restart(self):
        meta = self.native('blocked', 'cancelled phrase')
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def blocked_request(method, params):
            result = self.native_request(method, params)
            if method == 'thread/read':
                entered.set()
                if not release.wait(3):
                    raise RuntimeError('Fixture wait expired')
            return result

        self.catalog.request.side_effect = blocked_request
        self.pages = {None: {'data': [meta], 'nextCursor': None}}
        self.assertEqual(self.request('POST', '/api/history/index', {'limit': 1})[0], 200)
        self.assertTrue(entered.wait(1))
        worker = self.desk.history_scanner.worker
        status, second, _ = self.request('POST', '/api/history/index', {'limit': 20})
        self.assertEqual((status, second['limit'], second['seen']), (200, 1, 1))
        self.assertIs(worker, self.desk.history_scanner.worker)
        self.assertEqual(self.request('GET', '/api/history/index')[1]['job']['status'], 'running')
        self.assertEqual(self.recall(q='cancelled phrase')[1]['total'], 0)
        self.assertEqual(self.request('POST', '/api/history/index/cancel', {})[0], 200)
        release.set()
        cancelled = self.finish()
        self.assertEqual((cancelled['job']['status'], cancelled['job']['indexed']), ('cancelled', 0))
        self.assertEqual(cancelled['coverage']['indexed_threads'], 0)
        self.assertEqual(self.desk.store.sessions(), [])
        self.catalog.request.side_effect = self.native_request
        self.assertEqual(self.index([meta], 1)['job']['indexed'], 1)
        self.assertEqual(self.recall(q='cancelled phrase')[1]['total'], 1)

    def test_index_limits_validation_and_origin_do_not_start_worker(self):
        for invalid in (0, -1, 1001, True, False, '20', 1.0, None):
            with self.subTest(limit=invalid):
                status, result, _ = self.request('POST', '/api/history/index', {'limit': invalid})
                self.assertEqual(status, 400)
                self.assertIn('error', result)
        for payload in ([], None, '200'):
            self.assertEqual(self.request('POST', '/api/history/index', payload)[0], 400)
        self.assertEqual(self.request('POST', '/api/history/index', {},
                                     headers={'Origin': 'https://outside.example'})[0], 400)
        self.assertEqual(self.request('GET', '/api/history/index',
                                     headers={'Origin': 'https://outside.example'})[0], 400)
        self.assertEqual(self.request('POST', '/api/history/index/cancel', {})[0], 200)
        self.assertIsNone(self.desk.history_scanner.worker)
        self.catalog_factory.assert_not_called()
        rows = [self.native('limited-a'), self.native('limited-b')]
        self.pages = {None: {'data': rows, 'nextCursor': 'next'}}
        self.assertEqual(self.request('POST', '/api/history/index', {'limit': 1})[0], 200)
        result = self.finish()
        self.assertEqual((result['job']['seen'], result['job']['indexed'], result['job']['has_more']), (1, 1, True))
        self.assertEqual(self.calls[0], ('thread/list', {'limit': 1, 'modelProviders': [], 'sortKey': 'updated_at'}))
        self.assertNotIn(('thread/read', {'threadId': 'limited-b', 'includeTurns': True}), self.calls)

    def test_close_cancels_and_joins_scanner_before_native_runtime_close(self):
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)

        def blocked_listing(method, params):
            entered.set()
            release.wait(3)
            return self.native_request(method, params)

        self.catalog.request.side_effect = blocked_listing
        self.assertEqual(self.request('POST', '/api/history/index', {})[0], 200)
        self.assertTrue(entered.wait(1))
        closed = threading.Event()
        runtime = Mock(spec=['close'])
        runtime.close.side_effect = lambda: (self.assertFalse(self.desk.history_scanner.worker.is_alive()), closed.set())
        self.desk.runtimes['fixture'] = runtime
        closer = threading.Thread(target=self.desk.close, daemon=True)
        closer.start()
        self.assertTrue(self.desk.history_scanner.cancelled.wait(1))
        self.assertFalse(closed.is_set())
        release.set()
        closer.join(3)
        self.assertFalse(closer.is_alive())
        self.assertTrue(closed.is_set())
        runtime.close.assert_called_once()
        self.assertEqual(self.request('GET', '/api/history/index')[1]['job']['status'], 'cancelled')
        self.desk.runtimes.clear()


if __name__ == '__main__':
    unittest.main()
