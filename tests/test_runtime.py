import os
from pathlib import Path
import tempfile
import unittest
from codex_desk.runtime import Store, profiles, profile_config, save_profile

ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)

class PersistenceTests(unittest.TestCase):
    def test_reopen_and_latest_usage(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            db=Path(folder)/'desk.sqlite3';a=Store(db);i=a.create('/work/app','trial')
            a.update(i,thread_id='native-thread',status='completed',usage='{"total":{"inputTokens":100}}')
            a.update(i,usage='{"total":{"inputTokens":120}}')
            a.event(i,{'method':'turn/completed'});a.db.close();b=Store(db)
            self.assertEqual(b.get(i)['thread_id'],'native-thread')
            self.assertIn('120',b.get(i)['usage']);self.assertEqual(len(b.events(i)),1);b.db.close()
    def test_profiles_do_not_expose_keys_or_rewrite_base(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder);base=home/'config.toml';base.write_text('model="base"\n[mcp_servers.keep]\ncommand="keep"\n')
            (home/'trial.config.toml').write_text('model="trial"\nmodel_provider="relay"\n[model_providers.relay]\nbase_url="https://secret:password@example.com/v1?key=private"\nexperimental_bearer_token="private-key"\n')
            before=base.read_bytes();rows=profiles(home);config=profile_config(home,'trial')
            self.assertNotIn('private',str(rows));self.assertNotIn('password',str(rows));self.assertNotIn('secret',str(rows))
            self.assertEqual(config['model'],'trial');self.assertNotIn('mcp_servers',config);self.assertEqual(base.read_bytes(),before)
            self.assertIsNone(profile_config(home,'default'))
            with self.assertRaises(ValueError):profile_config(home,'../../other')

    def test_new_profile_is_local_private_and_never_overwrites(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as folder:
            home=Path(folder)
            result=save_profile(home,'my-api','http://127.0.0.1:9999/v1','fixture','local-test-secret')
            self.assertEqual(result,{'id':'sidecar:my-api'})
            self.assertEqual((home/'my-api.config.toml').stat().st_mode & 0o777,0o600)
            self.assertNotIn('local-test-secret',str(profiles(home)))
            self.assertEqual(profile_config(home,'my-api')['model'],'fixture')
            with self.assertRaises(ValueError):save_profile(home,'my-api','https://example.com/v1','other','other')
            default=save_profile(home,'default','https://example.com/v1','sidecar-default','test-default')
            self.assertEqual(default['id'],'sidecar:default')
            self.assertEqual(profile_config(home,'sidecar:default')['model'],'sidecar-default')
            self.assertIsNone(profile_config(home,'default'))
            self.assertEqual(profiles(home)[0]['id'],'default')
            with self.assertRaises(ValueError):save_profile(home,'../other','https://example.com/v1','other','other')

if __name__=='__main__':unittest.main()
