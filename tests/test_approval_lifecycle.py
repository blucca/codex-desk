"""Approval HTTP paths with a controlled native reader; no Codex calls."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from unittest.mock import Mock

from codex_desk.runtime import Runtime
from codex_desk.server import Desk, handler

ROOT = Path(os.environ.get('DESK_TEST_TEMP', Path.cwd() / 'temp'))
ROOT.mkdir(parents=True, exist_ok=True)

class NativeHTTPFixture(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.desk = Desk('unused-fake-native', self.path, self.path / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.identifier = self.desk.store.create(str(self.path), 'default', name='Fixture task')
        self.desk.store.update(self.identifier, thread_id='native-original', status='approval',
                               model='fixture-model', name_pending=0)
        self.runtime = object.__new__(Runtime)
        self.runtime.store, self.runtime.id, self.runtime.home = self.desk.store, self.identifier, self.path
        self.runtime.approvals = {}
        self.runtime.persisted = False
        self.runtime.closing = False
        self.runtime.lifecycle_lock = threading.Lock()
        self.runtime.turn_lock = threading.Lock()
        self.runtime.name_lock = threading.RLock()
        self.runtime.write_lock = threading.Lock()
        self.runtime.process = Mock()
        self.runtime.process.poll.return_value = None
        self.runtime.thread_result = {'thread': {'id': 'native-original', 'turns': []}}
        self.runtime.send = self.send_native
        self.runtime.request = self.native_request
        self.desk.runtimes[self.identifier] = self.runtime
        self.sent, self.requests, self.native_threads, self.native_errors = [], [], [], []
        self.incoming = []
        self.send_error = None
        self.addCleanup(self.join_native)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.addCleanup(self.close_server)

    def close_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)

    def join_native(self):
        for thread in self.native_threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(self.native_errors, [])

    def receive_native(self, events, attempted, completed):
        attempted.set()
        try:
            # Match Runtime._read: notifications share the lifecycle lock.
            for event in events:
                with self.runtime.lifecycle_lock:
                    self.runtime._message(event)
        except Exception as error:
            self.native_errors.append(error)
        finally:
            completed.set()

    def send_native(self, message):
        with self.runtime.write_lock:
            if self.send_error:
                raise self.send_error
            self.sent.append(message)
            if not self.incoming:
                return
            events, self.incoming = self.incoming, []
            attempted, completed = threading.Event(), threading.Event()
            native = threading.Thread(target=self.receive_native, args=(events, attempted, completed), daemon=True)
            self.native_threads.append(native)
            native.start()
            self.assertTrue(attempted.wait(timeout=1))
            # Give the native reader the response before send returns. The fixed
            # resolver keeps these events queued until the response is recorded.
            completed.wait(timeout=0.05)

    def native_request(self, method, params):
        self.requests.append({'method': method, 'params': params})
        if method == 'turn/start':
            turn = {'id': 'follow-up-turn', 'status': 'inProgress'}
            with self.runtime.lifecycle_lock:
                self.runtime._message({'method': 'turn/started', 'params': {'threadId': 'native-original', 'turn': turn}})
            return {'turn': turn}
        raise AssertionError(method)

    def add_approval(self, request_id='9', method='item/commandExecution/requestApproval'):
        params = {'threadId': 'native-original', 'turnId': 'current-turn', 'itemId': 'command-item'}
        if method == 'item/tool/requestUserInput':
            params['questions'] = [{'id': 'choice', 'header': 'Choice', 'question': 'Continue?',
                                    'options': [{'label': 'Yes', 'description': 'Continue'}]}]
        message = {'id': int(request_id), 'method': method, 'params': params}
        with self.runtime.lifecycle_lock:
            self.runtime._message(message)
        return message

    def completed(self, status='completed'):
        return {'method': 'turn/completed', 'params': {
            'threadId': 'native-original', 'turn': {'id': 'current-turn', 'status': status}}}

    def resolved(self, request_id='9'):
        return {'method': 'serverRequest/resolved', 'params': {
            'threadId': 'native-original', 'requestId': int(request_id)}}

    def post(self, path, **data):
        request = Request(f'http://127.0.0.1:{self.server.server_port}' + path,
                          data=json.dumps({'session': self.identifier, **data}).encode(),
                          headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=3) as response:
                return response.status, json.load(response)
        except HTTPError as response:
            with response:
                return response.code, json.load(response)

class ApprovalLifecycleTests(NativeHTTPFixture):
    def test_allow_once_can_finish_during_send_and_next_task_is_accepted(self):
        self.add_approval()
        self.incoming = [self.resolved(), self.completed()]
        status, response = self.post('/api/approval', request='9', decision='accept')
        self.join_native()
        self.assertEqual((status, response), (200, None))
        self.assertEqual(self.sent, [{'id': 9, 'result': {'decision': 'accept'}}])
        self.assertEqual(self.runtime.approvals, {})
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        status, _ = self.post('/api/turn', text='Continue the same task')
        self.assertEqual(status, 200)
        self.assertEqual(self.requests, [{'method': 'turn/start', 'params': {
            'threadId': 'native-original', 'input': [{'type': 'text', 'text': 'Continue the same task'}]}}])

    def test_duplicate_reply_is_rejected_without_resending_and_send_failure_keeps_pending(self):
        self.add_approval()
        self.send_error = OSError('fixture write failure')
        self.assertEqual(self.post('/api/approval', request='9', decision='accept')[0], 400)
        self.assertEqual(self.runtime.approvals.keys(), {'9'})
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'approval')
        self.assertEqual(self.sent, [])
        self.send_error = None
        self.assertEqual(self.post('/api/approval', request='9', decision='accept')[0], 200)
        self.assertEqual(self.post('/api/approval', request='9', decision='accept')[0], 400)
        self.assertEqual(len(self.sent), 1)

if __name__ == '__main__':
    unittest.main()
