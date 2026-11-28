"""A pending reviewed handoff cannot override newer explicit navigation."""
import json
import subprocess
import unittest
from test_navigation_controllers import APP,DOM,NODE

SETUP=DOM+r'''
let generation=7;
const listeners=new Map(),preview=$('preview');
preview.showModal=()=>{preview.open=true;};
preview.close=()=>{preview.open=false;for(const f of listeners.get('close')||[])f();};
preview.addEventListener=(type,f)=>{if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(f);};
$('history').close=()=>{$('history').open=false;};$('history').addEventListener=()=>{};
function resetNative(){}function nativeList(){}function fillProfiles(node){node.value='default';}
const opened=[];open=async id=>{opened.push(id);selected=id;++generation;};
let refreshes=0;async function refresh(){++refreshes;}
function error(e){throw e;}
const draft={text:'Selected unsent Plan',mode:'plan'},queue=['Paused Work','Paused Plan'];
$('prompt').value=draft.text;$('turn-mode').value=draft.mode;
const storage=new Map();const sessionStorage={getItem:key=>storage.get(key) ?? null,setItem:(key,value)=>storage.set(key,String(value))};
const token='00000000-0000-4000-8000-000000000001';let tokenCount=0;const crypto={randomUUID:()=>{++tokenCount;return token.slice(0,-1)+tokenCount;}};
const result=(id='created-a',outcome='accepted')=>({id,token:calls.filter(c=>c.path==='/api/handoff/start').at(-1).data.token,handoff:{status:outcome==='accepted'?'accepted':'needs_review',admission:{outcome}},preparation:{entries:[],reservation:outcome==='unknown'?{state:'unknown'}:null}});
const calls=[],gates=[];
let savedResult=null,readFailure=null;
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
api=async(path,data)=>{
  calls.push({path,data});
  if(path.startsWith('/api/handoff/request?')){if(readFailure)throw readFailure;const token=new URL('http://desk'+path).searchParams.get('token');const request=[...handoffRequests.values()].find(r=>r.token===token);return savedResult || request?.result || {id:'created-a',token,handoff:{status:'pending'},preparation:{entries:[],reservation:{state:'reserved'}}};}
  if(path==='/api/handoff')return {text:'Original evidence '+data.thread};
  if(path==='/api/handoff/start'){const gate=deferred();gates.push(gate);return await gate.promise;}
  throw Error('Unexpected '+path);
};
const submit=()=> $('handoff-start').onclick();
function editGoal(text){$('handoff-goal').value=text;$('handoff-goal').oninput();}
function editEvidence(text){$('handoff-text').value=text;$('handoff-text').oninput();}
function unchanged(){assert.strictEqual($('prompt').value,draft.text);assert.strictEqual($('turn-mode').value,draft.mode);assert.deepStrictEqual(queue,['Paused Work','Paused Plan']);}
'''

@unittest.skipUnless(NODE,'Node is required for handoff navigation')
class HandoffNavigationTests(unittest.TestCase):
    def check(self,body):
        source=APP.read_text();fragment=source[source.index('let handoffSource='):source.index('let providerEditing=')]
        original_read=source[source.index('let nativeIdVersion=0;'):source.index('function resetNative() {')]
        code=SETUP+original_read+fragment+'\n(async()=>{'+body+r'''
unchanged();process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        r=subprocess.run([NODE,'-e',code],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(json.loads(r.stdout),{'passed':True})
    def test_cancel_pending_success_keeps_selection_and_exposes_created_task_by_refresh(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Submitted next task');const pending=submit();$('preview-close').onclick();
gates[0].resolve(result());await pending;
assert.deepStrictEqual(opened,[]);assert.strictEqual(selected,'active');assert(!preview.open);assert(refreshes>0);
assert.strictEqual(calls.filter(c=>c.path==='/api/handoff/start').length,1);
''')
    def test_old_success_keeps_new_source_goal_evidence_and_dialog(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Submitted task A');const pending=submit();$('preview-close').onclick();
await showHandoff('source-b','/project/b');editGoal('Newer task B');editEvidence('Reviewed B evidence');
gates[0].resolve({...result(),token:handoffRequest('source-a').token});await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert.strictEqual($('handoff-goal').value,'Newer task B');
assert.strictEqual($('handoff-text').value,'Reviewed B evidence');assert.strictEqual($('handoff-cwd').value,'/project/b');
''')
    def test_old_failure_cannot_write_into_reopened_new_source_editor(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();$('preview-close').onclick();
await showHandoff('source-b','/project/b');editGoal('Newer B');gates[0].reject(Error('Source A start failed'));await pending;
assert(preview.open);assert($('handoff-error').hidden);assert.strictEqual($('handoff-goal').value,'Newer B');assert.deepStrictEqual(opened,[]);
''')
    def test_direct_repeat_activation_admits_one_task(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();const repeat=submit();
assert.strictEqual(calls.filter(c=>c.path==='/api/handoff/start').length,1);gates[0].resolve(result());await pending;await repeat;
assert.deepStrictEqual(opened,['created-a']);
''')

    def test_later_edits_after_submit_remain_unsent_with_created_task_status(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Submitted A');const pending=submit();
editGoal('Newer unsent A');editEvidence('Newer A evidence');$('handoff-cwd').value='/new/cwd';
gates[0].resolve(result());await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert.strictEqual($('handoff-goal').value,'Newer unsent A');
assert.strictEqual($('handoff-text').value,'Newer A evidence');assert.strictEqual($('handoff-cwd').value,'/new/cwd');
assert.strictEqual(calls.find(c=>c.path==='/api/handoff/start').data.cwd,'/project/a');
assert(!$('handoff-status').hidden);assert.match($('handoff-status').textContent,/later edits have not been sent/);
assert.strictEqual(handoffGoals.get('source-a'),'Newer unsent A');assert.strictEqual(handoffEvidence.get('source-a'),'Newer A evidence');
''')
    def test_reopened_same_source_serializes_submit_and_unlocks_its_new_editor(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();$('preview-close').onclick();
await showHandoff('source-a','/project/a');editGoal('Reopened A');assert($('handoff-start').disabled);
const repeat=submit();assert.strictEqual(calls.filter(c=>c.path==='/api/handoff/start').length,1);
gates[0].resolve(result());await pending;await repeat;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert($('handoff-start').disabled);assert(!$('handoff-new').disabled);assert.strictEqual($('handoff-goal').value,'Reopened A');
''')
    def test_current_failure_retains_retry_and_explicit_retry_opens_only_accepted_task(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Retry A');const pending=submit();gates[0].reject(Error('Start failed'));await pending;
assert(preview.open);assert(!$('handoff-error').hidden);assert.strictEqual($('handoff-error').textContent,'Start failed');
assert($('handoff-start').disabled);assert(!$('handoff-retry').disabled);assert.strictEqual($('handoff-goal').value,'Retry A');
const retry=$('handoff-retry').onclick();gates[1].resolve(result('created-retry'));await retry;assert.deepStrictEqual(opened,['created-retry']);assert(!preview.open);
''')
    def test_competing_evidence_reads_keep_latest_selected_source(self):
        self.check(r'''
const readA=deferred(),readB=deferred();api=async(path,data)=> data.thread==='source-a'?await readA.promise:await readB.promise;
const a=showHandoff('source-a','/project/a');const b=showHandoff('source-b','/project/b');
readB.resolve({text:'B original'});await b;editGoal('B edit');readA.resolve({text:'A original'});await a;
assert(preview.open);assert.strictEqual(handoffSource,'source-b');assert.strictEqual($('handoff-text').value,'B original');assert.strictEqual($('handoff-goal').value,'B edit');
''')

    def test_queued_old_close_event_does_not_cancel_immediate_reopen_read(self):
        self.check(r'''
await showHandoff('source-a','/project/a');
let delayedClose;preview.close=()=>{preview.open=false;delayedClose=()=>{for(const f of listeners.get('close')||[])f();};};
$('preview-close').onclick();const next=showHandoff('source-b','/project/b');delayedClose();await next;
assert(preview.open);assert.strictEqual(handoffSource,'source-b');assert.strictEqual($('handoff-cwd').value,'/project/b');
''')

    def test_first_start_captures_uuid_source_scope_and_body_before_native_send(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Exact reviewed goal');editEvidence('Private evidence');$('handoff-profile').value='reviewed-profile';
assert.strictEqual(tokenCount,0);const pending=submit();
const sent=calls.find(c=>c.path==='/api/handoff/start').data;
assert.deepStrictEqual(sent,{token,source:'source-a',cwd:'/project/a',profile:'reviewed-profile',goal:'Exact reviewed goal',text:'Private evidence'});
assert(Object.isFrozen(sent));assert.strictEqual(tokenCount,1);
assert.deepStrictEqual(JSON.parse(storage.get(handoffTokenKey)),{'source-a':token});
assert.strictEqual(storage.size,1);assert(![...storage.values()].some(v=>v.includes('Private evidence') || v.includes('Exact reviewed goal') || v.includes('/project/a') || v.includes('reviewed-profile')));
gates[0].resolve(result());await pending;
''')

    def test_lost_reply_exact_retry_never_captures_changed_editor(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Original goal');editEvidence('Original evidence');const pending=submit();
gates[0].reject(Error('Local response lost'));await pending;
const original=calls.find(c=>c.path==='/api/handoff/start').data;
editGoal('New unsent goal');editEvidence('New unsent evidence');$('handoff-cwd').value='/new/project';$('handoff-profile').value='new-profile';$('handoff-goal').focus();
await submit();assert.strictEqual(gates.length,1);assert($('handoff-new').disabled);
const retry=$('handoff-retry').onclick();assert.strictEqual(gates.length,2);
assert.strictEqual(calls.filter(c=>c.path==='/api/handoff/start')[1].data,original);assert.strictEqual(tokenCount,1);
gates[1].resolve(result());await retry;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert.strictEqual($('handoff-goal').value,'New unsent goal');assert.strictEqual($('handoff-profile').value,'new-profile');
assert.strictEqual(document.activeElement,$('handoff-goal'));assert.match($('handoff-status').textContent,/later edits have not been sent/);
assert(!$('handoff-open').hidden);await $('handoff-open').onclick();assert.deepStrictEqual(opened,['created-a']);
''')

    def test_opaque_token_cold_recovery_is_read_only_and_requires_explicit_open(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Lost original goal');const pending=submit();savedResult=result();gates[0].reject(Error('Reply lost'));await pending;$('preview-close').onclick();
handoffRequests.clear();handoffGoals.clear();handoffEvidence.clear();handoffScopes.clear();handoffEdits.clear();
const offset=calls.length;await showHandoff('source-a','/project/a');
assert.strictEqual(handoffRequest('source-a').body,null);assert.strictEqual($('handoff-goal').value,'');assert($('handoff-retry').hidden);assert($('handoff-start').disabled);
assert.strictEqual(calls.slice(offset).filter(c=>c.path.startsWith('/api/handoff/request?')).length,1);assert(!calls.slice(offset).some(c=>c.path==='/api/handoff/start'));
editGoal('Visible cold task');await submit();await $('handoff-retry').onclick();assert.strictEqual(gates.length,1);
const readOffset=calls.length;await $('handoff-recover').onclick();assert.deepStrictEqual(calls.slice(readOffset),[{path:'/api/handoff/request?token='+token,data:undefined}]);
assert.deepStrictEqual(opened,[]);assert(preview.open);assert.strictEqual($('handoff-goal').value,'Visible cold task');
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['created-a']);
''')

    def test_http_200_unknown_receipt_stays_blocked_until_exact_review(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Original unknown task');const pending=submit();savedResult=result('retained-unknown','unknown');gates[0].resolve(savedResult);await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert($('handoff-start').disabled);assert($('handoff-new').disabled);assert($('handoff-retry').hidden);
assert.match($('handoff-status').textContent,/Start unconfirmed/);editGoal('Changed unsent task');
await submit();$('handoff-new').onclick();await $('handoff-retry').onclick();await $('handoff-recover').onclick();assert.strictEqual(gates.length,1);assert.strictEqual(tokenCount,1);
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['retained-unknown']);
savedResult={...savedResult,handoff:{status:'needs_review',admission:{outcome:'rejected'}},preparation:{entries:[],reservation:null}};
await showHandoff('source-a','/project/a');assert(!$('handoff-new').disabled);assert.match($('handoff-status').textContent,/Start rejected/);
$('handoff-new').onclick();assert(!$('handoff-start').disabled);assert.strictEqual($('handoff-goal').value,'Changed unsent task');assert.strictEqual(tokenCount,1);
const newStart=submit();assert.strictEqual(tokenCount,2);assert.notStrictEqual(calls.filter(c=>c.path==='/api/handoff/start')[1].data.token,token);
gates[1].resolve(result('new-task'));await newStart;
''')

    def test_known_rejection_exposes_same_target_preparation_not_another_post(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Known rejected task');const pending=submit();gates[0].resolve(result('prepared-target','rejected'));await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert.match($('handoff-status').textContent,/Start rejected/);assert($('handoff-retry').hidden);
await submit();await $('handoff-retry').onclick();assert.strictEqual(gates.length,1);
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['prepared-target']);
''')

    def test_pending_retained_target_and_unproven_200_are_not_success(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();gates[0].resolve({id:'pending-target',token,handoff:{status:'pending'},preparation:{entries:[],reservation:{state:'reserved'}}});await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert($('handoff-new').disabled);assert.match($('handoff-status').textContent,/receipt pending/);
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['pending-target']);
await showHandoff('source-b','/project/b');const unproven=submit();gates[1].resolve({id:'unproven-target',token:handoffRequest('source-b').token,handoff:{status:'accepted'},preparation:{entries:[],reservation:null}});await unproven;
assert(preview.open);assert.deepStrictEqual(opened,['pending-target']);assert($('handoff-new').disabled);assert.match($('handoff-status').textContent,/No completed start receipt/);
''')

    def test_changed_scope_conflict_preserves_editor_and_original_target(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Submitted body');const pending=submit();
editGoal('Newer editor body');$('handoff-profile').value='new-profile';$('handoff-cwd').value='/different/cwd';
const conflict=Object.assign(Error('Different reviewed work'),{status:409,current:result('original-target')});gates[0].reject(conflict);await pending;
assert(preview.open);assert.deepStrictEqual(opened,[]);assert.strictEqual($('handoff-goal').value,'Newer editor body');assert.strictEqual($('handoff-profile').value,'new-profile');assert.strictEqual($('handoff-cwd').value,'/different/cwd');
assert($('handoff-retry').hidden);assert(!$('handoff-open').hidden);assert.match($('handoff-status').textContent,/different reviewed work/);
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['original-target']);
''')

    def test_no_target_validation_failure_requires_explicit_corrected_new_request(self):
        self.check(r'''
await showHandoff('source-a','/missing/project');editGoal('Reviewed task');const pending=submit();gates[0].reject(Object.assign(Error('Project not found'),{status:400}));await pending;
$('handoff-cwd').value='/correct/project';await submit();assert.strictEqual(gates.length,1);assert($('handoff-new').disabled);
readFailure=Object.assign(Error('No saved target'),{status:404});await $('handoff-recover').onclick();assert(!$('handoff-new').disabled);
assert.strictEqual(handoffRequest('source-a').body.cwd,'/missing/project');assert.strictEqual($('handoff-cwd').value,'/correct/project');
$('handoff-new').onclick();assert(!storage.get(handoffTokenKey).includes(token));assert.strictEqual(tokenCount,1);assert.strictEqual(gates.length,1);
const corrected=submit();const bodies=calls.filter(c=>c.path==='/api/handoff/start').map(c=>c.data);assert.notStrictEqual(bodies[1].token,bodies[0].token);assert.strictEqual(bodies[1].cwd,'/correct/project');
gates[1].resolve(result('corrected-target'));await corrected;assert.deepStrictEqual(opened,['corrected-target']);
''')

    def test_old_receipt_after_refresh_wait_cannot_close_newer_navigation(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Submitted A');const heldRefresh=deferred();refresh=async()=>{++refreshes;await heldRefresh.promise;};
const pending=submit();gates[0].resolve(result());while(!refreshes)await Promise.resolve();$('preview-close').onclick();
await showHandoff('source-b','/project/b');editGoal('Newer B');$('handoff-goal').focus();heldRefresh.resolve();await pending;
assert(preview.open);assert.strictEqual(handoffSource,'source-b');assert.strictEqual($('handoff-goal').value,'Newer B');assert.deepStrictEqual(opened,[]);assert.strictEqual(document.activeElement,$('handoff-goal'));
''')

    def test_older_pending_read_cannot_replace_later_accepted_start_receipt(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();const heldRead=deferred(),previousApi=api;
api=async(path,data)=>path.startsWith('/api/handoff/request?')?await heldRead.promise:await previousApi(path,data);
const recovery=$('handoff-recover').onclick();gates[0].resolve(result());await pending;
heldRead.resolve({id:'created-a',token,handoff:{status:'pending'},preparation:{entries:[],reservation:{state:'reserved'}}});await recovery;
assert(handoffAccepted(handoffRequest('source-a').result));assert.deepStrictEqual(opened,['created-a']);
''')

    def test_source_evidence_failure_does_not_hide_retained_request_review(self):
        self.check(r'''
await showHandoff('source-a','/project/a');const pending=submit();savedResult=result();gates[0].reject(Error('Reply lost'));await pending;$('preview-close').onclick();
handoffRequests.clear();const previousApi=api;api=async(path,data)=>{if(path==='/api/handoff')throw Error('Original evidence unavailable');return previousApi(path,data);};
await showHandoff('source-a','/project/a');assert(preview.open);assert.strictEqual(handoffRequest('source-a').body,null);assert(!$('handoff-open').hidden);
assert.strictEqual($('handoff-text').value,'');assert(!$('handoff-error').hidden);assert.strictEqual($('handoff-error').textContent,'Original evidence unavailable');
await $('handoff-open').onclick();assert.deepStrictEqual(opened,['created-a']);assert.strictEqual(gates.length,1);
''')

    def test_later_scope_edit_keeps_all_source_preparation_when_reopened(self):
        self.check(r'''
await showHandoff('source-a','/project/a');editGoal('Reviewed goal');editEvidence('Reviewed evidence');const pending=submit();
$('handoff-cwd').value='/later/cwd';$('handoff-cwd').oninput();$('handoff-profile').value='later-profile';$('handoff-profile').onchange();
gates[0].resolve(result());await pending;assert(preview.open);$('preview-close').onclick();
await showHandoff('source-a','/project/a');assert.strictEqual($('handoff-goal').value,'Reviewed goal');assert.strictEqual($('handoff-text').value,'Reviewed evidence');assert.strictEqual($('handoff-cwd').value,'/later/cwd');assert.strictEqual($('handoff-profile').value,'later-profile');
assert.deepStrictEqual(opened,[]);assert.match($('handoff-status').textContent,/later edits have not been sent/);
''')

if __name__=='__main__':unittest.main()
