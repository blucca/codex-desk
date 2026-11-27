"""Separate current-task correction identity, editor continuity and retained receipts."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
HARNESS=r"""
const assert=require('assert');
class Element {
  constructor(){this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.open=false;this.selectionStart=0;this.selectionEnd=0;this.scrollTop=0;}
  focus(){document.activeElement=this;}
}
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const document={activeElement:null};
const memory=new Map(),sessionStorage={getItem:k=>memory.get(k)||null,setItem:(k,v)=>memory.set(k,v)};
const crypto=require('crypto');
let owner={session:'desk-a',thread:'native-a',generation:7,opening:false,status:'running'};
const apiCalls=[];let transport=async()=>null;
const api=async(path,body)=>{apiCalls.push({path,body});return transport(path,body);};
const start=(id,thread=owner.thread)=>({method:'turn/started',params:{threadId:thread,turn:{id,status:'inProgress'}}});
const complete=id=>({method:'turn/completed',params:{threadId:owner.thread,turn:{id,status:'completed'}}});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const main={draft:'Unsent Plan 保留',mode:'plan',queue:['one','two']};
const mainBefore=JSON.stringify(main);
"""
SETUP=r"""
DeskSteering.configure({$,api,selection:()=>owner});DeskSteering.select(owner);
const consume=message=>DeskSteering.consume(message,owner);
const current=()=>DeskSteering.state();
const edit=text=>{$('steering-input').value=text;$('steering-input').oninput();};
const reply=(body,status='accepted',extra={})=>({session:body.session,token:body.token,request:{status,payload:{...body},binding_mismatch:false,target_current:true,result:{turnId:body.expectedTurnId},...extra}});
const send=()=>DeskSteering.send();
const knownBody={session:'desk-a',token:'12345678-1234-4234-8234-123456789abc',threadId:'native-a',expectedTurnId:'turn-a',text:'Exact earlier captured instruction 保留 <script>'};
"""

@unittest.skipUnless(NODE,'Node required')
class SteeringControllerTests(unittest.TestCase):
    def check(self,body,prefix=''):
        script=HARNESS+prefix+'\n'+(ROOT/'codex_desk/static/steering.js').read_text()+SETUP+'\n(async()=>{\n'+body+'\nassert.strictEqual(JSON.stringify(main),mainBefore);\n})().catch(e=>{console.error(e);process.exitCode=1;});'
        result=subprocess.run([NODE,'-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_only_native_parent_active_owner_can_send(self):
        self.check(r"""
edit('Skip integration; run unit tests.');assert($('steering-send').disabled);
consume(start('child','native-child'));assert.strictEqual(current().turn,null);
consume(start('turn-a'));assert(!$('steering-send').disabled);
DeskSteering.consume(complete('turn-a'),{...owner,generation:6});assert(current().active);
consume(complete('turn-a'));assert(!current().active);assert($('steering-send').disabled);
consume(start('turn-a'));assert.strictEqual(current().turn,null);
consume(start('turn-b'));assert.strictEqual(current().turn,'turn-b');
DeskSteering.restoreThread({id:owner.thread,turns:[{id:'turn-a',status:'inProgress'}]},owner);assert.strictEqual(current().turn,'turn-b');
consume(complete('turn-b'));DeskSteering.restoreThread({id:owner.thread,turns:[{id:'older-unseen',status:'inProgress'}]},owner);assert.strictEqual(current().turn,null);
assert.strictEqual(apiCalls.length,0);
""")

    def test_opening_stale_terminal_state_does_not_retire_newly_replayed_turn(self):
        self.check(r"""
owner.opening=true;owner.status='completed';consume(start('new-replayed-turn'));
DeskSteering.sync({id:owner.session,status:'completed'},owner);assert.strictEqual(current().turn,'new-replayed-turn');
owner.opening=false;owner.status='running';DeskSteering.sync({id:owner.session,status:'running'},owner);
assert(current().active);edit('Correct the newly resumed native task');assert(!$('steering-send').disabled);
""")

    def test_accepted_newer_terminal_snapshot_establishes_and_retires_its_boundary(self):
        self.check(r"""
consume(start('old-active'));DeskSteering.restoreThread({id:owner.thread,turns:[{id:'old-active',status:'completed'},{id:'new-terminal',status:'completed'}]},owner);
assert.strictEqual(current().turn,null);assert(!current().active);consume(start('old-active'));consume(start('new-terminal'));assert.strictEqual(current().turn,null);
consume(start('fresh-active'));assert.strictEqual(current().turn,'fresh-active');
""")

    def test_exact_five_field_capture_and_same_turn_acceptance_clear_only_correction(self):
        self.check(r"""
consume(start('turn-a'));edit('Exact correction 保留 <script>');
transport=async(path,body)=>reply(body);await send();
assert.strictEqual(apiCalls.length,1);const body=apiCalls[0].body;
assert.strictEqual(apiCalls[0].path,'/api/steer');assert.deepStrictEqual(Object.keys(body).sort(),['session','token','threadId','expectedTurnId','text'].sort());
assert.strictEqual(body.expectedTurnId,'turn-a');assert.strictEqual(body.text,'Exact correction 保留 <script>');assert(Object.isFrozen(body));
assert.strictEqual($('steering-input').value,'');assert.strictEqual(current().request.status,'accepted');
assert.strictEqual($('steering-captured-text').textContent,body.text);assert($('steering-send').disabled);
const stored=JSON.parse(memory.get('codex-desk-steer-requests'));assert.deepStrictEqual(Object.keys(stored[0]).sort(),['session','token']);assert(!JSON.stringify(stored).includes('Exact correction'));
""")

    def test_duplicate_inflight_click_and_newer_edit_away_back_never_clear(self):
        self.check(r"""
consume(start('turn-a'));edit('Captured instruction');const held=deferred();transport=()=>held.promise;
const pending=send();await send();assert.strictEqual(apiCalls.length,1);
edit('newer');edit('Captured instruction');$('steering-input').focus();$('steering-input').selectionStart=3;$('steering-input').selectionEnd=7;
held.resolve(reply(apiCalls[0].body));await pending;
assert.strictEqual(current().editor.text,'Captured instruction');assert.strictEqual($('steering-input').value,'Captured instruction');
assert.strictEqual(document.activeElement,$('steering-input'));assert.strictEqual($('steering-input').selectionStart,3);assert.strictEqual($('steering-input').selectionEnd,7);
assert(!$('steering-send').disabled);
""")

    def test_selection_change_never_mutates_another_correction(self):
        self.check(r"""
consume(start('turn-a'));edit('Original correction');const held=deferred();transport=()=>held.promise;const pending=send();
owner={session:'desk-b',thread:'native-b',generation:8,opening:false,status:'running'};DeskSteering.select(owner);consume(start('turn-other'));edit('Other correction');
held.resolve(reply(apiCalls[0].body));await pending;assert.strictEqual($('steering-input').value,'Other correction');assert.strictEqual(current().turn,'turn-other');
owner={session:'desk-a',thread:'native-a',generation:9,opening:false,status:'running'};DeskSteering.select(owner);consume(start('turn-a'));assert.strictEqual($('steering-input').value,'');assert.strictEqual(apiCalls.length,1);
""")

    def test_native_rejection_preserves_exact_capture_without_retry_or_fallback(self):
        self.check(r"""
consume(start('turn-a'));edit('Native may reject');transport=async(path,body)=>reply(body,'rejected',{error:'unsteerable native turn'});await send();
assert.strictEqual(current().request.status,'rejected');assert.strictEqual($('steering-input').value,'Native may reject');assert.strictEqual($('steering-captured-text').textContent,'Native may reject');
assert.strictEqual($('steering-error').textContent,'unsteerable native turn');assert.strictEqual(apiCalls.length,1);
await DeskSteering.read(current().request);assert.strictEqual(apiCalls[1].body,undefined);
assert(apiCalls.every(call=>call.path.startsWith('/api/steer')));
""")

    def test_lost_response_keeps_opaque_identity_and_check_never_resends(self):
        self.check(r"""
consume(start('turn-a'));edit('Captured unconfirmed');transport=async()=>{throw Error('response lost');};await send();
assert($('steering-send').disabled);assert.strictEqual(current().editor.text,'Captured unconfirmed');const body=apiCalls[0].body;
transport=async()=>reply(body,'needs_review',{error:'Review retained activity'});await DeskSteering.read(current().request);
assert.strictEqual(current().request.status,'needs_review');await send();assert.strictEqual(apiCalls.length,2);assert.strictEqual(apiCalls[1].body,undefined);
""")

    def test_old_unknown_requires_explicit_prepare_for_new_task_then_fresh_token(self):
        self.check(r"""
consume(start('turn-a'));edit('Captured unknown');transport=async(path,body)=>reply(body,'needs_review');await send();const first=apiCalls[0].body;
consume(complete('turn-a'));consume(start('turn-b'));assert($('steering-send').disabled);assert(!$('steering-prepare').hidden);
$('steering-prepare').onclick();assert(!$('steering-send').disabled);assert.strictEqual(apiCalls.length,1);edit('Fresh turn-b correction');
transport=async(path,body)=>reply(body);await send();assert.strictEqual(apiCalls.length,2);assert.notStrictEqual(apiCalls[1].body.token,first.token);assert.strictEqual(apiCalls[1].body.expectedTurnId,'turn-b');
""")

    def test_cold_rejected_receipt_restores_correction_only_through_get(self):
        prefix="memory.set('codex-desk-steer-requests',JSON.stringify([{session:'desk-a',token:'12345678-1234-4234-8234-123456789abc'}]));"
        self.check(r"""
consume(start('turn-a'));transport=async()=>reply(knownBody,'rejected');await DeskSteering.opened();
assert.strictEqual(apiCalls.length,1);assert.strictEqual(apiCalls[0].body,undefined);assert.strictEqual(current().editor.text,knownBody.text);assert.strictEqual($('steering-input').value,knownBody.text);
await DeskSteering.opened();assert.strictEqual(apiCalls.length,2);assert(apiCalls.every(call=>call.body===undefined));
""",prefix)

    def test_disconnected_retained_active_turn_cannot_send_but_receipt_check_works(self):
        prefix="memory.set('codex-desk-steer-requests',JSON.stringify([{session:'desk-a',token:'12345678-1234-4234-8234-123456789abc'}]));"
        self.check(r"""
owner.connected=false;consume(start('turn-a'));transport=async()=>reply(knownBody,'rejected');await DeskSteering.opened();
assert(!current().active);assert($('steering-send').disabled);assert(!$('steering-check').disabled);assert.strictEqual(current().editor.text,knownBody.text);
await send();assert.strictEqual(apiCalls.length,1);await DeskSteering.read(current().request);assert.strictEqual(apiCalls.length,2);assert(apiCalls.every(call=>call.body===undefined));
owner.connected=true;DeskSteering.sync({id:owner.session,status:'running'},owner);assert(current().active);assert(!$('steering-send').disabled);
""",prefix)

    def test_cold_accepted_receipt_does_not_repopulate_or_resend_correction(self):
        prefix="memory.set('codex-desk-steer-requests',JSON.stringify([{session:'desk-a',token:'12345678-1234-4234-8234-123456789abc'}]));"
        self.check(r"""
consume(start('turn-a'));transport=async()=>reply(knownBody);await DeskSteering.opened();
assert.strictEqual(current().editor.text,'');assert.strictEqual($('steering-captured-text').textContent,knownBody.text);assert.strictEqual(current().request.status,'accepted');await send();assert.strictEqual(apiCalls.length,1);
""",prefix)

    def test_mismatched_native_acceptance_never_clears_or_advances_task(self):
        self.check(r"""
consume(start('turn-a'));edit('Keep exact capture');transport=async(path,body)=>reply(body,'accepted',{result:{turnId:'foreign-turn'}});await send();
assert.strictEqual(current().editor.text,'Keep exact capture');assert.strictEqual(current().turn,'turn-a');assert.strictEqual(current().request.status,'pending');assert($('steering-send').disabled);
assert($('steering-error').textContent.includes('did not confirm'));
""")

    def test_discovery_failure_gates_only_steering_and_successful_get_recovers(self):
        self.check(r"""
consume(start('turn-a'));edit('Still unsent');transport=async()=>{throw Error('receipt service unavailable');};await DeskSteering.opened();assert($('steering-send').disabled);assert(!$('steering-check').hidden);await send();assert.strictEqual(apiCalls.length,1);
transport=async()=>null;await DeskSteering.opened();assert(!$('steering-send').disabled);assert.strictEqual(current().editor.text,'Still unsent');
""")

    def test_conflict_adopts_old_receipt_and_preserves_new_instruction(self):
        self.check(r"""
consume(start('turn-a'));edit('New correction must stay');transport=async()=>{const e=Error('An earlier instruction is unconfirmed');e.status=409;e.current=reply(knownBody,'needs_review');throw e;};await send();
assert.strictEqual(current().request.token,knownBody.token);assert.strictEqual($('steering-captured-text').textContent,knownBody.text);assert.strictEqual(current().editor.text,'New correction must stay');assert($('steering-send').disabled);
""")

    def test_state_only_terminal_and_late_child_events_retire_native_eligibility(self):
        self.check(r"""
consume(start('turn-a'));edit('Keep correction');owner.status='interrupted';DeskSteering.sync({id:owner.session,status:'interrupted'},owner);assert(!current().active);assert($('steering-send').disabled);
owner.status='running';consume(start('turn-a'));consume(start('wrong-child','native-child'));assert.strictEqual(current().turn,null);
consume(start('turn-b'));assert(current().active);assert.strictEqual(current().editor.text,'Keep correction');
""")

    def test_correction_focus_or_expanded_capture_pauses_following_only_when_visible(self):
        self.check(r"""
consume(start('turn-a'));$('steering-input').focus();assert(DeskSteering.reading());document.activeElement=null;assert(!DeskSteering.reading());
edit('Captured');transport=async(path,body)=>reply(body);await send();assert(DeskSteering.reading());$('steering-captured').open=false;assert(!DeskSteering.reading());
""")

    def test_losing_startup_false_receipt_probe_cannot_open_a_native_owner(self):
        setup=r"""
DeskSteering.configure({$,api,selection:()=>owner});
let generation=0,selected=null,opening=false,modeSelected=null,after=0,nativeThreadId=null,currentTurn=null;
const drafts=new Map(),items=new Map(),nodes=new Map(),itemTurns=new Map(),collaborationGroups=new Map(),requests=new Map();
const state={sessions:[{id:'old-startup',thread_id:'native-old'},{id:'chosen-session',thread_id:'native-chosen'}]};
const DeskHome={selectionChanged(){}},DeskRecall={selectionChanged(){}},DeskFollowups={select(){}};
const DeskNativeSteps={select(){},restoreThread(){}},DeskTurnChanges={select(){},restoreThread(){}};
function rememberDraft(){}function persistDraft(){}function latestLabel(){}function approvals(){}function draw(){}function draftStatus(){}
function loadDraft(){return Promise.resolve();}function turnRequest(){return null;}async function discoverTurnRequest(){return null;}
async function refresh(){}function consume(){}function renderItem(){}function error(e){throw e;}
let latestUpdates=0;const localStorage={setItem(){}};const requestAnimationFrame=f=>f();function goLatest(){}
Element.prototype.replaceChildren=function(){};
const probe=deferred();DeskSteering.opened=async()=>probe.promise;
const nativeOpened=[];transport=async(path,body)=>{if(path==='/api/open'){nativeOpened.push(body.session);return {thread:{id:body.session+'-native',turns:[]}};}if(path.startsWith('/api/events?'))return [];throw Error('unexpected '+path);};
"""
        source=(ROOT/'codex_desk/static/app.js').read_text()
        opening=source[source.index('async function open('):source.index('function profileInfo()')]
        body=r"""
const losing=open('old-startup',{steerReceiptOnly:true});await Promise.resolve();await Promise.resolve();
await open('chosen-session');probe.resolve(false);await losing;
assert.strictEqual(selected,'chosen-session');assert.deepStrictEqual(nativeOpened,['chosen-session']);
"""
        script=HARNESS+(ROOT/'codex_desk/static/steering.js').read_text()+setup+opening+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'
        result=subprocess.run([NODE,'-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
