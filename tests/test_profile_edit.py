"""Retained API profile corrections, key rotation and same-binding reopen."""
import copy
import json
import os
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from codex_desk.runtime import Runtime, Store, profile_config, profiles, save_profile, update_profile


ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class ProfileEditTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-profile-edit-')
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.home = self.root / 'native-home'
        self.home.mkdir()
        self.base = self.home / 'config.toml'
        self.base.write_text('model="current"\n[mcp_servers.keep]\ncommand="keep"\n')
        self.auth = self.home / 'auth.json'
        self.auth.write_text('{"fixture-auth":"preserve-this"}')
        self.before_base, self.before_auth = self.base.read_bytes(), self.auth.read_bytes()
        self.id = save_profile(self.home, 'retained', 'https://old.example/v1', 'old-model', 'old-key')['id']
        self.path = self.home / 'retained.config.toml'
        self.original = self.path.read_bytes()
        self.original_data = tomllib.loads(self.original.decode())

    def assert_main_unchanged(self):
        self.assertEqual(self.base.read_bytes(), self.before_base)
        self.assertEqual(self.auth.read_bytes(), self.before_auth)

    def test_corrected_unicode_profile_and_rotated_key_load_on_same_thread_reopen(self):
        endpoint = 'https://new.example:8443/v1/模型'
        model = 'model-"验证"\\branch-🔧'
        key = 'rotated-"密钥"\\private-🔑'
        result = update_profile(self.home, self.id, endpoint, model, key)
        self.assertEqual(result, {'id': self.id})
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        config = profile_config(self.home, self.id)
        provider = config['model_providers']['desk_provider']
        self.assertEqual(config['model'], model)
        self.assertEqual(provider['base_url'], endpoint)
        self.assertEqual(provider['experimental_bearer_token'], key)
        self.assertEqual(provider['name'], 'retained')
        row = next(p for p in profiles(self.home) if p['id'] == self.id)
        self.assertEqual((row['name'], row['model'], row['endpoint'], row['editable']),
                         ('retained', model, endpoint, True))
        self.assertNotIn(key, json.dumps([result, profiles(self.home)], ensure_ascii=False))
        self.assertNotIn('experimental_bearer_token', json.dumps(profiles(self.home)))

        state = self.root / 'desk.sqlite3'
        first = Store(state)
        identifier = first.create(str(self.root), self.id, name='Retained project task')
        first.update(identifier, thread_id='saved-native-thread', status='completed', thread_saved=1,
                     name_pending=0, name_source='user')
        first.db.close()
        reopened = Store(state)
        self.addCleanup(reopened.db.close)
        runtime = object.__new__(Runtime)
        runtime.store, runtime.id, runtime.home = reopened, identifier, self.home
        calls = []

        def request(method, params):
            calls.append((method, params))
            return {'thread': {'id': params['threadId'], 'turns': []},
                    'model': params['config']['model'], 'modelProvider': params['config']['model_provider']}

        runtime.request = request
        runtime.attach()
        self.assertEqual([method for method, _ in calls], ['thread/resume'])
        self.assertEqual(calls[0][1], {'threadId': 'saved-native-thread', 'config': config})
        self.assertEqual(reopened.get(identifier)['profile'], self.id)
        self.assertEqual(reopened.get(identifier)['model'], model)
        self.assert_main_unchanged()

    def test_blank_key_keeps_existing_secret_across_multiple_corrections(self):
        for blank in ('', ' \t\n '):
            with self.subTest(blank=blank):
                update_profile(self.home, self.id, ' https://corrected.example/v1/ ', ' corrected-model ', blank)
                config = profile_config(self.home, self.id)
                self.assertEqual(config['model'], 'corrected-model')
                self.assertEqual(config['model_providers']['desk_provider']['base_url'], 'https://corrected.example/v1')
                self.assertEqual(config['model_providers']['desk_provider']['experimental_bearer_token'], 'old-key')
        self.assert_main_unchanged()

    def test_current_settings_and_arbitrary_native_profiles_stay_read_only(self):
        variants = []
        extra = copy.deepcopy(self.original_data)
        extra['mcp_servers'] = {'custom': {'command': 'keep'}}
        variants.append(extra)
        effort = copy.deepcopy(self.original_data)
        effort['model_reasoning_effort'] = 'high'
        variants.append(effort)
        other_provider = copy.deepcopy(self.original_data)
        other_provider['model_providers']['another'] = {'name': 'Another'}
        variants.append(other_provider)
        extra_field = copy.deepcopy(self.original_data)
        extra_field['model_providers']['desk_provider']['env_key'] = 'EXISTING_KEY'
        variants.append(extra_field)
        wrong_wire = copy.deepcopy(self.original_data)
        wrong_wire['model_providers']['desk_provider']['wire_api'] = 'chat'
        variants.append(wrong_wire)
        wrong_provider = copy.deepcopy(self.original_data)
        wrong_provider['model_provider'] = 'native-provider'
        variants.append(wrong_provider)

        def toml(data):
            # Test fixture serializer; only dictionaries and scalar strings occur.
            lines = []

            def table(value, prefix=''):
                if prefix:
                    lines.append('[' + prefix + ']')
                for name, child in value.items():
                    if not isinstance(child, dict):
                        lines.append(name + ' = ' + json.dumps(child, ensure_ascii=False))
                for name, child in value.items():
                    if isinstance(child, dict):
                        table(child, prefix + '.' + name if prefix else name)

            table(data)
            return '\n'.join(lines)

        with self.assertRaisesRegex(ValueError, 'editable'):
            update_profile(self.home, 'default', 'https://new.example/v1', 'new', 'new-key')
        self.assertFalse(profiles(self.home)[0]['editable'])
        for data in variants:
            with self.subTest(data=data):
                self.path.write_text(toml(data))
                before = self.path.read_bytes()
                self.assertFalse(next(p for p in profiles(self.home) if p['id'] == self.id)['editable'])
                with self.assertRaisesRegex(ValueError, 'read-only'):
                    update_profile(self.home, self.id, 'https://new.example/v1', 'new', 'new-key')
                self.assertEqual(self.path.read_bytes(), before)
        self.assert_main_unchanged()

    def test_hidden_url_parts_are_sanitized_and_make_sidecar_read_only(self):
        for url in ('https://private-user:private-pass@example.com/v1',
                    'https://example.com/v1?key=private-query',
                    'https://example.com/v1#private-fragment'):
            with self.subTest(url=url):
                data = self.original.decode().replace('https://old.example/v1', url)
                self.path.write_text(data)
                before = self.path.read_bytes()
                row = next(p for p in profiles(self.home) if p['id'] == self.id)
                self.assertEqual(row['endpoint'], 'https://example.com/v1')
                self.assertFalse(row['editable'])
                self.assertNotIn('private-', json.dumps(profiles(self.home)))
                with self.assertRaisesRegex(ValueError, 'read-only'):
                    update_profile(self.home, self.id, row['endpoint'], 'new')
                self.assertEqual(self.path.read_bytes(), before)
        self.assert_main_unchanged()

    def test_unrelated_bad_urls_and_native_metadata_do_not_break_listing(self):
        for index, url in enumerate(('https://[broken/v1', 'https://example.com:bad/v1',
                                     'https://private-user:private-pass@example.com:99999/v1')):
            (self.home / f'bad-{index}.config.toml').write_text(
                'model="native"\nmodel_provider="native"\n[model_providers.native]\nbase_url=' + json.dumps(url))
        (self.home / 'bad-type.config.toml').write_text('model=[]\nmodel_provider=[]\nmodel_providers="bad"\n')
        rows = profiles(self.home)
        self.assertEqual(len(rows), 6)
        self.assertTrue(next(p for p in rows if p['id'] == self.id)['editable'])
        for row in rows:
            if row['id'].startswith('sidecar:bad-'):
                self.assertEqual(row['endpoint'], '')
                self.assertFalse(row['editable'])
        self.assertNotIn('private-', json.dumps(rows))
        self.assert_main_unchanged()

    def test_failed_validation_and_missing_profile_leave_existing_bytes(self):
        invalid = [('ftp://example.com/v1', 'model', ''),
                   ('https://example.com:bad/v1', 'model', ''),
                   ('https://[broken/v1', 'model', ''),
                   ('https://example.com/v1?key=private', 'model', ''),
                   ('https://private:secret@example.com/v1', 'model', ''),
                   ('https://example.com/v1', '', ''),
                   ('https://example.com/v1', 'model', None),
                   ('https://example.com/v1', 'model\ud800', '')]
        for endpoint, model, key in invalid:
            with self.subTest(endpoint=endpoint, model=model, key=key):
                with self.assertRaises(ValueError):
                    update_profile(self.home, self.id, endpoint, model, key)
                self.assertEqual(self.path.read_bytes(), self.original)
        for identifier in ('retained', 'sidecar:../other', 'sidecar:', None, 'sidecar:missing'):
            with self.subTest(identifier=identifier):
                with self.assertRaises(ValueError):
                    update_profile(self.home, identifier, 'https://new.example/v1', 'new', 'new')
                self.assertEqual(self.path.read_bytes(), self.original)
        self.path.unlink()
        with self.assertRaisesRegex(ValueError, 'no longer exists'):
            update_profile(self.home, self.id, 'https://new.example/v1', 'new', 'new')
        self.assertFalse(self.path.exists())
        self.assert_main_unchanged()

    def test_failed_atomic_replace_preserves_original_and_removes_temporary_key_file(self):
        original_files = set(self.home.iterdir())
        with patch('codex_desk.runtime.os.replace', side_effect=OSError('fixture replace failure')):
            with self.assertRaisesRegex(OSError, 'fixture replace failure'):
                update_profile(self.home, self.id, 'https://new.example/v1', 'new-model', 'rotated-key')
        self.assertEqual(self.path.read_bytes(), self.original)
        self.assertEqual(set(self.home.iterdir()), original_files)
        self.assert_main_unchanged()

    def test_desk_default_sidecar_is_distinct_from_read_only_current_settings(self):
        id = save_profile(self.home, 'default', 'https://default.example/v1', 'initial', 'initial-key')['id']
        self.assertEqual(id, 'sidecar:default')
        update_profile(self.home, id, 'https://default.example/v1', 'changed')
        self.assertEqual(profile_config(self.home, id)['model'], 'changed')
        rows = profiles(self.home)
        self.assertFalse(rows[0]['editable'])
        self.assertTrue(next(p for p in rows if p['id'] == id)['editable'])
        self.assert_main_unchanged()

    @unittest.skipUnless(hasattr(os, 'symlink'), 'Platform has no symbolic links')
    def test_symlink_profile_is_read_only(self):
        target = self.home / 'linked.config.toml'
        try:
            target.symlink_to(self.path)
        except OSError:
            self.skipTest('Symbolic links unavailable for this account')
        row = next(p for p in profiles(self.home) if p['id'] == 'sidecar:linked')
        self.assertFalse(row['editable'])
        with self.assertRaisesRegex(ValueError, 'read-only'):
            update_profile(self.home, row['id'], 'https://new.example/v1', 'new', 'new-key')
        self.assertTrue(target.is_symlink())
        self.assertEqual(self.path.read_bytes(), self.original)


if __name__ == '__main__':
    unittest.main()
