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
from .runtime import Runtime, Store, profiles, save_profile, task_name, first_task, session_name
from .handoff import build_handoff


class Desk:
    def __init__(self, binary, home, state):
        self.binary, self.home = binary, Path(home).expanduser().resolve()
        self.store = Store(Path(state) / "desk.sqlite3")
        self.runtimes = {}
        self.lock = threading.RLock()
    def open(self, identifier):
        with self.lock:
            runtime = self.runtimes.get(identifier)
            if runtime and runtime.process.poll() is None:
                return runtime.thread_result
            if not self.store.get(identifier):
                raise ValueError("Session not found")
            if runtime:
                runtime.close()
            runtime = None
            try:
                runtime = Runtime(self.store, identifier, self.binary, self.home)
                self.runtimes[identifier] = runtime
                return runtime.attach()
            except Exception:
                if runtime is not None:
                    runtime.close()
                self.runtimes.pop(identifier, None)
                self.store.update(identifier, status="failed", error="Native session could not open")
                raise
    def profile_id(self, value):
        rows = profiles(self.home)
        row = next((p for p in rows if p['id'] == value), None)
        row = row or next((p for p in rows if p.get('legacy_id') == value), None)
        if not row:
            raise ValueError('Select an existing Codex profile')
        return row['id']
    def create(self, cwd, profile, name=None):
        path = Path(cwd).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Select a project directory")
        profile = self.profile_id(profile)
        identifier = self.store.create(str(path), profile, name=name)
        self.open(identifier)
        return {"id": identifier}
    def runtime(self, identifier):
        self.open(identifier)
        return self.runtimes[identifier]
    def rename(self, identifier, name):
        name = session_name(name)
        if not self.store.get(identifier) or identifier == 'native-catalog':
            raise ValueError('Session not found')
        return self.runtime(identifier).rename(name)
    def catalog(self):
        with self.lock:
            identifier = 'native-catalog'
            if not self.store.get(identifier):
                self.store.create(str(Path.cwd()), 'default', identifier)
            runtime = self.runtimes.get(identifier)
            if not runtime or runtime.process.poll() is not None:
                if runtime:
                    runtime.close()
                runtime = Runtime(self.store, identifier, self.binary, self.home)
                self.runtimes[identifier] = runtime
            return runtime
    def history(self, thread_id):
        return self.catalog().request('thread/read', {'threadId': thread_id, 'includeTurns': True})['thread']
    def import_thread(self, thread_id, profile):
        thread = self.history(thread_id)
        cwd = Path(thread['cwd'])
        if not cwd.is_dir():
            raise ValueError('The saved project folder no longer exists; open a new workspace and hand off there')
        profile = self.profile_id(profile)
        existing = next((s for s in self.store.sessions()
            if s['thread_id'] == thread_id and (s['profile'] if s['profile'] == 'default' or s['profile'].startswith('sidecar:') else 'sidecar:' + s['profile']) == profile), None)
        if existing:
            return {'id': existing['id'], 'thread': thread}
        # Import is read-only. Native resume happens only when the user opens it.
        identifier = self.store.create(str(cwd), profile)
        self.store.update(identifier, thread_id=thread['id'], model=thread.get('model'),
                          provider=thread.get('modelProvider'), status='saved')
        title = task_name(thread.get('name') or '')
        source = 'native' if title else 'task'
        title = title or first_task(thread.get('turns', [])) or task_name(thread.get('preview') or '')
        if title:
            self.store.update(identifier, name=title, name_source=source, name_pending=0)
        return {'id': identifier, 'thread': thread}
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
                    return self.reply({'profiles': profiles(desk.home), 'sessions': [s for s in desk.store.sessions() if s['id'] != 'native-catalog'], 'pending': {k: list(v.approvals.values()) for k, v in desk.runtimes.items() if v.process.poll() is None}})
                if url.path == '/api/native':
                    params = parse_qs(url.query)
                    options = {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at'}
                    if params.get('cwd'):
                        options['cwd'] = params['cwd'][0]
                    if params.get('cursor'):
                        options['cursor'] = params['cursor'][0]
                    return self.reply(desk.catalog().request('thread/list', options))
                if url.path == '/api/native/thread':
                    params = parse_qs(url.query)
                    return self.reply(desk.history(params['id'][0]))
                if url.path == '/api/events':
                    params = parse_qs(url.query)
                    return self.reply(desk.store.events(params['session'][0], int(params.get('after', ['0'])[0])))
                if url.path not in ('/', '/app.js', '/evidence.js', '/style.css'):
                    return self.reply({'error': 'Not found'}, 404)
                name = 'index.html' if url.path == '/' else url.path[1:]
                data = (Path(__file__).parent / 'static' / name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'evidence.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name])
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, KeyError, RuntimeError, OSError) as error:
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
                if path == '/api/profiles':
                    result = save_profile(desk.home, data['name'], data['endpoint'], data['model'], data['key'])
                elif path == '/api/sessions':
                    result = desk.create(data['cwd'], data['profile'], data.get('name') or None)
                elif path == '/api/import':
                    result = desk.import_thread(data['thread'], data['profile'])
                elif path == '/api/handoff':
                    result = {'text': build_handoff(desk.history(data['thread']))}
                elif path == '/api/handoff/start':
                    text = data['text'].strip()
                    goal = data['goal'].strip()
                    if not text or not goal:
                        raise ValueError('Enter the next task and review the handoff before starting')
                    text = 'Next task: ' + goal + '\n\n' + text
                    result = desk.create(data['cwd'], data['profile'])
                    desk.runtime(result['id']).turn(text)
                elif path == '/api/open':
                    result = desk.open(data['session'])
                elif path == '/api/rename':
                    result = desk.rename(data['session'], data['name'])
                elif path == '/api/turn':
                    text = data['text'].strip()
                    if not text:
                        raise ValueError("Enter a project task")
                    result = desk.runtime(data['session']).turn(text, data.get('mode', 'native'))
                elif path == '/api/approval':
                    result = desk.runtime(data['session']).approve(data['request'], data['decision'])
                elif path == '/api/answer':
                    result = desk.runtime(data['session']).answer(data['request'], data['answers'])
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


def resolve_codex(value):
    # Native sessions run in the selected project, not the launch directory.
    # Keep the launcher path (including symlinks), but make it absolute now.
    executable = shutil.which(os.path.expanduser(value))
    if not executable:
        raise ValueError(f'Codex executable not found or not executable: {value}. '
                         'Install Codex CLI first, or pass --codex /path/to/codex')
    return os.path.abspath(executable)


def main():
    parser = argparse.ArgumentParser(description="Open your daily native Codex project workbench")
    parser.add_argument('--codex', default='codex',
                        help='Codex executable name or path (relative to this launch directory)')
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--state-dir', default=str(Path.home() / '.local' / 'state' / 'codex-desk'))
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        args.codex = resolve_codex(args.codex)
    except ValueError as error:
        parser.error(str(error))
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
