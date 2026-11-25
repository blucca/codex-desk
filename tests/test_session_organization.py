"""Reversible local organization at ordinary multi-project session volume."""
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

from codex_desk.drafts import load_draft, save_draft
from codex_desk.runtime import Store


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


def grouped_rows(groups):
    return [row for group in groups for section in ('active', 'recent', 'archived') for row in group[section]]


class SessionOrganizationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-organization-')
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        self.path = self.root / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.projects = {name: self.root / ('project-' + name) for name in ('a', 'b', 'c')}
        for project in self.projects.values():
            project.mkdir()
        (self.projects['b'] / 'sub').mkdir()
        self.ids = {}
        for project_number, (name, count) in enumerate((('a', 10), ('b', 10), ('c', 15))):
            self.ids[name] = []
            for index in range(count):
                id = f'{name}-{index:02d}'
                cwd = str(self.projects[name])
                if name == 'b' and index == 1:
                    cwd = str(self.projects[name] / 'sub' / '..')
                profile = 'sidecar:client' if index == 0 else 'sidecar:personal'
                self.store.create(cwd, profile, identifier=id, name=f'Project {name.upper()} work {index:02d}')
                self.store.update(id, thread_id='native-' + id, model='fixture', provider='desk_provider',
                                  status='completed', thread_saved=1, name_pending=0)
                with self.store.lock, self.store.db:
                    self.store.db.execute('UPDATE sessions SET created=?,updated=? WHERE id=?',
                                          (1, project_number * 100 + index, id))
                self.store.event(id, {'method': 'fixture/prior-evidence', 'params': {'text': 'needle-only-in-events'}})
                self.ids[name].append(id)
        self.assertEqual(len(self.store.sessions()), 35)
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE sessions SET thread_id='native-shared',name=? WHERE id='a-00'",
                                  ('Résumé release verification',))
            self.store.db.execute("UPDATE sessions SET thread_id='native-shared',name=? WHERE id='a-01'",
                                  ('STRASSE release task',))
        save_draft(self.store, 'a-00', '  Prepared next project task\nnot submitted  ', 'plan', 0)

    def test_archive_unarchive_and_restart_preserve_every_binding_draft_and_event(self):
        before = self.store.get('a-00')
        before_ids = [row['id'] for row in self.store.sessions()]
        events = self.store.events('a-00')
        draft = load_draft(self.store, 'a-00')
        self.assertEqual(self.store.archive('a-00', True), {'id': 'a-00', 'archived': True})
        after = self.store.get('a-00')
        self.assertTrue(after['archived'])
        self.assertEqual({k: v for k, v in after.items() if k != 'archived'},
                         {k: v for k, v in before.items() if k != 'archived'})
        self.assertEqual([row['id'] for row in self.store.sessions()], before_ids)
        self.assertEqual(self.store.events('a-00'), events)
        self.assertEqual(load_draft(self.store, 'a-00'), draft)
        self.assertNotIn('a-00', [row['id'] for row in grouped_rows(self.store.organized_sessions())])
        self.assertIn('a-01', [row['id'] for row in grouped_rows(self.store.organized_sessions())])

        self.store.db.close()
        self.store = Store(self.path)
        self.assertEqual(len(self.store.sessions()), 35)
        self.assertEqual(self.store.get('a-00'), after)
        self.assertEqual(self.store.events('a-00'), events)
        self.assertEqual(load_draft(self.store, 'a-00'), draft)
        self.assertEqual(self.store.archive('a-00', False), {'id': 'a-00', 'archived': False})
        self.assertEqual(self.store.get('a-00'), before)
        self.assertEqual([row['id'] for row in self.store.sessions()], before_ids)
        self.assertIn('a-00', [row['id'] for row in grouped_rows(self.store.organized_sessions())])

    def test_canonical_project_groups_title_only_scope_and_distinct_provider_bindings(self):
        before = self.store.sessions()
        groups = self.store.organized_sessions()
        self.assertEqual(len(groups), 3)
        self.assertEqual(len(grouped_rows(groups)), 35)
        by_project = {group['cwd']: group for group in groups}
        self.assertEqual([len(by_project[str(self.projects[name].resolve())]['recent'])
                          for name in ('a', 'b', 'c')], [10, 10, 15])
        self.assertEqual([group['name'] for group in groups], ['project-c', 'project-b', 'project-a'])
        scoped = self.store.organized_sessions(cwd=self.projects['b'] / 'sub' / '..')
        self.assertEqual(len(scoped), 1)
        self.assertEqual(scoped[0]['cwd'], str(self.projects['b'].resolve()))
        self.assertEqual({row['id'] for row in grouped_rows(scoped)}, set(self.ids['b']))
        self.assertEqual(self.store.get('b-01')['cwd'], str(self.projects['b'] / 'sub' / '..'))

        released = grouped_rows(self.store.organized_sessions(cwd=self.projects['a'], title='  RELEASE  '))
        self.assertEqual({row['id'] for row in released}, {'a-00', 'a-01'})
        self.assertEqual({row['thread_id'] for row in released}, {'native-shared'})
        self.assertEqual({row['profile'] for row in released}, {'sidecar:client', 'sidecar:personal'})
        self.assertEqual([row['id'] for row in grouped_rows(self.store.organized_sessions(title='straße'))], ['a-01'])
        self.assertEqual([row['id'] for row in grouped_rows(self.store.organized_sessions(title='RÉSUMÉ'))], ['a-00'])
        self.assertEqual(self.store.organized_sessions(title='needle-only-in-events'), [])
        self.assertEqual(self.store.organized_sessions(cwd=self.projects['b'], title='release'), [])
        self.assertEqual(self.store.sessions(), before)

    def test_archived_starting_running_and_approval_remain_visible_until_idle(self):
        for id, status in zip(self.ids['a'][:3], ('starting', 'running', 'approval')):
            self.store.update(id, status=status)
            self.store.archive(id, True)
        active = self.store.organized_sessions(cwd=self.projects['a'])[0]['active']
        self.assertEqual({row['id'] for row in active}, {'a-00', 'a-01', 'a-02'})
        self.assertEqual(active[0]['status'], 'approval')
        self.assertTrue(all(row['archived'] for row in active))
        self.assertEqual(self.store.get('a-00')['status'], 'starting')
        self.assertEqual(self.store.get('a-01')['status'], 'running')
        self.assertEqual(self.store.get('a-02')['status'], 'approval')
        self.assertEqual(self.store.events('a-02')[0]['event']['method'], 'fixture/prior-evidence')
        self.store.update('a-02', status='completed')
        group = self.store.organized_sessions(cwd=self.projects['a'])[0]
        self.assertNotIn('a-02', [row['id'] for row in grouped_rows([group])])
        shown = self.store.organized_sessions(cwd=self.projects['a'], include_archived=True)[0]
        self.assertEqual([row['id'] for row in shown['archived']], ['a-02'])
        self.assertEqual({row['id'] for row in shown['active']}, {'a-00', 'a-01'})
        self.store.archive('a-02', False)
        shown = self.store.organized_sessions(cwd=self.projects['a'])[0]
        self.assertIn('a-02', [row['id'] for row in shown['recent']])

    def test_archive_only_project_returns_only_when_requested_explicitly(self):
        before = self.store.sessions()
        for id in self.ids['c']:
            self.store.archive(id, True)
        self.assertEqual(len(self.store.sessions()), 35)
        self.assertEqual(len(self.store.organized_sessions()), 2)
        self.assertEqual(self.store.organized_sessions(cwd=self.projects['c']), [])
        groups = self.store.organized_sessions(include_archived=True)
        self.assertEqual(len(groups), 3)
        archived = next(group for group in groups if group['cwd'] == str(self.projects['c'].resolve()))
        self.assertEqual(len(archived['archived']), 15)
        self.assertEqual(archived['active'], [])
        self.assertEqual(archived['recent'], [])
        self.assertEqual(len(grouped_rows(groups)), 35)
        self.assertEqual({row['id']: row['updated'] for row in self.store.sessions()},
                         {row['id']: row['updated'] for row in before})

    def test_active_projects_first_and_all_sections_use_stable_recent_order(self):
        groups = self.store.organized_sessions()
        self.assertEqual([group['name'] for group in groups], ['project-c', 'project-b', 'project-a'])
        self.assertEqual([row['id'] for row in groups[0]['recent']], list(reversed(self.ids['c'])))
        self.store.update('a-00', status='approval')
        self.store.update('a-01', status='running')
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE sessions SET updated=0 WHERE id IN ('a-00','a-01')")
        groups = self.store.organized_sessions()
        self.assertEqual(groups[0]['name'], 'project-a')
        self.assertEqual([row['id'] for row in groups[0]['active']], ['a-00', 'a-01'])
        self.assertEqual([row['id'] for row in groups[0]['recent']], list(reversed(self.ids['a'][2:])))

    def test_invalid_archive_and_filters_do_not_mutate_rows_or_native_catalog(self):
        self.store.create('/internal/catalog', 'default', identifier='native-catalog', name='Catalog')
        before = self.store.sessions()
        for id in ('missing', 'native-catalog', '', None, 1):
            with self.subTest(id=id), self.assertRaises(ValueError):
                self.store.archive(id, True)
        for value in (0, 1, 'true', None, [], {}):
            with self.subTest(archived=value), self.assertRaises(ValueError):
                self.store.archive('a-00', value)
        for values in ({'title': []}, {'include_archived': 1}, {'include_archived': 'true'},
                       {'cwd': ''}, {'cwd': 1}):
            with self.subTest(filters=values), self.assertRaises(ValueError):
                self.store.organized_sessions(**values)
        self.assertEqual(self.store.sessions(), before)
        self.assertEqual(len(grouped_rows(self.store.organized_sessions(include_archived=True))), 35)
        self.assertFalse(self.store.get('native-catalog')['archived'])


class OrganizationMigrationTests(unittest.TestCase):
    def test_legacy_rows_default_visible_and_preserve_saved_fields(self):
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-organization-migration-') as temporary:
            path = Path(temporary) / 'desk.sqlite3'
            db = sqlite3.connect(path)
            db.executescript('''CREATE TABLE sessions(
              id TEXT PRIMARY KEY, cwd TEXT NOT NULL, profile TEXT NOT NULL,
              thread_id TEXT, model TEXT, provider TEXT, status TEXT,
              created REAL, updated REAL, usage TEXT, error TEXT,
              name TEXT, name_source TEXT NOT NULL DEFAULT 'default',
              name_pending INTEGER NOT NULL DEFAULT 0, mode TEXT NOT NULL DEFAULT 'native',
              thread_saved INTEGER NOT NULL DEFAULT 0);''')
            db.execute('''INSERT INTO sessions VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       ('old-session', str(Path(temporary) / 'old-project'), 'sidecar:original',
                        'old-native-id', 'old-model', 'old-provider', 'completed', 100, 200,
                        '{"total":{"inputTokens":42}}', None, 'Old retained title', 'user', 0, 'plan', 1))
            db.commit()
            keys = [column[1] for column in db.execute('PRAGMA table_info(sessions)')]
            before = dict(zip(keys, db.execute('SELECT * FROM sessions').fetchone()))
            db.close()
            store = Store(path)
            try:
                current = store.get('old-session')
                self.assertFalse(current['archived'])
                self.assertEqual({k: v for k, v in current.items() if k != 'archived'}, before)
                rows = grouped_rows(store.organized_sessions())
                self.assertEqual([row['id'] for row in rows], ['old-session'])
                self.assertEqual(rows[0]['thread_id'], 'old-native-id')
                self.assertEqual(rows[0]['profile'], 'sidecar:original')
                self.assertEqual(store.events('old-session'), [])
            finally:
                store.db.close()


if __name__ == '__main__':
    unittest.main()
