"""Exercise shipped independent Prepared ordinary request review and late replies."""
import subprocess
import unittest

from test_preparation_controller import HARNESS, NODE, ROOT


SETUP = HARNESS[:HARNESS.index('(async()=>{')]
SETUP = SETUP.replace('.filter(row=>row.draft.text||row.followups.entries.length||row.followups.reservation)',
                      '.filter(row=>row.draft.text||row.followups.entries.length||row.followups.reservation||row.turn_request)')
SETUP = SETUP.replace('DeskPreparation.configure({api,', r'''
const token=id=>'00000000-0000-4000-8000-'+({r:'000000000101',s:'000000000102'})[id];
const original=id=>({session:id,native_home:'/native/original',cwd:'/projects/requests',profile:'old-profile',thread_id:'native-'+id});
const long='  <script>literal captured Work/Plan — 保留</script>\n'+('Exact captured instructions.\n'.repeat(900))+'  Tail stays exact  ';
const requests={};
for(const [id,mode] of [['r','plan'],['s','native']]){
  world[id]={id,name:'Request '+id,cwd:'/projects/requests',profile:'old-profile',archived:id==='s',status:'failed',
    draft:{text:'',mode:'native',revision:0},followups:{entries:[],reservation:null},
    turn_request:{token:token(id),status:'pending',mode,binding:original(id)}};
  const body={session:id,token:token(id),text:long,mode,revision:1,writer:'captured-page',sequence:1};
  requests[id]={session:id,token:token(id),request:{status:'needs_review',payload:body,binding:original(id),current_binding:original(id),binding_mismatch:false}};
}
let navigationIdentity='selected-b:1';
const baseApi=api;
api=async(path,data)=>{
  if(path.startsWith('/api/turn/request?')){
    calls.push({path,data:null});
    const q=new URL(path,'http://local.invalid').searchParams,id=q.get('session');assert.equal(q.get('token'),token(id));
    if(control.failRequest)throw Error('Request temporarily unavailable');
    const result=clone(requests[id]);return control.request?control.request(path,result):result;
  }
  if(path==='/api/turn/resolve'){
    calls.push({path,data:clone(data)});const request=requests[data.session];
    assert.equal(data.token,request.token);assert.equal(request.request.status,'needs_review');
    if(control.rejectResolve)throw control.rejectResolve;
    request.request.status=data.outcome;request.request.reviewed=true;delete world[data.session].turn_request;
    const current=world[data.session].draft,body=request.request.payload;
    if(data.outcome==='accepted' && current.text===body.text && current.mode===body.mode && current.revision===body.revision)
      world[data.session].draft={text:'',mode:body.mode,revision:current.revision+1};
    return control.resolve?control.resolve(data,clone(request)):clone(request);
  }
  return baseApi(path,data);
};
const mainText=new Element('textarea'),mainMode=new Element('select');document.body.append(mainText,mainMode);
mainText.value=activeDraft.text;mainText.selectionStart=3;mainText.selectionEnd=11;mainMode.value='plan';
const paused=clone(world.b.followups),req=id=>n('request'+(id?'-'+id:''));
const requestReview=id=>{
  const source=all(n('list')).find(e=>e.dataset.session===id&&e.dataset.control==='request');assert(source);source.focus();return source.click();
};
const resolvePosts=()=>calls.filter(c=>c.path==='/api/turn/resolve');
function unchanged(){
  assert.equal(mainText.value,activeDraft.text);assert.equal(mainMode.value,'plan');assert.equal(mainText.selectionStart,3);assert.equal(mainText.selectionEnd,11);
  assert.deepEqual(world.b.followups,paused);assert.equal(opened.length,0);assert.equal(saved.length,0);
  assert(calls.every(c=>!c.data || c.path==='/api/turn/resolve'),'Only explicit request resolution may write');
}
DeskPreparation.configure({api,navigationIdentity:()=>navigationIdentity,''', 1)


@unittest.skipUnless(NODE, 'Node is required for Prepared request controller contracts')
class PreparedRequestControllerTests(unittest.TestCase):
    def check(self, body):
        script = SETUP + '\n(async()=>{\nawait DeskPreparation.show();\n' + body + r'''
unchanged();console.log(JSON.stringify({passed:true,request_gets:calls.filter(c=>c.path.startsWith('/api/turn/request?')).length,resolves:resolvePosts().length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script, str(ROOT / 'codex_desk/static/preparation.js')],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"passed":true', result.stdout)

    def test_outer_close_restores_unchanged_origin_backward_range_and_scroll(self):
        self.check(r'''
await n('close').click();mainText.focus();mainText.setSelectionRange(3,11,'backward');mainText.scrollTop=190;
await DeskPreparation.show();await requestReview('r');await req('return').click();
const nativeClose=n('').close.bind(n(''));n('').close=()=>{mainText.focus();mainText.setSelectionRange(0,0,'forward');mainText.scrollTop=0;nativeClose();};
await n('close').click();assert(document.activeElement===mainText);assert.equal(mainText.selectionStart,3);assert.equal(mainText.selectionEnd,11);assert.equal(mainText.selectionDirection,'backward');assert.equal(mainText.scrollTop,190);
''')

    def test_outer_close_does_not_restore_selection_after_task_switch_or_new_input(self):
        self.check(r'''
await n('close').click();mainText.focus();mainText.setSelectionRange(3,11,'backward');await DeskPreparation.show();
navigationIdentity='selected-other:2';mainText.setSelectionRange(7,7,'forward');mainMode.focus();await n('close').click();
assert(document.activeElement===mainMode);assert.equal(mainText.selectionStart,7);
mainText.focus();await DeskPreparation.show();mainText.value='A newer input while modal is open';mainText.setSelectionRange(1,4,'forward');mainMode.focus();await n('close').click();
assert(document.activeElement===mainMode);assert.equal(mainText.selectionStart,1);assert.equal(mainText.selectionEnd,4);
mainText.value=activeDraft.text;mainText.setSelectionRange(3,11);navigationIdentity='selected-b:1';
''')

    def test_request_only_review_never_initializes_editor_or_opens_native(self):
        self.check(r'''
assert(sessions().includes('r'));assert(!sessions().includes('s'));assert(n('editor').hidden);
const row=all(n('list')).find(e=>e.className==='preparation-session'&&e.dataset.session==='r');
assert(!button(row,'Review draft and follow-ups'));assert.match(row.textContent,/Plan task request · Receipt pending/);
await requestReview('r');assert(n('editor').hidden);assert(req('').open);assert(n('').open);
assert.equal(req('captured-text').textContent,long);assert.equal(req('captured-title').textContent,'Captured Plan task');
assert(req('captured').open);assert.match(req('original-binding').textContent,/native-r/);assert.match(req('current-binding').textContent,/old-profile/);
assert(!req('accepted').hidden);assert(!req('accepted').disabled);assert.equal(resolvePosts().length,0);
assert(!calls.some(c=>c.path.startsWith('/api/draft')));assert(document.activeElement===req('title'));
await req('return').click();assert(!req('').open);assert.equal(document.activeElement.dataset.session,'r');assert.equal(document.activeElement.dataset.control,'request');
assert(!all(req('')).some(e=>e.tagName==='BUTTON'&&/Retry|new task|Open/.test(e.textContent)));
''')

    def test_both_row_choices_and_other_editor_caret_queues_survive_return_and_refresh(self):
        self.check(r'''
world.r.draft={text:'A newer saved Work task',mode:'native',revision:2};await n('refresh').click();
const row=all(n('list')).find(e=>e.className==='preparation-session'&&e.dataset.session==='r');assert(button(row,'Review draft and follow-ups'));assert(button(row,'Review task request'));
await review('b');fill('B exact unsaved Plan — 保留  ','plan');n('text').selectionStart=2;n('text').selectionEnd=9;n('text').scrollTop=77;n('').scrollTop=180;
await requestReview('r');assert.equal(n('text').value,'B exact unsaved Plan — 保留  ');assert.equal(n('mode').value,'plan');
assert.equal(req('captured-text').textContent,long);await req('refresh').click();await req('return').click();
assert.equal(n('text').value,'B exact unsaved Plan — 保留  ');assert.equal(n('text').selectionStart,2);assert.equal(n('text').selectionEnd,9);assert.equal(n('text').scrollTop,77);assert.equal(n('').scrollTop,180);
await n('refresh').click();assert.equal(n('text').selectionStart,2);assert.equal(n('text').selectionEnd,9);assert.equal(n('mode').value,'plan');assert.match(n('editor-title').textContent,/B next work/);
assert.equal(world.r.draft.text,'A newer saved Work task');
''')

    def test_check_preserves_long_text_disclosure_scroll_range_and_keyboard_focus(self):
        self.check(r'''
await requestReview('r');const pre=req('captured-text'),disclosure=req('captured');
const descriptor=Object.getOwnPropertyDescriptor(Element.prototype,'textContent');let writes=0;
Object.defineProperty(pre,'textContent',{get(){return descriptor.get.call(this);},set(value){++writes;descriptor.set.call(this,value);}});
pre.scrollTop=520;pre.selection='Exact selected read-only range';disclosure.open=false;pre.focus();
await req('refresh').click();assert.equal(writes,0);assert.equal(pre.scrollTop,520);assert.equal(pre.selection,'Exact selected read-only range');assert.equal(disclosure.open,false);assert(document.activeElement===pre);
await n('refresh').click();assert(document.activeElement===pre);assert.equal(writes,0);
disclosure.open=true;await req('refresh').click();assert.equal(pre.scrollTop,520);assert(disclosure.open);assert.equal(writes,0);
await req('return').click();await requestReview('r');assert.equal(writes,0);assert.equal(pre.scrollTop,520);assert(disclosure.open);
''')

    def test_accepted_refresh_reads_cleared_revision_and_preserves_unsaved_editor_conflict(self):
        self.check(r'''
world.r.draft={text:long,mode:'plan',revision:1};await n('refresh').click();await review('r');fill('R newer unsaved Work after capture','native');
await requestReview('r');req('accepted').focus();await req('accepted').click();
assert.equal(resolvePosts().length,1);assert.deepEqual(resolvePosts()[0].data,{session:'r',token:token('r'),outcome:'accepted'});
assert.equal(requests.r.request.status,'accepted');assert(!sessions().includes('r'));assert.equal(req('captured-text').textContent,long);
assert.equal(n('text').value,'R newer unsaved Work after capture');assert.equal(n('mode').value,'native');assert.equal(n('conflict').hidden,false);assert.equal(n('save').disabled,true);
assert(calls.some(c=>c.path==='/api/draft?session=r'));assert(document.activeElement===req('return'));
await req('return').click();assert(document.activeElement===n('refresh'));assert.equal(n('text').value,'R newer unsaved Work after capture');
assert.equal(world.r.draft.text,'');assert.equal(world.r.draft.revision,2);
''')

    def test_rejected_refresh_keeps_newer_draft_two_queues_and_exact_return_origin(self):
        self.check(r'''
world.r.draft={text:'R newer saved preparation',mode:'native',revision:2};world.r.followups=clone(world.b.followups);await n('refresh').click();
await review('b');fill('B unsaved remains Plan','plan');await requestReview('r');req('rejected').focus();await req('rejected').click();
assert.equal(resolvePosts().length,1);assert.equal(resolvePosts()[0].data.outcome,'rejected');assert(sessions().includes('r'));assert.equal(world.r.draft.text,'R newer saved preparation');assert.deepEqual(world.r.followups,paused);
assert.equal(n('text').value,'B unsaved remains Plan');assert.equal(n('conflict').hidden,true);assert(req('accepted').hidden);assert(req('rejected').hidden);
await req('return').click();assert(document.activeElement===n('refresh'));
const row=all(n('list')).find(e=>e.className==='preparation-session'&&e.dataset.session==='r');assert(button(row,'Review draft and follow-ups'));assert(!button(row,'Review task request'));
''')

    def test_binding_each_changed_dimension_blocks_resolution_and_retains_evidence(self):
        for key, value in [('native_home', '/native/changed'), ('cwd', '/projects/changed'),
                           ('profile', 'changed-profile'), ('thread_id', 'native-changed')]:
            with self.subTest(key=key):
                self.check(r'''
requests.r.request.current_binding.KEY='VALUE';requests.r.request.binding_mismatch=true;
await requestReview('r');assert(req('accepted').disabled);assert(req('rejected').disabled);assert.match(req('status').textContent,/targets differ/);
assert.equal(req('captured-text').textContent,long);assert(req('original-binding').textContent.includes(original('r').KEY));assert(req('current-binding').textContent.includes('VALUE'));
await req('accepted').onclick();await req('rejected').onclick();assert.equal(resolvePosts().length,0);
requests.r.request.current_binding=original('r');requests.r.request.binding_mismatch=false;await req('refresh').click();assert(!req('accepted').disabled);
'''.replace('KEY', key).replace('VALUE', value))

    def test_client_binding_comparison_blocks_false_mismatch_flag(self):
        self.check(r'''
requests.r.request.current_binding.profile='Changed despite flag';requests.r.request.binding_mismatch=false;
await requestReview('r');assert(req('accepted').disabled);await req('accepted').onclick();assert.equal(resolvePosts().length,0);
''')

    def test_resolution_conflict_updates_authoritative_current_target_without_replaying(self):
        self.check(r'''
await requestReview('r');requests.r.request.binding_mismatch=true;requests.r.request.current_binding.native_home='/native/latest';
control.rejectResolve=Object.assign(Error('Restore original target'),{status:409,current:clone(requests.r)});
await req('accepted').click();assert.equal(resolvePosts().length,1);assert(req('accepted').disabled);assert.match(req('current-binding').textContent,/native.latest/);assert.match(req('error').textContent,/Restore original target/);
assert.equal(requests.r.request.status,'needs_review');assert(sessions().includes('r'));await req('rejected').onclick();assert.equal(resolvePosts().length,1);
''')

    def test_late_get_old_activation_and_old_refresh_cannot_repaint_new_identity(self):
        self.check(r'''
n('archived').checked=true;await n('archived').onchange();const held=deferred();control.request=(path,result)=>path.includes('session=r')?held.promise:result;
const reading=requestReview('r');await settle();await req('return').click();await requestReview('s');assert.equal(req('captured-title').textContent,'Captured Work task');
held.resolve(clone(requests.r));await reading;assert.equal(req('identity').textContent,'Request ID: '+token('s'));assert.equal(req('captured-title').textContent,'Captured Work task');assert.match(req('original-binding').textContent,/native-s/);
control.request=null;await req('return').click();await requestReview('r');const old=deferred();let count=0;control.request=(path,result)=>++count===1?old.promise:result;
const first=req('refresh').click();await settle();requests.r.request.status='accepted';await req('refresh').click();assert.match(req('status').textContent,/Run accepted/);
const stale=clone(requests.r);stale.request.status='needs_review';old.resolve(stale);await first;assert.match(req('status').textContent,/Run accepted/);assert(req('accepted').hidden);
''')

    def test_same_identity_reopen_ignores_old_get_and_close_via_escape(self):
        self.check(r'''
const held=deferred();let count=0;control.request=(path,result)=>++count===1?held.promise:result;
const first=requestReview('r');await settle();req('').close();assert(document.activeElement.dataset.control==='request');
requests.r.request.status='accepted';await requestReview('r');const stale=clone(requests.r);stale.request.status='needs_review';held.resolve(stale);await first;
assert.match(req('status').textContent,/Run accepted/);assert(req('accepted').hidden);assert(req('').open);
''')

    def test_late_resolution_cannot_refresh_new_request_or_hide_other_editor(self):
        self.check(r'''
n('archived').checked=true;await n('archived').onchange();await review('b');fill('B latest Plan while resolving','plan');await requestReview('r');
const held=deferred();control.resolve=()=>held.promise;const resolving=req('rejected').click();await settle();assert(req('accepted').disabled);
await req('return').click();await requestReview('s');const overviews=calls.filter(c=>c.path.startsWith('/api/preparation?')).length;
held.resolve(clone(requests.r));await resolving;assert.equal(calls.filter(c=>c.path.startsWith('/api/preparation?')).length,overviews);
assert.equal(req('identity').textContent,'Request ID: '+token('s'));assert(!req('accepted').disabled);assert.equal(n('text').value,'B latest Plan while resolving');assert.equal(resolvePosts().length,1);
''')

    def test_failures_and_nonmatching_get_keep_exact_capture_and_require_fresh_read(self):
        self.check(r'''
await requestReview('r');control.failRequest=true;await req('refresh').click();assert(req('accepted').disabled);assert.equal(req('captured-text').textContent,long);assert.match(req('error').textContent,/temporarily unavailable/);
control.failRequest=false;control.request=()=>clone(requests.s);await req('refresh').click();assert(req('accepted').disabled);assert.match(req('error').textContent,/did not match/);assert.equal(req('captured-text').textContent,long);
control.request=(path,result)=>{result.request.payload.text='Changed captured text';return result;};await req('refresh').click();assert(req('accepted').disabled);assert.match(req('error').textContent,/captured task changed/);assert.equal(req('captured-text').textContent,long);
control.request=null;await req('refresh').click();assert(!req('accepted').disabled);assert(req('error').hidden);assert.equal(resolvePosts().length,0);
''')

    def test_scope_close_and_reopen_keep_retained_editor_conflict(self):
        self.check(r'''
await review('b');fill('B kept draft in conflict','plan');world.b.draft={text:'B saved elsewhere',mode:'native',revision:1};await n('refresh').click();assert(!n('conflict').hidden);
await requestReview('r');req('captured-text').scrollTop=340;req('captured').open=false;
n('project').value='/gone/project';await n('project').onchange();assert(!sessions().includes('r'));assert.equal(req('captured-text').textContent,long);
await req('return').click();assert(document.activeElement===n('refresh'));assert.equal(n('text').value,'B kept draft in conflict');assert(!n('conflict').hidden);
await n('close').click();await DeskPreparation.show();assert.equal(n('text').value,'B kept draft in conflict');assert(!n('conflict').hidden);assert.equal(n('save').disabled,true);
''')

    def test_explicit_original_reader_uses_captured_thread_not_current_or_selected(self):
        self.check(r'''const reads=[];globalThis.DeskHistoryReader={show:async(result,callbacks)=>{reads.push({result,callbacks});return true;},close:()=>true};
await requestReview('r');requests.r.request.current_binding={...original('r'),thread_id:'native-replacement',cwd:'/projects/other',profile:'replacement-profile'};requests.r.request.binding_mismatch=true;
await req('refresh').click();assert(req('accepted').disabled);const pre=req('captured-text');pre.scrollTop=420;req('captured').open=false;req('').scrollTop=180;
await req('read-original').click();assert.equal(reads.length,1);assert.deepEqual(reads[0].result,{thread_id:'native-r',cwd:'/projects/requests'});assert(reads[0].callbacks.valid());assert.equal(reads[0].callbacks.backLabel,'Return to task request');
assert.equal(req('captured-text').textContent,long);reads[0].callbacks.onReturn();assert(document.activeElement===req('read-original'));assert.equal(pre.scrollTop,420);assert(!req('captured').open);assert.equal(req('').scrollTop,180);assert.equal(resolvePosts().length,0);
''')

    def test_original_read_rechecks_native_home_and_never_reads_wrong_home(self):
        self.check(r'''const reads=[];globalThis.DeskHistoryReader={show:async(result,callbacks)=>{reads.push(result);return true;},close:()=>true};
await requestReview('r');control.request=async(path,result)=>{result.request.current_binding.native_home='/another-home';result.request.binding_mismatch=true;return result;};
await req('read-original').click();assert.equal(reads.length,0);assert(req('read-original').disabled);assert.match(req('read-status').textContent,/Restore the original native home/);assert.equal(resolvePosts().length,0);
''')

    def test_original_read_missing_captured_thread_does_not_fabricate_selected_binding(self):
        self.check(r'''globalThis.DeskHistoryReader={show:async()=>{throw Error('No thread should be read');},close:()=>true};
requests.r.request.binding.thread_id=null;requests.r.request.current_binding.thread_id=null;
await requestReview('r');assert(req('read-original').disabled);assert.match(req('read-status').textContent,/No original native conversation/);
''')

    def test_late_original_receipt_after_return_never_opens_reader(self):
        self.check(r'''const reads=[];globalThis.DeskHistoryReader={show:async(result)=>{reads.push(result);return true;},close:()=>true};
await requestReview('r');let release;control.request=(path,result)=>new Promise(resolve=>release=()=>resolve(result));
const pending=req('read-original').click();await settle();await req('return').click();release();await pending;assert.equal(reads.length,0);assert(!req('').open);assert.equal(document.activeElement.dataset.session,'r');
''')

    def test_original_reader_owned_close_and_late_return_cannot_reopen_new_request(self):
        self.check(r'''const reads=[],closed=[];globalThis.DeskHistoryReader={show:async(result,callbacks)=>{reads.push({result,callbacks});return true;},close:expected=>{closed.push(expected);expected?.onReturn();return true;}};
await requestReview('r');await req('read-original').click();const first=reads[0];assert(first.callbacks.valid());await req('return').click();assert(!first.callbacks.valid());assert.equal(closed[0],first.callbacks);
n('archived').checked=true;await n('refresh').click();await requestReview('s');const before=document.activeElement;first.callbacks.onReturn();assert(document.activeElement===before);assert.match(req('title').textContent,/Request s/);assert.equal(req('captured-title').textContent,'Captured Work task');
''')


    def test_close_button_restores_before_queued_native_close_event(self):
        self.check(r'''await n('close').click();mainText.focus();mainText.setSelectionRange(3,11,'backward');mainText.scrollTop=190;
await DeskPreparation.show();await requestReview('r');await req('return').click();
const dialog=n('');dialog.close=()=>{dialog.open=false;mainText.focus();mainText.setSelectionRange(0,0,'forward');setTimeout(()=>dialog.dispatch('close'),0);};
await n('close').click();assert(document.activeElement===mainText);assert.equal(mainText.selectionStart,3);assert.equal(mainText.selectionEnd,11);assert.equal(mainText.selectionDirection,'backward');assert.equal(mainText.scrollTop,190);
await settle();assert.equal(mainText.selectionStart,3);assert.equal(mainText.selectionEnd,11);
''')


if __name__ == '__main__':
    unittest.main()
