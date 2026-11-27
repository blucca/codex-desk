"""Real read-only subprocess startup across removed Desk launch directories."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest

from codex_desk.drafts import load_draft, save_draft
from codex_desk.followups import add_followup, followup_snapshot
from codex_desk.server import Desk


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class CatalogRuntimeTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-catalog-')
        self.addCleanup(folder.cleanup)
        original = Path.cwd()
        self.addCleanup(os.chdir, original)
        self.root = Path(folder.name).resolve()
        self.launch = self.root / 'original-launch'
        self.launch.mkdir()
        self.other = self.root / 'new-launch'
        self.other.mkdir()
        self.home = self.root / 'native-home'
        self.home.mkdir()
        (self.home / 'config.toml').write_text('model="saved-model"\n')
        (self.home / 'auth.json').write_text('{"fixture":"saved-auth"}\n')
        (self.home / 'saved.config.toml').write_text('model="sidecar-model"\n')
        self.home_before = {p.name: p.read_bytes() for p in self.home.iterdir()}
        self.state = self.root / 'state'
        self.log = self.root / 'requests.jsonl'
        self.native = self.root / 'native-reader'
        self.native.write_text(f'#!{sys.executable}\n' + '''
import json, os, sys
from pathlib import Path
log = Path(''' + repr(str(self.log)) + ''')
metadata = {'id': 'saved-original', 'cwd': ''' + repr(str(self.launch)) + ''',
            'name': 'Saved decision', 'modelProvider': 'saved-provider', 'updatedAt': 100}
for line in sys.stdin:
    message = json.loads(line)
    with log.open('a') as out:
        out.write(json.dumps({'message': message, 'cwd': os.getcwd(),
                              'home': os.environ.get('CODEX_HOME'), 'argv': sys.argv[1:]}) + '\\n')
    method = message.get('method')
    if method == 'initialize':
        result = {}
    elif method == 'initialized':
        continue
    elif method == 'thread/list':
        result = {'data': [metadata], 'nextCursor': None}
    elif method == 'thread/read':
        result = {'thread': {**metadata, 'id': message['params']['threadId'], 'turns': [
            {'id': 'turn-exact', 'items': [{'id': 'item-exact', 'type': 'agentMessage',
              'text': 'Use the saved decision to avoid the repeated check.'}]}]}}
    else:
        raise AssertionError('Unexpected non-reader method: ' + str(method))
    print(json.dumps({'id': message['id'], 'result': result}), flush=True)
''')
        self.native.chmod(0o700)
        self.desks = []
        self.addCleanup(self.close_desks)

    def desk(self, launch, state=None):
        os.chdir(launch)
        desk = Desk(str(self.native), self.home, self.state if state is None else state)
        self.desks.append(desk)
        return desk

    def retire(self, desk):
        desk.close()
        desk.store.db.close()
        self.desks.remove(desk)

    def close_desks(self):
        for desk in self.desks:
            desk.close()
            desk.store.db.close()

    def requests(self):
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def assert_reader_requests(self):
        for record in self.requests():
            self.assertEqual(record['home'], str(self.home))
            self.assertEqual(record['argv'], ['app-server', '--stdio'])
            message = record['message']
            self.assertIn(message['method'], ('initialize', 'initialized', 'thread/list', 'thread/read'))
            if message['method'] == 'thread/read':
                self.assertEqual(message['params'], {'threadId': 'saved-original', 'includeTurns': True})
            elif message['method'] == 'thread/list':
                self.assertEqual(message['params'], {'limit': 30, 'modelProviders': [],
                                                      'sortKey': 'updated_at'})
        self.assertEqual({p.name: p.read_bytes() for p in self.home.iterdir()}, self.home_before)

    def assert_history(self, desk):
        thread = desk.history('saved-original')
        self.assertEqual(thread['id'], 'saved-original')
        self.assertEqual(thread['cwd'], str(self.launch))
        self.assertEqual(thread['turns'][0]['id'], 'turn-exact')
        self.assertEqual(thread['turns'][0]['items'][0]['id'], 'item-exact')

    @staticmethod
    def saved_sql(desk):
        # Indexing may write its native cache and scan checkpoint, not bindings or preparation.
        with desk.store.lock:
            tables = desk.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            return {name: desk.store.db.execute('SELECT * FROM "' + name + '" ORDER BY rowid').fetchall()
                    for (name,) in tables if not name.startswith('native_recall_')
                    and name != 'native_history_scan_state'}

    def test_existing_catalog_cwd_survives_cold_launch_from_another_folder(self):
        desk = self.desk(self.launch)
        self.assert_history(desk)
        desk.close()
        before = list(desk.store.db.iterdump())
        self.retire(desk)

        reopened = self.desk(self.other)
        self.assert_history(reopened)
        self.assert_history(reopened)
        self.assertEqual(list(reopened.store.db.iterdump()), before)
        self.assertEqual({r['cwd'] for r in self.requests()}, {str(self.launch)})
        self.assertEqual(sum(r['message']['method'] == 'initialize' for r in self.requests()), 2)
        self.assert_reader_requests()

    def test_removed_catalog_cwd_reads_indexes_and_reopens_without_changing_preparation(self):
        desk = self.desk(self.launch)
        self.assert_history(desk)
        session = desk.store.create(str(self.launch), 'sidecar:saved', name='Saved preparation')
        desk.store.update(session, thread_id='prepared-original', status='saved', thread_saved=1,
                          model='saved-model', provider='saved-provider')
        draft = save_draft(desk.store, session, 'Retain this saved Plan', 'plan', 0)
        add_followup(desk.store, session, 'Retain this queued task', 'native')
        followups = followup_snapshot(desk.store, session)
        desk.store.event(session, {'method': 'item/completed', 'params': {'threadId': 'prepared-original',
            'turnId': 'prepared-turn', 'item': {'id': 'prepared-item', 'type': 'agentMessage',
                                             'text': 'Preparation stays in its original project.'}}})
        original_session = desk.store.get(session)
        desk.close()
        before = list(desk.store.db.iterdump())
        saved = self.saved_sql(desk)
        catalog = desk.store.get('native-catalog')
        self.retire(desk)
        os.chdir(self.other)
        self.launch.rmdir()

        reopened = self.desk(self.other)
        self.assertEqual(list(reopened.store.db.iterdump()), before)
        self.assert_history(reopened)
        self.assert_history(reopened)
        self.assertEqual(list(reopened.store.db.iterdump()), before)
        reopened.history_scanner.start()
        reopened.history_scanner.worker.join(5)
        self.assertFalse(reopened.history_scanner.worker.is_alive())
        job = reopened.history_scanner.status()
        self.assertEqual((job['status'], job['indexed'], job['failed']), ('completed', 1, 0))
        hits = reopened.recall('saved decision')
        self.assertEqual(hits['total'], 1)
        self.assertEqual(hits['results'][0]['thread_id'], 'saved-original')
        self.assertEqual(self.saved_sql(reopened), saved)
        self.assertEqual(reopened.store.get('native-catalog'), catalog)
        self.assertEqual(reopened.store.get(session), original_session)
        self.assertEqual(load_draft(reopened.store, session), draft)
        self.assertEqual(followup_snapshot(reopened.store, session), followups)
        indexed_sql = list(reopened.store.db.iterdump())
        self.retire(reopened)

        cold = self.desk(self.other)
        request_count = len(self.requests())
        self.assertIsNone(cold.history_scanner.worker)
        self.assertEqual(cold.recall('saved decision')['total'], 1)
        self.assertEqual(len(self.requests()), request_count)
        page = cold.catalog().request('thread/list', {'limit': 30, 'modelProviders': [],
                                                      'sortKey': 'updated_at'})
        self.assertEqual(page['data'][0]['id'], 'saved-original')
        self.assert_history(cold)
        self.assertEqual(list(cold.store.db.iterdump()), indexed_sql)
        self.assertEqual(cold.store.get('native-catalog'), catalog)
        starts = [r for r in self.requests() if r['message']['method'] == 'initialize']
        self.assertEqual([r['cwd'] for r in starts], [str(self.launch), str(self.state), str(self.state)])
        self.assertEqual(len(cold.runtimes), 1)
        self.assert_reader_requests()

        # A genuine project runtime must still fail at its missing bound cwd.
        requests_before = self.requests()
        with self.assertRaises(FileNotFoundError):
            cold.open(session)
        self.assertEqual(self.requests(), requests_before)
        failed = cold.store.get(session)
        for field in ('id', 'thread_id', 'cwd', 'profile', 'model', 'provider'):
            self.assertEqual(failed[field], original_session[field])
        self.assertEqual(failed['status'], 'failed')
        self.assertEqual(load_draft(cold.store, session), draft)
        self.assertEqual(followup_snapshot(cold.store, session), followups)
        self.assertNotIn(session, cold.runtimes)

    def test_removed_process_cwd_before_first_read_uses_anchored_state_directory(self):
        desk = self.desk(self.launch, Path('../state'))
        self.launch.rmdir()
        with self.assertRaises(FileNotFoundError):
            Path.cwd()
        self.assert_history(desk)
        self.assert_history(desk)
        self.assertEqual(desk.store.get('native-catalog')['cwd'], str(self.state))
        self.assertEqual({r['cwd'] for r in self.requests()}, {str(self.state)})
        self.assert_reader_requests()


if __name__ == '__main__':
    unittest.main()
