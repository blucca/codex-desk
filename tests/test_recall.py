"""Saved visible evidence, scoped literal recall and preparation read isolation."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup, edit_followup, reserve_followup
from codex_desk.runtime import Runtime, Store
from codex_desk.server import Desk


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


def thread(items, identifier='native-original', turn='turn-original', **extra):
    return {'id': identifier, 'updatedAt': 1795625000,
            'turns': [{'id': turn, 'status': 'completed', 'completedAt': 1795625000, 'items': items}], **extra}


def agent(text, identifier='decision'):
    return {'id': identifier, 'type': 'agentMessage', 'text': text}


class RecallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-recall-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.db_path = self.root / 'desk.sqlite3'
        self.store = Store(self.db_path)
        self.addCleanup(lambda: self.store.db.close())
        self.session = self.store.create(str(self.root / 'project'), 'default', name='Original verification')
        self.store.update(self.session, thread_id='native-original', status='saved', thread_saved=1)

    def snapshot(self, items, **extra):
        self.store.recall_snapshot(self.session, thread(items, **extra))

    def event(self, method, item=None, *, scope='native-original', **params):
        payload = {'method': method, 'params': {'threadId': scope, 'turnId': 'turn-live', **params}}
        if item is not None:
            payload['params']['item'] = item
        self.store.event(self.session, payload)
        return payload

    def test_import_then_restart_recalls_precise_saved_native_evidence_without_open(self):
        project = self.root / 'import-project'
        project.mkdir()
        desk = Desk('never-executed', self.root / 'native-home', self.root / 'import-state')
        self.addCleanup(lambda: desk.store.db.close())
        desk.history = Mock(return_value=thread([
            agent('Keep the sparse-index decision; verification accepted.'),
            {'id': 'test-command', 'type': 'commandExecution', 'command': 'pytest test_sparse.py',
             'exitCode': 0, 'aggregatedOutput': 'Sparse index: 7 tests passed.'}], cwd=str(project), name='Sparse project'))
        imported = desk.import_thread('native-original', 'default')
        with patch.object(desk, 'open') as opened, patch.object(desk, 'catalog') as catalog:
            result = desk.recall('sparse index')
            opened.assert_not_called()
            catalog.assert_not_called()
        hit = result['results'][0]
        self.assertEqual((hit['session_id'], hit['turn_id'], hit['item_id']),
                         (imported['id'], 'turn-original', 'test-command'))
        self.assertIn('7 tests passed', hit['snippet'])
        self.assertEqual(desk.store.events(imported['id']), [])
        self.assertEqual(desk.runtimes, {})
        desk.close()
        desk.store.db.close()
        reopened = Desk('never-executed', self.root / 'native-home', self.root / 'import-state')
        self.addCleanup(reopened.close)
        self.addCleanup(reopened.store.db.close)
        self.assertEqual(reopened.recall('sparse index')['results'], result['results'])
        self.assertEqual(reopened.store.get(imported['id'])['thread_id'], 'native-original')

    def test_native_resume_snapshot_is_cached_without_extra_request(self):
        self.store.update(self.session, name_pending=0)
        runtime = object.__new__(Runtime)
        runtime.store, runtime.id, runtime.home = self.store, self.session, self.root / 'native-home'
        native = {'thread': thread([agent('Resume preserved the migration decision.')]),
                  'model': 'fixture-model', 'modelProvider': 'fixture-provider'}
        runtime.request = Mock(return_value=native)
        runtime.attach()
        runtime.request.assert_called_once_with('thread/resume', {'threadId': 'native-original'})
        self.assertEqual(self.store.recall('migration decision')['total'], 1)
        self.assertEqual(self.store.get(self.session)['thread_id'], 'native-original')

    def test_repeated_import_reconciles_same_binding_and_preserves_omitted_turns(self):
        desk = Desk('never-executed', self.root / 'native-home', self.root / 'repeat-state')
        self.addCleanup(desk.store.db.close)
        native = thread([agent('Previous accepted verification.')], cwd=str(self.root))
        desk.history = Mock(return_value=native)
        first = desk.import_thread('native-original', 'default')
        desk.history.return_value = {'id': 'native-original', 'cwd': str(self.root)}
        second = desk.import_thread('native-original', 'default')
        self.assertEqual(first['id'], second['id'])
        self.assertEqual(desk.recall('accepted verification')['total'], 1)
        desk.history.return_value = thread([agent('Corrected accepted outcome.')], cwd=str(self.root))
        desk.import_thread('native-original', 'default')
        self.assertEqual(desk.recall('accepted verification')['total'], 0)
        self.assertEqual(desk.recall('accepted outcome')['total'], 1)

    def test_unicode_normalization_casefold_and_original_match_offsets(self):
        self.snapshot([agent('Décision: STRASSE / Cafe\u0301 / ＡＢＣ / 项目回归通过.')])
        for query, match in [('straße', 'STRASSE'), ('CAFÉ', 'Cafe\u0301'), ('abc', 'ＡＢＣ'), ('项目回归', '项目回归')]:
            with self.subTest(query=query):
                result = self.store.recall(query)
                self.assertEqual(result['total'], 1)
                self.assertEqual(result['results'][0]['match_text'], match)
                self.assertIn(match, result['results'][0]['snippet'])

    def test_literal_sql_and_regex_characters_do_not_expand_matches(self):
        self.snapshot([agent("Use a%b_c[0].* literally, not regex; ' OR 1=1 -- stays text.")])
        for query in ('a%b_c[0].*', "' OR 1=1 --"):
            self.assertEqual(self.store.recall(query)['total'], 1)
        for query in ('a%bZc', '.*missing', '%_', '1=2'):
            self.assertEqual(self.store.recall(query)['total'], 0)
        self.assertEqual(len(self.store.sessions()), 1)

    def test_exact_canonical_project_archived_and_profile_binding_isolation(self):
        self.snapshot([agent('shared scope evidence')])
        other = self.store.create(str(self.root / 'project' / 'child'), 'sidecar:work')
        self.store.update(other, thread_id='native-original', status='saved')
        self.store.recall_snapshot(other, thread([agent('shared scope evidence')]))
        self.assertEqual(self.store.recall('scope evidence')['total'], 2)
        cwd = str(self.root / 'project' / '..' / 'project')
        scoped = self.store.recall('scope evidence', cwd=cwd)
        self.assertEqual(scoped['total'], 1)
        self.assertEqual(scoped['results'][0]['profile'], 'default')
        self.store.archive(self.session, True)
        self.store.update(self.session, status='running')
        self.assertEqual(self.store.recall('scope evidence', cwd=cwd)['total'], 0)
        self.assertTrue(self.store.recall('scope evidence', cwd=cwd, include_archived=True)['results'][0]['archived'])

    def test_snapshot_and_event_child_metadata_reasoning_media_fields_are_excluded(self):
        self.event('item/completed', agent('foreign child answer'), scope='native-child')
        self.store.recall_snapshot(self.session, thread([agent('foreign snapshot answer')], identifier='native-child'))
        self.snapshot([
            {'id': 'reasoning', 'type': 'reasoning', 'text': 'encrypted-secret', 'encryptedContent': 'hidden-secret'},
            {'id': 'user', 'type': 'userMessage', 'content': [
                {'type': 'text', 'text': 'Visible project request'},
                {'type': 'image', 'url': 'https://media-secret/asset?token=access-secret'}]},
            {'id': 'tool', 'type': 'mcpToolCall', 'tool': 'read', 'server': 'fixture',
             '_meta': {'secret': 'metadata-secret'}, 'encryptedContent': 'hidden-secret',
             'arguments': {'_meta': {'secret': 'argument-secret'}, 'url': 'https://public.example/?token=access-secret'},
             'result': {'content': [{'type': 'resource', 'resource': {
                'uri': 'https://public-resource/project?token=access-secret', 'text': 'Readable embedded result',
                 'blob': 'blob-secret', '_meta': {'secret': 'resource-meta-secret'}}}],
                        '_meta': {'secret': 'result-meta-secret'}}}])
        for query in ('foreign', 'encrypted-secret', 'hidden-secret', 'metadata-secret', 'argument-secret',
                      'media-secret', 'access-secret', 'blob-secret', 'result-meta-secret'):
            self.assertEqual(self.store.recall(query)['total'], 0, query)
        self.assertEqual(self.store.recall('readable embedded')['total'], 1)
        text = ' '.join(row[0] for row in self.store.db.execute('SELECT visible_text FROM recall_items'))
        self.assertNotIn('secret', text)

    def test_useful_structured_data_and_public_descriptors_survive_shared_sanitizer(self):
        self.snapshot([{'id': 'structured-tool', 'type': 'mcpToolCall', 'server': 'fixture', 'tool': 'verify',
            'arguments': {}, 'result': {'structuredContent': {'data': {'decision': 'Keep sparse index',
                'url': 'https://public.example/report?token=query-secret#fragment-secret'},
                '_meta': {'auth': 'metadata-secret'}}, 'content': [
                    {'type': 'image', 'mimeType': 'image/png', 'data': 'binary-secret'},
                    {'type': 'resource_link', 'name': 'Public verification report',
                     'uri': 'https://user:password-secret@public.example/report?token=token-secret'},
                    {'type': 'resource', 'resource': {'uri': 'file:///report', 'blob': 'blob-secret'}}]}}])
        self.assertEqual(self.store.recall('keep sparse index')['total'], 1)
        self.assertEqual(self.store.recall('public verification report')['total'], 1)
        self.assertEqual(self.store.recall('public.example/report')['total'], 1)
        for phrase in ('query-secret', 'fragment-secret', 'metadata-secret', 'binary-secret',
                       'password-secret', 'token-secret', 'blob-secret'):
            self.assertEqual(self.store.recall(phrase)['total'], 0, phrase)

    def test_live_deltas_completed_replacement_and_late_delta_cannot_duplicate_evidence(self):
        self.event('item/started', agent('', 'live-message'))
        self.event('item/agentMessage/delta', itemId='live-message', delta='interim decision')
        self.assertEqual(self.store.recall('interim decision')['total'], 1)
        self.event('item/completed', agent('Final accepted decision', 'live-message'))
        self.event('item/agentMessage/delta', itemId='live-message', delta=' late stale output')
        self.assertEqual(self.store.recall('interim decision')['total'], 0)
        self.assertEqual(self.store.recall('stale output')['total'], 0)
        self.assertEqual(self.store.recall('accepted decision')['total'], 1)
        self.event('item/commandExecution/outputDelta', itemId='live-command', delta='temporary test result')
        self.assertEqual(self.store.recall('temporary test')['total'], 1)
        self.event('item/completed', {'id': 'live-command', 'type': 'commandExecution',
            'command': 'pytest', 'exitCode': 0, 'aggregatedOutput': 'Accepted tests passed'})
        self.assertEqual(self.store.recall('temporary test')['total'], 0)
        self.assertEqual(self.store.recall('accepted tests')['total'], 1)

    def test_turn_summary_completion_preserves_known_command_and_old_turn(self):
        self.snapshot([agent('Old accepted decision')])
        self.event('item/completed', {'id': 'command', 'type': 'commandExecution',
            'command': 'pytest', 'exitCode': 0, 'aggregatedOutput': 'Current accepted tests'})
        self.event('turn/completed', turn={'id': 'turn-live', 'status': 'completed',
            'items': [agent('Current accepted reply', 'final')]})
        self.assertEqual(self.store.recall('accepted')['total'], 3)

    def test_terminal_empty_summary_seals_existing_and_fresh_delta_only_items(self):
        self.event('item/agentMessage/delta', itemId='interrupted-message', delta='Retained partial decision')
        self.event('turn/completed', turn={'id': 'turn-live', 'status': 'interrupted', 'items': []})
        self.event('item/agentMessage/delta', itemId='interrupted-message', delta=' late retired answer')
        self.event('item/agentMessage/delta', itemId='fresh-late-message', delta='late fresh answer')
        self.event('item/started', agent('late started answer', 'fresh-late-start'))
        self.assertEqual(self.store.recall('partial decision')['total'], 1)
        self.assertEqual(self.store.recall('late')['total'], 0)
        self.assertEqual(self.store.db.execute('SELECT complete FROM recall_items').fetchall(), [(1,)])
        self.store.db.close()
        self.store = Store(self.db_path)
        self.event('item/agentMessage/delta', itemId='new-after-restart', delta='late restart answer')
        self.assertEqual(self.store.recall('late')['total'], 0)

    def test_legacy_event_backfill_reuses_reducer_once_and_keeps_deltas(self):
        events = [
            {'method': 'item/agentMessage/delta', 'params': {'threadId': 'native-original',
                'turnId': 'legacy-turn', 'itemId': 'legacy-item', 'delta': 'Legacy saved decision'}},
            {'method': 'item/agentMessage/delta', 'params': {'threadId': 'native-child',
                'turnId': 'child-turn', 'itemId': 'child-item', 'delta': 'Legacy foreign answer'}}]
        with self.store.db:
            for event in events:
                self.store.db.execute('INSERT INTO events(session_id,payload) VALUES(?,?)',
                                      (self.session, json.dumps(event)))
        original_events = self.store.events(self.session)
        self.store.db.close()
        self.store = Store(self.db_path)
        result = self.store.recall('legacy saved')
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['results'][0]['turn_id'], 'legacy-turn')
        self.assertEqual(self.store.recall('foreign answer')['total'], 0)
        self.assertEqual(self.store.events(self.session), original_events)
        self.store.db.close()
        self.store = Store(self.db_path)
        self.assertEqual(self.store.recall('legacy saved')['results'], result['results'])
        self.assertNotIn('decisionLegacy', self.store.recall('legacy saved')['results'][0]['snippet'])

    def test_revisioned_preparations_read_current_text_without_admission_or_mutation(self):
        save_draft(self.store, self.session, 'Old migration draft', 'plan', 0, 'writer-private', 1)
        save_draft(self.store, self.session, 'Current migration draft', 'plan', 1, 'writer-private', 2)
        entry = add_followup(self.store, self.session, 'Old migration followup')
        edit_followup(self.store, self.session, entry['id'], 'Current migration followup', 'native', 1)
        reserve_followup(self.store, self.session, entry['id'], 2)
        before = list(self.store.db.iterdump())
        results = self.store.recall('migration')['results']
        self.assertEqual({row['kind'] for row in results}, {'draft', 'followup'})
        self.assertTrue(all('Current' in row['snippet'] for row in results))
        self.assertEqual(next(row for row in results if row['kind'] == 'followup')['followup_id'], entry['id'])
        self.assertNotIn('writer-private', json.dumps(results))
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_empty_search_does_not_create_preparation_tables(self):
        before = list(self.store.db.iterdump())
        result = self.store.recall('not cached')
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['coverage']['activity_items'], 0)
        self.assertEqual(result['coverage']['drafts'], 0)
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_recent_limit_total_truncation_and_bounded_snippet_are_stable(self):
        self.snapshot([agent('prefix ' * 500 + 'target decision ' + 'suffix ' * 1000, f'item-{i:02}')
                       for i in range(55)])
        result = self.store.recall('target decision')
        self.assertEqual((result['total'], result['truncated'], len(result['results'])), (55, True, 30))
        self.assertLessEqual(len(result['results'][0]['snippet']), 422)
        self.assertEqual(result['results'][0]['match_text'], 'target decision')
        self.assertEqual(result['coverage']['activity_items'], 55)
        self.assertEqual([r['item_id'] for r in result['results']], [f'item-{i:02}' for i in range(30)])
        self.assertEqual(self.store.recall('target decision', limit=50)['results'][:30], result['results'])

    def test_invalid_query_options_are_rejected(self):
        for query in ('', ' ', 'x', 'x' * 201, None, ['phrase']):
            with self.subTest(query=query), self.assertRaises(ValueError):
                self.store.recall(query)
        for limit in (0, 51, True, '30'):
            with self.subTest(limit=limit), self.assertRaises(ValueError):
                self.store.recall('valid', limit=limit)
        with self.assertRaises(ValueError):
            self.store.recall('valid', cwd='')
        with self.assertRaises(ValueError):
            self.store.recall('valid', include_archived=1)


if __name__ == '__main__':
    unittest.main()
