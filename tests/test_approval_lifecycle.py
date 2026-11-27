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

    def test_completion_cannot_be_overwritten_by_allow_once_or_answer(self):
        cases = [('/api/approval', 'item/commandExecution/requestApproval', {'decision': 'accept'}),
                 ('/api/answer', 'item/tool/requestUserInput', {'answers': {'choice': ['Yes']}})]
        for path, method, data in cases:
            with self.subTest(method=method):
                self.add_approval(method=method)
                self.incoming = [self.completed()]
                status, _ = self.post(path, request='9', **data)
                self.join_native()
                self.assertEqual(status, 200)
                self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
                self.assertEqual(self.runtime.approvals, {})

    def test_one_of_two_approvals_keeps_other_pending(self):
        self.add_approval('9')
        self.add_approval('10', 'item/fileChange/requestApproval')
        self.assertEqual(self.post('/api/approval', request='9', decision='accept')[0], 200)
        self.assertEqual(set(self.runtime.approvals), {'10'})
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'approval')
        self.assertEqual(self.post('/api/turn', text='Too soon')[0], 400)
        self.assertEqual(self.requests, [])
        self.assertEqual(self.post('/api/approval', request='10', decision='decline')[0], 200)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')

    def test_late_resolution_does_not_revive_a_stopped_turn(self):
        self.add_approval()
        self.assertEqual(self.post('/api/approval', request='9', decision='decline')[0], 200)
        with self.runtime.lifecycle_lock:
            self.runtime._message(self.completed('interrupted'))
            self.runtime._message(self.resolved())
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'interrupted')
        self.assertEqual(self.post('/api/turn', text='Continue after stop')[0], 200)

    def test_terminal_turn_retires_pending_requests_and_rejects_delayed_http_response(self):
        cases = [('/api/approval', 'item/commandExecution/requestApproval', 'interrupted', {'decision': 'accept'}),
                 ('/api/answer', 'item/tool/requestUserInput', 'completed', {'answers': {'choice': ['Yes']}})]
        for path, method, terminal_status, data in cases:
            with self.subTest(method=method, status=terminal_status):
                self.add_approval(method=method)
                with self.runtime.lifecycle_lock:
                    self.runtime._message(self.completed(terminal_status))
                status, _ = self.post(path, request='9', **data)
                self.assertEqual(status, 400)
                self.assertEqual(self.sent, [])
                self.assertEqual(self.runtime.approvals, {})
                self.assertEqual(self.desk.store.get(self.identifier)['status'], terminal_status)
                # The old native resolution may still arrive after completion.
                with self.runtime.lifecycle_lock:
                    self.runtime._message(self.resolved())
                self.assertEqual(self.desk.store.get(self.identifier)['status'], terminal_status)
                self.assertEqual(self.post('/api/turn', text='Continue after the finished interaction')[0], 200)

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


class TurnLifecycleTests(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.desk.store.update(self.identifier, status='ready')

    def test_two_tabs_start_only_one_turn_and_remain_busy_until_completion(self):
        entered, release = threading.Event(), threading.Event()
        result = []

        def native_start(method, params):
            self.requests.append({'method': method, 'params': params})
            if len(self.requests) == 1:
                entered.set()
                release.wait(timeout=2)
            # A response may precede turn/started. It still means a busy turn.
            return {'turn': {'id': 'current-turn', 'status': 'inProgress'}}

        self.runtime.request = native_start
        first = threading.Thread(target=lambda: result.append(self.post('/api/turn', text='First tab task')))
        first.start()
        try:
            self.assertTrue(entered.wait(timeout=1))
            status, response = self.post('/api/turn', text='Second tab task')
            self.assertEqual((status, response), (400, {'error': 'Finish or stop the current turn first'}))
            self.assertEqual(len(self.requests), 1)
            self.assertEqual(self.desk.store.get(self.identifier)['status'], 'starting')
        finally:
            release.set()
            first.join(timeout=3)
        self.assertFalse(first.is_alive())
        self.assertEqual(result[0][0], 200)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')
        self.assertEqual(self.post('/api/turn', text='Still too soon')[0], 400)
        with self.runtime.lifecycle_lock:
            self.runtime._message(self.completed())
        self.runtime.request = self.native_request
        self.assertEqual(self.post('/api/turn', text='Follow-up after completion')[0], 200)
        self.assertEqual(len(self.requests), 2)
        self.assertTrue(all(r['params']['threadId'] == 'native-original' for r in self.requests))

    def test_rejected_start_restores_idle_status_and_can_be_retried(self):
        def reject(method, params):
            self.requests.append({'method': method, 'params': params})
            raise RuntimeError('fixture request rejected')

        self.runtime.request = reject
        self.assertEqual(self.post('/api/turn', text='Make a plan', mode='plan'),
                         (400, {'error': 'fixture request rejected'}))
        row = self.desk.store.get(self.identifier)
        self.assertEqual(row['status'], 'ready')
        self.assertIsNone(row['error'])
        self.assertEqual(row['mode'], 'native')
        self.runtime.request = lambda method, params: {'turn': {'id': 'retry-turn', 'status': 'inProgress'}}
        self.assertEqual(self.post('/api/turn', text='Retry the task')[0], 200)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'running')

    def test_completion_before_start_response_is_not_overwritten(self):
        def complete_before_reply(method, params):
            self.requests.append({'method': method, 'params': params})
            with self.runtime.lifecycle_lock:
                self.runtime._message(self.completed())
            return {'turn': {'id': 'current-turn', 'status': 'inProgress'}}

        self.runtime.request = complete_before_reply
        self.assertEqual(self.post('/api/turn', text='A quick task')[0], 200)
        self.assertEqual(self.desk.store.get(self.identifier)['status'], 'completed')
        self.runtime.request = self.native_request
        self.assertEqual(self.post('/api/turn', text='Next task')[0], 200)


if __name__ == '__main__':
    unittest.main()
