"""Explicit scan catch-up for bound native evidence without tasks or sockets."""
from email.message import Message
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlencode

from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.server import Desk, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


def turn(identifier, text, item='answer', status='completed'):
    return {'id': identifier, 'status': status, 'completedAt': 1795600010,
            'items': [{'id': item, 'type': 'agentMessage', 'text': text}]}


class BoundRecallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-bound-recall-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        runtime = patch('codex_desk.server.Runtime', side_effect=AssertionError('Unexpected native runtime'))
        self.runtime = runtime.start()
        self.addCleanup(runtime.stop)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(lambda: self.desk.store.db.close())
        self.addCleanup(self.desk.close)
        self.project = self.root / 'project'
        self.meta = {'id': 'retained-native-thread', 'cwd': str(self.project),
                     'name': 'Retry decision', 'modelProvider': 'fixture', 'updatedAt': 1795600010}
        self.old = turn('old-turn', 'Initial retry behavior accepted.', 'old-answer')
        self.phrase = 'retry budget remains three attempts'
        self.new = turn('outside-desk-turn', self.phrase, 'outside-desk-answer')
        self.fresh = {**self.meta, 'turns': [self.old, self.new]}
        self.session = self.bind(self.project, 'default')
        self.desk.store.recall_snapshot(self.session, {**self.meta, 'turns': [self.old]})
        save_draft(self.desk.store, self.session, 'Review preparation tomorrow', 'plan', 0)
        add_followup(self.desk.store, self.session, 'Inspect prepared tests', 'native')
        self.calls = []
        self.catalog = Mock(spec=['request'])
        self.catalog.request.side_effect = self.native_request
        catalog = patch.object(self.desk, 'catalog', return_value=self.catalog)
        catalog.start()
        self.addCleanup(catalog.stop)

    def bind(self, project, profile, thread_id='retained-native-thread', identifier=None):
        session = self.desk.store.create(str(project), profile, identifier=identifier, name='Saved work')
        self.desk.store.update(session, thread_id=thread_id, status='saved', thread_saved=1)
        return session

    def native_request(self, method, params):
        self.calls.append((method, dict(params)))
        if method == 'thread/list':
            return {'data': [self.meta], 'nextCursor': None}
        if method == 'thread/read':
            self.assertEqual(params, {'threadId': self.meta['id'], 'includeTurns': True})
            return {'thread': self.fresh}
        raise AssertionError('Unexpected native method: ' + method)

    def request(self, method, path, payload=None, desk=None):
        instance = object.__new__(handler(desk or self.desk))
        instance.path = path
        instance.server = Mock(server_port=18787)
        instance.headers = Message()
        instance.headers['Host'] = '127.0.0.1:18787'
        if payload is not None:
            data = json.dumps(payload).encode()
            instance.headers['Content-Type'] = 'application/json'
            instance.headers['Content-Length'] = str(len(data))
            instance.rfile = io.BytesIO(data)
        replies = []
        instance.reply = lambda value, status=200: replies.append((status, value))
        getattr(instance, 'do_' + method)()
        self.assertEqual(len(replies), 1)
        self.assertEqual(replies[0][0], 200)
        return replies[0][1]

    def recall(self, desk=None, **query):
        return self.request('GET', '/api/recall?' + urlencode({'q': self.phrase, **query}), desk=desk)

    def scan(self):
        self.request('POST', '/api/history/index', {})
        self.desk.history_scanner.worker.join(3)
        self.assertFalse(self.desk.history_scanner.worker.is_alive())
        return self.request('GET', '/api/history/index')['job']

    def retained_state(self):
        with self.desk.store.lock:
            return {name: self.desk.store.db.execute('SELECT * FROM ' + name).fetchall()
                    for name in ('sessions', 'events', 'recall_turns', 'recall_checkpoints',
                                 'drafts', 'followups', 'followup_reservations')}

    def test_explicit_fresh_scan_finds_outside_answer_with_exact_ids_and_preserves_preparation(self):
        before = self.retained_state()
        old_rows = self.desk.store.db.execute('SELECT * FROM recall_items').fetchall()
        with patch.object(self.desk, 'open') as opened, patch.object(self.desk, 'import_thread') as imported:
            self.assertEqual(self.recall()['total'], 0)
            job = self.scan()
            result = self.recall()
            opened.assert_not_called()
            imported.assert_not_called()
        self.assertEqual((job['status'], job['seen'], job['indexed'], job['skipped'], job['failed']),
                         ('completed', 1, 1, 0, 0))
        self.assertEqual(result['total'], 1)
        hit = result['results'][0]
        self.assertEqual((hit['kind'], hit['session_id'], hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('activity', self.session, self.meta['id'], self.new['id'], 'outside-desk-answer'))
        self.assertEqual(hit['match_text'], self.phrase)
        self.assertEqual(self.recall(q='Initial retry behavior')['total'], 1)
        self.assertEqual(result['coverage']['activity_items'], 2)
        self.assertEqual(self.retained_state(), before)
        self.assertIn(old_rows[0], self.desk.store.db.execute('SELECT * FROM recall_items').fetchall())
        self.assertEqual([method for method, _ in self.calls], ['thread/list', 'thread/read'])
        dump = list(self.desk.store.db.iterdump())
        self.assertEqual(self.recall()['results'], result['results'])
        self.assertEqual(list(self.desk.store.db.iterdump()), dump)
        self.assertEqual(self.desk.runtimes, {})
        self.runtime.assert_not_called()

    def test_pre_fix_fresh_native_cache_repairs_on_list_only_scan_and_survives_cold_reopen(self):
        self.desk.native_index.replace_snapshot(self.fresh)
        self.assertFalse(self.desk.native_index.needs_snapshot(self.meta))
        dump = list(self.desk.store.db.iterdump())
        self.assertEqual(self.recall()['total'], 0)
        self.assertEqual(self.desk.native_index.search(self.phrase)['total'], 1)
        self.assertEqual(list(self.desk.store.db.iterdump()), dump)
        before = self.retained_state()
        job = self.scan()
        self.assertEqual((job['status'], job['indexed'], job['skipped'], job['failed']), ('completed', 0, 1, 0))
        self.assertEqual([method for method, _ in self.calls], ['thread/list'])
        result = self.recall()
        self.assertEqual(result['total'], 1)
        self.assertEqual(self.retained_state(), before)
        self.calls.clear()
        self.assertEqual(self.scan()['skipped'], 1)
        self.assertEqual(self.recall()['results'], result['results'])
        self.assertEqual([method for method, _ in self.calls], ['thread/list'])
        cold = Desk('never-executed', self.root / 'home', self.root / 'state')
        try:
            before = list(cold.store.db.iterdump())
            with patch.object(cold, 'catalog') as catalog, patch.object(cold, 'open') as opened:
                self.assertEqual(self.recall(desk=cold)['results'], result['results'])
                catalog.assert_not_called()
                opened.assert_not_called()
            self.assertEqual(list(cold.store.db.iterdump()), before)
            self.assertIsNone(cold.history_scanner.worker)
        finally:
            cold.close()
            cold.store.db.close()
        self.runtime.assert_not_called()

    def test_archived_new_answer_keeps_local_visibility_and_exact_project_scope(self):
        self.desk.store.archive(self.session, True)
        self.assertEqual(self.scan()['indexed'], 1)
        self.assertEqual(self.recall()['total'], 0)
        archived = self.recall(cwd=str(self.project / '..' / 'project'), archived='true')
        self.assertEqual(archived['total'], 1)
        hit = archived['results'][0]
        self.assertEqual((hit['session_id'], hit['thread_id'], hit['archived']),
                         (self.session, self.meta['id'], True))
        for project in (self.root, self.project / 'child', self.root / 'other'):
            self.assertEqual(self.recall(cwd=str(project), archived='true')['total'], 0)

    def test_two_scans_search_incomplete_reply_growth_without_rewriting_live_evidence(self):
        store = self.desk.store
        partial = 'The retry review is complete. '
        final = partial + self.phrase
        local = [turn('complete-turn', 'Completed local choice'),
                 turn('conflict-turn', 'Different local choice', status='inProgress'),
                 turn('longer-turn', 'Longer local choice stays available', status='inProgress')]
        store.recall_snapshot(self.session, {**self.meta, 'turns': local})
        native = [turn('complete-turn', 'Completed local choice with native completion tail'),
                  turn('conflict-turn', 'Different native choice with native conflict tail'),
                  turn('longer-turn', 'Longer local choice')]
        self.meta['updatedAt'] += 10
        self.new = turn('outside-desk-turn', partial, 'outside-desk-answer', 'inProgress')
        self.new.pop('completedAt')
        self.new['startedAt'] = self.meta['updatedAt']
        self.fresh = {**self.meta, 'turns': [self.old, *native, self.new]}
        self.assertEqual(self.scan()['indexed'], 1)
        self.assertEqual(self.recall()['total'], 0)
        rows = store.db.execute('SELECT * FROM recall_items ORDER BY turn_id,item_id').fetchall()
        before = self.retained_state()
        self.meta['updatedAt'] += 10
        self.new['status'] = 'completed'
        self.new['completedAt'] = self.meta['updatedAt']
        self.new['items'][0]['text'] = final
        self.fresh = {**self.meta, 'turns': [self.old, *native, self.new]}
        self.assertEqual(self.scan()['indexed'], 1)
        result = self.recall()
        self.assertEqual(result['total'], 1)
        hit = result['results'][0]
        self.assertEqual((hit['kind'], hit['session_id'], hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('activity', self.session, self.meta['id'], self.new['id'], 'outside-desk-answer'))
        self.assertEqual((hit['match_text'], hit['updated']), (self.phrase, self.meta['updatedAt']))
        self.assertEqual(result['coverage']['activity_items'], len(rows))
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(store.db.execute('SELECT * FROM recall_items ORDER BY turn_id,item_id').fetchall(), rows)
        dump = list(store.db.iterdump())
        for query, count in [('native completion tail', 0), ('native conflict tail', 0),
                             ('Completed local choice', 1), ('Different local choice', 1),
                             ('stays available', 1)]:
            self.assertEqual(self.recall(q=query)['total'], count, query)
        self.assertEqual(list(store.db.iterdump()), dump)
        self.calls.clear()
        self.assertEqual(self.scan()['skipped'], 1)
        self.assertEqual(self.recall()['results'], result['results'])
        self.assertEqual([method for method, _ in self.calls], ['thread/list'])
        self.assertEqual(list(store.db.iterdump()), dump)
        cold = Desk('never-executed', self.root / 'home', self.root / 'state')
        try:
            cold_dump = list(cold.store.db.iterdump())
            with patch.object(cold, 'catalog') as catalog, patch.object(cold, 'open') as opened:
                self.assertEqual(self.recall(desk=cold)['results'], result['results'])
                catalog.assert_not_called()
                opened.assert_not_called()
            self.assertEqual(list(cold.store.db.iterdump()), cold_dump)
        finally:
            cold.close()
            cold.store.db.close()
        self.assertEqual(self.recall(cwd=str(self.root))['total'], 0)
        store.archive(self.session, True)
        self.assertEqual(self.recall()['total'], 0)
        self.assertEqual(self.recall(archived='true')['total'], 1)
        store.archive(self.session, False)
        # Live deltas still append to the original partial row, not the search overlay.
        live_stamp = self.meta['updatedAt'] + 10
        delta = {'method': 'item/agentMessage/delta', 'emittedAtMs': live_stamp * 1000, 'params': {
            'threadId': self.meta['id'], 'turnId': self.new['id'],
            'itemId': 'outside-desk-answer', 'delta': self.phrase[:5]}}
        store.event(self.session, delta)
        self.assertEqual(self.recall()['results'][0]['updated'], live_stamp)
        delta['params']['delta'] = self.phrase[5:]
        store.event(self.session, delta)
        row = store.db.execute('''SELECT visible_text,complete FROM recall_items
            WHERE session_id=? AND turn_id=? AND item_id=?''',
            (self.session, self.new['id'], 'outside-desk-answer')).fetchone()
        self.assertEqual(row, ('Codex\n' + final, 0))
        result = self.recall()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['results'][0]['snippet'].count(self.phrase), 1)
        self.runtime.assert_not_called()

    def test_helper_preserves_existing_complete_streaming_longer_omitted_and_local_only_rows(self):
        store = self.desk.store
        local = [turn('stream-turn', 'Longer streaming evidence remains local', status='inProgress'),
                 turn('omitted-turn', 'Old retained evidence omitted by native cap'),
                 turn('local-only-turn', 'Local only evidence')]
        store.recall_snapshot(self.session, {**self.meta, 'turns': local})
        sidecar = self.bind(self.root / 'other', 'sidecar:work')
        store.archive(sidecar, True)
        unrelated = self.bind(self.project, 'default', thread_id='unrelated')
        self.bind(self.project, 'default', identifier='native-catalog')
        before = self.retained_state()
        rows = store.db.execute('SELECT * FROM recall_items ORDER BY session_id,turn_id,item_id').fetchall()
        index = NativeRecallIndex(store, max_thread_items=3)
        source = {**self.meta, 'turns': [local[1],
            turn('old-turn', 'Changed same-identity native body', 'old-answer'),
            turn('stream-turn', 'Short streaming body', status='inProgress'), self.new]}
        self.assertEqual(index.replace_snapshot(source)['omitted_items'], 1)
        native = store.db.execute('''SELECT turn_id,item_id,item_type,visible_text,normalized_text,updated
            FROM native_recall_items ORDER BY turn_id,item_id''').fetchall()
        self.assertEqual(index.catch_up_bindings(self.meta['id']), 4)
        after = store.db.execute('SELECT * FROM recall_items ORDER BY session_id,turn_id,item_id').fetchall()
        self.assertTrue(all(row in after for row in rows))
        self.assertEqual(self.retained_state(), before)
        self.assertEqual(store.db.execute('SELECT count(*) FROM recall_items WHERE session_id=?',
                                         (unrelated,)).fetchone()[0], 0)
        self.assertEqual(store.db.execute("SELECT count(*) FROM recall_items WHERE session_id='native-catalog'").fetchone()[0], 0)
        self.assertEqual(store.db.execute('''SELECT turn_id,item_id,item_type,visible_text,normalized_text,updated
            FROM recall_items WHERE session_id=? ORDER BY turn_id,item_id''', (sidecar,)).fetchall(), native)
        self.assertEqual(store.db.execute('SELECT complete FROM recall_items WHERE session_id=?',
                                         (sidecar,)).fetchall(), [(0,), (0,), (0,)])
        dump = list(store.db.iterdump())
        self.assertEqual(index.catch_up_bindings(self.meta['id']), 0)
        self.assertEqual(list(store.db.iterdump()), dump)
        self.assertEqual(self.recall(q='Changed same-identity native body')['total'], 0)
        self.assertEqual(self.recall(q='Longer streaming evidence')['total'], 1)
        self.assertEqual(self.recall()['total'], 1)
        self.assertEqual(self.recall(archived='true')['total'], 2)
        self.assertEqual(self.recall(cwd=str(self.root / 'other'), archived='true')['total'], 1)
        # An ordinary full bound snapshot, not the cache copy, supplies completion.
        store.recall_snapshot(self.session, self.fresh)
        self.assertEqual(store.db.execute('''SELECT complete FROM recall_items
            WHERE session_id=? AND turn_id=?''', (self.session, self.new['id'])).fetchone()[0], 1)


if __name__ == '__main__':
    unittest.main()
