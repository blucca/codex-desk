"""Fresh task-evidence Find uses the same exact eligible source rows as submit."""
import unittest
import test_task_evidence_controller as controls
S=controls.S
REFRESH=S[S.index('  async function refreshFind('):S.index('  async function refresh()')]
class TaskEvidenceRefreshTests(unittest.TestCase):
 def check(self,body):
  controls.TaskEvidenceControllerTests().check("function preserveChrome(fn){fn();}function renewFindMatches(){return null;}function findMatchesControls(){}"+S[S.index('  function rowKey('):S.index('  function itemNode(')]+REFRESH+body)
 def test_scope_refresh_retains_ordinal_exact_utf16_and_original_control(self):
  self.check(r"""openTaskEvidence();el('find-query').value='STRASSE Cafe\u0301 项目 😀';await submitFind();
const old=findGroups[0].spans.at(0),anchor={key:JSON.stringify(['chosen','same']),...old};
await refreshFind(el('find-query').value,anchor,version);assert.equal(findTotal,1);assert.equal(findCursor,0);assert.equal(findGroups[0].index,1);
assert.deepEqual(findGroups[0].spans.at(0),old);assert.equal(textFor(rows[1].item).slice(old.start,old.end),'Straße Café 项目 😀');
taskReview.evidence.scope='original';await refreshFind(el('find-query').value,anchor,version);assert.equal(findTotal,3);assert.equal(findCursor,1);assert.deepEqual(findGroups.map(g=>g.index),[0,1,2]);""")
 def test_fresh_changed_phrase_does_not_reuse_neighbor_match(self):
  self.check("openTaskEvidence();el('find-query').value='Straße';await submitFind();const old=findGroups[0].spans.at(0);rows[1].item.aggregatedOutput='changed actual chosen output';await refreshFind('Straße',{key:JSON.stringify(['chosen','same']),...old},version);assert.equal(findTotal,0);assert.equal(findCursor,-1);assert.equal(taskReview.evidence.capture.turn_id,'chosen');")
 def test_missing_and_ambiguous_task_return_empty_without_borrowing(self):
  self.check("openTaskEvidence();const chosen=source.turns[1];source.turns=source.turns.filter(t=>t.id!=='chosen');rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));await refreshFind('Straße',null,version);assert.equal(findTotal,0);source.turns.push(chosen,{...chosen});rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));await refreshFind('Straße',null,version);assert.equal(findTotal,0);assert.equal(taskReview.evidence.capture.turn_id,'chosen');")
 def test_duplicate_item_ids_are_not_addressable_in_fresh_scoped_find(self):
  self.check("openTaskEvidence();source.turns[1].items.push({...source.turns[1].items[0]});rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));await refreshFind('Straße',null,version);assert.equal(findTotal,0);el('find-query').value='Straße';await submitFind();assert.equal(findTotal,0);")
 def test_unreadable_and_missing_item_stay_out_of_scoped_search(self):
  self.check("openTaskEvidence();source.turns[1].items=[{id:'unsupported',type:'unsupported',aggregatedOutput:'Straße'}];rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));await refreshFind('Straße',null,version);assert.equal(findTotal,0);source.turns[1].items=[];rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));await refreshFind('Straße',null,version);assert.equal(findTotal,0);")
 def test_pending_query_supersession_discards_refreshed_results(self):
  self.check("openTaskEvidence();el('find-query').value='Straße';let release;root.DeskHistoryFind={...root.DeskHistoryFind,spansAsync:async()=>{await new Promise(r=>release=r);return {length:1}}};const pending=refreshFind('Straße',null,version);await new Promise(r=>setTimeout(r,10));++findVersion;el('find-query').value='newer unsent';finding=false;release();await pending;assert.equal(findTotal,0);assert.equal(el('find-query').value,'newer unsent');")
if __name__=='__main__':unittest.main()
