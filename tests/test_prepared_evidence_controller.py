"""Current existing Prepared row evidence: ordinary draft persistence and exact source return."""
import json
import subprocess
import unittest
from test_preparation_controller import HARNESS, NODE, ROOT

SETUP = HARNESS[:HARNESS.index('(async()=>{')]
SETUP = SETUP.replace("vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));", "vm.runInThisContext(fs.readFileSync(require('path').join(require('path').dirname(process.argv[1]),'evidence-preparation.js'),'utf8'));\nvm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));")
SETUP = SETUP.replace('DeskPreparation.configure({api,', '''DeskPreparation.configure({api:(path,data)=>api(path,data),
  navigationIdentity:()=>navigation,
  onBrowseEvidence:capture=>{browseCaptures.push(clone(capture));},
  onEvidenceChange:()=>DeskEvidencePreparation.sync(),
  readEvidenceReference:(reference,callbacks)=>DeskEvidencePreparation.readReference(reference,callbacks),''')
SETUP = SETUP.replace('const calls=[],saved=[],opened=[],activeDraft=', "let navigation='task-a:7';const browseCaptures=[],readerCalls=[];\nconst calls=[],saved=[],opened=[],activeDraft=")
SETUP += r'''
const baseApi=api,E=DeskEvidencePreparation;
const original={id:'original-A',name:'Exact source A',cwd:'/removed/original',turns:[{id:'turn-A',status:'failed',items:[
  {id:'item-A',type:'agentMessage',phase:'commentary',text:'First café 🌱 quote.\nSecond café 🌱 quote.'}]}]};
const projection=E.textForItem(original.turns[0].items[0]),start=projection.lastIndexOf('café');
const reference=E.capture(original,{native_home:'a'.repeat(64),thread_id:'original-A',turn_id:'turn-A',item_id:'item-A',
  start_utf16:start,end_utf16:projection.length,expected_quote:projection.slice(start)}),block=E.format(reference);
let nativeRead=null,readHold=null,homeHold=null;
api=async(path,data)=>{
 if(path==='/api/native/home'){calls.push({path});if(homeHold)await homeHold.promise;return {home_namespace:reference.native_home};}
 if(path.startsWith('/api/native/evidence-source?')){calls.push({path});if(readHold)await readHold.promise;return {home_namespace:reference.native_home,thread:clone(nativeRead || original)};}
 return baseApi(path,data);
};
E.configure({render:false,api:(path,data)=>api(path,data),destination:()=>DeskPreparation.evidenceDestination(),
 save:(payload,capture)=>DeskPreparation.saveReviewedEvidence(payload,capture),
 showOriginal:async(target,callbacks)=>{readerCalls.push({target,callbacks});return true;}});
const evidenceControl=id=>all(n('editor')).find(e=>e.id===id);
const evidenceButtons=node=>all(node).filter(e=>e.tagName==='BUTTON'&&e.dataset.control==='read-evidence');
const posts=()=>calls.filter(c=>c.data);
const seed=async()=>{await DeskPreparation.show();await review('b');fill('  Existing B unsent preparation 保留\n  ','plan');};
const reviewEvidence=()=>E.reviewLoaded({thread:clone(original),thread_id:original.id,turn_id:'turn-A',item_id:'item-A',
  start_utf16:start,end_utf16:projection.length});
'''


@unittest.skipUnless(NODE, 'Node required')
class PreparedEvidenceControllerTests(unittest.TestCase):
    def check(self, body):
        script = SETUP + '\n(async()=>{await seed();\n' + body + r'''
assert.equal(opened.length,0);assert.equal(activeDraft.text,'ACTIVE UNSENT PLAN — do not alter');
assert(calls.every(c=>!c.data || c.path==='/api/draft'),JSON.stringify(calls));
process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script, str(ROOT / 'codex_desk/static/preparation.js')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_explicit_browse_captures_only_existing_current_row_and_keeps_other_preparation(self):
        self.check(r'''
const before=clone(world),capture=DeskPreparation.evidenceDestination();
assert.equal(capture.session,'b');assert.equal(capture.kind,'prepared');assert.equal(capture.generation,'prepared:1:task-a:7');
assert.equal(capture.writer,'preparation-private-writer');assert.equal(capture.revision,0);assert.equal(capture.sequence,2);
assert.equal(capture.mode,'plan');assert.equal(capture.text,n('text').value);assert.equal(capture.cwd,'/gone/project');assert(!capture.busy);
await evidenceControl('preparation-browse-evidence').click();assert.deepEqual(browseCaptures,[capture]);assert.deepEqual(world,before);assert.equal(posts().length,0);
await n('close').click();assert.equal(DeskPreparation.evidenceDestination(),null);await DeskPreparation.show();
assert.notEqual(DeskPreparation.evidenceDestination().generation,capture.generation);
''')

    def test_review_and_cancel_leave_unsaved_draft_and_two_queues_unchanged(self):
        self.check(r'''
const before=clone(world),text=n('text').value;assert(await reviewEvidence());const state=E.state();
assert.equal(state.destination.text,text);assert.equal(state.destination.writer,'preparation-private-writer');assert.equal(state.reference.quote,reference.quote);
assert.equal(state.reference.quote_start,Array.from(projection.slice(0,start)).length);assert.equal(state.reference.phase,'commentary');
assert.deepEqual(world,before);assert.equal(posts().length,0);E.cancel();assert.equal(n('text').value,text);assert.deepEqual(world,before);
''')

    def test_append_reserves_synchronously_before_the_ordinary_draft_write(self):
        self.check(r'''
assert(await reviewEvidence());const capture=E.state().destination,beforeQueues=clone(world.b.followups),beforeA=clone(world.a);
let observed=null;control.post=(payload,next)=>{observed={payload:clone(payload),text:n('text').value,destination:DeskPreparation.evidenceDestination()};return next;};
const saving=E.append();assert(observed);assert.equal(observed.text,capture.text+'\n\n'+block);assert.equal(observed.destination.sequence,capture.sequence+1);
assert(observed.destination.busy);assert(await saving);assert.equal(posts().length,1);
const payload=posts()[0].data;assert.equal(payload.session,'b');assert.equal(payload.writer,capture.writer);assert.equal(payload.sequence,capture.sequence+1);
assert.equal(payload.revision,capture.revision);assert.equal(payload.mode,'plan');assert.equal(world.b.draft.text,n('text').value);assert.equal(world.b.draft.revision,1);
assert.deepEqual(world.b.followups,beforeQueues);assert.deepEqual(world.a,beforeA);assert.equal(saved[0].draft.text,world.b.draft.text);assert.equal(E.state(),null);
''')

    def test_every_stale_capture_field_rejects_without_reservation_or_write(self):
        self.check(r'''
const capture=DeskPreparation.evidenceDestination(),payload={session:capture.session,text:capture.text+'\n\n'+block,mode:capture.mode,revision:capture.revision,writer:capture.writer,sequence:capture.sequence+1};
for(const key of ['session','generation','revision','sequence','writer','text','mode']){
 const stale={...capture,[key]:typeof capture[key]==='number'?capture[key]+1:'changed-'+capture[key]};
 await assert.rejects(DeskPreparation.saveReviewedEvidence(payload,stale),/destination changed/);
 assert.equal(n('text').value,capture.text);assert.equal(DeskPreparation.evidenceDestination().sequence,capture.sequence);
}
assert.equal(posts().length,0);
''')

    def test_later_typing_and_mode_during_held_reply_are_kept_with_later_sequence(self):
        self.check(r'''
assert(await reviewEvidence());const wait=deferred();control.post=(payload,next)=>wait.promise;
const saving=E.append(),capture=DeskPreparation.evidenceDestination(),appended=n('text').value;await settle();
fill(appended+'\nNewer exact unsent work','native');assert.equal(DeskPreparation.evidenceDestination().sequence,capture.sequence+2);
wait.resolve(clone(world.b.draft));assert(await saving);assert.equal(n('text').value,appended+'\nNewer exact unsent work');assert.equal(n('mode').value,'native');
assert.equal(world.b.draft.text,appended);assert.match(n('draft-status').textContent,/Newer edits/);
control.post=null;await n('save').click();assert.equal(world.b.draft.text,n('text').value);assert.equal(posts()[1].data.sequence,capture.sequence+2);assert.equal(posts()[1].data.revision,1);
''')

    def test_immediate_typing_after_append_cannot_replace_the_captured_receipt(self):
        self.check(r'''
assert(await reviewEvidence());const saving=E.append(),appended=n('text').value;fill(appended+'\nImmediate later note','native');
assert(await saving);assert.equal(world.b.draft.text,appended);assert.equal(n('text').value,appended+'\nImmediate later note');assert.equal(n('mode').value,'native');
assert.equal(saved[0].draft.text,appended);assert.equal(posts().length,1);
''')

    def test_conflict_retains_reserved_quote_and_later_edit_until_explicit_keep(self):
        self.check(r'''
assert(await reviewEvidence());world.b.draft={text:'Other writer saved draft',mode:'native',revision:1};
assert.equal(await E.append(),false);assert.equal(E.state().status,'conflict');assert(n('text').value.includes(block));assert.equal(n('save').disabled,true);
fill(n('text').value+'\nLater mine','plan');const text=n('text').value;assert.equal(world.b.draft.text,'Other writer saved draft');E.cancel();
await n('keep').click();assert.equal(world.b.draft.text,text);assert.equal(world.b.draft.mode,'plan');assert.equal(posts()[1].data.revision,1);assert.equal(posts()[1].data.writer,'preparation-private-writer');
''')

    def test_explicit_load_saved_removes_old_reference_buttons_without_extra_write(self):
        self.check(r'''
fill(n('text').value+'\n\n'+block,'plan');assert.equal(evidenceButtons(evidenceControl('preparation-evidence-list')).length,1);
world.b.draft={text:'Other current without reference',mode:'native',revision:1};await n('refresh').click();assert.equal(n('save').disabled,true);
await n('load').click();assert.equal(n('text').value,'Other current without reference');assert.equal(evidenceButtons(evidenceControl('preparation-evidence-list')).length,0);assert.equal(posts().length,0);
''')

    def test_save_failure_keeps_unsaved_reference_for_existing_save_retry(self):
        self.check(r'''
assert(await reviewEvidence());control.failPost=true;assert.equal(await E.append(),false);assert.equal(E.state().status,'failed');assert(n('text').value.includes(block));
assert.equal(world.b.draft.revision,0);assert(!n('save').disabled);assert.equal(evidenceButtons(evidenceControl('preparation-evidence-list')).length,1);
E.cancel();control.failPost=false;await n('save').click();assert.equal(world.b.draft.text,n('text').value);assert.equal(world.b.draft.mode,'plan');
''')

    def test_late_save_for_b_cannot_replace_another_prepared_row_or_task(self):
        self.check(r'''
assert(await reviewEvidence());const wait=deferred();control.post=(payload,next)=>wait.promise;const saving=E.append();await settle();
await review('a');fill('A newer unrelated unsent Plan','plan');const text=n('text').value;wait.resolve(clone(world.b.draft));assert(await saving);
assert.equal(n('text').value,text);assert.equal(DeskPreparation.evidenceDestination().session,'a');assert.equal(saved[0].id,'b');
await review('b');assert.equal(n('text').value,world.b.draft.text);assert(n('text').value.includes(block));
''')

    def test_reference_read_and_exact_return_preserve_current_prepared_editor_view(self):
        self.check(r'''
fill(n('text').value+'\n\n'+block,'plan');n('text').setSelectionRange(3,12,'backward');n('text').scrollTop=67;n('').scrollTop=145;
const read=evidenceButtons(evidenceControl('preparation-evidence-list'))[0],before=clone(world);await read.click();
assert.equal(readerCalls.length,1);const {target,callbacks}=readerCalls[0];assert.equal(target.thread_id,'original-A');assert.equal(target.turn_id,'turn-A');assert.equal(target.item_id,'item-A');
assert.equal(target.start_utf16,start);assert.equal(callbacks.savedReference.quote,reference.quote);assert.equal(callbacks.backLabel,'Return to Prepared work');assert(callbacks.valid());
n('text').setSelectionRange(0,0);n('text').scrollTop=0;n('').scrollTop=0;callbacks.onReturn();
assert.equal(n('text').selectionStart,3);assert.equal(n('text').selectionEnd,12);assert.equal(n('text').selectionDirection,'backward');assert.equal(n('text').scrollTop,67);assert.equal(n('').scrollTop,145);
assert.equal(document.activeElement,read);assert.deepEqual(world,before);assert.equal(posts().length,0);assert(calls.some(c=>c.path.includes('home='+reference.native_home+'&thread=original-A')));
''')

    def test_reference_read_return_does_not_restore_over_newer_text(self):
        self.check(r'''
fill(n('text').value+'\n\n'+block,'plan');const read=evidenceButtons(evidenceControl('preparation-evidence-list'))[0];await read.click();
fill('Newer Prepared unsent text','native');n('text').setSelectionRange(4,9,'backward');n('text').scrollTop=98;readerCalls[0].callbacks.onReturn();
assert.equal(n('text').value,'Newer Prepared unsent text');assert.equal(n('text').selectionStart,4);assert.equal(n('text').selectionEnd,9);assert.equal(n('text').selectionDirection,'backward');assert.equal(n('text').scrollTop,98);assert.equal(posts().length,0);
''')

    def test_held_reference_reply_after_row_switch_close_or_task_navigation_is_suppressed(self):
        self.check(r'''
for(const change of [async()=>{await review('a');},async()=>{await n('close').click();},async()=>{navigation='task-other:8';}]){
 if(!n('').open)await DeskPreparation.show();await review('b');fill('B quote\n\n'+block,'plan');readHold=deferred();
 const reading=evidenceButtons(evidenceControl('preparation-evidence-list'))[0].click();await settle();await change();readHold.resolve();await reading;assert.equal(readerCalls.length,0);
 readHold=null;
}
assert.equal(posts().length,0);
''')

    def test_source_unavailable_keeps_saved_quote_and_exact_item_without_duplicate_fallback(self):
        self.check(r'''
fill(n('text').value+'\n\n'+block,'plan');nativeRead=clone(original);nativeRead.turns[0].items[0].id='different-item-same-words';
await evidenceButtons(evidenceControl('preparation-evidence-list'))[0].click();const {target,callbacks}=readerCalls[0];
assert.equal(target.item_id,'item-A');assert.equal(target.status,'source_unavailable');assert.equal(callbacks.savedReference.quote,reference.quote);assert(!callbacks.resolution.available);assert(n('text').value.includes(block));assert.equal(posts().length,0);
''')

    def test_saved_queued_and_reserved_instructions_offer_source_read_without_mutation(self):
        self.check(r'''
world.b.followups.entries[0].text='Instruction next\n\n'+block;world.d.followups.reservation.text='Captured instruction\n\n'+block;
await n('refresh').click();const before=clone(world);const queued=evidenceButtons(followup('b-one'));assert.equal(queued.length,1);await queued[0].click();
assert.equal(readerCalls[0].target.item_id,'item-A');readerCalls[0].callbacks.onReturn();await review('d');
const reservation=all(n('followups')).find(e=>e.className==='preparation-reservation'),reserved=evidenceButtons(reservation);assert.equal(reserved.length,1);await reserved[0].click();
assert.equal(readerCalls[1].callbacks.savedReference.quote,reference.quote);readerCalls[1].callbacks.onReturn();assert.deepEqual(world,before);assert.equal(posts().length,0);
''')


if __name__ == '__main__':
    unittest.main()
