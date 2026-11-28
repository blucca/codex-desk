"""Focused CLI/config and receipt contracts for original-keyboard acceptance."""
import ast
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import tomllib
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'tests' / 'browser_original_keyboard.py'
SPEC = importlib.util.spec_from_file_location('original_keyboard_harness', SCRIPT)
harness = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = harness
SPEC.loader.exec_module(harness)


class OriginalKeyboardHarnessTests(unittest.TestCase):
    def test_defaults_need_no_playwright_import(self):
        config = harness.parse_config([], {})
        self.assertEqual(config.source, ROOT)
        self.assertEqual((config.engine, config.widths, config.installed), ('chromium', (1250, 390), False))
        self.assertEqual(config.scratch, ROOT / 'temp' / 'original-keyboard')
        self.assertEqual(config.evidence, config.scratch / 'evidence')

    def test_cli_overrides_environment_and_preserves_installed_guards(self):
        config = harness.parse_config(['--engine', 'firefox', '--widths', '390', '--scratch', 'temp/keyboard-test'], {
            'DESK_SOURCE': str(ROOT), 'DESK_BROWSER_ENGINE': 'chromium',
            'DESK_USE_INSTALLED': '1', 'DESK_INSTALLED_ROOT': 'temp/installed',
            'DESK_EXPECT_VERSION': '0.1.0a64', 'DESK_TEST_TEMP': 'temp/old',
            'DESK_TEST_EVIDENCE': 'temp/evidence', 'PLAYWRIGHT_BROWSERS_PATH': 'temp/browsers',
            'DESK_BROWSER_EXECUTABLE': 'temp/browsers/firefox',
        })
        self.assertEqual((config.engine, config.widths, config.installed), ('firefox', (390,), True))
        self.assertEqual(config.scratch, Path('temp/keyboard-test').resolve())
        self.assertEqual(config.expect_version, '0.1.0a64')
        self.assertEqual(config.installed_root, Path('temp/installed').resolve())
        self.assertEqual(config.browsers_path, Path('temp/browsers').resolve())
        self.assertEqual(config.executable, Path('temp/browsers/firefox').resolve())

    def test_engine_environment_is_case_insensitive_and_webkit_ready(self):
        self.assertEqual(harness.parse_config([], {'DESK_BROWSER_ENGINE': 'Firefox'}).engine, 'firefox')
        self.assertEqual(harness.parse_config(['--engine', 'webkit'], {}).engine, 'webkit')

    def test_rejects_invalid_config_before_browser_start(self):
        invalid = [(['--engine', 'unknown'], {}), ([], {'DESK_BROWSER_ENGINE': 'unknown'}),
                   (['--widths', '319'], {}), (['--widths', 'wide'], {}),
                   (['--widths', '390', '390'], {}), (['--source', str(ROOT / 'tests')], {}),
                   (['--installed-root', 'temp/env'], {})]
        for argv, env in invalid:
            with self.subTest(argv=argv, env=env), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    harness.parse_config(argv, env)
                self.assertEqual(error.exception.code, 2)

    def test_help_runs_without_optional_browser_dependencies(self):
        result = subprocess.run([sys.executable, '-I', str(SCRIPT), '--help'], text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--engine {chromium,firefox,webkit}', result.stdout)
        self.assertIn('--installed-root', result.stdout)

    def test_startup_failure_retains_traceback_and_nonzero_exit(self):
        scratch = Path(os.environ.get('DESK_TEST_TEMP', ROOT / 'temp'))
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch, prefix='keyboard-cli-') as temporary:
            root = Path(temporary)
            config = harness.parse_config(['--installed', '--scratch', str(root / 'scratch'),
                                           '--evidence', str(root / 'evidence')], {})
            async def failed(_config):
                raise OSError('test browser executable missing')
            old_mask = os.umask(0o077)
            try:
                with patch.object(harness, 'parse_config', return_value=config), patch.object(harness, 'run', failed), contextlib.redirect_stdout(io.StringIO()):
                    self.assertEqual(harness.main([]), 1)
            finally:
                os.umask(old_mask)
            summary = json.loads((config.evidence / 'summary.json').read_text())
            self.assertEqual((summary['result'], summary['phase'], summary['installed']), ('FAIL', 'harness', True))
            self.assertIn('test browser executable missing', summary['traceback'])

    def test_workflow_reads_dynamic_source_version_without_importing_source(self):
        project=tomllib.loads((ROOT / 'pyproject.toml').read_text())['project']
        self.assertNotIn('version',project)
        self.assertIn('version',project['dynamic'])
        workflow=(ROOT / '.github/workflows/daily-workbench.yml').read_text()
        snippet=re.search(r"expected=\$\(python -c '([^']+)'\)",workflow).group(1)
        scratch=ROOT / 'temp'
        scratch.mkdir(exist_ok=True)
        result=subprocess.run([sys.executable,'-I','-c',snippet],cwd=scratch,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        module=ast.parse((ROOT / 'codex_desk/__init__.py').read_text())
        expected=next(ast.literal_eval(node.value) for node in module.body if isinstance(node,ast.Assign)
                      and any(isinstance(target,ast.Name) and target.id=='__version__' for target in node.targets))
        self.assertEqual(result.stdout.strip(),expected)

    def test_cross_language_quote_offsets_use_utf16(self):
        self.assertEqual(harness.utf16('Café 项目 😀'), len('Café 项目 😀') + 1)


if __name__ == '__main__':
    unittest.main()
