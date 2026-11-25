"""Parent isolation using shapes from the CLI 0.171 collaboration capture."""
import json
import os
from pathlib import Path
import queue
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from codex_desk.runtime import Runtime, Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)
PARENT = '01a2139e-e34c-7433-871d-43628ef2008e'
PARENT_TURN = '01a2139e-e36b-7150-8034-736af5c50a9e'
CHILD = '01a2139e-fd73-7313-bcb9-588f7be9deb9'
CHILD_TURN = '01a2139e-fd81-7b51-8d95-4ccce306d0f8'
OTHER_CHILD = '01a2139f-345d-70b2-81a2-6fb1af2e15c7'


def turn_event(thread_id=PARENT, completed=False):
    # The child has its own turn ID even though rootTurnId names the parent.
    turn = {'id': PARENT_TURN if thread_id == PARENT else CHILD_TURN,
            'rootTurnId': PARENT_TURN, 'items': [], 'itemsView': 'notLoaded',
            'status': 'inProgress', 'error': None, 'startedAt': 1795625516,
            'completedAt': None, 'durationMs': None}
    if completed:
        turn.update(items=[{'type': 'agentMessage', 'id': 'child-message',
                           'text': 'Unable to determine LINE_COUNT: the command failed.', 'phase': 'final_answer'}],
                    itemsView='summary', status='completed', completedAt=1795625536, durationMs=19732)
    return {'method': 'turn/completed' if completed else 'turn/started',
            'params': {'threadId': thread_id, 'turn': turn}, 'emittedAtMs': 1795625536000}


class RuntimeCollaborationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name)
        self.store = Store(self.path / 'desk.sqlite3')
        self.addCleanup(self.store.db.close)
        self.identifier = self.store.create(str(self.path), 'default', name='Parent task')
        self.store.update(self.identifier, thread_id=PARENT, status='running', model='reported-model',
                          usage=json.dumps({'total': {'totalTokens': 10702}}), thread_saved=1)
        self.runtime = object.__new__(Runtime)
        self.runtime.store, self.runtime.id, self.runtime.home = self.store, self.identifier, self.path
        self.runtime.approvals, self.runtime.pending = {}, {}
        self.runtime.persisted, self.runtime.closing = False, False
        self.runtime.lock = threading.Lock()
        self.runtime.lifecycle_lock = threading.Lock()
        self.runtime.turn_lock = threading.Lock()
        self.runtime.name_lock = threading.RLock()
        self.runtime.send = Mock()
        self.runtime.request = Mock(return_value={'turn': {'id': 'next-turn', 'status': 'inProgress'}})
        self.runtime._flush_name = Mock()

    def row(self):
        return self.store.get(self.identifier)

    def receive(self, message):
        with self.runtime.lifecycle_lock:
            self.runtime._message(message)

    def approval(self, request_id, thread_id=PARENT, method='item/commandExecution/requestApproval'):
        params = {'threadId': thread_id, 'turnId': PARENT_TURN if thread_id == PARENT else CHILD_TURN,
                  'itemId': 'command-item', 'startedAtMs': 1795625521485}
        if method == 'item/tool/requestUserInput':
            params.pop('startedAtMs')
            params.update(isBlocking=True, questions=[{'id': 'mode', 'header': 'Mode', 'question': 'Continue?',
                          'options': [{'label': 'Yes', 'description': 'Continue the read check'}]}])
        elif method == 'item/commandExecution/requestApproval':
            params.update(command='cat lines.txt', cwd=str(self.path), reason=None, approvalId=None)
        message = {'id': request_id, 'method': method, 'params': params}
        self.receive(message)
        return message

    def resolved(self, request_id, thread_id=CHILD):
        return {'method': 'serverRequest/resolved', 'params': {'threadId': thread_id, 'requestId': request_id}}

    def test_actual_child_turn_boundaries_cannot_complete_or_unblock_parent(self):
        self.approval(91)
        before = self.row()
        events = self.store.events(self.identifier)
        self.receive(turn_event(CHILD))
        self.receive(turn_event(CHILD, completed=True))
        self.assertEqual(self.row(), before)
        self.assertEqual(self.store.events(self.identifier), events)
        self.assertEqual(set(self.runtime.approvals), {'91'})
        self.assertFalse(self.runtime.persisted)
        self.runtime._flush_name.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'Finish or stop'):
            self.runtime.turn('Too early')
        self.runtime.request.assert_not_called()

    def test_foreign_scoped_items_status_usage_and_names_are_not_parent_evidence(self):
        events = [
            {'method': 'thread/status/changed', 'params': {'threadId': CHILD, 'status': {'type': 'active', 'activeFlags': []}}},
            {'method': 'thread/tokenUsage/updated', 'params': {'threadId': CHILD, 'turnId': CHILD_TURN,
                'tokenUsage': {'total': {'totalTokens': 11618, 'inputTokens': 11541}, 'last': {'outputTokens': 77}, 'modelContextWindow': 828400}}},
            {'method': 'item/completed', 'params': {'threadId': CHILD, 'turnId': CHILD_TURN,
                'item': {'id': 'child-command', 'type': 'commandExecution', 'status': 'failed', 'exitCode': 127,
                         'aggregatedOutput': 'zsh: command not found'}}},
            {'method': 'item/agentMessage/delta', 'params': {'threadId': CHILD, 'turnId': CHILD_TURN, 'itemId': 'child-message', 'delta': 'child result'}},
            {'method': 'thread/name/updated', 'params': {'threadId': CHILD, 'threadName': 'Child name'}},
            {'method': 'thread/started', 'params': {'thread': {'id': CHILD, 'status': {'type': 'idle'}, 'name': None}}},
        ]
        before = self.row()
        for event in events:
            self.receive(event)
        self.assertEqual(self.row(), before)
        self.assertEqual(self.store.events(self.identifier), [])

    def test_parent_collaboration_items_and_cumulative_usage_remain_visible(self):
        item = {'method': 'item/completed', 'params': {'threadId': PARENT, 'turnId': PARENT_TURN,
            'item': {'type': 'subAgentActivity', 'id': 'call-start', 'kind': 'started', 'agentThreadId': CHILD,
                     'agentPath': '/root/line_check', 'model': 'gpt-6.1-sol', 'reasoningEffort': 'low'}}}
        self.receive(item)
        usage = {'total': {'totalTokens': 21509}, 'last': {'totalTokens': 10807}, 'modelContextWindow': 828400}
        event = {'method': 'thread/tokenUsage/updated', 'params': {'threadId': PARENT, 'turnId': PARENT_TURN, 'tokenUsage': usage}}
        self.receive(event)
        self.receive(event)
        self.assertEqual(json.loads(self.row()['usage']), usage)
        self.assertEqual([r['event'] for r in self.store.events(self.identifier)], [item, event, event])

    def test_child_completion_retires_only_its_exact_requests(self):
        self.approval(91)
        self.approval('child-command', CHILD)
        self.approval('child-question', CHILD, 'item/tool/requestUserInput')
        self.approval('other-command', OTHER_CHILD)
        events = self.store.events(self.identifier)
        self.receive(turn_event(CHILD, completed=True))
        self.assertEqual(set(self.runtime.approvals), {'91', 'other-command'})
        self.assertEqual(self.row()['status'], 'approval')
        self.assertEqual(self.store.events(self.identifier), events)
        self.runtime._flush_name.assert_not_called()
        self.assertFalse(self.runtime.persisted)
        with self.assertRaisesRegex(ValueError, 'no longer pending'):
            self.runtime.approve('child-command', 'accept')

    def test_only_child_approval_retirement_restores_running_not_completed(self):
        self.approval('child-command', CHILD)
        before = self.row()
        self.receive(turn_event(CHILD, completed=True))
        self.assertEqual(self.runtime.approvals, {})
        self.assertEqual(self.row()['status'], 'running')
        for key in ('name', 'name_pending', 'thread_id', 'usage', 'error', 'thread_saved'):
            self.assertEqual(self.row()[key], before[key])
        with self.assertRaisesRegex(ValueError, 'Finish or stop'):
            self.runtime.turn('Parent still busy')
        self.assertFalse(self.runtime.persisted)

    def test_child_server_requests_keep_original_id_types_and_response_routing(self):
        command = self.approval(93, CHILD)
        question = self.approval('question-native-id', CHILD, 'item/tool/requestUserInput')
        self.assertEqual(self.runtime.approvals['93'], command)
        self.assertEqual(self.runtime.approvals['question-native-id'], question)
        self.assertEqual(self.row()['status'], 'approval')
        self.runtime.approve('93', 'accept')
        self.assertEqual(self.row()['status'], 'approval')
        self.runtime.answer('question-native-id', {'mode': ['Yes']})
        self.assertEqual(self.runtime.send.call_args_list[0].args[0], {'id': 93, 'result': {'decision': 'accept'}})
        self.assertEqual(self.runtime.send.call_args_list[1].args[0], {'id': 'question-native-id', 'result': {'answers': {'mode': {'answers': ['Yes']}}}})
        self.assertEqual(self.row()['status'], 'running')

    def test_known_child_resolution_is_retained_unknown_foreign_resolution_is_dropped(self):
        self.approval(91)
        self.approval('child-command', CHILD)
        known = self.resolved('child-command')
        self.receive(known)
        self.assertEqual(set(self.runtime.approvals), {'91'})
        self.assertEqual(self.row()['status'], 'approval')
        self.assertEqual(self.store.events(self.identifier)[-1]['event'], known)
        events = self.store.events(self.identifier)
        self.receive(known)
        self.receive(self.resolved('unknown-child-request'))
        self.assertEqual(self.store.events(self.identifier), events)
        self.receive(self.resolved(91))
        self.assertEqual(self.runtime.approvals, {})
        self.assertEqual(self.row()['status'], 'running')

    def test_parent_completion_retires_all_owned_requests_and_flushes_only_parent(self):
        self.approval(91)
        self.approval('child-command', CHILD)
        self.approval('other-command', OTHER_CHILD)
        complete = turn_event(completed=True)
        with patch('codex_desk.runtime.threading.Thread') as worker:
            self.receive(complete)
            worker.assert_called_once_with(target=self.runtime._flush_name, daemon=True)
            worker.return_value.start.assert_called_once()
        self.assertEqual(self.row()['status'], 'completed')
        self.assertEqual(self.runtime.approvals, {})
        self.assertTrue(self.runtime.persisted)
        before = self.row()
        self.receive(turn_event(CHILD, completed=True))
        self.receive(self.resolved('child-command'))
        self.assertEqual(self.row(), before)
        self.assertEqual(self.store.events(self.identifier)[-1]['event'], complete)

    def test_late_child_requests_and_answers_never_revive_terminal_parent(self):
        for status in ('completed', 'failed', 'interrupted', 'ready'):
            with self.subTest(status=status):
                self.store.update(self.identifier, status=status, error='Keep parent outcome')
                before = self.row()
                self.approval(93, CHILD)
                self.approval('child-question', CHILD, 'item/tool/requestUserInput')
                self.assertEqual(self.row(), before)
                self.runtime.approve(93, 'decline')
                self.runtime.answer('child-question', {'mode': ['Yes']})
                self.assertEqual(self.row(), before)
                self.approval('retired-at-child-finish', CHILD)
                self.receive(turn_event(CHILD, completed=True))
                self.assertEqual(self.runtime.approvals, {})
                self.assertEqual(self.row(), before)
                self.approval('resolved-late', CHILD)
                self.receive(self.resolved('resolved-late'))
                self.assertEqual(self.row(), before)

    def test_jsonrpc_responses_bypass_thread_filter_and_remain_unstored(self):
        for message in ({'id': 7, 'result': {'thread': {'id': CHILD}}},
                        {'id': 7, 'error': {'message': 'Native rejection'}, 'params': {'threadId': CHILD}}):
            target = queue.Queue(maxsize=1)
            self.runtime.pending[7] = target
            self.receive(message)
            self.assertEqual(target.get_nowait(), message)
        self.assertEqual(self.store.events(self.identifier), [])

    def test_old_unscoped_and_null_scoped_notifications_remain_compatible(self):
        global_event = {'method': 'account/rateLimits/updated', 'params': {'rateLimits': {'limitId': 'codex'}}}
        self.receive(global_event)
        self.receive({'method': 'remoteControl/status/changed', 'params': None})
        for thread_id in ('missing', None):
            started = turn_event()
            if thread_id == 'missing':
                started['params'].pop('threadId')
            else:
                started['params']['threadId'] = None
            self.receive(started)
            self.assertEqual(self.row()['status'], 'running')
        self.assertEqual(len(self.store.events(self.identifier)), 4)
        self.assertEqual(self.store.events(self.identifier)[0]['event'], global_event)

    def test_attach_notifications_before_binding_are_retained_without_inventing_a_binding(self):
        self.store.update(self.identifier, thread_id=None, status='starting')
        started = {'method': 'thread/started', 'params': {'thread': {'id': PARENT, 'status': {'type': 'idle'}, 'name': None}}}

        def attach_response(method, params):
            self.assertEqual(method, 'thread/start')
            self.receive(started)
            self.assertIsNone(self.row()['thread_id'])
            return {'thread': {'id': PARENT, 'turns': []}, 'model': 'reported-model', 'modelProvider': 'custom'}

        self.runtime.request.side_effect = attach_response
        result = self.runtime.attach()
        self.assertEqual(result['thread']['id'], PARENT)
        self.assertEqual(self.row()['thread_id'], PARENT)
        self.assertEqual(self.row()['status'], 'ready')
        self.assertEqual(self.store.events(self.identifier)[0]['event'], started)
        events = self.store.events(self.identifier)
        self.receive(turn_event(CHILD))
        self.assertEqual(self.store.events(self.identifier), events)

    def test_stop_uses_parent_turn_even_with_existing_cached_child_turn_events(self):
        self.store.event(self.identifier, turn_event())
        self.store.event(self.identifier, turn_event(CHILD))
        self.runtime.interrupt()
        self.runtime.request.assert_called_once_with('turn/interrupt', {'threadId': PARENT, 'turnId': PARENT_TURN})


if __name__ == '__main__':
    unittest.main()
