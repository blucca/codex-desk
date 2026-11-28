"""Original Find overview is maintained UI, not an extra sample source/event fixture."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('find_matches_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
class BrowserPreviewFindMatchesTests(unittest.TestCase):
    def test_four_modes_keep_counts_and_copy_exact_find_assets(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='find-matches-build-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    output=preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    html=(output/'index.html').read_text()
                    for label in ['Show Find matches','Return to Find matches','Return to current passage']:
                        self.assertIn(label,html)
                    for identity in ['history-reader-find-matches-show','history-reader-find-matches-return','history-reader-find-match-list']:
                        self.assertEqual(html.count('id="'+identity+'"'),1)
                    histories=preview.reading_fixture()[0] if rich else preview.sample_threads()
                    self.assertEqual(len(histories),4);self.assertEqual(sum(len(t['items']) for h in histories for t in h['turns']),15 if rich else 13)
                    self.assertEqual(histories[-1]['turns'][0]['items'][1]['text'].count(preview.CHILD_QUOTE),2)
                    for name in ['history_reader.js','history_find.js','style.css']:
                        self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes())
if __name__=='__main__':unittest.main()
