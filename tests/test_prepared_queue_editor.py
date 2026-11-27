"""Queued instruction editing without native Open or draft writes."""
import subprocess,unittest
from test_preparation_controller import HARNESS,NODE,ROOT
SETUP=HARNESS[:HARNESS.index('(async()=>{')]
SETUP=SETUP.replace('DeskPreparation.configure({api,','DeskPreparation.configure({api:(path,data)=>api(path,data),')
SETUP=SETUP.replace("selector==='button'&&child.tagName==='BUTTON'","child.tagName===selector.toUpperCase()")
SETUP+=r'''
const baseApi=api;let queueGate=null;
api=async(path,data)=>{
 if(path.startsWith('/api/followups?session='))return clone(world[path.split('=')[1]].followups);
 if(path==='/api/followups/edit'){
  calls.push({path,data:clone(data)});const entries=world[data.session].followups.entries;
  const old=entries.find(e=>e.id===data.id);if(old.revision!==data.revision){const e=Error('Instruction changed elsewhere');e.current=clone(world[data.session].followups);throw e;}
  Object.assign(old,{text:data.text,mode:data.mode,revision:old.revision+1});
  const snapshot=clone(world[data.session].followups);return queueGate?queueGate(snapshot):snapshot;
 }
 return baseApi(path,data);
};
const queueControl=(id,key)=>all(n('followups')).find(e=>e.dataset.followup===id&&e.dataset.control===key);
const start=async()=>{await review('b');await queueControl('b-one','queue-edit').click();};
function input(text,mode){const t=queueControl('b-one','queue-text');t.value=text;t.oninput();if(mode){const m=queueControl('b-one','queue-mode');m.value=mode;m.onchange();}}
const queuePosts=()=>calls.filter(c=>c.path==='/api/followups/edit');
'''
@unittest.skipUnless(NODE,'Node required')
class PreparedQueueEditorTests(unittest.TestCase):
 def check(self,body):
  script=SETUP+'\n(async()=>{await DeskPreparation.show();\n'+body+r'''
assert.equal(opened.length,0);assert.equal(saved.length,0);assert.equal(activeDraft.text,'ACTIVE UNSENT PLAN — do not alter');
assert(calls.every(c=>!c.data||c.path==='/api/followups/edit'));
console.log(JSON.stringify({passed:true,queue_posts:queuePosts().length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  r=subprocess.run([NODE,'-e',script,str(ROOT/'codex_desk/static/preparation.js')],capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_exact_text_mode_save_only_queue_and_cancel(self):
  self.check(r'''
await start();input('  Exact corrected 保留\n  ','plan');await queueControl('b-one','queue-save').click();
assert.equal(world.b.followups.entries[0].text,'  Exact corrected 保留\n  ');assert.equal(world.b.followups.entries[0].mode,'plan');
assert.equal(queuePosts()[0].data.session,'b');assert.equal(queuePosts()[0].data.revision,1);
input('Cancel unsaved','native');await queueControl('b-one','queue-cancel').click();assert(!queueControl('b-one','queue-text'));
assert.equal(world.b.followups.entries[0].text,'  Exact corrected 保留\n  ');
''')
 def test_refresh_scope_switch_close_return_keeps_queue_edit_view(self):
  self.check(r'''
await start();input('My retained queue edit','plan');let t=queueControl('b-one','queue-text');t.focus();t.setSelectionRange(3,9,'backward');t.scrollTop=44;
await n('refresh').click();t=queueControl('b-one','queue-text');assert.equal(t.value,'My retained queue edit');assert.equal(t.selectionStart,3);assert.equal(t.selectionDirection,'backward');assert.equal(t.scrollTop,44);
await review('a');await review('b');assert.equal(queueControl('b-one','queue-text').value,'My retained queue edit');
await n('close').click();await DeskPreparation.show();assert.equal(queueControl('b-one','queue-mode').value,'plan');assert.equal(queuePosts().length,0);
''')
 def test_stale_revision_keeps_local_text_requires_explicit_revision_choice(self):
  self.check(r'''
await start();input('Mine correct','plan');world.b.followups.entries[0].text='Other current';world.b.followups.entries[0].revision=2;
await queueControl('b-one','queue-save').click();assert.equal(queueControl('b-one','queue-text').value,'Mine correct');assert(queueControl('b-one','queue-save').disabled);
await queueControl('b-one','queue-keep').click();assert.equal(queuePosts().length,1);assert(!queueControl('b-one','queue-save').disabled);
await queueControl('b-one','queue-save').click();assert.equal(world.b.followups.entries[0].text,'Mine correct');assert.equal(queuePosts()[1].data.revision,2);
''')
 def test_typing_while_save_waits_keeps_newer_unsent_edit(self):
  self.check(r'''
await start();input('First submitted','plan');const wait=deferred();queueGate=()=>wait.promise;
const saving=queueControl('b-one','queue-save').click();await settle();input('Newer unsent edit','native');
wait.resolve(clone(world.b.followups));await saving;assert.equal(queueControl('b-one','queue-text').value,'Newer unsent edit');
assert.equal(world.b.followups.entries[0].text,'First submitted');assert.equal(queueControl('b-one','queue-mode').value,'native');
queueGate=null;await queueControl('b-one','queue-save').click();assert.equal(world.b.followups.entries[0].text,'Newer unsent edit');
''')
 def test_cancel_and_other_editor_own_late_save(self):
  self.check(r'''
await start();input('Old queued save','plan');const wait=deferred();queueGate=()=>wait.promise;
const saving=queueControl('b-one','queue-save').click();await settle();await queueControl('b-one','queue-cancel').click();await review('a');fill('Other Prepared draft edit','plan');
wait.resolve(clone(world.b.followups));await saving;assert.equal(n('text').value,'Other Prepared draft edit');
await review('b');assert(!queueControl('b-one','queue-text'));assert.equal(world.b.followups.entries[0].text,'Old queued save');
''')

 def test_removed_row_keeps_unsaved_edit_without_mutation(self):
  self.check(r'''
await start();input('Removed but locally retained','plan');world.b.followups.entries=[];await n('refresh').click();
assert.equal(queueControl('b-one','queue-text').value,'Removed but locally retained');assert(queueControl('b-one','queue-text').disabled);assert(queueControl('b-one','queue-save').disabled);
await queueControl('b-one','queue-cancel').click();assert(!queueControl('b-one','queue-text'));assert.equal(queuePosts().length,0);
''')

 def test_delayed_conflict_never_replaces_newer_refreshed_instruction(self):
  self.check(r'''
await start();input('My local pending edit','plan');const wait=deferred(),prior=api;
world.b.followups.entries[0].text='Other revision two';world.b.followups.entries[0].revision=2;
const failure=Error('Earlier conflict');failure.current=clone(world.b.followups);
api=async(path,data)=>path==='/api/followups/edit'?wait.promise.then(()=>{throw failure;}):prior(path,data);
const saving=queueControl('b-one','queue-save').click();await settle();
world.b.followups.entries[0].text='Newest revision three';world.b.followups.entries[0].revision=3;
await n('refresh').click();wait.resolve();await saving;
assert.equal(queueControl('b-one','queue-text').value,'My local pending edit');
await queueControl('b-one','queue-load').click();assert.equal(queueControl('b-one','queue-text').value,'Newest revision three');
''')

 def test_real_partial_entry_conflict_reads_exact_queue_before_choice(self):
  self.check(r'''
await start();input('My pending edit','plan');const prior=api;
world.b.followups.entries[0].text='Current saved entry';world.b.followups.entries[0].revision=2;
api=async(path,data)=>{if(path==='/api/followups/edit'){const e=Error('Actual partial conflict');e.current={entry:clone(world.b.followups.entries[0]),reservation:null};throw e;}return prior(path,data);};
await queueControl('b-one','queue-save').click();assert(queueControl('b-one','queue-save').disabled);
assert.equal(queueControl('b-one','queue-text').value,'My pending edit');
await queueControl('b-one','queue-load').click();assert.equal(queueControl('b-one','queue-text').value,'Current saved entry');
''')
