import contextlib
import errno
import http.client
import io
import json
import os
from pathlib import Path
import queue
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from codex_desk import __version__
from codex_desk import server as desk_server


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class CliTests(unittest.TestCase):
    def test_loopback_listener_keeps_numeric_address_without_reverse_dns(self):
        with patch('socket.getfqdn', side_effect=AssertionError('reverse DNS called')) as fqdn, \
                patch('socket.gethostbyaddr', side_effect=AssertionError('reverse DNS called')) as reverse, \
                desk_server.LoopbackHTTPServer(('127.0.0.1', 0),
                    desk_server.BaseHTTPRequestHandler) as server:
            self.assertEqual(server.server_name, '127.0.0.1')
            self.assertGreater(server.server_port, 0)
            self.assertEqual(server.server_address, ('127.0.0.1', server.server_port))
            fqdn.assert_not_called()
            reverse.assert_not_called()

    def test_invalid_ports_stop_before_preflight_state_server_or_browser(self):
        for port in ('-1', '65536', 'not-a-port'):
            with self.subTest(port=port), \
                    patch.object(sys, 'argv', ['codex-desk', '--port', port]), \
                    patch.object(desk_server, 'resolve_codex') as preflight, \
                    patch.object(desk_server, 'Desk') as desk, \
                    patch.object(desk_server, 'LoopbackHTTPServer') as server, \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(io.StringIO()) as output, \
                    contextlib.redirect_stderr(io.StringIO()) as errors:
                with self.assertRaises(SystemExit) as exit:
                    desk_server.main()
                self.assertEqual(exit.exception.code, 2)
                self.assertIn('Use port 0 or an integer from 1 to 65535', errors.getvalue())
                self.assertNotIn('Traceback', errors.getvalue())
                self.assertEqual(output.getvalue(), '')
                preflight.assert_not_called()
                desk.assert_not_called()
                server.assert_not_called()
                browser.assert_not_called()

    def test_occupied_loopback_port_has_guidance_without_creating_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder, \
                desk_server.LoopbackHTTPServer(('127.0.0.1', 0),
                    desk_server.BaseHTTPRequestHandler) as occupied:
            state = Path(folder) / 'state'
            port = occupied.server_port
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(sys, 'argv', ['codex-desk', '--port', str(port),
                    '--state-dir', str(state)]), \
                    patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                    patch.object(desk_server, 'Desk') as desk, \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as exit:
                    desk_server.main()
            self.assertEqual(exit.exception.code, 2)
            self.assertIn(f'http://127.0.0.1:{port} is already in use', errors.getvalue())
            self.assertIn('If Codex Desk is already running, reopen that URL', errors.getvalue())
            self.assertIn('--port 8788', errors.getvalue())
            self.assertNotIn('Traceback', errors.getvalue())
            self.assertEqual(output.getvalue(), '')
            self.assertFalse(state.exists())
            desk.assert_not_called()
            browser.assert_not_called()

    def test_other_listener_failure_is_actionable_without_creating_state(self):
        with patch.object(sys, 'argv', ['codex-desk', '--port', '8787']), \
                patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                patch.object(desk_server, 'LoopbackHTTPServer',
                    side_effect=OSError(errno.EACCES, 'Permission denied')), \
                patch.object(desk_server, 'Desk') as desk, \
                patch.object(desk_server.webbrowser, 'open') as browser, \
                contextlib.redirect_stderr(io.StringIO()) as errors:
            with self.assertRaises(SystemExit) as exit:
                desk_server.main()
        self.assertEqual(exit.exception.code, 2)
        self.assertIn('Could not listen on http://127.0.0.1:8787', errors.getvalue())
        self.assertIn('Permission denied', errors.getvalue())
        self.assertNotIn('Traceback', errors.getvalue())
        desk.assert_not_called()
        browser.assert_not_called()

    def test_listener_precedes_state_and_port_zero_no_browser_closes_resources(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            state = Path(folder) / 'state'
            servers, desks = [], []
            server_type, desk_type = desk_server.LoopbackHTTPServer, desk_server.Desk
            def bind(*args):
                self.assertFalse(state.exists())
                server = server_type(*args)
                server.serve_forever = lambda: None
                servers.append(server)
                return server
            def initialize(*args):
                self.assertGreater(servers[0].socket.fileno(), -1)
                self.assertGreater(servers[0].server_port, 0)
                desk = desk_type(*args)
                desks.append(desk)
                return desk
            with patch.object(sys, 'argv', ['codex-desk', '--port', '0', '--no-browser',
                    '--state-dir', str(state)]), \
                    patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                    patch.object(desk_server, 'LoopbackHTTPServer', side_effect=bind), \
                    patch.object(desk_server, 'Desk', side_effect=initialize), \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                desk_server.main()
            self.assertEqual(output.getvalue(), f'Codex Desk: http://127.0.0.1:{servers[0].server_port}\n')
            self.assertEqual(servers[0].socket.fileno(), -1)
            self.assertEqual(desks[0].runtimes, {})
            with self.assertRaises(sqlite3.ProgrammingError):
                desks[0].store.db.execute('SELECT 1')
            browser.assert_not_called()

    def test_state_initialization_failure_closes_partial_store_and_listener(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            servers, stores = [], []
            server_type, store_type = desk_server.LoopbackHTTPServer, desk_server.Store
            def bind(*args):
                server = server_type(*args)
                servers.append(server)
                return server
            def store(*args):
                result = store_type(*args)
                stores.append(result)
                return result
            with patch.object(sys, 'argv', ['codex-desk', '--port', '0',
                    '--state-dir', str(Path(folder) / 'state')]), \
                    patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                    patch.object(desk_server, 'LoopbackHTTPServer', side_effect=bind), \
                    patch.object(desk_server, 'Store', side_effect=store), \
                    patch.object(desk_server, 'NativeRecallIndex', side_effect=ValueError('index unavailable')), \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                with self.assertRaisesRegex(ValueError, 'index unavailable'):
                    desk_server.main()
            self.assertEqual(servers[0].socket.fileno(), -1)
            with self.assertRaises(sqlite3.ProgrammingError):
                stores[0].db.execute('SELECT 1')
            self.assertEqual(output.getvalue(), '')
            browser.assert_not_called()

    def test_browser_startup_failure_closes_desk_store_and_listener(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            servers, desks = [], []
            server_type, desk_type = desk_server.LoopbackHTTPServer, desk_server.Desk
            def bind(*args):
                server = server_type(*args)
                servers.append(server)
                return server
            def initialize(*args):
                desk = desk_type(*args)
                desks.append(desk)
                return desk
            with patch.object(sys, 'argv', ['codex-desk', '--port', '0',
                    '--state-dir', str(Path(folder) / 'state')]), \
                    patch.object(desk_server, 'resolve_codex', return_value=sys.executable), \
                    patch.object(desk_server, 'LoopbackHTTPServer', side_effect=bind), \
                    patch.object(desk_server, 'Desk', side_effect=initialize), \
                    patch.object(desk_server.webbrowser, 'open', side_effect=RuntimeError('browser unavailable')), \
                    contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'browser unavailable'):
                    desk_server.main()
            self.assertEqual(servers[0].socket.fileno(), -1)
            self.assertEqual(desks[0].runtimes, {})
            self.assertTrue(desks[0].history_scanner.cancelled.is_set())
            with self.assertRaises(sqlite3.ProgrammingError):
                desks[0].store.db.execute('SELECT 1')

    def test_version_exits_before_codex_preflight_state_server_or_browser(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['codex-desk', '--version']), \
                patch.object(desk_server, 'resolve_codex') as preflight, \
                patch.object(desk_server, 'Desk') as desk, \
                patch.object(desk_server, 'LoopbackHTTPServer') as server, \
                patch.object(desk_server.webbrowser, 'open') as browser, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as exit:
                desk_server.main()
        self.assertEqual(exit.exception.code, 0)
        self.assertEqual(output.getvalue(), __version__ + '\n')
        self.assertEqual(errors.getvalue(), '')
        preflight.assert_not_called()
        desk.assert_not_called()
        server.assert_not_called()
        browser.assert_not_called()

    def test_module_version_succeeds_without_codex_or_created_state(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            home, state = root / 'native-home', root / 'state'
            source = str(Path(desk_server.__file__).parent.parent)
            env = {**os.environ, 'PYTHONPATH': source, 'PATH': '', 'CODEX_HOME': str(home)}
            result = subprocess.run([sys.executable, '-m', 'codex_desk.server',
                '--codex', str(root / 'missing-codex'), '--state-dir', str(state), '--version'],
                cwd=root, env=env, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, __version__ + '\n')
            self.assertEqual(result.stderr, '')
            self.assertFalse(home.exists())
            self.assertFalse(state.exists())

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

    @unittest.skipIf(os.name == 'nt', 'POSIX executable launcher fixture')
    def test_broken_launcher_stops_before_state_browser_or_url_without_private_output(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            root = Path(folder)
            executable = root / 'npm codex'
            executable.write_text(f'#!{sys.executable}\n' + '''
import os, sys
assert sys.argv[1:] == ['--version']
print(os.environ['DESK_FIXTURE_KEY'])
print(os.environ['DESK_FIXTURE_KEY'], file=sys.stderr)
sys.exit(1)
''')
            executable.chmod(0o755)
            output, errors = io.StringIO(), io.StringIO()
            state = root / 'state'
            with patch.object(sys, 'argv', ['codex-desk', '--codex', str(executable),
                    '--state-dir', str(state)]), \
                    patch.dict(os.environ, {'DESK_FIXTURE_KEY': 'fixture-private-key'}), \
                    patch.object(desk_server, 'Desk') as desk, \
                    patch.object(desk_server.webbrowser, 'open') as browser, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as exit:
                    desk_server.main()
            self.assertEqual(exit.exception.code, 2)
            self.assertIn('--version exited with status 1', errors.getvalue())
            self.assertIn(shlex.quote(str(executable)) + ' --version', errors.getvalue())
            self.assertIn('same shell', errors.getvalue())
            self.assertIn('Complete or repair', errors.getvalue())
            self.assertNotIn('fixture-private-key', errors.getvalue() + output.getvalue())
            self.assertNotIn('Traceback', errors.getvalue())
            self.assertEqual(output.getvalue(), '')
            self.assertFalse(state.exists())
            desk.assert_not_called()
            browser.assert_not_called()

    def test_launcher_timeout_is_bounded_and_stops_before_state_or_browser(self):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, 'argv', ['codex-desk', '--codex', sys.executable]), \
                patch.object(desk_server.subprocess, 'run', side_effect=subprocess.TimeoutExpired(
                    [sys.executable, '--version'], 10, output='fixture-private-key',
                    stderr='fixture-private-key')) as run, \
                patch.object(desk_server, 'Desk') as desk, \
                patch.object(desk_server.webbrowser, 'open') as browser, \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            with self.assertRaises(SystemExit) as exit:
                desk_server.main()
        self.assertEqual(exit.exception.code, 2)
        run.assert_called_once_with([os.path.abspath(sys.executable), '--version'], timeout=10,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.assertIn('--version timed out after 10 seconds', errors.getvalue())
        self.assertIn('same shell', errors.getvalue())
        self.assertNotIn('fixture-private-key', errors.getvalue() + output.getvalue())
        self.assertEqual(output.getvalue(), '')
        desk.assert_not_called()
        browser.assert_not_called()

    @unittest.skipIf(os.name == 'nt', 'POSIX missing-interpreter fixture')
    def test_executable_with_missing_interpreter_has_actionable_preflight_error(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            executable = Path(folder) / 'codex'
            executable.write_text('#!/missing/codex-interpreter\n')
            executable.chmod(0o755)
            with self.assertRaisesRegex(ValueError, '--version could not run.*same shell'):
                desk_server.resolve_codex(str(executable))

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
            home = root / 'home'
            home.mkdir()
            config = home / 'config.toml'
            config.write_text('model="existing-model"\nmodel_provider="existing-provider"\n')
            auth = home / 'auth.json'
            auth.write_text('{"OPENAI_API_KEY":"fixture-private-key"}')
            config_before, auth_before = config.read_bytes(), auth.read_bytes()
            log = root / 'launcher.jsonl'
            executable.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
with Path(os.environ['DESK_LAUNCHER_LOG']).open('a') as log:
    log.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd(),
                         'home': os.environ.get('CODEX_HOME')}) + '\\n')
if sys.argv[1:] == ['--version']:
    print('codex-cli fixture')
    sys.exit(0)
assert sys.argv[1:] == ['app-server', '--stdio']
assert os.environ['DESK_FIXTURE_KEY'] == 'fixture-private-key'
for line in sys.stdin:
    message = json.loads(line)
    if 'id' not in message:
        continue
    method = message['method']
    if method == 'initialize':
        result = {'userAgent': 'onboarding-fixture'}
    elif method == 'thread/start':
        assert message['params']['cwd'] == os.getcwd()
        assert 'config' not in message['params']
        result = {'thread': {'id': 'onboarding-thread', 'cwd': os.getcwd()},
                  'model': 'fixture', 'modelProvider': 'fixture'}
    else:
        raise AssertionError(method)
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
            executable.chmod(0o755)
            source = str(Path(desk_server.__file__).parent.parent)
            env = {**os.environ, 'PYTHONPATH': source, 'DESK_LAUNCHER_LOG': str(log),
                   'DESK_FIXTURE_KEY': 'fixture-private-key'}
            process = subprocess.Popen([sys.executable, '-m', 'codex_desk.server',
                '--codex', './bin with spaces/codex', '--codex-home', str(home),
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
            launches = [json.loads(line) for line in log.read_text().splitlines()]
            self.assertEqual(launches[0]['argv'], ['--version'])
            self.assertEqual(launches[0]['cwd'], str(launch))
            self.assertEqual(len(launches), 2)
            self.assertEqual(launches[1], {'argv': ['app-server', '--stdio'],
                                          'cwd': str(project), 'home': str(home)})
            self.assertNotIn('fixture-private-key', log.read_text() + errors)
            self.assertEqual(config.read_bytes(), config_before)
            self.assertEqual(auth.read_bytes(), auth_before)


if __name__ == '__main__':
    unittest.main()
