import contextlib
import http.client
import io
import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from codex_desk import server as desk_server


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class CliTests(unittest.TestCase):
    def test_missing_executable_stops_before_state_or_browser(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            missing = str(Path(folder) / 'missing-codex')
            with patch.object(sys, 'argv', ['codex-desk', '--codex', missing]), \
                    patch.object(desk_server, 'Desk') as desk, \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as exit:
                    desk_server.main()
            self.assertEqual(exit.exception.code, 2)
            self.assertIn('Codex executable not found or not executable', errors.getvalue())
            self.assertIn('--codex /path/to/codex', errors.getvalue())
            self.assertNotIn('Traceback', errors.getvalue())
            desk.assert_not_called()
            browser.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX executable permissions and home fixture')
    def test_expands_home_and_rejects_nonexecutable_file(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            executable = Path(folder) / 'codex'
            executable.write_text('#!/bin/sh\nexit 0\n')
            with patch.dict(os.environ, {'HOME': folder}):
                with self.assertRaises(ValueError):
                    desk_server.resolve_codex('~/codex')
                executable.chmod(0o755)
                self.assertEqual(desk_server.resolve_codex('~/codex'), str(executable))

    @unittest.skipIf(os.name == 'nt', 'POSIX native-protocol executable fixture')
    def test_relative_launcher_opens_a_different_project(self):
        # This is the actual CLI and HTTP first-project path, with no model turn.
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            launch, project = root / 'launch', root / 'project'
            launch.mkdir()
            project.mkdir()
            bin_dir = launch / 'bin with spaces'
            bin_dir.mkdir()
            executable = bin_dir / 'codex'
            executable.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
assert sys.argv[1:] == ['app-server', '--stdio']
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message:
        continue
    method = message['method']
    if method == 'initialize':
        result = {'userAgent': 'onboarding-fixture'}
    elif method == 'thread/start':
        result = {'thread': {'id': 'onboarding-thread', 'cwd': os.getcwd()},
                  'model': 'fixture', 'modelProvider': 'fixture'}
    else:
        raise AssertionError(method)
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
            executable.chmod(0o755)
            source = str(Path(desk_server.__file__).parent.parent)
            env = {**os.environ, 'PYTHONPATH': source}
            process = subprocess.Popen([sys.executable, '-m', 'codex_desk.server',
                '--codex', './bin with spaces/codex', '--codex-home', str(root / 'home'),
                '--state-dir', str(root / 'state'), '--port', '0', '--no-browser'],
                cwd=launch, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                line = lines.get(timeout=10)
                self.assertTrue(line.startswith('Codex Desk: http://127.0.0.1:'), line)
                address = urlsplit(line.removeprefix('Codex Desk: ').strip())
                connection = http.client.HTTPConnection(address.hostname, address.port, timeout=10)
                try:
                    connection.request('POST', '/api/sessions',
                        json.dumps({'cwd': str(project), 'profile': 'default'}),
                        {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    created = json.loads(response.read())
                    self.assertEqual(response.status, 200, created)
                    connection.request('POST', '/api/open',
                        json.dumps({'session': created['id']}), {'Content-Type': 'application/json'})
                    response = connection.getresponse()
                    opened = json.loads(response.read())
                    self.assertEqual(response.status, 200, opened)
                    self.assertEqual(opened['thread']['cwd'], str(project))
                    self.assertEqual(opened['thread']['id'], 'onboarding-thread')
                finally:
                    connection.close()
            finally:
                process.terminate()
                try:
                    _, errors = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    _, errors = process.communicate(timeout=5)
                reader.join(timeout=5)
            self.assertEqual(process.returncode, 0, errors)


if __name__ == '__main__':
    unittest.main()
