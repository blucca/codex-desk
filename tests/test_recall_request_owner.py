"""Independent captured-request viewer activation belongs to Recall, not Prepared."""
import subprocess,unittest
from test_prepared_request_controller import SETUP,NODE,ROOT

@unittest.skipUnless(NODE,'Node required')
class RecallRequestOwnerTests(unittest.TestCase):
    def check(self,body):
        script=SETUP+r'''
(async()=>{
await DeskPreparation.show();await n('close').click();
let scope=1,returned=0,resolved=0;
const owner=()=>({origin:'recall',backLabel:'Return to results',valid:()=>scope===1,
  onReturn:()=>++returned,onResolved:()=>{++resolved;return false;},refreshMessage:'Return then Search to update results.'});
const resultRow=clone(world.r);const show=()=>DeskPreparedRequest.show(resultRow,owner());
'''+body+r'''
unchanged();console.log(JSON.stringify({passed:true,returned,resolved}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result=subprocess.run([NODE,'-e',script,str(ROOT/'codex_desk/static/preparation.js')],text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertIn('"passed":true',result.stdout)

    def test_without_prepared_open_exact_body_and_origin_close(self):
        self.check(r'''
await show();assert(req('').open);assert(!n('').open);assert.equal(req('return').textContent,'Return to results');
assert.equal(req('captured-text').textContent,long);assert.equal(req('identity').textContent,'Request ID: '+token('r'));
DeskPreparedRequest.close('prepared');assert(req('').open);assert.equal(returned,0);
DeskPreparedRequest.close('recall');assert(!req('').open);assert.equal(returned,1);
''')

    def test_resolution_only_calls_active_owner_and_keeps_other_editor(self):
        self.check(r'''
await show();const before=clone(world.b);await req('accepted').click();
assert.equal(resolved,1);assert.equal(requests.r.request.status,'accepted');assert.deepEqual(world.b,before);
assert(req('status').textContent.includes('Return then Search'));assert.equal(resolvePosts().length,1);
await req('return').click();assert.equal(returned,1);
''')

    def test_invalid_origin_rejects_late_get_and_return(self):
        self.check(r'''
let release;control.request=(_,value)=>new Promise(r=>release=()=>r(value));
const pending=show();await Promise.resolve();scope=2;DeskPreparedRequest.close('recall');
release();await pending;assert(!req('').open);assert.equal(returned,0);assert.equal(resolved,0);
''')

    def test_new_activation_same_uuid_owns_late_resolve(self):
        self.check(r'''
await show();let release;control.resolve=(_,value)=>new Promise(r=>release=()=>r(value));
const pending=req('rejected').click();await Promise.resolve();DeskPreparedRequest.close('recall');
control.resolve=null;await show();const current=req('status').textContent;
release();await pending;assert(req('').open);assert.equal(req('status').textContent,current);assert.equal(resolved,0);
assert.equal(returned,1);await req('return').click();assert.equal(returned,2);
''')

    def test_late_prepared_close_event_cannot_close_recall_owner(self):
        self.check(r'''
await DeskPreparation.show();const nativeClose=n('').close.bind(n(''));await n('close').click();
await show();nativeClose();assert(req('').open);assert.equal(returned,0);
await req('return').click();assert.equal(returned,1);
''')
