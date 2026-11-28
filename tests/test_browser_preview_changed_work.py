"""Sample changed-work frontiers use the maintained pure native classifier."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('changed_preview_build',ROOT/'examples/build_browser_preview.py')
preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
HARNESS=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),stored=new Map();let writes=0,external=0;
global.window=global;global.localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>{writes++;stored.set(key,value);},removeItem:key=>{writes++;stored.delete(key);}};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>{}};
global.document={getElementById:()=>null,addEventListener:()=>{}};global.open=()=>{};
global.fetch=()=>{external++;throw Error('Unexpected external request');};
for(const name of ['sample-data.js',...(process.argv[2]==='rich'?['session-reading-fixture.js']:[]),'preview-api.js','new-activity.js','changed-work.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
const request=async(path,data)=>{const response=await fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});assert.equal(response.status,200);return response.json();};
const material=async session=>(await request('/api/state')).native_material.summaries.find(row=>row.owner.session===session);
const rows=view=>view.groups.flatMap(group=>group.rows);
'''


@unittest.skipUnless(NODE,'Node is needed for sample metadata projection')
class BrowserPreviewChangedWorkTests(unittest.TestCase):
    def run_js(self,body,rich=False):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='changed-preview-') as tmp:
            output=preview.build(Path(tmp)/'demo',session_reading_fixture=rich)
            script=HARNESS+'\n(async()=>{\n'+body+"\nprocess.stdout.write(JSON.stringify({passed:true}));\n})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});"
            run=subprocess.run([NODE,'-e',script,str(output),'rich' if rich else 'normal'],capture_output=True,text=True,timeout=15)
            self.assertEqual(run.returncode,0,run.stderr);self.assertTrue(json.loads(run.stdout)['passed'])

    def test_four_distribution_variants_copy_actual_changed_and_reading_assets(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='changed-preview-bytes-') as tmp:
            for embedded in (False,True):
                for rich in (False,True):
                    output=preview.build(Path(tmp)/f'{embedded}-{rich}',embedded=embedded,session_reading_fixture=rich)
                    for name in ('changed-work.js','changed-work-view.js','new-activity-view.js','history_reader.js','activity.js'):
                        self.assertEqual((output/name).read_bytes(),(ROOT/'codex_desk/static'/name).read_bytes(),name)
                    self.assertEqual((output/'preview-api.js').read_bytes(),(ROOT/'examples/browser-preview/preview-api.js').read_bytes())
                    self.assertEqual((output/'app.js').read_text(),(ROOT/'codex_desk/static/app.js').read_text().replace("'codex-desk-session'","'codex-desk-browser-preview-session-v1'"))
                    self.assertEqual((output/'reading_checkpoint.js').read_text(),(ROOT/'codex_desk/static/reading_checkpoint.js').read_text().replace("'codex-desk-reading-checkpoints-v1'",repr(preview.READING_KEY)))
                    self.assertEqual((output/'new-activity.js').read_text(),(ROOT/'codex_desk/static/new-activity.js').read_text().replace("'codex-desk-activity-review-v1'",repr(preview.REVIEW_KEY)))
                    html=(output/'index.html').read_text()
                    self.assertIn('./changed-work-view.js',html)
                    self.assertIn('id="show-changed-work"',html)
                    self.assertEqual('DeskPreviewReadingFixture' in (output/'sample-data.js').read_text(),rich)
                    self.assertEqual('data-preview-embedded="true"' in html,embedded)

    def test_default_zero_event_metadata_keeps_unknown_baseline_and_no_read_or_storage_side_effect(self):
        self.run_js(r'''
const ids=[];for(const thread of DeskPreviewThreads)ids.push((await request('/api/import',{thread:thread.id})).id);
const before=JSON.stringify(DeskBrowserPreview.snapshot()),storedBefore=writes,calls=DeskBrowserPreview.requests.length;
const state=await request('/api/state'),native=state.native_material;
assert.equal(native.summaries.length,3);assert.equal(native.native_home,(await request('/api/native/home')).home_namespace);
for(const summary of native.summaries){assert.equal(summary.status,'available');assert.equal(summary.material_seq,0);assert.equal(summary.received_seq,0);assert.deepEqual(Object.keys(summary).sort(),['material_seq','owner','received_seq','status']);}
const projected=DeskChangedWork.project({native_home:native.native_home,summaries:native.summaries,reviews:[],tasks:state.sessions.map(task=>({session:task.id,group_id:'sample',active:false,archived:false,thread_id:task.thread_id}))},{mode:'all'});
assert(rows(projected).every(row=>row.activity_status==='baseline_missing' && row.changed===null));
assert.equal(writes,storedBefore);assert.equal(JSON.stringify(DeskBrowserPreview.snapshot()),before);assert.equal(external,0);
assert.deepEqual(DeskBrowserPreview.requests.slice(calls).map(row=>row.path),['/api/state','/api/native/home']);
''')

    def test_fixture_material_frontier_ignores_child_status_and_plan_and_never_marks(self):
        self.run_js(r'''
const first=DeskPreviewThreads[0],id=(await request('/api/import',{thread:first.id})).id,home=(await request('/api/native/home')).home_namespace;
const owner={native_home:home,session:id,thread_id:first.id},reviews=DeskNewActivity.create(localStorage);
reviews.seed(owner,DeskNewActivity.capture(owner,(await request('/api/events?session='+id)).map(row=>row)));
const seeded=reviews.get(owner).reviewed_seq;assert.equal(seeded,3);
const controls=DeskBrowserPreview.fixture,frontier=controls.updateCommand(),received=controls.appendIgnored();
const before=JSON.stringify(DeskBrowserPreview.snapshot()),storedBefore=writes,calls=DeskBrowserPreview.requests.length;
const summary=await material(id);assert.equal(summary.material_seq,frontier);assert.equal(summary.received_seq,received);
assert.equal(reviews.get(owner).reviewed_seq,seeded);assert.equal(writes,storedBefore);assert.equal(JSON.stringify(DeskBrowserPreview.snapshot()),before);
assert.deepEqual(DeskBrowserPreview.requests.slice(calls).map(row=>row.path),['/api/state']);assert.equal(external,0);
assert(!JSON.stringify(summary).includes('NEW SAMPLE COMMAND MATERIAL'));
const later=controls.appendOutput(),newer=await material(id);assert.equal(newer.material_seq,later);assert.equal(reviews.get(owner).reviewed_seq,seeded);
''',rich=True)

    def test_streaming_plan_exact_turn_eligibility_and_bounded_unavailable_summary(self):
        self.run_js(r'''
const first=DeskPreviewThreads[0],id=(await request('/api/import',{thread:first.id})).id;
const events=DeskPreviewReadingFixture.events[id],emit=event=>{const row={seq:(events.at(-1)?.seq||0)+1,event};events.push(row);return row.seq;};
const notify=(method,params)=>emit({method,params:{threadId:first.id,...params}});
notify('turn/started',{turn:{id:'plan-turn-A'}});
notify('item/started',{turnId:'plan-turn-A',item:{id:'empty-plan',type:'plan',text:''}});
const good=notify('item/plan/delta',{turnId:'plan-turn-A',itemId:'empty-plan',delta:'A readable current plan'});
notify('turn/started',{turn:{id:'plan-turn-B'}});
notify('item/plan/delta',{turnId:'plan-turn-A',itemId:'empty-plan',delta:'Dropped old streaming owner'});
notify('item/plan/delta',{turnId:'plan-turn-B',itemId:'missing-plan',delta:'Dropped unknown plan'});
assert.equal((await material(id)).material_seq,good);
notify('item/started',{turnId:'plan-turn-B',item:{id:'new-plan',type:'plan',text:''}});
const next=notify('item/plan/delta',{turnId:'plan-turn-B',itemId:'new-plan',delta:'Current B plan'});
notify('turn/completed',{turn:{id:'plan-turn-B',status:'completed',items:[null,'primitive', {id:'new-plan',type:'plan'}]}});
notify('item/plan/delta',{turnId:'plan-turn-B',itemId:'new-plan',delta:'Dropped terminal plan'});
assert.equal((await material(id)).material_seq,next);
while(events.length<=5000)notify('thread/tokenUsage/updated',{tokenUsage:{total:1}});
const unavailable=await material(id);assert.equal(unavailable.status,'unavailable');assert(!Object.hasOwn(unavailable,'material_seq'));assert.equal(external,0);
''',rich=True)


if __name__=='__main__':unittest.main()
