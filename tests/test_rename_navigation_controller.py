"""Rename replies preserve later typing and explicitly newer navigation."""
import json
import subprocess
import unittest
from test_navigation_controllers import APP, DOM, NODE

SETUP=DOM+r'''
const listeners=new Map();
const dialog=$('rename-dialog');
dialog.showModal=()=>{dialog.open=true;};
dialog.close=()=>{dialog.open=false;for(const f of listeners.get('close')||[])f();};
dialog.addEventListener=(type,f)=>{if(!listeners.has(type))listeners.set(type,[]);listeners.get(type).push(f);};
$('rename-name').select=()=>{};
const draft={text:'Unsent Plan — keep',mode:'plan'},queue=['Paused Work','Paused Plan'];
$('prompt').value=draft.text;$('turn-mode').value=draft.mode;
state.sessions=[{id:'active',name:'Original title'},{id:'other',name:'Other title'}];
let refreshes=0;async function refresh(){++refreshes;}
const calls=[],gates=[];
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});return {promise,resolve,reject};};
api=async(path,data)=>{calls.push({path,data});const gate=deferred();gates.push(gate);return await gate.promise;};
const submit=()=>$('rename-form').onsubmit({preventDefault(){}});
function unchanged(){assert.strictEqual($('prompt').value,draft.text);assert.strictEqual($('turn-mode').value,draft.mode);assert.deepStrictEqual(queue,['Paused Work','Paused Plan']);}
'''

@unittest.skipUnless(NODE,'Node is required for rename navigation')
class RenameNavigationTests(unittest.TestCase):
    def check(self,body):
        source=APP.read_text();start=source.index('let renameSession=') if 'let renameSession=' in source else source.index("$('rename').onclick=")
        code=SETUP+source[start:]+ '\n(async()=>{'+body+r'''
unchanged();process.stdout.write(JSON.stringify({passed:true}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
'''
        r=subprocess.run([NODE,'-e',code],capture_output=True,text=True,timeout=20)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr);self.assertEqual(json.loads(r.stdout),{'passed':True})
    def test_typing_after_submit_survives_success_and_can_be_saved_next(self):
        self.check(r'''
$('rename').onclick();$('rename-name').value='Submitted';const pending=submit();
$('rename-name').value='Newer unsaved title';gates[0].resolve({});await pending;
assert(dialog.open);assert.strictEqual($('rename-name').value,'Newer unsaved title');assert(!$('rename-save').disabled);
const next=submit();assert.strictEqual(calls[1].data.name,'Newer unsaved title');gates[1].resolve({});await next;
assert(!dialog.open);assert.strictEqual(calls[0].data.session,'active');
''')
    def test_cancel_reopen_same_session_preserves_editor_and_serializes_request(self):
        self.check(r'''
$('rename').onclick();$('rename-name').value='Submitted';const pending=submit();$('rename-cancel').onclick();
$('rename').onclick();$('rename-name').value='Reopened edit';assert($('rename-save').disabled);const duplicate=submit();assert.strictEqual(calls.length,1);
gates[0].resolve({});await pending;assert(dialog.open);assert.strictEqual($('rename-name').value,'Reopened edit');assert(!$('rename-save').disabled);
''')
    def test_success_for_prior_session_does_not_close_new_dialog_or_change_selection(self):
        self.check(r'''
$('rename').onclick();$('rename-name').value='Prior name';const pending=submit();$('rename-cancel').onclick();selected='other';
$('rename').onclick();$('rename-name').value='Other unsent name';const newer=submit();
assert.strictEqual(calls[1].data.session,'other');gates[0].resolve({});await pending;
assert(dialog.open);assert.strictEqual(selected,'other');assert.strictEqual($('rename-name').value,'Other unsent name');assert($('rename-save').disabled);
gates[1].resolve({});await newer;assert(!dialog.open);
''')
    def test_failure_for_prior_editor_does_not_surface_in_new_editor(self):
        self.check(r'''
$('rename').onclick();const pending=submit();$('rename-cancel').onclick();selected='other';$('rename').onclick();
$('rename-name').value='Newer edit';gates[0].reject(Error('Prior rename failed'));await pending;
assert(dialog.open);assert($('rename-error').hidden);assert.strictEqual($('rename-name').value,'Newer edit');assert(!$('rename-save').disabled);
''')
    def test_current_failure_keeps_retry_and_repeat_submit_is_one_request(self):
        self.check(r'''
$('rename').onclick();$('rename-name').value='Retry exact name';const pending=submit();const duplicate=submit();assert.strictEqual(calls.length,1);
gates[0].reject(Error('Native naming unavailable'));await pending;
assert(dialog.open);assert.strictEqual($('rename-name').value,'Retry exact name');assert(!$('rename-save').disabled);
assert(!$('rename-error').hidden);assert.strictEqual($('rename-error').textContent,'Native naming unavailable');
''')

if __name__=='__main__':unittest.main()
