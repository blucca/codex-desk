"""Per-page folder reuse stays fresh across symlink and retained-path changes."""
from collections import Counter
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from codex_desk import recall
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)
PHRASE = 'RÉSUMÉ café 项目 retry budget'


def history(identifier, cwd, count=18):
    return {'id': identifier, 'cwd': str(cwd), 'updatedAt': 1_795_600_000,
            'turns': [{'id': 'original-turn', 'status': 'completed', 'items': [
                {'id': f'item-{i:02}', 'type': 'agentMessage', 'text': PHRASE}
                for i in range(count)]}]}


class RecallCwdReuseTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='recall-cwd-reuse-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.project = self.root / 'project'
        self.store = Store(self.root / 'desk.sqlite3')
        self.addCleanup(self.store.db.close)
        self.index = NativeRecallIndex(self.store)

    def bind(self, identifier, cwd, count=18, archived=False):
        self.store.create(str(cwd), 'default', identifier=identifier)
        self.store.update(identifier, thread_id=identifier, status='saved', thread_saved=1)
        source = history(identifier, cwd, count)
        self.store.recall_snapshot(identifier, source)
        self.index.replace_snapshot(source)
        self.store.archive(identifier, archived)

    def test_each_raw_folder_is_resolved_once_across_counts_preparation_and_page_rows(self):
        alias = self.project / '..' / 'project'
        for identifier, cwd in (('bound-a', self.project), ('bound-b', self.project),
                                ('bound-alias', alias)):
            self.bind(identifier, cwd)
        self.bind('child', self.project / 'child', 3)
        self.bind('archived', self.project, 2, archived=True)
        self.index.replace_snapshot(history('unbound', self.project, 6))
        save_draft(self.store, 'bound-a', PHRASE, 'plan', 0)
        add_followup(self.store, 'bound-a', PHRASE, 'native')
        requested = str(self.root / 'unused' / '..' / 'project')
        before = list(self.store.db.iterdump())
        for search, total in ((self.store.recall, 56), (self.index.search_combined, 62)):
            received = []
            coverage = None
            for offset in (0, 30, 60):
                with self.subTest(search=search.__name__, offset=offset), \
                        patch.object(recall, 'canonical_cwd', wraps=recall.canonical_cwd) as canonical:
                    page = search(PHRASE.lower(), requested, offset=offset)
                calls = Counter(call.args[0] for call in canonical.call_args_list)
                self.assertEqual(calls[str(self.project)], 1)
                self.assertEqual(calls[str(alias)], 1)
                self.assertEqual(calls[str(self.project / 'child')], 1)
                self.assertIsNone(self.store._recall_cwds)
                self.assertEqual((page['total'], page['cwd']), (total, str(self.project)))
                self.assertTrue(all(hit['cwd'] == str(self.project) and hit['match_text'] == PHRASE
                                    for hit in page['results']))
                received.extend((hit['kind'], hit.get('session_id'), hit.get('thread_id'),
                                 hit.get('turn_id'), hit.get('item_id'), hit.get('followup_id'))
                                for hit in page['results'])
                coverage = coverage or page['coverage']
                self.assertEqual(page['coverage'], coverage)
            self.assertEqual(len(received), total)
            self.assertEqual(len(set(received)), total)
            included = search(PHRASE, requested, include_archived=True, offset=30)
            self.assertEqual(included['total'], total + 2)
            self.assertNotIn('archived', {hit.get('thread_id') for hit in page['results']})
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_next_query_follows_retargeted_symlinks_and_deleted_project_paths(self):
        first, second = self.root / 'first', self.root / 'second'
        first.mkdir()
        second.mkdir()
        link = self.root / 'project-link'
        link.symlink_to(first, target_is_directory=True)
        self.bind('linked-a', link, 3)
        self.bind('linked-b', link, 3)
        before = list(self.store.db.iterdump())
        for search in (self.store.recall, self.index.search_combined):
            initial = search(PHRASE, str(first))
            self.assertEqual(initial['total'], 6)
            self.assertTrue(all(hit['cwd'] == str(first) for hit in initial['results']))
        link.unlink()
        link.symlink_to(second, target_is_directory=True)
        for search in (self.store.recall, self.index.search_combined):
            self.assertEqual(search(PHRASE, str(first))['total'], 0)
            moved = search(PHRASE, str(second))
            self.assertEqual(moved['total'], 6)
            self.assertTrue(all(hit['cwd'] == str(second) for hit in moved['results']))
            self.assertTrue(all(hit['kind'] == 'activity' for hit in moved['results']))
        second.rmdir()
        for search in (self.store.recall, self.index.search_combined):
            deleted = search(PHRASE, str(link))
            self.assertEqual(deleted['total'], 6)
            self.assertTrue(all(hit['cwd'] == str(second) for hit in deleted['results']))
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_failed_read_discards_partial_folder_reuse_before_retry(self):
        self.bind('first', self.project, 2)
        other = self.root / 'other'
        self.bind('other', other, 2)
        canonical = recall.canonical_cwd
        def fail_other(value):
            if value == str(other):
                raise OSError('fixture folder lookup failed')
            return canonical(value)
        for search in (self.store.recall, self.index.search_combined):
            with patch.object(recall, 'canonical_cwd', side_effect=fail_other):
                with self.assertRaises(sqlite3.OperationalError):
                    search(PHRASE, str(self.project))
            self.assertIsNone(self.store._recall_cwds)
            with patch.object(recall, 'canonical_cwd', wraps=canonical) as resolved:
                retry = search(PHRASE, str(self.project))
            self.assertEqual(retry['total'], 2)
            self.assertIn(str(other), [call.args[0] for call in resolved.call_args_list])
            self.assertIsNone(self.store._recall_cwds)


if __name__ == '__main__':
    unittest.main()
