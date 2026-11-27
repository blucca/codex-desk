"""Completed native command/tool evidence replaces one pending recall result."""
import copy
import time
import unittest

from codex_desk.followups import add_followup
from codex_desk.handoff import visible_text
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.server import Desk
import test_bound_recall as fixture


class BoundCompletionTests(unittest.TestCase):
    # Reuse only the established native-free HTTP/Store fixture, not its tests.
    bind = fixture.BoundRecallTests.bind
    native_request = fixture.BoundRecallTests.native_request
    request = fixture.BoundRecallTests.request
    recall = fixture.BoundRecallTests.recall
    scan = fixture.BoundRecallTests.scan
    retained_state = fixture.BoundRecallTests.retained_state

    def setUp(self):
        fixture.BoundRecallTests.setUp(self)
        add_followup(self.desk.store, self.session, 'Review the patch after the remaining check', 'plan')

    def snapshot(self, item, *, turn_status='inProgress', stamp=None):
        stamp = self.meta['updatedAt'] if stamp is None else stamp
        turn = {'id': 'checks-turn', 'status': turn_status, 'startedAt': stamp, 'items': [copy.deepcopy(item)]}
        if turn_status != 'inProgress':
            turn['completedAt'] = stamp
        return {**self.meta, 'updatedAt': stamp,
                'status': {'type': 'active' if turn_status == 'inProgress' else 'idle'},
                'turns': [self.old, turn]}

    def event(self, method, **params):
        self.desk.store.event(self.session, {'method': method,
            'params': {'threadId': self.meta['id'], 'turnId': 'checks-turn', **params}})

    def assert_original(self, item, phrase):
        original = self.request('GET', '/api/native/thread?id=' + self.meta['id'])
        found = next(entry for turn in original['turns'] if turn['id'] == 'checks-turn'
                     for entry in turn['items'] if entry['id'] == item['id'])
        self.assertEqual(found, item)
        self.assertIn(phrase, visible_text(found))

    def finish(self, pending, final, phrase, *, active=False):
        self.phrase = phrase
        self.meta['status'] = {'type': 'active'}
        self.fresh = self.snapshot(pending)
        self.desk.store.recall_snapshot(self.session, self.fresh)
        self.assertEqual(self.scan()['indexed'], 1)
        self.assertEqual(self.recall()['total'], 0)
        before = self.retained_state()
        rows = self.desk.store.db.execute('SELECT * FROM recall_items ORDER BY turn_id,item_id').fetchall()
        self.meta['status'] = {'type': 'active' if active else 'idle'}
        self.fresh = self.snapshot(final, turn_status='inProgress' if active else 'completed')
        job = self.scan()
        self.assertEqual((job['indexed'], job['failed']), (1, 0))
        hits = self.recall()
        self.assertEqual(hits['total'], 1, hits)
        hit = hits['results'][0]
        self.assertEqual((hit['kind'], hit['session_id'], hit['thread_id'], hit['turn_id'], hit['item_id']),
            ('activity', self.session, self.meta['id'], 'checks-turn', final['id']))
        self.assertEqual(hit['match_text'], phrase)
        self.assertIn(phrase, hit['snippet'])
        self.assertEqual(hits['coverage']['activity_items'], len(rows))
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(self.desk.store.db.execute('SELECT * FROM recall_items ORDER BY turn_id,item_id').fetchall(), rows)
        self.assert_original(final, phrase)
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(self.desk.runtimes, {})
        self.runtime.assert_not_called()
        return hit

    def test_same_second_command_finish_exact_read_and_late_completion_stays_single(self):
        pending = {'id': 'command', 'type': 'commandExecution', 'command': 'pytest tests/test_retry.py -q',
                   'status': 'inProgress', 'exitCode': None, 'aggregatedOutput': 'Collecting retry tests\n'}
        final = {**pending, 'status': 'completed', 'exitCode': 0,
                 'aggregatedOutput': 'Collecting retry tests\nretry budget remains three attempts: 12 passed.\n'}
        phrase = 'retry budget remains three attempts'
        self.assertFalse(visible_text(final).startswith(visible_text(pending)))
        hit = self.finish(pending, final, phrase)
        self.assertEqual(self.recall(q='Status: inProgress')['total'], 0)
        self.assertEqual(self.recall(q='Exit: 0')['total'], 1)
        self.assertEqual(self.scan()['skipped'], 1)
        self.assertEqual(self.recall()['results'], [hit])
        # Completion switches authority to the ordinary local row, not a second
        # native result. Late output deltas still cannot duplicate completed text.
        self.event('item/completed', item=final)
        self.event('item/commandExecution/outputDelta', itemId='command', delta=phrase)
        result = self.recall()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['results'][0]['snippet'].count(phrase), 1)

    def test_command_failure_declined_and_interrupted_outcomes(self):
        for status, exit_code, phrase in (
                ('failed', 1, 'Checkout timeout assertion failed'),
                ('declined', None, 'Checkout command was declined'),
                ('interrupted', None, 'Checkout command was interrupted')):
            with self.subTest(status=status):
                pending = {'id': 'command-' + status, 'type': 'commandExecution', 'command': 'pytest checkout',
                           'status': 'inProgress', 'aggregatedOutput': 'Starting checkout check'}
                final = {**pending, 'status': status, 'exitCode': exit_code, 'aggregatedOutput': phrase}
                self.finish(pending, final, phrase)
                self.assertEqual(self.recall(q='Status: ' + status)['total'], 1)

    def test_completed_mcp_dynamic_file_and_collaboration_formats(self):
        cases = [
            ({'id': 'mcp', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'inspect',
              'status': 'inProgress', 'arguments': {'case': 'retry'}, 'result': None},
             {'status': 'completed', 'result': {'content': [{'type': 'text', 'text': 'Retry cursor stays stable'}],
                 'structuredContent': {'decision': 'Cursor reconstruction can be skipped'}, '_meta': {'private': 'PRIVATE-MARKER'}}},
             'Cursor reconstruction can be skipped'),
            ({'id': 'mcp-error', 'type': 'mcpToolCall', 'server': 'local', 'tool': 'inspect',
              'status': 'inProgress', 'arguments': {'case': 'timeout'}},
             {'status': 'failed', 'error': {'message': 'Timeout inspection unavailable; retry this check'}},
             'Timeout inspection unavailable'),
            ({'id': 'dynamic', 'type': 'dynamicToolCall', 'namespace': 'local', 'tool': 'inspect',
              'status': 'inProgress', 'arguments': {'case': 'replay'}},
             {'status': 'completed', 'success': False, 'contentItems': [
                 {'type': 'inputText', 'text': 'Replay result needs the timeout check'},
                 {'type': 'inputImage', 'imageUrl': 'data:image/png;base64,PRIVATE-MEDIA'}]},
             'Replay result needs the timeout check'),
            ({'id': 'patch', 'type': 'fileChange', 'status': 'inProgress', 'changes': []},
             {'status': 'completed', 'changes': [{'path': 'retry.py', 'diff': '+RETRY_BUDGET = 3'}]},
             'RETRY_BUDGET = 3'),
            ({'id': 'child', 'type': 'collabAgentToolCall', 'tool': 'wait', 'status': 'inProgress',
              'senderThreadId': self.meta['id'], 'receiverThreadIds': ['child-thread'], 'agentsStates': {}},
             {'status': 'completed', 'agentsStates': {'child-thread':
                 {'status': 'completed', 'message': 'Child verification accepted the retry budget'}}},
             'Child verification accepted the retry budget'),
        ]
        for pending, update, phrase in cases:
            with self.subTest(kind=pending['type'], item=pending['id']):
                self.finish(pending, {**pending, **update}, phrase)
        self.assertEqual(self.recall(q='PRIVATE-MARKER')['total'], 0)
        self.assertEqual(self.recall(q='PRIVATE-MEDIA')['total'], 0)

    def test_completed_tool_in_active_turn_uses_capture_time_not_old_turn_start(self):
        pending = {'id': 'active-command', 'type': 'commandExecution', 'command': 'pytest retry',
                   'status': 'inProgress', 'aggregatedOutput': 'Collecting tests\n'}
        self.desk.store.recall_snapshot(self.session, self.snapshot(pending))
        self.event('item/commandExecution/outputDelta', itemId=pending['id'], delta='Collected retry tests\n')
        local_stamp = self.desk.store.db.execute('SELECT updated FROM recall_items WHERE item_id=?', (pending['id'],)).fetchone()[0]
        final = {**pending, 'status': 'completed', 'exitCode': 0,
                 'aggregatedOutput': 'Collected retry tests\nActive command confirms the retry budget'}
        self.fresh = self.snapshot(final)
        self.scan()
        self.assertLess(self.desk.store.db.execute('SELECT updated FROM native_recall_items WHERE item_id=?', (pending['id'],)).fetchone()[0], local_stamp)
        self.assertEqual(self.recall(q='Active command confirms the retry budget')['total'], 1)
        self.assertTrue(self.desk.native_index.needs_snapshot(self.meta))

    def test_completed_plan_and_normalized_literal_match_keep_exact_source(self):
        pending = {'id': 'proposed-plan', 'type': 'plan', 'text': 'Investigate checkout retry behavior'}
        final = {**pending, 'text': 'Skip the retry reconstruction; inspect only timeout handling.\nCafe\u0301 retry a%b_c[0].*'}
        self.finish(pending, final, 'inspect only timeout handling')
        for query, expected in [('CAFÉ', 'Cafe\u0301'), ('a%b_c[0].*', 'a%b_c[0].*')]:
            hit = self.recall(q=query)
            self.assertEqual(hit['total'], 1)
            self.assertEqual(hit['results'][0]['item_id'], final['id'])
            self.assertEqual(hit['results'][0]['match_text'], expected)
            self.assertIn(expected, visible_text(final))
        self.assertEqual(self.recall(q='a%bZc')['total'], 0)

    def test_complete_and_newer_local_evidence_win_over_cached_terminal(self):
        pending = {'id': 'owned-command', 'type': 'commandExecution', 'command': 'pytest retry',
                   'status': 'inProgress', 'aggregatedOutput': 'Local pending output\n'}
        native = {**pending, 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'Native final evidence'}
        self.desk.store.recall_snapshot(self.session, self.snapshot(pending))
        self.fresh = self.snapshot(native, turn_status='completed')
        self.scan()
        future = time.time() + 10
        self.desk.store.event(self.session, {'method': 'item/commandExecution/outputDelta', 'emittedAtMs': future * 1000,
            'params': {'threadId': self.meta['id'], 'turnId': 'checks-turn', 'itemId': pending['id'], 'delta': 'Newer local evidence'}})
        self.assertEqual(self.recall(q='Newer local evidence')['total'], 1)
        self.assertEqual(self.recall(q='Native final evidence')['total'], 0)
        local = {**native, 'aggregatedOutput': 'Completed local evidence'}
        self.event('item/completed', item=local)
        self.assertEqual(self.recall(q='Completed local evidence')['total'], 1)
        self.assertEqual(self.recall(q='Native final evidence')['total'], 0)

    def test_in_progress_or_shortened_native_text_does_not_replace_local(self):
        pending = {'id': 'running-command', 'type': 'commandExecution', 'command': 'pytest retry',
                   'status': 'inProgress', 'aggregatedOutput': 'Pending local evidence'}
        self.desk.store.recall_snapshot(self.session, self.snapshot(pending))
        self.fresh = self.snapshot({**pending, 'aggregatedOutput': 'Native unfinished evidence'}, turn_status='failed')
        self.scan()
        self.assertEqual(self.recall(q='Pending local evidence')['total'], 1)
        self.assertEqual(self.recall(q='Native unfinished evidence')['total'], 0)
        self.assertEqual(self.desk.store.db.execute('SELECT complete FROM native_recall_items WHERE item_id=?', (pending['id'],)).fetchone()[0], 0)
        final = {**pending, 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'Native final evidence ' * 100}
        index = NativeRecallIndex(self.desk.store, max_thread_chars=100)
        self.assertGreater(index.replace_snapshot(self.snapshot(final, turn_status='completed'))['shortened_items'], 0)
        self.assertEqual(self.recall(q='Pending local evidence')['total'], 1)
        self.assertEqual(self.recall(q='Native final evidence')['total'], 0)

    def test_duplicate_exact_native_identity_and_archive_project_scope(self):
        pending = {'id': 'scope-command', 'type': 'commandExecution', 'command': 'pytest retry',
                   'status': 'inProgress', 'aggregatedOutput': 'Collecting'}
        final = {**pending, 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'Scoped retry budget accepted'}
        hit = self.finish(pending, final, 'Scoped retry budget accepted')
        self.assertEqual(self.desk.native_index.search(self.phrase)['total'], 1)
        self.assertEqual(self.recall()['results'], [hit])
        self.assertEqual(self.recall(cwd=str(self.root))['total'], 0)
        self.desk.store.archive(self.session, True)
        self.assertEqual(self.recall()['total'], 0)
        self.assertEqual(self.recall(archived='true', cwd=str(self.project))['total'], 1)

    def test_old_cache_upgrade_retains_text_and_preparation_requires_one_explicit_read(self):
        pending = {'id': 'upgrade-command', 'type': 'commandExecution', 'command': 'pytest retry',
                   'status': 'inProgress', 'aggregatedOutput': 'Collecting'}
        final = {**pending, 'status': 'completed', 'exitCode': 0, 'aggregatedOutput': 'Upgrade retry budget accepted'}
        self.desk.store.recall_snapshot(self.session, self.snapshot(pending))
        self.fresh = self.snapshot(final, turn_status='completed')
        self.desk.native_index.replace_snapshot(self.fresh)
        self.assertFalse(self.desk.native_index.needs_snapshot(self.meta))
        self.desk.store.db.execute('ALTER TABLE native_recall_items DROP COLUMN complete')
        self.desk.store.db.commit()
        before = self.retained_state()
        self.calls.clear()
        cold = Desk('never-executed', self.root / 'home', self.root / 'state')
        try:
            self.assertEqual(self.calls, [])
            self.assertIsNone(cold.history_scanner.worker)
            self.assertEqual(cold.runtimes, {})
            self.assertEqual(self.retained_state(), before)
            self.assertTrue(cold.native_index.needs_snapshot(self.meta))
            self.assertEqual(cold.native_index.search('Upgrade retry budget accepted')['total'], 1)
            self.assertEqual(self.recall(desk=cold, q='Upgrade retry budget accepted')['total'], 0)
            cold.catalog = self.desk.catalog
            self.request('POST', '/api/history/index', {}, desk=cold)
            cold.history_scanner.worker.join(3)
            self.assertFalse(cold.history_scanner.worker.is_alive())
            self.assertEqual(self.recall(desk=cold, q='Upgrade retry budget accepted')['total'], 1)
            self.assertFalse(cold.native_index.needs_snapshot(self.meta))
            self.assertEqual([method for method, _ in self.calls], ['thread/list', 'thread/read'])
            self.assertEqual(self.retained_state(), before)
            self.calls.clear()
            self.request('POST', '/api/history/index', {}, desk=cold)
            cold.history_scanner.worker.join(3)
            self.assertEqual([method for method, _ in self.calls], ['thread/list'])
            self.assertEqual(self.recall(desk=cold, q='Upgrade retry budget accepted')['total'], 1)
        finally:
            cold.close()
            cold.store.db.close()
        self.runtime.assert_not_called()


if __name__ == '__main__':
    unittest.main()
