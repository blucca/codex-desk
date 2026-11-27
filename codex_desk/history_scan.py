"""Explicit persisted native-history continuation; indexing never sends a task."""
import copy
import json
import os
from pathlib import Path
import threading
import time


class NativeHistoryScanner:
    """One launch-owned scanner; no worker or native request starts on reopen."""

    def __init__(self, desk, index):
        self.desk, self.index = desk, index
        self.store = index.store
        self.native_home = os.path.normcase(str(Path(desk.home).expanduser().resolve()))
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.worker = None
        self._reading = None
        with self.store.lock, self.store.db:
            self.store.db.execute('''CREATE TABLE IF NOT EXISTS native_history_scan_state(
                native_home TEXT PRIMARY KEY NOT NULL,
                continuation TEXT, job TEXT,
                failed_rows TEXT NOT NULL DEFAULT '[]', updated REAL NOT NULL)''')

    @staticmethod
    def _checkpoint():
        return {'cursor': None, 'pending': [], 'next_cursor': None, 'exhausted': False}

    def _load(self):
        with self.store.lock:
            row = self.store.db.execute('''SELECT continuation,job,failed_rows
                FROM native_history_scan_state WHERE native_home=?''', (self.native_home,)).fetchone()
        if row is None:
            return {'continuation': None, 'job': None, 'failed_rows': []}
        return dict(zip(('continuation', 'job', 'failed_rows'),
                        (json.loads(value) if value is not None else None for value in row)))

    def _save(self, state):
        with self.lock, self.store.lock, self.store.db:
            self.store.db.execute('''INSERT INTO native_history_scan_state
                (native_home,continuation,job,failed_rows,updated) VALUES(?,?,?,?,?)
                ON CONFLICT(native_home) DO UPDATE SET continuation=excluded.continuation,
                job=excluded.job,failed_rows=excluded.failed_rows,updated=excluded.updated''',
                (self.native_home,
                 json.dumps(state['continuation'], ensure_ascii=False) if state['continuation'] is not None else None,
                 json.dumps(state['job'], ensure_ascii=False) if state['job'] is not None else None,
                 json.dumps(state['failed_rows'], ensure_ascii=False), time.time()))

    @staticmethod
    def _unfinished(job):
        return (job is not None and job['status'] in ('running', 'paused', 'cancelled', 'failed')
                and job['seen'] < job['limit'] and not job['checkpoint']['exhausted'])

    def status(self):
        with self.lock:
            state = self._load()
            job, continuation = state['job'], state['continuation']
            if job is None:
                result = {'status': 'idle', 'mode': 'recent', 'seen': 0, 'indexed': 0,
                          'skipped': 0, 'failed': 0, 'limit': 200, 'has_more': False}
            else:
                result = {key: job[key] for key in ('status', 'mode', 'seen', 'indexed', 'skipped', 'failed', 'limit')}
                if result['status'] == 'running' and not (self.worker and self.worker.is_alive()):
                    result['status'] = 'paused'
                if result['status'] == 'running' and self._reading is not None:
                    result['seen'] = max(result['seen'], min(job['limit'], self._reading + 1))
                result['has_more'] = not job['checkpoint']['exhausted']
                if job.get('error'):
                    result['error'] = job['error']
            result.update(native_home=self.native_home,
                          older_available=continuation is not None and not continuation['exhausted'],
                          resumable=self._unfinished(job), retryable_failures=len(state['failed_rows']))
            return result

    def start(self, limit=200, *, op='recent'):
        mode = op
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError('Choose between 1 and 1000 saved conversations')
        if mode not in ('recent', 'older', 'retry'):
            raise ValueError('Choose recent refresh, older continuation or explicit retry')
        with self.lock:
            if self.worker and self.worker.is_alive():
                return self.status()
            state = self._load()
            previous = state['job']
            continued = (self._unfinished(previous) and
                         (mode == 'retry' or (mode == 'older' and previous['mode'] == 'older')))
            if continued:
                job = previous
            else:
                if mode == 'older':
                    checkpoint = state['continuation']
                    if checkpoint is None:
                        raise ValueError('Complete the initial recent pass before indexing older conversations')
                    if checkpoint['exhausted']:
                        raise ValueError('The retained continuation has reached the end; refresh recent history separately')
                    checkpoint = copy.deepcopy(checkpoint)
                elif mode == 'retry':
                    if not state['failed_rows']:
                        raise ValueError('No failed history reads remain to retry')
                    checkpoint = self._checkpoint()
                    checkpoint['pending'] = copy.deepcopy(state['failed_rows'][:limit])
                else:
                    checkpoint = self._checkpoint()
                job = {'status': 'running', 'mode': mode, 'limit': limit,
                       'seen': 0, 'indexed': 0, 'skipped': 0, 'failed': 0,
                       'checkpoint': checkpoint, 'visited_cursors': []}
            job['status'] = 'running'
            job.pop('error', None)
            state['job'] = job
            self.cancelled.clear()
            self._save(state)
            self.worker = threading.Thread(target=self._run, args=(state,), daemon=True)
            self.worker.start()
            return self.status()

    def cancel(self):
        self.cancelled.set()
        return self.status()

    def close(self):
        self.cancelled.set()
        worker = self.worker
        if worker and worker is not threading.current_thread():
            worker.join()

    def _page(self, state):
        job = state['job']
        checkpoint = job['checkpoint']
        cursor = checkpoint['cursor']
        options = {'limit': min(30, job['limit'] - job['seen']),
                   'modelProviders': [], 'sortKey': 'updated_at'}
        if cursor:
            options['cursor'] = cursor
        page = self.desk.catalog().request('thread/list', options)
        rows = page.get('data', [])
        if not isinstance(rows, list):
            raise ValueError('Native history listing unavailable')
        next_cursor = page.get('nextCursor') or None
        if next_cursor is not None and not isinstance(next_cursor, str):
            raise ValueError('Native history returned an invalid page cursor')
        if next_cursor and (next_cursor == cursor or next_cursor in job['visited_cursors']):
            raise ValueError('Native history repeated a page cursor')
        if next_cursor:
            job['visited_cursors'].append(next_cursor)
        # The list response, including every unread row, is durable BEFORE the
        # first thread/read. A cancellation during listing keeps the whole page.
        checkpoint['pending'] = [dict(row) if isinstance(row, dict) else row for row in rows]
        for row in checkpoint['pending']:
            if isinstance(row, dict):
                row.pop('turns', None)
        checkpoint['next_cursor'] = next_cursor
        if not rows:
            checkpoint['cursor'] = next_cursor
            checkpoint['next_cursor'] = None
            checkpoint['exhausted'] = next_cursor is None
        if job['mode'] == 'older':
            state['continuation'] = copy.deepcopy(checkpoint)
        self._save(state)

    def _read(self, meta):
        if not isinstance(meta, dict) or not isinstance(meta.get('id'), str):
            raise ValueError('Native conversation metadata unavailable')
        if not self.index.needs_snapshot(meta):
            self.index.catch_up_bindings(meta['id'])
            return 'skipped'
        thread = self.desk.history(meta['id'])
        if (not isinstance(thread, dict) or thread.get('id') != meta['id']
                or not isinstance(thread.get('turns'), list)):
            raise ValueError('Native history read returned a different conversation')
        snapshot = dict(thread)
        for key, value in meta.items():
            if key != 'turns' and snapshot.get(key) in (None, ''):
                snapshot[key] = value
        # These commits are per conversation, not held until the whole pass.
        self.index.replace_snapshot(snapshot)
        self.index.catch_up_bindings(meta['id'])
        return 'indexed'

    def _row(self, state):
        with self.lock:
            self._reading = state['job']['seen']
        try:
            self._process_row(state)
        finally:
            with self.lock:
                self._reading = None

    def _process_row(self, state):
        job = state['job']
        checkpoint = job['checkpoint']
        meta = checkpoint['pending'][0]
        try:
            field = self._read(meta)
        except Exception:
            field = 'failed'
            if isinstance(meta, dict) and isinstance(meta.get('id'), str):
                state['failed_rows'] = [row for row in state['failed_rows'] if row.get('id') != meta['id']]
                state['failed_rows'].append(meta)
        else:
            if isinstance(meta, dict):
                state['failed_rows'] = [row for row in state['failed_rows'] if row.get('id') != meta['id']]
        # Cache/catch-up have committed before this metadata checkpoint moves.
        # If the process stops before this commit, replay is an unchanged skip.
        checkpoint['pending'].pop(0)
        job['seen'] += 1
        job[field] += 1
        if not checkpoint['pending']:
            checkpoint['cursor'] = checkpoint['next_cursor']
            checkpoint['next_cursor'] = None
            checkpoint['exhausted'] = checkpoint['cursor'] is None
        if job['mode'] == 'older':
            state['continuation'] = copy.deepcopy(checkpoint)
        self._save(state)

    def _run(self, state):
        job = state['job']
        pages = 0
        try:
            while job['seen'] < job['limit'] and not job['checkpoint']['exhausted']:
                if self.cancelled.is_set():
                    break
                if not job['checkpoint']['pending']:
                    if pages >= job['limit']:
                        raise ValueError('Native history page budget reached; explicit Retry keeps the checkpoint')
                    pages += 1
                    self._page(state)
                    if self.cancelled.is_set():
                        break
                    if not job['checkpoint']['pending']:
                        continue
                # Finish this one in-flight read/cache commit, then stop before
                # the next row. Pending page rows never advance on cancellation.
                self._row(state)
            completed = job['seen'] >= job['limit'] or job['checkpoint']['exhausted']
            job['status'] = 'completed' if completed else 'cancelled' if self.cancelled.is_set() else 'completed'
            if (job['mode'] == 'recent' and job['status'] == 'completed' and
                    (state['continuation'] is None or state['continuation']['exhausted'])):
                # An unfinished older boundary is never rewound by refresh.
                # Once exhausted, explicit refresh can re-arm older discovery
                # for histories newly restored beyond the current recent edge.
                state['continuation'] = copy.deepcopy(job['checkpoint'])
        except Exception as error:
            if self.cancelled.is_set():
                job['status'] = 'cancelled'
                job.pop('error', None)
            else:
                job['status'] = 'failed'
                job['error'] = str(error)
        self._save(state)
