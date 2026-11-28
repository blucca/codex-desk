"""Focused native older-history persistence and read-only acceptance."""
import copy
import os
from pathlib import Path
import tempfile
import unittest

from codex_desk.history_scan import NativeHistoryScanner
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Store

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)

class NativeSource:
    def __init__(self, home, prefix='native', count=260):
        self.home = Path(home)
        self.prefix = prefix
        self.calls = []
        self.cursors = {}
        self.rows = []
        self.threads = {}
        for position in range(1, count + 1):
            identifier = f'{prefix}-{position:03}'
            text = 'OLDER-230 retry budget decision' if position == 230 else f'Original evidence {position}'
            thread = {'id': identifier, 'name': f'Conversation {position}', 'cwd': '/missing/retained-project',
                      'modelProvider': 'fixture', 'updatedAt': 1795601000 - position,
                      'turns': [{'id': f'turn-{position}', 'status': 'completed',
                                 'items': [{'id': f'answer-{position}', 'type': 'agentMessage', 'text': text}]}]}
            self.rows.append({key: value for key, value in thread.items() if key != 'turns'})
            self.threads[identifier] = thread

    def catalog(self):
        return self

    def token(self, offset):
        token = f'{self.prefix} / opaque+页 ={offset}'
        self.cursors[token] = offset
        return token

    def request(self, method, params):
        self.calls.append((method, dict(params)))
        assert method == 'thread/list', 'Native mutation requested: ' + method
        assert params['modelProviders'] == [] and params['sortKey'] == 'updated_at'
        cursor = params.get('cursor')
        offset = self.cursors[cursor] if cursor else 0
        size = params['limit']
        rows = self.rows[offset:offset + size]
        return {'data': copy.deepcopy(rows),
                'nextCursor': self.token(offset + len(rows)) if offset + len(rows) < len(self.rows) else None}

    def history(self, identifier):
        self.calls.append(('thread/read', {'threadId': identifier, 'includeTurns': True}))
        return copy.deepcopy(self.threads[identifier])

class OlderScanTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='older-scan-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.path = self.root / 'state' / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.index = NativeRecallIndex(self.store)
        self.source = NativeSource(self.root / 'home-a')
        self.scanner = NativeHistoryScanner(self.source, self.index)
        self.addCleanup(lambda: self.scanner.close())

    def run_pass(self, scanner=None, **options):
        scanner = scanner or self.scanner
        scanner.start(**options)
        scanner.worker.join(10)
        self.assertFalse(scanner.worker.is_alive())
        return scanner.status()

    def reopen(self):
        self.scanner.close()
        self.store.db.close()
        self.store = Store(self.path)
        self.index = NativeRecallIndex(self.store)
        self.scanner = NativeHistoryScanner(self.source, self.index)

    def test_recent_200_then_explicit_older_finds_230th_exact_original_without_native_task_calls(self):
        recent = self.run_pass()
        self.assertEqual((recent['status'], recent['seen'], recent['indexed'], recent['older_available']),
                         ('completed', 200, 200, True))
        self.assertEqual(self.index.search('OLDER-230')['total'], 0)
        before = len(self.source.calls)
        self.reopen()
        self.assertEqual(len(self.source.calls), before)
        self.scanner.status()
        self.assertEqual(len(self.source.calls), before)
        older = self.run_pass(op='older')
        self.assertEqual((older['status'], older['seen'], older['indexed'], older['older_available']),
                         ('completed', 60, 60, False))
        hit = self.index.search('OLDER-230')['results'][0]
        self.assertEqual((hit['thread_id'], hit['turn_id'], hit['item_id']),
                         ('native-230', 'turn-230', 'answer-230'))
        self.assertEqual(self.index.stats()['indexed_threads'], 260)
        self.assertEqual(self.store.sessions(), [])
        self.assertTrue(all(method in ('thread/list', 'thread/read') for method, _ in self.source.calls))
        self.assertTrue(all(1 <= params['limit'] <= 30 for method, params in self.source.calls if method == 'thread/list'))

if __name__ == '__main__':
    unittest.main()
