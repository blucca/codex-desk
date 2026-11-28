"""Exact reported-child preview sources and read-only transport parity."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('linked_preview_build', ROOT / 'examples/build_browser_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')


class BrowserPreviewLinkedOriginalTests(unittest.TestCase):
    def test_exact_reported_child_is_independent_original_in_both_distributions(self):
        normal = preview.sample_threads()
        rich, fixture = preview.reading_fixture()
        for threads in (normal, rich):
            self.assertEqual(len(threads), 4)
            parent = threads[0]
            child = next(t for t in threads if t['id'] == preview.CHILD)
            self.assertNotEqual(parent['id'], child['id'])
            self.assertFalse(child['cwdExists'])
            item = next(i for i in parent['turns'][0]['items'] if i['id'] == 'sample-checkout-collaboration')
            self.assertEqual(item['receiverThreadIds'], [child['id']])
            self.assertEqual(set(item['agentsStates']), {child['id']})
            self.assertEqual(child['turns'][0]['id'], preview.CHILD_TURN)
            original = next(item for item in child['turns'][0]['items'] if item['type'] == 'agentMessage')
            self.assertEqual(original['id'], preview.CHILD_ITEM)
            self.assertEqual(original['phase'], 'final_answer')
            self.assertEqual(original['text'].count(preview.CHILD_QUOTE), 2)
            self.assertIn('Child source line 1199', original['text'])
            self.assertGreater(len(original['text']), 100000)
        self.assertEqual(normal[-1], rich[-1])
        self.assertNotIn('desk-' + preview.CHILD, fixture['events'])
        self.assertNotIn('desk-' + preview.CHILD, fixture['pending'])

    def test_known_id_and_instruction_entrance_uses_existing_fourth_original(self):
        base = Path(os.environ.get('DESK_TEST_TEMP', ROOT / 'temp')).resolve()
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix='source-entry-sample-') as temporary:
            for embedded in (False, True):
                output = preview.build(Path(temporary) / str(embedded), embedded=embedded)
                html = (output / 'index.html').read_text()
                self.assertIn('id="history-id-form"', html)
                self.assertIn('id="history-id-read"', html)
                self.assertIn('sample-child-thread</code> by ID', html)
                self.assertIn('reported retry result</code>', html)
                child = preview.sample_threads()[-1]
                self.assertEqual(child['id'], preview.CHILD)
                prompts = [i for i in child['turns'][0]['items'] if i['type'] == 'userMessage']
                self.assertEqual(len(prompts), 1)
                self.assertIn('reported retry result', prompts[0]['content'][0]['text'])
                self.assertEqual(sum(len(t['items']) for s in preview.sample_threads() for t in s['turns']), 13)
                for asset in (ROOT / 'codex_desk/static').iterdir():
                    if asset.is_file() and asset.name not in ('app.js', 'index.html'):
                        expected = asset.read_bytes()
                        if asset.name == 'reading_checkpoint.js':
                            expected = expected.replace(b"'codex-desk-reading-checkpoints-v1'", repr(preview.READING_KEY).encode()).replace(b"'codex-desk-original-reading-checkpoints-v1'", repr(preview.ORIGINAL_READING_KEY).encode())
                        elif asset.name == 'original_frontier.js':
                            expected = expected.replace(b"'codex-desk-original-frontiers-v1'", repr(preview.ORIGINAL_FRONTIER_KEY).encode())
                        elif asset.name == 'new-activity.js':
                            expected = expected.replace(b"'codex-desk-activity-review-v1'", repr(preview.REVIEW_KEY).encode())
                        self.assertEqual((output / asset.name).read_bytes(), expected)

    @unittest.skipUnless(NODE, 'Node is needed for sample transport units')
    def test_linked_read_exact_namespace_ids_and_truthful_history_counts_no_child_writes(self):
        base = Path(os.environ.get('DESK_TEST_TEMP', ROOT / 'temp')).resolve()
        base.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base, prefix='linked-sample-') as temporary:
            for rich in (False, True):
                output = preview.build(Path(temporary) / str(rich), session_reading_fixture=rich)
                script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stored=new Map();let external=0;
global.localStorage={getItem:k=>stored.get(k)||null,setItem:(k,v)=>stored.set(k,v),removeItem:k=>stored.delete(k)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1'};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('No external transport');}};
for(const name of ['sample-data.js',...(process.argv[2]==='True'?['session-reading-fixture.js']:[]),'preview-api.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
(async()=>{
 const request=async(path,data)=>{const r=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});return {status:r.status,body:await r.json()};};
 const threads=window.DeskPreviewThreads,parent=threads[0],child=threads.at(-1);
 const imported=await request('/api/import',{thread:parent.id});const id=imported.body.id;
 await request('/api/draft',{session:id,text:'Existing B Plan',mode:'plan',revision:0});
 for(const mode of ['native','plan'])await request('/api/followups',{session:id,text:'Retained '+mode,mode});
 const before=window.DeskBrowserPreview.snapshot(),raw=Object.fromEntries(stored);
 if(window.DeskBrowserPreview.fixture){
  const linked=window.DeskBrowserPreview.fixture.updateLinkedOriginal();
  const rows=(await request('/api/events?session='+id+'&after=3')).body;
  assert.equal(rows.length,1);assert.equal(rows[0].seq,linked);
  assert.equal(rows[0].event.params.item.id,'sample-checkout-collaboration');
  assert.deepEqual(rows[0].event.params.item.receiverThreadIds,[child.id]);
 }
 const home=(await request('/api/native/home')).body.home_namespace;
 const original=await request('/api/native/evidence-source?home='+home+'&thread='+child.id);
 assert.equal(original.status,200);assert.deepEqual(original.body,{thread:child,home_namespace:home,source:'native history read'});
 const direct=await request('/api/native/thread?id='+child.id);assert.deepEqual(direct.body,child);
 const response=await request('/api/native/task-response?thread='+child.id+'&turn='+child.turns[0].id);
 assert.deepEqual(response.body.thread,child);assert.equal(response.body.response.item_id,child.turns[0].items.find(i=>i.type==='agentMessage').id);assert.equal(response.body.response.selection,'final_answer');
 for(const bad of ['/api/native/evidence-source?home='+home+'&thread='+child.id+'&thread=other','/api/native/evidence-source?home='+home+'&thread='+child.id+'&extra=1','/api/native/evidence-source?home='+('0'.repeat(64))+'&thread='+child.id,'/api/native/evidence-source?home='+home+'&thread=missing'])assert.equal((await request(bad)).status,400,bad);
 assert.equal((await request('/api/native/evidence-source?home='+home+'&thread='+child.id,{x:1})).status,400);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual(Object.fromEntries(stored),raw);
 assert.equal(before.sessions.length,1);assert.equal(before.sessions[0].thread_id,parent.id);
 assert.equal((await request('/api/native')).body.data.length,3);
 assert.deepEqual((await request('/api/native?archived=true')).body.data.map(t=>t.id),[child.id]);
 const index=await request('/api/history/index',{});assert.equal(index.body.job.seen,4);assert.equal(index.body.job.indexed,4);assert.equal(index.body.coverage.indexed_threads,4);
 assert.equal(index.body.coverage.indexed_items,threads.reduce((n,t)=>n+t.turns.reduce((m,turn)=>m+turn.items.length,0),0));
 const find=await request('/api/recall?q='+encodeURIComponent('Child decisive evidence'));
 assert.equal(find.body.total,1);assert.equal(find.body.results[0].thread_id,child.id);assert.equal(find.body.results[0].kind,'native-activity');
 assert.equal(find.body.coverage.activity_items,parent.turns.reduce((n,t)=>n+t.items.length,0));
 assert.equal((await request('/api/history/index',{op:'older'})).status,400);
 for(const path of ['/api/turn','/api/followups/send','/api/answer','/api/approval','/api/steer','/api/stop'])assert.equal((await request(path,{session:id})).status,400,path);
 const after=window.DeskBrowserPreview.snapshot();assert.deepEqual(after.sessions,before.sessions);assert.deepEqual(after.drafts,before.drafts);assert.deepEqual(after.followups,before.followups);
 assert.equal(external,0);process.stdout.write(JSON.stringify({passed:true,histories:4,items:index.body.coverage.indexed_items,native_admissions:0}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
                run = subprocess.run([NODE, '-e', script, str(output), str(rich)], capture_output=True, text=True, timeout=20)
                self.assertEqual(run.returncode, 0, run.stderr)
                self.assertTrue(json.loads(run.stdout)['passed'])
