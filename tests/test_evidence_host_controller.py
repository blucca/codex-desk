"""Independent shipped evidence host callbacks with actual draft persistence."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from test_navigation_controllers import DOM

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / 'codex_desk/static/app.js'
NODE = shutil.which('node')

SETUP = DOM[:DOM.index('let state=')] + r'''
const vm=require('vm'),fs=require('fs');
vm.runInThisContext(fs.readFileSync(MODULE,'utf8'),{filename:MODULE});
const E=DeskEvidencePreparation,clone=x=>JSON.parse(JSON.stringify(x));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<30;i++)await Promise.resolve();};
const crypto={randomUUID:()=> '00000000-0000-4000-8000-000000000001'};
let state={sessions:[{id:'a',name:'A prepared Plan',cwd:'/former/a',thread_id:'thread-A'},{id:'b',name:'B prepared Work',cwd:'/former/b',thread_id:'thread-B'}]},selected='a',generation=7,opening=false,modeSelected='a',nativeThreadId='thread-A';
const drafts=new Map(),submitting=new Set(),timerCallbacks=new Map();let timerId=0;
const setTimeout=callback=>{timerCallbacks.set(++timerId,callback);return timerId;};
const clearTimeout=id=>timerCallbacks.delete(id);
const window={scrollY:123,events:new Map(),moves:[],addEventListener:(name,callback)=>window.events.set(name,callback),scrollTo:options=>window.moves.push(options)};
const readerCalls=[],readerOptions={};
const DeskHistoryReader={textForItem:E.textForItem,configure:options=>Object.assign(readerOptions,options),show:async(target,callbacks)=>{readerCalls.push({target,callbacks});return true;}};
const calls=[],control={},errors=[];const error=e=>errors.push(e.message);
const db={a:{text:'Exact current Plan — 保留  ',mode:'plan',revision:3},b:{text:'Other current Work',mode:'native',revision:4}};
const native={id:'thread-A',name:'Original evidence',cwd:'/deleted/source',turns:[{id:'turn-A',status:'failed',items:[{id:'item-A',type:'agentMessage',phase:'commentary',text:'Native café 🌱 evidence. Still commentary.'}]}]};
const projection=E.textForItem(native.turns[0].items[0]);
const reference=E.capture(native,{native_home:'a'.repeat(64),thread_id:'thread-A',turn_id:'turn-A',item_id:'item-A',start_utf16:6,end_utf16:projection.length});
const block=E.format(reference);let sourceReturns=0,sourceLive=true;
async function api(path,data){
  calls.push({path,data:data===undefined?undefined:clone(data)});
  if(path==='/api/native/home'){if(control.homeHold)await control.homeHold.promise;return {home_namespace:reference.native_home};}
  if(path.startsWith('/api/native/evidence-source?')){if(control.readHold)await control.readHold.promise;return {home_namespace:reference.native_home,thread:clone(control.native || native)};}
  if(path.startsWith('/api/draft?'))return clone(db[decodeURIComponent(path.split('=')[1])]);
  assert.equal(path,'/api/draft','Evidence host must use draft or native original GET only');
  if(control.conflict){const e=Error('Saved by another writer');e.status=409;e.current=clone(db[data.session]);throw e;}
  assert.equal(data.revision,db[data.session].revision);assert.equal(data.writer,draftWriter);
  control.onSave?.(data);const next={text:data.text,mode:data.mode,revision:data.revision+1};db[data.session]=clone(next);
  if(control.saveHold)await control.saveHold.promise;return next;
}
function seed(id='a',text=db[id].text){
  selected=id;nativeThreadId=state.sessions.find(row=>row.id===id).thread_id;opening=false;$('task').hidden=false;$('prompt').value=text;$('turn-mode').value=db[id].mode;
  draftRevisions.set(id,db[id].revision);draftEdits.set(id,7);drafts.set(id,text);draftModes.set(id,db[id].mode);
  draftSaved.set(id,clone(db[id]));draftIdentities.set(id,{revision:db[id].revision,sequence:7});
  $('prompt').selectionStart=2;$('prompt').selectionEnd=9;$('prompt').scrollTop=77;
  $('prompt').setSelectionRange=function(start,end){this.selectionStart=start;this.selectionEnd=end;};
  syncDraftEvidence();
}
async function review(){return readerOptions.onEvidence({thread:clone(native),turn_id:'turn-A',item_id:'item-A',selection_utf16:{start:6,end:projection.length},valid:()=>sourceLive,onReturn:()=>{sourceReturns++;}});}
const posts=()=>calls.filter(c=>c.data!==undefined);
function unchangedNative(){assert(calls.every(c=>c.path==='/api/draft'||c.path.startsWith('/api/draft?')||c.path==='/api/native/home'||c.path.startsWith('/api/native/evidence-source?')));}
'''


@unittest.skipUnless(NODE, 'Node is required for evidence host integration')
class EvidenceHostControllerTests(unittest.TestCase):
    def run_js(self, body):
        source = APP.read_text()
        draft = source[source.index('const draftWriter='):source.index('// Browser retention')]
        host = source[source.index('let preparedEvidenceOwner='):source.index("$('read-original').onclick=")]
        reading = '\n'.join(source[source.index(begin):source.index(end)] for begin, end in [
            ('const sessionReadingViews=', 'let sessionReadingHomeValue='),
            ('function sessionReadingBinding()', 'function sessionReadingIdentity('),
            ('function sessionReadingInput()', "window.addEventListener('wheel',")])
        events = '\n'.join(line for line in source.splitlines()
                           if line.startswith("$('prompt').oninput=") or line.startswith("$('turn-mode').onchange="))
        script = SETUP.replace('MODULE', json.dumps(str(ROOT / 'codex_desk/static/evidence-preparation.js')))
        script += '\n' + reading + '\n' + draft + '\n' + host + '\n' + events + '\n(async()=>{seed();\n' + body + r'''
unchangedNative();process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_destination_captures_revision_generation_writer_sequence_and_current_editor(self):
        self.run_js(r'''
const capture=evidenceDestination();assert.deepStrictEqual(capture,{session:'a',generation:7,revision:3,sequence:7,writer:draftWriter,text:db.a.text,mode:'plan',name:'A prepared Plan',cwd:'/former/a',busy:false});
for(const block of [()=>{opening=true;},()=>{$('task').hidden=true;},()=>{draftRevisions.delete('a');},()=>{selected='missing';}]){block();assert.strictEqual(evidenceDestination(),null);seed();}
for(const holder of [submitting,draftSaves,draftTimers,draftConflicts]){holder instanceof Set?holder.add('a'):holder.set('a',true);assert(evidenceDestination().busy);holder.delete('a');}
assert.equal(calls.length,0);
''')

    def test_exact_reader_review_callback_keeps_capture_and_draft_before_append(self):
        self.run_js(r'''
const before=clone(db.a);assert(await review());const captured=E.state();
assert.equal(captured.reference.quote,projection.slice(6));assert.equal(captured.reference.thread_id,'thread-A');assert.equal(captured.reference.turn_id,'turn-A');assert.equal(captured.reference.item_id,'item-A');
assert.equal(captured.reference.phase,'commentary');assert.equal(captured.reference.turn_status,'failed');
assert.equal(captured.destination.revision,3);assert.equal(captured.destination.generation,7);assert.equal(captured.destination.writer,draftWriter);assert.equal(captured.destination.sequence,7);
assert.deepStrictEqual(db.a,before);assert.equal($('prompt').value,before.text);assert.equal(posts().length,0);
assert.deepStrictEqual(calls.map(c=>c.path),['/api/native/home']);E.cancel();assert.equal(sourceReturns,1);assert.equal(posts().length,0);
''')

    def test_append_reserves_editor_maps_sequence_before_actual_persist(self):
        self.run_js(r'''
assert(await review());const capture=E.state().destination;
const original=persistDraft,reservations=[];persistDraft=(id,options)=>{reservations.push({id,options,text:$('prompt').value,map:drafts.get(id),mode:draftModes.get(id),sequence:draftEdits.get(id)});return original(id,options);};
const pending=E.append();assert.equal(reservations.length,1);assert.equal(reservations[0].sequence,8);assert.equal(reservations[0].text,reservations[0].map);assert.equal(reservations[0].mode,'plan');assert.equal(reservations[0].options.identify,true);assert.equal(typeof reservations[0].options.onSaved,'function');
assert(await pending);assert.equal(posts().length,1);const payload=posts()[0].data;
assert.equal(payload.revision,capture.revision);assert.equal(payload.writer,capture.writer);assert.equal(payload.sequence,capture.sequence+1);assert.equal(payload.session,capture.session);assert.equal(payload.mode,capture.mode);assert.equal(payload.text,db.a.text);
assert.equal(draftRevisions.get('a'),4);assert.deepStrictEqual(draftIdentities.get('a'),{revision:4,sequence:8});assert.equal(sourceReturns,1);assert.equal(E.state(),null);
''')

    def test_stale_capture_in_any_identity_field_cannot_reserve_or_write(self):
        self.run_js(r'''
for(const key of ['session','generation','revision','sequence','writer','text','mode']){
 const capture=evidenceDestination(),stale={...capture,[key]:typeof capture[key]==='number'?capture[key]+1:('changed-'+capture[key])};
 const before=$('prompt').value;await assert.rejects(saveReviewedEvidence({session:'a',text:'Wrong replacement',mode:'plan',revision:3,writer:draftWriter,sequence:8},stale),/destination changed/);
 assert.equal($('prompt').value,before);assert.equal(draftEdits.get('a'),7);
}
assert.equal(posts().length,0);
''')

    def test_later_input_while_save_reply_held_is_never_overwritten_then_saves_new_identity(self):
        self.run_js(r'''
assert(await review());const hold=deferred();control.saveHold=hold;const pending=E.append();await settle();assert.equal(posts().length,1);
sessionReadingPending=true;sessionReadingRestoring=true;sessionReadingLatest=true;const readingEpoch=sessionReadingEpoch;
const newer=$('prompt').value+'\nLater exact unsent Work';$('prompt').value=newer;$('turn-mode').value='native';$('prompt').oninput();
assert.equal(sessionReadingEpoch,readingEpoch+1);assert.equal(sessionReadingPending,false);assert.equal(sessionReadingRestoring,false);assert.equal(sessionReadingLatest,false);
assert.equal(draftEdits.get('a'),9);hold.resolve();assert(await pending);assert.equal($('prompt').value,newer);assert.equal(drafts.get('a'),newer);assert.equal(draftModes.get('a'),'native');assert.equal($('turn-mode').value,'native');
delete control.saveHold;assert(await persistDraft('a',{identify:true}));assert.equal(db.a.text,newer);assert.equal(db.a.mode,'native');assert.equal(posts()[1].data.sequence,9);assert.equal(posts()[1].data.revision,4);
''')

    def test_input_before_persist_microtask_is_saved_as_newer_without_fabricated_append_receipt(self):
        self.run_js(r'''
assert(await review());const pending=E.append();const newer=$('prompt').value+'\nImmediate newer note';$('prompt').value=newer;$('prompt').oninput();
assert.equal(await pending,false);assert.equal($('prompt').value,newer);assert.equal(db.a.text,newer);assert.equal(draftEdits.get('a'),9);assert.equal(posts()[0].data.sequence,9);assert.equal(E.state().status,'failed');assert.equal(sourceReturns,0);
''')

    def test_actual_on_saved_receipt_survives_newer_global_saved_state(self):
        self.run_js(r'''
const capture=evidenceDestination(),payload={session:'a',revision:3,sequence:8,writer:draftWriter,text:db.a.text+'\n\n'+block,mode:'plan'};
const original=persistDraft;persistDraft=(id,options)=>original(id,{...options,onSaved:next=>{options.onSaved(next);const newer={text:'Newer same-page saved task',mode:'native',revision:next.revision+1};draftSaved.set(id,newer);draftRevisions.set(id,newer.revision);drafts.set(id,newer.text);draftModes.set(id,newer.mode);draftEdits.set(id,9);$('prompt').value=newer.text;$('turn-mode').value=newer.mode;}});
const receipt=await saveReviewedEvidence(payload,capture);assert.equal(receipt.text,payload.text);assert.equal(receipt.mode,'plan');assert.equal(receipt.revision,4);assert.equal(posts().length,1);
assert.equal(draftSaved.get('a').text,'Newer same-page saved task');assert.equal($('prompt').value,'Newer same-page saved task');assert.equal(draftEdits.get('a'),9);
''')

    def test_reader_review_preflight_rejects_missing_busy_and_unselected_long_item(self):
        self.run_js(r'''
const payload={thread:clone(native),turn_id:'turn-A',item_id:'item-A',valid:()=>true,onReturn:()=>{sourceReturns++;}};
opening=true;assert.throws(()=>readerOptions.onEvidence(payload),/Select an existing task/);opening=false;
draftTimers.set('a',true);assert.throws(()=>readerOptions.onEvidence(payload),/finish saving/);draftTimers.delete('a');
payload.thread.turns[0].items[0].text='x'.repeat(8001);assert.throws(()=>readerOptions.onEvidence(payload),/Select up to 8,000/);
assert.equal(calls.length,0);assert.equal(posts().length,0);assert.equal(sourceReturns,0);assert.equal(E.state(),null);
''')

    def test_other_writer_conflict_retains_reserved_local_editor_without_overwriting_saved(self):
        self.run_js(r'''
assert(await review());db.a={text:'Other writer saved exact Work',mode:'native',revision:4};control.conflict=true;
assert.equal(await E.append(),false);assert.equal(E.state().status,'conflict');assert.equal(draftRevisions.get('a'),3);assert.deepStrictEqual(draftConflicts.get('a'),db.a);
assert($('prompt').value.includes(block));assert.equal(drafts.get('a'),$('prompt').value);assert.equal(db.a.text,'Other writer saved exact Work');
$('prompt').value+='\nLater mine';$('prompt').oninput();assert.equal(await persistDraft('a'),false);assert.equal(posts().length,1);assert.equal(db.a.text,'Other writer saved exact Work');assert.equal(sourceReturns,0);
''')

    def test_switch_during_append_reply_cannot_replace_other_task_or_return_focus(self):
        self.run_js(r'''
assert(await review());const hold=deferred();control.saveHold=hold;const pending=E.append();await settle();
selected='b';generation=8;seed('b');sourceLive=false;const before=$('prompt').value;hold.resolve();assert(await pending);
assert.equal($('prompt').value,before);assert.equal(drafts.get('b'),before);assert.equal(db.b.text,before);assert.equal(sourceReturns,0);assert.equal(posts().length,1);assert.equal(posts()[0].data.session,'a');
''')

    def test_opening_hidden_task_and_new_selection_clear_previous_reference_buttons(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);assert(!$('draft-evidence').hidden);assert.equal($('draft-evidence-list').children.length,1);
opening=true;syncDraftEvidence();assert($('draft-evidence').hidden);assert.equal($('draft-evidence-list').children.length,0);
opening=false;$('task').hidden=true;syncDraftEvidence();assert.equal($('draft-evidence-list').children.length,0);
generation++;seed('b');assert($('draft-evidence').hidden);assert.equal($('draft-evidence-list').children.length,0);assert.equal(posts().length,0);
''')

    def test_reference_read_and_return_restore_editor_view_without_draft_write_or_admission(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);const before=clone(db),text=$('prompt').value;await $('draft-evidence-list').children[0].onclick();
assert.equal(readerCalls.length,1);const {target,callbacks}=readerCalls[0];assert.equal(target.thread_id,'thread-A');assert.equal(target.turn_id,'turn-A');assert.equal(target.item_id,'item-A');assert.equal(target.match_text,reference.quote);
assert.strictEqual(callbacks.preloadedThread.id,'thread-A');assert(callbacks.valid());$('prompt').selectionStart=0;$('prompt').selectionEnd=0;$('prompt').scrollTop=0;
callbacks.onReturn();assert.strictEqual(document.activeElement,$('prompt'));assert.deepStrictEqual($('prompt').focusOptions,{preventScroll:true});assert.equal($('prompt').selectionStart,2);assert.equal($('prompt').selectionEnd,9);assert.equal($('prompt').scrollTop,77);assert.deepStrictEqual(window.moves,[{top:123,behavior:'instant'}]);
assert.equal($('prompt').value,text);assert.deepStrictEqual(db,before);assert.equal(posts().length,0);assert.equal(calls.length,1);assert(calls[0].path.startsWith('/api/native/evidence-source?'));
''')

    def test_newer_editor_text_during_reference_read_survives_return_without_write(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);const hold=deferred();control.readHold=hold;const pending=$('draft-evidence-list').children[0].onclick();
const newer='Newer unrelated unsent task';$('prompt').value=newer;drafts.set('a',newer);draftEdits.set('a',8);$('prompt').selectionStart=4;$('prompt').selectionEnd=6;$('prompt').scrollTop=99;
hold.resolve();await pending;readerCalls[0].callbacks.onReturn();assert.equal($('prompt').value,newer);assert.equal($('prompt').selectionStart,4);assert.equal($('prompt').selectionEnd,6);assert.equal($('prompt').scrollTop,99);assert.equal(posts().length,0);
''')

    def test_switch_during_held_reference_read_suppresses_original_and_return(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);const hold=deferred();control.readHold=hold;const pending=$('draft-evidence-list').children[0].onclick();
generation++;seed('b');const before=$('prompt').value;hold.resolve();await pending;
assert.equal(readerCalls.length,0);assert.equal(window.moves.length,0);assert.equal($('prompt').value,before);assert.equal(posts().length,0);
''')

    def test_unavailable_reference_keeps_exact_original_identity_without_phrase_substitution(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);const changed=clone(native);changed.turns[0].items[0].id='different-same-phrase';control.native=changed;
await $('draft-evidence-list').children[0].onclick();const {target,callbacks}=readerCalls[0];assert.equal(target.thread_id,'thread-A');assert.equal(target.turn_id,'turn-A');assert.equal(target.item_id,'item-A');assert(!('match_text' in target));assert.equal(callbacks.resolution.status,'source_unavailable');assert.equal(callbacks.savedReference.quote,reference.quote);assert.equal(posts().length,0);
''')

    def test_load_saved_draft_updates_reference_panel_immediately(self):
        self.run_js(r'''
seed('a',db.a.text+'\n\n'+block);draftConflicts.set('a',{text:'Saved replacement without reference',mode:'native',revision:4});
$('draft-load').onclick();assert.equal($('prompt').value,'Saved replacement without reference');assert($('draft-evidence').hidden);assert.equal($('draft-evidence-list').children.length,0);assert.equal(posts().length,0);
''')


if __name__ == '__main__':
    unittest.main()
