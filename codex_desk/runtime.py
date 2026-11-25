"""Native app-server transport; never rewrite Codex config/auth or rollouts."""
import json
import os
from pathlib import Path
import queue
import sqlite3
import subprocess
import threading
import time
import tomllib
import uuid
from datetime import datetime


NAME_LIMIT = 120


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


def profiles(home):
    home = Path(home)
    result = [{"id": "default", "name": "Current Codex settings"}]
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
        endpoint = data.get("model_providers", {}).get(provider, {}).get("base_url", "")
        # Endpoint credentials/query strings never leave the process.
        from urllib.parse import urlsplit, urlunsplit
        parsed = urlsplit(endpoint)
        host = parsed.hostname or ""
        if ':' in host:
            host = '[' + host + ']'
        if parsed.port:
            host += ':' + str(parsed.port)
        endpoint = urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        row = {"id": identifier, "name": native_name if identifier != "default" else "Current Codex settings",
               "legacy_id": native_name if identifier != "default" else "default",
               "model": data.get("model", ""), "provider": provider, "endpoint": endpoint}
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
              thread_saved INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
            columns = {r[1] for r in self.db.execute('PRAGMA table_info(sessions)')}
            for column, definition in (
                ('name', 'TEXT'), ('name_source', "TEXT NOT NULL DEFAULT 'default'"),
                ('name_pending', 'INTEGER NOT NULL DEFAULT 0'),
                ('mode', "TEXT NOT NULL DEFAULT 'native'"),
                ('thread_saved', 'INTEGER NOT NULL DEFAULT 0')):
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
            self.db.execute("INSERT INTO events(session_id,payload) VALUES(?,?)", (identifier, json.dumps(payload)))
    def events(self, identifier, after=0):
        with self.lock:
            return [{"seq": r[0], "event": json.loads(r[1])} for r in self.db.execute(
                "SELECT seq,payload FROM events WHERE session_id=? AND seq>? ORDER BY seq", (identifier, after))]
    def sessions(self):
        with self.lock:
            cursor = self.db.execute("SELECT * FROM sessions ORDER BY updated DESC")
            keys = [c[0] for c in cursor.description]
            return [dict(zip(keys, row)) for row in cursor]
    def get(self, identifier):
        return next((r for r in self.sessions() if r['id'] == identifier), None)


class Runtime:
    def __init__(self, store, identifier, binary, home):
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
        env = {**os.environ, "CODEX_HOME": str(home)}
        self.process = subprocess.Popen([binary, "app-server", "--stdio"],
            cwd=row['cwd'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.stderr_reader = threading.Thread(target=self._stderr, daemon=True)
        self.reader.start()
        self.stderr_reader.start()
        try:
            self.request("initialize", {"clientInfo": {"name": "codex_desk", "title": "Codex Desk", "version": "0.1.0a11"}, "capabilities": {"experimentalApi": True}})
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
            self.send({"id": number, "method": method, "params": params})
            try:
                message = result.get(timeout=timeout)
            except queue.Empty:
                raise RuntimeError("Native Codex request timed out; stop Desk and reopen the session") from None
            if 'error' in message:
                raise RuntimeError(message['error'].get('message', str(message['error'])))
            return message['result']
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
        if 'method' not in msg and 'id' in msg:
            with self.lock:
                target = self.pending.get(msg['id'])
                if target:
                    try:
                        target.put_nowait(msg)
                    except queue.Full:
                        pass
            return
        self.store.event(self.id, msg)
        method, params = msg.get('method'), msg.get('params', {})
        if 'id' in msg:
            self.approvals[str(msg['id'])] = msg
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
                    target.put_nowait({"error": {"message": "Codex app-server exited"}})
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
            except Exception:
                with self.lifecycle_lock:
                    if self.store.get(self.id)['status'] == 'starting':
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
            self.store.update(self.id, status='running' if not self.approvals else 'approval')
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
            self.store.update(self.id, status='running' if not self.approvals else 'approval')
            return {'answered': True}

    def interrupt(self):
        events = self.store.events(self.id)
        turn_id = next((r['event']['params']['turn']['id'] for r in reversed(events)
            if r['event'].get('method') == 'turn/started'), None)
        if not turn_id:
            raise ValueError("No running turn")
        return self.request('turn/interrupt', {'threadId': self.store.get(self.id)['thread_id'], 'turnId': turn_id})
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
    import re
    from urllib.parse import urlsplit
    name, endpoint, model, key = name.strip(), endpoint.strip().rstrip('/'), model.strip(), key.strip()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,40}', name):
        raise ValueError('Profile name: 1–41 letters, numbers, underscores or hyphens')
    url = urlsplit(endpoint)
    if url.scheme not in ('http','https') or not url.hostname:
        raise ValueError('Enter the full HTTP(S) API base URL')
    if not model or not key:
        raise ValueError('Enter a model and your existing API key')
    home = Path(home)
    home.mkdir(parents=True, exist_ok=True)
    text = ('model = ' + json.dumps(model) + '\nmodel_provider = "desk_provider"\n'
            + '[model_providers.desk_provider]\nname = ' + json.dumps(name)
            + '\nbase_url = ' + json.dumps(endpoint) + '\nwire_api = "responses"\n'
            + 'experimental_bearer_token = ' + json.dumps(key) + '\n')
    path = home / (name + '.config.toml')
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        raise ValueError('This profile already exists; choose a new name') from None
    with os.fdopen(fd, 'w', encoding='utf-8') as file:
        file.write(text)
    return {'id':'sidecar:' + name}
