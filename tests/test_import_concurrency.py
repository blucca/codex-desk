"""Two browser windows must share one stopped-thread/profile binding."""
from concurrent.futures import ThreadPoolExecutor
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock

from codex_desk.server import Desk, ThreadingHTTPServer, handler

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class ImportConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-import-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.project = self.root / 'project with spaces'
        self.project.mkdir()
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.thread = {'id': 'stopped-native-thread', 'cwd': str(self.project),
                       'name': 'Saved verification', 'turns': []}
        self.desk.history = Mock(return_value=self.thread)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def post(self):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', '/api/import', json.dumps({
                'thread': self.thread['id'], 'profile': 'default'}),
                {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_concurrent_browser_imports_commit_one_complete_binding(self):
        first_create = threading.Event()
        release_create = threading.Event()
        second_history = threading.Event()
        second_lookup = threading.Event()
        second_reader = None
        original_sessions = self.desk.store.sessions
        self.addCleanup(release_create.set)
        native_read = self.desk.history
        history_count = 0
        counter_lock = threading.Lock()

        def history(identifier):
            nonlocal history_count, second_reader
            with counter_lock:
                history_count += 1
                if history_count == 2:
                    second_reader = threading.get_ident()
                    second_history.set()
            return native_read(identifier)

        def sessions():
            rows = original_sessions()
            if threading.get_ident() == second_reader:
                second_lookup.set()
            return rows

        self.desk.store.sessions = sessions

        def create(*args, **kwargs):
            if not first_create.is_set():
                first_create.set()
                if not release_create.wait(3):
                    raise RuntimeError('Fixture import gate timed out')
            return original_create(*args, **kwargs)

        self.desk.history = history
        original_create = self.desk.store.create
        create_spy = Mock(side_effect=create)
        self.desk.store.create = create_spy
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(self.post)
            self.assertTrue(first_create.wait(3))
            second = pool.submit(self.post)
            try:
                self.assertTrue(second_history.wait(3))
                # The second browser has completed its native read, but the
                # first import has not committed its new local binding yet.
                # Before the repair, this observes the second empty snapshot
                # before releasing the first commit, reliably exposing two IDs.
                # After the repair, the second lookup waits for that commit.
                second_lookup.wait(.15)
            finally:
                release_create.set()
            results = [first.result(timeout=3), second.result(timeout=3)]
        self.assertEqual([status for status, _ in results], [200, 200])
        self.assertEqual(results[0][1]['id'], results[1][1]['id'])
        create_spy.assert_called_once()
        rows = self.desk.store.sessions()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual((row['thread_id'], row['profile'], row['cwd'], row['name'],
                          row['status'], row['thread_saved']),
                         (self.thread['id'], 'default', str(self.project),
                          'Saved verification', 'saved', 1))
        self.assertEqual(self.desk.store.events(row['id']), [])
        self.assertEqual(self.desk.runtimes, {})

    def test_native_history_read_does_not_hold_session_open_lock(self):
        reading = threading.Event()
        release = threading.Event()
        self.addCleanup(release.set)
        identifier = self.desk.store.create(str(self.project), 'default')
        runtime = Mock()
        runtime.process.poll.return_value = None
        runtime.thread_result = {'thread': {'id': 'already-open'}}
        self.desk.runtimes[identifier] = runtime

        def slow_history(thread_id):
            reading.set()
            if not release.wait(3):
                raise RuntimeError('Fixture history gate timed out')
            return self.thread

        self.desk.history = slow_history
        with ThreadPoolExecutor(max_workers=2) as pool:
            imported = pool.submit(self.post)
            self.assertTrue(reading.wait(3))
            try:
                opened = pool.submit(self.desk.open, identifier)
                self.assertEqual(opened.result(timeout=1), runtime.thread_result)
            finally:
                release.set()
            self.assertEqual(imported.result(timeout=3)[0], 200)
        runtime.attach.assert_not_called()


if __name__ == '__main__':
    unittest.main()
