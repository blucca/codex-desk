"""Prepared work saves the reviewed draft before its explicit conversation handoff."""
import subprocess
import unittest

from test_preparation_controller import HARNESS, NODE, ROOT


SETUP = HARNESS[:HARNESS.index('(async()=>{')]
SETUP = SETUP.replace('const nodes=', "if(!ids.includes('preparation-save-open'))ids.push('preparation-save-open');\nconst nodes=", 1)
SETUP = SETUP.replace(
    'onSaved:async(id,draft)=>saved.push({id,draft:clone(draft)}),openConversation:async id=>{opened.push(id);return true;}',
    'onSaved:async(id,draft)=>{saved.push({id,draft:clone(draft)});return control.saved?control.saved(id,draft):true;},'
    'openConversation:async id=>{opened.push(id);return control.open?control.open(id):true;}', 1)


@unittest.skipUnless(NODE, 'Node is required for the preparation handoff controller')
class PreparationHandoffControllerTests(unittest.TestCase):
    def check(self, body):
        script = SETUP + '\n(async()=>{\nawait DeskPreparation.show();\n' + body + r'''
assert.deepEqual(activeDraft,{session:'a',text:'ACTIVE UNSENT PLAN — do not alter',mode:'plan'});
assert(!calls.some(c=>/^\/api\/(open|import|turn|sessions|followups)/.test(c.path)));
console.log(JSON.stringify({passed:true,explicit_saves:saved.length,open_callbacks:opened.length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script, str(ROOT / 'codex_desk/static/preparation.js')],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"passed":true', result.stdout)

    def test_reused_plan_is_saved_before_open_and_queue_stays_prepared(self):
        self.check(r'''
const queue=clone(world.b.followups);
await review('b');
await button(followup('b-two'),'Use in this session draft').click();await n('replace').click();
assert.equal(n('text').value,'Clarify the next acceptance');assert.equal(n('mode').value,'plan');
assert.equal(n('open').textContent,'Open without these edits');assert.deepEqual(opened,[]);
control.open=id=>{
  assert.equal(id,'b');assert.equal(saved.length,1);
  assert.deepEqual(world.b.draft,{text:'Clarify the next acceptance',mode:'plan',revision:1});return true;
};
await n('save-open').click();
assert.deepEqual(opened,['b']);assert.equal(n('').open,false);assert.deepEqual(world.b.followups,queue);
assert.equal(calls.filter(c=>c.data).length,1);
await DeskPreparation.show();assert.equal(n('text').value,world.b.draft.text);assert.equal(n('mode').value,'plan');
assert.equal(n('open').textContent,'Open conversation');
''')

    def test_failed_save_keeps_review_and_retry_opens_only_after_save(self):
        self.check(r'''
await review('a');fill('Reviewed preparation','native');control.failPost=true;
await n('save-open').click();assert.deepEqual(opened,[]);assert.equal(n('').open,true);
assert.equal(n('text').value,'Reviewed preparation');assert.equal(n('mode').value,'native');
assert.equal(world.a.draft.text,'A saved Plan');assert.match(n('draft-status').textContent,/not saved/);
control.failPost=false;await n('save-open').click();
assert.deepEqual(opened,['a']);assert.equal(world.a.draft.text,'Reviewed preparation');
''')

    def test_revision_conflict_does_not_open_until_explicit_resolution(self):
        self.check(r'''
await review('a');fill('My unsaved preparation','native');
world.a.draft={text:'Other tab preparation',mode:'plan',revision:2};
await n('save-open').click();assert.deepEqual(opened,[]);assert.equal(n('conflict').hidden,false);
assert.equal(n('save-open').disabled,true);assert.equal(n('text').value,'My unsaved preparation');
await n('load').click();assert.equal(n('text').value,'Other tab preparation');assert.equal(n('mode').value,'plan');
await n('save-open').click();assert.deepEqual(opened,['a']);assert.equal(world.a.draft.text,'Other tab preparation');
''')

    def test_newer_edits_during_save_stay_local_and_require_another_choice(self):
        self.check(r'''
await review('a');fill('Reviewed capture','plan');const held=deferred();control.post=()=>held.promise;
const saving=n('save-open').click();await settle();assert.equal(n('save-open').disabled,true);
assert.equal(n('open').disabled,true);fill('Newer unsaved text','native');
held.resolve(clone(world.a.draft));await saving;
assert.deepEqual(opened,[]);assert.equal(n('').open,true);assert.equal(world.a.draft.text,'Reviewed capture');
assert.equal(n('text').value,'Newer unsaved text');assert.equal(n('mode').value,'native');
assert.match(n('draft-status').textContent,/Newer edits/);
control.post=null;await n('save-open').click();assert.deepEqual(opened,['a']);
assert.equal(world.a.draft.text,'Newer unsaved text');assert.equal(world.a.draft.mode,'native');
''')

    def test_switching_review_during_save_never_opens_the_old_destination(self):
        self.check(r'''
await review('a');fill('Reviewed A capture','plan');const held=deferred();control.post=()=>held.promise;
const saving=n('save-open').click();await settle();await review('b');fill('B retained unsaved','native');
held.resolve(clone(world.a.draft));await saving;
assert.deepEqual(opened,[]);assert.equal(n('').open,true);assert.equal(n('text').value,'B retained unsaved');
assert.equal(world.a.draft.text,'Reviewed A capture');assert.equal(world.b.draft.text,'');
await review('a');assert.match(n('draft-status').textContent,/Return to this preparation/);
control.post=null;await n('save-open').click();assert.deepEqual(opened,['a']);
''')

    def test_closing_review_while_save_waits_cannot_open_a_native_conversation(self):
        self.check(r'''
await review('a');fill('Parked draft','native');const held=deferred();control.post=()=>held.promise;
const saving=n('save-open').click();await settle();await n('close').click();
held.resolve(clone(world.a.draft));await saving;
assert.deepEqual(opened,[]);assert.equal(n('').open,false);assert.equal(world.a.draft.text,'Parked draft');
await DeskPreparation.show();assert.equal(n('text').value,'Parked draft');assert.deepEqual(opened,[]);
await n('open').click();assert.deepEqual(opened,['a']);assert.equal(calls.filter(c=>c.data).length,1);
''')

    def test_returning_to_same_review_during_save_does_not_restore_open_permission(self):
        self.check(r'''
await review('a');fill('Reviewed A capture','plan');const held=deferred();control.post=()=>held.promise;
const saving=n('save-open').click();await settle();await review('b');await review('a');
held.resolve(clone(world.a.draft));await saving;
assert.deepEqual(opened,[]);assert.equal(n('').open,true);assert.equal(world.a.draft.text,'Reviewed A capture');
assert.match(n('draft-status').textContent,/Return to this preparation/);
control.post=null;await n('open').click();assert.deepEqual(opened,['a']);
assert.equal(calls.filter(c=>c.data).length,1);
''')

    def test_reopening_same_review_during_save_requires_another_open_choice(self):
        self.check(r'''
await review('a');fill('Parked reviewed capture','native');const held=deferred();control.post=()=>held.promise;
const saving=n('save-open').click();await settle();await n('close').click();await DeskPreparation.show();
held.resolve(clone(world.a.draft));await saving;
assert.deepEqual(opened,[]);assert.equal(n('').open,true);assert.equal(n('text').value,'Parked reviewed capture');
assert.equal(world.a.draft.text,'Parked reviewed capture');
assert.match(n('draft-status').textContent,/Return to this preparation/);
control.post=null;await n('open').click();assert.deepEqual(opened,['a']);
assert.equal(calls.filter(c=>c.data).length,1);
''')

    def test_workbench_conflict_callback_blocks_handoff_without_losing_saved_text(self):
        self.check(r'''
await review('a');fill('Prepared replacement','native');control.saved=()=>false;
await n('save-open').click();assert.equal(world.a.draft.text,'Prepared replacement');
assert.deepEqual(opened,[]);assert.equal(n('').open,true);assert.match(n('draft-status').textContent,/other unsaved edits/);
control.saved=()=>true;await n('save-open').click();assert.deepEqual(opened,['a']);
''')

    def test_open_failure_after_save_keeps_preparation_and_open_retry_needs_no_save(self):
        self.check(r'''
await review('b');fill('Saved before unavailable native project','plan');
control.open=()=>{throw Error('Project folder unavailable');};await n('save-open').click();
assert.equal(n('').open,true);assert.equal(n('text').value,'Saved before unavailable native project');
assert.equal(world.b.draft.mode,'plan');assert.match(n('error').textContent,/Project folder unavailable/);
assert.equal(n('save-open').disabled,false);assert.equal(n('open').textContent,'Open conversation');
control.open=()=>true;await n('open').click();assert.deepEqual(opened,['b','b']);
assert.equal(n('').open,false);assert.equal(calls.filter(c=>c.data).length,1);
''')

    def test_real_workbench_callback_preserves_dirty_draft_and_accepts_clean_handoff(self):
        source = (ROOT / 'codex_desk/static/app.js').read_text()
        callback = source[source.index('function preparationSaved('):source.index('DeskPreparation.configure(')]
        self.check(r'''
const main={prompt:new Element('textarea'),mode:new Element('select')};
const $=id=>id==='prompt'?main.prompt:main.mode;
const drafts=new Map([['a','Workbench unsaved text']]),draftModes=new Map([['a','plan']]);
const draftSaved=new Map([['a',clone(world.a.draft)]]),draftRevisions=new Map([['a',1]]);
const draftTimers=new Map(),draftSaves=new Map(),draftConflicts=new Map(),draftMessages=new Map();
let selected='a',modeSelected='a';function draftStatus(){}
''' + callback + r'''
control.saved=preparationSaved;await review('a');fill('Reviewed local preparation','native');
await n('save-open').click();assert.deepEqual(opened,[]);assert.equal(drafts.get('a'),'Workbench unsaved text');
assert.equal(draftModes.get('a'),'plan');assert.equal(draftConflicts.get('a').text,'Reviewed local preparation');
assert.match(n('draft-status').textContent,/other unsaved edits/);
// The workbench user explicitly loads the saved conflict before returning.
const current=draftConflicts.get('a');draftSaved.set('a',current);drafts.set('a',current.text);
draftModes.set('a',current.mode);draftRevisions.set('a',current.revision);draftConflicts.delete('a');
fill('Ready after review','plan');await n('save-open').click();assert.deepEqual(opened,['a']);
assert.equal(drafts.get('a'),'Ready after review');assert.equal(main.prompt.value,'Ready after review');
assert.equal(main.mode.value,'plan');assert.equal(draftConflicts.has('a'),false);
''')


if __name__ == '__main__':
    unittest.main()
