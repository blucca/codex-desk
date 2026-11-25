import http.client
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from codex_desk import __version__
from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class RuntimeStartupTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.home = self.path / 'native-home'
        self.home.mkdir()
        self.project = self.path / 'project'
        self.project.mkdir()
        (self.home / 'saved-project').write_text(str(self.project))
        self.native = self.path / 'native-fixture'
        self.native.write_text(f'#!{sys.executable}\n' + '''
import json, os, subprocess, sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
if (home / 'spawn-child').exists():
    (home / 'spawn-child').unlink()
    child_code = ''' + repr('''
import json, sys, time
from pathlib import Path
home = Path(sys.argv[1])
deadline = time.monotonic() + 6
while not (home / 'release-child').exists() and time.monotonic() < deadline:
    time.sleep(0.02)
print(json.dumps({'method': 'turn/completed', 'params': {'turn': {'id': 'retired-turn', 'status': 'completed'}}}), flush=True)
''') + '''
    subprocess.Popen([sys.executable, '-c', child_code, str(home)])
for line in sys.stdin:
    message = json.loads(line)
    with (home / 'fixture-requests.jsonl').open('a') as log:
        log.write(json.dumps(message) + '\\n')
    method = message.get('method')
    if method == 'initialize':
        if (home / 'reject-initialize').exists():
            (home / 'reject-initialize').unlink()
            reply = {'error': {'code': -32000, 'message': 'fixture initialization unavailable'}}
        else:
            reply = {'result': {}}
    elif method == 'thread/resume':
        if (home / 'missing-rollout').exists():
            reply = {'error': {'code': -32000, 'message': 'no rollout found'}}
        else:
            reply = {'result': {'thread': {'id': message['params']['threadId'], 'turns': []},
                                'model': 'saved-model', 'modelProvider': 'saved-provider'}}
    elif method == 'thread/read':
        reply = {'result': {'thread': {'id': message['params']['threadId'],
            'cwd': (home / 'saved-project').read_text(), 'name': 'Existing verification',
            'model': 'saved-model', 'modelProvider': 'saved-provider', 'turns': [
                {'items': [{'type': 'userMessage', 'content': [{'type': 'text', 'text': 'Verify this project'}]},
                           {'type': 'agentMessage', 'text': 'Verification passed'}]}]}}}
    elif method == 'thread/start':
        reply = {'result': {'thread': {'id': 'replacement-blank', 'turns': []}}}
    else:
        continue
    print(json.dumps({'id': message['id'], **reply}), flush=True)
''')
        self.native.chmod(0o700)
        self.desk = Desk(str(self.native), self.home, self.path / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.children = []
        popen = subprocess.Popen

        def spawn(*args, **kwargs):
            child = popen(*args, **kwargs)
            self.children.append(child)
            return child

        patcher = patch('codex_desk.runtime.subprocess.Popen', side_effect=spawn)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for child in self.children:
            if child.poll() is None:
                child.kill()
                child.wait(timeout=5)

    def test_native_initialize_reports_canonical_package_version(self):
        identifier = self.desk.store.create(str(self.project), 'default')
        self.desk.store.update(identifier, thread_id='native-original', status='completed')
        self.assertEqual(self.desk.open(identifier)['thread']['id'], 'native-original')
        requests = [json.loads(line) for line in
                    (self.home / 'fixture-requests.jsonl').read_text().splitlines()]
        initialize = [r for r in requests if r['method'] == 'initialize']
        self.assertEqual(len(initialize), 1)
        self.assertEqual(initialize[0]['params']['clientInfo'], {
            'name': 'codex_desk', 'title': 'Codex Desk', 'version': __version__})
        self.assertEqual(initialize[0]['params']['capabilities'], {'experimentalApi': True})
        self.assertEqual([r['method'] for r in requests],
                         ['initialize', 'initialized', 'thread/resume'])

    def test_rejected_initialize_reaps_child_and_reopens_same_saved_session(self):
        config = self.home / 'saved.config.toml'
        config.write_text('model="saved-model"\nmodel_provider="saved-provider"\n'
                          '[model_providers.saved-provider]\nname="Saved provider"\n'
                          'base_url="https://example.com/v1"\nexperimental_bearer_token="fixture-key"\n')
        original_config = config.read_bytes()
        identifier = self.desk.store.create(str(self.project), 'sidecar:saved', name='Saved task')
        self.desk.store.update(identifier, thread_id='native-original', status='completed',
                               model='saved-model', provider='saved-provider', name_pending=0,
                               usage='{"total":{"inputTokens":42}}')
        self.desk.store.event(identifier, {'method': 'turn/started', 'params': {'turn': {'id': 'saved-turn'}}})
        original = self.desk.store.get(identifier)
        original_events = self.desk.store.events(identifier)
        (self.home / 'reject-initialize').touch()

        with self.assertRaisesRegex(RuntimeError, 'fixture initialization unavailable'):
            self.desk.open(identifier)

        self.assertIsNotNone(self.children[0].poll(), 'Rejected native process must be reaped')
        self.assertTrue(all(stream.closed for stream in (
            self.children[0].stdin, self.children[0].stdout, self.children[0].stderr)))
        self.assertNotIn(identifier, self.desk.runtimes)
        failed = self.desk.store.get(identifier)
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(failed['error'], 'Native session could not open')

        opened = self.desk.open(identifier)
        self.assertEqual(opened['thread']['id'], 'native-original')
        recovered = self.desk.store.get(identifier)
        self.assertEqual(recovered['status'], 'ready')
        self.assertIsNone(recovered['error'])
        for field in ('id', 'thread_id', 'cwd', 'profile', 'name', 'created', 'usage'):
            self.assertEqual(recovered[field], original[field])
        self.assertEqual(self.desk.store.events(identifier), original_events)
        self.assertEqual(config.read_bytes(), original_config)
        requests = [json.loads(line) for line in (self.home / 'fixture-requests.jsonl').read_text().splitlines()]
        resumes = [r for r in requests if r['method'] == 'thread/resume']
        self.assertEqual(len(resumes), 1)
        self.assertEqual(resumes[0]['params']['threadId'], 'native-original')
        self.assertEqual(resumes[0]['params']['config']['model_provider'], 'saved-provider')
        self.assertNotIn('thread/start', [r['method'] for r in requests])

    def test_missing_binary_marks_saved_session_failed(self):
        identifier = self.desk.store.create(str(self.project), 'default')
        self.desk.store.update(identifier, thread_id='native-original', status='completed')
        self.desk.binary = str(self.path / 'missing-native')
        with self.assertRaises(FileNotFoundError):
            self.desk.open(identifier)
        self.assertEqual(self.desk.store.get(identifier)['status'], 'failed')
        self.assertEqual(self.desk.store.get(identifier)['thread_id'], 'native-original')
        self.assertEqual(self.desk.runtimes, {})

    def test_missing_imported_history_keeps_binding_and_actionable_error_until_restored(self):
        config = self.home / 'config.toml'
        config.write_text('# Existing configuration must stay intact\nmodel="saved-model"\n')
        config_before = config.read_bytes()
        identifier = self.desk.import_thread('native-original', 'default')['id']
        original = self.desk.store.get(identifier)
        self.assertEqual(self.desk.store.events(identifier), [])
        missing = self.home / 'missing-rollout'
        missing.touch()

        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        worker = threading.Thread(target=server.serve_forever,
                                  kwargs={'poll_interval': 0.01}, daemon=True)
        worker.start()
        connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
        try:
            connection.request('POST', '/api/open', json.dumps({'session': identifier}),
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            body = json.loads(response.read())
            self.assertEqual(response.status, 400, body)
            self.assertIn('original --codex-home', body['error'])
            self.assertIn('Start new conversation explicitly', body['error'])
            failed = self.desk.store.get(identifier)
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(failed['error'], body['error'])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            worker.join(timeout=5)

        self.desk.close()
        reopened = Desk(str(self.native), self.home, self.path / 'state')
        self.addCleanup(reopened.store.db.close)
        self.addCleanup(reopened.close)
        with self.assertRaisesRegex(RuntimeError, 'original --codex-home'):
            reopened.open(identifier)
        failed = reopened.store.get(identifier)
        for field in ('id', 'thread_id', 'cwd', 'profile', 'name', 'created', 'model', 'provider'):
            self.assertEqual(failed[field], original[field])
        self.assertEqual(reopened.runtimes, {})
        self.assertEqual(reopened.store.events(identifier), [])

        missing.unlink()
        self.assertEqual(reopened.open(identifier)['thread']['id'], 'native-original')
        self.assertEqual(reopened.store.get(identifier)['status'], 'ready')
        self.assertIsNone(reopened.store.get(identifier)['error'])
        self.assertEqual(config.read_bytes(), config_before)
        requests = [json.loads(line) for line in (self.home / 'fixture-requests.jsonl').read_text().splitlines()]
        self.assertEqual(sum(r['method'] == 'thread/read' for r in requests), 1)
        self.assertEqual(sum(r['method'] == 'thread/resume' for r in requests), 3)
        self.assertNotIn('thread/start', [r['method'] for r in requests])
        self.assertNotIn('turn/start', [r['method'] for r in requests])

    def test_close_is_bounded_with_inherited_pipes_and_retired_reader_cannot_change_reopened_turn(self):
        identifier = self.desk.store.create(str(self.project), 'default')
        self.desk.store.update(identifier, thread_id='native-original', status='completed')
        (self.home / 'spawn-child').touch()
        self.desk.open(identifier)
        retired = self.desk.runtimes[identifier]
        release = self.home / 'release-child'

        def release_child():
            release.touch()
            retired.reader.join(timeout=2)
            retired.stderr_reader.join(timeout=2)

        self.addCleanup(release_child)
        pending = queue.Queue(maxsize=1)
        with retired.lock:
            retired.pending[999] = pending
        self.desk.store.update(identifier, status='running')
        started = time.monotonic()
        retired.close()
        self.assertLess(time.monotonic() - started, 2)
        self.assertIsNotNone(retired.process.poll())
        self.assertEqual(pending.get(timeout=0.1)['error']['message'], 'Codex app-server exited')
        self.assertEqual(self.desk.store.get(identifier)['status'], 'interrupted')
        self.assertTrue(retired.reader.is_alive(), 'Fixture child should still hold stdout open')

        self.desk.open(identifier)
        self.desk.store.update(identifier, status='running', error=None)
        events = self.desk.store.events(identifier)
        release_child()
        self.assertFalse(retired.reader.is_alive())
        self.assertFalse(retired.stderr_reader.is_alive())
        self.assertTrue(retired.process.stdout.closed)
        self.assertTrue(retired.process.stderr.closed)
        self.assertEqual(self.desk.store.get(identifier)['status'], 'running')
        self.assertIsNone(self.desk.store.get(identifier)['error'])
        self.assertEqual(self.desk.store.events(identifier), events)


if __name__ == '__main__':
    unittest.main()
