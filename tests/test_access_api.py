"""Per-launch local access: private routes reject before state/native changes."""
import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import secrets
import sys
import tempfile
import threading
import tomllib
import unittest
from unittest.mock import call, patch
from urllib.parse import urlsplit

from codex_desk import server as desk_server
from codex_desk.drafts import save_draft
from codex_desk.runtime import save_profile


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class PrivateAccessTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-access-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.desk = desk_server.Desk('not-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.session = self.desk.store.create(str(self.root), 'default')
        self.desk.store.update(self.session, status='completed')
        self.draft = save_draft(self.desk.store, self.session, 'Private saved preparation', 'plan', 0)
        save_profile(self.desk.home, 'review', 'https://original.invalid/v1', 'model', 'synthetic-key')
        self.profile = self.desk.home / 'review.config.toml'
        self.token = secrets.token_urlsafe(32)
        self.server = desk_server.LoopbackHTTPServer(('127.0.0.1', 0),
            desk_server.handler(self.desk, access_token=self.token))
        self.worker = threading.Thread(target=self.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def request(self, method, path, value=None, token=None, raw=None, **headers):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        if token is not None:
            headers['X-Codex-Desk-Access'] = token
        if value is not None:
            headers.setdefault('Content-Type', 'application/json')
        try:
            connection.request(method, path, json.dumps(value) if value is not None else raw, headers)
            response = connection.getresponse()
            body = response.read().decode()
            return response.status, body, dict(response.getheaders())
        finally:
            connection.close()

    def assert_denied(self, response):
        status, body, headers = response
        self.assertEqual(status, 403)
        self.assertIn('current printed Codex Desk URL', json.loads(body)['error'])
        for secret in (self.token, 'Private saved preparation', 'synthetic-key'):
            self.assertNotIn(secret, body)
        self.assertNotIn('Set-Cookie', headers)

    def test_missing_wrong_and_stale_capabilities_block_before_private_reads(self):
        for token in (None, 'wrong-token', 'previous-launch-token', 'wrong-\xe9'):
            for path in ('/api/state', '/api/draft?session=' + self.session):
                with self.subTest(token_type='missing' if token is None else 'incorrect', path=path), \
                        patch.object(self.desk.store, 'sessions', side_effect=AssertionError('private read')):
                    self.assert_denied(self.request('GET', path, token=token))

    def test_authorized_owner_can_restore_save_and_edit_with_original_key_retained(self):
        status, body, _ = self.request('GET', '/api/state', token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['sessions'][0]['id'], self.session)
        self.assertNotIn('synthetic-key', body)
        status, body, _ = self.request('GET', '/api/draft?session=' + self.session, token=self.token)
        self.assertEqual((status, json.loads(body)), (200, self.draft))
        saved = {'session': self.session, 'text': 'Owner changed preparation', 'mode': 'native', 'revision': 1}
        status, body, _ = self.request('POST', '/api/draft', saved, token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)['revision'], 2)
        status, body, _ = self.request('POST', '/api/profiles/update', {
            'id': 'sidecar:review', 'endpoint': 'https://owner-updated.invalid/v1', 'model': 'next-model'}, token=self.token)
        self.assertEqual((status, json.loads(body)), (200, {'id': 'sidecar:review', 'restartRequired': False}))
        provider = tomllib.loads(self.profile.read_text())['model_providers']['desk_provider']
        self.assertEqual(provider['base_url'], 'https://owner-updated.invalid/v1')
        self.assertEqual(provider['experimental_bearer_token'], 'synthetic-key')
        self.assertEqual(self.desk.runtimes, {})

    def test_unauthorized_mutations_reject_before_body_or_native_admission(self):
        before = self.profile.read_bytes()
        with patch.object(self.desk, 'create') as create, \
                patch.object(self.desk, 'open') as open_session, \
                patch.object(self.desk, 'turn') as turn:
            for path in ('/api/sessions', '/api/open', '/api/turn', '/api/profiles/update', '/api/draft'):
                # Bad/missing JSON headers/body would fail differently if read.
                self.assert_denied(self.request('POST', path, raw='not-json'))
            create.assert_not_called()
            open_session.assert_not_called()
            turn.assert_not_called()
        self.assertEqual(self.profile.read_bytes(), before)
        self.assertEqual(self.desk.runtimes, {})
        self.assert_denied(self.request('POST', '/api/profiles/update', {
            'id': 'sidecar:review', 'endpoint': 'https://other-account.invalid/v1', 'model': 'model'}))
        self.assertEqual(self.profile.read_bytes(), before)
        status, body, _ = self.request('GET', '/api/draft?session=' + self.session, token=self.token)
        self.assertEqual((status, json.loads(body)), (200, self.draft))

    def test_static_bootstrap_discloses_no_capability_and_local_gates_remain(self):
        for path in ('/', '/app.js'):
            status, body, headers = self.request('GET', path)
            self.assertEqual(status, 200)
            self.assertNotIn(self.token, body)
            self.assertNotIn('Set-Cookie', headers)
        for headers in ({'Origin': 'https://outside.invalid'},
                        {'Host': 'outside.invalid:' + str(self.server.server_port)}):
            self.assertEqual(self.request('GET', '/api/state', token=self.token, **headers)[0], 400)
        self.assertEqual(self.request('POST', '/api/draft', token=self.token,
            raw='not-json', **{'Content-Type': 'text/plain'})[0], 400)

    def test_restart_rejects_previous_token_and_fresh_token_restores_saved_draft(self):
        previous_token, port = self.token, self.server.server_port
        self.stop_server()
        self.token = secrets.token_urlsafe(32)
        self.server = desk_server.LoopbackHTTPServer(('127.0.0.1', port),
            desk_server.handler(self.desk, access_token=self.token))
        self.worker = threading.Thread(target=self.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.assert_denied(self.request('GET', '/api/draft?session=' + self.session, token=previous_token))
        status, body, _ = self.request('GET', '/api/draft?session=' + self.session, token=self.token)
        self.assertEqual((status, json.loads(body)), (200, self.draft))


class LaunchAccessTests(unittest.TestCase):
    def test_main_always_injects_a_fresh_capability_and_opens_its_fragment_url(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-launch-access-') as folder:
            servers, desks = [], []
            server_type, desk_type = desk_server.LoopbackHTTPServer, desk_server.Desk

            def bind(*args):
                server = server_type(*args)
                server.serve_forever = lambda: None
                servers.append(server)
                return server

            def initialize(*args):
                desk = desk_type(*args)
                desks.append(desk)
                return desk

            with patch.object(sys, 'argv', ['codex-desk', '--port', '0', '--codex-home', str(Path(folder) / 'home'),
                    '--state-dir', str(Path(folder) / 'state')]), \
                    patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                    patch.object(desk_server, 'LoopbackHTTPServer', side_effect=bind), \
                    patch.object(desk_server, 'Desk', side_effect=initialize), \
                    patch.object(desk_server, 'handler', wraps=desk_server.handler) as built, \
                    patch.object(desk_server.secrets, 'token_urlsafe',
                        side_effect=['controlled-first-launch', 'controlled-next-launch']) as generated, \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                desk_server.main()
                desk_server.main()
            self.assertEqual(generated.call_args_list, [call(32), call(32)])
            tokens = ('controlled-first-launch', 'controlled-next-launch')
            lines = output.getvalue().splitlines()
            for index, token in enumerate(tokens):
                self.assertEqual(built.call_args_list[index], call(desks[index], access_token=token))
                address = f'http://127.0.0.1:{servers[index].server_port}#access={token}'
                self.assertEqual(lines[index], 'Codex Desk: ' + address)
                self.assertEqual(browser.call_args_list[index], call(address))
                self.assertEqual(urlsplit(address).fragment, 'access=' + token)
                self.assertEqual(servers[index].socket.fileno(), -1)


if __name__ == '__main__':
    unittest.main()
