"""Keyboard ownership through real shipped Archive/Restore controller replies."""
import json
import subprocess
import unittest

from test_navigation_controllers import APP, DOM, NODE


SETUP = DOM.replace("function setArchived(){throw Error('Rendering must not archive');}", '') + r'''
let nativeThreadId=null,stopStateSnapshot=null;
const DeskStopTask={select(){},consume(){},restoreThread(){},sync(){},snapshot:()=>null,opened:async()=>false,reading:()=>false};
let opening=false,modeSelected=selected,nativeFailureSignature='',generation=7,refreshVersion=0;
const submitting=new Set();let requests=new Map();
function turnRequestBlocked(){return false;}
function drawTurnRequest(){}
const draft={text:'Exact unsent Plan — 保留  ',mode:'plan'};
const queue=[{id:'first',text:'Prepared Work',mode:'native'},
             {id:'second',text:'Prepared Plan',mode:'plan'}];
$('prompt').value=draft.text;$('turn-mode').value=draft.mode;
const DeskHome={sync(){}},DeskFollowups={status(){},refresh(){},blocked(){return false;}};
const DeskNativeState={usage(){return '';},card(){throw Error('No native failure expected');}};
const DeskRecall={stateChanged(){}};
function approvals(){}
function drawProfiles(){throw Error('Archive must not open profile settings');}
const row=id=>$('sessions').querySelectorAll('.session-row').find(node=>node.dataset.session===id);
const focusArchive=id=>row(id).querySelector('.session-archive').focus();
const focusedId=()=>document.activeElement.closest('.session-row')?.dataset.session;
const clone=value=>JSON.parse(JSON.stringify(value));
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
const settle=async()=>{await Promise.resolve();await Promise.resolve();};
const saved=id=>({id,name:'Same task title',cwd:'/projects/same',profile:'default',status:'ready',archived:false});
const active={...saved('active'),status:'running'};
const calls=[];let world,hold;
api=async(path,data)=>{
  calls.push({path,data:clone(data??null)});
  if(path==='/api/archive'){
    await hold.promise;world.sessions.find(session=>session.id===data.session).archived=data.archived;
    return {id:data.session,archived:data.archived};
  }
  if(path==='/api/state')return clone(world);
  throw Error('Archive navigation unexpectedly invoked '+path);
};
function seed(sessions){state={sessions,profiles:[]};world=clone(state);hold=deferred();draw();}
function unchanged(){
  assert.strictEqual(selected,'active');assert.strictEqual(generation,7);
  assert.strictEqual($('prompt').value,draft.text);assert.strictEqual($('turn-mode').value,draft.mode);
  assert.deepStrictEqual(queue,[{id:'first',text:'Prepared Work',mode:'native'},{id:'second',text:'Prepared Plan',mode:'plan'}]);
  assert(calls.every(call=>['/api/archive','/api/state'].includes(call.path)));
}
'''

# draw() uses the real outcome presenter global introduced by this candidate.
_app_globals = APP.read_text()
SETUP += '\nlet nativeOutcomeSignature=' + _app_globals.split('nativeOutcomeSignature=', 1)[1].split(',', 1)[0] + ';\n'


@unittest.skipUnless(NODE, 'Node is required for archive keyboard continuity')
class ArchiveNavigationControllerTests(unittest.TestCase):
    def check(self, body):
        source = APP.read_text()
        shipped = source[source.index('function activeSession('):source.index('function itemText(')]
        shipped += 'const interactionCards=new Map();\n' + source[source.index('function syncInteractionCards('):source.index('function consume(m)')]
        shipped += source[source.index('async function refresh()'):source.index('async function open(id,')]
        native_readouts = (APP.parent / 'native-steps.js').read_text() + '\nDeskNativeSteps.configure({$,make});\n'
        native_readouts += (APP.parent / 'turn-changes.js').read_text() + '\nDeskTurnChanges.configure({$,writeText:async()=>{}});\nconst DeskSteering={select(){},sync(){},consume(){},restoreThread(){},opened(){},reading:()=>false};\n'
        code = SETUP + '\n' + native_readouts + shipped + '\n(async()=>{\n' + body + r'''
unchanged();process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', code], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_pending_archive_keeps_action_focus_and_success_moves_to_next_visible_action(self):
        self.check(r'''
seed([active,saved('quoted "] session'),saved('last')]);
const id='quoted "] session';focusArchive(id);$('sessions').scrollTop=120;
const pending=setArchived(id,true);await settle();
assert.strictEqual(focusedId(),id);assert(document.activeElement.classList.contains('session-archive'));
assert.strictEqual(document.activeElement.getAttribute('aria-disabled'),'true');
await setArchived(id,true);assert.strictEqual(calls.filter(call=>call.path==='/api/archive').length,1);
hold.resolve();await pending;
assert(!row(id));assert.strictEqual(focusedId(),'last');
assert(document.activeElement.classList.contains('session-archive'));
assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
assert.strictEqual($('sessions').scrollTop,120);assert.strictEqual(archiving.size,0);
''')

    def test_failed_archive_returns_focus_to_retry_with_existing_state_and_error(self):
        self.check(r'''
seed([active,saved('one')]);focusArchive('one');const pending=setArchived('one',true);await settle();
assert.strictEqual(focusedId(),'one');hold.reject(Error('Archive temporarily unavailable'));await pending;
assert.strictEqual(focusedId(),'one');assert(document.activeElement.classList.contains('session-archive'));
assert.strictEqual(document.activeElement.getAttribute('aria-disabled'),'false');
assert.strictEqual(document.activeElement.textContent,'Archive');assert.strictEqual(state.sessions[1].archived,false);
assert.strictEqual($('organization-error').hidden,false);
assert.strictEqual($('organization-error').textContent,'Archive temporarily unavailable');
assert.strictEqual(calls.length,1);assert.strictEqual(archiving.size,0);
''')

    def test_restore_preserves_exact_action_after_reordering_and_keeps_filter(self):
        self.check(r'''
$('show-archived').checked=true;$('session-filter').value='same task';
seed([active,{...saved('one'),archived:true},saved('two')]);focusArchive('one');
const pending=setArchived('one',false);await settle();assert.strictEqual(focusedId(),'one');
world.sessions.reverse();hold.resolve();await pending;
assert.strictEqual(focusedId(),'one');assert.strictEqual(document.activeElement.textContent,'Archive');
assert.strictEqual(document.activeElement.getAttribute('aria-disabled'),'false');
assert.strictEqual($('session-filter').value,'same task');assert.strictEqual($('show-archived').checked,true);
assert.strictEqual(calls.filter(call=>call.path==='/api/archive').length,1);
''')

    def test_reply_does_not_steal_newer_task_editor_focus(self):
        self.check(r'''
seed([active,saved('one'),saved('two')]);focusArchive('one');const pending=setArchived('one',true);await settle();
$('prompt').focus();hold.resolve();await pending;
assert.strictEqual(document.activeElement,$('prompt'));assert(!row('one'));assert.strictEqual(archiving.size,0);
''')

    def test_newer_unsent_work_and_its_focus_survive_archive_reply(self):
        self.check(r'''
seed([active,saved('one')]);focusArchive('one');const pending=setArchived('one',true);await settle();
draft.text='Newer unsent Work — explicit typing';draft.mode='native';
$('prompt').value=draft.text;$('turn-mode').value=draft.mode;$('prompt').focus();
hold.resolve();await pending;assert.strictEqual(document.activeElement,$('prompt'));
assert.strictEqual($('prompt').value,'Newer unsent Work — explicit typing');
assert.strictEqual($('turn-mode').value,'native');assert.strictEqual(archiving.size,0);
''')

    def test_archived_active_session_keeps_its_action_under_nonmatching_search(self):
        self.check(r'''
$('session-filter').value='no matching title';seed([active,saved('one')]);focusArchive('active');
const pending=setArchived('active',true);await settle();hold.resolve();await pending;
assert.strictEqual(focusedId(),'active');assert.strictEqual(document.activeElement.textContent,'Restore');
assert.strictEqual(document.activeElement.getAttribute('aria-disabled'),'false');
assert.strictEqual($('sessions').querySelectorAll('.session-row').length,1);
assert.strictEqual($('session-filter').value,'no matching title');
assert.strictEqual($('archive-session').textContent,'Restore session');
''')

    def test_archiving_last_visible_idle_row_returns_to_search_without_selecting_work(self):
        self.check(r'''
seed([{...saved('active'),status:'completed'}]);focusArchive('active');
const pending=setArchived('active',true);await settle();hold.resolve();await pending;
assert.strictEqual($('sessions').querySelectorAll('.session-row').length,0);
assert.strictEqual(document.activeElement,$('session-filter'));
assert.strictEqual($('archive-session').textContent,'Restore session');
assert.strictEqual($('session-filter').value,'');assert.strictEqual(archiving.size,0);
''')


if __name__ == '__main__':
    unittest.main()
