"""Maintained archived preview originals and source-only reading-place metadata."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('revisit_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')

class BrowserPreviewRevisitOriginalTests(unittest.TestCase):
    def test_existing_fourth_original_is_archived_without_additional_sample_content(self):
        ordinary=preview.sample_threads();rich,_=preview.reading_fixture()
        for histories,items in ((ordinary,13),(rich,15)):
            self.assertEqual(len(histories),4)
            self.assertEqual(sum(len(t['items']) for h in histories for t in h['turns']),items)
            archived=[h for h in histories if h.get('archived')]
            self.assertEqual([h['id'] for h in archived],[preview.CHILD])
            self.assertEqual(archived[0],ordinary[-1])
            self.assertGreater(len(archived[0]['turns'][0]['items'][1]['text']),100000)

    def test_all_four_builds_namespace_only_reading_metadata_and_show_explicit_revisit(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='revisit-preview-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    output=preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    html=(output/'index.html').read_text()
                    self.assertIn('Archived native conversations',html)
                    self.assertIn('linked retry original',html)
                    self.assertIn('explicitly reopen by title or known ID',html)
                    checkpoint=(output/'reading_checkpoint.js').read_text()
                    self.assertIn(repr(preview.READING_KEY),checkpoint)
                    self.assertIn(repr(preview.ORIGINAL_READING_KEY),checkpoint)
                    self.assertNotIn("'codex-desk-original-reading-checkpoints-v1'",checkpoint)
                    self.assertEqual((output/'history_reader.js').read_bytes(),(ROOT/'codex_desk/static/history_reader.js').read_bytes())

    @unittest.skipUnless(NODE,'Node is needed for maintained sample transport tests')
    def test_native_catalog_modes_and_fresh_original_reads_never_change_preparation(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='revisit-api-') as tmp:
            output=preview.build(Path(tmp)/'demo')
            script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stored=new Map();let external=0,reloads=0;
global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>reloads++};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('No external transport');}};
const load=name=>vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
load('sample-data.js');load('preview-api.js');
(async()=>{
 const request=async(path,data)=>{const r=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});return {status:r.status,body:await r.json()};};
 const child=window.DeskPreviewThreads.at(-1),B=window.DeskPreviewThreads[1];
 const id=(await request('/api/import',{thread:B.id})).body.id;
 await request('/api/draft',{session:id,text:'Existing B unsent Plan',mode:'plan',revision:0});
 for(const mode of ['native','plan'])await request('/api/followups',{session:id,text:'Retained '+mode,mode});
 const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored);
 for(const path of ['/api/native','/api/native?archived=false']){
  const r=await request(path);assert.equal(r.status,200);assert.equal(r.body.data.length,3);assert(!r.body.data.some(t=>t.id===child.id));
 }
 assert.deepEqual((await request('/api/native?archived=true')).body.data.map(t=>t.id),[child.id]);
 assert.equal((await request('/api/native?archived=false&search=linked')).body.data.length,0);
 assert.deepEqual((await request('/api/native?archived=true&search=linked')).body.data.map(t=>t.id),[child.id]);
 for(const path of ['/api/native?archived=','/api/native?archived=1','/api/native?archived=True','/api/native?archived=true&archived=false'])assert.equal((await request(path)).status,400,path);
 assert.deepEqual((await request('/api/native/thread?id='+child.id)).body,child);
 const home=(await request('/api/native/home')).body.home_namespace;
 assert.deepEqual((await request('/api/native/evidence-source?home='+home+'&thread='+child.id)).body.thread,child);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual(Object.fromEntries(stored),raw);
 const previewKey=window.DeskBrowserPreview.originalReadingKey,installedKey='codex-desk-original-reading-checkpoints-v1';
 stored.set(previewKey,JSON.stringify({version:1,checkpoints:[]}));stored.set(installedKey,'untouched installed metadata');
 const checkpoint=stored.get(previewKey);load('preview-api.js');assert.equal(stored.get(previewKey),checkpoint);assert.equal(reloads,0);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);
 window.DeskBrowserPreview.reset();assert.equal(reloads,1);assert.equal(stored.has(previewKey),false);assert.equal(stored.get(installedKey),'untouched installed metadata');
 assert.equal(external,0);console.log(JSON.stringify({passed:true,current:3,archived:1,reset_metadata_only:true}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''
            r=subprocess.run([NODE,'-e',script,str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue(json.loads(r.stdout)['passed'])

if __name__=='__main__':unittest.main()
