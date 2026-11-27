"""Run the shipped changed-binding and token-free ordinary recovery controller."""
import unittest

import test_turn_request_controller as run_fixture

NODE = run_fixture.NODE

BINDINGS = r'''
const originalBinding={session:'a',native_home:'/native/old-home',cwd:'/retained/old-project',profile:'old-profile',thread_id:'native-original'};
const currentBinding={session:'a',native_home:'/native/current-home',cwd:'/retained/current-project',profile:'current-profile',thread_id:'native-replacement'};
function mismatch(status='rejected'){
  const token='00000000-0000-4000-8000-000000000077';
  const body={session:'a',token,text:world.draft.text,mode:world.draft.mode,revision:world.draft.revision,writer:'old-page',sequence:1};
  world.receipt=receipt(body,status);
  Object.assign(world.receipt.request,{binding:clone(originalBinding),current_binding:clone(currentBinding),binding_mismatch:true,error:'The retained native target changed before admission'});
  return body;
}
'''


@unittest.skipUnless(NODE, 'Node is required for ordinary target recovery controllers')
class TurnRecoveryControllerTests(unittest.TestCase):
    check = run_fixture.TurnRequestControllerTests.check

    def test_captured_plan_visible_with_blank_editor_and_same_body_draw_preserves_reader(self):
        self.check(BINDINGS + r'''
const original=mismatch('needs_review');world.receipt.request.binding_mismatch=false;world.receipt.request.current_binding=clone(originalBinding);
world.draft={text:'',mode:'plan',revision:2};drafts.clear();draftRevisions.clear();draftSaved.clear();draftModes.clear();selected=null;
await open('a');const disclosure=$('turn-request-captured'),pre=$('turn-request-captured-text');
assert(!disclosure.hidden);assert(disclosure.open);assert.equal($('turn-request-captured-title').textContent,'Captured Plan task');assert.equal(pre.textContent,original.text);
assert.equal($('prompt').value,'');assert(calls.every(call=>!call.data));
const descriptor=Object.getOwnPropertyDescriptor(Element.prototype,'textContent');let writes=0;
Object.defineProperty(pre,'textContent',{get(){return descriptor.get.call(this);},set(value){++writes;descriptor.set.call(this,value);}});
pre.scrollTop=137;disclosure.open=false;pre.focus();draw();await submit();draw();
assert.equal(writes,0);assert.equal(pre.scrollTop,137);assert.equal(disclosure.open,false);assert.equal(document.activeElement,pre);assert.equal($('prompt').value,'');
disclosure.open=true;await submit();assert.equal(pre.scrollTop,137);assert(disclosure.open);assert.equal(writes,0);assert.equal(pre.textContent,original.text);
''')

    def test_captured_work_is_exact_text_and_new_identity_resets_disclosure(self):
        self.check(BINDINGS + r'''
const original=mismatch('rejected');original.mode='native';original.text='  <script>literal captured task</script>\nWork — 保留  ';world.receipt.request.payload=clone(original);
await open('a');assert.equal($('turn-request-captured-title').textContent,'Captured Work task');assert.equal($('turn-request-captured-text').textContent,original.text);assert($('turn-request-captured').open);
$('turn-request-captured').open=false;const replacement={...original,token:'00000000-0000-4000-8000-000000000088'};
world.receipt=receipt(replacement,'needs_review');adoptTurnConflict(turnRequest(),world.receipt);draw();assert($('turn-request-captured').open);assert.equal($('turn-request-captured-text').textContent,original.text);
assert(!storage.get(turnRequestKey).includes('<script>'));
''', cold=True)

    def test_cold_rejected_changed_target_shows_exact_targets_and_blocks_original_retry(self):
        self.check(BINDINGS + r'''
const original=mismatch();await open('a');
assert.equal(turnRequest().status,'rejected');assert.equal(turnRequest().body.token,original.token);assert(calls.every(c=>!c.data));
assert(!$('turn-request-binding').hidden);assert($('turn-request-original-binding').textContent.includes('/native/old-home'));
assert($('turn-request-original-binding').textContent.includes('/retained/old-project'));
assert($('turn-request-original-binding').textContent.includes('old-profile'));assert($('turn-request-original-binding').textContent.includes('native-original'));
assert($('turn-request-current-binding').textContent.includes('/native/current-home'));assert($('turn-request-current-binding').textContent.includes('native-replacement'));
assert($('turn-request-retry').disabled);await $('turn-request-retry').onclick();assert.equal(posts().length,0);
assert.equal($('turn-request-new').textContent,'Use current target for a new task');assert.match($('turn-request-error').textContent,/retained native target changed/);
assert(!storage.get(turnRequestKey).includes('/native/'));
''', cold=True)

    def test_known_rejected_explicit_current_target_review_does_not_send_until_fresh_run(self):
        self.check(BINDINGS + r'''
const original=mismatch();await open('a');edit('Newer exact Plan — 保留  ');await persistDraft('a');$('prompt').focus();$('prompt').selectionStart=3;$('prompt').selectionEnd=8;
const before=calls.filter(call=>call.path.startsWith('/api/turn/request?')).length;
await $('turn-request-new').onclick();assert(!turnRequest());assert.equal(posts().length,0);
assert(calls.filter(call=>call.path.startsWith('/api/turn/request?')).length>before);assert.equal($('prompt').value,'Newer exact Plan — 保留  ');
assert.equal($('prompt').selectionStart,3);assert.equal($('prompt').selectionEnd,8);assert.equal(document.activeElement,$('prompt'));
await submit();assert.equal(starts,1);assert.equal(posts().length,1);assert.notEqual(posts()[0].data.token,original.token);assert.equal(posts()[0].data.text,'Newer exact Plan — 保留  ');
''', cold=True)

    def test_newer_edits_during_target_review_remain_unsent_and_require_another_choice(self):
        self.check(BINDINGS + r'''
mismatch();await open('a');const held=deferred();control.read=()=>held.promise;
const reviewing=$('turn-request-new').onclick();await settle();edit('Newer edit while target check waits','native');$('prompt').focus();$('prompt').selectionStart=4;
held.resolve(clone(world.receipt));await reviewing;assert(turnRequest());assert.equal(posts().length,0);assert.equal($('prompt').value,'Newer edit while target check waits');
assert.equal($('turn-mode').value,'native');assert.equal($('prompt').selectionStart,4);assert.match($('turn-request-status').textContent,/changed during review/);
control.read=null;await $('turn-request-new').onclick();assert(!turnRequest());assert.equal(posts().length,0);
''', cold=True)

    def test_new_target_during_review_requires_review_of_latest_binding(self):
        self.check(BINDINGS + r'''
mismatch();await open('a');const held=deferred();control.read=()=>held.promise;
const reviewing=$('turn-request-new').onclick();await settle();world.receipt.request.current_binding.thread_id='native-third';
held.resolve(clone(world.receipt));await reviewing;assert(turnRequest());assert.equal(posts().length,0);assert.match($('turn-request-current-binding').textContent,/native-third/);
assert.match($('turn-request-status').textContent,/changed during review/);
''', cold=True)

    def test_selection_changed_during_target_review_cannot_release_original_identity(self):
        self.check(BINDINGS + r'''
mismatch();await open('a');const held=deferred();control.read=()=>held.promise;
const reviewing=$('turn-request-new').onclick();await settle();selected='other';++generation;$('prompt').value='Other exact task';$('turn-mode').value='native';$('prompt').focus();
held.resolve(clone(world.receipt));await reviewing;assert(turnRequest('a'));assert.equal(selected,'other');assert.equal($('prompt').value,'Other exact task');assert.equal(posts().length,0);
''', cold=True)

    def test_unknown_mismatch_allows_only_read_and_original_target_restoration(self):
        self.check(BINDINGS + r'''
mismatch('needs_review');await open('a');assert(turnRequest());assert($('turn-request-new').hidden);
assert($('turn-request-accepted').hidden && $('turn-request-rejected').hidden);assert.match($('turn-request-status').textContent,/Restore the original target/);
await $('turn-request-accepted').onclick();await $('turn-request-rejected').onclick();await $('turn-request-retry').onclick();await $('turn-request-new').onclick();await submit();
assert(calls.every(call=>!call.data));assert(turnRequest());assert.equal(starts,0);assert($('followup-send').disabled);
world.receipt.request.binding_mismatch=false;world.receipt.request.current_binding=clone(originalBinding);await submit();
assert(!$('turn-request-accepted').hidden && !$('turn-request-rejected').hidden);await $('turn-request-rejected').onclick();assert.equal(turnRequest().status,'rejected');assert.equal(posts().length,0);
''', cold=True)

    def test_accepted_mismatch_never_reconciles_blank_original_into_current_editor(self):
        self.check(BINDINGS + r'''
const original=mismatch('accepted');const text=world.draft.text;await loadDraft('a',-1);world.draft={text:'',mode:'plan',revision:original.revision+1};
await open('a');assert.equal($('prompt').value,text);assert.equal(turnRequest().status,'accepted');assert.equal(posts().length,0);assert(!$('turn-request-binding').hidden);
''', cold=True)

    def test_session_only_discovery_mounts_unknown_request_with_blank_draft_get_only(self):
        self.check(BINDINGS + r'''
const original=mismatch('needs_review');world.receipt.request.binding_mismatch=false;world.receipt.request.current_binding=clone(originalBinding);
world.draft={text:'',mode:'plan',revision:2};drafts.clear();draftRevisions.clear();draftSaved.clear();draftModes.clear();selected=null;
await open('a');assert.equal(turnRequest().token,original.token);assert.equal(turnRequest().status,'needs_review');assert.equal($('prompt').value,'');
assert(calls.some(call=>call.path==='/api/turn/request?session=a'));assert(calls.every(call=>!call.data));assert(!calls.some(call=>call.path==='/api/open'));
assert(!$('turn-request-accepted').hidden && !$('turn-request-rejected').hidden);assert.equal($('prompt').required,false);
assert.deepEqual(JSON.parse(storage.get(turnRequestKey)),[{session:'a',token:original.token}]);
''')

    def test_session_discovery_unknown_changed_target_preserves_newer_plan_and_reader(self):
        self.check(BINDINGS + r'''
const original=mismatch('needs_review');world.draft={text:'Newer saved Plan — 保留  ',mode:'plan',revision:3};drafts.clear();draftRevisions.clear();draftSaved.clear();draftModes.clear();selected=null;
$('history-reader').open=true;await open('a');assert.equal(turnRequest().token,original.token);assert.equal($('prompt').value,'Newer saved Plan — 保留  ');
assert($('turn-request-accepted').hidden);assert($('turn-request-new').hidden);assert($('history-reader').open);assert.equal(frames.length,0);assert(calls.every(call=>!call.data));
''')


if __name__ == '__main__':
    unittest.main()
