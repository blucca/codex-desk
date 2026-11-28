"""The paired reader retires old evidence captures and item mode on task overview."""
from pathlib import Path
import json,os,shutil,subprocess,unittest
R=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1]))
S=(R/'codex_desk/static/history_reader.js').read_text()
CONTEXT=S[S.index('  function openTaskContext('):S.index('  function taskButton(')]
EVIDENCE=S[S.index('  function taskEvidenceScoped()'):S.index('  function taskSnapshot(')]
OVERVIEW=S[S.index('  function taskOverviewState()'):S.index('  function chooseOverviewTask(')]
@unittest.skipUnless(shutil.which('node'),'Node required')
class TaskUnionEvidenceResetTests(unittest.TestCase):
 def check(self,body):
  head=r'''
const assert=require('assert/strict');global.DeskHistoryFind=require(FIND);global.DeskHistoryTasks=require(TASKS);const root={DeskHistoryTasks:global.DeskHistoryTasks,DeskTaskEvidence:require(EVIDENCE)};
let source={id:'A',turns:[{id:'old',items:[{id:'same',type:'commandExecution',aggregatedOutput:'OLD source'}]},{id:'new',items:[{id:'same',type:'commandExecution',aggregatedOutput:'NEW source'}]}]},taskReview={capture:{thread_id:'A',turn_id:'old'},mode:'item',evidenceItem:true,evidence:{capture:{thread_id:'A',turn_id:'old'},scope:'task'}},findVersion=0,finding=false,findSubmitted=false,findGroups=[],findTotal=0,findCursor=-1,loading=false;
const visibleTypes=new Set(['commandExecution']),textFor=i=>i.aggregatedOutput,available=()=>true,captureView=()=>({items:new Map()}),findControls=()=>{},resetFind=()=>{},render=()=>{},taskSnapshot=()=>{};
const el=()=>({value:'',hidden:false}),str=x=>typeof x==='string'?x:'';let version=1;
'''.replace('FIND',json.dumps(str(R/'codex_desk/static/history_find.js'))).replace('TASKS',json.dumps(str(R/'codex_desk/static/history_tasks.js'))).replace('EVIDENCE',json.dumps(str(R/'codex_desk/static/task-evidence.js')))
  result=subprocess.run(['node','-e',head+EVIDENCE+CONTEXT+OVERVIEW+body],capture_output=True,text=True,timeout=10)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
 def test_new_context_retires_old_evidence_then_uses_exact_new_native_item(self):
  self.check("const old=taskReview.evidence;assert(openTaskContext({thread_id:'A',turn_id:'new'}));assert.equal(taskReview.evidence,null);assert(!taskReview.evidenceItem);assert(openTaskEvidence());assert.notStrictEqual(taskReview.evidence,old);assert.deepEqual(taskReview.evidence.capture,{thread_id:'A',turn_id:'new'});assert.equal(taskReview.evidence.result.items[0].preview,'NEW source');")
 def test_stale_evidence_capture_is_cleared_even_if_context_already_names_new_turn(self):
  self.check("taskReview.capture={thread_id:'A',turn_id:'new'};assert(openTaskContext(taskReview.capture));assert.equal(taskReview.evidence,null);assert(!taskReview.evidenceItem);openTaskEvidence();assert.equal(taskReview.evidence.result.items[0].preview,'NEW source');")
 def test_stale_thread_capture_is_cleared_for_same_native_turn_name(self):
  self.check("taskReview.capture={thread_id:'A',turn_id:'old'};taskReview.evidence.capture.thread_id='previous-thread';openTaskContext(taskReview.capture);assert.equal(taskReview.evidence,null);openTaskEvidence();assert.equal(taskReview.evidence.capture.thread_id,'A');")
 def test_show_overview_retires_evidence_full_item_mode(self):
  self.check("assert(showTaskOverview());assert.equal(taskReview.mode,'overview');assert(!taskReview.evidenceItem);assert(!taskEvidenceScoped());")
if __name__=='__main__':unittest.main()
