"""Deliberate-only sample task skim/evidence fixture, without preparation mutation."""
import importlib.util,json,os
from pathlib import Path
import shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parents[1]
SPEC=importlib.util.spec_from_file_location('task_review_preview_build',ROOT/'examples/build_browser_preview.py');preview=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(preview)
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
HARNESS=r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict'),stored=new Map();let external=0;
global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>{}};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('Unexpected external transport');}};
const load=name=>vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
load('sample-data.js');load('preview-api.js');
const request=async(path,data)=>{const r=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});assert.equal(r.status,200);return await r.json();};
const count=()=>window.DeskPreviewThreads.reduce((n,h)=>n+h.turns.reduce((m,t)=>m+t.items.length,0),0);
'''

class BrowserPreviewTaskReviewTests(unittest.TestCase):
    def test_four_modes_keep_initial_counts_and_all_maintained_assets(self):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='task-review-build-') as tmp:
            for rich in (False,True):
                for embedded in (False,True):
                    output=preview.build(Path(tmp)/f'{rich}-{embedded}',embedded=embedded,session_reading_fixture=rich)
                    html=(output/'index.html').read_text();self.assertEqual(html.count('id="preview-tasks-prepare"'),1)
                    self.assertIn('Prepare sample task review',html);self.assertIn('Task overview',html);self.assertIn('Read this task’s evidence',html)
                    histories=preview.reading_fixture()[0] if rich else preview.sample_threads()
                    self.assertEqual(len(histories),4);self.assertEqual(sum(len(t['items']) for h in histories for t in h['turns']),15 if rich else 13)
                    for asset in (ROOT/'codex_desk/static').iterdir():
                        if asset.is_file() and asset.name not in ('index.html','app.js','reading_checkpoint.js','original_frontier.js','new-activity.js'):
                            self.assertEqual((output/asset.name).read_bytes(),asset.read_bytes())
                    helper=ROOT/'codex_desk/static/task-evidence.js'
                    if helper.exists():
                        self.assertIn('task-evidence.js',json.loads((output/'preview-source.json').read_text())['assets'])
                        self.assertIn('src="./task-evidence.js"',html)
                        self.assertEqual((output/'task-evidence.js').read_bytes(),helper.read_bytes())

    def run_js(self,body):
        base=Path(os.environ.get('DESK_TEST_TEMP',ROOT/'temp'));base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base,prefix='task-review-api-') as tmp:
            output=preview.build(Path(tmp)/'demo')
            script=HARNESS+'\n(async()=>{'+body+'\n})().catch(e=>{console.error(e.stack);process.exitCode=1;});'
            r=subprocess.run([NODE,'-e',script,str(output)],capture_output=True,text=True,timeout=15)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)

    @unittest.skipUnless(NODE,'Node is needed for sample transport units')
    def test_deliberate_prepare_changes_only_existing_child_original(self):
        self.run_js(r'''
const B=(await request('/api/import',{thread:'sample-docs-thread'})).id;
await request('/api/draft',{session:B,text:'Exact existing B Plan',mode:'plan',revision:0});
for(const mode of ['native','plan'])await request('/api/followups',{session:B,text:'Retained '+mode,mode});
const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored),original=structuredClone(window.DeskPreviewThreads),requests=window.DeskBrowserPreview.requests.length;
const f=window.DeskBrowserPreview.tasksFixture;assert(!f.prepared);assert.equal(count(),13);
assert.equal(f.prepare(),true);assert.equal(f.prepare(),false);assert.equal(window.DeskBrowserPreview.requests.length,requests);
const child=window.DeskPreviewThreads.find(t=>t.id===f.threadId);assert.equal(child.turns.length,61);assert.deepEqual(child.turns[0],original.find(t=>t.id===f.threadId).turns[0]);
for(const t of original.filter(t=>t.id!==f.threadId))assert.deepEqual(window.DeskPreviewThreads.find(fresh=>fresh.id===t.id),t);
assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual(Object.fromEntries(stored),raw);assert.equal(external,0);
const chosen=child.turns.find(t=>t.id===f.turnId);assert.equal(chosen.items.length,45);assert.equal(chosen.items[25].id,f.itemId);assert.equal(chosen.status,'failed');
assert.equal(child.turns[45].items.length,0);assert.equal(child.turns[45].status,'interrupted');assert(child.turns[45].error.message);
assert(!child.turns[46].items.some(i=>i.type==='userMessage'));
''')

    @unittest.skipUnless(NODE,'Node is needed for sample transport units')
    def test_same_response_id_stays_in_exact_turn_and_scoped_spans_are_literal(self):
        self.run_js(r'''
load('history_find.js');load('history_tasks.js');load('history_reader.js');const f=window.DeskBrowserPreview.tasksFixture;f.prepare();const child=window.DeskPreviewThreads.find(t=>t.id===f.threadId);
for(const n of [40,41]){const turn='sample-review-task-'+n;const resolved=DeskHistoryTasks.response(child,{thread_id:f.threadId,turn_id:turn});assert.equal(resolved.item_id,f.responseId);assert.equal(resolved.phase,'final_answer');assert.equal(child.turns[n].items.find(i=>i.id===resolved.item_id).text,'Own supplied task '+n+' final response.');}
const unreported=DeskHistoryTasks.response(child,{thread_id:f.threadId,turn_id:'sample-review-task-42'});assert.equal(unreported.phase,null);assert.equal(unreported.selection,'last_assistant_message');
const hits=[];for(const turn of child.turns)for(const item of turn.items){if(item.type!=='commandExecution')continue;const text=DeskHistoryReader.textForItem(item);for(const span of DeskHistoryFind.spans(text,f.query))hits.push({turn:turn.id,item:item.id,span,text});}
assert.equal(hits.length,3);const scoped=hits.filter(h=>h.turn===f.turnId);assert.equal(scoped.length,1);assert.equal(scoped[0].item,f.itemId);assert(scoped[0].span.start>20000);assert.equal(scoped[0].text.slice(scoped[0].span.start,scoped[0].span.end),f.quote);
assert(scoped[0].text.includes('Café 项目 😀'));assert(scoped[0].text.includes('Task source line 1899'));
''')

    @unittest.skipUnless(NODE,'Node is needed for sample transport units')
    def test_ordinary_reload_returns_default_source_and_keeps_preparation_without_reads(self):
        self.run_js(r'''
const B=(await request('/api/import',{thread:'sample-docs-thread'})).id;await request('/api/draft',{session:B,text:'Keep this unsent B Plan',mode:'plan',revision:0});
for(const mode of ['native','plan'])await request('/api/followups',{session:B,text:'Retained '+mode,mode});
const before=window.DeskBrowserPreview.snapshot();window.DeskBrowserPreview.tasksFixture.prepare();assert.equal(window.DeskPreviewThreads.find(t=>t.id==='sample-child-thread').turns.length,61);
load('sample-data.js');load('preview-api.js');assert.equal(window.DeskPreviewThreads.find(t=>t.id==='sample-child-thread').turns.length,1);assert.equal(count(),13);assert(!window.DeskBrowserPreview.tasksFixture.prepared);
assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.equal(window.DeskBrowserPreview.requests.length,0);assert.equal(external,0);
''')

if __name__=='__main__':unittest.main()
