"""Ordinary saved/captured instruction -> native original -> retained live editor."""
import json,subprocess,unittest
from test_followup_editor_controller import HARNESS
from test_navigation_controllers import APP,NODE
SETUP=HARNESS.replace("selector==='button'?child.tagName==='BUTTON':child.classList.contains(selector.slice(1))", "selector.startsWith('.')?child.classList.contains(selector.slice(1)):child.tagName===selector.toUpperCase()")
SETUP+=r'''
Element.prototype.setSelectionRange=function(a,b,d){this.selectionStart=a;this.selectionEnd=b;this.selectionDirection=d;};
const fs=require('fs'),vm=require('vm');vm.runInThisContext(fs.readFileSync(EVIDENCE,'utf8'));
const E=DeskEvidencePreparation;
const original={id:'source-A',name:'Original source A',cwd:'/removed/A',turns:[{id:'source-turn',status:'completed',items:[{id:'source-item',type:'agentMessage',phase:'final_answer',text:'Decisive café🙂 original.'}]}]};
const projected=E.textForItem(original.turns[0].items[0]),reference=E.capture(original,{native_home:'a'.repeat(64),thread_id:original.id,turn_id:'source-turn',item_id:'source-item',start_utf16:6,end_utf16:projected.length});
const block=E.format(reference);world.a.entries[0].text='Saved instruction\n\n'+block;
let navigation='a:7',sourceGate=null,queueGate=null;const readCalls=[],closes=[];
const initialApi=api;api=async(path,data)=>{
 if(path.startsWith('/api/native/evidence-source?')){calls.push({path,data:null});if(sourceGate)await sourceGate;return {home_namespace:reference.native_home,thread:clone(original)};}
 if(data===undefined && queueGate)await queueGate;
 return initialApi(path,data);
};
const controller=E.createController({render:false,api:(...args)=>api(...args),destination:()=>null,save:()=>{throw Error('Source reads cannot save');},showOriginal:async(target,callbacks)=>{readCalls.push({target,callbacks});return true;}});
const sourceButton=parent=>parent.querySelectorAll('button').find(n=>n.textContent.startsWith('Read referenced original'));
'''
@unittest.skipUnless(NODE,'Node required')
class FollowupEvidenceControllerTests(unittest.TestCase):
 def check(self,body):
  script=SETUP.replace('EVIDENCE',json.dumps(str(APP.parent/'evidence-preparation.js')))+'\n'+(APP.parent/'followups.js').read_text()+r'''
(async()=>{
DeskFollowups.configure({api:(...args)=>api(...args),make,selected:()=>selected,refresh:async()=>{throw Error('No native refresh');},navigationIdentity:()=>navigation,readEvidenceReference:(...args)=>controller.readReference(...args),closeReader:callback=>closes.push(callback)});
DeskFollowups.select('a');await settle();DeskFollowups.status('a',false);
'''+body+r'''
assert.equal(posts().length,0);console.log('PASS ordinary instruction source binding');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  r=subprocess.run([NODE,'-e',script],text=True,capture_output=True,timeout=20);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_exact_source_reread_preserves_live_unsaved_edit_and_range(self):
  self.check(r'''
button(row('one'),'Edit').onclick();edit('one','Unsent different instruction','plan');const field=text('one');caret('one');
$('followup-list').scrollTop=127;const read=sourceButton(row('one'));assert(read);await read.onclick();
assert.equal(readCalls.length,1);assert.equal(readCalls[0].target.thread_id,'source-A');assert.equal(readCalls[0].target.item_id,'source-item');
assert.equal(readCalls[0].callbacks.backLabel,'Return to saved follow-up');assert.equal(readCalls[0].callbacks.savedReference.quote,reference.quote);
assert.equal(calls.filter(c=>c.path.startsWith('/api/native/evidence-source?')).length,1);
field.scrollTop=0;readCalls[0].callbacks.onReturn();sameReader('one',field);assert.equal(field.value,'Unsent different instruction');assert.equal($('followup-list').scrollTop,127);
''')
 def test_held_read_return_preserves_latest_local_editing_intent(self):
  self.check(r'''
button(row('one'),'Edit').onclick();edit('one','Earlier local edit','plan');const field=text('one');caret('one');
const gate=deferred();sourceGate=gate.promise;const pending=sourceButton(row('one')).onclick();await settle();
edit('one','Latest local unsent Plan','plan');field.setSelectionRange(9,18,'forward');field.scrollTop=111;
gate.resolve();await pending;field.scrollTop=0;field.setSelectionRange(0,0,'forward');readCalls[0].callbacks.onReturn();
assert.equal(field.value,'Latest local unsent Plan');assert.equal(field.scrollTop,111);assert.deepEqual([field.selectionStart,field.selectionEnd,field.selectionDirection],[9,18,'forward']);assert.strictEqual(document.activeElement,field);
''')
 def test_stale_revision_text_mode_or_state_no_source_read_or_editor_loss(self):
  self.check(r'''
button(row('one'),'Edit').onclick();edit('one','Keep local unsent Plan','plan');const field=text('one');caret('one');
world.a.entries[0].revision++;await sourceButton(row('one')).onclick();sameReader('one',field);assert.equal(readCalls.length,0);assert.equal($('followup-error').hidden,false);assert($('followup-error').textContent.includes('changed'));
''')
 def test_held_original_reply_after_other_owner_cannot_open_or_return(self):
  self.check(r'''
const gate=deferred();sourceGate=gate.promise;const pending=sourceButton(row('one')).onclick();await settle();
selected='b';navigation='b:8';DeskFollowups.select('b');await settle();button(row('b-one'),'Edit').onclick();edit('b-one','B retained unsent','plan');const field=text('b-one');caret('b-one');
gate.resolve();await pending;assert.equal(readCalls.length,0);sameReader('b-one',field);
''')
 def test_actual_reader_callback_closed_on_owner_switch(self):
  self.check(r'''
await sourceButton(row('one')).onclick();const read=readCalls[0];assert(read.callbacks.valid());selected='b';navigation='b:8';DeskFollowups.select('b');await settle();
assert.strictEqual(closes[0],read.callbacks);assert(!read.callbacks.valid());$('prompt').focus();read.callbacks.onReturn();assert.strictEqual(document.activeElement,$('prompt'));
''')
 def test_routine_refresh_keeps_existing_reference_button_and_live_editor(self):
  self.check(r'''
button(row('one'),'Edit').onclick();edit('one','Unsent composition ahead','plan');const field=text('one');caret('one');const read=sourceButton(row('one'));
world.a.entries[1].text='Other tab changed other entry';await DeskFollowups.refresh();assert.strictEqual(sourceButton(row('one')),read);sameReader('one',field);await read.onclick();assert.equal(readCalls.length,1);
''')
 def test_captured_reservation_uses_immutable_text_not_revised_queue_entry(self):
  self.check(r'''
world.a.reservation={token:'captured-token',entry_id:'one',revision:1,mode:'native',state:'unknown',text:'Captured original instruction\n\n'+block};
world.a.entries[0].text='Revised queued instruction without reference';world.a.entries[0].revision=2;await DeskFollowups.refresh();
await sourceButton($('followup-review')).onclick();assert.equal(readCalls.length,1);assert.equal(readCalls[0].callbacks.backLabel,'Return to captured instruction');assert.equal(readCalls[0].target.thread_id,'source-A');
''')
