"""Captured-action controller invokes only exact original GET and parent-owned return."""
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SETUP = r'''
const assert=require('assert/strict'),L=require(process.argv[1]),R=require(process.argv[2]);
const owner={native_home:'a'.repeat(64),session:'A',thread_id:'native-A',turn_id:'parent-turn',item_id:'parent-call'};
let current={...owner},generation=3,intent=5;
const parentSource={id:'native-A',turns:[{id:'parent-turn',items:[{id:'parent-call',type:'collabAgentToolCall',receiverThreadIds:['child-1','child-2']}]}]};
const targets=L.capture(owner,parentSource.turns[0].items[0]).targets;
const parentView={turn:'parent-turn',item:'parent-call',open:true,scrollTop:281,screenTop:145,windowTop:930};
const retained={draft:'A exact unsent Plan',mode:'plan',queue:['A Work','A Plan'],B:{answers:{question:'B exact unsent answer'},draft:'B independent Plan',queue:['B Work','B Plan']},reviewed:11,status:'running'};
const before=JSON.stringify(retained),requests=[],returns=[],readers=[],notices=[];
let transport=async path=>({home_namespace:owner.native_home,thread:{id:new URL(path,'http://local').searchParams.get('thread'),cwd:'/original/child',turns:[{id:'child-turn',status:'failed',error:{message:'Exact native failure'},items:[{id:'child-answer',type:'agentMessage',phase:'commentary',text:'Exact supplied child response.'}]}]}});
const controller=R.create({owner:()=>current,generation:()=>generation,parentSource:()=>parentSource,
 captureParent:()=>JSON.parse(JSON.stringify(parentView)),readingIntent:()=>intent,beginRead:()=>{intent++;},
 api:async path=>{requests.push(path);return transport(path);},notice:text=>notices.push(text),
 reader:{show:async(target,options)=>{readers.push({target,options});return options.valid();}},
 returnParent:(view,context)=>returns.push({view,context})});
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {resolve,promise};};
'''


class LinkedAgentReadController(unittest.TestCase):
    def check(self, body):
        script = SETUP + '\n(async()=>{' + body + r'''
assert.equal(JSON.stringify(retained),before);assert(requests.every(path=>path.startsWith('/api/native/evidence-source?home=') && !path.includes('/api/open')));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''
        run = subprocess.run(['node', '-e', script, str(ROOT / 'codex_desk/static/linked-agent.js'), str(ROOT / 'codex_desk/static/linked-agent-read.js')], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_one_exact_read_and_full_original_returns_to_captured_parent(self):
        self.check(r'''
assert(await controller.open(targets[0]));assert.equal(requests.length,1);assert.equal(readers.length,1);
assert.equal(new URL(requests[0],'http://local').searchParams.get('thread'),'child-1');
assert.equal(readers[0].options.preloadedThread.turns[0].status,'failed');assert.equal(readers[0].options.preloadedThread.turns[0].items[0].phase,'commentary');
assert.equal(readers[0].options.backLabel,'Return to parent activity');readers[0].options.onReturn();
assert.deepEqual(returns[0].view,parentView);assert.equal(returns[0].context.target.owner.item_id,'parent-call');assert.equal(controller.state().target,null);
''')

    def test_held_original_cannot_replace_new_parent_owner_or_editor(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const reading=controller.open(targets[0]);await Promise.resolve();
current={...owner,session:'C',thread_id:'native-C'};generation++;intent++;
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert.equal(await reading,false);assert.equal(readers.length,0);assert.equal(returns.length,0);
''')

    def test_same_parent_later_reading_intent_wins_held_response(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const reading=controller.open(targets[0]);await Promise.resolve();intent++;
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert.equal(await reading,false);assert.equal(readers.length,0);
''')

    def test_closed_capture_cannot_open_or_restore_when_response_arrives(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const reading=controller.open(targets[0]);await Promise.resolve();controller.close();
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert.equal(await reading,false);assert.equal(readers.length,0);assert.equal(returns.length,0);
''')

    def test_newer_linked_agent_original_supersedes_older_read(self):
        self.check(r'''
const held=deferred(),ordinary=transport;transport=path=>new URL(path,'http://local').searchParams.get('thread')==='child-1'?held.promise:ordinary(path);
const earlier=controller.open(targets[0]);await Promise.resolve();assert(await controller.open(targets[1]));
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert.equal(await earlier,false);
assert.equal(readers.length,1);assert.equal(readers[0].target.thread_id,'child-2');
''')

    def test_retry_preserves_exact_target_and_original_parent_view(self):
        self.check(r'''
const ordinary=transport;transport=async()=>{throw Error('Native original unavailable');};assert.equal(await controller.open(targets[0]),false);
assert(controller.state().failed);parentView.windowTop=1600;transport=ordinary;
// Pointerdown on the explicit Retry action is a new reading intent, not a retarget.
intent++;assert(await controller.retry());
assert.equal(requests[0],requests[1]);readers[0].options.onReturn();assert.equal(returns[0].view.windowTop,930);
''')

    def test_changed_parent_relationship_is_unavailable_before_any_native_read(self):
        self.check(r'''
parentSource.turns[0].items[0].receiverThreadIds=['other-child'];assert.equal(await controller.open(targets[0]),false);
assert.equal(requests.length,0);assert(notices[0].includes('relationship_unavailable'));
''')

    def test_changed_home_or_wrong_child_never_appears_in_reader(self):
        self.check(r'''
transport=async()=>({home_namespace:'b'.repeat(64),thread:{id:'child-1',turns:[]}});assert.equal(await controller.open(targets[0]),false);assert(controller.state().failed);
transport=async()=>({home_namespace:owner.native_home,thread:{id:'child-2',turns:[]}});assert.equal(await controller.retry(),false);assert.equal(readers.length,0);
''')

    def test_reading_inside_loaded_child_keeps_original_and_parent_return_valid(self):
        self.check(r'''
assert(await controller.open(targets[0]));intent++;assert(readers[0].options.valid());
readers[0].options.onReturn();assert.equal(returns.length,1);assert.deepEqual(returns[0].view,parentView);
''')

    def test_changed_relationship_while_get_held_never_opens_stale_child(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const reading=controller.open(targets[0]);await Promise.resolve();
parentSource.turns[0].items[0].receiverThreadIds=['child-2'];
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert.equal(await reading,false);assert.equal(readers.length,0);
assert(controller.state().failed);assert(notices.at(-1).includes('relationship_unavailable'));
''')

    def test_loaded_original_refresh_uses_same_scoped_get_and_relationship_guard(self):
        self.check(r'''
assert(await controller.open(targets[0]));await readers[0].options.loadOriginal();assert.equal(requests[0],requests[1]);
parentSource.turns[0].items[0].receiverThreadIds=['child-2'];
await assert.rejects(readers[0].options.loadOriginal(),/relationship_unavailable/);assert.equal(requests.length,2);
''')

    def test_exported_active_target_cannot_retarget_an_inflight_capture(self):
        self.check(r'''
const held=deferred();transport=()=>held.promise;const reading=controller.open(targets[0]);await Promise.resolve();
const exported=controller.state().target;exported.child_thread_id='child-2';exported.owner.item_id='other-call';
assert.equal(controller.state().target.child_thread_id,'child-1');assert.equal(controller.state().target.owner.item_id,'parent-call');
held.resolve({home_namespace:owner.native_home,thread:{id:'child-1',turns:[]}});assert(await reading);
assert.equal(readers[0].target.thread_id,'child-1');
''')

    def test_return_callback_cannot_move_new_owner(self):
        self.check(r'''
assert(await controller.open(targets[0]));current={...owner,session:'B'};generation++;intent++;
readers[0].options.onReturn();assert.equal(returns.length,0);
''')


if __name__ == '__main__':
    unittest.main()
