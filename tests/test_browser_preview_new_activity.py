"""Maintained sample review keys, frozen responses and fresh exact source fixtures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('activity_preview_build', ROOT / 'examples/build_browser_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')


class BrowserPreviewNewActivity(unittest.TestCase):
    def temporary(self):
        base = Path(os.environ.get('DESK_TEST_TEMP', ROOT / 'temp'))
        base.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=base, prefix='sample-new-activity-')

    def test_namespaces_only_review_key_and_preserves_default_source_data(self):
        with self.temporary() as tmp:
            normal = preview.build(Path(tmp) / 'normal')
            rich = preview.build(Path(tmp) / 'rich', embedded=True, session_reading_fixture=True)
            source = (ROOT / 'codex_desk/static/new-activity.js').read_text()
            self.assertIn("'codex-desk-activity-review-v1'", source)
            self.assertEqual((normal / 'new-activity.js').read_text(), source.replace("'codex-desk-activity-review-v1'", repr(preview.REVIEW_KEY)))
            for name in ('new-activity.js', 'new-activity-view.js', 'app.js'):
                self.assertEqual((normal / name).read_bytes(), (rich / name).read_bytes())
            self.assertNotIn('DeskPreviewReadingFixture', (normal / 'sample-data.js').read_text())
            self.assertIn('session-reading-fixture.js', (rich / 'index.html').read_text())

    @unittest.skipUnless(NODE, 'Node is needed for sample fixture controller units')
    def test_response_is_frozen_fresh_source_exact_and_reset_is_scoped(self):
        with self.temporary() as tmp:
            output = preview.build(Path(tmp) / 'demo', session_reading_fixture=True)
            script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stored=new Map([['codex-desk-activity-review-v1','installed-review-marker']]);let reloaded=0;
global.window=global;global.localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>{reloaded++;}};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.open=()=>{};global.fetch=()=>{throw Error('Unexpected external request');};
for(const name of ['sample-data.js','session-reading-fixture.js','preview-api.js','new-activity.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
(async()=>{
 const request=async(path,data)=>{const response=await fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});return {status:response.status,body:await response.json()};};
 const controls=DeskBrowserPreview.fixture,original=DeskPreviewThreads[0],id=(await request('/api/import',{thread:original.id})).body.id;
 const home=(await request('/api/native/home')).body.home_namespace,owner={native_home:home,session:id,thread_id:original.id};
 const store=DeskNewActivity.create(localStorage);store.seed(owner,DeskNewActivity.capture(owner,(await request('/api/events?session='+id)).body));
 assert.equal(store.get(owner).reviewed_seq,3);const updated=controls.updateCommand(),tail=controls.appendIgnored();assert.equal(updated,4);assert.equal(tail,7);
 const rows=(await request('/api/events?session='+id+'&after=3')).body;
 const capture=DeskNewActivity.capture(owner,rows,row=>row.event.method!=='item/plan/delta');
 assert.equal(capture.frontier,4);assert.equal(capture.received_seq,7);assert.equal(store.pending(owner,capture).first.item_id,'sample-checkout-evidence');
 controls.holdResponse('/api/events');let finished=false;const held=request('/api/events?session='+id+'&after=3').then(r=>{finished=true;return r;});
 for(let i=0;i<8 && !controls.responsesEntered.length;i++)await Promise.resolve();
 assert.deepEqual(controls.responsesEntered,['/api/events']);assert.equal(finished,false);
 const later=controls.appendOutput();store.mark(owner,capture);assert.equal(store.get(owner).reviewed_seq,4);
 controls.releaseResponse('/api/events');const frozen=(await held).body;assert.equal(frozen.at(-1).seq,7);assert.equal(later,8);
 const fresh=(await request('/api/native/evidence-source?home='+home+'&thread='+original.id)).body.thread;
 assert(fresh.turns[0].items.find(item=>item.id==='sample-checkout-evidence').aggregatedOutput.includes('NEW SAMPLE COMMAND MATERIAL'));
 assert.equal(fresh.turns[1].items.at(-1).id,'sample-checkout-new-output');
 const activityRows=controls.activityRows();global.DeskPreviewReadingOverrides={activityRows,movedCommand:true};
 vm.runInThisContext(fs.readFileSync(process.argv[1]+'/sample-data.js','utf8'));vm.runInThisContext(fs.readFileSync(process.argv[1]+'/session-reading-fixture.js','utf8'));
 assert.equal(DeskPreviewThreads[0].turns[0].items.some(item=>item.id==='sample-checkout-evidence'),false);
 assert.equal(DeskPreviewThreads[0].turns[1].items.at(-1).id,'sample-checkout-evidence');
 assert.equal(DeskPreviewReadingFixture.events[id].at(-1).seq,8);
 const key=DeskNewActivity.STORAGE_KEY;assert.equal(key,DeskBrowserPreview.reviewKey);assert(!localStorage.getItem(key).includes('NEW SAMPLE COMMAND MATERIAL'));
 DeskBrowserPreview.reset();assert.equal(stored.has(key),false);assert.equal(stored.get('codex-desk-activity-review-v1'),'installed-review-marker');assert.equal(reloaded,1);
 // The current page can still save its metadata after Reset; the next document consumes the marker.
 stored.set(key,'late-pagehide-review');vm.runInThisContext(fs.readFileSync(process.argv[1]+'/preview-api.js','utf8'));
 assert.equal(stored.has(key),false);assert.equal(stored.has('codex-desk-browser-preview-reset-v1'),false);
 assert.equal(stored.get('codex-desk-activity-review-v1'),'installed-review-marker');
 process.stdout.write(JSON.stringify({passed:true,frontier:capture.frontier,received:capture.received_seq,frozen_tail:frozen.at(-1).seq,later,reset_scoped:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
            run = subprocess.run([NODE, '-e', script, str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(json.loads(run.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
