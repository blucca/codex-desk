"""Static distribution sample tracks maintained assets without changing runtime."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
import os
import json
import shutil
import subprocess

ROOT=Path(__file__).resolve().parents[1]
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
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
            self.assertIn('id="preview-start"',html)
            self.assertIn(preview.PUBLIC,html)
            self.assertNotIn('src="/',html)
            for name in ('evidence.js','activity.js','history_reader.js','native-state.js','followups.js','recall.js','home.js','style.css'):
                self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes())
            self.assertEqual((output/'app.js').read_text(),(ROOT/'codex_desk/static/app.js').read_text().replace("'codex-desk-session'","'codex-desk-browser-preview-session-v1'"))
            source=json.loads((output/'preview-source.json').read_text())
            self.assertTrue(source['sample'])
            self.assertEqual(source['source'],'blucca/codex-desk')

    def test_embedded_installer_keeps_native_popup_function(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='preview-embedded-') as tmp:
            output=preview.build(Path(tmp)/'demo',embedded=True)
            html=(output/'index.html').read_text()
            self.assertIn('data-preview-embedded="true"',html)
            self.assertIn('target="_blank" rel="noopener noreferrer"',html)
            api=(output/'preview-api.js').read_text()
            self.assertIn('const openExternal=window.open.bind(window)',api)
            self.assertIn("openExternal(url,'_blank','noopener')",api)
            self.assertNotIn("window.open('https://github.com/",api)

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

    @unittest.skipUnless(NODE, 'Node is needed for sample API controller units')
    def test_missing_sample_script_reports_reload_without_mutating_preparation(self):
        script = r'''
const fs=require('fs'),vm=require('vm');
const saved={sessions:[{id:'saved-preparation'}],indexed:false,drafts:{'saved-preparation':{text:'Keep this unsent draft',mode:'plan',revision:1}},followups:{},nextId:1};
let stored=JSON.stringify(saved);
global.localStorage={getItem:()=>stored,setItem:(_key,value)=>{stored=value;}};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1'};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{throw new Error('Unexpected external request');}};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
(async()=>{
 const result=[];
 for(const [path,options] of [
  ['/api/native',{}],['/api/native/thread?id=sample-checkout-thread',{}],
  ['/api/recall?q=retry',{}],['/api/history/index',{method:'POST',body:'{}'}],
  ['/api/import',{method:'POST',body:'{"thread":"sample-checkout-thread"}'}],
  ['/api/open',{method:'POST',body:'{"session":"saved-preparation"}'}]]){
  const response=await window.fetch(path,options);result.push({status:response.status,...await response.json()});
 }
 const state=await (await window.fetch('/api/state')).json();
 process.stdout.write(JSON.stringify({result,state,preserved:JSON.parse(stored),snapshot:window.DeskBrowserPreview.snapshot()}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        result=subprocess.run([NODE,'-e',script,str(ROOT/'examples/browser-preview/preview-api.js')],
                              capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        result=json.loads(result.stdout)
        self.assertEqual(len(result['result']),6)
        for response in result['result']:
            self.assertEqual(response['status'],400)
            self.assertEqual(response['error'],'Sample histories did not load. Reload this page to try again.')
        self.assertEqual(result['preserved'],result['snapshot'])
        self.assertFalse(result['snapshot']['indexed'])
        self.assertEqual(result['snapshot']['drafts']['saved-preparation']['text'],'Keep this unsent draft')
        self.assertEqual(result['state']['sessions'],result['snapshot']['sessions'])


if __name__=='__main__':unittest.main()
