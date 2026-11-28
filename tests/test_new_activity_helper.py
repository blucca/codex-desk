"""Captured parent-native event boundaries, separate from fetched/read-position state."""
import subprocess
import unittest
from pathlib import Path


HELPER = Path(__file__).resolve().parents[1] / 'codex_desk/static/new-activity.js'
PRELUDE = r'''
const assert=require('node:assert/strict'),N=require(process.argv[1]);
const A={native_home:'a'.repeat(64),session:'A',thread_id:'native-A'};
const B={native_home:'a'.repeat(64),session:'B',thread_id:'native-B'};
const event=(seq,item='answer',method='item/agentMessage/delta',extra={})=>({seq,event:{method,
  params:{threadId:A.thread_id,turnId:'turn-1',itemId:item,delta:'More native output',...extra}}});
const memory=()=>{const data=new Map();return {data,getItem:key=>data.get(key)??null,setItem:(key,value)=>data.set(key,value)};};
const source=(target,extra={})=>({...A,turn_ids:[target.turn_id],items:[{turn_id:target.turn_id,
  item_id:target.item_id,item_type:target.item_type}],...extra});
'''


class NewActivityHelper(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(['node', '-e', PRELUDE + script, str(HELPER)],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_first_capture_seeds_old_backlog_once(self):
        self.run_js(r'''
const store=N.create(memory()),first=N.capture(A,[event(1),event(3,'old-tool')]);
assert.equal(store.pending(A,first).status,'baseline_missing');
assert.equal(store.seed(A,first).review.reviewed_seq,3);
assert.equal(store.pending(A,first).status,'up_to_date');
assert.equal(store.seed(A,N.capture(A,[event(4)])).status,'baseline_exists');
assert.equal(store.pending(A,N.capture(A,[event(4)])).first.item_id,'answer');
''')

    def test_distinct_changed_item_targets_not_delta_counts(self):
        self.run_js(r'''
const batch=N.capture(A,[event(11,'command','item/commandExecution/outputDelta'),event(12,'command',
  'item/commandExecution/outputDelta'),event(13,'answer'),event(14,'command','item/commandExecution/outputDelta')]);
const pending=N.pending(A,batch,10);
assert.equal(pending.targets.length,2);
assert.deepEqual(pending.targets.map(t=>[t.item_id,t.first_seq,t.last_seq]),[['command',11,14],['answer',13,13]]);
assert.equal(pending.first.item_type,'commandExecution');
''')

    def test_only_existing_rendered_parent_item_methods(self):
        self.run_js(r'''
for(const [method,type,field] of [['item/agentMessage/delta','agentMessage','delta'],
 ['item/commandExecution/outputDelta','commandExecution','delta'],['item/plan/delta','plan','delta'],
 ['item/mcpToolCall/progress','mcpToolCall','message']]) {
  const row=event(1,'same',method,{[field]:'new'});
  assert.equal(N.classify(A,row).item_type,type);
  assert.equal(N.classify(A,event(1,'same',method,{[field]:''})),null);
}
for(const type of ['commandExecution','fileChange','mcpToolCall','dynamicToolCall','collabAgentToolCall','subAgentActivity'])
  assert.equal(N.classify(A,event(1,'same','item/completed',{item:{id:'same',type}})).item_type,type);
assert.equal(N.classify(A,event(1,'same','item/started',{item:{id:'same',type:'agentMessage',text:''}})),null);
assert.equal(N.classify(A,event(1,'same','item/completed',{item:{id:'same',type:'plan',text:'Plan'}})).item_type,'plan');
''')

    def test_native_user_text_only_and_unsupported_items_stay_uncounted(self):
        self.run_js(r'''
const item={id:'same',type:'userMessage',content:[{type:'image',text:'not native user text'}]};
assert.equal(N.classify(A,event(1,'same','item/completed',{item})),null);
item.content.push({type:'text',text:'Instruction'});
assert.equal(N.classify(A,event(1,'same','item/completed',{item})).item_type,'userMessage');
assert.equal(N.classify(A,event(1,'same','item/completed',{item:{id:'same',type:'reasoning',text:'hidden'}})),null);
''')

    def test_child_missing_thread_requests_and_wrong_route_do_not_count(self):
        self.run_js(r'''
for(const extra of [{threadId:'child'},{threadId:undefined},{turnId:''},{itemId:''}])
  assert.equal(N.classify(A,event(1,'answer',undefined,extra)),null);
const request=event(1);request.event.id=0;assert.equal(N.classify(A,request),null);
const foreign=event(1);foreign.session_id='B';assert.equal(N.classify(A,foreign),null);
assert.equal(N.classify(A,event(1,'conflict','item/completed',{item:{id:'another',type:'commandExecution'}})),null);
''')

    def test_outcome_snapshot_title_status_approvals_and_usage_are_not_new_output(self):
        self.run_js(r'''
let seq=1;const rows=[];
for(const method of ['desk/nativeTaskSnapshot','turn/started','turn/completed','thread/name/updated',
  'thread/tokenUsage/updated','serverRequest/resolved','item/commandExecution/requestApproval',
  'item/tool/requestUserInput','error']) rows.push(event(seq++,'answer',method));
const batch=N.capture(A,rows);assert.equal(batch.received_seq,9);assert.equal(batch.frontier,0);
assert.equal(N.pending(A,batch,0).status,'up_to_date');
''')

    def test_read_capture_and_replay_do_not_mark_review(self):
        self.run_js(r'''
const store=N.create(memory());store.seed(A,N.capture(A,[event(10)]));
const captured=N.capture(A,[event(11),event(12)]);
for(let i=0;i<3;i++)assert.equal(store.pending(A,captured).first.first_seq,11);
const replay=N.capture(A,[event(1,'old'),event(10),event(11),event(12)]);
assert.equal(store.pending(A,replay).first.first_seq,11);assert.equal(store.get(A).reviewed_seq,10);
''')

    def test_explicit_review_uses_captured_material_frontier_not_latest_fetch(self):
        self.run_js(r'''
const store=N.create(memory());store.seed(A,N.capture(A,[event(10)]));
const displayed=N.capture(A,[event(11),event(12,'ignored','thread/tokenUsage/updated')]);
const arrived=N.capture(A,[event(11),event(12,'ignored','thread/tokenUsage/updated'),event(13,'newer')]);
assert.equal(store.mark(A,displayed).review.reviewed_seq,11);
assert.equal(store.pending(A,arrived).first.first_seq,13);
store.mark(A,arrived);store.mark(A,displayed);assert.equal(store.get(A).reviewed_seq,13);
''')

    def test_mark_needs_baseline_and_empty_capture_does_not_roll_it_back(self):
        self.run_js(r'''
const store=N.create(memory()),empty=N.capture(A,[]);
assert.equal(store.mark(A,empty).status,'baseline_missing');
store.seed(A,N.capture(A,[event(7)]));store.mark(A,empty);assert.equal(store.get(A).reviewed_seq,7);
''')

    def test_same_source_identity_required_for_capture_and_mark(self):
        self.run_js(r'''
const store=N.create(memory()),batch=N.capture(A,[event(1)]);store.seed(A,batch);
for(const changed of [B,{...A,native_home:'b'.repeat(64)},{...A,thread_id:'new-thread'}]) {
  assert.throws(()=>store.seed(changed,batch));assert.throws(()=>store.mark(changed,batch));
  assert.equal(store.get(changed),null);
}
assert.equal(store.get(A).reviewed_seq,1);
''')

    def test_cold_retention_contains_only_owner_and_review_sequence(self):
        self.run_js(r'''
const storage=memory(),store=N.create(storage);store.seed(A,N.capture(A,[event(9)]));
store.mark(A,N.capture(A,[event(10,'secret-body')]));
const raw=storage.getItem(N.STORAGE_KEY),saved=JSON.parse(raw);
assert.deepEqual(Object.keys(saved),['version','reviews']);
assert.deepEqual(Object.keys(saved.reviews[0]),['owner','reviewed_seq']);
assert.deepEqual(Object.keys(saved.reviews[0].owner),['native_home','session','thread_id']);
assert(!raw.includes('secret-body'));assert(!raw.includes('More native output'));
assert.equal(N.create(storage).get(A).reviewed_seq,10);
assert.equal(N.create(storage).pending(A,N.capture(A,[event(11)])).first.first_seq,11);
''')

    def test_two_tab_stale_mark_cannot_regress_boundary(self):
        self.run_js(r'''
const storage=memory(),one=N.create(storage),two=N.create(storage);
one.seed(A,N.capture(A,[event(1)]));two.mark(A,N.capture(A,[event(9)]));
one.mark(A,N.capture(A,[event(4)]));assert.equal(two.get(A).reviewed_seq,9);
''')

    def test_storage_failure_keeps_current_page_metadata_and_cold_has_no_baseline(self):
        self.run_js(r'''
const storage={getItem:()=>{throw Error('denied')},setItem:()=>{throw Error('denied')}};
const store=N.create(storage);assert.equal(store.seed(A,N.capture(A,[event(1)])).stored,false);
assert.equal(store.pending(A,N.capture(A,[event(2)])).first.first_seq,2);
assert.equal(store.mark(A,N.capture(A,[event(2)])).stored,false);assert.equal(store.get(A).reviewed_seq,2);
assert.equal(N.create(storage).get(A),null);
''')

    def test_bounded_owners_and_corrupt_storage(self):
        self.run_js(r'''
const storage=memory(),store=N.create(storage);
for(let i=0;i<110;i++){const value={...A,session:'session-'+i};store.seed(value,N.capture(value,[]));}
assert.equal(store.read().reviews.length,100);assert.equal(store.get({...A,session:'session-0'}),null);
assert.equal(store.get({...A,session:'session-109'}).reviewed_seq,0);
assert(storage.getItem(N.STORAGE_KEY).length<=N.LIMITS.characters);
storage.setItem(N.STORAGE_KEY,'not JSON');assert.equal(N.create(storage).read().status,'invalid_storage');
storage.setItem(N.STORAGE_KEY,'x'.repeat(N.LIMITS.characters+1));assert.equal(N.create(storage).get(A),null);
''')

    def test_invalid_sequences_order_and_cross_session_batch_are_rejected(self):
        self.run_js(r'''
for(const seq of [-1,0,1.5,Number.MAX_SAFE_INTEGER+1,NaN])assert.throws(()=>N.capture(A,[event(seq)]));
assert.throws(()=>N.capture(A,[event(2),event(1)]));assert.throws(()=>N.capture(A,[event(1),event(1)]));
const foreign=event(1);foreign.session_id='B';assert.throws(()=>N.capture(A,[foreign]));
assert.throws(()=>N.capture({...A,native_home:'path'},[]));
assert.throws(()=>N.pending(A,N.capture(A,[]),-1));
''')

    def test_exact_fresh_target_resolves_updated_earlier_item(self):
        self.run_js(r'''
const first=N.pending(A,N.capture(A,[event(2,'earlier-command','item/commandExecution/outputDelta'),event(3,'later-answer')]),1).first;
const fresh=source(first,{turn_ids:['old-turn',first.turn_id,'new-turn'],items:[
  {turn_id:'old-turn',item_id:'old-answer',item_type:'agentMessage'},
  {turn_id:first.turn_id,item_id:first.item_id,item_type:first.item_type},
  {turn_id:'new-turn',item_id:'later-answer',item_type:'agentMessage'}]});
assert.equal(N.resolveTarget(A,first,fresh).available,true);
assert.equal(N.resolveTarget(A,first,fresh).target.item_id,'earlier-command');
''')

    def test_immutable_merge_preserves_first_across_later_poll_and_replay(self):
        self.run_js(r'''
const initial=N.capture(A,[event(11,'command','item/commandExecution/outputDelta'),event(12,'command','item/commandExecution/outputDelta')]);
const later=N.capture(A,[event(13,'answer'),event(14,'command','item/commandExecution/outputDelta')]);
const combined=N.merge(A,10,initial,later,initial);
assert(Object.isFrozen(initial));assert(Object.isFrozen(initial.updates));assert(Object.isFrozen(initial.updates[0]));
assert.deepEqual(combined.updates.map(e=>e.seq),[11,12,13,14]);
assert.equal(N.pending(A,combined,10).first.first_seq,11);
assert.equal(N.pending(A,combined,12).first.first_seq,13);
assert.equal(N.pending(A,initial,10).frontier,12);
assert.throws(()=>N.merge(B,10,initial));
assert.throws(()=>N.merge(A,10,initial,N.capture(A,[event(11,'conflicting')])));
''')

    def test_repeated_review_and_held_mark_keep_earliest_new_update(self):
        self.run_js(r'''
const store=N.create(memory());store.seed(A,N.capture(A,[event(2)]));
const batch=N.capture(A,[event(2,'command','item/commandExecution/outputDelta'),event(15,'command',
 'item/commandExecution/outputDelta'),event(18,'answer'),event(20,'command','item/commandExecution/outputDelta')]);
assert.equal(N.pending(A,N.merge(A,2,batch),2).first.first_seq,15);
const changed=N.capture(A,[event(11,'command','item/commandExecution/outputDelta'),event(12,'command',
 'item/commandExecution/outputDelta'),event(14,'command','item/commandExecution/outputDelta')]);
store.mark(A,N.capture(A,[event(11,'command','item/commandExecution/outputDelta')]));
const remaining=N.merge(A,store.get(A).reviewed_seq,changed);
assert.equal(store.pending(A,remaining).first.first_seq,12);
''')

    def test_missing_ambiguous_and_changed_targets_are_not_replaced(self):
        self.run_js(r'''
const target=N.pending(A,N.capture(A,[event(2)]),1).first;
assert.equal(N.resolveTarget(A,target,source(target,{turn_ids:[]})).status,'turn_unavailable');
assert.equal(N.resolveTarget(A,target,source(target,{turn_ids:['turn-1','turn-1']})).status,'turn_ambiguous');
assert.equal(N.resolveTarget(A,target,source(target,{items:[]})).status,'item_unavailable');
const pair=source(target).items[0];
assert.equal(N.resolveTarget(A,target,source(target,{items:[pair,pair]})).status,'item_ambiguous');
assert.equal(N.resolveTarget(A,target,source(target,{items:[{...pair,item_type:'plan'}]})).status,'item_type_changed');
const similar={...pair,item_id:'same-text-different-item'};
assert.equal(N.resolveTarget(A,target,source(target,{items:[similar]})).available,false);
''')

    def test_target_owner_source_and_home_all_match(self):
        self.run_js(r'''
const target=N.pending(A,N.capture(A,[event(2)]),1).first;
for(const [extra,status] of [[{native_home:'b'.repeat(64)},'home_mismatch'],[{session:'B'},'session_mismatch'],
 [{thread_id:'another'},'thread_mismatch']])assert.equal(N.resolveTarget(A,target,source(target,extra)).status,status);
assert.equal(N.resolveTarget(A,{...target,owner:B},source(target)).status,'session_mismatch');
assert.equal(N.resolveTarget(A,target,source(target,{items:null})).status,'source_unavailable');
''')


if __name__ == '__main__':
    unittest.main()
