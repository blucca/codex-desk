"""Explicit history indexing and cold literal recall through real loopback HTTP."""
import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

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

if __name__ == '__main__':
    unittest.main()
