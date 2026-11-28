"""Controlled native/HTTP fixture for the retained evidence lifecycle."""
import copy
import http.client
import json
import threading
import uuid
from urllib.parse import urlencode
from unittest.mock import Mock
from http.server import ThreadingHTTPServer
from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.runtime import NativeRequestRejected, NativeRequestUnknown
from codex_desk.server import handler
from test_approval_lifecycle import NativeHTTPFixture

TEXT='Review exactly one project decision — 保留  '

class NativeRequestFixture(NativeHTTPFixture):
    def setUp(self):
        super().setUp()
        self.desk.store.update(self.identifier, status='ready')
        self.runtime.lock = threading.Lock()
        self.runtime.pending = {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()
        self.native_mode = 'completed'
        self.runtime.request = self.controlled_native
        save_draft(self.desk.store, self.identifier, TEXT, 'plan', 0)
        add_followup(self.desk.store, self.identifier, 'Paused Work — exact  ', 'native')
        add_followup(self.desk.store, self.identifier, 'Paused Plan — exact  ', 'plan')
        self.preparation = followup_snapshot(self.desk.store, self.identifier)

    def start_server(self, port=0):
        self.server = ThreadingHTTPServer(('127.0.0.1', port), handler(self.desk))
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()

    def controlled_native(self, method, params):
        self.assertEqual(method, 'turn/start')
        self.requests.append({'method': method, 'params': copy.deepcopy(params)})
        turn = 'ordinary-turn-' + str(len(self.requests))
        if self.native_mode == 'rejected':
            raise NativeRequestRejected('Controlled known rejection')
        if self.native_mode == 'unknown':
            raise NativeRequestUnknown('Controlled no-event unknown admission')
        self.native_event('turn/started', params['threadId'], {'turn': {'id': turn, 'status': 'inProgress'}})
        if self.native_mode == 'completed':
            self.native_event('item/completed', params['threadId'], {'turnId': turn, 'item': {
                'id': 'user-' + turn, 'type': 'userMessage', 'content': params['input']}})
            self.native_event('item/completed', params['threadId'], {'turnId': turn, 'item': {
                'id': 'answer-' + turn, 'type': 'agentMessage', 'text': 'Controlled result ' + turn}})
            self.native_event('turn/completed', params['threadId'], {'turn': {'id': turn, 'status': 'completed'}})
        return {'turn': {'id': turn, 'status': 'inProgress'}}

    def native_event(self, method, thread, fields):
        with self.runtime.lifecycle_lock:
            self.runtime._message({'method': method, 'params': {'threadId': thread, **fields}})

    def request(self, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=25)
        headers = {}
        if data is not None:
            headers['Content-Type'] = 'application/json'
        try:
            connection.request('GET' if data is None else 'POST', path,
                               None if data is None else json.dumps(data), headers)
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def capture(self, text=TEXT, mode='plan'):
        current = load_draft(self.desk.store, self.identifier)
        writer = str(uuid.uuid4())
        saved = save_draft(self.desk.store, self.identifier, text, mode, current['revision'], writer, 1)
        return {'session': self.identifier, 'token': str(uuid.uuid4()), 'text': text,
                'mode': mode, 'revision': saved['revision'], 'writer': writer, 'sequence': 1}

    def read_request(self, payload):
        return self.request('/api/turn/request?' + urlencode({'session': payload['session'], 'token': payload['token']}))

    def assert_preparation(self):
        self.assertEqual(followup_snapshot(self.desk.store, self.identifier), self.preparation)

