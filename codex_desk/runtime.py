"""Native app-server transport; never rewrite Codex config/auth or rollouts."""
import json
import os
from pathlib import Path
import queue
import re
import sqlite3
import subprocess
import tempfile
import threading
import time
import tomllib
import uuid
from datetime import datetime
from urllib.parse import urlsplit, urlunsplit
from . import __version__, recall


NAME_LIMIT = 120
ACTIVE_STATUSES = frozenset(('starting', 'running', 'approval'))
PROFILE_NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,40}')


class NativeRequestRejected(RuntimeError):
    """The native JSON-RPC server returned a definite request rejection."""


class NativeRequestUnknown(RuntimeError):
    """Transport loss left native request admission unconfirmed."""


def _public_endpoint(endpoint):
    """Display host/path only; an unrelated malformed profile stays listable."""
    if not isinstance(endpoint, str):
        return ''
    try:
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ''
        if parsed.scheme not in ('http', 'https') or not host:
            return ''
        if ':' in host:
            host = '[' + host + ']'
        if parsed.port is not None:
            host += ':' + str(parsed.port)
        return urlunsplit((parsed.scheme, host, parsed.path, '', ''))
    except ValueError:
        return ''


def _profile_values(endpoint, model, key, require_key=True):
    if not all(isinstance(v, str) for v in (endpoint, model, key)):
        raise ValueError('Enter an API base URL, model and key as text')
    endpoint, model, key = endpoint.strip().rstrip('/'), model.strip(), key.strip()
    try:
        url = urlsplit(endpoint)
        port = url.port
        if (url.scheme not in ('http', 'https') or not url.hostname
                or (port is not None and port == 0)
                or any(c.isspace() or ord(c) < 32 for c in endpoint)):
            raise ValueError
    except ValueError:
        raise ValueError('Enter the full HTTP(S) API base URL') from None
    if url.username is not None or url.password is not None or '?' in endpoint or '#' in endpoint:
        raise ValueError('Use a base URL without credentials, query or fragment; enter the key separately')
    if not model or (require_key and not key):
        raise ValueError('Enter a model and your existing API key')
    try:
        for value in (endpoint, model, key):
            value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('Use valid Unicode text for the API provider') from None
    return endpoint, model, key


def _desk_provider(data):
    """Only the provider-only shape written by Add API provider is editable."""
    if set(data) != {'model', 'model_provider', 'model_providers'} or data['model_provider'] != 'desk_provider':
        return None
    providers = data['model_providers']
    if not isinstance(providers, dict) or set(providers) != {'desk_provider'}:
        return None
    provider = providers['desk_provider']
    if (not isinstance(provider, dict)
            or set(provider) != {'name', 'base_url', 'wire_api', 'experimental_bearer_token'}
            or provider['wire_api'] != 'responses'
            or not isinstance(provider['name'], str) or not PROFILE_NAME.fullmatch(provider['name'])):
        return None
    try:
        _profile_values(provider['base_url'], data['model'], provider['experimental_bearer_token'])
    except ValueError:
        return None
    return provider


def _profile_text(name, endpoint, model, key):
    # Literal Unicode avoids JSON surrogate-pair escapes, which TOML rejects.
    quoted = lambda value: json.dumps(value, ensure_ascii=False)
    return ('model = ' + quoted(model) + '\nmodel_provider = "desk_provider"\n'
            + '[model_providers.desk_provider]\nname = ' + quoted(name)
            + '\nbase_url = ' + quoted(endpoint) + '\nwire_api = "responses"\n'
            + 'experimental_bearer_token = ' + quoted(key) + '\n')


class MissingRolloutError(RuntimeError):
    """A saved binding must survive missing native history."""


def session_name(value):
    if not isinstance(value, str):
        raise ValueError("Enter a session name")
    value = ' '.join(value.split())
    if not value or len(value) > NAME_LIMIT:
        raise ValueError(f"Use a session name of 1–{NAME_LIMIT} characters")
    return value


def task_name(text):
    """A useful local title, without sending a separate inference request."""
    return ' '.join(text.split())[:NAME_LIMIT].rstrip()


def default_name(cwd, created, identifier):
    project = Path(cwd).name or str(cwd)
    stamp = datetime.fromtimestamp(created).strftime('%b %d, %H:%M')
    return f"{project[:80]} · {stamp} · {identifier[:6]}"


def first_task(turns):
    for turn in turns:
        for item in turn.get('items', []):
            if item.get('type') == 'userMessage':
                title = task_name(' '.join(c.get('text', '') for c in item.get('content', [])))
                if title:
                    return title
    return ''


def _thread_scope(params):
    if not isinstance(params, dict):
        return None
    thread_id = params.get('threadId')
    if isinstance(thread_id, str) and thread_id:
        return thread_id
    thread = params.get('thread')
    return thread.get('id') if isinstance(thread, dict) and isinstance(thread.get('id'), str) else None


def profiles(home):
    home = Path(home)
    result = [{"id": "default", "name": "Current Codex settings", "editable": False}]
    for path in [home / "config.toml", *sorted(home.glob("*.config.toml"))]:
        if not path.is_file():
            continue
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        native_name = path.name.removesuffix(".config.toml")
        identifier = "default" if path.name == "config.toml" else "sidecar:" + native_name
        provider = data.get("model_provider", "openai")
        provider = provider if isinstance(provider, str) else ''
        providers = data.get('model_providers', {})
        settings = providers.get(provider, {}) if isinstance(providers, dict) else {}
        endpoint = _public_endpoint(settings.get('base_url', '') if isinstance(settings, dict) else '')
        model = data.get('model', '')
        row = {"id": identifier, "name": native_name if identifier != "default" else "Current Codex settings",
               "legacy_id": native_name if identifier != "default" else "default",
               "model": model if isinstance(model, str) else '', "provider": provider, "endpoint": endpoint,
               "editable": (identifier != 'default' and not path.is_symlink()
                            and bool(PROFILE_NAME.fullmatch(native_name)) and _desk_provider(data) is not None)}
        if identifier == "default":
            result[0] = row
        else:
            result.append(row)
    return result


def profile_config(home, profile):
    if profile == "default":
        return None
    row = next((row for row in profiles(home)
        if row['id'] == profile or row.get('legacy_id') == profile), None)
    if not row or row['id'] == 'default':
        raise ValueError("Choose an existing Codex profile")
    data = tomllib.loads((Path(home) / (row['legacy_id'] + ".config.toml")).read_text(encoding="utf-8-sig"))
    return {k: v for k, v in data.items() if k in (
        "model", "model_provider", "model_reasoning_effort", "model_providers", "model_catalog_json")}


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if not path.exists():
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(fd)
        os.chmod(path, 0o600)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.db:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(
              id TEXT PRIMARY KEY, cwd TEXT NOT NULL, profile TEXT NOT NULL,
              thread_id TEXT, model TEXT, provider TEXT, status TEXT,
              created REAL, updated REAL, usage TEXT, error TEXT,
              name TEXT, name_source TEXT NOT NULL DEFAULT 'default',
              name_pending INTEGER NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'native',
              thread_saved INTEGER NOT NULL DEFAULT 0,
              archived INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            columns = {r[1] for r in self.db.execute('PRAGMA table_info(sessions)')}
            for column, definition in (
                ('name', 'TEXT'), ('name_source', "TEXT NOT NULL DEFAULT 'default'"),
                ('name_pending', 'INTEGER NOT NULL DEFAULT 0'),
                ('mode', "TEXT NOT NULL DEFAULT 'native'"),
                ('thread_saved', 'INTEGER NOT NULL DEFAULT 0'),
                ('archived', 'INTEGER NOT NULL DEFAULT 0')):
                if column not in columns:
                    self.db.execute(f'ALTER TABLE sessions ADD COLUMN {column} {definition}')
            if 'thread_saved' not in columns:
                # Older bindings do not distinguish imported history from a
                # never-used blank. Preserve them rather than guess and replace.
                self.db.execute('UPDATE sessions SET thread_saved=1 WHERE thread_id IS NOT NULL')
            # Backfill in place: keep IDs, binding, event sequence, and list order.
            for identifier, cwd, created in self.db.execute(
                    "SELECT id,cwd,created FROM sessions WHERE name IS NULL OR trim(name)='' ").fetchall():
                items = [e['event'].get('params', {}).get('item', {}) for e in self.events(identifier)]
                title = first_task([{'items': items}])
                self.db.execute('UPDATE sessions SET name=?,name_source=?,name_pending=? WHERE id=?',
                    (title or default_name(cwd, created or 0, identifier),
                     'task' if title else 'default', int(bool(title)), identifier))
            recall.initialize(self)
    def create(self, cwd, profile, identifier=None, name=None):
        identifier = identifier or uuid.uuid4().hex
        now = time.time()
        title = session_name(name) if name is not None else default_name(cwd, now, identifier)
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions(id,cwd,profile,status,created,updated,name,name_source,name_pending) VALUES(?,?,?,?,?,?,?,?,?)",
                            (identifier, cwd, profile, "starting", now, now, title,
                             'user' if name is not None else 'default', int(name is not None)))
        return identifier
    def update(self, identifier, **fields):
        if not fields:
            return
        fields['updated'] = time.time()
        with self.lock, self.db:
            self.db.execute("UPDATE sessions SET " + ','.join(k + '=?' for k in fields) + ' WHERE id=?',
                            [*fields.values(), identifier])
    def event(self, identifier, payload):
        with self.lock, self.db:
            cursor = self.db.execute("INSERT INTO events(session_id,payload) VALUES(?,?)", (identifier, json.dumps(payload)))
            recall.record_event(self, identifier, payload, cursor.lastrowid)
    def recall_snapshot(self, identifier, thread):
        with self.lock, self.db:
            recall.save_snapshot(self, identifier, thread)
    def recall(self, q, cwd=None, include_archived=False, limit=30, offset=0):
        return recall.search(self, q, cwd, include_archived, limit, offset)
    def events(self, identifier, after=0):
        with self.lock:
            return [{"seq": r[0], "event": json.loads(r[1])} for r in self.db.execute(
                "SELECT seq,payload FROM events WHERE session_id=? AND seq>? ORDER BY seq", (identifier, after))]
    def sessions(self):
        with self.lock:
            cursor = self.db.execute("SELECT * FROM sessions ORDER BY updated DESC")
            keys = [c[0] for c in cursor.description]
            rows = [dict(zip(keys, row)) for row in cursor]
            for row in rows:
                row['archived'] = bool(row['archived'])
            return rows
    def get(self, identifier):
        return next((r for r in self.sessions() if r['id'] == identifier), None)
    def archive(self, identifier, archived):
        """Change local visibility only; preserve activity time and native binding."""
        if not isinstance(identifier, str) or not identifier or identifier == 'native-catalog':
            raise ValueError('Select an existing project session')
        if type(archived) is not bool:
            raise ValueError('Choose archive or unarchive with a boolean value')
        with self.lock, self.db:
            if self.db.execute('SELECT 1 FROM sessions WHERE id=?', (identifier,)).fetchone() is None:
                raise ValueError('Session not found')
            self.db.execute('UPDATE sessions SET archived=? WHERE id=?', (int(archived), identifier))
        return {'id': identifier, 'archived': archived}
    @staticmethod
    def _canonical_cwd(cwd):
        if not isinstance(cwd, (str, os.PathLike)) or not str(cwd).strip():
            raise ValueError('Choose a project folder')
        return os.path.normcase(str(Path(cwd).expanduser().resolve()))
    def organized_sessions(self, cwd=None, title='', include_archived=False):
        """Canonical project groups; active work never disappears behind archive."""
        if not isinstance(title, str) or type(include_archived) is not bool:
            raise ValueError('Use title text and a boolean archived option')
        scoped = self._canonical_cwd(cwd) if cwd is not None else None
        title = title.strip().casefold()
        groups = {}
        for row in self.sessions():
            if row['id'] == 'native-catalog' or (title and title not in (row['name'] or '').casefold()):
                continue
            active = row['status'] in ACTIVE_STATUSES
            if row['archived'] and not active and not include_archived:
                continue
            project = self._canonical_cwd(row['cwd'])
            if scoped is not None and project != scoped:
                continue
            group = groups.setdefault(project, {'cwd': project, 'name': Path(project).name or project,
                                                'active': [], 'recent': [], 'archived': []})
            section = 'active' if active else 'archived' if row['archived'] else 'recent'
            group[section].append(row)
        recent_key = lambda row: (-(row['updated'] or 0), row['id'])
        for group in groups.values():
            group['active'].sort(key=lambda row: (row['status'] != 'approval', *recent_key(row)))
            group['recent'].sort(key=recent_key)
            group['archived'].sort(key=recent_key)
        return sorted(groups.values(), key=lambda group: (
            not bool(group['active']),
            -max(row['updated'] or 0 for section in ('active', 'recent', 'archived') for row in group[section]),
            group['cwd']))


class Runtime:
    def __init__(self, store, identifier, binary, home, *, catalog_cwd=None):
        self.store, self.id, self.home = store, identifier, home
        self.pending, self.approvals = {}, {}
        self.lock, self.write_lock = threading.Lock(), threading.Lock()
        self.name_lock = threading.RLock()
        self.lifecycle_lock = threading.Lock()
        self.turn_lock = threading.Lock()
        self.closing = False
        self.persisted = False
        self.counter = 0
        row = store.get(identifier)
        cwd = catalog_cwd if identifier == 'native-catalog' and catalog_cwd is not None else row['cwd']
        env = {**os.environ, "CODEX_HOME": str(home)}
        self.process = subprocess.Popen([binary, "app-server", "--stdio"],
            cwd=cwd, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.stderr_reader = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start()
        self.stderr_reader.start()
        try:
            self.request("initialize", {"clientInfo": {"name": "codex_desk", "title": "Codex Desk", "version": __version__}, "capabilities": {"experimentalApi": True}})
            self.send({"method": "initialized", "params": {}})
        except Exception:
            # A rejected handshake never reaches Desk's runtime registry.
            self.close()
            raise
    def send(self, payload):
        with self.write_lock:
            self.process.stdin.write(json.dumps(payload) + '\n')
            self.process.stdin.flush()
    def request(self, method, params, timeout=30):
        with self.lock:
            self.counter += 1
            number = self.counter
            result = queue.Queue(maxsize=1)
            self.pending[number] = result
        try:
            try:
                self.send({"id": number, "method": method, "params": params})
            except (OSError, ValueError) as error:
                raise NativeRequestUnknown('Native Codex request could not be confirmed; stop Desk and reopen the session') from error
            try:
                message = result.get(timeout=timeout)
            except queue.Empty:
                raise NativeRequestUnknown("Native Codex request timed out; stop Desk and reopen the session") from None
            if 'transport_error' in message:
                raise NativeRequestUnknown(message['transport_error'])
            if 'error' in message:
                error = message['error']
                raise NativeRequestRejected(error.get('message', str(error)) if isinstance(error, dict) else str(error))
            if 'result' not in message:
                raise NativeRequestUnknown('Native Codex reply did not confirm the request')
            return message['result']
        except NativeRequestUnknown as error:
            if getattr(self, 'id', None) == 'native-catalog':
                # A failed reader can remain alive while no longer answering.
                # Retire only this read-only backend. The next explicit read
                # (or remaining scan row) opens a fresh one, without replaying
                # the failed request or touching a project task runtime.
                self.close()
                raise NativeRequestUnknown('Native history reader became unavailable. '
                    'Choose Retry to reopen it.') from error
            raise
        finally:
            with self.lock:
                self.pending.pop(number, None)
    def _read(self):
        try:
            for line in self.process.stdout:
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                with self.lifecycle_lock:
                    if self.closing:
                        break
                    self._message(msg)
        finally:
            with self.lifecycle_lock:
                self._fail_pending()
                if not self.closing:
                    self._mark_exited()
            self.process.stdout.close()
    def _message(self, msg):
        if getattr(self, 'closing', False):
            return
        if 'method' not in msg and 'id' in msg:
            with self.lock:
                target = self.pending.get(msg['id'])
                if target:
                    try:
                        target.put_nowait(msg)
                    except queue.Full:
                        pass
            return
        method, params = msg.get('method'), msg.get('params') or {}
        row = self.store.get(self.id)
        thread_id = _thread_scope(params)
        foreign = bool(row['thread_id'] and thread_id and thread_id != row['thread_id'])
        if foreign and 'id' not in msg:
            if method == 'serverRequest/resolved':
                if str(params.get('requestId')) not in self.approvals:
                    return
            elif method == 'turn/completed':
                # A child finish retires only that child's interactions. It is
                # not a parent turn boundary, usage snapshot, or name flush.
                retired = [key for key, request in self.approvals.items()
                           if _thread_scope(request.get('params')) == thread_id]
                for key in retired:
                    self.approvals.pop(key)
                if retired and not self.approvals and row['status'] == 'approval':
                    self.store.update(self.id, status='running')
                return
            else:
                return
        self.store.event(self.id, msg)
        if 'id' in msg:
            self.approvals[str(msg['id'])] = msg
            # Child requests can still be answered by their original IDs, but
            # late child activity must not reopen a finished parent turn.
            if not foreign or row['status'] in ACTIVE_STATUSES:
                self.store.update(self.id, status="approval")
        elif method == 'serverRequest/resolved':
            resolved = self.approvals.pop(str(params.get('requestId')), None)
            # A response already sent by Desk, or a late notification after
            # completion/stop, must not turn an idle session back into running.
            if resolved and not self.approvals and self.store.get(self.id)['status'] == 'approval':
                self.store.update(self.id, status='running')
        elif method == 'thread/tokenUsage/updated':
            # Native totals are cumulative snapshots, never sum them.
            self.store.update(self.id, usage=json.dumps(params.get('tokenUsage', {})))
        elif method == 'turn/started':
            self.store.update(self.id, status="running", error=None, thread_saved=1)
        elif method == 'turn/completed':
            turn = params.get('turn', {})
            # Completion retires this turn's interactions even when the native
            # serverRequest/resolved notifications have not arrived yet.
            self.approvals.clear()
            self.store.update(self.id, status=turn.get('status', 'completed'),
                              error=json.dumps(turn['error']) if turn.get('error') else None)
            self.persisted = True
            # The reader must stay available for the name/set response.
            threading.Thread(target=self._flush_name, daemon=True).start()
        elif method == 'thread/name/updated' and params.get('threadId') == self.store.get(self.id)['thread_id']:
            name = params.get('threadName')
            row = self.store.get(self.id)
            if name and (not row['name_pending'] or name == row['name']):
                self.store.update(self.id, name=task_name(name), name_source='native', name_pending=0)
    def _fail_pending(self):
        with self.lock:
            for target in self.pending.values():
                try:
                    target.put_nowait({"error": {"message": "Codex app-server exited"},
                                       "transport_error": "Codex app-server exited"})
                except queue.Full:
                    pass
    def _mark_exited(self):
        row = self.store.get(self.id)
        if row['status'] in ('starting', 'running', 'approval'):
            self.store.update(self.id, status="interrupted", error="Codex app-server exited; reopen to resume")
    def _stderr(self):
        try:
            for _ in self.process.stderr:
                if self.closing:
                    break
                # Native diagnostics arrive through typed events.
        finally:
            self.process.stderr.close()
    def attach(self):
        row = self.store.get(self.id)
        config = profile_config(self.home, row['profile'])
        params = {'config': config} if config else {}
        thread_saved = 0
        if row['thread_id']:
            try:
                result = self.request('thread/resume', {'threadId': row['thread_id'], **params})
                self.persisted = True
                thread_saved = 1
            except RuntimeError as error:
                if 'no rollout found' not in str(error):
                    raise
                used = row['thread_saved'] or row['status'] == 'saved' or any(
                    e['event'].get('method') == 'turn/started' for e in self.store.events(self.id))
                if used:
                    raise MissingRolloutError(
                        'Saved Codex conversation unavailable (no rollout found). Restore its history '
                        'or restart Desk with the original --codex-home. To proceed without it, '
                        'choose Start new conversation explicitly.') from None
                # Codex writes its rollout lazily on the first turn. A blank workspace
                # may be reopened with a fresh native thread, never a used conversation.
                result = self.request('thread/start', {'cwd': row['cwd'], **params})
        else:
            result = self.request('thread/start', {'cwd': row['cwd'], **params})
        self.thread_result = result
        thread = result['thread']
        self.store.update(self.id, thread_id=thread['id'], model=result.get('model'),
                          provider=result.get('modelProvider'), status="ready", error=None,
                          thread_saved=thread_saved)
        self.store.recall_snapshot(self.id, thread)
        if row['name_pending']:
            self._flush_name()
        elif thread.get('name'):
            self.store.update(self.id, name=task_name(thread['name']), name_source='native')
        elif row['name_source'] == 'default':
            title = first_task(thread.get('turns', [])) or task_name(thread.get('preview', ''))
            if title:
                self.store.update(self.id, name=title, name_source='task')
        return result
    def _sync_name(self):
        with self.name_lock:
            row = self.store.get(self.id)
            if not self.persisted or not row['name_pending']:
                return
            self.request('thread/name/set', {'threadId': row['thread_id'], 'name': row['name']})
            self.store.update(self.id, name_pending=0)
    def _flush_name(self):
        try:
            self._sync_name()
        except (RuntimeError, OSError, ValueError):
            # The local name remains saved and pending for the next resume.
            pass
    def rename(self, name):
        name = session_name(name)
        with self.name_lock:
            self.store.update(self.id, name=name, name_source='user', name_pending=1)
            self._sync_name()
        return {'name': name, 'namePending': bool(self.store.get(self.id)['name_pending'])}
    def turn(self, text, mode="native"):
        if mode not in ("native", "plan"):
            raise ValueError("Choose Work or Plan mode")
        # One outstanding start per session, including the gap before its
        # native turn/started notification (or after an unusually fast finish).
        if not self.turn_lock.acquire(blocking=False):
            raise ValueError("Finish or stop the current turn first")
        try:
            with self.lifecycle_lock:
                idle = self.store.get(self.id)
                if idle['status'] in ('starting', 'running', 'approval'):
                    raise ValueError("Finish or stop the current turn first")
                if (mode == 'plan' or idle.get('mode') == 'plan') and not idle.get('model'):
                    raise ValueError('Reopen the session to load its native model before choosing Plan')
                self.store.update(self.id, status='starting', error=None)
            try:
                with self.name_lock:
                    row = self.store.get(self.id)
                    if row['name_source'] == 'default':
                        title = task_name(text)
                        if title:
                            self.store.update(self.id, name=title, name_source='task', name_pending=1)
                            self._sync_name()
                params = {'threadId': row['thread_id'], 'input': [{'type': 'text', 'text': text}]}
                if mode == 'plan' or row.get('mode') == 'plan':
                    params['collaborationMode'] = {'mode': 'plan' if mode == 'plan' else 'default',
                        'settings': {'model': row['model'], 'developer_instructions': None}}
                # The native reader needs lifecycle_lock to deliver this reply.
                result = self.request('turn/start', params)
                turn = result.get('turn') if isinstance(result, dict) else None
                if not isinstance(turn, dict) or not isinstance(turn.get('id'), str) or not turn['id']:
                    raise NativeRequestUnknown('Native Codex reply did not confirm the task start; review the session before continuing')
            except Exception as error:
                with self.lifecycle_lock:
                    if self.store.get(self.id)['status'] == 'starting':
                        if isinstance(error, NativeRequestUnknown):
                            self.store.update(self.id, status='interrupted', error=str(error))
                        else:
                            self.store.update(self.id, status=idle['status'], error=idle['error'])
                raise
            with self.lifecycle_lock:
                fields = {'mode': mode, 'thread_saved': 1}
                if self.store.get(self.id)['status'] == 'starting':
                    turn = result.get('turn', {})
                    status = turn.get('status', 'inProgress')
                    fields['status'] = 'running' if status == 'inProgress' else status
                    fields['error'] = json.dumps(turn['error']) if turn.get('error') else None
                self.store.update(self.id, **fields)
            return result
        finally:
            self.turn_lock.release()
    def approve(self, request_id, decision):
        # Native resolved/completed events and another HTTP response cannot
        # interleave between writing a decision and retiring its pending entry.
        with self.lifecycle_lock:
            msg = self.approvals.get(str(request_id))
            if not msg:
                raise ValueError("This request is no longer pending")
            if msg['method'] not in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
                raise ValueError("This native interaction needs a dedicated UI; stop the turn instead")
            if decision not in ('accept', 'decline', 'cancel'):
                raise ValueError("Choose a one-time decision")
            self.send({'id': msg['id'], 'result': {'decision': decision}})
            self.approvals.pop(str(request_id))
            self._interaction_finished(msg)
    def answer(self, request_id, answers):
        with self.lifecycle_lock:
            msg = self.approvals.get(str(request_id))
            if not msg or msg['method'] != 'item/tool/requestUserInput':
                raise ValueError('This question is no longer pending')
            questions = msg['params']['questions']
            result = {}
            for question in questions:
                values = answers.get(question['id'])
                if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v.strip() for v in values):
                    raise ValueError('Answer every question before continuing')
                options = question.get('options') or []
                if options and not question.get('isOther'):
                    labels = {o['label'] for o in options}
                    if any(v not in labels for v in values):
                        raise ValueError('Choose one of the offered answers')
                result[question['id']] = {'answers': values}
            self.send({'id': msg['id'], 'result': {'answers': result}})
            self.approvals.pop(str(request_id))
            self._interaction_finished(msg)
            return {'answered': True}

    def _interaction_finished(self, message):
        thread_id = _thread_scope(message.get('params'))
        if thread_id:
            row = self.store.get(self.id)
            if row['thread_id'] and thread_id != row['thread_id'] and row['status'] not in ACTIVE_STATUSES:
                return
        self.store.update(self.id, status='running' if not self.approvals else 'approval')

    def interrupt(self):
        events = self.store.events(self.id)
        thread_id = self.store.get(self.id)['thread_id']
        turn_id = next((r['event']['params']['turn']['id'] for r in reversed(events)
            if r['event'].get('method') == 'turn/started'
            and (not _thread_scope(r['event'].get('params'))
                 or _thread_scope(r['event'].get('params')) == thread_id)), None)
        if not turn_id:
            raise ValueError("No running turn")
        return self.request('turn/interrupt', {'threadId': thread_id, 'turnId': turn_id})
    def close(self):
        with self.lifecycle_lock:
            if self.closing:
                return
            self.closing = True
            self._mark_exited()
        self._fail_pending()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        self.process.stdin.close()
        # A native command can retain inherited pipes after app-server exits.
        # Retired readers ignore its output and close their own streams at EOF.
        deadline = time.monotonic() + 1
        for reader in (self.reader, self.stderr_reader):
            reader.join(timeout=max(0, deadline - time.monotonic()))


def save_profile(home, name, endpoint, model, key):
    """Create one native provider-only sidecar; keep the key out of responses/argv."""
    if not isinstance(name, str) or not PROFILE_NAME.fullmatch(name.strip()):
        raise ValueError('Profile name: 1–41 letters, numbers, underscores or hyphens')
    name = name.strip()
    endpoint, model, key = _profile_values(endpoint, model, key)
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    text = _profile_text(name, endpoint, model, key)
    path = home / (name + '.config.toml')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('This profile already exists; choose a new name') from None
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(text)
    return {'id':'sidecar:' + name}


def update_profile(home, id, endpoint, model, key=''):
    """Replace an existing Desk sidecar atomically; blank key retains its secret."""
    if (not isinstance(id, str) or not id.startswith('sidecar:')
            or not PROFILE_NAME.fullmatch(id.removeprefix('sidecar:'))):
        raise ValueError('Choose an editable API provider')
    path = Path(home) / (id.removeprefix('sidecar:') + '.config.toml')
    if path.is_symlink():
        raise ValueError('This Codex profile is read-only')
    try:
        data = tomllib.loads(path.read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        raise ValueError('This API provider no longer exists; refresh the provider list') from None
    except ValueError:
        raise ValueError('This Codex profile is read-only') from None
    provider = _desk_provider(data)
    if provider is None:
        raise ValueError('This Codex profile is read-only')
    endpoint, model, key = _profile_values(endpoint, model, key, require_key=False)
    key = key or provider['experimental_bearer_token']
    text = _profile_text(provider['name'], endpoint, model, key)
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '.', suffix='.tmp', dir=path.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as file:
            file.write(text)
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary, 0o600)
        if not path.is_file() or path.is_symlink():
            raise ValueError('This API provider no longer exists; refresh the provider list')
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return {'id': id}
