"""Portable engine/config contracts for the maintained task-review sample checker."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'examples' / 'check_browser_preview_task_review.py'
SPEC = importlib.util.spec_from_file_location('task_review_harness', SCRIPT)
harness = importlib.util.module_from_spec(SPEC)
sys.path.insert(0, str(ROOT / 'examples'))
try:
    SPEC.loader.exec_module(harness)
finally:
    sys.path.pop(0)


class TaskReviewHarnessTests(unittest.TestCase):
    def args(self, extra=(), env=None):
        return harness.parse_args(['--site', 'temp/sample', '--evidence', 'temp/evidence', *extra], env or {})

    def test_portable_engine_launch_options(self):
        self.assertEqual(harness.browser_options('firefox'), {'headless': True})
        self.assertEqual(harness.browser_options('webkit', '/cache/MiniBrowser'),
                         {'headless': True, 'executable_path': '/cache/MiniBrowser'})
        self.assertIn('--no-sandbox', harness.browser_options('chromium')['args'])

    def test_defaults_and_cli_environment_precedence(self):
        args = self.args()
        self.assertEqual((args.engine, args.widths, args.executable), ('chromium', (1250, 390), None))
        args = self.args(['--engine', 'webkit', '--widths', '390', '--executable', 'temp/webkit'],
                         {'DESK_BROWSER_ENGINE': 'firefox', 'DESK_BROWSER_EXECUTABLE': 'temp/firefox',
                          'DESK_CHROMIUM': 'temp/chromium'})
        self.assertEqual((args.engine, args.widths, args.executable), ('webkit', (390,), 'temp/webkit'))
        self.assertIsNone(self.args(['--engine', 'firefox'], {'DESK_CHROMIUM': 'temp/chromium'}).executable)
        self.assertEqual(self.args(['--chromium', 'temp/custom']).executable, 'temp/custom')

    def test_invalid_engine_widths_and_cross_engine_legacy_option(self):
        for extra, env in [(['--widths', 'wide'], {}), (['--widths', '390,390'], {}),
                           (['--widths', '319'], {}), ([], {'DESK_BROWSER_ENGINE': 'unknown'}),
                           (['--engine', 'firefox', '--chromium', 'temp/chromium'], {})]:
            with self.subTest(extra=extra, env=env), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    self.args(extra, env)
                self.assertEqual(error.exception.code, 2)

    def test_independent_quote_span_includes_unicode_command_header(self):
        command={'command':'inspect 😀', 'status':'completed', 'exitCode':1,
                 'aggregatedOutput':'before 😀\n'+harness.QUOTE}
        prefix='Command\ninspect 😀\nStatus: completed\nExit: 1\nbefore 😀\n'
        span=harness.command_quote_span(command)
        self.assertEqual(span['start'],len(prefix.encode('utf-16-le'))//2)
        self.assertEqual(span['end']-span['start'],len(harness.QUOTE.encode('utf-16-le'))//2)

    def test_help_without_playwright(self):
        result = subprocess.run([sys.executable, str(SCRIPT), '--help'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('--engine {chromium,firefox,webkit}', result.stdout)

    @unittest.skipUnless(shutil.which('node'), 'Node exercises the delegated clipboard observer')
    def test_clipboard_observer_delegates_actual_write_before_recording(self):
        script = """const assert=require('assert/strict');let finish,calls=[];
        Object.defineProperty(globalThis,'navigator',{configurable:true,value:{clipboard:{writeText:text=>{calls.push(text);return new Promise(resolve=>finish=resolve);}}}});
        """ + harness.CLIPBOARD_WRITE_OBSERVER + """
        (async()=>{const pending=navigator.clipboard.writeText('Exact Café 😀 original');
          assert.deepEqual(calls,['Exact Café 😀 original']);assert.equal(global.__deskTaskCopy,undefined);
          finish();await pending;assert.equal(global.__deskTaskCopy,'Exact Café 😀 original');
        })().catch(e=>{console.error(e.stack);process.exitCode=1;});"""
        result = subprocess.run([shutil.which('node'), '-e', script], capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == '__main__':
    unittest.main()
