"""Private Prepared work GET uses the real read-only SQLite snapshot."""
import http.client
import json
import os
from pathlib import Path
import secrets
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import quote

from codex_desk import server as desk_server
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup, followup_snapshot


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PreparationApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-preparation-api-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk = desk_server.Desk('not-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.session = self.desk.store.create(str(self.root), 'default', identifier='local-task', name='Local prepared task')
        self.desk.store.update(self.session, status='failed')
        self.token = secrets.token_urlsafe(32)
        self.server = desk_server.LoopbackHTTPServer(('127.0.0.1', 0), desk_server.handler(self.desk, access_token=self.token))
        self.worker = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown(); self.server.server_close(); self.worker.join(3)

    def request(self, path, token=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            headers = {'X-Codex-Desk-Access': token} if token is not None else {}
            connection.request('GET', path, headers=headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read()), dict(response.getheaders())
        finally:
            connection.close()

    def schema(self):
        return list(self.desk.store.db.execute('SELECT name,sql FROM sqlite_master ORDER BY name'))

    def test_raw_requests_reject_before_snapshot_and_header_owner_reads(self):
        saved = save_draft(self.desk.store, self.session, 'Local private Plan preparation', 'plan', 0)
        with patch.object(desk_server, 'preparation_snapshot', side_effect=AssertionError('Private snapshot must not be reached')) as snapshot:
            for token in (None, 'wrong-capability', 'old-launch-capability'):
                status, body, headers = self.request('/api/preparation?archived=false', token)
                self.assertEqual(status, 403)
                self.assertNotIn('Local private Plan preparation', json.dumps(body))
                self.assertNotIn(self.token, json.dumps(body))
                self.assertNotIn('Set-Cookie', headers)
            snapshot.assert_not_called()
        status, body, _ = self.request('/api/preparation?archived=false', self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body['sessions'][0]['draft'], saved)
        self.assertEqual(body['sessions'][0]['id'], self.session)
        self.assertEqual(self.desk.runtimes, {})

    def test_invalid_and_duplicate_query_options_are400_without_private_snapshot(self):
        with patch.object(desk_server, 'preparation_snapshot', side_effect=AssertionError('Invalid query must not read preparation')) as snapshot:
            for query in ('archived=maybe', 'archived=', 'archived=true&archived=false',
                          'cwd=%2Fa&cwd=%2Fb', 'offset=0', 'x=1&x=2&x=3&x=4&x=5'):
                with self.subTest(query=query):
                    status, body, _ = self.request('/api/preparation?' + query, self.token)
                    self.assertEqual(status, 400)
                    self.assertIn('error', body)
            snapshot.assert_not_called()
        for query in ('cwd=', 'cwd=%20'):
            status, body, _ = self.request('/api/preparation?' + query, self.token)
            self.assertEqual(status, 400)
            self.assertIn('error', body)

    def test_empty_and_populated_get_leave_schema_and_sqlite_changes_untouched(self):
        before_schema, before_changes = self.schema(), self.desk.store.db.total_changes
        sql = []
        self.desk.store.db.set_trace_callback(sql.append)
        try:
            status, body, _ = self.request('/api/preparation', self.token)
        finally:
            self.desk.store.db.set_trace_callback(None)
        self.assertEqual((status, body), (200, {'sessions': []}))
        self.assertEqual(self.schema(), before_schema)
        self.assertEqual(self.desk.store.db.total_changes, before_changes)
        self.assertFalse(any(s.lstrip().upper().startswith(('CREATE ', 'ALTER ', 'INSERT ', 'UPDATE ', 'DELETE ')) for s in sql), sql)

        saved = save_draft(self.desk.store, self.session, 'Exact retained Plan', 'plan', 0)
        add_followup(self.desk.store, self.session, 'First remaining check', 'native')
        add_followup(self.desk.store, self.session, 'Second remaining check', 'plan')
        queue = followup_snapshot(self.desk.store, self.session)
        before_schema, before_changes = self.schema(), self.desk.store.db.total_changes
        before_dump = list(self.desk.store.db.iterdump())
        status, body, _ = self.request('/api/preparation?archived=false', self.token)
        self.assertEqual(status, 200)
        self.assertEqual(body['sessions'][0]['draft'], saved)
        self.assertEqual(body['sessions'][0]['followups'], queue)
        self.assertEqual(self.schema(), before_schema)
        self.assertEqual(self.desk.store.db.total_changes, before_changes)
        self.assertEqual(list(self.desk.store.db.iterdump()), before_dump)
        self.assertEqual(self.desk.runtimes, {})

    def test_exact_removed_project_and_archive_scopes_use_local_saved_state(self):
        removed = self.root / 'removed'; removed.mkdir()
        other = self.desk.store.create(str(removed), 'default', identifier='removed-task', name='Removed project task')
        self.desk.store.update(other, status='saved')
        saved = save_draft(self.desk.store, other, 'Removed folder still has local preparation', 'native', 0)
        removed.rmdir()
        status, body, _ = self.request('/api/preparation?cwd=' + quote(str(removed), safe=''), self.token)
        self.assertEqual(status, 200)
        self.assertEqual([row['id'] for row in body['sessions']], [other])
        self.assertEqual(body['sessions'][0]['draft'], saved)
        self.assertFalse(removed.exists())
        self.desk.store.archive(other, True)
        status, body, _ = self.request('/api/preparation?archived=false', self.token)
        self.assertEqual((status, body), (200, {'sessions': []}))
        status, body, _ = self.request('/api/preparation?archived=1&cwd=' + quote(str(removed), safe=''), self.token)
        self.assertEqual(status, 200)
        self.assertTrue(body['sessions'][0]['archived'])
        self.assertEqual(body['sessions'][0]['followups'], {'entries': [], 'reservation': None})
        self.assertEqual(self.desk.runtimes, {})


if __name__ == '__main__':
    unittest.main()
