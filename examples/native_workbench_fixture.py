"""Shared loopback fixture for the installed workbench journeys."""
import copy
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tests'))
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.server import handler
from codex_desk.drafts import save_draft, load_draft
from codex_desk.followups import add_followup, followup_snapshot

ACCESS = 'local-workbench-fixture'
SOURCE, TURN, ITEM = 'source-A', 'source-turn', 'source-command'
INSTRUCTION_ITEM, RESPONSE_ITEM = 'source-instruction', 'source-response'
INSTRUCTION = 'Inspect the checkout retry limit before repeating the failing check.'
RESPONSE = 'Keep the configured two-attempt limit; inspect the original command result before changing the check.'
QUOTE = 'Retry budget: 2 attempts. Café🙂 remains exact.'
DRAFT = 'Keep B as an unsent Plan while checking the original.'
NEWER = 'Newer unsent Plan — keep this after the completed request.'
OUTPUT = 'Original beginning\n' + ('Original numbered source line 🌱\n' * 900) + QUOTE + '\nOriginal end'


class WorkbenchFixture(NativeHTTPFixture):
    def runTest(self):
        pass

    def start(self):
        self.setUp()
        self.close_server()
        self.desk.store.update(self.identifier, status='ready', thread_saved=1)
        save_draft(self.desk.store, self.identifier, DRAFT, 'plan', 0)
        add_followup(self.desk.store, self.identifier, 'Paused Work instruction', 'native')
        add_followup(self.desk.store, self.identifier, 'Paused Plan instruction', 'plan')
        self.other = self.desk.store.create(str(self.path), 'default', name='Other task')
        save_draft(self.desk.store, self.other, 'Other task remains unsent.', 'plan', 0)
        self.original = {'id': SOURCE, 'name': 'Older retry decision',
            'cwd': str(self.path / 'removed-A'), 'updatedAt': 1795800000,
            'turns': [{'id': TURN, 'status': 'completed', 'items': [
                {'id': INSTRUCTION_ITEM, 'type': 'userMessage',
                 'content': [{'type': 'text', 'text': INSTRUCTION}]},
                {'id': ITEM, 'type': 'commandExecution', 'command': 'inspect retry',
                 'status': 'completed', 'exitCode': 1, 'aggregatedOutput': OUTPUT},
                {'id': RESPONSE_ITEM, 'type': 'agentMessage',
                 'phase': 'final_answer', 'text': RESPONSE}]}]}
        self.http, self.history_calls = [], []
        self.drop_reply = False
        self.hold_reply = False
        self.reply_entered, self.reply_release = threading.Event(), threading.Event()
        self.reply_release.set()
        self.runtime.lock, self.runtime.pending = threading.Lock(), {}
        self.runtime.reader, self.runtime.stderr_reader = Mock(), Mock()
        self.runtime.request = self.transport
        owner = self

        class Catalog:
            def request(self, method, params, timeout=30):
                owner.history_calls.append({'method': method, 'params': copy.deepcopy(params)})
                if method == 'thread/list':
                    return {'data': [{k: v for k, v in owner.original.items() if k != 'turns'}], 'nextCursor': None}
                assert method == 'thread/read' and params == {'threadId': SOURCE, 'includeTurns': True}
                return {'thread': copy.deepcopy(owner.original)}

        class Reader(Catalog):
            def __init__(self, *args):
                self.closing = False
                self.process = Mock()
                self.process.poll.return_value = None

            def close(self):
                self.closing = True
                self.process.poll.return_value = 0

        self.reader_type = Reader
        self.desk.catalog = lambda: Catalog()
        # Initial fixture events have no bearing on this remembered original.
        self.runtime.thread_result = {'thread': {'id': 'native-original', 'turns': []}}

        class Handler(handler(self.desk, ACCESS)):
            def do_GET(self):
                owner.http.append(('GET', self.path))
                super().do_GET()

            def do_POST(self):
                owner.http.append(('POST', self.path))
                super().do_POST()

            def reply(self, value, status=200):
                if self.path == '/api/turn' and status == 200:
                    owner.reply_entered.set()
                    if owner.hold_reply:
                        assert owner.reply_release.wait(20), 'Unreleased completed request'
                    if owner.drop_reply:
                        owner.drop_reply = False
                        self.close_connection = True
                        return
                super().reply(value, status)

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, kwargs={'poll_interval': .01}, daemon=True)
        self.server_thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/#access={ACCESS}'

    def transport(self, method, params):
        assert method == 'turn/start'
        self.requests.append({'method': method, 'params': copy.deepcopy(params)})
        turn = 'completed-task'
        with self.runtime.lifecycle_lock:
            for event in (
                {'method': 'turn/started', 'params': {'threadId': 'native-original', 'turn': {'id': turn, 'status': 'inProgress'}}},
                {'method': 'item/completed', 'params': {'threadId': 'native-original', 'turnId': turn, 'item': {
                    'id': 'answer', 'type': 'agentMessage', 'text': 'Completed native result.'}}},
                {'method': 'turn/completed', 'params': {'threadId': 'native-original', 'turn': {'id': turn, 'status': 'completed'}}},
            ):
                self.runtime._message(event)
        return {'turn': {'id': turn, 'status': 'inProgress'}}

    def prepared(self):
        return {'draft': load_draft(self.desk.store, self.identifier),
                'queue': followup_snapshot(self.desk.store, self.identifier),
                'other': load_draft(self.desk.store, self.other)}

    def stop(self):
        self.reply_release.set()
        self.doCleanups()
