"""Recover an explicit read-only retry without restarting Desk or native tasks."""
import http.client
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.runtime import Runtime
from codex_desk.server import Desk, ThreadingHTTPServer, handler


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class QuickReader(Runtime):
    def request(self, method, params, timeout=30):
        return super().request(method, params, timeout=.5 if method != 'initialize' else 5)


class CatalogRecoveryTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-catalog-recovery-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.home = self.root / 'native-home'
        self.home.mkdir()
        (self.home / 'config.toml').write_text('model="original-model"\n')
        (self.home / 'auth.json').write_text('{"fixture":"original-auth"}\n')
        self.home_before = {p.name: p.read_bytes() for p in self.home.iterdir()}
        self.log = self.root / 'requests.jsonl'
        self.native = self.root / 'native-reader'
        self.native.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys, time
from pathlib import Path
home = Path(os.environ['CODEX_HOME'])
log = Path(''' + repr(str(self.log)) + ''')
rows = [{'id': 'saved-' + str(i), 'cwd': '/removed/project', 'name': 'Original ' + str(i),
         'modelProvider': 'fixture', 'updatedAt': 100 - i} for i in range(3)]
for line in sys.stdin:
    message = json.loads(line)
    with log.open('a') as out:
        out.write(json.dumps({'message': message, 'pid': os.getpid()}) + '\\n')
    method = message.get('method')
    if method == 'initialized':
        continue
    if method == 'initialize':
        result = {}
    else:
        assert method in ('thread/list', 'thread/read'), 'Native mutation: ' + method
        marker = home / 'stall'
        target = message['params'].get('threadId', message['params'].get('cursor', 'first'))
        if marker.exists() and marker.read_text() == method + ':' + target:
            marker.unlink()
            while True:
                time.sleep(60)
        if (home / 'reject').exists():
            (home / 'reject').unlink()
            print(json.dumps({'id': message['id'], 'error': {'message': 'Original history temporarily unavailable'}}), flush=True)
            continue
        if method == 'thread/list':
            offset = int(message['params'].get('cursor', '0'))
            size = 2 if message['params']['limit'] > 1 else 1
            result = {'data': rows[offset:offset + size],
                      'nextCursor': str(offset + size) if offset + size < len(rows) else None}
        else:
            meta = next(row for row in rows if row['id'] == message['params']['threadId'])
            result = {'thread': {**meta, 'turns': [{'id': 'turn-' + meta['id'], 'items': [
                {'id': 'answer-' + meta['id'], 'type': 'agentMessage',
                 'text': 'Retained original proof ' + meta['id']}]}]}}
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
        self.native.chmod(0o700)
        patcher = patch('codex_desk.server.Runtime', QuickReader)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.desk = Desk(str(self.native), self.home, self.root / 'state')
        self.addCleanup(self.desk.store.db.close)
        self.addCleanup(self.desk.close)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), handler(self.desk))
        self.worker = threading.Thread(target=self.server.serve_forever,
                                       kwargs={'poll_interval': .01}, daemon=True)
        self.worker.start()
        self.addCleanup(self.stop_server)
        # A separate selected task is never owned by this read-only catalog.
        self.session = self.desk.store.create('/removed/selected-project', 'default', name='Prepared task')
        self.desk.store.update(self.session, thread_id='selected-native', status='saved', thread_saved=1)
        self.draft = save_draft(self.desk.store, self.session, 'Keep my prepared task', 'plan', 0)
        add_followup(self.desk.store, self.session, 'Keep my queued task', 'native')
        self.followups = followup_snapshot(self.desk.store, self.session)
        self.binding = self.desk.store.get(self.session)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.worker.join(3)

    def request(self, path, data=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=5)
        try:
            connection.request('GET' if data is None else 'POST', path,
                               body=None if data is None else json.dumps(data),
                               headers={} if data is None else {'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.loads(response.read())
        finally:
            connection.close()

    def finish(self):
        self.desk.history_scanner.worker.join(5)
        self.assertFalse(self.desk.history_scanner.worker.is_alive())
        return self.request('/api/history/index')[1]['job']

    def requests(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_saved_work(self):
        self.assertEqual(self.desk.store.get(self.session), self.binding)
        self.assertEqual(load_draft(self.desk.store, self.session), self.draft)
        self.assertEqual(followup_snapshot(self.desk.store, self.session), self.followups)
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir()}, self.home_before)
        self.assertEqual(self.desk.store.events(self.session), [])
        self.assertEqual([s['id'] for s in self.desk.store.sessions() if s['id'] != 'native-catalog'], [self.session])
        self.assertTrue(all(r['message']['method'] in ('initialize', 'initialized', 'thread/list', 'thread/read')
                            for r in self.requests()))

    def test_original_reader_timeout_is_reaped_and_explicit_retry_reads_same_item(self):
        self.desk.catalog()  # Native initialization succeeds before this stall.
        retired = self.desk.runtimes['native-catalog']
        (self.home / 'stall').write_text('thread/read:saved-1')
        path = '/api/native/thread?id=saved-1'
        status, failure = self.request(path)
        self.assertEqual(status, 400)
        self.assertIsNotNone(retired.process.poll(), 'Timed-out read-only process must be reaped')
        self.assertIn('Retry', failure['error'])
        self.assertEqual(sum(r['message']['method'] == 'initialize' for r in self.requests()), 1)
        status, original = self.request(path)
        self.assertEqual(status, 200)
        self.assertEqual(original['id'], 'saved-1')
        self.assertEqual(original['turns'][0]['items'][0]['id'], 'answer-saved-1')
        self.assertIsNot(self.desk.runtimes['native-catalog'], retired)
        self.assertEqual(sum(r['message']['method'] == 'initialize' for r in self.requests()), 2)
        self.assert_saved_work()

    def test_native_title_retry_retains_literal_query_and_opaque_cursor(self):
        self.desk.catalog()
        retired = self.desk.runtimes['native-catalog']
        (self.home / 'stall').write_text('thread/list:2')
        path = '/api/native?' + urlencode({'search': 'Original + résumé', 'cursor': '2'})
        self.assertEqual(self.request(path)[0], 400)
        self.assertIsNotNone(retired.process.poll())
        status, page = self.request(path)
        self.assertEqual((status, page['data'][0]['id']), (200, 'saved-2'))
        listed = [r['message']['params'] for r in self.requests() if r['message']['method'] == 'thread/list']
        self.assertEqual(listed, [{'limit': 30, 'modelProviders': [], 'sortKey': 'updated_at',
                                  'searchTerm': 'Original + résumé', 'cursor': '2'}] * 2)
        self.assert_saved_work()

    def test_scan_reader_timeout_keeps_failed_row_and_other_reads_then_retries_only_it(self):
        self.desk.catalog()
        retired = self.desk.runtimes['native-catalog']
        (self.home / 'stall').write_text('thread/read:saved-1')
        self.assertEqual(self.request('/api/history/index', {})[0], 200)
        job = self.finish()
        self.assertEqual((job['status'], job['seen'], job['indexed'], job['failed'], job['retryable_failures']),
                         ('completed', 3, 2, 1, 1))
        self.assertIsNotNone(retired.process.poll())
        self.assertEqual(self.desk.recall('original proof')['total'], 2)
        before = len(self.requests())
        self.assertEqual(self.request('/api/history/index', {'op': 'retry'})[0], 200)
        job = self.finish()
        self.assertEqual((job['status'], job['seen'], job['indexed'], job['retryable_failures']),
                         ('completed', 1, 1, 0))
        after = self.requests()[before:]
        self.assertEqual([r['message']['method'] for r in after], ['thread/read'])
        self.assertEqual(after[0]['message']['params'], {'threadId': 'saved-1', 'includeTurns': True})
        self.assertEqual(self.desk.recall('original proof')['total'], 3)
        self.assert_saved_work()

    def test_scan_listing_timeout_preserves_next_page_for_explicit_continue(self):
        self.desk.catalog()
        retired = self.desk.runtimes['native-catalog']
        (self.home / 'stall').write_text('thread/list:2')
        self.assertEqual(self.request('/api/history/index', {})[0], 200)
        job = self.finish()
        self.assertEqual((job['status'], job['seen'], job['indexed'], job['resumable']), ('failed', 2, 2, True))
        self.assertIsNotNone(retired.process.poll())
        before = len(self.requests())
        self.assertEqual(self.request('/api/history/index', {'op': 'retry'})[0], 200)
        job = self.finish()
        self.assertEqual((job['status'], job['seen'], job['indexed']), ('completed', 3, 3))
        after = [r['message'] for r in self.requests()[before:]]
        self.assertEqual([m['method'] for m in after], ['initialize', 'initialized', 'thread/list', 'thread/read'])
        self.assertEqual(after[2]['params']['cursor'], '2')
        self.assertEqual(after[3]['params']['threadId'], 'saved-2')
        self.assert_saved_work()

    def test_native_rejection_keeps_healthy_reader_for_explicit_retry(self):
        self.desk.catalog()
        reader = self.desk.runtimes['native-catalog']
        (self.home / 'reject').touch()
        status, failure = self.request('/api/native/thread?id=saved-1')
        self.assertEqual((status, failure['error']), (400, 'Original history temporarily unavailable'))
        self.assertIsNone(reader.process.poll())
        self.assertEqual(self.request('/api/native/thread?id=saved-1')[0], 200)
        self.assertIs(self.desk.runtimes['native-catalog'], reader)
        self.assertEqual(sum(r['message']['method'] == 'initialize' for r in self.requests()), 1)
        self.assert_saved_work()


if __name__ == '__main__':
    unittest.main()
