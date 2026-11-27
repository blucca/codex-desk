"""Capability-protected lookup GET over the existing preparation snapshot."""
import json
from unittest.mock import patch
from urllib.parse import urlencode
import test_preparation_api as base
from codex_desk import server as desk_server
from codex_desk.drafts import save_draft


class PreparationFindApiTests(base.PreparationApiTests):
    def test_lookup_keeps_all_scoped_owners_but_returns_only_exact_matching_controls(self):
        save_draft(self.desk.store, self.session, 'Decisive Straße café🙂 retained instruction', 'plan', 0)
        other = self.desk.store.create(str(self.root / 'other'), 'default', identifier='other', name='Other owner')
        save_draft(self.desk.store, other, 'Different retained work', 'native', 0)
        before = list(self.desk.store.db.iterdump()); changes = self.desk.store.db.total_changes
        status, body, _ = self.request('/api/preparation?' + urlencode({'q': 'strasse café🙂', 'limit': 1}), self.token)
        self.assertEqual(status, 200)
        hit, = body['lookup']['results']
        self.assertEqual((hit['session_id'], hit['kind'], hit['revision']), (self.session, 'draft', 1))
        self.assertEqual({r['id'] for r in body['sessions']}, {self.session, other})
        self.assertIn('Straße café🙂', hit['snippet'])
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.desk.store.db.total_changes, changes)
        self.assertEqual(self.desk.runtimes, {})

    def test_lookup_capability_rejected_before_any_private_source_read(self):
        with patch.object(desk_server, 'lookup_snapshot', side_effect=AssertionError('Private lookup must not run')) as read:
            for token in (None, 'wrong', 'expired'):
                status, body, _ = self.request('/api/preparation?q=private', token)
                self.assertEqual(status, 403)
                self.assertNotIn('sessions', body)
            read.assert_not_called()

    def test_lookup_duplicate_unknown_or_malformed_options_are_rejected(self):
        queries = ('q=one&q=two', 'q=one&offset=0&offset=1', 'q=one&limit=-1',
                   'q=one&offset=+1', 'q=one&limit=51', 'q=one&limit=0',
                   'q=x', 'q=' + ('a' * 201), 'q=one&bogus=x', 'q=one&limit',
                   'q=one&archived=maybe', 'q=one&cwd=', 'q=one&cwd=a&cwd=b')
        for query in queries:
            with self.subTest(query=query):
                status, body, _ = self.request('/api/preparation?' + query, self.token)
                self.assertEqual(status, 400)
                self.assertIn('error', body)

    def test_post_cannot_invoke_lookup_or_admit_a_native_task(self):
        import http.client
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            with patch.object(desk_server, 'lookup_snapshot', side_effect=AssertionError('POST must not read lookup')) as read:
                connection.request('POST', '/api/preparation?q=private', body='{}', headers={'X-Codex-Desk-Access': self.token, 'Content-Type': 'application/json'})
                response = connection.getresponse(); self.assertEqual(response.status, 404); response.read()
                read.assert_not_called()
        finally:
            connection.close()
        self.assertEqual(self.desk.runtimes, {})
