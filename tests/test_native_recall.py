"""First-use native history recall, persistence, coverage and read isolation."""
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest

from codex_desk.native_recall import MAX_THREAD_CHARS, MAX_THREAD_ITEMS, NativeRecallIndex
from codex_desk.recall import MAX_ITEM_CHARS, canonical_cwd


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp'))) / 'r119-native-recall'
ROOT.mkdir(parents=True, exist_ok=True)


def agent(text, identifier='native-item'):
    return {'id': identifier, 'type': 'agentMessage', 'text': text}


def snapshot(items, identifier='native-thread', turn='native-turn', **metadata):
    return {'id': identifier, 'cwd': '/missing/native-project', 'name': 'Native verification',
            'modelProvider': 'native-provider', 'updatedAt': 1795625000,
            'turns': [{'id': turn, 'items': items, 'completedAt': 1795625000}], **metadata}


class NativeRecallTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='index-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.db_path = self.root / 'cache.sqlite3'
        self.store = SimpleNamespace(db=sqlite3.connect(self.db_path, check_same_thread=False),
                                     lock=threading.RLock())
        self.addCleanup(lambda: self.store.db.close())
        self.index = NativeRecallIndex(self.store)

    def reopen(self):
        self.store.db.close()
        self.store.db = sqlite3.connect(self.db_path, check_same_thread=False)
        self.index = NativeRecallIndex(self.store)

    def test_first_use_search_retains_native_ids_without_desk_binding_or_tables(self):
        self.assertEqual(self.index.search('sparse index')['total'], 0)
        source = snapshot([agent('Keep the sparse index decision'),
            {'id': 'native-command', 'type': 'commandExecution', 'command': 'pytest test_sparse.py',
             'exitCode': 0, 'aggregatedOutput': 'Sparse index: 7 tests passed.'}])
        untouched = json.dumps(source)
        stats = self.index.replace_snapshot(source)
        hit = self.index.search('sparse index')['results'][0]
        self.assertEqual((hit['kind'], hit['thread_id'], hit['turn_id'], hit['item_id'], hit['item_type']),
                         ('native-activity', 'native-thread', 'native-turn', 'native-command', 'commandExecution'))
        self.assertEqual((hit['title'], hit['provider']), ('Native verification', 'native-provider'))
        self.assertIn('7 tests passed', hit['snippet'])
        self.assertNotIn('session_id', hit)
        self.assertEqual(stats['indexed_items'], 2)
        self.assertEqual(json.dumps(source), untouched)
        tables = {row[0] for row in self.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertEqual(tables, {'native_recall_threads', 'native_recall_items'})

    def test_cold_reopen_preserves_hits_and_full_read_freshness_without_mutation(self):
        source = snapshot([agent('Accepted migration decision')])
        self.index.replace_snapshot(source)
        before = self.index.search('migration decision')
        self.assertFalse(self.index.needs_snapshot(source))
        self.reopen()
        self.assertEqual(self.index.search('migration decision'), before)
        self.assertFalse(self.index.needs_snapshot(source))
        dump = list(self.store.db.iterdump())
        self.index.search('migration decision')
        self.index.stats()
        self.index.needs_snapshot(source)
        self.assertEqual(list(self.store.db.iterdump()), dump)

    def test_full_replacement_removes_obsolete_items_and_preserves_other_threads(self):
        self.index.replace_snapshot(snapshot([agent('Old accepted evidence', 'old'),
                                              agent('Retired proof', 'retired')]))
        self.index.replace_snapshot(snapshot([agent('Other accepted evidence')], identifier='other-thread'))
        self.index.replace_snapshot(snapshot([agent('Corrected accepted evidence', 'old')]))
        self.assertEqual(self.index.search('old accepted')['total'], 0)
        self.assertEqual(self.index.search('retired proof')['total'], 0)
        self.assertEqual(self.index.search('accepted evidence')['total'], 2)
        self.assertEqual(self.index.stats()['indexed_items'], 2)
        self.index.replace_snapshot(snapshot([], turns=[]))
        self.assertEqual(self.index.search('corrected accepted')['total'], 0)
        self.assertEqual(self.index.search('other accepted')['total'], 1)
        self.assertEqual(self.index.stats()['indexed_threads'], 2)

    def test_metadata_only_keeps_history_and_does_not_refresh_last_full_read(self):
        source = snapshot([agent('Preserved decision')])
        self.index.replace_snapshot(source)
        metadata = {'id': 'native-thread', 'cwd': str(self.root / 'new-missing-folder'),
                    'name': 'New native title', 'modelProvider': 'new-provider',
                    'updatedAt': 1795625100}
        self.index.replace_snapshot(metadata)
        hit = self.index.search('preserved decision')['results'][0]
        self.assertEqual((hit['cwd'], hit['title'], hit['provider']),
                         (canonical_cwd(metadata['cwd']), 'New native title', 'new-provider'))
        self.assertTrue(self.index.needs_snapshot(metadata))
        self.index.replace_snapshot({'id': 'native-thread', 'turns': None})
        self.assertEqual(self.index.search('preserved decision')['total'], 1)
        self.reopen()
        self.assertTrue(self.index.needs_snapshot(metadata))
        self.index.replace_snapshot({**metadata, 'turns': source['turns']})
        self.assertFalse(self.index.needs_snapshot(metadata))

    def test_freshness_compares_full_metadata_and_requires_valid_native_timestamp(self):
        source = snapshot([agent('Native snapshot')])
        self.assertTrue(self.index.needs_snapshot(source))
        self.index.replace_snapshot(source)
        summary = {key: value for key, value in source.items() if key != 'turns'}
        self.assertFalse(self.index.needs_snapshot(summary))
        self.assertFalse(self.index.needs_snapshot({**summary, 'updatedAt': summary['updatedAt'] * 1000}))
        for changed in ({'updatedAt': 1795625100}, {'cwd': '/another/project'},
                        {'name': 'Changed title'}, {'modelProvider': 'Changed provider'}):
            self.assertTrue(self.index.needs_snapshot({**summary, **changed}), changed)
        for missing in (None, 0, -1, True, float('inf'), 10**1000, '1795625000'):
            self.assertTrue(self.index.needs_snapshot({**summary, 'updatedAt': missing}))
        without_timestamp = {key: value for key, value in summary.items() if key != 'updatedAt'}
        self.assertTrue(self.index.needs_snapshot(without_timestamp))
        self.index.replace_snapshot({**source, 'updatedAt': None})
        self.assertTrue(self.index.needs_snapshot(summary))
        smaller = NativeRecallIndex(self.store, max_thread_chars=100)
        self.assertTrue(smaller.needs_snapshot(summary))

    def test_literal_unicode_original_snippets_and_sql_regex_metacharacters(self):
        self.index.replace_snapshot(snapshot([agent("Décision: STRASSE / Cafe\u0301 / ＡＢＣ / 项目回归通过; "
                                                   "a%b_c[0].*; ' OR 1=1 --")]))
        for query, match in [('straße', 'STRASSE'), ('CAFÉ', 'Cafe\u0301'), ('abc', 'ＡＢＣ'),
                             ('项目回归', '项目回归'), ('a%b_c[0].*', 'a%b_c[0].*'),
                             ("' OR 1=1 --", "' OR 1=1 --")]:
            with self.subTest(query=query):
                result = self.index.search(query)
                self.assertEqual(result['total'], 1)
                self.assertEqual(result['results'][0]['match_text'], match)
                self.assertIn(match, result['results'][0]['snippet'])
        for query in ('a%bZc', '.*missing', '%_', '1=2'):
            self.assertEqual(self.index.search(query)['total'], 0, query)

    def test_exact_canonical_cwd_and_missing_folder_metadata_are_retained(self):
        project = self.root / 'missing-project'
        source = snapshot([agent('Scoped native decision')], cwd=str(project))
        self.index.replace_snapshot(source)
        self.index.replace_snapshot(snapshot([agent('Scoped native decision')],
                                            identifier='child-native', cwd=str(project / 'child')))
        scoped = self.index.search('native decision', cwd=str(project / '..' / 'missing-project'))
        self.assertEqual(scoped['total'], 1)
        self.assertEqual(scoped['results'][0]['cwd'], str(project))
        self.assertEqual(scoped['coverage']['threads'], 1)
        self.assertEqual(self.index.stats(cwd=str(project))['indexed_items'], 1)
        self.assertFalse(project.exists())
        self.reopen()
        self.assertEqual(self.index.search('native decision', cwd=str(project)), scoped)

    def test_unsupported_private_and_binary_tool_structures_do_not_enter_cache(self):
        self.index.replace_snapshot(snapshot([
            {'id': 'reasoning', 'type': 'reasoning', 'text': 'reasoning-secret', 'encryptedContent': 'encrypted-secret'},
            {'id': 'media', 'type': 'imageGeneration', 'data': 'binary-secret'},
            {'id': 'user', 'type': 'userMessage', 'content': [
                {'type': 'text', 'text': 'Visible project request'},
                {'type': 'image', 'url': 'https://media-secret/?token=access-secret'}]},
            {'id': 'tool', 'type': 'mcpToolCall', 'server': 'fixture', 'tool': 'verify',
             'arguments': {'_meta': {'secret': 'argument-secret'}},
             'result': {'structuredContent': {'decision': 'Keep native index',
                 'url': 'https://user:password-secret@public.example/report?token=query-secret#fragment-secret',
                 '_meta': {'secret': 'structured-secret'}},
                 'content': [{'type': 'image', 'data': 'binary-secret'},
                    {'type': 'resource', 'resource': {'uri': 'file:///report', 'text': 'Readable embedded result',
                     'blob': 'blob-secret', '_meta': {'secret': 'resource-secret'}}}],
                 '_meta': {'secret': 'result-secret'}}, '_meta': {'secret': 'metadata-secret'}}]))
        for query in ('reasoning-secret', 'encrypted-secret', 'binary-secret', 'media-secret',
                      'access-secret', 'argument-secret', 'password-secret', 'query-secret',
                      'fragment-secret', 'structured-secret', 'blob-secret', 'resource-secret',
                      'result-secret', 'metadata-secret'):
            self.assertEqual(self.index.search(query)['total'], 0, query)
        for query in ('Visible project request', 'keep native index', 'readable embedded', 'public.example/report'):
            self.assertEqual(self.index.search(query)['total'], 1, query)
        dump = '\n'.join(self.store.db.iterdump())
        self.assertNotIn('secret', dump)
        self.assertEqual(self.index.stats()['unsupported_items'], 2)

    def test_thread_character_budget_keeps_newest_items_and_explicit_coverage(self):
        self.index = NativeRecallIndex(self.store, max_thread_chars=100)
        source = snapshot([], turns=[
            {'id': 'older-turn', 'items': [agent('Old proof ' * 20, 'old')]},
            {'id': 'newest-turn', 'items': [agent('Middle proof ' * 20, 'middle'),
                                         agent('Newest proof', 'newest')]}])
        stats = self.index.replace_snapshot(source)
        self.assertEqual((stats['indexed_chars'], stats['indexed_items'], stats['readable_items']), (100, 2, 3))
        self.assertEqual((stats['omitted_items'], stats['shortened_items'], stats['truncated']), (1, 1, True))
        self.assertEqual(self.index.search('old proof')['total'], 0)
        self.assertEqual(self.index.search('newest proof')['results'][0]['turn_id'], 'newest-turn')
        coverage = self.index.search('middle proof')['coverage']
        self.assertEqual((coverage['truncated_threads'], coverage['max_thread_chars']), (1, 100))
        self.assertEqual(self.store.db.execute('SELECT sum(length(visible_text)) FROM native_recall_items').fetchone()[0], 100)

    def test_per_item_and_item_count_caps_report_coverage(self):
        self.index.replace_snapshot(snapshot([agent('z' * (MAX_ITEM_CHARS + 100) + 'beyond item cap')]))
        stats = self.index.stats()
        self.assertEqual(stats['indexed_chars'], MAX_ITEM_CHARS)
        self.assertEqual(stats['item_limit_hits'], 1)
        self.assertEqual(stats['truncated_threads'], 1)
        self.assertEqual(self.index.search('beyond item cap')['total'], 0)
        limited = NativeRecallIndex(self.store, max_thread_items=2)
        stats = limited.replace_snapshot(snapshot([agent('bounded proof', f'item-{i}') for i in range(4)]))
        self.assertEqual((stats['indexed_items'], stats['omitted_items']), (2, 2))
        self.assertEqual([hit['item_id'] for hit in limited.search('bounded proof')['results']], ['item-3', 'item-2'])

    def test_default_thread_cap_is_enforced_and_counted(self):
        self.index.replace_snapshot(snapshot([agent('e' * MAX_ITEM_CHARS, f'item-{i}') for i in range(12)]))
        stats = self.index.stats()
        self.assertEqual((stats['indexed_chars'], stats['indexed_items'], stats['omitted_items']),
                         (MAX_THREAD_CHARS, 10, 2))
        self.assertLessEqual(self.store.db.execute('SELECT sum(length(visible_text)) FROM native_recall_items').fetchone()[0], MAX_THREAD_CHARS)

    def test_long_multi_turn_history_keeps_exact_default_item_window_after_reopen(self):
        source = snapshot([], turns=[
            {'id': f'turn-{turn}', 'completedAt': 1795625000 + turn,
             'items': [agent(f'Decision proof {item:04d}', f'item-{item}')
                       for item in range(turn * 100, (turn + 1) * 100)]}
            for turn in range(60)])
        stats = self.index.replace_snapshot(source)
        self.assertEqual((stats['source_turns'], stats['source_items'], stats['readable_items']),
                         (60, 6000, 6000))
        self.assertEqual((stats['indexed_items'], stats['omitted_items'], stats['indexed_chars']),
                         (MAX_THREAD_ITEMS, 1000, MAX_THREAD_ITEMS * len('Codex\nDecision proof 1000')))
        self.assertEqual((stats['shortened_items'], stats['item_limit_hits']), (0, 0))
        self.assertTrue(stats['truncated'])
        self.assertEqual(self.index.search('Decision proof 0999')['total'], 0)
        oldest = self.index.search('Decision proof 1000')['results'][0]
        self.assertEqual((oldest['turn_id'], oldest['item_id']), ('turn-10', 'item-1000'))
        self.assertEqual(self.index.search('Decision proof')['results'][0]['item_id'], 'item-5999')
        self.assertFalse(self.index.needs_snapshot(source))
        self.reopen()
        self.assertFalse(self.index.needs_snapshot(source))
        self.assertEqual(self.index.search('Decision proof')['total'], MAX_THREAD_ITEMS)
        self.assertEqual(self.index.search('Decision proof 1000')['results'][0], oldest)

    def test_replacement_is_atomic_on_observed_database_failure(self):
        self.index.replace_snapshot(snapshot([agent('Original preserved evidence')]))
        before = list(self.store.db.iterdump())
        with self.store.db:
            self.store.db.execute('''CREATE TRIGGER fail_native_item BEFORE INSERT ON native_recall_items
                WHEN NEW.item_id='bad' BEGIN SELECT RAISE(ABORT,'fixture failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            self.index.replace_snapshot(snapshot([agent('New failed evidence', 'bad'), agent('New failed proof', 'good')],
                                                name='Failed replacement'))
        self.assertEqual(self.index.search('original preserved')['total'], 1)
        self.assertEqual(self.index.search('new failed')['total'], 0)
        with self.store.db:
            self.store.db.execute('DROP TRIGGER fail_native_item')
        self.assertEqual(list(self.store.db.iterdump()), before)

    def test_malformed_snapshots_and_duplicate_ids_preserve_newest_valid_text(self):
        source = snapshot([None, {'id': 'bad-shape', 'type': {}},
            {'id': 'bad-text', 'type': 'agentMessage', 'text': {}},
            {'id': 'bad-unicode', 'type': 'agentMessage', 'text': '\ud800'},
            {'id': '', 'type': 'agentMessage', 'text': 'invalid identifier'},
            agent('Older duplicate proof', 'same'), agent('Newer duplicate proof', 'same')])
        stats = self.index.replace_snapshot(source)
        self.assertEqual(stats['indexed_items'], 1)
        self.assertEqual((stats['unsupported_items'], stats['invalid_items']), (2, 3))
        self.assertEqual(self.index.search('newer duplicate')['total'], 1)
        self.assertEqual(self.index.search('older duplicate')['total'], 0)

    def test_metadata_only_thread_is_counted_without_claiming_indexed_history(self):
        self.index.replace_snapshot({'id': 'unread-native', 'cwd': '/missing/native', 'preview': 'CLI-only task',
                                     'updatedAt': 1795625000, 'token': 'auth-secret'})
        coverage = self.index.stats()
        self.assertEqual((coverage['threads'], coverage['indexed_threads'], coverage['metadata_only_threads']), (1, 0, 1))
        self.assertEqual(coverage['indexed_items'], 0)
        self.assertTrue(self.index.needs_snapshot({'id': 'unread-native', 'updatedAt': 1795625000}))
        self.assertNotIn('auth-secret', '\n'.join(self.store.db.iterdump()))

    def test_recent_limit_and_bounded_original_snippet(self):
        self.index.replace_snapshot(snapshot([agent('prefix ' * 200 + 'target decision ' + 'suffix ' * 300, f'item-{i:02}')
                                              for i in range(55)]))
        result = self.index.search('target decision')
        self.assertEqual((result['total'], result['truncated'], len(result['results'])), (55, True, 30))
        self.assertEqual(result['results'][0]['item_id'], 'item-54')
        self.assertEqual(result['results'][0]['match_text'], 'target decision')
        self.assertLessEqual(len(result['results'][0]['snippet']), 422)

    def test_input_validation(self):
        for query in (None, 2, '', 'x', 'a' * 201, '\ud800x'):
            with self.assertRaises(ValueError):
                self.index.search(query)
        for limit in (0, 51, 1.5, True, '30'):
            with self.assertRaises(ValueError):
                self.index.search('valid query', limit=limit)
        for cwd in ('', ' ', 2, '\ud800'):
            with self.assertRaises(ValueError):
                self.index.search('valid query', cwd=cwd)
        for source in (None, {}, {'id': ''}, {'id': 'a' * 201}, {'id': '\ud800'}):
            with self.assertRaises(ValueError):
                self.index.replace_snapshot(source)
            with self.assertRaises(ValueError):
                self.index.needs_snapshot(source)
        for kwargs in ({'max_thread_chars': 0}, {'max_thread_chars': MAX_THREAD_CHARS + 1},
                       {'max_thread_items': True}, {'max_thread_items': 5001}):
            with self.assertRaises(ValueError):
                NativeRecallIndex(self.store, **kwargs)


if __name__ == '__main__':
    unittest.main()
