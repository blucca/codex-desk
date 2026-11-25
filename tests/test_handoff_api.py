"""A failed native turn remains reviewable in a distinct-thread handoff."""
import copy
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


class HandoffApiTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-handoff-api-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.source = self.desk.store.create(str(self.root), 'default')
        self.desk.store.update(self.source, thread_id='native-source', thread_saved=1,
                               status='failed', error='Provider stream disconnected')
        # Turn/TurnError fields from native 0.171 thread/read, including a
        # partial reply before the final stream failure.
        self.thread = {'id': 'native-source', 'cwd': str(self.root), 'modelProvider': 'relay',
                       'turns': [{'id': 'failed-turn', 'status': 'failed', 'items': [
                           {'id': 'request', 'type': 'userMessage', 'content': [
                               {'type': 'text', 'text': 'Verify the project build'}]},
                           {'id': 'partial', 'type': 'agentMessage',
                            'text': 'I found the verification command; it has not run yet.'}],
                           'error': {'message': 'Provider stream disconnected',
                                     'codexErrorInfo': {'responseStreamDisconnected': {
                                         'httpStatusCode': 503}},
                                     'additionalDetails': 'Retry limit reached'}}]}
        self.desk.history = Mock(return_value=self.thread)

        def open_target(identifier):
            thread_id = 'target-' + identifier
            self.desk.store.update(identifier, thread_id=thread_id)
            return {'thread': {'id': thread_id, 'turns': []}}

        self.desk.open = Mock(side_effect=open_target)
        self.desk.turn = Mock(return_value={'turn': {'id': 'target-turn'}})
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def post(self, path, data):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('POST', path, json.dumps(data), {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def test_partial_reply_and_final_failure_survive_review_and_target_start(self):
        original_thread = copy.deepcopy(self.thread)
        original_session = self.desk.store.get(self.source)
        status, review = self.post('/api/handoff', {'thread': self.thread['id']})
        self.assertEqual(status, 200)
        text = review['text']
        for value in ('it has not run yet', 'Turn failed-turn\nStatus: failed',
                      'Provider stream disconnected', 'responseStreamDisconnected',
                      '503', 'Retry limit reached'):
            self.assertIn(value, text)
        self.assertLess(text.index('it has not run yet'), text.index('Turn failed-turn'))
        self.desk.open.assert_not_called()
        self.desk.turn.assert_not_called()
        status, target = self.post('/api/handoff/start', {
            'cwd': str(self.root), 'profile': 'default', 'text': text,
            'goal': 'Run the verification command and report its result'})
        self.assertEqual(status, 200)
        self.assertNotEqual(target['id'], self.source)
        self.assertNotEqual(self.desk.store.get(target['id'])['thread_id'], self.thread['id'])
        self.desk.turn.assert_called_once_with(target['id'],
            'Next task: Run the verification command and report its result\n\n' + text.strip())
        self.assertEqual(self.desk.store.get(self.source), original_session)
        self.assertEqual(self.thread, original_thread)
        self.assertEqual(self.desk.runtimes, {})


if __name__ == '__main__':
    unittest.main()
