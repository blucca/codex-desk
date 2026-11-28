"""Ordinary checkout discovery and disposable fixtures under another user's HOME."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]

# Runs in a fresh interpreter so discovery cannot inherit another test's roots.
PROBE = r'''
import json, os, pathlib, sys, unittest

checkout = pathlib.Path.cwd().resolve()
scratch = pathlib.Path(os.environ.get('DESK_TEST_TEMP', checkout / 'temp')).resolve()
created = []

def audit(event, args):
    if event in ('os.mkdir', 'tempfile.mkdtemp'):
        path = pathlib.Path(args[0]).resolve()
        assert path == scratch or path.is_relative_to(scratch), (
            'Fixture scratch escaped the selected checkout: ' + str(path))
        if event == 'tempfile.mkdtemp':
            created.append(path)

sys.addaudithook(audit)
sys.path.insert(0, str(checkout / 'tests'))
before = os.environ.get('DESK_TEST_TEMP')

if sys.argv[1] == 'discover':
    loader = unittest.TestLoader()
    suite = loader.discover('tests')
    assert not loader.errors, '\n'.join(loader.errors)
    for name in ('test_native_outcome', 'test_native_material',
                 'test_native_outcome_index', 'test_task_response_api',
                 'test_evidence_source_api', 'test_evidence_source_contract'):
        assert name in sys.modules, 'Missing discovered fixture: ' + name
    report = {'discovered': suite.countTestCases()}
else:
    import test_native_outcome as outcome
    import test_task_response_api as response
    import test_browser_preview_linked_original as linked
    import test_launch_http as launch
    import test_steer_admission
    assert outcome.ROOT == scratch, (outcome.ROOT, scratch)
    assert response.ROOT == scratch, (response.ROOT, scratch)
    names = [
        'test_native_outcome.NativeOutcomeTests.'
        'test_cold_state_uses_retained_snapshot_without_native_call_or_new_schema',
        'test_task_response_api.TaskResponseApiTests.'
        'test_one_read_exact_turn_last_final_full_unicode_source_and_zero_writes',
        'test_browser_preview_linked_original.BrowserPreviewLinkedOriginalTests.'
        'test_known_id_and_instruction_entrance_uses_existing_fourth_original',
        'test_launch_http.LaunchHTTPTests.'
        'test_ephemeral_port_serves_own_assets_and_shutdown_reaps_child',
    ]
    result = unittest.TextTestRunner(verbosity=2).run(
        unittest.defaultTestLoader.loadTestsFromNames(names))
    assert result.wasSuccessful(), 'Relocated fixture acceptance failed'
    assert result.testsRun == len(names), result.testsRun
    assert not result.skipped, result.skipped
    assert len(created) == len(names), created
    assert all(path.parent == scratch for path in created), created
    assert all(not path.exists() for path in created), created
    assert not list(scratch.iterdir()), list(scratch.iterdir())
    report = {'executed': result.testsRun, 'cleaned': len(created)}

assert os.environ.get('DESK_TEST_TEMP') == before, 'Import changed fixture environment'
print(json.dumps(report))
'''


class CheckoutScratchTests(unittest.TestCase):
    def setUp(self):
        scratch = Path(os.environ.get('DESK_TEST_TEMP', SOURCE / 'temp')).resolve()
        scratch.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=scratch, prefix='checkout-portability-')
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name) / 'another user'
        self.home.mkdir()
        self.native_home = self.home / '.codex'
        self.native_home.mkdir()
        (self.native_home / 'config.toml').write_text('model = "untouched-user-model"\n')
        (self.native_home / 'auth.json').write_text('{"fixture": "untouched-user-auth"}\n')
        self.home_before = {p.name: p.read_bytes() for p in self.native_home.iterdir()}
        self.checkout = self.home / 'checkout'
        shutil.copytree(SOURCE, self.checkout, ignore=shutil.ignore_patterns(
            '.git', 'temp', '__pycache__', '*.pyc', '*.egg-info', 'build', 'dist'))
        self.env = {key: value for key, value in os.environ.items()
                    if not key.startswith('DESK_') and key not in (
                        'TMPDIR', 'TEMP', 'TMP', 'PYTHONPATH')}
        self.env.update(HOME=str(self.home), USERPROFILE=str(self.home),
                        PYTHONDONTWRITEBYTECODE='1')

    def probe(self, mode):
        result = subprocess.run([sys.executable, '-B', '-c', PROBE, mode],
                                cwd=self.checkout, env=self.env,
                                capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual({p.name: p.read_bytes() for p in self.native_home.iterdir()},
                         self.home_before)
        return json.loads(result.stdout.splitlines()[-1])

    def test_discovery_imports_native_and_inherited_fixtures_without_environment_wrapper(self):
        report = self.probe('discover')
        self.assertGreater(report['discovered'], 0)

    def test_default_fixtures_use_checkout_scratch_and_remove_state(self):
        self.assertEqual(self.probe('fixtures'), {'executed': 4, 'cleaned': 4})

    def test_relative_scratch_alias_is_normalized_without_changing_environment(self):
        (self.checkout / 'temp' / 'alias').mkdir(parents=True)
        self.env['DESK_TEST_TEMP'] = 'temp/alias/../chosen scratch'
        self.assertEqual(self.probe('fixtures'), {'executed': 4, 'cleaned': 4})


if __name__ == '__main__':
    unittest.main()
