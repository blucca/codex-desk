"""Conversation-first recall reuses the exact read-only mixed corpus."""
import unittest
from unittest.mock import patch

import test_recall_pagination as base
from codex_desk.drafts import save_draft


class RecallConversationTests(unittest.TestCase):
    setUp = base.RecallPaginationTests.setUp
    stop_server = base.RecallPaginationTests.stop_server
    get = base.RecallPaginationTests.get
    bind = base.RecallPaginationTests.bind

    def seed(self):
        self.desk.native_index.replace_snapshot(base.snapshot('dominant', self.project, 65, start=base.BASE + 100))
        self.desk.native_index.replace_snapshot(base.snapshot('distinct', self.project, 1))

    def test_same_project_distinct_answer_is_visible_with_exact_group_counts(self):
        self.seed()
        self.assertEqual({r['thread_id'] for r in self.get()[1]['results']}, {'dominant'})
        status, result = self.get(view='conversations')
        self.assertEqual((status, result['total'], result['item_total']), (200, 2, 66))
        self.assertEqual([(r['group_kind'], r['group_id'], r['match_count']) for r in result['results']],
                         [('native', 'dominant', 65), ('native', 'distinct', 1)])
        _, result = self.get(source_thread='distinct')
        self.assertEqual((result['total'], len(result['results'])), (1, 1))
        self.assertEqual(result['results'][0]['item_id'], 'item-00')

    def test_scoped_pages_reach_only_own_exact_items_without_reads_or_writes(self):
        self.seed()
        before = list(self.desk.store.db.iterdump()); changes = self.desk.store.db.total_changes
        with patch.object(self.desk, 'catalog') as catalog, patch.object(self.desk, 'open') as opened, \
                patch.object(self.desk, 'import_thread') as imported:
            items = []
            for offset in (0, 30, 60):
                status, page = self.get(source_thread='dominant', offset=offset)
                self.assertEqual((status, page['total']), (200, 65))
                self.assertTrue(all(r['thread_id'] == 'dominant' for r in page['results']))
                items.extend(r['item_id'] for r in page['results'])
            catalog.assert_not_called(); opened.assert_not_called(); imported.assert_not_called()
        self.assertEqual(len(items), len(set(items))); self.assertEqual(len(items), 65)
        self.assertEqual(list(self.desk.store.db.iterdump()), before)
        self.assertEqual(self.desk.store.db.total_changes, changes)
        self.assertEqual(self.desk.runtimes, {})

    def test_saved_bindings_keep_preparation_profile_and_archive_ownership(self):
        thread = base.snapshot('shared-native', self.project, 2)
        self.bind('binding-a', thread); self.bind('binding-b', thread)
        self.desk.native_index.replace_snapshot(thread)
        save_draft(self.desk.store, 'binding-a', base.PHRASE + ' draft', 'plan', 0)
        result = self.get(view='conversations')[1]
        self.assertEqual([(r['group_kind'], r['group_id'], r['match_count']) for r in result['results']],
                         [('session', 'binding-a', 3), ('session', 'binding-b', 2)])
        scoped = self.get(source_session='binding-a')[1]
        self.assertEqual(scoped['total'], 3)
        self.assertEqual({r['session_id'] for r in scoped['results']}, {'binding-a'})
        self.assertEqual(self.get(source_thread='shared-native')[1]['total'], 0)
        self.desk.store.archive('binding-a', True)
        self.assertEqual(self.get(source_session='binding-a')[1]['total'], 0)
        self.assertEqual(self.get(source_session='binding-a', archived='true')[1]['total'], 3)
        self.assertEqual(self.get(view='conversations')[1]['results'][0]['group_id'], 'binding-b')

    def test_project_scope_and_literal_unicode_apply_before_group_count(self):
        self.seed()
        self.desk.native_index.replace_snapshot(base.snapshot('other', self.other, 1))
        self.assertEqual(self.get(view='conversations', cwd=str(self.project))[1]['total'], 2)
        self.assertEqual(self.get(view='conversations', source_session='dominant')[0], 400)
        self.assertEqual(self.get(source_thread='dominant', cwd=str(self.other))[1]['total'], 0)
        text = 'Café 项目 😀 fullwidth Ａ literal 100%_'
        source = base.snapshot('unicode', self.project, 2)
        for turn in source['turns']: turn['items'][0]['text'] = text
        self.desk.native_index.replace_snapshot(source)
        for q in ('CAFE\u0301 项目 😀', 'Ａ literal 100%_', 'a literal 100%_'):
            grouped = self.get(q=q, view='conversations')[1]
            self.assertEqual((grouped['total'], grouped['item_total']), (1, 2))
            self.assertEqual(grouped['results'][0]['match_count'], 2)
        self.assertEqual(self.get(q='100%missing_', view='conversations')[1]['total'], 0)
        unusual = base.snapshot('original/接口?+', self.project, 1)
        self.desk.native_index.replace_snapshot(unusual)
        scoped = self.get(source_thread=unusual['id'])[1]
        self.assertEqual((scoped['total'], scoped['results'][0]['thread_id']), (1, unusual['id']))
        connection = base.http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET', '/api/recall?q=phrase&view=items&view=conversations')
            response = connection.getresponse(); response.read(); self.assertEqual(response.status, 400)
        finally: connection.close()

    def test_native_replacement_recounts_source_and_group_without_stale_items(self):
        self.seed(); source = base.snapshot('dominant', self.project, 65, start=base.BASE + 200)
        source['turns'][0]['items'][0]['text'] = 'changed own native response'
        self.desk.native_index.replace_snapshot(source)
        result = self.get(view='conversations')[1]
        self.assertEqual((result['total'], result['item_total'], result['results'][0]['match_count']), (2, 65, 64))
        self.assertEqual(self.get(source_thread='dominant')[1]['total'], 64)
        self.assertEqual(self.get(q='changed own native response', source_thread='dominant')[1]['total'], 1)

    def test_group_pages_order_empty_and_invalid_source_parameters(self):
        for n in range(35):
            self.desk.native_index.replace_snapshot(base.snapshot(f'native-{n:02}', self.project, 1))
        first = self.get(view='conversations')[1]; second = self.get(view='conversations', offset=30)[1]
        identities = [r['group_id'] for p in (first, second) for r in p['results']]
        self.assertEqual((first['total'], first['item_total'], len(first['results']), len(second['results'])), (35, 35, 30, 5))
        self.assertEqual(identities, sorted(identities)); self.assertEqual(len(set(identities)), 35)
        self.assertEqual(self.get(view='conversations', offset=60)[1]['results'], [])
        self.assertEqual(self.get(source_thread='missing')[1]['total'], 0)
        for options in ({'view':'invalid'}, {'source_thread':''}, {'source_session':'', 'view':'items'},
                        {'source_thread':'a', 'source_session':'b'}, {'source_thread':'a', 'view':'conversations'}):
            self.assertEqual(self.get(**options)[0], 400, options)


if __name__ == '__main__': unittest.main()
