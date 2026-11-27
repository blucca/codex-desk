"""Installed daily fixtures use explicit source support and portable Chromium."""
import ast
from pathlib import Path
from types import SimpleNamespace
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / '.github/workflows/daily-workbench.yml'


class DailyWorkflowSetupTests(unittest.TestCase):
    def test_installed_command_supplies_source_and_receipt_environment(self):
        workflow = WORKFLOW.read_text()
        self.assertIn('DESK_SOURCE: ${{ github.workspace }}', workflow)
        self.assertIn('DESK_USE_INSTALLED=1', workflow)
        self.assertIn('DESK_TEST_EVIDENCE="$PWD/evidence/$fixture"', workflow)
        self.assertIn('assert not installed.is_relative_to(source)', workflow)

    def test_selected_browser_launches_use_managed_default_or_override(self):
        workflow = WORKFLOW.read_text()
        selected = workflow.split('for fixture in ', 1)[1].split('; do', 1)[0].split()
        for name in selected:
            with self.subTest(fixture=name):
                tree = ast.parse((ROOT / 'tests' / f'browser_{name}.py').read_text())
                paths = [kw.value for node in ast.walk(tree) if isinstance(node, ast.Call)
                         and isinstance(node.func, ast.Attribute) and node.func.attr == 'launch'
                         for kw in node.keywords if kw.arg == 'executable_path']
                self.assertTrue(paths)
                for value in paths:
                    expression = compile(ast.Expression(value), '<browser executable>', 'eval')
                    for environ, expected in (({}, None), ({'DESK_CHROMIUM': '/chosen/chromium'}, '/chosen/chromium')):
                        self.assertEqual(eval(expression, {'os': SimpleNamespace(environ=environ)}), expected)


if __name__ == '__main__':
    unittest.main()
