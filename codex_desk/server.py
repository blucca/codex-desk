"""Loopback UI for project-bound native sessions."""
import argparse
import errno
import json
import os
from pathlib import Path
import secrets
import shlex
import shutil
import signal
from socketserver import TCPServer
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit
import webbrowser
from . import __version__
from .runtime import (Runtime, Store, profiles, save_profile, update_profile, task_name,
                      first_task, session_name, MissingRolloutError, NativeRequestRejected, NativeRequestUnknown)
from .handoff import build_handoff
from .native_recall import NativeRecallIndex
from .history_scan import NativeHistoryScanner
from .drafts import load_draft, save_draft, DraftConflict
from .followups import (FollowupConflict, followup_snapshot, add_followup, edit_followup,
    remove_followup, reorder_followups, clear_followups, reserve_followup, record_followup_receipt)


class FollowupDispatchError(RuntimeError):
    def __init__(self, message, snapshot):
        self.snapshot = snapshot
        super().__init__(message)


class LoopbackHTTPServer(ThreadingHTTPServer):
    """Bind the numeric local listener without a reverse-DNS lookup."""
    def server_bind(self):
        # HTTPServer.server_bind calls getfqdn after reserving the socket.
        # The UI uses its numeric loopback URL, so keep that address directly.
        TCPServer.server_bind(self)
        self.server_name, self.server_port = self.server_address[:2]


class Desk:
    def __init__(self, binary, home, state):
        self.binary, self.home = binary, Path(home).expanduser().resolve()
        self._catalog_fallback_cwd = Path(state).resolve()
        self.store = Store(self._catalog_fallback_cwd / "desk.sqlite3")
        try:
            self.native_index = NativeRecallIndex(self.store)
            self.history_scanner = NativeHistoryScanner(self, self.native_index)
        except BaseException:
            self.store.db.close()
            raise
        self.runtimes = {}
        self.lock = threading.RLock()
        self.admissions = {}
        self.followup_sends = {}
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
            except Exception as error:
                if runtime is not None:
                    runtime.close()
                self.runtimes.pop(identifier, None)
                self.store.update(identifier, status="failed", error=(str(error)
                    if isinstance(error, MissingRolloutError) else "Native session could not open"))
                raise
    def profile_id(self, value):
        rows = profiles(self.home)
        row = next((p for p in rows if p['id'] == value), None)
        row = row or next((p for p in rows if p.get('legacy_id') == value), None)
        if not row:
            raise ValueError('Select an existing Codex profile')
        return row['id']
    def project_path(self, cwd):
        if not cwd:
            raise ValueError("Select a project directory")
        path = Path(cwd).expanduser().resolve(strict=True)
        if not path.is_dir():
            raise ValueError("Select a project directory")
        return path
    def create(self, cwd, profile, name=None):
        path = self.project_path(cwd)
        profile = self.profile_id(profile)
        identifier = self.store.create(str(path), profile, name=name)
        self.open(identifier)
        return {"id": identifier}
    def runtime(self, identifier):
        self.open(identifier)
        return self.runtimes[identifier]
    def admission_lock(self, identifier):
        if not isinstance(identifier, str) or not identifier or identifier == 'native-catalog':
            raise ValueError('Select an existing project session')
        with self.lock:
            return self.admissions.setdefault(identifier, threading.Lock())
    def turn(self, identifier, text, mode='native'):
        # The same explicit admission gate covers ordinary tasks and Send next.
        gate = self.admission_lock(identifier)
        if not gate.acquire(blocking=False):
            raise ValueError('Finish or stop the current turn first')
        try:
            snapshot = followup_snapshot(self.store, identifier)
            if snapshot['reservation']:
                raise FollowupConflict(snapshot)
            runtime = self.runtime(identifier)
            records = self.store.events(identifier)
            cursor = records[-1]['seq'] if records else 0
            try:
                return runtime.turn(text, mode)
            except NativeRequestUnknown:
                result = self.started_since(identifier, cursor)
                if result is not None:
                    self.record_admission_mode(identifier, mode)
                    return result
                self.retire_runtime(identifier, runtime)
                raise
        finally:
            gate.release()
    def retire_runtime(self, identifier, runtime):
        try:
            runtime.close()
        finally:
            with self.lock:
                if self.runtimes.get(identifier) is runtime:
                    self.runtimes.pop(identifier, None)
    def mutate_followups(self, operation, data):
        identifier = data['session']
        # Brief local commits remain available while native start is pending.
        with self.lock:
            if operation == 'add':
                add_followup(self.store, identifier, data['text'], data.get('mode', 'native'))
            elif operation == 'edit':
                edit_followup(self.store, identifier, data['id'], data['text'], data['mode'], data['revision'])
            elif operation == 'remove':
                remove_followup(self.store, identifier, data['id'], data['revision'])
            elif operation == 'reorder':
                if not isinstance(data['order'], list):
                    raise ValueError('Use the follow-up order you reviewed')
                reorder_followups(self.store, identifier, data['ids'], data['order'])
            elif operation == 'clear':
                if not isinstance(data['order'], list):
                    raise ValueError('Use the follow-up order you reviewed')
                clear_followups(self.store, identifier, data['order'])
            return followup_snapshot(self.store, identifier)
    def started_since(self, identifier, cursor):
        thread_id = self.store.get(identifier)['thread_id']
        for record in reversed(self.store.events(identifier, cursor)):
            event = record['event']
            params = event.get('params', {})
            turn = params.get('turn')
            if (event.get('method') == 'turn/started' and params.get('threadId', thread_id) == thread_id
                    and isinstance(turn, dict) and isinstance(turn.get('id'), str) and turn['id']):
                return {'turn': turn}
        return None
    def record_admission_mode(self, identifier, mode):
        """Remember accepted Work/Plan intent without replacing the native outcome."""
        self.store.update(identifier, mode=mode, thread_saved=1)
    def send_followup(self, data):
        identifier = data['session']
        gate = self.admission_lock(identifier)
        if not gate.acquire(blocking=False):
            raise FollowupConflict(followup_snapshot(self.store, identifier))
        reservation = None
        try:
            with self.lock:
                reservation = reserve_followup(self.store, identifier, data['id'], data['revision'], first_only=True)
                if reservation is None:
                    raise FollowupConflict(followup_snapshot(self.store, identifier))
                self.followup_sends[identifier] = reservation['token']
            records = self.store.events(identifier)
            cursor = records[-1]['seq'] if records else 0
            invoked, result, error, runtime = False, None, None, None
            try:
                runtime = self.runtime(identifier)
                # Attach/resume notifications describe prior work, not this
                # prepared task's admission.
                records = self.store.events(identifier)
                cursor = records[-1]['seq'] if records else 0
                invoked = True
                result = runtime.turn(reservation['text'], reservation['mode'])
                turn = result.get('turn') if isinstance(result, dict) else None
                confirmed = isinstance(turn, dict) and isinstance(turn.get('id'), str) and bool(turn['id'])
                if not confirmed:
                    result = self.started_since(identifier, cursor)
                    if result is None:
                        error = 'Native task admission is unconfirmed; review this receipt before sending another task'
            except Exception as failure:
                error = str(failure)
                # A genuine started event is admission proof even if its reply
                # was lost or a very fast task already completed.
                result = (self.started_since(identifier, cursor)
                          if invoked and not isinstance(failure, ValueError) else None)
                rejected = not invoked or isinstance(failure, (NativeRequestRejected, ValueError))
            else:
                rejected = False
            outcome = 'accepted' if result is not None else 'rejected' if rejected else 'unknown'
            if outcome == 'accepted':
                self.record_admission_mode(identifier, reservation['mode'])
            receipt = record_followup_receipt(self.store, identifier, reservation['token'],
                reservation['entry_id'], reservation['revision'], outcome)
            if outcome == 'unknown' and runtime is not None:
                # Retire an unconfirmed writer before explicit rejection can
                # make another admission possible. Late retired events cannot
                # become a second task's start/completion evidence.
                self.retire_runtime(identifier, runtime)
            snapshot = {**followup_snapshot(self.store, identifier), 'receipt': receipt}
            if outcome == 'accepted':
                snapshot['turn'] = result
                return snapshot
            raise FollowupDispatchError(error, snapshot)
        finally:
            if reservation is not None:
                with self.lock:
                    if self.followup_sends.get(identifier) == reservation['token']:
                        self.followup_sends.pop(identifier, None)
            gate.release()
    def resolve_followup(self, data):
        identifier = data['session']
        if data['outcome'] not in ('accepted', 'rejected'):
            raise ValueError('Confirm accepted or rejected task admission')
        gate = self.admission_lock(identifier)
        if not gate.acquire(blocking=False):
            raise FollowupConflict(followup_snapshot(self.store, identifier))
        try:
            with self.lock:
                snapshot = followup_snapshot(self.store, identifier)
                runtime = self.runtimes.get(identifier)
                if identifier in self.followup_sends:
                    raise FollowupConflict(snapshot)
                if (data['outcome'] == 'rejected' and runtime is not None
                        and runtime.process.poll() is None
                        and self.store.get(identifier)['status'] in ('starting', 'running', 'approval')):
                    raise FollowupConflict(snapshot)
                receipt = record_followup_receipt(self.store, identifier, data['token'], data['id'],
                    data['revision'], data['outcome'])
                if data['outcome'] == 'accepted':
                    self.record_admission_mode(identifier, snapshot['reservation']['mode'])
                return {**followup_snapshot(self.store, identifier), 'receipt': receipt}
        finally:
            gate.release()
    def rename(self, identifier, name):
        name = session_name(name)
        if not self.store.get(identifier) or identifier == 'native-catalog':
            raise ValueError('Session not found')
        return self.runtime(identifier).rename(name)
    def catalog(self):
        with self.lock:
            identifier = 'native-catalog'
            row = self.store.get(identifier)
            if not row:
                try:
                    cwd = Path.cwd()
                except FileNotFoundError:
                    cwd = self._catalog_fallback_cwd
                self.store.create(str(cwd), 'default', identifier)
                row = self.store.get(identifier)
            runtime = self.runtimes.get(identifier)
            if not runtime or runtime.process.poll() is not None:
                if runtime:
                    runtime.close()
                # History reads need no former project. Keep its stored cwd,
                # but launch from the stable state directory if it disappeared.
                options = {} if Path(row['cwd']).is_dir() else {'catalog_cwd': self._catalog_fallback_cwd}
                runtime = Runtime(self.store, identifier, self.binary, self.home, **options)
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
        # Native history is read before the lock; only the local binding
        # decision/commit must be atomic across concurrent browser windows.
        with self.lock:
            existing = next((s for s in self.store.sessions()
                if s['thread_id'] == thread_id and (s['profile'] if s['profile'] == 'default' or s['profile'].startswith('sidecar:') else 'sidecar:' + s['profile']) == profile), None)
            if existing:
                self.store.archive(existing['id'], False)
                self.store.update(existing['id'], thread_saved=1)
                self.store.recall_snapshot(existing['id'], thread)
                return {'id': existing['id'], 'thread': thread}
            # Import is read-only. Native resume happens only when the user opens it.
            identifier = self.store.create(str(cwd), profile)
            self.store.update(identifier, thread_id=thread['id'], model=thread.get('model'),
                              provider=thread.get('modelProvider'), status='saved', thread_saved=1)
            title = task_name(thread.get('name') or '')
            source = 'native' if title else 'task'
            title = title or first_task(thread.get('turns', [])) or task_name(thread.get('preview') or '')
            if title:
                self.store.update(identifier, name=title, name_source=source, name_pending=0)
            self.store.recall_snapshot(identifier, thread)
            return {'id': identifier, 'thread': thread}
    def recall(self, q, cwd=None, include_archived=False, limit=30):
        # Search only saved SQLite evidence. Bindings include archived sessions:
        # their native cache must never become an alternate visibility path.
        with self.store.lock:
            result = self.store.recall(q, cwd, include_archived, limit)
            bindings = dict(self.store.db.execute(
                'SELECT id,thread_id FROM sessions WHERE thread_id IS NOT NULL'))
            for hit in result['results']:
                if hit['kind'] == 'activity' and hit['session_id'] in bindings:
                    hit['thread_id'] = bindings[hit['session_id']]
            native = self.native_index.search(q, cwd, limit, exclude_thread_ids=bindings.values())
            native_hits = [dict(hit, name=hit['title'], profile='default', archived=False)
                           for hit in native['results']]
            result['results'] = sorted(result['results'] + native_hits,
                                       key=lambda hit: hit['updated'], reverse=True)[:limit]
            result['total'] += native['total']
            result['truncated'] = result['total'] > len(result['results'])
            result['coverage']['native'] = native['coverage']
            return result
    def close(self):
        self.history_scanner.close()
        for runtime in list(self.runtimes.values()):
            runtime.close()


def handler(desk, access_token=None):
    """Build the UI handler with a per-launch private-API capability.

    access_token=None is internal controlled-fixture mode. Production main
    always injects a fresh capability shared through its printed launch URL.
    """
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
        def authorized(self):
            if access_token is not None and not secrets.compare_digest(
                    self.headers.get('X-Codex-Desk-Access', '').encode('utf-8'),
                    access_token.encode('utf-8')):
                self.reply({'error': 'Open the current printed Codex Desk URL to access your local workbench'}, 403)
                return False
            return True
        def do_GET(self):
            try:
                self.local()
                url = urlsplit(self.path)
                if url.path.startswith('/api/') and not self.authorized():
                    return
                if url.path == '/api/history/index':
                    return self.reply({'job': desk.history_scanner.status(),
                                       'coverage': desk.native_index.stats()})
                if url.path == '/api/recall':
                    params = parse_qs(url.query, keep_blank_values=True, max_num_fields=10)
                    if any(key not in ('q', 'cwd', 'archived', 'limit') or len(values) != 1
                           for key, values in params.items()):
                        raise ValueError('Use each recall query option once')
                    archived = params.get('archived', ['false'])[0].lower()
                    if archived not in ('true', 'false', '0', '1'):
                        raise ValueError('Choose whether to include archived sessions')
                    return self.reply(desk.recall(params.get('q', [''])[0], params.get('cwd', [None])[0],
                        archived in ('true', '1'), int(params.get('limit', ['30'])[0])))
                if url.path == '/api/followups':
                    params = parse_qs(url.query)
                    return self.reply(followup_snapshot(desk.store, params['session'][0]))
                if url.path == '/api/draft':
                    params = parse_qs(url.query)
                    return self.reply(load_draft(desk.store, params['session'][0]))
                if url.path == '/api/state':
                    return self.reply({'profiles': profiles(desk.home),
                        'sessions': [s for s in desk.store.sessions() if s['id'] != 'native-catalog'],
                        'organized': desk.store.organized_sessions(include_archived=True),
                        'pending': {k: list(v.approvals.values()) for k, v in desk.runtimes.items() if v.process.poll() is None}})
                if url.path == '/api/organized':
                    params = parse_qs(url.query, keep_blank_values=True)
                    archived = params.get('include_archived', ['false'])[0].lower()
                    if archived not in ('false', 'true', '0', '1'):
                        raise ValueError('Choose whether to include archived sessions')
                    return self.reply(desk.store.organized_sessions(cwd=params.get('cwd', [None])[0],
                        title=params.get('title', [''])[0], include_archived=archived in ('true', '1')))
                if url.path == '/api/native':
                    params = parse_qs(url.query, keep_blank_values=True)
                    options = {'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at'}
                    if 'cwd' in params:
                        options['cwd'] = str(desk.project_path(params['cwd'][0]))
                    search = params.get('search', [''])[0].strip()
                    if search:
                        options['searchTerm'] = search
                    if params.get('cursor'):
                        options['cursor'] = params['cursor'][0]
                    result = desk.catalog().request('thread/list', options)
                    if params.get('recent') == ['1']:
                        # Enrich a copy for Home; ordinary history stays native-shaped.
                        result = dict(result, data=[dict(row, cwdExists=Path(row['cwd']).expanduser().is_dir())
                            if isinstance(row, dict) and isinstance(row.get('cwd'), str) else row
                            for row in result.get('data', [])])
                    return self.reply(result)
                if url.path == '/api/native/thread':
                    params = parse_qs(url.query)
                    return self.reply(desk.history(params['id'][0]))
                if url.path == '/api/events':
                    params = parse_qs(url.query)
                    return self.reply(desk.store.events(params['session'][0], int(params.get('after', ['0'])[0])))
                if url.path not in ('/', '/app.js', '/evidence.js', '/activity.js', '/history_reader.js', '/followups.js', '/native-state.js', '/recall.js', '/home.js', '/style.css'):
                    return self.reply({'error': 'Not found'}, 404)
                name = 'index.html' if url.path == '/' else url.path[1:]
                data = (Path(__file__).parent / 'static' / name).read_bytes()
                self.send_response(200)
                self.send_header('Content-Type', {'index.html': 'text/html; charset=utf-8', 'app.js': 'text/javascript; charset=utf-8', 'evidence.js': 'text/javascript; charset=utf-8', 'activity.js': 'text/javascript; charset=utf-8', 'history_reader.js': 'text/javascript; charset=utf-8', 'followups.js': 'text/javascript; charset=utf-8', 'native-state.js': 'text/javascript; charset=utf-8', 'recall.js': 'text/javascript; charset=utf-8', 'home.js': 'text/javascript; charset=utf-8', 'style.css': 'text/css; charset=utf-8'}[name])
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                self.wfile.write(data)
            except (ValueError, KeyError, RuntimeError, OSError) as error:
                self.reply({'error': str(error)}, 400)
        def do_POST(self):
            try:
                self.local()
                if not self.authorized():
                    return
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    raise ValueError("Expected JSON request")
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 1024 * 1024:
                    raise ValueError("Request size outside supported range")
                data = json.loads(self.rfile.read(size))
                path = urlsplit(self.path).path
                if path in ('/api/history/index', '/api/history/index/cancel'):
                    if not isinstance(data, dict):
                        raise ValueError('Expected a history indexing object')
                    if path == '/api/history/index':
                        result = desk.history_scanner.start(data.get('limit', 200))
                    else:
                        result = desk.history_scanner.cancel()
                elif path == '/api/followups':
                    result = desk.mutate_followups('add', data)
                elif path in ('/api/followups/edit', '/api/followups/remove', '/api/followups/reorder', '/api/followups/clear'):
                    result = desk.mutate_followups(path.rsplit('/', 1)[-1], data)
                elif path == '/api/followups/send':
                    result = desk.send_followup(data)
                elif path == '/api/followups/resolve':
                    result = desk.resolve_followup(data)
                elif path == '/api/draft':
                    result = save_draft(desk.store, data['session'], data['text'], data['mode'], data['revision'], data.get('writer'), data.get('sequence'))
                elif path == '/api/archive':
                    result = desk.store.archive(data['session'], data['archived'])
                elif path == '/api/profiles':
                    result = save_profile(desk.home, data['name'], data['endpoint'], data['model'], data['key'])
                elif path == '/api/profiles/update':
                    with desk.lock:
                        result = update_profile(desk.home, data['id'], data['endpoint'], data['model'], data.get('key', ''))
                        stored = {row['id']: row['profile'] for row in desk.store.sessions()}
                        result['restartRequired'] = any(runtime.process.poll() is None and
                            (stored[identifier] if stored[identifier] == 'default' or stored[identifier].startswith('sidecar:')
                             else 'sidecar:' + stored[identifier]) == result['id']
                            for identifier, runtime in desk.runtimes.items() if identifier in stored)
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
                    desk.turn(result['id'], text)
                elif path == '/api/open':
                    result = desk.open(data['session'])
                elif path == '/api/rename':
                    result = desk.rename(data['session'], data['name'])
                elif path == '/api/turn':
                    text = data['text'].strip()
                    if not text:
                        raise ValueError("Enter a project task")
                    result = desk.turn(data['session'], text, data.get('mode', 'native'))
                elif path == '/api/approval':
                    result = desk.runtime(data['session']).approve(data['request'], data['decision'])
                elif path == '/api/answer':
                    result = desk.runtime(data['session']).answer(data['request'], data['answers'])
                elif path == '/api/stop':
                    result = desk.runtime(data['session']).interrupt()
                else:
                    return self.reply({'error': 'Not found'}, 404)
                self.reply(result)
            except (DraftConflict, FollowupConflict) as error:
                self.reply({'error': str(error), 'current': error.current}, 409)
            except FollowupDispatchError as error:
                self.reply({'error': str(error), **error.snapshot}, 400)
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
    executable = os.path.abspath(executable)
    # npm can leave an executable shim without Node or its native dependency.
    # Check the actual launcher before creating Desk state or opening its UI.
    try:
        checked = subprocess.run([executable, '--version'], timeout=10,
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        reason = '--version timed out after 10 seconds'
    except OSError:
        reason = '--version could not run'
    else:
        if checked.returncode == 0:
            return executable
        reason = f'--version exited with status {checked.returncode}'
    command = ("& '" + executable.replace("'", "''") + "' --version" if os.name == 'nt'
               else shlex.quote(executable) + ' --version')
    raise ValueError(f'Codex launcher check failed ({reason}). '
                     f'Run {command} in the same shell to see its native diagnostic. '
                     'Complete or repair that Codex CLI installation, or pass --codex /path/to/codex')


def port_number(value):
    try:
        port = int(value)
    except ValueError:
        raise argparse.ArgumentTypeError('Use port 0 or an integer from 1 to 65535') from None
    if not 0 <= port <= 65535:
        raise argparse.ArgumentTypeError('Use port 0 or an integer from 1 to 65535')
    return port


def main():
    parser = argparse.ArgumentParser(description="Open your daily native Codex project workbench")
    parser.add_argument('--version', action='version', version=__version__,
                        help='Show the Codex Desk version and exit')
    parser.add_argument('--codex', default='codex',
                        help='Codex executable name or path (relative to this launch directory)')
    parser.add_argument('--codex-home', default=os.environ.get('CODEX_HOME', str(Path.home() / '.codex')))
    parser.add_argument('--state-dir', default=str(Path.home() / '.local' / 'state' / 'codex-desk'))
    parser.add_argument('--port', type=port_number, default=8787,
                        help='Loopback port (default: 8787; 0 chooses an available port)')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    try:
        args.codex = resolve_codex(args.codex)
    except ValueError as error:
        parser.error(str(error))
    # Reserve the listener before creating or migrating any Desk state. No
    # requests are handled until the initialized Desk handler is installed.
    try:
        server = LoopbackHTTPServer(('127.0.0.1', args.port), BaseHTTPRequestHandler)
    except OSError as error:
        url = f'http://127.0.0.1:{args.port}'
        alternate = 8788 if args.port != 8788 else 8787
        if error.errno in (errno.EADDRINUSE, 10048):
            parser.error(f'{url} is already in use. If Codex Desk is already running, '
                         f'use the complete printed URL from its existing terminal; otherwise choose another port '
                         f'with --port {alternate}')
        parser.error(f'Could not listen on {url}: {error.strerror or error}. '
                     f'Choose another port with --port {alternate}')
    desk = None
    previous_signals = {}
    try:
        desk = Desk(args.codex, args.codex_home, args.state_dir)
        access_token = secrets.token_urlsafe(32)
        server.RequestHandlerClass = handler(desk, access_token=access_token)
        url = f'http://127.0.0.1:{server.server_port}#access={access_token}'
        print('Codex Desk: ' + url, flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        def stop(*_):
            threading.Thread(target=server.shutdown, daemon=True).start()
        for signum in (signal.SIGTERM, signal.SIGINT):
            previous_signals[signum] = signal.signal(signum, stop)
        server.serve_forever()
    finally:
        try:
            for signum, previous in previous_signals.items():
                signal.signal(signum, previous)
        finally:
            try:
                server.server_close()
            finally:
                if desk is not None:
                    try:
                        desk.close()
                    finally:
                        desk.store.db.close()

if __name__ == '__main__':
    main()
