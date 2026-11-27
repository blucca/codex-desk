"""Active → idle keyboard continuity through the shipped state refresh path."""
import json
import subprocess
import unittest

from test_archive_navigation_controller import APP, NODE, SETUP


@unittest.skipUnless(NODE, 'Node is required for transition keyboard continuity')
class TransitionNavigationControllerTests(unittest.TestCase):
    def check(self, body):
        source = APP.read_text()
        shipped = source[source.index('function activeSession('):source.index('function itemText(')]
        shipped += source[source.index('async function refresh()'):source.index('async function open(id,')]
        native_steps = (APP.parent / 'native-steps.js').read_text() + '\nDeskNativeSteps.configure({$,make});\n'
        code = SETUP + '\n' + native_steps + shipped + '\n(async()=>{\n' + body + r'''
unchanged();assert(calls.every(call=>call.path==='/api/state'));
process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', code], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_filtered_completion_moves_both_controls_to_nearest_visible_row(self):
        self.check(r'''
for(const status of ['starting','running','approval'])for(const control of ['session','session-archive']){
  $('session-filter').value='  Needle  ';$('show-archived').checked=true;
  const id='quoted "] session';
  seed([{...active,name:'Needle selected'}, {...saved(id),status}, {...saved('tail'),name:'Needle tail'}]);
  const old=row(id).querySelector('.'+control);old.focus();$('sessions').scrollTop=120;$('sessions').scrollLeft=7;
  world.sessions.find(s=>s.id===id).status='completed';await refresh();
  assert(!row(id));assert.strictEqual(focusedId(),'tail');
  assert(document.activeElement.classList.contains(control));
  assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
  assert.strictEqual($('sessions').scrollTop,120);assert.strictEqual($('sessions').scrollLeft,7);
  assert.strictEqual($('session-filter').value,'  Needle  ');assert.strictEqual($('show-archived').checked,true);
  assert.strictEqual(document.activeElement.getAttribute('aria-current'),null);
  unchanged();
}
''')

    def test_archived_completion_clamps_to_last_visible_same_control(self):
        self.check(r'''
for(const control of ['session','session-archive']){
  $('session-filter').value='';$('show-archived').checked=false;
  seed([{...active,status:'completed'}, {...saved('last'),status:'running',archived:true}]);
  row('last').querySelector('.'+control).focus();world.sessions[1].status='failed';await refresh();
  assert(!row('last'));assert.strictEqual(focusedId(),'active');
  assert(document.activeElement.classList.contains(control));
  assert.strictEqual($('session-filter').value,'');assert.strictEqual($('show-archived').checked,false);
  assert.strictEqual(world.sessions[1].archived,true);
  unchanged();
}
''')

    def test_last_active_completion_returns_both_controls_to_exact_search(self):
        self.check(r'''
for(const control of ['session','session-archive']){
  $('session-filter').value=' Exact nonmatching + 决策  ';$('show-archived').checked=false;
  seed([{...active,archived:true}]);row('active').querySelector('.'+control).focus();
  world.sessions[0].status='completed';await refresh();
  assert.strictEqual($('sessions').querySelectorAll('.session-row').length,0);
  assert.strictEqual(document.activeElement,$('session-filter'));
  assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
  assert.strictEqual($('session-filter').value,' Exact nonmatching + 决策  ');
  assert.strictEqual($('show-archived').checked,false);unchanged();
}
''')

    def test_visible_idle_transition_retains_original_control_through_reorder(self):
        self.check(r'''
for(const control of ['session','session-archive']){
  $('session-filter').value='same task';$('show-archived').checked=true;
  seed([active,{...saved('one'),status:'running',archived:true},saved('two')]);
  row('one').querySelector('.'+control).focus();world.sessions[1].status='completed';world.sessions.reverse();await refresh();
  assert.strictEqual(focusedId(),'one');assert(document.activeElement.classList.contains(control));
  assert.strictEqual(row('one').querySelector('.session-archive').textContent,'Restore');unchanged();
}
''')

    def test_held_state_reply_keeps_newer_editor_search_toggle_or_row_focus(self):
        self.check(r'''
for(const target of ['prompt','session-filter','show-archived','other-row']){
  $('session-filter').value='needle';$('show-archived').checked=false;
  seed([{...active,name:'Needle selected'}, {...saved('one'),status:'running'}, {...saved('two'),name:'Needle tail'}]);
  focusArchive('one');const gate=deferred();
  api=async path=>{calls.push({path});await gate.promise;return clone(world);};
  const pending=refresh();await settle();world.sessions[1].status='completed';
  const newer=target==='other-row'?row('two').querySelector('.session') : $(target);newer.focus();
  gate.resolve();await pending;assert(!row('one'));
  if(target==='other-row'){assert.strictEqual(focusedId(),'two');assert(document.activeElement.classList.contains('session'));}
  else assert.strictEqual(document.activeElement,newer);
  assert.strictEqual($('session-filter').value,'needle');unchanged();
}
''')

    def test_explicit_idle_filter_and_archive_scope_do_not_trigger_transition_fallback(self):
        self.check(r'''
seed([active,saved('one')]);focusArchive('one');$('session-filter').value='nonmatching';$('session-filter').oninput();
assert.strictEqual(document.activeElement,document.body);assert(!row('one'));
$('session-filter').value='';$('show-archived').checked=true;
seed([active,{...saved('one'),status:'running',archived:true}]);focusArchive('one');
world.sessions[1].status='completed';await refresh();assert.strictEqual(focusedId(),'one');
$('show-archived').checked=false;$('show-archived').onchange();
assert.strictEqual(document.activeElement,document.body);assert(!row('one'));
assert.strictEqual($('session-filter').value,'');assert.strictEqual($('show-archived').checked,false);
''')


if __name__ == '__main__':
    unittest.main()
