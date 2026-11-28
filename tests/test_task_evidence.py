"""Selected supplied-task item scope, bounded previews, no original mutation."""
from pathlib import Path
import shutil,subprocess,unittest
ROOT=Path(__file__).resolve().parents[1]
@unittest.skipUnless(shutil.which('node'),'Node required')
class TaskEvidenceTests(unittest.TestCase):
 def check(self,body):
  head="const assert=require('assert/strict');global.DeskHistoryTasks=require("+repr(str(ROOT/'codex_desk/static/history_tasks.js'))+");const E=require("+repr(str(ROOT/'codex_desk/static/task-evidence.js'))+");const read=i=>['userMessage','agentMessage','commandExecution'].includes(i.type),project=i=>i.text||i.aggregatedOutput||'';const capture={thread_id:'A',turn_id:'chosen'};"
  r=subprocess.run(['node','-e',head+body],capture_output=True,text=True,timeout=15);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_exact_turn_no_neighbor_or_whole_original_search(self):
  self.check("const thread={id:'A',turns:[{id:'before',items:[{id:'same',type:'commandExecution',aggregatedOutput:'neighbor'}]},{id:'chosen',status:'inProgress',items:[{id:'same',type:'commandExecution',aggregatedOutput:'chosen'}]},{id:'after',items:[{id:'same',type:'commandExecution',aggregatedOutput:'neighbor'}]}]};const before=JSON.stringify(thread);const result=E.list(thread,capture,project,read);assert.equal(result.total,1);assert.equal(result.items[0].preview,'chosen');assert.equal(result.turn_status,'inProgress');assert.equal(JSON.stringify(thread),before);")
 def test_many_items_page_and_preview_boundaries(self):
  self.check("const thread={id:'A',turns:[{id:'chosen',items:Array.from({length:47},(_,i)=>({id:'i'+i,type:'agentMessage',text:'😀'.repeat(200)}))}]};const r=E.list(thread,capture,project,read);assert.equal(r.items.length,47);assert(r.items.every(i=>i.preview.length<=180&&!Object.hasOwn(i,'text')));assert.equal(E.page(r,1).items.length,20);assert.equal(E.page(r,1).items[0].item_id,'i20');assert.equal(E.page(r,2).items.length,7);assert.equal(E.page(r,999).index,2);assert.throws(()=>E.page(r,-1));")
 def test_duplicate_item_identity_unavailable_no_substitution(self):
  self.check("const r=E.list({id:'A',turns:[{id:'chosen',items:[{id:'dup',type:'agentMessage',text:'one'},{id:'dup',type:'commandExecution',aggregatedOutput:'two'}]}]},capture,project,read);assert.equal(r.readable_count,0);assert(r.items.every(i=>i.reason==='ambiguous_item'&&i.preview==='')); ")
 def test_missing_and_ambiguous_turn_keep_capture(self):
  self.check("for(const turns of [[],[{id:'chosen',items:[]},{id:'chosen',items:[]}]]){const r=E.list({id:'A',turns},capture,project,read);assert(!r.available);assert.equal(r.turn_id,'chosen');assert.equal(r.items.length,0);}assert.throws(()=>E.list({id:'B',turns:[]},capture,project,read));")
 def test_empty_error_and_items_not_supplied_are_distinct(self):
  self.check("const error={message:'actual native error'};const r=E.list({id:'A',turns:[{id:'chosen',status:'failed',error,items:[]}]},capture,project,read);assert(r.available);assert.equal(r.total,0);assert.equal(r.turn_status,'failed');assert.equal(r.turn_error,error);assert.equal(E.page(r).pages,1);const absent=E.list({id:'A',turns:[{id:'chosen'}]},capture,project,read);assert.equal(absent.status,'items_unavailable');assert.equal(absent.turn_status,null);")
 def test_unsupported_and_missing_items_remain_rows(self):
  self.check("const r=E.list({id:'A',turns:[{id:'chosen',items:[null,{id:'u',type:'futureNativeItem'},{type:'agentMessage',text:'bad id'},{id:'blank',type:'agentMessage',text:'  '},{id:'ok',type:'agentMessage',text:'actual'}]}]},capture,project,read);assert.equal(r.total,5);assert.equal(r.readable_count,1);assert.deepEqual(r.items.map(i=>i.reason),['item_unavailable','unsupported_item','invalid_item_id','text_unavailable',null]);assert.equal(r.items[1].item_type,'futureNativeItem');")
if __name__=='__main__':unittest.main()
