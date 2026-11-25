import json
import os
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock
from codex_desk.runtime import Store, Runtime, session_name
from codex_desk.server import Desk

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class SessionNamesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT)
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name)
        self.store = Store(self.path / 'desk.sqlite3')
        self.addCleanup(self.store.db.close)

    def runtime(self, identifier, responder):
        runtime = object.__new__(Runtime)
        runtime.store, runtime.id, runtime.home = self.store, identifier, self.path
        runtime.persisted = False
        runtime.name_lock = threading.RLock()
        runtime.lifecycle_lock = threading.Lock()
        runtime.turn_lock = threading.Lock()
        runtime.request = Mock(side_effect=responder)
        return runtime

    def test_distinct_defaults_stable_after_restart(self):
        a = self.store.create('/work/app', 'default')
        b = self.store.create('/work/app', 'default')
        names = [self.store.get(i)['name'] for i in (a, b)]
        self.assertNotEqual(*names)
        self.assertTrue(all(n.startswith('app · ') for n in names))
        reopened = Store(self.path / 'desk.sqlite3')
        try:
            self.assertEqual(names, [reopened.get(i)['name'] for i in (a, b)])
        finally:
            reopened.db.close()

    def test_existing_database_migration_preserves_binding_events_and_order(self):
        db = self.path / 'legacy.sqlite3'
        conn = sqlite3.connect(db)
        conn.executescript('''CREATE TABLE sessions(id TEXT PRIMARY KEY,cwd TEXT NOT NULL,profile TEXT NOT NULL,
          thread_id TEXT,model TEXT,provider TEXT,status TEXT,created REAL,updated REAL,usage TEXT,error TEXT);
          CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL,payload TEXT NOT NULL);''')
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('used', '/work/app', 'trial', 'native-original', 'model', 'provider', 'completed', 1, 2, '{"total":3}', None))
        conn.execute('INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?)',
            ('blank', '/work/app', 'default', 'native-blank', None, None, 'ready', 3, 4, None, None))
        payload = {'method':'item/completed', 'params':{'item':{'type':'userMessage', 'content':[{'type':'text', 'text':'Fix the\n login redirect'}]}}}
        conn.execute('INSERT INTO events(session_id,payload) VALUES(?,?)', ('used', json.dumps(payload)))
        conn.commit(); conn.close()
        migrated = Store(db)
        try:
            row = migrated.get('used')
            self.assertEqual(row['name'], 'Fix the login redirect')
            self.assertEqual(row['name_source'], 'task')
            self.assertEqual((row['thread_id'], row['cwd'], row['profile'], row['updated'], row['usage']),
                             ('native-original', '/work/app', 'trial', 2, '{"total":3}'))
            self.assertEqual([s['id'] for s in migrated.sessions()], ['blank', 'used'])
            self.assertEqual(migrated.events('used'), [{'seq':1, 'event':payload}])
            # Legacy imports cannot be distinguished from local blank bindings.
            self.assertEqual(migrated.get('used')['thread_saved'], 1)
            self.assertEqual(migrated.get('blank')['thread_saved'], 1)
            new_blank = migrated.create('/work/app', 'default')
            self.assertEqual(migrated.get(new_blank)['thread_saved'], 0)
            migrated.update('used', name='My session', name_source='user')
        finally:
            migrated.db.close()
        again = Store(db)
        try:
            self.assertEqual(again.get('used')['name'], 'My session')
        finally:
            again.db.close()

    def test_first_task_names_once_and_defers_native_write_until_persisted(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='original', status='ready')
        runtime = self.runtime(identifier, lambda method, params: {'turn':{'id':'turn'}} if method=='turn/start' else {})
        runtime.turn('  Repair the\n login redirect  ')
        self.assertEqual(self.store.get(identifier)['name'], 'Repair the login redirect')
        self.assertEqual(self.store.get(identifier)['thread_saved'], 1)
        self.assertEqual([c.args[0] for c in runtime.request.call_args_list], ['turn/start'])
        runtime.persisted = True
        runtime._flush_name()
        runtime.request.assert_called_with('thread/name/set', {'threadId':'original', 'name':'Repair the login redirect'})
        self.assertEqual(self.store.get(identifier)['name_pending'], 0)
        self.store.update(identifier, status='completed')
        runtime.turn('A different follow-up task')
        self.assertEqual(self.store.get(identifier)['name'], 'Repair the login redirect')

    def test_used_native_resume_imports_name_and_rename_keeps_native_id(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='original', status='saved')
        def respond(method, params):
            if method == 'thread/resume':
                return {'thread':{'id':'original', 'name':'Saved native title', 'turns':[{'items':[]}]}, 'model':'model'}
            return {}
        runtime = self.runtime(identifier, respond)
        runtime.attach()
        self.assertEqual(self.store.get(identifier)['name'], 'Saved native title')
        self.assertEqual(runtime.rename('  Release checklist  '), {'name':'Release checklist', 'namePending':False})
        runtime.request.assert_called_with('thread/name/set', {'threadId':'original', 'name':'Release checklist'})
        self.assertEqual(self.store.get(identifier)['thread_id'], 'original')

    def test_blank_rename_then_reopen_does_not_call_native_name_set(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='blank-original', status='ready')
        runtime = self.runtime(identifier, lambda method, params: {})
        self.assertTrue(runtime.rename('Plan the dashboard')['namePending'])
        runtime.request.assert_not_called()
        def respond(method, params):
            if method == 'thread/resume':
                raise RuntimeError('no rollout found')
            if method == 'turn/start':
                return {'turn':{'id':'turn'}}
            self.assertEqual(method, 'thread/start')
            return {'thread':{'id':'replacement-blank', 'turns':[]}}
        reopened = self.runtime(identifier, respond)
        reopened.attach()
        self.assertEqual(self.store.get(identifier)['name'], 'Plan the dashboard')
        self.assertEqual([c.args[0] for c in reopened.request.call_args_list], ['thread/resume', 'thread/start'])
        reopened.turn('Do not replace my chosen name')
        self.assertEqual(self.store.get(identifier)['name'], 'Plan the dashboard')

    def test_used_thread_missing_rollout_is_never_replaced(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='used-original', status='ready')
        self.store.event(identifier, {'method':'turn/started', 'params':{'turn':{'id':'turn'}}})
        runtime = self.runtime(identifier, lambda method, params: (_ for _ in ()).throw(RuntimeError('no rollout found')))
        with self.assertRaisesRegex(RuntimeError, 'no rollout found'):
            runtime.attach()
        self.assertEqual(self.store.get(identifier)['thread_id'], 'used-original')
        self.assertEqual([c.args[0] for c in runtime.request.call_args_list], ['thread/resume'])

    def test_imported_used_thread_missing_rollout_is_never_replaced(self):
        desk = Desk('unused', self.path, self.path / 'import-state')
        self.addCleanup(desk.store.db.close)
        desk.history = Mock(return_value={'id': 'imported-original', 'cwd': str(self.path),
            'name': 'Saved verification', 'turns': [{'items': [{'type': 'userMessage',
                'content': [{'type': 'text', 'text': 'Run the verification command'}]}]}]})
        identifier = desk.import_thread('imported-original', 'default')['id']
        original = desk.store.get(identifier)
        self.assertEqual(desk.store.events(identifier), [])
        runtime = self.runtime(identifier, lambda method, params: (
            _ for _ in ()).throw(RuntimeError('no rollout found')))
        runtime.store = desk.store
        with self.assertRaisesRegex(RuntimeError, 'original --codex-home'):
            runtime.attach()
        self.assertEqual(desk.store.get(identifier), original)
        self.assertEqual(desk.store.events(identifier), [])
        self.assertEqual([c.args[0] for c in runtime.request.call_args_list], ['thread/resume'])

    def test_successful_resume_without_local_turns_remains_saved_after_restart(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='saved-original', status='ready')
        runtime = self.runtime(identifier, lambda method, params: {
            'thread': {'id': 'saved-original', 'turns': []}})
        runtime.attach()
        self.assertEqual(self.store.events(identifier), [])
        reopened = Store(self.path / 'desk.sqlite3')
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.get(identifier)['thread_saved'], 1)
        failed = self.runtime(identifier, lambda method, params: (
            _ for _ in ()).throw(RuntimeError('no rollout found')))
        failed.store = reopened
        with self.assertRaisesRegex(RuntimeError, 'Start new conversation explicitly'):
            failed.attach()
        self.assertEqual(reopened.get(identifier)['thread_id'], 'saved-original')
        self.assertEqual([c.args[0] for c in failed.request.call_args_list], ['thread/resume'])

    def test_native_write_failure_keeps_local_name_pending_for_resume(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='original', status='ready')
        runtime = self.runtime(identifier, lambda method, params: (_ for _ in ()).throw(RuntimeError('unavailable')))
        runtime.persisted = True
        with self.assertRaisesRegex(RuntimeError, 'unavailable'):
            runtime.rename('Keep this name')
        self.assertEqual(self.store.get(identifier)['name'], 'Keep this name')
        self.assertEqual(self.store.get(identifier)['name_pending'], 1)

    def test_native_history_import_uses_name_or_first_user_task_without_writes(self):
        desk = Desk('unused', os.path.relpath(self.path), self.path / 'import-state')
        self.assertEqual(desk.home, self.path.resolve())
        self.addCleanup(desk.store.db.close)
        desk.history = Mock(return_value={'id':'native-a', 'cwd':str(self.path), 'name':'Native name', 'turns':[]})
        named = desk.import_thread('native-a', 'default')
        self.assertEqual(desk.store.get(named['id'])['name'], 'Native name')
        desk.history.return_value = {'id':'native-b', 'cwd':str(self.path), 'name':None, 'preview':'preview',
            'turns':[{'items':[{'type':'userMessage', 'content':[{'text':'First user task'}]}]}]}
        unnamed = desk.import_thread('native-b', 'default')
        self.assertEqual(desk.store.get(unnamed['id'])['name'], 'First user task')
        self.assertEqual(desk.runtimes, {})
        self.assertEqual(desk.store.get(named['id'])['thread_id'], 'native-a')
        self.assertEqual(desk.store.get(named['id'])['thread_saved'], 1)
        self.assertEqual(desk.store.get(unnamed['id'])['thread_saved'], 1)
        again = desk.import_thread('native-b', 'default')
        self.assertEqual(again['id'], unnamed['id'])
        self.assertEqual(len(desk.store.sessions()), 2)

    def test_plan_mode_and_explicit_return_to_native(self):
        identifier = self.store.create(str(self.path), 'default')
        self.store.update(identifier, thread_id='original', status='ready', model='fixture-model')
        runtime = self.runtime(identifier, lambda method, params: {'turn':{'id':'turn'}})
        runtime.turn('Make a plan', mode='plan')
        runtime.request.assert_called_with('turn/start', {'threadId':'original',
            'input':[{'type':'text','text':'Make a plan'}], 'collaborationMode':{
                'mode':'plan','settings':{'model':'fixture-model','developer_instructions':None}}})
        self.assertEqual(self.store.get(identifier)['mode'], 'plan')
        self.store.update(identifier, status='completed')
        runtime.turn('Execute the selected step', mode='native')
        params=runtime.request.call_args.args[1]
        self.assertEqual(params['collaborationMode']['mode'], 'default')
        self.assertEqual(self.store.get(identifier)['mode'], 'native')
        self.store.update(identifier, status='completed')
        runtime.turn('Continue in native mode')
        self.assertNotIn('collaborationMode', runtime.request.call_args.args[1])
        with self.assertRaises(ValueError):runtime.turn('bad mode', mode='unknown')

    def test_name_validation(self):
        self.assertEqual(session_name(' One\n useful name '), 'One useful name')
        for value in ('', ' \n ', 'x'*121, None, 7):
            with self.assertRaises(ValueError):
                session_name(value)


if __name__ == '__main__':
    unittest.main()
