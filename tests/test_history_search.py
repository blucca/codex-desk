"""Native title-search HTTP forwarding with metadata-only catalog fixtures."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class HistorySearchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-title-search-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.desk = Desk('never-executed', self.root / 'native-home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.metadata = {
            'data': [{'id': 'saved-thread', 'cwd': str(self.project),
                      'modelProvider': 'fixture-provider', 'name': '项目验证 + résumé'}],
            'nextCursor': 'next-page+页',
        }
        self.catalog = Mock(spec=['request'])
        self.catalog.request.return_value = self.metadata
        patcher = patch.object(self.desk, 'catalog', return_value=self.catalog)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': 0.01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(timeout=5)

    def get(self, query=None):
        path = '/api/native' + ('?' + urlencode(query) if query is not None else '')
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', path)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    @staticmethod
    def base_options():
        return {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at'}

    def test_recent_preview_marks_missing_folders_without_mutating_native_metadata(self):
        status, body = self.get({'recent': '1'})
        self.assertEqual(status, 200)
        self.assertTrue(body['data'][0]['cwdExists'])
        self.assertNotIn('cwdExists', self.metadata['data'][0])
        self.project.rmdir()
        status, body = self.get({'recent': '1'})
        self.assertFalse(body['data'][0]['cwdExists'])
        self.assertEqual(self.get()[1], self.metadata)
        self.catalog.request.assert_called_with('thread/list', self.base_options())

    def test_title_search_preserves_canonical_project_and_all_providers(self):
        status, body = self.get({'cwd': str(self.project / '..' / self.project.name),
                                 'search': '  verification  '})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.metadata)
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project.resolve()),
            'searchTerm': 'verification',
        })
        self.assertEqual(self.desk.store.sessions(), [])
        self.assertEqual(self.desk.runtimes, {})

    def test_absent_empty_and_whitespace_search_keep_unfiltered_request(self):
        for search in (None, '', ' \t\n ', '\u3000'):
            with self.subTest(search=search):
                self.catalog.request.reset_mock()
                query = None if search is None else {'search': search}
                status, body = self.get(query)
                self.assertEqual(status, 200)
                self.assertEqual(body, self.metadata)
                self.catalog.request.assert_called_once_with('thread/list', self.base_options())

    def test_unicode_title_and_opaque_cursor_are_forwarded_with_project(self):
        status, body = self.get({'cwd': str(self.project),
                                 'search': '  项目验证 + résumé  ',
                                 'cursor': 'opaque+页 /=next'})
        self.assertEqual(status, 200)
        self.assertEqual(body['nextCursor'], self.metadata['nextCursor'])
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project.resolve()),
            'searchTerm': '项目验证 + résumé', 'cursor': 'opaque+页 /=next',
        })

    def test_global_title_search_does_not_add_project_filter(self):
        status, body = self.get({'search': ' saved title ', 'cursor': 'older'})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.metadata)
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'searchTerm': 'saved title', 'cursor': 'older',
        })

    def test_empty_search_preserves_project_and_existing_pagination(self):
        status, body = self.get({'cwd': str(self.project), 'search': '', 'cursor': 'older'})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.metadata)
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project.resolve()), 'cursor': 'older',
        })

    def test_invalid_project_returns_existing_error_before_catalog_request(self):
        ordinary_file = self.root / 'ordinary-file'
        ordinary_file.write_text('fixture')
        for cwd in ('', str(ordinary_file)):
            with self.subTest(cwd=cwd):
                status, body = self.get({'cwd': cwd, 'search': 'saved title'})
                self.assertEqual(status, 400)
                self.assertEqual(body, {'error': 'Select a project directory'})
        self.catalog.request.assert_not_called()

    def test_native_catalog_error_keeps_existing_http_error_response(self):
        self.catalog.request.side_effect = RuntimeError('Fixture native catalog unavailable')
        status, body = self.get({'search': 'saved title'})
        self.assertEqual(status, 400)
        self.assertEqual(body, {'error': 'Fixture native catalog unavailable'})
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'searchTerm': 'saved title',
        })
        self.assertEqual(self.desk.store.sessions(), [])
        self.assertEqual(self.desk.runtimes, {})


if __name__ == '__main__':
    unittest.main()
