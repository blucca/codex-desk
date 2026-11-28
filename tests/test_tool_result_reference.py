"""Tool-result reference namespace uses explicit reader-owned result segments."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from codex_desk import evidence_reference as E

@unittest.skipUnless(shutil.which('node'),'Node required')
class ToolResultReferenceTests(unittest.TestCase):
    def test_production_segments_unicode_parity_and_fresh_reader_mapping(self):
        result=subprocess.run([shutil.which('node'),str(Path(__file__).with_suffix('.js'))],capture_output=True,text=True,timeout=30)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        fixtures=json.loads(result.stdout)['fixtures']
        for f in fixtures:
            parts=lambda item:f['before_parts']
            reference=E.capture_reference(f['before'],native_home='a'*64,thread_id='A',turn_id='t',item_id='tool',quote_start=f['start_codepoint'],quote_end=f['end_codepoint'],text_for_item=lambda item:parts(item)['text'],parts_for_item=parts)
            self.assertEqual(reference,f['reference']);self.assertEqual(E.format_evidence_block(reference),f['block']);self.assertEqual(E.parse_evidence_blocks(f['block'])[0]['reference'],reference)
            fresh=lambda item:f['fresh_parts'];resolve=lambda ref:E.resolve_reference(ref,'a'*64,f['fresh'],text_for_item=lambda item:fresh(item)['text'],parts_for_item=fresh)
            self.assertEqual(resolve(reference),f['resolved'])
            self.assertEqual(E.resolve_reference(reference,'a'*64,f['fresh'],text_for_item=lambda item:fresh(item)['text'])['status'],'quote_unavailable')
            bad=lambda item:{**fresh(item),'result':'Not the agreed renderer body'}
            self.assertEqual(E.resolve_reference(reference,'a'*64,f['fresh'],text_for_item=lambda item:fresh(item)['text'],parts_for_item=bad)['status'],'quote_unavailable')
            self.assertEqual(E.parse_evidence_blocks(f['block'].replace('history-reader-tool-result/v1','unsupported-result/v1')),[])

if __name__=='__main__':unittest.main()
