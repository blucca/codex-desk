"""An admitted/captured instruction returns to its own exact evidence and back."""
import pathlib, shutil, subprocess, unittest
ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'codex_desk/static/history_reader.js').read_text()
READ = SOURCE[SOURCE.index('  async function readEmbeddedReference('):SOURCE.index('  function scrollMatch(')]
CLOSE = SOURCE[SOURCE.index('  function close('):SOURCE.index('  function available(')]
SETUP = r'''
const assert=require('assert/strict');
let live=true,version=7,source={id:'sent-B',turns:[]},requested={thread_id:'sent-B',turn_id:'sent-turn',item_id:'sent-item'};
let returned=0,options={valid:()=>live,onReturn:()=>returned++},page=3,findSubmitted=true,findQuery='needle',findGroups=[{index:121,spans:[{start:9,end:15}]}],findTotal=1,findCursor=0;
const query={value:'needle'},elements={'find-query':query,'':{open:true,close(){this.open=false;}}};
const el=id=>elements[id];let reads=[],shows=[],renders=[],restores=[],findUpdates=0,reply,hold=null;
const reference={native_home:'a'.repeat(64),thread_id:'original-A',turn_id:'turn-A',item_id:'item-A',quote:'needle'};
const current=t=>t===version && live;
const captureView=()=>({items:new Map(),selection:{text:'needle'},scroll:21,outer:12});
const textFor=()=>'';
const root={DeskEvidencePreparation:{resolve:(r,h,t,f)=>{assert.strictEqual(r,reference);assert.equal(h,r.native_home);assert.equal(t.id,'original-A');assert.strictEqual(f,textFor);return {available:true,start_utf16:40};}}};
const api=async path=>{reads.push(path);if(hold)await hold;return reply || {home_namespace:reference.native_home,thread:{id:'original-A',turns:[]}};};
const show=async (target,callbacks)=>{shows.push({target,callbacks});options=callbacks;source=callbacks.preloadedThread;requested=target;++version;return true;};
const findControls=()=>findUpdates++,render=(scroll,view)=>renders.push({scroll,view});
const invalidate=()=>{const cb=options?.onReturn;options=null;source=null;requested=null;++version;cb?.();};
const settle=()=>new Promise(resolve=>setTimeout(resolve,0));
'''
@unittest.skipUnless(shutil.which('node'), 'Node required')
class EvidenceReaderLifecycleTests(unittest.TestCase):
    def js(self, body):
        result=subprocess.run(['node','-e',SETUP+READ+CLOSE+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'],capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_one_get_exact_source_then_back_restores_same_instruction_view_and_find(self):
        self.js(r'''
const parent=options;assert(await readEmbeddedReference(reference,7));assert.equal(reads.length,1);
assert.equal(reads[0],'/api/native/evidence-source?home='+reference.native_home+'&thread=original-A');
const child=shows[0];assert.deepEqual(child.target,{thread_id:'original-A',turn_id:'turn-A',item_id:'item-A',match_text:'needle',match_start:40});
assert.strictEqual(child.callbacks.savedReference,reference);assert.strictEqual(child.callbacks.returnOwner,parent);assert.equal(returned,0);
page=0;findQuery='changed';findSubmitted=false;findGroups=[];findTotal=0;findCursor=-1;query.value='changed';
child.callbacks.onReturn();await settle();assert.equal(shows.length,2);assert.strictEqual(options,parent);
assert.deepEqual(shows[1].target,{thread_id:'sent-B',turn_id:'sent-turn',item_id:'sent-item'});assert.equal(shows[1].callbacks.preloadedThread.id,'sent-B');
assert.equal(reads.length,1);assert.equal(page,3);assert.equal(query.value,'needle');assert.equal(findQuery,'needle');assert(findSubmitted);
assert.equal(findTotal,1);assert.equal(findCursor,0);assert.equal(findGroups[0].index,121);assert.equal(renders.length,1);assert.equal(renders[0].scroll,false);assert.equal(renders[0].view.scroll,21);assert.equal(returned,0);
''')

    def test_late_get_does_not_replace_newer_reader(self):
        self.js(r'''
let release;hold=new Promise(r=>release=r);const pending=readEmbeddedReference(reference,7);version++;release();assert.equal(await pending,false);assert.equal(shows.length,0);
''')

    def test_foreign_home_leaves_saved_instruction_intact(self):
        self.js(r'''
reply={home_namespace:'b'.repeat(64),thread:{id:'original-A',turns:[]}};const parent=source;
await assert.rejects(readEmbeddedReference(reference,7),/different native home/);assert.strictEqual(source,parent);assert.equal(shows.length,0);
''')

    def test_changed_quote_keeps_captured_excerpt_without_equal_phrase_fallback(self):
        self.js(r'''
root.DeskEvidencePreparation.resolve=()=>({available:false,status:'quote_changed'});assert(await readEmbeddedReference(reference,7));
assert.equal(shows[0].target.match_text,undefined);assert.equal(shows[0].target.match_start,undefined);
assert.strictEqual(shows[0].callbacks.savedReference,reference);assert.equal(shows[0].callbacks.resolution.status,'quote_changed');
''')

    def test_source_failure_keeps_original_and_return_callback(self):
        self.js(r'''
reply={home_namespace:reference.native_home,thread:{id:'wrong',turns:[]}};const parent=options;
await assert.rejects(readEmbeddedReference(reference,7),/could not be read/);assert.strictEqual(options,parent);assert.equal(returned,0);assert.equal(shows.length,0);
''')

    def test_owner_switch_close_matches_ancestor_without_reopening_old_source(self):
        self.js(r'''
const parent=options;await readEmbeddedReference(reference,7);assert(close(parent));await settle();assert.equal(shows.length,1);assert.equal(returned,1);assert.equal(options,null);assert(!el('').open);
''')

    def test_unrelated_close_cannot_close_referenced_reader(self):
        self.js(r'''
await readEmbeddedReference(reference,7);assert.equal(close({}),false);assert.equal(returned,0);assert.equal(shows.length,1);assert(el('').open);
''')

    def test_owner_change_while_reading_cannot_restore_previous_instruction(self):
        self.js(r'''
await readEmbeddedReference(reference,7);live=false;shows[0].callbacks.onReturn();await settle();assert.equal(shows.length,1);assert.equal(returned,1);
''')
