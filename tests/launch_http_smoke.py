"""Real CLI/bind/asset/shutdown acceptance without native or browser work.

Run ``python tests/launch_http_smoke.py``; set DESK_USE_INSTALLED=1 for the
installed package and DESK_TEST_TEMP to the workspace scratch directory.
The current Python executable supplies the harmless --version preflight.
Every child spawn is recorded; non-version spawns and browser opens are trapped.
"""
import contextlib
import hashlib
from html.parser import HTMLParser
import http.client
import json
import os
from pathlib import Path
import queue
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

SOURCE = Path(__file__).resolve().parents[1]
if os.environ.get('DESK_USE_INSTALLED') == '1':
    sys.path[:] = [path for path in sys.path if Path(path or Path.cwd()).resolve() != SOURCE]
else:
    sys.path.insert(0, str(SOURCE))
from codex_desk import server as desk_server

STARTUP_TIMEOUT = 20

DRIVER = '''import json, os, runpy, socket, subprocess, sys, webbrowser
from pathlib import Path

def reverse_dns(*args, **kwargs):
    raise AssertionError('Unexpected reverse DNS in numeric loopback launch')

socket.getfqdn = socket.gethostbyaddr = reverse_dns

def audit(event, details):
    if event != 'subprocess.Popen':
        return
    argv = details[1]
    expected = [sys.executable, '--version']
    preflight = (argv == subprocess.list2cmdline(expected) if isinstance(argv, str)
                 else list(argv) == expected)
    with Path(os.environ['DESK_LAUNCH_CALLS']).open('a', encoding='utf-8') as log:
        log.write(json.dumps({'argv': argv, 'preflight': preflight}) + '\\n')
    if not preflight:
        raise AssertionError('Unexpected native/child process in launch-only fixture')

def browser_open(*args, **kwargs):
    Path(os.environ['DESK_LAUNCH_BROWSER']).write_text('browser-called', encoding='utf-8')
    raise AssertionError('Unexpected browser open in launch-only fixture')

sys.addaudithook(audit)
webbrowser.open = browser_open
sys.argv[0] = 'codex-desk'
runpy.run_module('codex_desk.server', run_name='__main__')
'''

class PageAssets(HTMLParser):
    def __init__(self):
        super().__init__()
        self.assets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'script' and attrs.get('src'):
            self.assets.append((attrs['src'], 'text/javascript; charset=utf-8'))
        elif tag == 'link' and attrs.get('rel') == 'stylesheet' and attrs.get('href'):
            self.assets.append((attrs['href'], 'text/css; charset=utf-8'))

class LaunchHTTPTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('DESK_TEST_TEMP',
            SOURCE / 'temp')).resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix='launch-http-')
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.state = self.root / 'state'
        self.home = self.root / 'native-home'
        self.calls = self.root / 'child-calls.jsonl'
        self.browser = self.root / 'browser-call.txt'
        self.driver = self.root / 'launch-driver.py'
        self.driver.write_text(DRIVER, encoding='utf-8')
        self.env = {**os.environ, 'PYTHONDONTWRITEBYTECODE': '1',
            'DESK_LAUNCH_CALLS': str(self.calls), 'DESK_LAUNCH_BROWSER': str(self.browser)}
        if self.env.get('DESK_USE_INSTALLED') == '1':
            self.env.pop('PYTHONPATH', None)
        else:
            self.env['PYTHONPATH'] = str(Path(desk_server.__file__).resolve().parent.parent)

    @contextlib.contextmanager
    def launch(self, port, no_browser=False):
        argv = [sys.executable, '-B', str(self.driver), '--codex', sys.executable,
            '--codex-home', str(self.home), '--state-dir', str(self.state), '--port', str(port)]
        if no_browser:
            argv.append('--no-browser')
        process = subprocess.Popen(argv, cwd=self.root, env=self.env,
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8')
        try:
            yield process
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                process.communicate(timeout=4)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=4)
            self.assertIsNotNone(process.returncode, 'Launcher child was not reaped')

    def assert_launch_only(self, preflight=None):
        rows = [json.loads(line) for line in self.calls.read_text(encoding='utf-8').splitlines()] \
            if self.calls.exists() else []
        self.assertTrue(all(row['preflight'] for row in rows), rows)
        self.assertLessEqual(len(rows), 1, rows)
        if preflight is not None:
            self.assertEqual(len(rows), preflight, rows)
        self.assertFalse(self.browser.exists(), 'Launcher called the browser')
        self.assertFalse(self.home.exists(), 'Launcher wrote native home')

    def startup_line(self, process, timeout=STARTUP_TIMEOUT):
        lines = queue.Queue()
        reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
        reader.start()
        try:
            line = lines.get(timeout=timeout)
        except queue.Empty:
            line = None
        if line and line.startswith('Codex Desk: http://127.0.0.1:'):
            reader.join(timeout=1)
            return line
        # Read stderr only after reaping, so a cold startup cannot hide a real
        # preflight/import error behind an uninformative queue.Empty traceback.
        if process.poll() is None:
            process.terminate()
        try:
            process.wait(timeout=4)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=4)
        reader.join(timeout=1)
        remaining, errors = process.communicate(timeout=4)
        reason = (f'no startup URL within {timeout}s' if line is None
                  else 'exited or printed unexpected startup output')
        calls = self.calls.read_text(encoding='utf-8') if self.calls.exists() else ''
        self.fail(f'Launcher {reason}; exit={process.returncode}; '
                  f'stdout={(line or "") + remaining!r}; stderr={errors!r}; '
                  f'child_calls={calls!r}; state_exists={self.state.exists()}; '
                  f'native_home_exists={self.home.exists()}; browser_called={self.browser.exists()}')

    @staticmethod
    def get(address, path, headers=None):
        connection = http.client.HTTPConnection(address.hostname, address.port, timeout=2)
        try:
            connection.request('GET', path, headers=headers or {})
            response = connection.getresponse()
            return response.status, response.getheader('Content-Type'), response.read()
        finally:
            connection.close()

    def test_unrelated_occupied_port_exits_without_state_browser_native_or_probe(self):
        with socket.socket() as occupied:
            occupied.bind(('127.0.0.1', 0))
            occupied.listen()
            port = occupied.getsockname()[1]
            with self.launch(port) as process:
                output, errors = process.communicate(timeout=STARTUP_TIMEOUT)
                self.assertEqual(process.returncode, 2, errors)
                self.assertEqual(output, '')
                self.assertNotIn('Traceback', errors)
                self.assertIn(f'http://127.0.0.1:{port}', errors)
                # Windows may protect the held listener with EACCES/10013,
                # not EADDRINUSE. Runtime must not misclassify that OS error.
                messages = ('already in use', 'Could not listen') if os.name == 'nt' \
                    else ('already in use',)
                self.assertTrue(any(message in errors for message in messages), errors)
                self.assertIn('--port 8788', errors)
                self.assertLess(len(errors), 2000, errors)
                self.assertFalse(self.state.exists(), 'Failed bind created state')
                self.assert_launch_only()
                occupied.settimeout(0.1)
                with self.assertRaises(socket.timeout):
                    connection, _ = occupied.accept()
                    connection.close()

    def test_ephemeral_port_serves_own_assets_and_shutdown_reaps_child(self):
        started = time.monotonic()
        with self.launch(0, no_browser=True) as process:
            line = self.startup_line(process)
            self.assertTrue(line.startswith('Codex Desk: http://127.0.0.1:'), line)
            address = urlsplit(line.removeprefix('Codex Desk: ').strip())
            self.assertEqual(address.hostname, '127.0.0.1')
            self.assertGreater(address.port, 0)
            self.assertLessEqual(address.port, 65535)
            access_token = parse_qs(address.fragment)['access'][0]
            self.assertTrue(access_token)
            status, mime, body = self.get(address, '/api/state')
            self.assertEqual((status, mime), (403, 'application/json; charset=utf-8'))
            self.assertIn('current printed Codex Desk URL', json.loads(body)['error'])
            self.assertNotIn(access_token.encode(), body)
            status, mime, body = self.get(address, '/api/state', {'X-Codex-Desk-Access': access_token})
            self.assertEqual((status, mime), (200, 'application/json; charset=utf-8'))
            self.assertEqual(json.loads(body), {'profiles': [{'id': 'default',
                'name': 'Current Codex settings', 'editable': False}],
                'sessions': [], 'organized': [], 'pending': {}, 'native_outcomes': {},
                'native_material': {'native_home': hashlib.sha256(str(self.home.resolve()).encode('utf-8')).hexdigest(),
                                    'summaries': []}})
            status, mime, body = self.get(address, '/')
            self.assertEqual((status, mime), (200, 'text/html; charset=utf-8'))
            static = Path(desk_server.__file__).resolve().parent / 'static'
            self.assertEqual(body, (static / 'index.html').read_bytes())
            page = PageAssets()
            page.feed(body.decode('utf-8'))
            self.assertIn('/app.js', [asset for asset, _ in page.assets])
            self.assertIn('/style.css', [asset for asset, _ in page.assets])
            for asset, expected_mime in page.assets:
                with self.subTest(asset=asset):
                    parsed = urlsplit(asset)
                    self.assertFalse(parsed.scheme or parsed.netloc)
                    status, mime, body = self.get(address, asset)
                    self.assertEqual((status, mime), (200, expected_mime))
                    self.assertEqual(body, (static / parsed.path.lstrip('/')).read_bytes())
            self.assertTrue((self.state / 'desk.sqlite3').is_file())
            self.assert_launch_only(preflight=1)
            process.terminate()
            _, errors = process.communicate(timeout=4)
            # Windows terminate() uses TerminateProcess, not the SIGTERM handler.
            # Both paths must release the listener and leave a reaped child.
            if os.name != 'nt':
                self.assertEqual(process.returncode, 0, errors)
            else:
                self.assertIsNotNone(process.returncode)
            self.assertNotIn('Traceback', errors)
            with socket.socket() as connection:
                connection.settimeout(1)
                self.assertNotEqual(connection.connect_ex(('127.0.0.1', address.port)), 0,
                    'Launcher left the HTTP listener running')
        self.assertLess(time.monotonic() - started, STARTUP_TIMEOUT + 10)

if __name__ == '__main__':
    unittest.main(verbosity=2)
