"""Static distribution sample tracks maintained assets without changing runtime."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import os
import json

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('browser_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)


class BrowserPreviewBuildTests(unittest.TestCase):
    def test_source_assets_and_route_are_preserved(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='preview-build-') as tmp:
            output=preview.build(Path(tmp)/'demo')
            html=(output/'index.html').read_text()
            self.assertIn('id="preview-banner"',html)
            self.assertIn(preview.PUBLIC,html)
            self.assertNotIn('src="/',html)
            for name in ('evidence.js','activity.js','history_reader.js','native-state.js','followups.js','recall.js','home.js','style.css'):
                self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes())
            self.assertEqual((output/'app.js').read_text(),(ROOT/'codex_desk/static/app.js').read_text().replace("'codex-desk-session'","'codex-desk-browser-preview-session-v1'"))
            source=json.loads((output/'preview-source.json').read_text())
            self.assertTrue(source['sample'])
            self.assertEqual(source['source'],'blucca/codex-desk')

    def test_sample_original_id_contract(self):
        threads=preview.sample_threads()
        self.assertEqual(len(threads),3)
        original=threads[0]
        self.assertEqual(original['id'],'sample-checkout-thread')
        turn=original['turns'][0]
        self.assertEqual(turn['id'],'sample-checkout-turn')
        answer=turn['items'][1]
        self.assertEqual(answer['id'],'sample-checkout-answer')
        self.assertIn('retry budget',answer['text'])
        self.assertTrue(all(t['cwd'].startswith('/sample/') for t in threads))


if __name__=='__main__':unittest.main()
