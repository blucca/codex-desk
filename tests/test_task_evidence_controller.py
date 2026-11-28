"""Same-reader task evidence identity, exact source spans and stale action guards."""
from pathlib import Path
import json,shutil,subprocess,unittest
R=Path(__file__).resolve().parents[1]
S=(R/'codex_desk/static/history_reader.js').read_text()
CONTROLLER=S[S.index('  function taskEvidenceScoped()'):S.index('  function taskSnapshot()')]
FIND=S[S.index('  async function submitFind('):S.index('  function markText(')]
@unittest.skipUnless(shutil.which('node'),'Node required')
class TaskEvidenceControllerTests(unittest.TestCase):
 def check(self,body):
  head=r'''
const assert=require('assert/strict');global.DeskHistoryTasks=require(TASKS);global.DeskHistoryFind=require(FIND);const root={DeskTaskEvidence:require(EVIDENCE),DeskHistoryFind:global.DeskHistoryFind};
const sourceA=()=>({id:'A',turns:['before','chosen','after'].map(id=>({id,status:'completed',items:[{id:'same',type:'commandExecution',aggregatedOutput:id+' Straße Café 项目 😀'}]}))});
let source=sourceA(),taskReview={capture:{thread_id:'A',turn_id:'chosen'},mode:'context',contextView:null},rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item}))),version=1,findVersion=0,live=true,loading=false,finding=false,findCursor=-1,findGroups=[],findTotal=0,findSubmitted=false,findQuery='',targetIndex=-1,page=0,requested={thread_id:'A'};
const PAGE_ENTRIES=40,visibleTypes=new Set(['commandExecution']),str=x=>typeof x==='string'?x:'',textFor=i=>i.aggregatedOutput;
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{children:[],dataset:{},value:'',append(...x){this.children.push(...x)},replaceChildren(){this.children=[]},focus(){},scrollTop:0});return elements.get(id);};
const node=(tag,text,cls)=>({tag,textContent:text,className:cls,children:[],dataset:{},append(...x){this.children.push(...x)},focus(){}});
const taskButton=(label,action,callback,disabled=false)=>({label,dataset:{taskAction:action},onclick:callback,disabled});
let view={items:new Map(),selection:{text:'exact',backward:true}},calls=[],restored;
const current=ticket=>live&&ticket===version,available=()=>live,captureView=()=>view,restoreView=v=>restored=v;
const render=(scroll,v)=>calls.push({scroll,v,mode:taskReview.mode}),findControls=()=>{},taskControls=()=>{},resetFind=()=>{++findVersion;findSubmitted=false;findGroups=[];findTotal=0;findCursor=-1;el('find-query').value='';};
const flatten=n=>n.children.flatMap(c=>[c,...(c.children?flatten(c):[])]);
function jumpFind(direction){findCursor=0;}function findMatch(){return null;}function itemNode(){return {};}function scrollMatch(){}function resetFindMatches(){}
'''.replace('TASKS',json.dumps(str(R/'codex_desk/static/history_tasks.js'))).replace('FIND',json.dumps(str(R/'codex_desk/static/history_find.js'))).replace('EVIDENCE',json.dumps(str(R/'codex_desk/static/task-evidence.js')))
  result=subprocess.run(['node','-e',head+CONTROLLER+FIND+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1});'],capture_output=True,text=True,timeout=15)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr)
 def test_open_scope_exact_capture_and_one_item_same_native_id(self):
  self.check("assert(openTaskEvidence());const state=taskReview.evidence;assert.deepEqual(state.capture,{thread_id:'A',turn_id:'chosen'});assert(taskEvidenceScoped());assert(readTaskEvidenceItem(0));assert.equal(targetIndex,1);assert.deepEqual(requested,{thread_id:'A',turn_id:'chosen',item_id:'same'});assert(taskReview.evidenceItem);assert.equal(state.chosen,'same');")
 def test_exact_evidence_page_and_item_view_return(self):
  self.check("openTaskEvidence();const state=taskReview.evidence;state.page=0;const listView=view;readTaskEvidenceItem(0);view={items:new Map([[JSON.stringify(['chosen','same']),{}]]),selection:{text:'native quote',backward:true},outer:55};const itemView=view;assert(returnTaskEvidence());assert.strictEqual(calls.at(-1).v,listView);assert.strictEqual(state.itemView,itemView);assert(readTaskEvidenceItem(0));assert.strictEqual(calls.at(-1).v,itemView);")
 def test_refresh_missing_turn_keeps_capture_empty_and_no_neighbor(self):
  self.check("openTaskEvidence();const state=taskReview.evidence;source={id:'A',turns:source.turns.filter(t=>t.id!=='chosen')};const r=taskEvidenceResult(state);assert.equal(r.reason,'turn_unavailable');assert.equal(state.capture.turn_id,'chosen');assert.equal(r.items.length,0);assert(!readTaskEvidenceItem(0));")
 def test_detached_row_after_new_query_cannot_choose(self):
  self.check("openTaskEvidence();renderTaskEvidence();const button=flatten(el('body')).find(n=>n.dataset?.taskAction===taskEvidenceAction({item_id:'same'}));assert(button);++findVersion;button.onclick();assert.equal(taskReview.mode,'evidence');assert.equal(targetIndex,-1);")
 def test_detached_row_after_source_or_close_cannot_choose(self):
  self.check("openTaskEvidence();renderTaskEvidence();const button=flatten(el('body')).find(n=>n.dataset?.taskAction===taskEvidenceAction({item_id:'same'}));source=sourceA();button.onclick();assert.equal(taskReview.mode,'evidence');live=false;button.onclick();assert.equal(targetIndex,-1);")
 def test_task_find_exact_utf16_span_only_chosen_vs_original_control(self):
  self.check("openTaskEvidence();el('find-query').value='STRASSE Cafe\\u0301 项目 😀';await submitFind();assert.equal(findTotal,1);assert.equal(findGroups[0].index,1);const span=findGroups[0].spans.at(0);assert.equal(textFor(rows[1].item).slice(span.start,span.end),'Straße Café 项目 😀');taskReview.evidence.scope='original';el('find-query').value='STRASSE Cafe\\u0301 项目 😀';await submitFind();assert.equal(findTotal,3);assert.deepEqual(findGroups.map(g=>g.index),[0,1,2]);")
 def test_fresh_insert_relocates_exact_focused_item_page_not_neighbor(self):
  self.check("source={id:'A',turns:[{id:'chosen',items:Array.from({length:45},(_,i)=>({id:'i'+i,type:'commandExecution',aggregatedOutput:'native '+i}))}]};rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));openTaskEvidence();const state=taskReview.evidence;state.page=1;const key=taskEvidenceAction({item_id:'i39'});const saved={items:new Map(),taskFocus:key,outer:12};source={...source,turns:[{...source.turns[0],items:[{id:'inserted',type:'commandExecution',aggregatedOutput:'insert'},...source.turns[0].items]}]};rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));renderTaskEvidence(false,saved);assert.equal(state.page,2);const button=flatten(el('body')).find(n=>n.dataset?.taskAction===key);assert(button);button.onclick();assert.equal(requested.item_id,'i39');")
 def test_newer_query_while_async_search_discards_old_spans(self):
  self.check("openTaskEvidence();el('find-query').value='chosen';let release,entered;const original=root.DeskHistoryFind.spansAsync;root.DeskHistoryFind={...root.DeskHistoryFind,spansAsync:async(text,q,valid)=>{entered=true;await new Promise(r=>release=r);return original(text,q,valid)}};const pending=submitFind();await new Promise(r=>setTimeout(r,10));assert(entered);el('find-query').value='newer unsent';++findVersion;findSubmitted=false;finding=false;release();await pending;assert.equal(findTotal,0);assert.equal(el('find-query').value,'newer unsent');")
if __name__=='__main__':unittest.main()
