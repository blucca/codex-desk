"""Execute the shipped ordinary Run controller with private receipt/DOM fixtures."""
import json
import subprocess
import unittest

from test_navigation_controllers import APP, DOM, NODE

SETUP = DOM[:DOM.index('let state=')] + r'''
const clone=value=>JSON.parse(JSON.stringify(value));
let uuidCount=0;const crypto={randomUUID:()=>`00000000-0000-4000-8000-${String(++uuidCount).padStart(12,'0')}`};
const storage=new Map(COLD ? [['codex-desk-turn-requests',JSON.stringify([{session:'a',token:'00000000-0000-4000-8000-000000000077'}])]]:[]);
const sessionStorage={getItem:key=>storage.get(key)??null,setItem:(key,value)=>storage.set(key,value)};
const localStorage={setItem(){},getItem(){return null;}};
const window={addEventListener(){}};
const timers=new Map();let timerId=0;const setTimeout=callback=>{timers.set(++timerId,callback);return timerId;};const clearTimeout=id=>timers.delete(id);
const frames=[];const requestAnimationFrame=f=>frames.push(f);
const archiving=new Set(),profileLabel=()=> 'Native';
const DeskHome={sync(){},selectionChanged(){}},DeskRecall={stateChanged(){},selectionChanged(){}};
const queues=[{id:'paused-one',mode:'native',text:'Paused Work — exact  '},{id:'paused-two',mode:'plan',text:'Paused Plan — 保留  '}];
const DeskFollowups={status(id,busy){$('followup-send').disabled=busy;},blocked(){return false;},refresh(){},select(){},add(){throw Error('Run cannot use followup admission');}};
const DeskNativeState={usage(){return '';},card(){throw Error('No native failure');}};
function drawSidebar(){}function syncSelectedOriginal(){}function drawProfiles(){}function approvals(){}
function nearLatest(){return false;}function latestLabel(){}function goLatest(){throw Error('Recovery must not move viewport');}
function renderItem(){}
const calls=[],control={};let starts=0;
const world={draft:{text:'  Exact ordinary Plan — 保留  ',mode:'plan',revision:1},writer:'previous-page',sequence:0,receipt:null};
const sessions=[{id:'a',cwd:'/retained/project',profile:'default',thread_id:'native-a',status:'ready'}];
function receipt(data,status){return {session:data.session,token:data.token,request:{status,payload:clone(data),draft:clone(world.draft)}};}
function accept(data){
  ++starts;
  if(world.draft.text===data.text && world.draft.mode===data.mode && world.draft.revision===data.revision && world.writer===data.writer && world.sequence===data.sequence)world.draft={text:'',mode:data.mode,revision:data.revision+1};
  world.receipt=receipt(data,'accepted');world.receipt.request.turn={turn:{id:'turn-'+starts}};return clone(world.receipt);
}
async function api(path,data){
  calls.push({path,data:data===undefined?null:clone(data)});
  if(path==='/api/state')return {sessions:clone(sessions),profiles:[]};
  if(path.startsWith('/api/stop?'))throw Object.assign(Error('No saved Stop request'),{status:404});
  if(path.startsWith('/api/events?'))return control.events || [];
  if(path.startsWith('/api/draft?'))return clone(world.draft);
  if(path==='/api/draft'){
    assert.equal(data.session,'a');
    if(world.writer===data.writer && data.sequence>world.sequence && data.revision<world.draft.revision){}
    else assert.equal(data.revision,world.draft.revision);
    world.draft={text:data.text,mode:data.mode,revision:world.draft.revision+1};world.writer=data.writer;world.sequence=data.sequence;
    const saved=clone(world.draft);if(control.save)await control.save(saved);return saved;
  }
  if(path==='/api/turn'){
    if(world.receipt && world.receipt.token===data.token){
      const original=world.receipt.request.payload;
      for(const key of ['session','token','text','mode','revision','writer','sequence'])assert.equal(data[key],original[key]);
      if(!data.retry)return clone(world.receipt);
      assert.equal(world.receipt.request.status,'rejected');
    }
    return control.turn?control.turn(data):accept(data);
  }
  if(path.startsWith('/api/turn/request?')){
    if(control.read)return control.read(path);
    if(!world.receipt)throw Object.assign(Error('No retained request'),{status:404});
    const result=clone(world.receipt);result.request.draft=clone(world.draft);return result;
  }
  if(path==='/api/turn/resolve'){
    assert.equal(world.receipt.request.status,'needs_review');assert.equal(data.token,world.receipt.token);
    world.receipt.request.status=data.outcome;world.receipt.request.draft=clone(world.draft);return clone(world.receipt);
  }
  throw Error('Unexpected controller endpoint '+path);
}
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{for(let i=0;i<20;i++)await Promise.resolve();};
const submit=()=>$('task').onsubmit({preventDefault(){}});
function edit(text,mode='plan'){$('prompt').value=text;$('turn-mode').value=mode;rememberDraft('a');scheduleDraft('a');}
const posts=()=>calls.filter(c=>c.path==='/api/turn');
'''


@unittest.skipUnless(NODE, 'Node is required for ordinary Run controller contracts')
class TurnRequestControllerTests(unittest.TestCase):
    def check(self, body, *, cold=False, real_followups=False):
        source = APP.read_text()
        fragments = []
        for begin, end in [('let state =', 'function nearLatest('),
                           ('function activeSession(', 'function sidebarGroups('),
                           ('let selectedOriginalReview=', 'function selectedOriginalCurrent('),
                           ('function draw()', 'function itemText('),
                           ('function syncInteractionCards(', 'function consume(m)'),
                           ('function consume(m)', 'async function refresh()'),
                           ('async function refresh()', 'function profileInfo()'),
                           ("$('task').onsubmit=", "let failures=0;"),
                           ('async function pollActivity()', 'async function tick()')]:
            fragments.append(source[source.index(begin):source.index(end)])
        setup = SETUP.replace('COLD', json.dumps(cold))
        configuration = ''
        if real_followups:
            begin = setup.index('const DeskFollowups=')
            end = setup.index('const DeskNativeState=', begin)
            setup = setup[:begin] + 'document.getElementById=$;\n' + (APP.parent / 'followups.js').read_text() + '\n' + setup[end:]
            setup = setup.replace("  if(path==='/api/state')", "  if(path.startsWith('/api/followups?'))return {entries:queues.map((entry,index)=>({...entry,order:index+1,revision:1,state:'queued'})),reservation:null};\n  if(path==='/api/state')", 1)
            configuration = next(line for line in source.splitlines() if line.startswith('DeskFollowups.configure(')) + '\n'
        presenter = (APP.parent / 'preparation.js').read_text().split('/* Local preparation review;')[0]
        presenter += (APP.parent / 'evidence-preparation.js').read_text()
        fragments.append(source[source.index('let preparedEvidenceOwner='):source.index('DeskEvidencePreparation.configure(')])
        native_readouts = 'const interactionCards=new Map();\n' + (APP.parent / 'native-steps.js').read_text() + '\nDeskNativeSteps.configure({$,make});\n'
        native_readouts += (APP.parent / 'turn-changes.js').read_text() + '\nDeskTurnChanges.configure({$,writeText:async()=>{}});\nconst DeskSteering={select(){},sync(){},consume(){},restoreThread(){},opened(){},reading:()=>false};\n'
        native_readouts += (APP.parent / 'stop-task.js').read_text() + '\n'
        configuration += next(line for line in source.splitlines() if line.startswith('DeskStopTask.configure(')) + '\n'
        code = setup + '\n' + native_readouts + presenter + '\n' + '\n'.join(fragments) + '\n' + configuration + r'''
(async()=>{
state={sessions:clone(sessions),profiles:[]};
''' + ('' if cold else "selected='a';generation=7;nativeThreadId='native-a';await loadDraft('a',generation);draw();\n") + body + r'''
assert.deepStrictEqual(queues,[{id:'paused-one',mode:'native',text:'Paused Work — exact  '},{id:'paused-two',mode:'plan',text:'Paused Plan — 保留  '}]);
assert(!calls.some(c=>c.data && /^\/api\/(followups|handoff|sessions|import)/.test(c.path)));
process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exit(1);});
'''
        result = subprocess.run([NODE], input=code, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_normal_acceptance_clears_exact_and_same_words_new_edit_gets_fresh_token(self):
        self.check(r'''
const text=$('prompt').value;$('prompt').focus();await submit();
assert.equal(starts,1);assert.equal($('prompt').value,'');assert.equal(world.draft.text,'');assert(!turnRequest());
assert.equal(posts()[0].data.writer,draftWriter);assert.equal(posts()[0].data.sequence,0);assert.equal(posts()[0].data.revision,2);
assert.equal(calls.filter(c=>c.path==='/api/draft').length,1);assert.equal($('send').textContent,'Run task');assert($('prompt').required);
assert.equal(document.activeElement,$('prompt'));edit(text);await submit();assert.equal(starts,2);
assert.notEqual(posts()[0].data.token,posts()[1].data.token);assert.equal(posts()[1].data.text,text);
''')

    def test_lost_local_response_repeated_run_only_get_recovers_original(self):
        self.check(r'''
control.turn=data=>{accept(data);throw Error('Lost local reply');};await submit();
const request=turnRequest();assert(request);assert.equal(starts,1);assert.equal($('send').textContent,'Check Run request');
const stored=JSON.parse(storage.get(turnRequestKey));assert.deepEqual(stored,[{session:'a',token:posts()[0].data.token}]);
assert(!storage.get(turnRequestKey).includes('Exact'));assert(!storage.get(turnRequestKey).includes('revision'));
await submit();assert.equal(starts,1);assert.equal(posts().length,1);assert.equal($('prompt').value,'');assert(!turnRequest());
''')

    def test_held_response_newer_text_mode_selection_focus_and_paused_queues_survive(self):
        self.check(r'''
const held=deferred();control.turn=data=>{const result=accept(data);return held.promise.then(()=>result);};
const pending=submit();await settle();assert.equal(starts,1);edit('Newer exact unsent Plan — 保留  ','plan');await persistDraft('a');
$('prompt').selectionStart=3;$('prompt').selectionEnd=9;$('prompt').focus();$('history-reader').open=true;
held.resolve(clone(world.receipt));await pending;
assert.equal($('prompt').value,'Newer exact unsent Plan — 保留  ');assert.equal($('turn-mode').value,'plan');
assert.equal($('prompt').selectionStart,3);assert.equal($('prompt').selectionEnd,9);assert.equal(document.activeElement,$('prompt'));assert($('history-reader').open);
assert.equal(turnRequest().status,'accepted');const count=posts().length;await submit();assert.equal(posts().length,count);assert.equal(starts,1);
$('turn-request-new').onclick();assert(!turnRequest());assert.equal($('prompt').value,'Newer exact unsent Plan — 保留  ');assert.equal(posts().length,count);
''')

    def test_pending_duplicates_preserve_one_identity_and_read_before_new_task(self):
        self.check(r'''
control.turn=data=>{world.receipt=receipt(data,'pending');return clone(world.receipt);};await submit();
const token=turnRequest().token;await submit();await $('turn-request-recover').onclick();
assert.equal(posts().length,1);assert.equal(turnRequest().token,token);assert($('followup-send').disabled);
const original=world.receipt.request.payload;world.receipt=accept(original);await submit();assert(!turnRequest());assert.equal(starts,1);
''')

    def test_rejected_original_retry_preserves_newer_editor_and_new_task_is_separate(self):
        self.check(r'''
control.turn=data=>{world.receipt=receipt(data,'rejected');return clone(world.receipt);};await submit();
const original=clone(posts()[0].data);edit('Different newer task','native');await persistDraft('a');
control.turn=data=>accept(data);await $('turn-request-retry').onclick();
assert.deepEqual(posts()[1].data,{...original,retry:true});assert.equal(starts,1);assert.equal($('prompt').value,'Different newer task');assert.equal($('turn-mode').value,'native');
$('turn-request-new').onclick();assert.equal(posts().length,2);await submit();assert.equal(starts,2);assert.notEqual(posts()[2].data.token,original.token);assert.equal(posts()[2].data.text,'Different newer task');
''')

    def test_actual_followup_refresh_keeps_run_get_enabled_and_send_next_blocked(self):
        self.check(r'''
DeskFollowups.select('a');await settle();draw();
control.turn=data=>{world.receipt=receipt(data,'needs_review');return clone(world.receipt);};await submit();
assert.equal($('send').textContent,'Check Run request');assert(!$('send').disabled);assert($('followup-send').disabled);
await DeskFollowups.refresh('a');assert(!$('send').disabled);assert($('followup-send').disabled);
const count=posts().length;await submit();assert.equal(posts().length,count);assert(!$('send').disabled);assert($('followup-send').disabled);
''', real_followups=True)

    def test_unknown_explicit_review_never_resends_then_retry_is_deliberate(self):
        self.check(r'''
control.turn=data=>{world.receipt=receipt(data,'needs_review');return clone(world.receipt);};await submit();
const token=turnRequest().token;assert(!$('turn-request-accepted').hidden);assert(!$('turn-request-rejected').hidden);assert($('followup-send').disabled);
await submit();$('turn-request-new').onclick();await $('turn-request-retry').onclick();assert.equal(posts().length,1);assert.equal(turnRequest().token,token);
await $('turn-request-rejected').onclick();assert.equal(turnRequest().status,'rejected');assert.equal(posts().length,1);assert.equal(starts,0);
control.turn=data=>accept(data);await $('turn-request-retry').onclick();assert.equal(posts().length,2);assert.equal(posts()[1].data.token,token);assert(posts()[1].data.retry);
''')

    def test_same_words_newer_revision_never_clear_by_body_similarity(self):
        self.check(r'''
const text=$('prompt').value,held=deferred();control.turn=data=>{const result=accept(data);return held.promise.then(()=>result);};
const pending=submit();await settle();edit('Changed preparation','native');edit(text,'plan');await persistDraft('a');
$('prompt').selectionStart=5;$('prompt').selectionEnd=12;$('prompt').focus();held.resolve(clone(world.receipt));await pending;
assert.equal($('prompt').value,text);assert.equal(world.draft.text,text);assert.equal(turnRequest().status,'accepted');assert.equal($('prompt').selectionStart,5);assert.equal(document.activeElement,$('prompt'));
await submit();assert.equal(posts().length,1);
''')

    def test_cold_retained_rejected_reads_without_attach_and_retries_private_original(self):
        self.check(r'''
const token='00000000-0000-4000-8000-000000000077';
const original={session:'a',token,text:'Private old task',mode:'native',revision:1,writer:'old-page',sequence:4};
world.receipt=receipt(original,'rejected');world.draft={text:'Cold newer exact Plan — 保留  ',mode:'plan',revision:4};
await open('a');assert.equal(posts().length,0);assert(calls.every(c=>!c.data));assert(!calls.some(c=>c.path==='/api/open'));
assert.equal($('prompt').value,'Cold newer exact Plan — 保留  ');assert.equal(turnRequest().body.text,'Private old task');
assert.equal(nativeThreadId,'native-a');assert.equal(frames.length,0);
await $('turn-request-retry').onclick();assert.deepEqual(posts()[0].data,{...original,retry:true});assert.equal(starts,1);assert.equal($('prompt').value,'Cold newer exact Plan — 保留  ');
assert(!storage.get(turnRequestKey).includes('Private old task'));
''', cold=True)

    def test_cold_accepted_blank_receipt_retires_and_next_run_is_deliberate(self):
        self.check(r'''
const token='00000000-0000-4000-8000-000000000077',original={session:'a',token,text:'Same words',mode:'plan',revision:2,writer:'old',sequence:3};
world.draft={text:'',mode:'plan',revision:3};world.receipt=receipt(original,'accepted');await open('a');
assert(calls.every(c=>!c.data));assert.equal($('prompt').value,'');assert(!turnRequest());edit('Same words');await submit();assert.equal(starts,1);assert.notEqual(posts()[0].data.token,token);
''', cold=True)

    def test_edits_back_to_same_words_during_cold_receipt_read_are_not_cleared(self):
        self.check(r'''
const token='00000000-0000-4000-8000-000000000077',text=world.draft.text;
const original={session:'a',token,text,mode:'plan',revision:1,writer:'old',sequence:3};
const held=deferred();control.read=()=>held.promise;
const openingTask=open('a');await settle();edit('Different cold edit','native');edit(text,'plan');$('prompt').focus();$('prompt').selectionStart=4;
world.draft={text:'',mode:'plan',revision:2};world.receipt=receipt(original,'accepted');held.resolve(clone(world.receipt));await openingTask;
assert.equal($('prompt').value,text);assert.equal($('prompt').selectionStart,4);assert.equal(document.activeElement,$('prompt'));assert.equal(turnRequest().status,'accepted');assert.equal(posts().length,0);
''', cold=True)

    def test_cold_absent_token_stays_retained_get_only_and_cannot_retry_or_replace(self):
        self.check(r'''
await open('a');assert(turnRequest().notFound);assert.equal(posts().length,0);await submit();await $('turn-request-retry').onclick();$('turn-request-new').onclick();
assert(turnRequest());assert(calls.every(c=>!c.data));assert.equal($('prompt').value,world.draft.text);assert.equal(frames.length,0);
''', cold=True)

    def test_fresh_page_conflict_recovers_older_authoritative_identity_not_new_editor(self):
        self.check(r'''
const original={session:'a',token:'00000000-0000-4000-8000-000000000077',text:'Original unresolved task',mode:'native',revision:1,writer:'prior',sequence:1};
world.receipt=receipt(original,'needs_review');edit('Newer unsent exact Plan — 保留  ');$('prompt').focus();$('prompt').selectionStart=2;$('prompt').selectionEnd=6;
control.turn=data=>{throw Object.assign(Error('Review original'),{status:409,current:clone(world.receipt)});};await submit();
assert.equal(turnRequest().token,original.token);assert.equal(turnRequest().status,'needs_review');assert.equal(turnRequest().body.text,original.text);
assert.equal($('prompt').value,'Newer unsent exact Plan — 保留  ');assert.equal($('prompt').selectionStart,2);assert.equal(document.activeElement,$('prompt'));
assert.deepEqual(JSON.parse(storage.get(turnRequestKey)),[{session:'a',token:original.token}]);assert.equal(posts().length,1);assert.equal(starts,0);
await $('turn-request-rejected').onclick();assert.equal(turnRequest().status,'rejected');assert.equal(posts().length,1);
''')

    def test_newer_edit_while_identifying_save_is_not_dispatched(self):
        self.check(r'''
const held=deferred();control.save=()=>held.promise;const pending=submit();await settle();edit('Newer while identify save waits','native');
held.resolve();await pending;assert.equal(posts().length,0);assert(!turnRequest());assert.equal($('prompt').value,'Newer while identify save waits');
assert.match($('draft-status').textContent,/Newer edits remain unsent/);
''')


if __name__ == '__main__':
    unittest.main()
