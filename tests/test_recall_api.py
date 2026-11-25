"""HTTP recall searches saved SQLite text without starting a native backend."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class RecallApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-recall-api-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.session = self.desk.store.create(str(self.root / 'project'), 'default', name='Project return')
        self.desk.store.update(self.session, thread_id='native-kept', status='saved')
        self.desk.store.recall_snapshot(self.session, {'id': 'native-kept', 'turns': [
            {'id': 'verification-turn', 'status': 'completed', 'items': [
                {'id': 'decision-item', 'type': 'agentMessage', 'text': 'Literal 项目验证 + résumé [accepted].'}]}]})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def get(self, query=None, *, raw=None, headers=None):
        path = '/api/recall' + ('?' + (raw if raw is not None else urlencode(query)) if raw is not None or query is not None else '')
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            conn.request('GET', path, headers=headers or {})
            response = conn.getresponse()
            return response.status, json.loads(response.read()), response.getheader('Cache-Control')
        finally:
            conn.close()

    def test_unicode_literal_api_preserves_exact_navigation_and_no_native_calls(self):
        before = list(self.desk.store.db.iterdump())
        with patch.object(self.desk, 'catalog') as catalog, patch.object(self.desk, 'open') as opened:
            status, result, cache = self.get({'q': '  项目验证 + RÉSUMÉ [accepted]  ',
                'cwd': str(self.root / 'project' / '..' / 'project'), 'limit': 30})
            catalog.assert_not_called()
            opened.assert_not_called()
        self.assertEqual((status, cache, result['total']), (200, 'no-store', 1))
        self.assertEqual(result['query'], '项目验证 + RÉSUMÉ [accepted]')
        hit = result['results'][0]
        self.assertEqual((hit['session_id'], hit['turn_id'], hit['item_id']),
                         (self.session, 'verification-turn', 'decision-item'))
        self.assertIn('not whole native history', result['coverage']['text'])
        self.assertEqual(result['coverage']['activity_items'], 1)
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.desk.runtimes, {})

    def test_global_and_exact_project_archive_options(self):
        self.assertEqual(self.get({'q': 'accepted'})[1]['total'], 1)
        self.assertEqual(self.get({'q': 'accepted', 'cwd': str(self.root / 'other')})[1]['total'], 0)
        self.desk.store.archive(self.session, True)
        self.assertEqual(self.get({'q': 'accepted'})[1]['total'], 0)
        status, result, _ = self.get({'q': 'accepted', 'archived': 'true'})
        self.assertEqual(status, 200)
        self.assertTrue(result['results'][0]['archived'])

    def test_invalid_and_repeated_options_return_400_without_open(self):
        queries = ({}, {'q': 'x'}, {'q': 'x' * 201}, {'q': 'valid', 'limit': '0'},
                   {'q': 'valid', 'limit': '51'}, {'q': 'valid', 'limit': 'no'},
                   {'q': 'valid', 'cwd': ''}, {'q': 'valid', 'archived': 'yes'},
                   {'q': 'valid', 'unknown': 'x'})
        with patch.object(self.desk, 'catalog') as catalog, patch.object(self.desk, 'open') as opened:
            for query in queries:
                with self.subTest(query=query):
                    self.assertEqual(self.get(query)[0], 400)
            self.assertEqual(self.get(raw='q=valid&q=other')[0], 400)
            catalog.assert_not_called()
            opened.assert_not_called()

    def test_origin_restriction_applies_to_saved_text(self):
        self.assertEqual(self.get({'q': 'accepted'}, headers={'Origin': 'https://outside.example'})[0], 400)


if __name__ == '__main__':
    unittest.main()
