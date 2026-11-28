"""Exact captured responses through HTTP and an unpersisted native reader."""
import copy
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.server import Desk, LoopbackHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', Path.cwd() / 'temp')).resolve()
ROOT.mkdir(parents=True, exist_ok=True)


def message(identifier, phase='final_answer', text='Exact native answer'):
    return {'id': identifier, 'type': 'agentMessage', 'phase': phase, 'text': text}


def original(items=None, status='failed', thread='parent', turn='captured'):
    return {'id': thread, 'cwd': '/former/native/project', 'name': 'Original task', 'turns': [
        {'id': 'earlier', 'status': 'completed', 'items': [message('earlier-answer')]},
        {'id': turn, 'status': status, 'error': {'message': 'Native task failure',
         'codexErrorInfo': 'sandboxError'}, 'items': items if items is not None else [message('answer')]},
        {'id': 'newer', 'status': 'inProgress', 'items': [message('newer-answer')]}]}


class TaskResponseApiTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='native-response-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / 'home'
        self.home.mkdir()
        (self.home / 'config.toml').write_text('model="saved-model"\n')
        (self.home / 'auth.json').write_text('{"fixture":"saved-auth"}\n')
        self.home_before = {p.name: p.read_bytes() for p in self.home.iterdir()}
        self.native_log = self.root / 'requests.jsonl'
        self.reply_file = self.root / 'reply.json'
        self.native = self.root / 'native-reader'
        self.native.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
log = Path(''' + repr(str(self.native_log)) + ''')
reply_file = Path(''' + repr(str(self.reply_file)) + ''')
for line in sys.stdin:
    message = json.loads(line)
    with log.open('a') as stream:
        stream.write(json.dumps({'message': message, 'cwd': os.getcwd(),
            'home': os.environ.get('CODEX_HOME'), 'argv': sys.argv[1:]}) + '\\n')
    method = message.get('method')
    if method == 'initialize':
        result = {}
    elif method == 'initialized':
        continue
    elif method == 'thread/read':
        assert message['params'].get('includeTurns') is True
        result = json.loads(reply_file.read_text())
        # Catalog notifications cannot mutate Desk state or start a task.
        print(json.dumps({'method': 'turn/started', 'params': {'threadId': 'foreign-child',
            'turn': {'id': 'child-turn', 'status': 'inProgress'}}}), flush=True)
        print(json.dumps({'id': 9999, 'method': 'item/commandExecution/requestApproval',
            'params': {'threadId': 'foreign-child', 'turnId': 'child-turn'}}), flush=True)
        print(json.dumps({'method': 'turn/completed', 'params': {'threadId': 'foreign-child',
            'turn': {'id': 'child-turn', 'status': 'failed'}}}), flush=True)
        if isinstance(result, dict) and 'native_error' in result:
            print(json.dumps({'id': message['id'], 'error': {'message': result['native_error']}}), flush=True)
            continue
        if isinstance(result, dict) and result.get('transport_exit'):
            sys.exit(1)
    else:
        raise AssertionError('Unexpected task admission: ' + str(method))
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
        self.native.chmod(0o700)
        self.desk = Desk(str(self.native), self.home, self.root / 'state')
        self.addCleanup(self.close_desk)
        self.sessions = []
        for index, mode in enumerate(('native', 'plan')):
            project = self.root / ('project-' + str(index))
            project.mkdir()
            session = self.desk.store.create(str(project), 'default', name='Retained preparation')
            self.desk.store.update(session, thread_id='parent' if index == 0 else 'other-parent',
                status='saved', thread_saved=1, mode=mode, name_pending=0)
            save_draft(self.desk.store, session, 'Unsent ' + mode + ' draft', mode, 0)
            add_followup(self.desk.store, session, 'Queued Work task', 'native')
            add_followup(self.desk.store, session, 'Queued Plan task', 'plan')
            self.desk.store.event(session, {'method': 'turn/completed', 'params': {
                'threadId': 'parent' if index == 0 else 'other-parent',
                'turn': {'id': 'captured', 'status': 'failed', 'error': {'message': 'Retained outcome'}}}})
            self.sessions.append(session)
        self.access = 'fixture-access'
        self.server = None
        self.start_server()
        self.addCleanup(self.stop_server)
        self.source = original()
        self.set_reply({'thread': self.source})

    def close_desk(self):
        self.desk.close()
        self.desk.store.db.close()

    def start_server(self):
        self.server = LoopbackHTTPServer(('127.0.0.1', 0), handler(self.desk, self.access))
        self.worker = threading.Thread(target=self.server.serve_forever,
            kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()

    def stop_server(self):
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.worker.join(3)
            self.server = None

    def request(self, method='GET', path=None, data=None, headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        body = json.dumps(data).encode() if method == 'POST' else None
        request_headers = {'X-Codex-Desk-Access': self.access}
        if body is not None:
            request_headers['Content-Type'] = 'application/json'
        request_headers.update(headers or {})
        try:
            connection.request(method, path or self.path(), body=body, headers=request_headers)
            result = connection.getresponse()
            return result.status, json.loads(result.read()), result.getheader('Cache-Control')
        finally:
            connection.close()

    @staticmethod
    def path(thread='parent', turn='captured'):
        return '/api/native/task-response?' + urlencode({'thread': thread, 'turn': turn})

    def set_reply(self, reply):
        self.reply_file.write_text(json.dumps(reply, ensure_ascii=False))

    def native_calls(self):
        if not self.native_log.exists():
            return []
        return [json.loads(line) for line in self.native_log.read_text().splitlines()]

    def state(self):
        with self.desk.store.lock:
            return {'sql': list(self.desk.store.db.iterdump()),
                'sqlite': (self.root / 'state' / 'desk.sqlite3').read_bytes(),
                'sessions': self.desk.store.sessions(),
                'drafts': [load_draft(self.desk.store, s) for s in self.sessions],
                'queues': [followup_snapshot(self.desk.store, s) for s in self.sessions],
                'events': [self.desk.store.events(s) for s in self.sessions],
                'changes': self.desk.store.db.total_changes}

    def assert_read_only(self, before, expected_reads):
        self.assertEqual(self.state(), before)
        self.assertEqual(self.desk.runtimes, {})
        self.assertIsNone(self.desk.store.get('native-catalog'))
        self.assertIsNone(self.desk.history_scanner.worker)
        self.assertEqual(self.desk.admissions, {})
        self.assertEqual(self.desk.followup_sends, {})
        self.assertEqual(self.desk.steer_sends, {})
        self.assertEqual(self.desk.stop_sends, {})
        calls = self.native_calls()
        self.assertEqual(sum(c['message']['method'] == 'thread/read' for c in calls), expected_reads)
        for call in calls:
            self.assertIn(call['message']['method'], ('initialize', 'initialized', 'thread/read'))
            self.assertEqual(call['argv'], ['app-server', '--stdio'])
            self.assertEqual(call['cwd'], str(self.root / 'state'))
            self.assertEqual(call['home'], str(self.home))
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir()}, self.home_before)

    def test_one_read_exact_turn_last_final_full_unicode_source_and_zero_writes(self):
        long_text = 'Exact Unicode café 🌱 项目 e\u0301\r\n' * 15000
        self.source = original([message('first-final'),
            {'id': 'tool', 'type': 'commandExecution', 'aggregatedOutput': 'Tool result'},
            message('last-final', text=long_text), message('after-final', 'commentary'),
            {'id': 'child', 'type': 'collabAgentToolCall', 'receiverThreadIds': ['foreign-child']}])
        self.set_reply({'thread': self.source})
        before = self.state()
        with (patch.object(self.desk, 'catalog', side_effect=AssertionError('Persisted catalog forbidden')),
              patch.object(self.desk, 'open', side_effect=AssertionError('Task attach forbidden'))):
            status, result, cache = self.request()
        self.assertEqual((status, cache), (200, 'no-store'))
        self.assertEqual(result['thread'], self.source)
        response = result['response']
        self.assertEqual((response['thread_id'], response['turn_id'], response['item_id']),
                         ('parent', 'captured', 'last-final'))
        self.assertTrue(response['available'])
        self.assertEqual((response['phase'], response['selection'], response['turn_status']),
                         ('final_answer', 'final_answer', 'failed'))
        self.assertEqual(response['turn_error'], self.source['turns'][1]['error'])
        self.assertEqual(response['source'], 'native history read')
        self.assertIsNone(response['reason'])
        self.assertNotIn('text', response)
        self.assertLess(len(json.dumps(response)), 600)
        reads = [c['message'] for c in self.native_calls() if c['message']['method'] == 'thread/read']
        self.assertEqual(reads, [{'id': reads[0]['id'], 'method': 'thread/read',
            'params': {'threadId': 'parent', 'includeTurns': True}}])
        self.assert_read_only(before, 1)

    def test_commentary_partial_omitted_null_and_future_phase_keep_native_status(self):
        before = self.state()
        for index, (phase, status) in enumerate(((None, 'failed'), ('commentary', 'inProgress'),
                ('partial_answer', 'interrupted'), ('future_phase', 'failed'), ('omitted', 'completed')), 1):
            with self.subTest(phase=phase):
                item = message('legacy', phase)
                if phase == 'omitted':
                    item.pop('phase')
                thread = original([item], status=status)
                self.set_reply({'thread': thread})
                status_code, result, _ = self.request()
                self.assertEqual(status_code, 200)
                self.assertEqual(result['thread'], thread)
                response = result['response']
                self.assertEqual(response['item_id'], 'legacy')
                self.assertEqual(response['phase'], None if phase == 'omitted' else phase)
                self.assertEqual(response['selection'], 'last_assistant_message')
                self.assertEqual(response['turn_status'], status)
                self.assert_read_only(before, index)

    def test_absent_empty_tools_and_invalid_responses_never_substitute_later_turn(self):
        before = self.state()
        cases = [({'id': 'parent', 'turns': original()['turns'][::2]}, 'turn_unavailable'),
            (original([]), 'response_unavailable'),
            (original([{'id': 'tool', 'type': 'commandExecution', 'aggregatedOutput': 'Answer'}]), 'response_unavailable'),
            (original([message('   '), message('blank', text=' \n'), message('x'*201)]), 'response_unavailable')]
        for index, (thread, reason) in enumerate(cases, 1):
            with self.subTest(reason=reason):
                self.set_reply({'thread': thread})
                status, result, _ = self.request()
                self.assertEqual(status, 200)
                self.assertEqual(result['thread'], thread)
                response = result['response']
                self.assertFalse(response['available'])
                self.assertEqual(response['reason'], reason)
                self.assertEqual((response['thread_id'], response['turn_id']), ('parent', 'captured'))
                self.assertNotIn('item_id', response)
                self.assert_read_only(before, index)

    def test_foreign_malformed_and_ambiguous_native_reads_reject_after_one_read(self):
        before = self.state()
        duplicate_turn = original()
        duplicate_turn['turns'].append(copy.deepcopy(duplicate_turn['turns'][1]))
        replies = [None, [], {}, {'thread': None}, {'thread': original(thread='foreign')},
            {'thread': {'id': 'parent', 'turns': None}}, {'thread': duplicate_turn},
            {'thread': original([message('duplicate'), message('duplicate')])}]
        for index, reply in enumerate(replies, 1):
            with self.subTest(reply=reply):
                self.set_reply(reply)
                status, result, cache = self.request()
                self.assertEqual((status, cache), (400, 'no-store'))
                self.assertIn('error', result)
                self.assertNotIn('response', result)
                self.assert_read_only(before, index)

    def test_missing_repeated_extra_blank_overlong_query_fails_before_any_native_call(self):
        before = self.state()
        prefix = '/api/native/task-response'
        paths = [prefix, prefix + '?thread=parent', prefix + '?turn=captured',
            prefix + '?thread=parent&turn=captured&thread=other',
            prefix + '?thread=parent&turn=captured&turn=other',
            prefix + '?thread=parent&turn=captured&extra=',
            prefix + '?thread=parent&turn=captured&',
            prefix + '?thread=parent&turn',
            self.path(thread=''), self.path(turn=''), self.path(thread=' \t'), self.path(turn='\n'),
            self.path(thread='x'*201), self.path(turn='x'*201),
            prefix + '?thread=parent&turn=captured&' + '&'.join('extra'+str(i)+'=v' for i in range(100)),
            prefix + '?thread=parent&turn=%FF']
        with (patch('codex_desk.server._NativeReader', side_effect=AssertionError('Native creation forbidden')) as created,
              patch.object(self.desk, 'read_native', side_effect=AssertionError('Read forbidden')) as read):
            for path in paths:
                with self.subTest(path=path):
                    status, result, _ = self.request(path=path)
                    self.assertEqual(status, 400)
                    self.assertIn('error', result)
            created.assert_not_called()
            read.assert_not_called()
        self.assertIsNone(self.desk.native_reader)
        self.assert_read_only(before, 0)

    def test_opaque_id_200_limit_unicode_and_surrounding_space_preserved(self):
        before = self.state()
        thread_id = ' 父 /?+%&=' + '界'*191
        turn_id = ' 任务 /+?% ' + '文'*191
        self.assertEqual(len(thread_id), 200)
        self.assertEqual(len(turn_id), 200)
        thread = original(thread=thread_id, turn=turn_id)
        self.set_reply({'thread': thread})
        status, result, _ = self.request(path=self.path(thread_id, turn_id))
        self.assertEqual(status, 200)
        self.assertEqual((result['response']['thread_id'], result['response']['turn_id']), (thread_id, turn_id))
        reads = [c['message'] for c in self.native_calls() if c['message']['method'] == 'thread/read']
        self.assertEqual(reads[0]['params'], {'threadId': thread_id, 'includeTurns': True})
        self.assert_read_only(before, 1)

    def test_post_and_unauthorized_get_never_admit_or_read(self):
        before = self.state()
        with patch('codex_desk.server._NativeReader', side_effect=AssertionError('Native creation forbidden')) as created:
            for path in (self.path(), '/api/native/task-response'):
                status, result, _ = self.request('POST', path, {'thread': 'parent', 'turn': 'captured'})
                self.assertEqual(status, 404)
                self.assertIn('error', result)
            self.assertEqual(self.request(headers={'X-Codex-Desk-Access': ''})[0], 403)
            self.assertEqual(self.request(headers={'Origin': 'https://foreign.example'})[0], 400)
            created.assert_not_called()
        self.assert_read_only(before, 0)

    def test_repeated_and_cold_read_do_not_run_replay_or_change_any_saved_state(self):
        before = self.state()
        first = self.request()[1]
        self.assertEqual(self.request()[1], first)
        self.assert_read_only(before, 2)
        self.stop_server()
        self.close_desk()
        self.desk = Desk(str(self.native), self.home, self.root / 'state')
        self.start_server()
        # Reopening Desk changes no persisted data and issues no native RPC.
        cold_before = self.state()
        self.assertEqual(cold_before['sql'], before['sql'])
        self.assertEqual(cold_before['sqlite'], before['sqlite'])
        self.assertIsNone(self.desk.native_reader)
        self.assertEqual(len(self.native_calls()), 4)
        self.assertEqual(self.request()[1], first)
        self.assert_read_only(cold_before, 3)
        self.assertEqual(sum(c['message']['method'] == 'initialize' for c in self.native_calls()), 2)

    def test_removed_original_project_needs_only_read_from_anchored_state_directory(self):
        for index in range(2):
            (self.root / ('project-' + str(index))).rmdir()
        before = self.state()
        self.assertEqual(self.request()[0], 200)
        self.assert_read_only(before, 1)

    def test_native_failure_is_not_replayed_and_retry_reads_only_captured_target(self):
        before = self.state()
        self.set_reply({'native_error': 'Native saved read unavailable'})
        status, result, _ = self.request()
        self.assertEqual(status, 400)
        self.assertEqual(result['error'], 'Native saved read unavailable')
        self.assert_read_only(before, 1)
        self.set_reply({'thread': self.source})
        self.assertEqual(self.request()[1]['response']['turn_id'], 'captured')
        self.assert_read_only(before, 2)

    def test_exited_reader_reopens_only_on_explicit_retry_without_store_changes(self):
        before = self.state()
        self.set_reply({'transport_exit': True})
        status, result, _ = self.request()
        self.assertEqual(status, 400)
        self.assertIn('Native history reader became unavailable', result['error'])
        self.assert_read_only(before, 1)
        old_reader = self.desk.native_reader
        self.assertTrue(old_reader.closing)
        self.set_reply({'thread': self.source})
        status, result, _ = self.request()
        self.assertEqual(status, 200)
        self.assertEqual(result['response']['turn_id'], 'captured')
        self.assertIsNot(self.desk.native_reader, old_reader)
        self.assert_read_only(before, 2)

    def test_backend_invalid_capture_validates_both_ids_before_read(self):
        before = self.state()
        with patch.object(self.desk, 'read_native') as read:
            for thread, turn in (('parent', None), ('parent', 2), ('parent', ' '), ('x'*201, 'captured')):
                with self.subTest(thread=thread, turn=turn), self.assertRaises(ValueError):
                    self.desk.task_response(thread, turn)
            read.assert_not_called()
        self.assert_read_only(before, 0)


if __name__ == '__main__':
    unittest.main()
