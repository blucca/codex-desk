"""Pure original-offset Find contract; no browser, native process, or disk state."""
import json
from pathlib import Path
import shutil
import subprocess
import unicodedata
import unittest

HELPER = Path(__file__).resolve().parents[1] / 'codex_desk' / 'static' / 'history_find.js'
NODE = shutil.which('node')


@unittest.skipUnless(NODE, 'Node.js is required for the pure browser helper contract')
class HistoryFindTests(unittest.TestCase):
    def check(self, cases, script=None):
        code = script or r"""
const fs=require('fs'),h=require(process.argv[1]);
const cases=JSON.parse(fs.readFileSync(0,'utf8'));
process.stdout.write(JSON.stringify(cases.map(({text,query})=>({
  normalized:h.normalize(text),spans:Array.from(h.spans(text,query))
}))));
"""
        result = subprocess.run([NODE, '-e', code, str(HELPER)],
            input=json.dumps(cases, ensure_ascii=False), text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_literal_occurrences_no_match_and_empty_query(self):
        cases = [{'text': 'Use a%b_c[0].* twice: A%B_C[0].*', 'query': 'a%b_c[0].*'},
                 {'text': 'unchanged original', 'query': 'absent'},
                 {'text': 'unchanged original', 'query': ''}]
        actual = self.check(cases)
        self.assertEqual(actual[0]['spans'], [{'start': 4, 'end': 14}, {'start': 22, 'end': 32}])
        self.assertEqual(actual[1]['spans'], [])
        self.assertEqual(actual[2]['spans'], [])

    def test_unicode_casefold_normalization_keeps_exact_original_offsets(self):
        cases = [
            ('🧪 Straße / STRASSE', 'strasse', [(3, 9), (12, 19)]),
            ('🧪 Cafe\u0301 / CAFÉ', 'café', [(3, 8), (11, 15)]),
            ('🧪 ＡＢＣ / 𝔄🧪 proof', 'abc', [(3, 6)]),
            ('🧪 가 proof', '가 proof', [(3, 11)]),
            ('Σςσ', 'Σ', [(0, 1), (1, 2), (2, 3)]),
            ('ß', 's', [(0, 1)]),
            ('🧪 constructor __proto__ toString', 'constructor', [(3, 14)]),
        ]
        actual = self.check([{'text': text, 'query': query} for text, query, _ in cases])
        for result, (text, _, expected) in zip(actual, cases):
            with self.subTest(text=text):
                normalized = unicodedata.normalize('NFKC', unicodedata.normalize('NFKC', text).casefold())
                self.assertEqual(result['normalized'], normalized)
                self.assertEqual(result['spans'], [{'start': start, 'end': end} for start, end in expected])

    def test_authoritative_casefold_deviations_from_lowercase(self):
        chars = [chr(n) for n in range(0x110000) if chr(n).casefold() != chr(n).lower()]
        cases = [{'text': char, 'query': unicodedata.normalize('NFKC',
                    unicodedata.normalize('NFKC', char).casefold())} for char in chars]
        for char, result, case in zip(chars, self.check(cases), cases):
            with self.subTest(character=f'U+{ord(char):04X}'):
                self.assertEqual(result['normalized'], case['query'])
                self.assertEqual(result['spans'], [{'start': 0, 'end': len(char.encode('utf-16-le')) // 2}])

    def test_compatibility_composition_across_cluster_and_chunk_boundaries(self):
        cases = [
            {'text': '\uffa1\uffc2', 'query': '가'},
            {'text': 'カ' * 4095 + 'カ\uff9e', 'query': 'ガ'},
            {'text': 'カ' * 4095 + '\uffa1\uffc2', 'query': '가'},
            {'text': 'a' * 4095 + 'e\u0301', 'query': 'é'},
        ]
        expected = [(0, 2), (4095, 4097), (4095, 4097), (4095, 4097)]
        for result, case, span in zip(self.check(cases), cases, expected):
            with self.subTest(phrase=case['query']):
                self.assertEqual(result['normalized'], unicodedata.normalize('NFKC',
                    unicodedata.normalize('NFKC', case['text']).casefold()))
                self.assertEqual(result['spans'], [{'start': span[0], 'end': span[1]}])

    def test_full_two_million_character_output_first_and_last_occurrences(self):
        text = 'FIRST Diagnostic\n' + 'x' * 1_000_000 + '\nCafé 项目\n' + 'x' * 1_000_000 + '\nLAST DIAGNOSTIC'
        result = self.check([{'text': text, 'query': 'diagnostic'}])[0]
        self.assertEqual(result['spans'], [{'start': 6, 'end': 16},
            {'start': len(text) - 10, 'end': len(text)}])
        self.assertEqual(result['normalized'], unicodedata.normalize('NFKC', text.casefold()))

    def test_dense_matches_use_compact_offsets_and_keep_first_last(self):
        script = r"""
const h=require(process.argv[1]),n=2000000,spans=h.spans('e'.repeat(n),'e');
process.stdout.write(JSON.stringify({length:spans.length,first:spans.at(0),last:spans.at(-1),
  compact:spans.values.data instanceof Uint32Array}));
"""
        result = self.check([], script)
        self.assertEqual(result, {'length': 2_000_000, 'first': {'start': 0, 'end': 1},
                                 'last': {'start': 1_999_999, 'end': 2_000_000}, 'compact': True})

    def test_large_unchanged_unicode_output_does_not_need_character_objects(self):
        text = '項' * 2_000_000 + '完整原文'
        script = r"""
const fs=require('fs'),h=require(process.argv[1]),[{text,query}]=JSON.parse(fs.readFileSync(0,'utf8'));
const spans=h.spans(text,query);
process.stdout.write(JSON.stringify(Array.from(spans)));
"""
        self.assertEqual(self.check([{'text': text, 'query': '完整原文'}], script),
                         [{'start': 2_000_000, 'end': 2_000_004}])

    def test_async_search_yields_and_invalidated_work_returns_no_results(self):
        script = r"""
const h=require(process.argv[1]);
(async()=>{
  let valid=true;setTimeout(()=>{valid=false;},0);
  const cancelled=await h.spansAsync('e'.repeat(2000000),'e',()=>valid);
  const fresh=await h.spansAsync('Cafe\u0301 / CAFÉ','café');
  process.stdout.write(JSON.stringify({cancelled:cancelled===null,fresh:Array.from(fresh)}));
})().catch(error=>{process.stderr.write(String(error));process.exit(1);});
"""
        self.assertEqual(self.check([], script), {'cancelled': True,
            'fresh': [{'start': 0, 'end': 5}, {'start': 8, 'end': 12}]})


if __name__ == '__main__':
    unittest.main()
