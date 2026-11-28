"""Source-only sample additions and scoped original-frontier metadata."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('following_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')

class BrowserPreviewFollowingOriginalTests(unittest.TestCase):
    def test_four_builds_preserve_default_sources_and_namespace_only_frontier_key(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='following-preview-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    output=preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    html=(output/'index.html').read_text()
                    self.assertIn('id="preview-supply-original"',html)
                    self.assertIn('Read first newly supplied item',html)
                    self.assertIn('Return to original passage',html)
                    self.assertIn('previous fresh original read',html)
                    self.assertEqual((output/'original_frontier.js').read_text(),(ROOT/'codex_desk/static/original_frontier.js').read_text().replace("'codex-desk-original-frontiers-v1'",repr(preview.ORIGINAL_FRONTIER_KEY)))
                    for name in ('history_reader.js','history_tasks.js','history_find.js','style.css'):
                        self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes())
                    histories=preview.reading_fixture()[0] if rich else preview.sample_threads()
                    self.assertEqual(len(histories),4)
                    self.assertEqual(sum(len(t['items']) for h in histories for t in h['turns']),15 if rich else 13)

    @unittest.skipUnless(NODE,'Node is needed for maintained sample transport tests')
    def test_explicit_addition_fresh_original_and_scoped_reset(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='following-api-') as tmp:
            output=preview.build(Path(tmp)/'demo')
            script=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stored=new Map();let external=0,reloads=0;
global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>reloads++};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('No external transport');}};
const load=name=>vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
load('sample-data.js');load('preview-api.js');load('original_frontier.js');
(async()=>{
 const request=async(path,data)=>{const r=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});assert.equal(r.status,200);return await r.json();};
 const child=window.DeskPreviewThreads.at(-1),B=window.DeskPreviewThreads[1];
 const id=(await request('/api/import',{thread:B.id})).id;
 await request('/api/draft',{session:id,text:'Existing B unsent Plan',mode:'plan',revision:0});
 for(const mode of ['native','plan'])await request('/api/followups',{session:id,text:'Retained '+mode,mode});
 const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored);
 const previous=await request('/api/native/thread?id='+child.id);
 const frontier=global.DeskOriginalFrontier,owner={native_home:(await request('/api/native/home')).home_namespace,thread_id:child.id};
 const cache=frontier.create(localStorage);cache.put(owner,frontier.snapshot(previous));
 assert.equal(previous.turns[0].items.length,3);
 const f=window.DeskBrowserPreview.originalFixture;
 assert.equal(f.append(),true);assert.equal(f.append(),false);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);
 for(const [k,v] of Object.entries(raw))assert.equal(stored.get(k),v);
 const fresh=await request('/api/native/thread?id='+child.id);
 assert.deepEqual(frontier.resolve(cache.get(owner),fresh),{status:'new_items',count:5,target:{turn_id:f.turnId,item_id:f.itemId},index:3});
 assert.equal(previous.turns.length,1);assert.equal(fresh.turns.length,3);
 const previewKey=window.DeskBrowserPreview.originalFrontierKey;
 assert.equal(previewKey,frontier.STORAGE_KEY);assert(stored.has(previewKey));
 const others={'codex-desk-original-frontiers-v1':'installed source frontier','codex-desk-original-reading-checkpoints-v1':'installed place',unrelated:'same origin independent key'};
 for(const [k,v] of Object.entries(others))stored.set(k,v);
 const meta=stored.get(previewKey);load('preview-api.js');assert.equal(stored.get(previewKey),meta);assert.equal(reloads,0);
 window.DeskBrowserPreview.reset();assert.equal(reloads,1);assert.equal(stored.has(previewKey),false);
 // Ordinary pagehide may race Reset; reset marker removes only preview-owned writes next load.
 stored.set(previewKey,meta);stored.set(window.DeskBrowserPreview.originalReadingKey,'late old preview place');
 load('preview-api.js');assert.equal(stored.has(previewKey),false);assert.equal(stored.has(window.DeskBrowserPreview.originalReadingKey),false);
 for(const [k,v] of Object.entries(others))assert.equal(stored.get(k),v);
 assert.equal(external,0);console.log(JSON.stringify({passed:true,explicit_source_items:5,reset_own_keys_only:true}));
})().catch(e=>{console.error(e.stack);process.exitCode=1;});
'''
            r=subprocess.run([NODE,'-e',script,str(output)],capture_output=True,text=True,timeout=10)
            self.assertEqual(r.returncode,0,r.stderr)
            self.assertTrue(json.loads(r.stdout)['passed'])

if __name__=='__main__':unittest.main()
