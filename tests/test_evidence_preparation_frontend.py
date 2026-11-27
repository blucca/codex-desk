"""Standalone Node source/reference and local preparation ownership acceptance."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(NODE, 'Node is required for frontend ownership tests')
class EvidencePreparationFrontendTests(unittest.TestCase):
    def test_exact_artifact_and_controller_ownership(self):
        result = subprocess.run([NODE, str(ROOT / 'tests/test_evidence_preparation_frontend.js')],
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"passed":true', result.stdout)


if __name__ == '__main__':
    unittest.main()
