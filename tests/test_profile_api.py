"""Local profile edits retain identity and report loaded native settings."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import tomllib
import unittest
from unittest.mock import Mock
from codex_desk.runtime import save_profile
from codex_desk.server import Desk, ThreadingHTTPServer, handler

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class ProfileApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-profile-api-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        save_profile(self.desk.home, 'default', 'https://example.invalid/v1', 'old-model', 'private-fixture-key')
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def update(self, **fields):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', '/api/profiles/update', json.dumps({
                'id': 'sidecar:default', 'endpoint': 'https://example.invalid/updated/v1',
                'model': 'updated-model', **fields}), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def loaded(self, profile):
        identifier = self.desk.store.create(str(self.root), profile)
        self.desk.store.update(identifier, thread_id='saved-'+identifier, status='ready', thread_saved=1)
        runtime = Mock()
        runtime.process.poll.return_value = None
        self.desk.runtimes[identifier] = runtime
        return identifier, runtime

    def test_blank_key_edit_preserves_bindings_and_only_matches_sidecar_namespace(self):
        official, official_runtime = self.loaded('default')
        status, result = self.update()
        self.assertEqual((status, result), (200, {'id':'sidecar:default', 'restartRequired':False}))
        row_before = self.desk.store.get(official)
        retained, retained_runtime = self.loaded('sidecar:default')
        retained_before = self.desk.store.get(retained)
        status, result = self.update(model='next-model')
        self.assertEqual((status, result), (200, {'id':'sidecar:default', 'restartRequired':True}))
        config = tomllib.loads((self.desk.home / 'default.config.toml').read_text())
        self.assertEqual(config['model'], 'next-model')
        self.assertEqual(config['model_providers']['desk_provider']['experimental_bearer_token'], 'private-fixture-key')
        self.assertEqual(self.desk.store.get(official), row_before)
        self.assertEqual(self.desk.store.get(retained), retained_before)
        for runtime in (official_runtime, retained_runtime):
            runtime.attach.assert_not_called()
            runtime.request.assert_not_called()
            runtime.close.assert_not_called()
        self.assertNotIn('private-fixture-key', json.dumps(result))

    def test_failed_edit_is_inline_compatible_and_never_writes_or_reveals_key(self):
        path = self.desk.home / 'default.config.toml'
        before = path.read_bytes()
        status, result = self.update(endpoint='not-an-endpoint', key='rotated-private-fixture')
        self.assertEqual(status, 400)
        self.assertIn('error', result)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn('rotated-private-fixture', json.dumps(result))
        status, result = self.update(id='default', key='rotated-private-fixture')
        self.assertEqual(status, 400)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(self.desk.store.sessions(), [])


if __name__ == '__main__':
    unittest.main()
