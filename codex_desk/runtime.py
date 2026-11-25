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
        identifier = "default" if path.name == "config.toml" else path.name.removesuffix(".config.toml")
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
        row = {"id": identifier, "name": identifier if identifier != "default" else "Current Codex settings",
               "model": data.get("model", ""), "provider": provider, "endpoint": endpoint}
        if identifier == "default":
            result[0] = row
        else:
            result.append(row)
    return result


def overrides(home, profile):
    if profile == "default":
        return []
    if profile not in {row['id'] for row in profiles(home)}:
        raise ValueError("Choose an existing Codex profile")
    data = tomllib.loads((Path(home) / (profile + ".config.toml")).read_text(encoding="utf-8-sig"))
    # Provider-only sidecars retain main MCP, trust, sandbox and user preferences.
    allowed = {k: v for k, v in data.items() if k in (
        "model", "model_provider", "model_reasoning_effort", "model_providers", "model_catalog_json")}
    args = []
    def flatten(prefix, value):
        if isinstance(value, dict):
            for k, v in value.items():
                flatten(prefix + "." + k if prefix else k, v)
        else:
            args.extend(["-c", prefix + "=" + json.dumps(value, ensure_ascii=False)])
    for key, value in allowed.items():
        flatten(key, value)
    return args


class Store:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.lock = threading.RLock()
        with self.db:
            self.db.executescript('''
            CREATE TABLE IF NOT EXISTS sessions(
              id TEXT PRIMARY KEY, cwd TEXT NOT NULL, profile TEXT NOT NULL,
              thread_id TEXT, model TEXT, provider TEXT, status TEXT,
              created REAL, updated REAL, usage TEXT, error TEXT);
            CREATE TABLE IF NOT EXISTS events(
              seq INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL, payload TEXT NOT NULL);
            ''')
    def create(self, cwd, profile):
        identifier = uuid.uuid4().hex
        now = time.time()
        with self.lock, self.db:
            self.db.execute("INSERT INTO sessions(id,cwd,profile,status,created,updated) VALUES(?,?,?,?,?,?)",
                            (identifier, cwd, profile, "starting", now, now))
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
        self.store, self.id = store, identifier
        self.pending, self.approvals = {}, {}
        self.lock, self.write_lock = threading.Lock(), threading.Lock()
        self.counter = 0
        row = store.get(identifier)
        env = {**os.environ, "CODEX_HOME": str(home)}
        self.process = subprocess.Popen([binary, "app-server", "--stdio", *overrides(home, row['profile'])],
            cwd=row['cwd'], env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8", bufsize=1)
        threading.Thread(target=self._read, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()
        self.request("initialize", {"clientInfo": {"name": "codex_desk", "title": "Codex Desk", "version": "0.1.0"}})
        self.send({"method": "initialized", "params": {}})
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
            message = result.get(timeout=timeout)
            if 'error' in message:
                raise RuntimeError(message['error'].get('message', str(message['error'])))
            return message['result']
        finally:
            with self.lock:
                self.pending.pop(number, None)
    def _read(self):
        for line in self.process.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            if 'method' not in msg and 'id' in msg:
                with self.lock:
                    target = self.pending.get(msg['id'])
                if target:
                    target.put(msg)
                continue
            self.store.event(self.id, msg)
            method, params = msg.get('method'), msg.get('params', {})
            if 'id' in msg:
                self.approvals[str(msg['id'])] = msg
                self.store.update(self.id, status="approval")
            elif method == 'thread/tokenUsage/updated':
                # Native totals are cumulative snapshots, never sum them.
                self.store.update(self.id, usage=json.dumps(params.get('tokenUsage', {})))
            elif method == 'turn/started':
                self.store.update(self.id, status="running", error=None)
            elif method == 'turn/completed':
                turn = params.get('turn', {})
                self.store.update(self.id, status=turn.get('status', 'completed'),
                                  error=json.dumps(turn['error']) if turn.get('error') else None)
        with self.lock:
            for target in self.pending.values():
                if target.empty():
                    target.put({"error": {"message": "Codex app-server exited"}})
        row = self.store.get(self.id)
        if row['status'] in ('starting', 'running', 'approval'):
            self.store.update(self.id, status="interrupted", error="Codex app-server exited; reopen to resume")
    def _stderr(self):
        for _ in self.process.stderr:
            pass  # Native diagnostics arrive through typed events; don't leak auth-bearing logs.
    def attach(self):
        row = self.store.get(self.id)
        if row['thread_id']:
            try:
                result = self.request('thread/resume', {'threadId': row['thread_id']})
            except RuntimeError as error:
                used = any(e['event'].get('method') == 'turn/started' for e in self.store.events(self.id))
                if 'no rollout found' not in str(error) or used:
                    raise
                # Codex writes its rollout lazily on the first turn. A blank workspace
                # may be reopened with a fresh native thread, never a used conversation.
                result = self.request('thread/start', {'cwd': row['cwd']})
        else:
            result = self.request('thread/start', {'cwd': row['cwd']})
        thread = result['thread']
        self.store.update(self.id, thread_id=thread['id'], model=result.get('model'),
                          provider=result.get('modelProvider'), status="ready")
        return result
    def turn(self, text):
        row = self.store.get(self.id)
        if row['status'] in ('running', 'approval'):
            raise ValueError("Finish or stop the current turn first")
        return self.request('turn/start', {'threadId': row['thread_id'],
            'input': [{'type': 'text', 'text': text}]})
    def approve(self, request_id, decision):
        msg = self.approvals.get(str(request_id))
        if not msg:
            raise ValueError("This request is no longer pending")
        if msg['method'] not in ('item/commandExecution/requestApproval', 'item/fileChange/requestApproval'):
            raise ValueError("This native interaction needs a dedicated UI; stop the turn instead")
        if decision not in ('accept', 'decline', 'cancel'):
            raise ValueError("Choose a one-time decision")
        self.send({'id': msg['id'], 'result': {'decision': decision}})
        self.approvals.pop(str(request_id))
        self.store.update(self.id, status="running")
    def interrupt(self):
        events = self.store.events(self.id)
        turn_id = next((r['event']['params']['turn']['id'] for r in reversed(events)
            if r['event'].get('method') == 'turn/started'), None)
        if not turn_id:
            raise ValueError("No running turn")
        return self.request('turn/interrupt', {'threadId': self.store.get(self.id)['thread_id'], 'turnId': turn_id})
    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
