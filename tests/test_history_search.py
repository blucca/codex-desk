"""Native title-search HTTP forwarding with metadata-only catalog fixtures."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
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
        return self.request('GET', path)

    def request(self, method, path, value=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        headers = {'Content-Type': 'application/json'} if value is not None else {}
        try:
            connection.request(method, path, json.dumps(value) if value is not None else None, headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def scoped_metadata(self, exists=True):
        return {**self.metadata,
            'data': [dict(row, cwdExists=exists) for row in self.metadata['data']],
            'projectScope': {'cwd': str(self.project.resolve()), 'cwdExists': exists}}

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
        self.assertEqual(self.get()[1], {**self.metadata, 'data': [dict(row, cwdExists=False) for row in self.metadata['data']]})
        self.catalog.request.assert_called_with('thread/list', self.base_options())

    def test_title_search_preserves_canonical_project_and_all_providers(self):
        status, body = self.get({'cwd': str(self.project / '..' / self.project.name),
                                 'search': '  verification  '})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.scoped_metadata())
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
                self.assertEqual(body, {**self.metadata, 'data': [dict(row, cwdExists=True) for row in self.metadata['data']]})
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
        self.assertEqual(body, {**self.metadata, 'data': [dict(row, cwdExists=True) for row in self.metadata['data']]})
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'searchTerm': 'saved title', 'cursor': 'older',
        })

    def test_empty_search_preserves_project_and_existing_pagination(self):
        status, body = self.get({'cwd': str(self.project), 'search': '', 'cursor': 'older'})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.scoped_metadata())
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project.resolve()), 'cursor': 'older',
        })

    def test_invalid_project_returns_existing_error_before_catalog_request(self):
        ordinary_file = self.root / 'ordinary-file'
        ordinary_file.write_text('fixture')
        for cwd in ('', ' \t\n ', str(ordinary_file), str(ordinary_file / 'child')):
            with self.subTest(cwd=cwd):
                status, body = self.get({'cwd': cwd, 'search': 'saved title'})
                self.assertEqual(status, 400)
                if cwd != str(ordinary_file / 'child'):
                    self.assertEqual(body, {'error': 'Select a project directory'})
        self.catalog.request.assert_not_called()

    def test_removed_project_scope_keeps_exact_title_cursor_native_rows_and_read(self):
        self.project.rmdir()
        original = json.loads(json.dumps(self.metadata))
        status, body = self.get({'cwd': str(self.project / '..' / self.project.name),
                                'search': '  项目验证 + résumé  ', 'cursor': 'older+页 /='})
        self.assertEqual(status, 200)
        self.assertEqual(body, self.scoped_metadata(False))
        self.assertEqual(self.metadata, original)
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project),
            'searchTerm': '项目验证 + résumé', 'cursor': 'older+页 /=',
        })
        thread = {**original['data'][0], 'turns': [{'id': 'turn', 'items': [
            {'id': 'answer', 'type': 'agentMessage', 'text': 'Original exact decision.'}]}]}
        self.catalog.request.return_value = {'thread': thread}
        status, read = self.request('GET', '/api/native/thread?id=saved-thread')
        self.assertEqual((status, read), (200, thread))
        self.catalog.request.assert_called_with('thread/read', {
            'threadId': 'saved-thread', 'includeTurns': True})
        self.assertEqual(self.desk.store.sessions(), [])
        self.assertEqual(self.desk.runtimes, {})
        self.assertFalse(self.project.exists())

    def test_missing_project_empty_page_reports_read_only_scope_without_global_fallback(self):
        self.project.rmdir()
        self.catalog.request.return_value = {'data': [], 'nextCursor': None}
        status, body = self.get({'cwd': str(self.project), 'search': 'unmatched'})
        self.assertEqual((status, body), (200, {'data': [], 'nextCursor': None,
            'projectScope': {'cwd': str(self.project), 'cwdExists': False}}))
        self.catalog.request.assert_called_once_with('thread/list', {
            **self.base_options(), 'cwd': str(self.project), 'searchTerm': 'unmatched'})
        self.assertFalse(self.project.exists())

    def test_missing_scope_does_not_relax_create_import_handoff_or_bound_open(self):
        self.project.rmdir()
        thread = self.metadata['data'][0]
        self.catalog.request.return_value = {'thread': thread}
        for path, value in (
            ('/api/sessions', {'cwd': str(self.project), 'profile': 'default'}),
            ('/api/handoff/start', {'cwd': str(self.project), 'profile': 'default',
                                   'text': 'Original evidence', 'goal': 'Next task'}),
            ('/api/import', {'thread': thread['id'], 'profile': 'default'}),
        ):
            with self.subTest(path=path):
                status, body = self.request('POST', path, value)
                self.assertEqual(status, 400)
                self.assertIn('error', body)
                self.assertEqual(self.desk.store.sessions(), [])
                self.assertEqual(self.desk.runtimes, {})
        self.catalog.request.assert_called_once_with('thread/read', {
            'threadId': 'saved-thread', 'includeTurns': True})
        identifier = self.desk.store.create(str(self.project), 'default', identifier='bound')
        self.desk.store.update(identifier, thread_id='saved-thread', status='saved', thread_saved=1)
        self.desk.binary = sys.executable
        with patch('codex_desk.runtime.subprocess.Popen', wraps=subprocess.Popen) as start:
            status, body = self.request('POST', '/api/open', {'session': identifier})
            self.assertEqual(status, 400)
            self.assertIn(str(self.project), body['error'])
            self.assertEqual(start.call_args.kwargs['cwd'], str(self.project))
        self.assertEqual(self.desk.runtimes, {})
        self.assertFalse(self.project.exists())

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
