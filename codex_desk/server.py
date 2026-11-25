"""Loopback UI for project-bound native sessions."""
import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser
from .runtime import Runtime, Store, profiles


class Desk:
    def __init__(self, binary, home, state):
        self.binary, self.home = binary, Path(home)
        self.store = Store(Path(state) / "desk.sqlite3")
        self.runtimes = {}
        self.lock = threading.RLock()
    def open(self, identifier):
        with self.lock:
            runtime = self.runtimes.get(identifier)
            if runtime and runtime.process.poll() is None:
                return {"thread": {"id": self.store.get(identifier)['thread_id']}}
            if not self.store.get(identifier):
                raise ValueError("Session not found")
            runtime = Runtime(self.store, identifier, self.binary, self.home)
            self.runtimes[identifier] = runtime
            try:
                return runtime.attach()
            except Exception:
                runtime.close()
                self.runtimes.pop(identifier, None)
                self.store.update(identifier, status="failed", error="Native session could not open")
                raise
    def create(self, cwd, profile):
        path = Path(cwd).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Select a project directory")
        if profile not in {p['id'] for p in profiles(self.home)}:
            raise ValueError("Select an existing Codex profile")
        identifier = self.store.create(str(path), profile)
        self.open(identifier)
        return {"id": identifier}
    def runtime(self, identifier):
        self.open(identifier)
        return self.runtimes[identifier]
    def close(self):
        for runtime in list(self.runtimes.values()):
            runtime.close()


def handler(desk):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def reply(self, value, status=200):
            data = json.dumps(value).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            self.wfile.write(data)
        def local(self):
            # Local browser pages must not turn arbitrary websites into command clients.
            expected = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected:
                raise ValueError("Use the printed loopback URL")
            origin = self.headers.get('Origin')
            if origin and origin != 'http://' + expected:
                raise ValueError("Cross-origin requests are not accepted")
        def do_GET(self):
            try:
                self.local()
                url = urlsplit(self.path)
                if url.path == '/api/state':
                    return self.reply({'profiles': profiles(desk.home), 'sessions': desk.store.sessions(), 'pending': {k: list(v.approvals.values()) for k, v in desk.runtimes.items() if v.process.poll() is None}})
                if url.path == '/api/events':
                    params = parse_qs(url.query)
                    return self.reply(desk.store.events(params['session'][0], int(params.get('after', ['0'])[0])))
                if url.path not in ('/', '/app.js', '/style.css'):
                    return self.reply({'error': 'Not found'}, 404)
                name = 'index.html' if url.path == '/' else url.path[1:]
                data = (Path(__file__).parent / 'static' / name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name])
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, KeyError) as error:
                self.reply({'error': str(error)}, 400)
        def do_POST(self):
            try:
                self.local()
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError("Expected JSON request")
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Request size outside supported range")
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path == '/api/sessions':
                    result = desk.create(data['cwd'], data['profile'])
                elif path == '/api/open':
                    result = desk.open(data['session'])
                elif path == '/api/turn':
                    text = data['text'].strip()
                    if not text:
                        raise ValueError("Enter a project task")
                    result = desk.runtime(data['session']).turn(text)
                elif path == '/api/approval':
                    result = desk.runtime(data['session']).approve(data['request'], data['decision'])
                elif path == '/api/stop':
                    result = desk.runtime(data['session']).interrupt()
                else:
                    return self.reply({'error': 'Not found'}, 404)
                self.reply(result)
            except (ValueError, KeyError, OSError, RuntimeError) as error:
                self.reply({'error': str(error)}, 400)
            except Exception as error:
                self.reply({'error': type(error).__name__ + ': ' + str(error)}, 500)
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Open your daily native Codex project workbench")
    parser.add_argument('--codex', default=shutil.which('codex'))
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--state-dir', default=str(Path.home() / '.local' / 'state' / 'codex-desk'))
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not args.codex:
        parser.error('Install Codex CLI first, or pass --codex /path/to/codex')
    desk = Desk(args.codex, args.codex_home, args.state_dir)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), handler(desk))
    url = f'http://127.0.0.1:{server.server_port}'
    print('Codex Desk: ' + url, flush=True)
    if not args.no_browser:
        webbrowser.open(url)
    def stop(*_):
        threading.Thread(target=server.shutdown, daemon=True).start()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        server.serve_forever()
    finally:
        desk.close()
        server.server_close()

if __name__ == '__main__':
    main()
