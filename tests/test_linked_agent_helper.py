"""Pure exact native relationship capture; no controller, storage or network."""
import subprocess
import unittest
from pathlib import Path

HELPER = Path(__file__).resolve().parents[1] / 'codex_desk/static/linked-agent.js'
PRELUDE = r'''
const assert=require('assert/strict'),L=require(process.argv[1]);
const A={native_home:'a'.repeat(64),session:'saved-A',thread_id:'native-A',turn_id:'turn-A',item_id:'parent-call'};
const item={id:A.item_id,type:'collabAgentToolCall',tool:'spawnAgent',receiverThreadIds:['child-1','child-2'],
 agentsStates:{'child-2':{status:'completed',message:'Native reported output.'},'child-3':{status:'errored'}}};
const source=()=>({id:A.thread_id,turns:[{id:A.turn_id,items:[JSON.parse(JSON.stringify(item))]}]});
const captured=()=>L.capture(A,item).targets[0];
'''


class LinkedAgentHelper(unittest.TestCase):
    def check(self, body):
        run = subprocess.run(['node', '-e', PRELUDE + body, str(HELPER)], capture_output=True, text=True, timeout=10)
        self.assertEqual(run.returncode, 0, run.stderr)

    def test_receivers_and_native_state_map_deduplicate_exact_ids_and_provenance(self):
        self.check(r'''
const result=L.capture(A,item);assert.equal(result.status,'available');
assert.deepEqual(result.targets.map(t=>[t.child_thread_id,t.relationships]),[
 ['child-1',['receiverThreadIds']],['child-2',['receiverThreadIds','agentsStates']],['child-3',['agentsStates']]]);
assert.equal(result.targets[0].item_type,'collabAgentToolCall');assert.deepEqual(result.targets[0].owner,A);
''')

    def test_sub_agent_activity_uses_only_actual_agent_thread_id(self):
        self.check(r'''
const result=L.capture(A,{id:A.item_id,type:'subAgentActivity',agentThreadId:'actual-child',agentPath:'guess/other-child',receiverThreadIds:['not-supported-here']});
assert.deepEqual(result.targets.map(t=>t.child_thread_id),['actual-child']);
assert.deepEqual(result.targets[0].relationships,['agentThreadId']);
''')

    def test_no_topology_inference_from_prompt_sender_path_or_similar_text(self):
        self.check(r'''
const result=L.capture(A,{id:A.item_id,type:'collabAgentToolCall',senderThreadId:'child-from-sender',agentThreadId:'not-supported-here',prompt:'Read child-from-prompt',agentPath:'child-from-path'});
assert.equal(result.status,'relationship_unavailable');assert.deepEqual(result.targets,[]);
''')

    def test_invalid_and_self_ids_and_application_meta_are_not_targets(self):
        self.check(r'''
item.receiverThreadIds=[A.thread_id,'',null,' '.repeat(4),'x'.repeat(201),'actual-child','actual-child'];
item.agentsStates={_meta:{name:'not-a-child'},[A.thread_id]:{},'':{},'actual-child':null};
assert.deepEqual(L.capture(A,item).targets.map(t=>t.child_thread_id),['actual-child']);
''')

    def test_unsupported_or_wrong_parent_item_is_unavailable(self):
        self.check(r'''
assert.equal(L.capture(A,{...item,type:'commandExecution'}).status,'unsupported_item');
assert.equal(L.capture(A,{...item,id:'other-call'}).status,'parent_item_mismatch');
assert.throws(()=>L.capture({...A,native_home:'/path'},item));
assert.throws(()=>L.capture({...A,turn_id:''},item));
''')

    def test_capture_is_immutable_detached_and_contains_identity_only(self):
        self.check(r'''
const result=L.capture(A,item),raw=JSON.stringify(result);item.receiverThreadIds[0]='later-child';A.session='new-owner';
assert.equal(result.targets[0].child_thread_id,'child-1');assert.equal(result.owner.session,'saved-A');
assert(Object.isFrozen(result.targets[0]) && Object.isFrozen(result.targets[0].owner));
assert(!raw.includes('Native reported output'));assert(!raw.includes('errored'));assert(!raw.includes('spawnAgent'));
''')

    def test_fresh_exact_parent_relationship_is_required(self):
        self.check(r'''
const request=captured(),native=source();assert(L.resolveParent(A,request,native).available);
for(const change of [{native_home:'b'.repeat(64)},{session:'saved-B'},{thread_id:'native-B'},{turn_id:'other-turn'},{item_id:'other-call'}])
 assert(!L.resolveParent({...A,...change},request,native).available);
native.turns[0].items[0].receiverThreadIds=['other-child'];assert.equal(L.resolveParent(A,request,native).status,'relationship_unavailable');
''')

    def test_moved_item_equal_id_in_another_turn_never_substitutes(self):
        self.check(r'''
const request=captured(),native=source(),moved=native.turns[0].items.pop();native.turns.push({id:'other-turn',items:[moved]});
assert.equal(L.resolveParent(A,request,native).status,'parent_item_unavailable');
''')

    def test_ambiguous_parent_turn_or_item_is_unavailable(self):
        self.check(r'''
const request=captured(),native=source();native.turns.push(native.turns[0]);assert.equal(L.resolveParent(A,request,native).status,'parent_turn_ambiguous');
native.turns.pop();native.turns[0].items.push({...item});assert.equal(L.resolveParent(A,request,native).status,'parent_item_ambiguous');
''')

    def test_parent_type_change_is_unavailable_even_if_child_id_equal(self):
        self.check(r'''
const request=captured(),native=source();native.turns[0].items[0]={id:A.item_id,type:'subAgentActivity',agentThreadId:'child-1'};
assert.equal(L.resolveParent(A,request,native).status,'parent_item_type_changed');
''')

    def test_child_original_requires_captured_namespace_and_native_thread(self):
        self.check(r'''
const request=captured();assert(L.resolveOriginal(request,{native_home:A.native_home,thread:{id:'child-1',turns:[]}}).available);
assert.equal(L.resolveOriginal(request,{native_home:'b'.repeat(64),thread:{id:'child-1',turns:[]}}).status,'home_mismatch');
assert.equal(L.resolveOriginal(request,{native_home:A.native_home,thread:{id:'child-2',turns:[]}}).status,'child_thread_mismatch');
assert.equal(L.resolveOriginal(request,{native_home:A.native_home,thread:{id:'child-1'}}).status,'child_source_unavailable');
''')

    def test_native_outcome_and_response_phase_remain_unmodified_source_facts(self):
        self.check(r'''
const child={id:'child-1',turns:[{id:'child-turn',status:'failed',error:{message:'Native failure'},items:[{id:'answer',type:'agentMessage',phase:'commentary',text:'Native supplied partial result.'}]}]};
const before=JSON.stringify(child);assert(L.resolveOriginal(captured(),{native_home:A.native_home,thread:child}).available);
assert.equal(JSON.stringify(child),before);assert.equal(child.turns[0].status,'failed');
''')


if __name__ == '__main__':
    unittest.main()
