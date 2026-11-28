"""Explicit prepared-task HTTP admission with controlled native transport."""
import http.client
import json
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock

from codex_desk.runtime import NativeRequestUnknown
from codex_desk.server import Desk, handler
from codex_desk.drafts import load_draft, save_draft
from http.server import ThreadingHTTPServer
from test_approval_lifecycle import NativeHTTPFixture, ROOT
from pathlib import Path

class FollowupApiTests(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.desk.store.update(self.identifier, status='ready')
        self.runtime.lock = threading.Lock()
        self.runtime.pending = {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()

    def get(self, session=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request('GET', '/api/followups?session=' + (session or self.identifier))
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def add(self, text='Next exact verification', mode='native'):
        status, snapshot = self.post('/api/followups', text=text, mode=mode)
        self.assertEqual(status, 200)
        return snapshot['entries'][-1]

    def test_prepare_edit_order_remove_clear_is_a_snapshot_without_native_work(self):
        before = self.desk.store.get(self.identifier)
        one, two = self.add('  Exact first task\nwith spaces  ', 'plan'), self.add('Second task')
        self.assertEqual(self.get()[1], {'entries': [one, two], 'reservation': None})
        status, snapshot = self.post('/api/followups/edit', id=one['id'], text='Edited task',
                                     mode='native', revision=one['revision'])
        self.assertEqual(status, 200)
        edited = snapshot['entries'][0]
        self.assertEqual(edited['revision'], one['revision'] + 1)
        self.assertEqual(self.post('/api/followups/edit', id=one['id'], text='Stale', mode='plan', revision=1)[0], 409)
        self.assertEqual(self.post('/api/followups/send', id=two['id'], revision=two['revision'])[0], 409)
        status, snapshot = self.post('/api/followups/reorder', ids=[two['id'], one['id']],
                                     order=[one['id'], two['id']])
        self.assertEqual(status, 200)
        self.assertEqual([entry['id'] for entry in snapshot['entries']], [two['id'], one['id']])
        self.assertEqual(self.post('/api/followups/clear', order=[one['id'], two['id']])[0], 409)
        self.assertEqual(self.post('/api/followups/clear', order=None)[0], 400)
        status, snapshot = self.post('/api/followups/remove', id=two['id'], revision=snapshot['entries'][0]['revision'])
        self.assertEqual(status, 200)
        self.assertEqual(self.post('/api/followups/clear', order=[one['id']]),
                         (200, {'entries': [], 'reservation': None}))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.desk.store.get(self.identifier), before)

    def check_lost_plan_reply_preserves_next_work(self, queued, terminal):
        draft = save_draft(self.desk.store, self.identifier, 'Separate saved Plan draft', 'plan', 0)
        first = self.add('Review the project before implementing', 'plan') if queued else None
        later = self.add('Implement the reviewed change', 'native')
        native_outcome = {}

        def started_then_lost(method, params):
            self.native_request(method, params)
            with self.runtime.lifecycle_lock:
                self.runtime._message({'method': 'thread/tokenUsage/updated', 'params': {
                    'threadId': 'native-original', 'tokenUsage': {'total': {'totalTokens': 42}}}})
                completed = self.completed(terminal)
                if terminal == 'failed':
                    completed['params']['turn']['error'] = {'message': 'Fixture task failed'}
                self.runtime._message(completed)
                native_outcome.update(self.desk.store.get(self.identifier))
            raise NativeRequestUnknown('Lost native reply after Plan task')

        self.runtime.request = started_then_lost
        status, result = (self.send(first) if queued else
                          self.post('/api/turn', text='Review the project before implementing', mode='plan'))
        self.assertEqual(status, 200)
        self.assertEqual(self.requests[0]['params']['collaborationMode']['mode'], 'plan')
        recovered = self.desk.store.get(self.identifier)
        self.assertEqual(recovered['mode'], 'plan')
        for field in ('id', 'cwd', 'profile', 'thread_id', 'name', 'created', 'status', 'usage', 'error'):
            self.assertEqual(recovered[field], native_outcome[field], field)
        self.assertTrue(recovered['thread_saved'])
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)
        self.assertEqual(self.get()[1], {'entries': [dict(later, order=1)], 'reservation': None})
        if queued:
            self.assertEqual(result['receipt']['outcome'], 'accepted')
            self.assertTrue(result['receipt']['consumed'])
        self.runtime.request = self.native_request
        self.assertEqual(self.send(later)[0], 200)
        self.assertEqual(self.requests[-1]['params']['collaborationMode'], {
            'mode': 'default', 'settings': {'model': 'fixture-model', 'developer_instructions': None}})
        self.assertEqual(load_draft(self.desk.store, self.identifier), draft)

class FollowupStdioTests(unittest.TestCase):
    def test_real_http_and_native_stdio_admission_rejection_exit_restart(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        home = root / 'home'
        home.mkdir()
        config, auth = home / 'config.toml', home / 'auth.json'
        config.write_text('model="original-model"\n')
        auth.write_text('{"fixture":"original auth"}\n')
        originals = config.read_bytes(), auth.read_bytes()
        launcher = root / 'native-fixture'
        launcher.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
for line in sys.stdin:
    message = json.loads(line)
    with (home / 'requests.jsonl').open('a') as log:
        log.write(json.dumps(message) + '\\n')
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        result = {}
    elif method == 'thread/resume':
        result = {'thread': {'id': params['threadId'], 'turns': []},
                  'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
    elif method == 'turn/start':
        text = params['input'][0]['text']
        if text == 'Exit without reply':
            sys.exit(0)
        if text == 'Reject this task':
            print(json.dumps({'id': message['id'], 'error': {
                'code': -32602, 'message': 'Definite native fixture rejection'}}), flush=True)
            continue
        turn = {'id': 'fixture-turn', 'status': 'inProgress'}
        print(json.dumps({'method': 'turn/started', 'params': {
            'threadId': params['threadId'], 'turn': turn}}), flush=True)
        print(json.dumps({'id': message['id'], 'result': {'turn': turn}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {
            'threadId': params['threadId'], 'turn': {**turn, 'status': 'completed'}}}), flush=True)
        continue
    elif method == 'thread/name/set':
        result = {}
    else:
        continue
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
        launcher.chmod(0o700)
        desk = Desk(str(launcher), home, root / 'state')
        self.addCleanup(desk.store.db.close)
        self.addCleanup(desk.close)
        identifier = desk.store.create(str(root), 'default', name='Fixture project')
        desk.store.update(identifier, thread_id='native-original', thread_saved=1,
                          status='saved', name_pending=0)
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler(desk))
        worker = threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        worker.start()

        def stop_server():
            server.shutdown()
            server.server_close()
            worker.join(2)

        self.addCleanup(stop_server)

        def call(path, fields=None):
            connection = http.client.HTTPConnection('127.0.0.1', server.server_port, timeout=5)
            try:
                if fields is None:
                    connection.request('GET', path + '?session=' + identifier)
                else:
                    connection.request('POST', path, json.dumps({'session': identifier, **fields}),
                                       {'Content-Type': 'application/json'})
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        self.assertEqual(call('/api/followups'), (200, {'entries': [], 'reservation': None}))
        self.assertEqual(desk.runtimes, {})
        _, snapshot = call('/api/followups', {'text': 'Plan one project task', 'mode': 'plan'})
        first = snapshot['entries'][0]
        status, snapshot = call('/api/followups/send', {'id': first['id'], 'revision': first['revision']})
        self.assertEqual(status, 200)
        self.assertEqual(snapshot['receipt']['outcome'], 'accepted')
        self.assertEqual(snapshot['entries'], [])
        _, snapshot = call('/api/followups', {'text': 'Reject this task', 'mode': 'native'})
        second = snapshot['entries'][0]
        status, rejected = call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})
        self.assertEqual(status, 400)
        self.assertEqual(rejected['receipt']['outcome'], 'rejected')
        self.assertEqual(rejected['entries'], [second])
        _, snapshot = call('/api/followups/edit', {'id': second['id'], 'revision': second['revision'],
                                                  'text': 'Exit without reply', 'mode': 'native'})
        second = snapshot['entries'][0]
        original_runtime = desk.runtimes[identifier]
        status, unknown = call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})
        self.assertEqual(status, 400)
        self.assertEqual(unknown['receipt']['outcome'], 'unknown')
        self.assertTrue(original_runtime.closing)
        self.assertIsNotNone(original_runtime.process.poll())
        self.assertEqual(desk.runtimes, {})
        self.assertEqual(call('/api/turn', {'text': 'No replay'})[0], 409)
        desk.close()
        desk.store.db.close()
        restarted = Desk(str(launcher), home, root / 'state')
        self.addCleanup(restarted.store.db.close)
        self.addCleanup(restarted.close)
        server.RequestHandlerClass = handler(restarted)
        self.assertEqual(call('/api/followups')[1]['reservation'], unknown['reservation'])
        self.assertEqual(restarted.runtimes, {})
        self.assertEqual(call('/api/followups/send', {'id': second['id'], 'revision': second['revision']})[0], 409)
        reservation = unknown['reservation']
        status, reviewed = call('/api/followups/resolve', {'token': reservation['token'],
            'id': reservation['entry_id'], 'revision': reservation['revision'], 'outcome': 'rejected'})
        self.assertEqual(status, 200)
        self.assertEqual(reviewed['entries'][0]['state'], 'queued')
        self.assertIsNone(reviewed['reservation'])
        requests = [json.loads(line) for line in (home / 'requests.jsonl').read_text().splitlines()]
        turns = [request for request in requests if request.get('method') == 'turn/start']
        self.assertEqual(len(turns), 3)
        self.assertTrue(all(turn['params']['threadId'] == 'native-original' for turn in turns))
        self.assertEqual(turns[0]['params']['collaborationMode']['mode'], 'plan')
        self.assertEqual((config.read_bytes(), auth.read_bytes()), originals)

if __name__ == '__main__':
    unittest.main()
