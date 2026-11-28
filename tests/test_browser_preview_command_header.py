"""Deliberate original command fixture preserves counts, native output and preparation."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('header_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')

class BrowserPreviewCommandHeaderTests(unittest.TestCase):
    def test_four_modes_preserve_initial_counts_and_maintained_runtime(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='command-header-build-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    output=preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    html=(output/'index.html').read_text()
                    for identity in ('preview-header-prepare','preview-header-toggle','preview-header-reader-toggle'):
                        self.assertEqual(html.count('id="'+identity+'"'),1)
                    self.assertIn('Prepare sample command output',html)
                    self.assertIn('Complete sample command',html)
                    histories=preview.reading_fixture()[0] if rich else preview.sample_threads()
                    self.assertEqual(len(histories),4)
                    self.assertEqual(sum(len(t['items']) for h in histories for t in h['turns']),15 if rich else 13)
                    for name in ('history_reader.js','history_tasks.js','history_find.js','style.css'):
                        self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes())
                    self.assertEqual((output/'reading_checkpoint.js').read_text(),(ROOT/'codex_desk/static/reading_checkpoint.js').read_text().replace("'codex-desk-reading-checkpoints-v1'",repr(preview.READING_KEY)).replace("'codex-desk-original-reading-checkpoints-v1'",repr(preview.ORIGINAL_READING_KEY)))

    @unittest.skipUnless(NODE,'Node is needed for sample transport units')
    def test_prepare_toggle_and_held_fresh_read_change_only_source_header(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='command-header-api-') as tmp:
            output=preview.build(Path(tmp)/'demo')
            script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');const stored=new Map();let external=0;
global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>{}};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('Unexpected external transport');}};
const load=name=>vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));load('sample-data.js');load('preview-api.js');
(async()=>{
 const request=async(path,data)=>{const r=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});assert.equal(r.status,200);return await r.json();};
 const B=(await request('/api/import',{thread:'sample-docs-thread'})).id;
 await request('/api/draft',{session:B,text:'Exact existing B Plan',mode:'plan',revision:0});
 for(const mode of ['native','plan'])await request('/api/followups',{session:B,text:'Retained '+mode,mode});
 const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored),f=window.DeskBrowserPreview.headerFixture;
 const count=()=>window.DeskPreviewThreads.reduce((n,h)=>n+h.turns.reduce((m,t)=>m+t.items.length,0),0);
 assert.equal(count(),13);assert.equal(f.prepare(),true);assert.equal(f.prepare(),false);
 assert.equal(f.command().status,'inProgress');assert.equal(Object.hasOwn(f.command(),'exitCode'),false);
 const output=f.command().aggregatedOutput;assert.equal(output.split('\n').length,10000);assert(output.includes(f.quote));
 const read=await request('/api/native/thread?id='+f.threadId);f.toggle();assert.equal(f.command().status,'completed');assert.equal(f.command().exitCode,0);
 assert.equal(f.command().aggregatedOutput,output);assert.equal(read.turns[0].items[2].status,'inProgress');
 f.hold();const pending=request('/api/native/thread?id='+f.threadId);await Promise.resolve();await Promise.resolve();assert.equal(f.held(),true);
 f.toggle();f.release();const fresh=await pending;assert.equal(fresh.turns[0].items[2].status,'inProgress');assert.equal(fresh.turns[0].items[2].aggregatedOutput,output);
 assert.equal(count(),13);assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual(Object.fromEntries(stored),raw);assert.equal(external,0);
 console.log(JSON.stringify({passed:true,identical_native_output:true,source_only_header:true}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''
            r=subprocess.run([NODE,'-e',script,str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr);self.assertTrue(json.loads(r.stdout)['passed'])
if __name__=='__main__':unittest.main()
