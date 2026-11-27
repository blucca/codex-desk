"""Sample session-reading fixtures preserve normal distribution and source identity."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('reading_preview_build', ROOT / 'examples/build_browser_preview.py')
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')


class BrowserPreviewSessionReadingTests(unittest.TestCase):
    def temporary(self):
        base = Path(os.environ.get('DESK_TEST_TEMP', ROOT / 'temp'))
        base.mkdir(parents=True, exist_ok=True)
        return tempfile.TemporaryDirectory(dir=base, prefix='sample-reading-')

    def test_fixture_opt_in_preserves_default_histories_and_assets(self):
        with self.temporary() as tmp:
            normal = preview.build(Path(tmp) / 'normal')
            rich = preview.build(Path(tmp) / 'rich', embedded=True, session_reading_fixture=True)
            self.assertNotIn('DeskPreviewReadingFixture', (normal / 'sample-data.js').read_text())
            self.assertNotIn('session-reading-fixture.js', (normal / 'index.html').read_text())
            self.assertIn('session-reading-fixture.js', (rich / 'index.html').read_text())
            self.assertIn('data-preview-embedded="true"', (rich / 'index.html').read_text())
            threads, fixture = preview.reading_fixture()
            self.assertEqual([thread['id'] for thread in threads], [thread['id'] for thread in preview.sample_threads()])
            prior = threads[0]['turns'][0]
            self.assertEqual(prior['id'], 'sample-checkout-turn')
            self.assertEqual(prior['items'][1], preview.sample_threads()[0]['turns'][0]['items'][1])
            self.assertEqual([item['type'] for item in prior['items'][-2:]], ['mcpToolCall', 'collabAgentToolCall'])
            self.assertGreater(len(prior['items'][2]['aggregatedOutput'].splitlines()), 900)
            self.assertEqual(fixture['pending']['desk-sample-docs-thread'][0]['id'], 801)
            self.assertEqual([row['seq'] for row in fixture['events']['desk-sample-checkout-thread']], [1, 2, 3])
            for name in ('app.js', 'activity.js', 'native-steps.js', 'turn-changes.js'):
                self.assertEqual((normal / name).read_bytes(), (rich / name).read_bytes())

    def test_metadata_namespaced_in_distribution_only(self):
        with self.temporary() as tmp:
            staged = Path(tmp) / 'repo'
            shutil.copytree(ROOT / 'codex_desk/static', staged / 'codex_desk/static')
            shutil.copyfile(ROOT / 'codex_desk/__init__.py', staged / 'codex_desk/__init__.py')
            shutil.copytree(ROOT / 'examples/browser-preview', staged / 'examples/browser-preview')
            checkpoint = staged / 'codex_desk/static/reading_checkpoint.js'
            original = "const STORAGE_KEY='codex-desk-reading-checkpoints-v1';\n"
            checkpoint.write_text(original)
            with patch.object(preview, 'ROOT', staged):
                output = preview.build(Path(tmp) / 'demo')
            self.assertEqual(checkpoint.read_text(), original)
            self.assertIn(repr(preview.READING_KEY), (output / 'reading_checkpoint.js').read_text())
            self.assertNotIn("'codex-desk-reading-checkpoints-v1'", (output / 'reading_checkpoint.js').read_text())

    @unittest.skipUnless(NODE, 'Node is needed for sample fixture controller units')
    def test_native_fixture_reads_holds_and_reset_never_admit_or_send(self):
        with self.temporary() as tmp:
            output = preview.build(Path(tmp) / 'demo', session_reading_fixture=True)
            script = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const stored=new Map([['codex-desk-reading-checkpoints-v1','installed-marker'],['codex-desk-session','installed-session']]);let external=0,reloaded=0;
global.localStorage={getItem:key=>stored.get(key)||null,setItem:(key,value)=>stored.set(key,value),removeItem:key=>stored.delete(key)};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1',reload:()=>{reloaded++;}};
global.document={getElementById:()=>null,addEventListener:()=>{}};
global.window={open:()=>{},fetch:()=>{external++;throw Error('Unexpected external request');},DeskPreviewReadingOverrides:{freshMcp:true,namespaceHold:true}};
for(const name of ['sample-data.js','session-reading-fixture.js','preview-api.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
(async()=>{
 const request=async(path,data)=>{const response=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});return {status:response.status,body:await response.json()};};
 const controls=window.DeskBrowserPreview.fixture,original=window.DeskPreviewThreads[0];
 let settled=false;const held=request('/api/native/home').then(r=>{settled=true;return r;});
 await Promise.resolve();assert.equal(settled,false);assert.deepEqual(controls.entered,['/api/native/home']);
 controls.release('/api/native/home');const home=(await held).body.home_namespace;assert.match(home,/^[a-f0-9]{64}$/);
 const ids=[];for(const thread of window.DeskPreviewThreads)ids.push((await request('/api/import',{thread:thread.id})).body.id);
 for(const id of ids){await request('/api/followups?session='+id);await request('/api/draft',{session:id,text:'Unsent '+id,mode:'plan',revision:0});}
 for(const [text,mode] of [['First remains queued','native'],['Second remains Plan','plan']])assert.equal((await request('/api/followups',{session:ids[0],text,mode})).status,200);
 const before=window.DeskBrowserPreview.snapshot(),state=(await request('/api/state')).body;
 assert.equal(state.pending[ids[1]][0].id,801);assert.equal(state.native_outcomes[ids[0]].turn_id,'sample-checkout-live-turn');
 const rows=(await request('/api/events?session='+ids[0]+'&after=1')).body;assert.deepEqual(rows.map(r=>r.seq),[2,3]);assert.equal(rows[0].event.method,'turn/plan/updated');
 const exact=(await request('/api/native/evidence-source?home='+home+'&thread='+original.id)).body.thread;
 assert.deepEqual(exact,original);assert(exact.turns[0].items.find(i=>i.id==='sample-checkout-mcp').result.content[0].text.includes('FRESH SAMPLE MCP RESULT'));
 const sequence=controls.appendOutput();assert.equal(sequence,4);const update=(await request('/api/events?session='+ids[0]+'&after=3')).body;
 assert.equal(update.length,1);assert.equal(update[0].event.params.item.id,'sample-checkout-new-output');
 for(const path of ['/api/turn','/api/followups/send','/api/answer','/api/approval','/api/steer','/api/stop'])assert.equal((await request(path,{session:ids[0]})).status,400,path);
 assert.deepEqual(window.DeskBrowserPreview.snapshot(),before);assert.deepEqual((await request('/api/state')).body.pending,state.pending);
 const key=window.DeskBrowserPreview.readingKey;stored.set(key,'sample-reading-marker');stored.set(window.DeskBrowserPreview.sessionKey,ids[0]);
 window.DeskBrowserPreview.reset();assert.equal(stored.has(key),false);assert.equal(stored.has(window.DeskBrowserPreview.storageKey),false);assert.equal(stored.has(window.DeskBrowserPreview.sessionKey),false);
 assert.equal(stored.get('codex-desk-reading-checkpoints-v1'),'installed-marker');assert.equal(stored.get('codex-desk-session'),'installed-session');assert.equal(reloaded,1);assert.equal(external,0);
 // Simulate the real app's pagehide write after reset, then the new document.
 stored.set(key,'pagehide-reading-marker');vm.runInThisContext(fs.readFileSync(process.argv[1]+'/preview-api.js','utf8'));
 assert.equal(stored.has(key),false);assert.equal(stored.has('codex-desk-browser-preview-reset-v1'),false);
 assert.equal(window.DeskBrowserPreview.snapshot().sessions.length,0);assert.equal(stored.get('codex-desk-reading-checkpoints-v1'),'installed-marker');
 process.stdout.write(JSON.stringify({passed:true,pending:state.pending,events:rows.length,sequence,external,reset_scoped:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
            run = subprocess.run([NODE, '-e', script, str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            self.assertTrue(json.loads(run.stdout)['passed'])

    @unittest.skipUnless(NODE, 'Node is needed for sample fixture controller units')
    def test_missing_anchor_fixture_keeps_equal_id_only_in_later_turn(self):
        with self.temporary() as tmp:
            output = preview.build(Path(tmp) / 'demo', session_reading_fixture=True)
            script = r'''
const fs=require('fs'),vm=require('vm');global.window={DeskPreviewReadingOverrides:{movedCommand:true}};
for(const name of ['sample-data.js','session-reading-fixture.js'])vm.runInThisContext(fs.readFileSync(process.argv[1]+'/'+name,'utf8'));
process.stdout.write(JSON.stringify(window.DeskPreviewThreads[0]));
'''
            run = subprocess.run([NODE, '-e', script, str(output)], capture_output=True, text=True, timeout=15)
            self.assertEqual(run.returncode, 0, run.stderr)
            thread = json.loads(run.stdout)
            self.assertFalse(any(item['id'] == 'sample-checkout-evidence' for item in thread['turns'][0]['items']))
            self.assertEqual(thread['turns'][1]['items'][-1]['id'], 'sample-checkout-evidence')
            self.assertEqual(thread['turns'][1]['id'], 'sample-checkout-live-turn')


if __name__ == '__main__':
    unittest.main()
