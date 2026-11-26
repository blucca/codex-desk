"""Public stdlib snapshot example: literal normalized lookup keeps original IDs."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get('DESK_TEST_TEMP', str(Path.cwd() / 'temp')))
ROOT.mkdir(parents=True, exist_ok=True)


class NativeAnswerExampleTests(unittest.TestCase):
    def lookup(self, phrase):
        fixture = SOURCE / 'examples/native-answer-snapshot.json'
        original = fixture.read_bytes()
        with tempfile.TemporaryDirectory(dir=ROOT, prefix='desk-native-answer-') as temporary:
            snapshot = Path(temporary) / 'snapshot.json'
            snapshot.write_bytes(original)
            result = subprocess.run([
                sys.executable, '-B', str(SOURCE / 'examples/find_native_answer.py'),
                str(snapshot), phrase,
            ], cwd=temporary, capture_output=True, text=True, timeout=5, check=True)
            self.assertEqual(result.stderr, '')
            self.assertEqual(snapshot.read_bytes(), original)
        self.assertEqual(fixture.read_bytes(), original)
        return [json.loads(line) for line in result.stdout.splitlines()]

    def expected(self):
        return [
            {'threadId': 'synthetic-checkout-thread', 'turnId': 'synthetic-turn',
             'itemId': 'synthetic-answer', 'preview': 'RETRY BUDGET: retain the original retry limit.'},
            {'threadId': 'synthetic-checkout-thread', 'turnId': 'synthetic-turn',
             'itemId': 'synthetic-command', 'preview': 'Retry budget verified: 2 attempts retained.'},
        ]

    def test_normal_phrase_returns_two_original_items(self):
        self.assertEqual(self.lookup('retry budget'), self.expected())

    def test_fullwidth_phrase_returns_same_ids_and_original_previews(self):
        self.assertEqual(self.lookup('ＲＥＴＲＹ ＢＵＤＧＥＴ'), self.expected())

    def test_regex_punctuation_is_literal_and_null_output_is_empty(self):
        self.assertEqual(self.lookup('.*'), [])


if __name__ == '__main__':
    unittest.main()
