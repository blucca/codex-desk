"""Organization controls reuse exact local queue revision/order APIs."""
import subprocess,unittest
from test_prepared_queue_editor import SETUP,NODE,ROOT
SETUP+=r'''
const editApi=api;let organizationGate=null;
api=async(path,data)=>{
 if(['/api/followups/remove','/api/followups/reorder','/api/followups/clear'].includes(path)){
  calls.push({path,data:clone(data)});const queue=world[data.session].followups;
  const ids=queue.entries.map(e=>e.id),same=(a,b)=>JSON.stringify(a)===JSON.stringify(b);
  const failure=()=>{const e=Error('Queue changed elsewhere');e.current=clone(queue);throw e;};
  if(path.endsWith('/remove')){const e=queue.entries.find(e=>e.id===data.id);if(!e||e.revision!==data.revision||e.state!=='queued')failure();queue.entries=queue.entries.filter(e=>e.id!==data.id);}
  else{if(!same(ids,data.order)||queue.reservation||queue.entries.some(e=>e.state!=='queued'))failure();
   if(path.endsWith('/clear'))queue.entries=[];
   else queue.entries=data.ids.map(id=>queue.entries.find(e=>e.id===id));
  }
  queue.entries.forEach((e,i)=>e.order=i+1);const result=clone(queue);return organizationGate?organizationGate(result):result;
 }
 return editApi(path,data);
};
const organizationPosts=()=>calls.filter(c=>c.data&&c.path!=='/api/followups/edit');
const clearButton=()=>all(n('followups')).find(e=>e.dataset.control==='queue-clear');
'''
@unittest.skipUnless(NODE,'Node required')
class PreparedQueueOrganizationTests(unittest.TestCase):
 def check(self,body):
  script=SETUP+'\n(async()=>{await DeskPreparation.show();\n'+body+r'''
assert.equal(opened.length,0);assert.equal(saved.length,0);assert.equal(activeDraft.text,'ACTIVE UNSENT PLAN — do not alter');
assert(calls.every(c=>!c.data||['/api/followups/edit','/api/followups/remove','/api/followups/reorder','/api/followups/clear'].includes(c.path)));
console.log(JSON.stringify({passed:true,posts:organizationPosts().length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  r=subprocess.run([NODE,'-e',script,str(ROOT/'codex_desk/static/preparation.js')],capture_output=True,text=True,timeout=20)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_move_exact_order_and_boundary_buttons(self):
  self.check(r'''
await review('b');assert(queueControl('b-one','queue-up').disabled);assert(queueControl('b-two','queue-down').disabled);
await queueControl('b-one','queue-down').click();assert.deepEqual(world.b.followups.entries.map(e=>e.id),['b-two','b-one']);
assert.deepEqual(organizationPosts()[0].data,{session:'b',ids:['b-two','b-one'],order:['b-one','b-two']});
''')
 def test_remove_saved_revision_keeps_unsaved_edit_until_cancel(self):
  self.check(r'''
await start();input('My retained removed edit','plan');await queueControl('b-one','queue-remove').click();
assert.deepEqual(world.b.followups.entries.map(e=>e.id),['b-two']);assert.equal(queueControl('b-one','queue-text').value,'My retained removed edit');assert(queueControl('b-one','queue-save').disabled);
assert.deepEqual(organizationPosts()[0].data,{session:'b',id:'b-one',revision:1});await queueControl('b-one','queue-cancel').click();assert(!queueControl('b-one','queue-text'));
''')
 def test_clear_captured_order_keeps_local_edit(self):
  self.check(r'''
await start();input('Retained after Clear','plan');await clearButton().click();assert.equal(world.b.followups.entries.length,0);
assert.deepEqual(organizationPosts()[0].data,{session:'b',order:['b-one','b-two']});assert.equal(queueControl('b-one','queue-text').value,'Retained after Clear');assert(queueControl('b-one','queue-save').disabled);
''')
 def test_stale_order_response_keeps_edits_and_new_queue(self):
  self.check(r'''
await start();input('Local pending edit','plan');world.b.followups.entries.push({id:'new',text:'New instruction',mode:'native',state:'queued',order:3,revision:1});
await queueControl('b-one','queue-down').click();assert.deepEqual(world.b.followups.entries.map(e=>e.id),['b-one','b-two','new']);
assert.equal(queueControl('b-one','queue-text').value,'Local pending edit');assert(n('followups').textContent.includes('Queue changed elsewhere'));
''')
 def test_reserved_or_captured_queue_is_not_reordered_or_cleared(self):
  self.check(r'''
await review('b');world.b.followups.entries[0].state='reserved';world.b.followups.reservation={state:'unknown',text:'Captured original stays'};
await n('refresh').click();assert(!queueControl('b-one','queue-edit'));assert(!queueControl('b-one','queue-remove'));assert(clearButton().disabled);assert(queueControl('b-two','queue-up').disabled);
await clearButton().click();await queueControl('b-two','queue-up').click();assert.equal(organizationPosts().length,0);
''')
 def test_late_reorder_response_cannot_steal_other_prepared_editor(self):
  self.check(r'''
await start();input('Retained b queue edit','plan');const wait=deferred();organizationGate=()=>wait.promise;
const moving=queueControl('b-one','queue-down').click();await settle();await review('a');fill('Other retained Prepared edit','plan');n('text').focus();
wait.resolve(clone(world.b.followups));await moving;assert.equal(n('text').value,'Other retained Prepared edit');assert(document.activeElement===n('text'));
await review('b');assert.equal(queueControl('b-one','queue-text').value,'Retained b queue edit');
''')

 def test_delayed_order_conflict_never_replaces_newer_refreshed_queue(self):
  self.check(r'''
await start();input('Local pending edit','plan');const wait=deferred(),prior=api;
world.b.followups.entries.push({id:'new',text:'Earlier external instruction',mode:'native',state:'queued',order:3,revision:1});
const failure=Error('Earlier queue conflict');failure.current=clone(world.b.followups);
api=async(path,data)=>path==='/api/followups/reorder'?wait.promise.then(()=>{throw failure;}):prior(path,data);
const moving=queueControl('b-one','queue-down').click();await settle();
world.b.followups.entries[2].text='Latest external instruction';world.b.followups.entries[2].revision=2;
await n('refresh').click();wait.resolve();await moving;
assert(n('followups').textContent.includes('Latest external instruction'));
assert(!n('followups').textContent.includes('Earlier external instruction'));
assert.equal(queueControl('b-one','queue-text').value,'Local pending edit');
''')
