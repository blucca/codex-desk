"""Explicit, resumable local indexing of native history; never resumes a task."""
import threading


class NativeHistoryScanner:
    def __init__(self, desk, index):
        self.desk, self.index = desk, index
        self.lock = threading.RLock()
        self.cancelled = threading.Event()
        self.worker = None
        self.state = {'status': 'idle', 'seen': 0, 'indexed': 0, 'skipped': 0,
                      'failed': 0, 'limit': 200, 'has_more': False}

    def status(self):
        with self.lock:
            return dict(self.state)

    def start(self, limit=200):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 1000:
            raise ValueError('Choose between 1 and 1000 saved conversations')
        with self.lock:
            if self.worker and self.worker.is_alive():
                return self.status()
            self.cancelled.clear()
            self.state = {'status': 'running', 'seen': 0, 'indexed': 0, 'skipped': 0,
                          'failed': 0, 'limit': limit, 'has_more': False}
            self.worker = threading.Thread(target=self._run, args=(limit,), daemon=True)
            self.worker.start()
            return self.status()

    def cancel(self):
        self.cancelled.set()
        return self.status()

    def close(self):
        self.cancelled.set()
        worker = self.worker
        if worker and worker is not threading.current_thread():
            # Native requests have a bounded timeout. Finish this reader before
            # its caller releases the SQLite connection or native runtimes.
            worker.join()

    def _add(self, field):
        with self.lock:
            self.state[field] += 1

    def _run(self, limit):
        cursor = None
        cursors = set()
        try:
            while not self.cancelled.is_set():
                remaining = limit - self.status()['seen']
                if remaining <= 0:
                    break
                options = {'limit': min(30, remaining), 'modelProviders': [], 'sortKey': 'updated_at'}
                if cursor:
                    options['cursor'] = cursor
                page = self.desk.catalog().request('thread/list', options)
                rows = page.get('data', [])
                if not isinstance(rows, list):
                    raise ValueError('Native history listing unavailable')
                for meta in rows[:remaining]:
                    if self.cancelled.is_set():
                        break
                    self._add('seen')
                    if not isinstance(meta, dict) or not isinstance(meta.get('id'), str):
                        self._add('failed')
                        continue
                    try:
                        if not self.index.needs_snapshot(meta):
                            self._add('skipped')
                            continue
                        thread = self.desk.history(meta['id'])
                        if self.cancelled.is_set():
                            break
                        if (not isinstance(thread, dict) or thread.get('id') != meta['id']
                                or not isinstance(thread.get('turns'), list)):
                            raise ValueError('Native history read returned a different conversation')
                        # Fill metadata omitted by some reads, but never label a
                        # full read with a different list snapshot's timestamp.
                        # History can change between these two native requests.
                        snapshot = dict(thread)
                        for key, value in meta.items():
                            if key != 'turns' and snapshot.get(key) in (None, ''):
                                snapshot[key] = value
                        self.index.replace_snapshot(snapshot)
                        self._add('indexed')
                    except Exception:
                        if self.cancelled.is_set():
                            break
                        self._add('failed')
                next_cursor = page.get('nextCursor')
                with self.lock:
                    self.state['has_more'] = bool(next_cursor or len(rows) > remaining)
                if not next_cursor or self.cancelled.is_set() or self.status()['seen'] >= limit:
                    break
                if next_cursor in cursors:
                    raise ValueError('Native history repeated a page cursor')
                cursors.add(next_cursor)
                cursor = next_cursor
            with self.lock:
                self.state['status'] = 'cancelled' if self.cancelled.is_set() else 'completed'
        except Exception:
            with self.lock:
                if self.cancelled.is_set():
                    self.state['status'] = 'cancelled'
                else:
                    self.state['status'] = 'failed'
                    self.state['error'] = 'Native history could not be listed. Retry when Codex is available.'
