"""Indexed exact-folder recall keeps original identities and binding visibility."""
import os
from pathlib import Path
import tempfile
import unittest

from codex_desk.native_recall import NativeRecallIndex
from codex_desk.recall import PAGE_ORDER, canonical_cwd, normalize
from codex_desk.runtime import Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)
PHRASE = 'RÉSUMÉ café 项目 retry budget'


def history(identifier, cwd, count, updated=1_795_600_000):
    return {'id': identifier, 'cwd': str(cwd), 'updatedAt': updated,
            'name': identifier, 'turns': [{'id': 'original-turn', 'items': [
                {'id': f'item-{i:02}', 'type': 'agentMessage', 'text': PHRASE}
                for i in range(count)]}]}


def identity(hit):
    return (hit['kind'], hit.get('session_id'), hit['thread_id'],
            hit['turn_id'], hit['item_id'])


class NativeRecallScopePlanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='native-recall-scope-plan-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / 'missing-project'
        self.store = Store(self.root / 'desk.sqlite3')
        self.addCleanup(self.store.db.close)
        self.index = NativeRecallIndex(self.store)

    def bind(self, identifier, source, cwd=None, archived=False):
        self.store.create(str(cwd or self.project), 'default', identifier=identifier)
        self.store.update(identifier, thread_id=source['id'], status='saved', thread_saved=1)
        self.store.recall_snapshot(identifier, source)
        self.store.archive(identifier, archived)

    def test_exact_folder_count_and_page_use_cwd_index_with_each_exclusion_form(self):
        for identifier, folder in (('bound', self.project), ('excluded', self.project),
                                   ('retained', self.project), ('child', self.project / 'child')):
            self.index.replace_snapshot(history(identifier, folder, 1))
        self.bind('binding', history('bound', self.project, 1))
        needle = normalize(PHRASE)
        for excluded, exclude_bound, expected in (((), False, 3), (('excluded',), False, 2),
                                                 ((), True, 2), (('excluded',), True, 1)):
            with self.subTest(excluded=excluded, exclude_bound=exclude_bound):
                sql, params, total = self.index._search_query(
                    str(self.project), needle, excluded, exclude_bound=exclude_bound)
                self.assertEqual(total, expected)
                count_sql = 'SELECT count(*) ' + sql[sql.index('FROM native_recall_items'):]
                for statement, options in ((count_sql, params),
                                           (sql + PAGE_ORDER, (*params, 30, 0))):
                    plan = [row[3] for row in self.store.db.execute(
                        'EXPLAIN QUERY PLAN ' + statement, options)]
                    self.assertTrue(any('SEARCH t USING' in row and 'native_recall_cwd' in row
                                        and 'cwd=?' in row for row in plan), plan)
                    self.assertTrue(any('SEARCH i USING INDEX' in row and 'thread_id=?' in row
                                        for row in plan), plan)
                    self.assertFalse(any(row == 'SCAN i' for row in plan), plan)
        sql, params, total = self.index._search_query(None, needle)
        self.assertEqual((total, params), (4, (needle,)))
        self.assertNotIn('t.cwd=?', sql)

    def test_canonical_missing_folder_pages_keep_order_unicode_and_explicit_exclusions(self):
        self.index.replace_snapshot(history('native-a', self.project, 36))
        self.index.replace_snapshot(history('native-b', self.project, 4))
        self.index.replace_snapshot(history('child', self.project / 'child', 2))
        self.index.replace_snapshot(history('sibling', self.root / 'missing-project-other', 2))
        expected = [('native-activity', None, identifier, 'original-turn', f'item-{i:02}')
                    for identifier, count in (('native-a', 36), ('native-b', 4))
                    for i in reversed(range(count))]
        before = list(self.store.db.iterdump())
        received = []
        coverage = None
        for offset in (0, 30, 60):
            page = self.index.search(PHRASE.lower(),
                                     str(self.project / '..' / self.project.name), offset=offset)
            self.assertEqual((page['total'], page['cwd'], page['has_more']),
                             (40, canonical_cwd(str(self.project)), offset == 0))
            received.extend(identity(hit) for hit in page['results'])
            self.assertTrue(all(hit['cwd'] == str(self.project) and hit['match_text'] == PHRASE
                                for hit in page['results']))
            coverage = coverage or page['coverage']
            self.assertEqual(page['coverage'], coverage)
        self.assertEqual(received, expected)
        self.assertEqual(len(set(received)), 40)
        excluded = self.index.search(PHRASE, str(self.project),
                                     exclude_thread_ids=('native-a', 'native-a'))
        self.assertEqual(excluded['total'], 4)
        self.assertEqual([identity(hit) for hit in excluded['results']], expected[-4:])
        self.assertEqual(self.index.search(PHRASE)['total'], 44)
        self.assertFalse(self.project.exists())
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_combined_pages_preserve_archive_and_out_of_scope_binding_ownership(self):
        local = history('bound', self.project, 35, updated=1_795_600_001)
        archived = history('archived', self.project, 2)
        moved = history('moved', self.project, 2)
        for source in (local, archived, moved, history('unbound', self.project, 35),
                       history('child', self.project / 'child', 2)):
            self.index.replace_snapshot(source)
        self.bind('local-binding', local)
        self.bind('archived-binding', archived, archived=True)
        self.bind('moved-binding', moved, cwd=self.root / 'other-project')
        before = list(self.store.db.iterdump())
        received = []
        for offset in (0, 30, 60, 90):
            page = self.index.search_combined(PHRASE, str(self.project), offset=offset)
            self.assertEqual((page['total'], page['has_more']), (70, offset < 60))
            received.extend(identity(hit) for hit in page['results'])
        expected = [('activity', 'local-binding', 'bound', 'original-turn', f'item-{i:02}')
                    for i in range(35)]
        expected += [('native-activity', None, 'unbound', 'original-turn', f'item-{i:02}')
                     for i in reversed(range(35))]
        self.assertEqual(received, expected)
        self.assertEqual(len(set(received)), 70)
        included = self.index.search_combined(PHRASE, str(self.project), include_archived=True,
                                              offset=30)
        self.assertEqual(included['total'], 72)
        archived_hits = [hit for hit in included['results'] if hit['thread_id'] == 'archived']
        self.assertEqual(len(archived_hits), 2)
        self.assertTrue(all(hit['session_id'] == 'archived-binding' and hit['archived']
                            for hit in archived_hits))
        moved_page = self.index.search_combined(PHRASE, str(self.root / 'other-project'))
        self.assertEqual(moved_page['total'], 2)
        self.assertTrue(all(hit['kind'] == 'activity' and hit['session_id'] == 'moved-binding'
                            for hit in moved_page['results']))
        self.assertEqual(list(self.store.db.iterdump()), before)


if __name__ == '__main__':
    unittest.main()
