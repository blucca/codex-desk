import os
from pathlib import Path
import tempfile
import unittest
from codex_desk.runtime import Store, profiles, overrides

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
            before=base.read_bytes();rows=profiles(home);args=overrides(home,'trial')
            self.assertNotIn('private',str(rows));self.assertNotIn('password',str(rows));self.assertNotIn('secret',str(rows))
            self.assertIn('model="trial"',args);self.assertIn('model_providers.relay.base_url="https://secret:password@example.com/v1?key=private"',args);self.assertNotIn('mcp_servers',str(args));self.assertEqual(base.read_bytes(),before)
            self.assertEqual(overrides(home,'default'),[])
            with self.assertRaises(ValueError):overrides(home,'../../other')

if __name__=='__main__':unittest.main()
