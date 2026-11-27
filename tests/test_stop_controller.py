"""Captured Stop UI identity, acknowledgement and cold/read-only recovery."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
HARNESS = r"""
const assert = require('assert');
class Element {
  constructor(tag='div'){this.tagName=tag.toUpperCase();this.textContent='';this.value='';this.hidden=false;this.disabled=false;this.open=false;this.children=[];this.dataset={};this.selectionStart=0;this.selectionEnd=0;this.scrollTop=0;}
  append(...nodes){this.children.push(...nodes);}
  replaceChildren(...nodes){this.children=[...nodes];}
  focus(){document.activeElement=this;}
}
const elements=new Map(), $=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const make=(tag,text='',cls='')=>{const node=new Element(tag);node.textContent=text;node.className=cls;return node;};
const document={activeElement:null};
const memory=new Map(), sessionStorage={getItem:key=>memory.get(key)||null,setItem:(key,value)=>memory.set(key,value)};
const crypto=require('crypto');
let owner={session:'desk-a',thread:'native-a',generation:7,opening:false,connected:true,status:'running'};
const apiCalls=[]; let transport=async()=>null;
const api=async(path,body)=>{apiCalls.push({path,body});return transport(path,body);};
const start=(id,thread=owner.thread)=>({method:'turn/started',params:{threadId:thread,turn:{id,status:'inProgress'}}});
const complete=(id,status='completed',thread=owner.thread)=>({method:'turn/completed',params:{threadId:thread,turn:{id,status}}});
const deferred=()=>{let resolve,reject;const promise=new Promise((yes,no)=>{resolve=yes;reject=no;});return {promise,resolve,reject};};
const main={draft:'Unsent Plan 保留',mode:'plan',queues:['one','two'],steering:'A newer correction',steeringWriting:true,startWriting:true};
const mainBefore=JSON.stringify(main);
"""
SETUP = r"""
DeskStopTask.configure({$,api,make,selection:()=>owner}); DeskStopTask.select(owner);
let consume=event=>DeskStopTask.consume(event,owner); const current=()=>DeskStopTask.state();
const knownBody={session:'desk-a',token:'12345678-1234-4234-8234-123456789abc',threadId:'native-a',expectedTurnId:'turn-a'};
const reply=(body,status='accepted',extra={})=>({session:body.session,token:body.token,request:{status,payload:{...body},binding:{session:body.session,thread_id:body.threadId,turn_id:body.expectedTurnId,native_home:'/original/home',profile:'original',cwd:'/original/project'},current_binding:{session:body.session,thread_id:body.threadId,turn_id:body.expectedTurnId},binding_mismatch:false,target_current:true,terminal_status:null,...extra}});
const send=()=>DeskStopTask.send();
"""

@unittest.skipUnless(NODE, 'Node required')
class StopControllerTests(unittest.TestCase):
    def check(self, body, prefix=''):
        source = (ROOT/'codex_desk/static/stop-task.js').read_text()
        script = HARNESS + prefix + '\n' + source + SETUP + '\n(async()=>{\n' + body + '\nassert.strictEqual(JSON.stringify(main),mainBefore);\n})().catch(error=>{console.error(error);process.exitCode=1;});'
        result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_parent_connected_active_turn_is_required(self):
        self.check(r"""
assert($('stop').disabled); consume(start('child','native-child')); assert.strictEqual(current().turn,null);
consume({...start('rpc'),id:3}); assert.strictEqual(current().turn,null);
consume(start('turn-a')); assert(!$('stop').disabled);
owner.connected=false; DeskStopTask.sync({id:owner.session,status:'running'},owner); assert($('stop').disabled);
owner.connected=true; owner.opening=true; DeskStopTask.sync({id:owner.session,status:'running'},owner); assert($('stop').disabled);
owner.opening=false; owner.status='starting'; DeskStopTask.sync({id:owner.session,status:'starting'},owner); assert(!$('stop').disabled);
assert.strictEqual(apiCalls.length,0);
""")

    def test_stop_available_while_steering_and_start_acknowledgements_wait(self):
        self.check(r"""
consume(start('turn-a')); owner.status='starting'; DeskStopTask.sync({id:owner.session,status:'starting'},owner);
assert(main.steeringWriting && main.startWriting); assert(!$('stop').disabled);
transport=async(path,body)=>reply(body); await $('stop').onclick(); assert.strictEqual(apiCalls.length,1);
""")

    def test_four_field_immutable_capture_and_ack_is_not_terminal(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body); await send();
assert.strictEqual(apiCalls.length,1); const body=apiCalls[0].body;
assert.strictEqual(apiCalls[0].path,'/api/stop'); assert.deepStrictEqual(Object.keys(body).sort(),['session','token','threadId','expectedTurnId'].sort());
assert(Object.isFrozen(body)); assert.strictEqual(body.expectedTurnId,'turn-a');
assert.strictEqual(current().turn,'turn-a'); assert(current().active); assert.strictEqual($('stop').textContent,'Stop requested'); assert($('stop').disabled);
assert($('stop-request-status').textContent.includes('Waiting')); assert($('stop-request-target').textContent.includes('native-a / turn-a'));
const stored=JSON.parse(memory.get('codex-desk-stop-requests')); assert.deepStrictEqual(Object.keys(stored[0]).sort(),['session','token']);
assert(!JSON.stringify(stored).includes('turn-a')); await send(); assert.strictEqual(apiCalls.length,1);
""")

    def test_duplicate_held_send_and_delayed_ack_preserve_new_turn_approval_and_editor(self):
        self.check(r"""
consume(start('turn-a')); const held=deferred(); transport=()=>held.promise; const pending=send(); await send(); assert.strictEqual(apiCalls.length,1);
consume(complete('turn-a')); consume(start('turn-b')); const approvals=new Map([['new-approval',{turnId:'turn-b'}]]);
$('steering-input').value=main.steering; $('steering-input').focus(); $('steering-input').selectionStart=4; $('steering-input').selectionEnd=9; $('steering-input').scrollTop=41;
held.resolve(reply(apiCalls[0].body)); await pending;
assert.deepStrictEqual([...approvals.keys()],['new-approval']); assert.strictEqual(current().turn,'turn-b'); assert(current().active); assert(!$('stop').disabled);
assert.strictEqual(document.activeElement,$('steering-input')); assert.strictEqual($('steering-input').value,main.steering); assert.strictEqual($('steering-input').selectionStart,4); assert.strictEqual($('steering-input').selectionEnd,9); assert.strictEqual($('steering-input').scrollTop,41);
assert.strictEqual(apiCalls.length,1); assert($('stop-request-target').textContent.includes('turn-a'));
""")

    def test_old_ack_cannot_replace_a_fresh_stop_or_retire_new_task(self):
        self.check(r"""
consume(start('turn-a')); const old=deferred(); transport=()=>old.promise; const first=send(), a=apiCalls[0].body;
consume(complete('turn-a')); consume(start('turn-b')); transport=async(path,body)=>reply(body); await send(); const b=apiCalls[1].body;
assert.notStrictEqual(a.token,b.token); assert.strictEqual(b.expectedTurnId,'turn-b');
old.resolve(reply(a)); await first;
assert.strictEqual(current().request.token,b.token); assert.strictEqual(current().turn,'turn-b'); assert($('stop-request-target').textContent.includes('turn-b'));
assert(!$('stop-request-previous').hidden); assert($('stop-request-previous-list').children[0].children[0].textContent.includes('turn-a'));
assert.strictEqual(apiCalls.length,2);
""")

    def test_lost_reply_and_explicit_check_use_get_without_resend(self):
        self.check(r"""
consume(start('turn-a')); transport=async()=>{throw Error('local response lost');}; await send(); const body=apiCalls[0].body;
assert.strictEqual(current().request.status,'pending'); assert($('stop').disabled);
transport=async()=>reply(body,'needs_review',{error:'Native acknowledgement unknown'}); await $('stop-request-check').onclick(); await send();
assert.strictEqual(apiCalls.length,2); assert.strictEqual(apiCalls[1].body,undefined); assert(apiCalls[1].path.includes('token='+body.token));
assert.strictEqual(current().request.status,'needs_review'); assert($('stop-request-status').textContent.includes('unconfirmed'));
""")

    def test_later_turn_stop_is_explicit_fresh_uuid_and_keeps_old_unknown_receipt(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body,'needs_review'); await send(); const a=apiCalls[0].body;
consume(complete('turn-a')); consume(start('turn-b')); assert(!$('stop').disabled); assert.strictEqual(apiCalls.length,1);
transport=async(path,body)=>reply(body); await send(); const b=apiCalls[1].body;
assert.notStrictEqual(a.token,b.token); assert.strictEqual(b.expectedTurnId,'turn-b'); assert.strictEqual(current().requests.length,2);
assert(!$('stop-request-previous').hidden); assert($('stop-request-previous-list').children[0].children[1].textContent.includes('unconfirmed'));
""")

    def test_actual_matching_native_terminal_not_other_turn_sets_outcome(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body); await send();
consume(complete('child','interrupted','native-child')); assert.strictEqual(current().turn,'turn-a');
consume(complete('turn-other','failed')); assert.strictEqual(current().turn,'turn-a'); assert($('stop-request-status').textContent.includes('Waiting'));
consume(complete('turn-a','interrupted')); assert.strictEqual(current().turn,null); assert($('stop').disabled); assert($('stop-request-status').textContent.includes('interrupted'));
consume(start('turn-a')); assert.strictEqual(current().turn,null); consume(start('turn-b')); assert.strictEqual(current().turn,'turn-b');
""")

    def test_terminal_before_ack_stays_authoritative_and_never_retires_newer_turn(self):
        self.check(r"""
consume(start('turn-a')); const held=deferred(); transport=()=>held.promise; const pending=send(); const a=apiCalls[0].body;
consume(complete('turn-a','failed')); consume(start('turn-b')); held.resolve(reply(a)); await pending;
assert.strictEqual(current().turn,'turn-b'); assert($('stop-request-status').textContent.includes('failed')); assert(!$('stop').disabled);
""")

    def test_stale_terminal_state_snapshot_cannot_retire_a_new_streamed_turn(self):
        self.check(r"""
consume(start('turn-a')); const snapshot=DeskStopTask.snapshot(); consume(complete('turn-a')); consume(start('turn-b'));
owner.status='completed'; DeskStopTask.sync({id:owner.session,status:'completed'},{...owner,snapshot}); assert.strictEqual(current().turn,'turn-b');
owner.status='running'; DeskStopTask.sync({id:owner.session,status:'running'},owner); assert(current().active);
const fresh=DeskStopTask.snapshot(); owner.status='interrupted'; DeskStopTask.sync({id:owner.session,status:'interrupted'},{...owner,snapshot:fresh}); assert.strictEqual(current().turn,null);
""")

    def test_stale_opening_terminal_and_old_thread_snapshot_preserve_new_owner(self):
        self.check(r"""
owner.opening=true; owner.status='completed'; consume(start('turn-b')); DeskStopTask.sync({id:owner.session,status:'completed'},owner); assert.strictEqual(current().turn,'turn-b');
owner.opening=false; owner.status='running'; DeskStopTask.restoreThread({id:owner.thread,turns:[{id:'turn-a',status:'inProgress'}]},owner); assert.strictEqual(current().turn,'turn-b');
DeskStopTask.consume(complete('turn-b'),{...owner,generation:6}); assert.strictEqual(current().turn,'turn-b');
DeskStopTask.restoreThread({id:owner.thread,turns:[{id:'turn-b',status:'completed'},{id:'new-terminal',status:'failed'}]},owner); assert.strictEqual(current().turn,null);
consume(start('turn-b')); consume(start('new-terminal')); assert.strictEqual(current().turn,null); consume(start('turn-c')); assert(current().active);
""")

    def test_retained_cold_identity_checks_only_get_and_connection_gate(self):
        prefix="memory.set('codex-desk-stop-requests',JSON.stringify([{session:'desk-a',token:'12345678-1234-4234-8234-123456789abc'}]));"
        self.check(r"""
owner.connected=false; consume(start('turn-a')); transport=async()=>reply(knownBody,'accepted'); await DeskStopTask.opened();
assert.strictEqual(apiCalls.length,1); assert.strictEqual(apiCalls[0].body,undefined); assert(!current().active); assert($('stop').disabled); assert(!$('stop-request-check').disabled);
await send(); assert.strictEqual(apiCalls.length,1); await $('stop-request-check').onclick(); assert.strictEqual(apiCalls.length,2);
assert(apiCalls.every(call=>call.body===undefined && call.path.startsWith('/api/stop?')));
""",prefix)

    def test_blank_cold_discovery_and_unknown_transport_never_send_or_open(self):
        self.check(r"""
consume(start('turn-a')); transport=async()=>{throw Error('receipt transport unavailable');}; assert.strictEqual(await DeskStopTask.opened(),true); assert($('stop').disabled);
await send(); assert.strictEqual(apiCalls.length,1); assert.strictEqual(apiCalls[0].body,undefined);
transport=async()=>{const error=Error('No saved Stop request');error.status=404;throw error;}; assert.strictEqual(await DeskStopTask.opened(),false); assert(!$('stop').disabled);
assert.strictEqual(apiCalls.length,2); assert(apiCalls.every(call=>call.body===undefined));
""")

    def test_multiple_cold_identities_remain_read_only_and_recover_targets(self):
        prefix="memory.set('codex-desk-stop-requests',JSON.stringify([{session:'desk-a',token:'12345678-1234-4234-8234-123456789abc'},{session:'desk-a',token:'22345678-1234-4234-8234-123456789abc'}]));"
        self.check(r"""
consume(start('turn-c')); transport=async path=>path.includes('22345678')?reply({...knownBody,token:'22345678-1234-4234-8234-123456789abc',expectedTurnId:'turn-b'}):reply(knownBody,'needs_review');
await DeskStopTask.opened(); assert.strictEqual(apiCalls.length,2); assert(apiCalls.every(call=>call.body===undefined)); assert(!$('stop').disabled); assert.strictEqual(current().requests.length,2);
assert(current().requests.every(req=>req.body)); assert($('stop-request-previous-list').children[0].children[0].textContent.includes('turn-a'));
""",prefix)

    def test_native_rejection_preserves_capture_with_no_retry(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body,'rejected',{error:'Native turn cannot be interrupted'}); await send();
assert.strictEqual(apiCalls.length,1); assert.strictEqual(current().request.status,'rejected'); assert.strictEqual(current().turn,'turn-a'); assert($('stop-request-error').textContent.includes('cannot be interrupted')); assert(!$('stop').disabled);
const original=apiCalls[0].body; transport=async()=>reply(original,'rejected'); await $('stop-request-check').onclick(); assert.strictEqual(apiCalls[1].body,undefined); assert.strictEqual(apiCalls.length,2);
""")

    def test_known_native_rejection_allows_only_explicit_fresh_identity(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body,'rejected'); await send(); const original=apiCalls[0].body;
assert(!$('stop').disabled); assert.strictEqual(apiCalls.length,1); transport=async(path,body)=>reply(body); await $('stop').onclick();
assert.strictEqual(apiCalls.length,2); const fresh=apiCalls[1].body; assert.notStrictEqual(fresh.token,original.token); assert.strictEqual(fresh.expectedTurnId,original.expectedTurnId);
assert.strictEqual(current().requests.length,2); assert.strictEqual(current().request.token,fresh.token); assert($('stop').disabled);
""")

    def test_same_session_new_generation_uses_its_own_cold_probe(self):
        self.check(r"""
const held=deferred(); transport=()=>held.promise; const old=DeskStopTask.opened(); assert.strictEqual(apiCalls.length,1);
owner={...owner,generation:8}; DeskStopTask.select(owner); transport=async()=>reply(knownBody,'needs_review');
assert.strictEqual(await DeskStopTask.opened(),true); assert.strictEqual(apiCalls.length,2);
const missing=Error('No saved Stop request'); missing.status=404; held.reject(missing); assert.strictEqual(await old,false);
assert.strictEqual(current().context.generation,8); assert.strictEqual(current().request.token,knownBody.token); assert.strictEqual(current().request.status,'needs_review');
assert(apiCalls.every(call=>call.body===undefined));
""")

    def test_mismatched_receipt_cannot_change_captured_target(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply({...body,expectedTurnId:'foreign-task'}); await send();
assert.strictEqual(current().request.body.expectedTurnId,'turn-a'); assert.strictEqual(current().request.status,'pending'); assert($('stop-request-error').textContent.includes('different captured target')); assert.strictEqual(current().turn,'turn-a');
""")

    def test_conflict_recovers_original_uuid_without_new_target_or_native_retry(self):
        self.check(r"""
consume(start('turn-a')); transport=async()=>{const error=Error('Existing request');error.status=409;error.current=reply(knownBody,'needs_review');throw error;}; await send();
assert.strictEqual(current().request.token,knownBody.token); assert.strictEqual(current().requests.length,1); assert($('stop-request-target').textContent.includes('turn-a')); assert($('stop').disabled); await send(); assert.strictEqual(apiCalls.length,1);
const stored=JSON.parse(memory.get('codex-desk-stop-requests')); assert.strictEqual(stored.length,1); assert.strictEqual(stored[0].token,knownBody.token);
""")

    def test_receipt_only_changed_binding_retains_original_target_and_allows_fresh_current_capture(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body,'rejected',{binding_mismatch:true,target_current:false,current_binding:{thread_id:'native-a',profile:'changed'}}); await send();
assert($('stop-request-original-binding').textContent.includes('original')); assert($('stop-request-current-binding').textContent.includes('changed')); assert(!$('stop').disabled); assert.strictEqual(apiCalls.length,1);
""")

    def test_selection_change_held_response_cannot_mutate_current_task(self):
        self.check(r"""
consume(start('turn-a')); const held=deferred(); transport=()=>held.promise; const pending=send(); const a=apiCalls[0].body;
owner={session:'desk-b',thread:'native-b',generation:8,opening:false,connected:true,status:'running'}; DeskStopTask.select(owner); consume(start('turn-b'));
held.resolve(reply(a)); await pending; assert.strictEqual(current().turn,'turn-b'); assert.strictEqual(current().request,undefined); assert.strictEqual($('stop-request-target').textContent,''); assert(!$('stop').disabled);
""")

    def test_storage_failure_precedes_any_native_request(self):
        self.check(r"""
consume(start('turn-a')); sessionStorage.setItem=()=>{throw Error('Storage unavailable');}; await send();
assert.strictEqual(apiCalls.length,0); assert.strictEqual(current().request,undefined); assert($('stop-request-error').textContent.includes('Storage unavailable'));
""")

    def test_visible_retained_reading_preserves_focus_scroll_and_follow_gate(self):
        self.check(r"""
consume(start('turn-a')); transport=async(path,body)=>reply(body); await send(); assert(DeskStopTask.reading());
$('prompt').value=main.draft; $('prompt').focus(); $('prompt').selectionStart=2; $('prompt').selectionEnd=8; $('prompt').scrollTop=48;
await $('stop-request-check').onclick(); assert.strictEqual(document.activeElement,$('prompt')); assert.strictEqual($('prompt').value,main.draft); assert.strictEqual($('prompt').selectionStart,2); assert.strictEqual($('prompt').selectionEnd,8); assert.strictEqual($('prompt').scrollTop,48);
$('stop-request-captured').open=false; assert(!DeskStopTask.reading()); $('stop-request-captured').open=true; $('stop-request').hidden=true; assert(!DeskStopTask.reading());
""")

    def app_open_check(self, setup, body, prefix=''):
        source = (ROOT/'codex_desk/static/app.js').read_text()
        opening = source[source.index('async function open('):source.index('function profileInfo()')]
        evidence = (ROOT/'codex_desk/static/evidence-preparation.js').read_text() + '\nconst draftRevisions=new Map();\n'
        evidence += source[source.index('function taskEvidenceDestination('):source.index('async function saveReviewedEvidence(')]
        evidence += source[source.index('function syncDraftEvidence('):source.index('DeskEvidencePreparation.configure(')]
        script = HARNESS + prefix + evidence + (ROOT/'codex_desk/static/stop-task.js').read_text() + SETUP + setup + opening + '\n(async()=>{' + body + '})().catch(error=>{console.error(error);process.exitCode=1;});'
        result = subprocess.run([NODE, '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_losing_cold_stop_probe_cannot_open_a_superseded_native_owner(self):
        setup = r"""
let generation=0,selected=null,opening=false,modeSelected=null,after=0,nativeThreadId=null,currentTurn=null;
const drafts=new Map(),items=new Map(),nodes=new Map(),itemTurns=new Map(),collaborationGroups=new Map(),requests=new Map();
const state={sessions:[{id:'old-startup',thread_id:'native-old'},{id:'chosen-session',thread_id:'native-chosen'}]};
const DeskHome={selectionChanged(){}},DeskRecall={selectionChanged(){}},DeskFollowups={select(){}};
const DeskNativeSteps={select(){},restoreThread(){}},DeskTurnChanges={select(){},restoreThread(){}},DeskSteering={select(){},restoreThread(){},opened:async()=>false,reading:()=>false};
function rememberDraft(){} function persistDraft(){} function latestLabel(){} function approvals(){} function draw(){} function draftStatus(){}
function loadDraft(){return Promise.resolve();} function turnRequest(){return null;} async function discoverTurnRequest(){return null;}
async function refresh(){} function renderItem(){} function error(error){throw error;}
let latestUpdates=0; const localStorage={setItem(){}}; const requestAnimationFrame=callback=>callback(); function goLatest(){}
const probe=deferred(); DeskStopTask.opened=async()=>selected==='old-startup'?probe.promise:false;
const nativeOpened=[]; transport=async(path,body)=>{if(path==='/api/open'){nativeOpened.push(body.session);return {thread:{id:body.session+'-native',turns:[]}};}if(path.startsWith('/api/events?'))return [];throw Error('unexpected '+path);};
"""
        self.app_open_check(setup, r"""
const losing=open('old-startup',{steerReceiptOnly:true}); await Promise.resolve(); await Promise.resolve(); await Promise.resolve();
await open('chosen-session'); probe.resolve(false); await losing;
assert.strictEqual(selected,'chosen-session'); assert.deepStrictEqual(nativeOpened,['chosen-session']);
""")

    def test_actual_app_cold_stop_receipt_path_is_get_only_before_native_open(self):
        setup = r"""
let generation=0,selected=null,opening=false,modeSelected=null,after=0,nativeThreadId=null,currentTurn=null;
const drafts=new Map(),items=new Map(),nodes=new Map(),itemTurns=new Map(),collaborationGroups=new Map(),requests=new Map();
const state={sessions:[{id:'desk-a',thread_id:'native-a',status:'running'}],pending:{}};
const DeskHome={selectionChanged(){}},DeskRecall={selectionChanged(){}},DeskFollowups={select(){}};
const DeskNativeSteps={select(){},restoreThread(){}},DeskTurnChanges={select(){},restoreThread(){}},DeskSteering={select(){},restoreThread(){},opened:async()=>false,reading:()=>false};
function rememberDraft(){} function persistDraft(){} function latestLabel(){} function approvals(){} function draftStatus(){}
function loadDraft(){return Promise.resolve();} function turnRequest(){return null;} async function discoverTurnRequest(){return null;}
async function refresh(){} function renderItem(){} function error(error){throw error;}
function draw(){DeskStopTask.sync(state.sessions[0],{session:selected,thread:nativeThreadId,generation});}
consume=event=>DeskStopTask.consume(event,{session:selected,thread:nativeThreadId,generation});
let latestUpdates=0; const localStorage={setItem(){}}; const requestAnimationFrame=callback=>callback(); function goLatest(){}
DeskStopTask.configure({$,api,make,selection:()=>({session:selected,thread:nativeThreadId,generation,opening,status:state.sessions[0].status,connected:Object.hasOwn(state.pending,selected)})});
transport=async(path,body)=>{assert.strictEqual(body,undefined);if(path.startsWith('/api/stop?'))return reply(knownBody,'needs_review');if(path.startsWith('/api/events?'))return [{seq:1,event:start('turn-a','native-a')}];throw Error('unexpected '+path);};
"""
        self.app_open_check(setup, r"""
assert.strictEqual(await open('desk-a',{steerReceiptOnly:true}),true); assert.strictEqual(selected,'desk-a'); assert.strictEqual(nativeThreadId,'native-a');
assert.strictEqual(current().turn,'turn-a'); assert(!current().active); assert($('stop').disabled); assert(apiCalls.every(call=>call.body===undefined)); assert(apiCalls.every(call=>call.path!=='/api/open'));
""")

    def test_actual_app_wiring_has_no_ack_retirement_or_refresh(self):
        source = (ROOT/'codex_desk/static/app.js').read_text()
        self.assertNotIn("$('stop').onclick=async", source)
        self.assertIn('DeskStopTask.configure({$,api,make,selection:', source)
        self.assertIn('stopSnapshot=DeskStopTask.snapshot()', source)
        self.assertIn('snapshot:stopStateSnapshot', source)
        self.assertEqual(source.count('!DeskStopTask.reading()'), 3)
        self.assertIn('<script src="/stop-task.js" defer>', (ROOT/'codex_desk/static/index.html').read_text())

if __name__ == '__main__': unittest.main()
