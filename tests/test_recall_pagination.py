"""Complete mixed-source recall pages through local SQLite and loopback HTTP."""
import http.client
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from codex_desk import recall
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)
BASE = 1_795_600_000
PHRASE = 'ISSUE-732 retry budget'


def snapshot(identifier, cwd, count, *, step=0, start=BASE):
    return {'id': identifier, 'cwd': str(cwd), 'name': identifier, 'modelProvider': 'fixture',
            'updatedAt': start + count * step, 'turns': [
                {'id': f'turn-{i:02}', 'status': 'completed', 'completedAt': start + i * step,
                 'items': [{'id': f'item-{i:02}', 'type': 'agentMessage',
                            'text': f'{PHRASE} retained decision {i:02}'}]}
                for i in range(count)]}


def identity(hit):
    return (hit['kind'], hit.get('session_id') or hit.get('thread_id'),
            hit.get('turn_id'), hit.get('item_id'), hit.get('followup_id'))


class RecallPaginationTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-recall-pages-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.desk = Desk('never-executed', self.root / 'home', self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.project, self.other = self.root / 'project', self.root / 'other'
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def get(self, **query):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', '/api/recall?' + urlencode({'q': PHRASE, **query}))
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def bind(self, identifier, thread):
        self.desk.store.create(str(self.project), 'default', identifier=identifier, name=identifier)
        self.desk.store.update(identifier, thread_id=thread['id'], status='saved', updated=BASE + 200)
        self.desk.store.recall_snapshot(identifier, thread)
        return identifier

    def seed_interleaved(self):
        bound = snapshot('bound-thread', self.project, 48, step=2, start=BASE + 1)
        self.session = self.bind('binding-a', bound)
        self.desk.native_index.replace_snapshot(bound)
        self.desk.native_index.replace_snapshot(snapshot('unbound-thread', self.project, 48, step=2))
        self.desk.native_index.replace_snapshot(snapshot('other-thread', self.other, 1, start=BASE - 100))
        save_draft(self.desk.store, self.session, PHRASE + ' next-task draft', 'plan', 0)
        self.followup = add_followup(self.desk.store, self.session, PHRASE + ' remaining work', 'native')['id']
        self.desk.store.update(self.session, updated=BASE + 200)

    def test_interleaved_http_pages_reach_every_original_and_only_render_the_requested_page(self):
        self.seed_interleaved()
        expected = [('draft', self.session, None, None, None),
                    ('followup', self.session, None, None, self.followup)]
        for i in reversed(range(48)):
            expected.extend([('activity', self.session, f'turn-{i:02}', f'item-{i:02}', None),
                             ('native-activity', 'unbound-thread', f'turn-{i:02}', f'item-{i:02}', None)])
        expected.append(('native-activity', 'other-thread', 'turn-00', 'item-00', None))
        before = list(self.desk.store.db.iterdump())
        received, coverage = [], None
        with patch.object(self.desk, 'catalog') as catalog, patch.object(self.desk, 'open') as opened, \
                patch.object(self.desk, 'import_thread') as imported:
            for offset in (0, 30, 60, 90):
                with patch('codex_desk.recall._snippet', wraps=recall._snippet) as snippets:
                    status, result = self.get(offset=offset)
                    self.assertEqual(status, 200)
                    self.assertEqual(snippets.call_count, len(result['results']))
                self.assertEqual((result['total'], result['offset'], result['limit']), (99, offset, 30))
                self.assertEqual(result['has_more'], offset < 90)
                received.extend(identity(hit) for hit in result['results'])
                if coverage is None:
                    coverage = result['coverage']
                self.assertEqual(result['coverage'], coverage)
                for hit in result['results']:
                    if hit['kind'] == 'activity':
                        self.assertEqual(hit['thread_id'], 'bound-thread')
                    if hit['kind'] in ('activity', 'native-activity'):
                        self.assertEqual(hit['match_text'], PHRASE)
            catalog.assert_not_called(); opened.assert_not_called(); imported.assert_not_called()
        self.assertEqual(received, expected)
        self.assertEqual(len(set(received)), 99)
        self.assertEqual(coverage['activity_items'], 48)
        self.assertEqual(coverage['native']['indexed_items'], 97)
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.desk.runtimes, {})

    def test_equal_timestamp_pages_preserve_desk_identity_and_native_reverse_position_order(self):
        bound = snapshot('bound-thread', self.project, 40)
        self.bind('binding-a', bound)
        self.desk.native_index.replace_snapshot(snapshot('native-a', self.project, 40))
        expected = [('activity', 'binding-a', f'turn-{i:02}', f'item-{i:02}', None) for i in range(40)]
        expected += [('native-activity', 'native-a', f'turn-{i:02}', f'item-{i:02}', None)
                     for i in reversed(range(40))]
        first = [identity(hit) for offset in (0, 30, 60)
                 for hit in self.desk.recall(PHRASE, offset=offset)['results']]
        again = [identity(hit) for offset in (0, 30, 60)
                 for hit in self.desk.recall(PHRASE, offset=offset)['results']]
        self.assertEqual(first, expected)
        self.assertEqual(again, expected)
        self.assertEqual(len(set(first)), 80)
        self.assertEqual([identity(hit) for hit in self.desk.store.recall(PHRASE, offset=30)['results']],
                         expected[30:40])
        self.assertEqual([identity(hit) for hit in self.desk.native_index.search(PHRASE, offset=30)['results']],
                         expected[70:80])

    def test_exact_project_and_archive_scope_apply_to_every_page_and_never_leak_native_duplicates(self):
        self.seed_interleaved()
        self.desk.store.archive(self.session, True)
        visible = [hit for offset in (0, 30) for hit in self.desk.recall(PHRASE, offset=offset)['results']]
        self.assertEqual(len(visible), 49)
        self.assertTrue(all(hit['kind'] == 'native-activity' for hit in visible))
        self.assertNotIn('bound-thread', {hit['thread_id'] for hit in visible})
        for offset in (0, 30, 60, 90):
            status, result = self.get(cwd=str(self.project / '..' / 'project'), archived='true', offset=offset)
            self.assertEqual((status, result['total'], result['cwd']), (200, 98, str(self.project)))
            self.assertTrue(all(hit['cwd'] == str(self.project) for hit in result['results']))
            self.assertTrue(all(hit['archived'] for hit in result['results'] if hit['kind'] != 'native-activity'))
            self.assertNotIn('other-thread', {hit.get('thread_id') for hit in result['results']})
        self.assertEqual(self.get(cwd=str(self.other), offset=0)[1]['total'], 1)
        self.assertEqual(self.get(cwd=str(self.other), offset=30)[1]['results'], [])
        self.assertEqual(self.get(cwd=str(self.project / 'child'))[1]['total'], 0)

    def test_invalid_offsets_are_rejected_and_exhausted_page_keeps_total_and_coverage(self):
        self.seed_interleaved()
        for offset in (-1, True, 1.5, '30', 2 ** 63):
            for search in (self.desk.recall, self.desk.store.recall, self.desk.native_index.search):
                with self.subTest(offset=offset, search=search.__qualname__), self.assertRaises(ValueError):
                    search(PHRASE, offset=offset)
        for offset in ('-1', 'one', str(2 ** 63)):
            self.assertEqual(self.get(offset=offset)[0], 400)
        status, page = self.get(offset=120)
        self.assertEqual((status, page['total'], page['offset'], page['results'], page['has_more']),
                         (200, 99, 120, [], False))
        self.assertEqual(page['coverage'], self.get()[1]['coverage'])


if __name__ == '__main__':
    unittest.main()
