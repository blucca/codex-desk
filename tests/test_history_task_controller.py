"""Actual reader task transitions preserve exact native source and passage ownership."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'codex_desk/static/history_reader.js').read_text()
TASKS = SOURCE[SOURCE.index('  function commandOutputStart('):SOURCE.index('  function saveOriginalReading(')] + SOURCE[SOURCE.index('  function originalFrontierControls()'):SOURCE.index('  function originalReadingStore()')] + SOURCE[SOURCE.index('  function taskControls('):SOURCE.index('  function configure(')]
SETUP = r'''
let findMatches=null;
const assert=require('assert/strict'),root={DeskHistoryTasks:require(TASK_HELPER),DeskHistoryFind:require(FIND_HELPER)};
const document={activeElement:null};
class Element {
  constructor(tag,text='',cls=''){this.tag=tag;this.textContent=text;this.className=cls;this.children=[];this.dataset={};this.hidden=false;this.disabled=false;this.value='';this.scrollTop=0;}
  append(...children){this.children.push(...children);}replaceChildren(...children){this.children=children;}
  setAttribute(){}focus(){document.activeElement=this;}
}
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);};
const node=(tag,text,cls)=>new Element(tag,text,cls),str=value=>typeof value==='string'?value:'';
const user=(id,text)=>({id,type:'userMessage',content:[{type:'text',text}]}),answer=(id,text,phase='final_answer')=>({id,type:'agentMessage',text,phase});
const fillers=Array.from({length:45},(_,i)=>answer('detail-'+i,'Earlier same-turn detail '+i,'commentary'));
let source={id:'A',turns:[
 {id:'earlier',status:'completed',items:[user('earlier-user','UNRELATED earlier instruction'),answer('answer','UNRELATED earlier answer')]},
 {id:'target',status:'failed',error:{message:'native task failed exactly'},items:[user('instruction-1','ACTUAL target instruction 🌱'),...fillers,user('instruction-2','ACTUAL supplied correction'),{id:'command',type:'commandExecution',aggregatedOutput:'second Unicode quote'},answer('answer','EXACT target final'),answer('last-comment','Later commentary','commentary')]},
 {id:'empty',status:'interrupted',error:{message:'empty task interrupted'},items:[]},
 {id:'no-user',status:'inProgress',items:[answer('answer','OWN response without user input','partial_answer')]},
 {id:'later',status:'completed',items:[user('later-user','UNRELATED later instruction'),answer('answer','UNRELATED later answer')]}
]};
let rows=source.turns.flatMap(turn=>turn.items.length?turn.items.map(item=>({turn,item})):[{turn,item:null}]);
const PAGE_ENTRIES=40;let page=1,targetIndex=rows.findIndex(row=>row.item?.id==='command');
let requested={thread_id:'A',turn_id:'target',item_id:'command',match_text:'second Unicode quote',match_start:50000};
let options=null,taskReview=null,loading=false,live=true,version=7,refreshVersion=2,findVersion=1,finding=false,findSubmitted=true,findQuery='quote';
const originalSpans=root.DeskHistoryFind.spans('second Unicode quote','quote');
let findGroups=[{index:targetIndex,first:0,spans:originalSpans}],findTotal=1,findCursor=0;
let view={items:new Map(),anchor:{key:JSON.stringify(['target','command']),offset:19,screenTop:240},selection:{key:JSON.stringify(['target','command']),start:50000,end:50020,text:'second Unicode quote',backward:true},scroll:72,outer:44,page:1,first:JSON.stringify(['target','detail-36'])};
const capturedView=view;let rendered=[],restored=[],recomputations=[];
const current=ticket=>live && ticket===version,available=()=>current(version),captureView=()=>view;
const rowKey=row=>row?.item?JSON.stringify([row.turn.id,row.item.id]):null;
const findMatch=()=>findCursor<0?null:{index:findGroups[0].index,...findGroups[0].spans.at(findCursor)};
const textFor=item=>item.type==='userMessage'?'User\n'+item.content.filter(c=>c.type==='text').map(c=>c.text).join('\n'):'Codex\n'+(item.text||'');
const findControls=message=>{if(message!==undefined)el('find-status').textContent=message;};
const restoreView=(value,ticket)=>restored.push({view:value,ticket});
function render(scroll=true,value=null){taskControls();rendered.push({requested:{...requested},page,scroll,view:value});if(taskReview?.mode==='context')renderTaskContext(scroll,value);else if(value)restoreView(value,version);}
async function refreshFind(query,anchor,ticket){recomputations.push({query,anchor,ticket});}
const descendants=element=>element.children.flatMap(child=>[child,...descendants(child)]);
const controls=()=>descendants(el('body')).filter(element=>element.tag==='button');
const action=name=>controls().find(element=>element.dataset.taskAction===name);
const contextText=()=>descendants(el('body')).map(element=>element.textContent).join('\n');
el('find-query').value='quote';el('find-status').textContent='Match 1 of 1';el('status').textContent='Original successful read';el('match').textContent='Showing the matching original native turn and item.';el('error').hidden=true;el('retry').hidden=true;
'''.replace('TASK_HELPER', json.dumps(str(ROOT / 'codex_desk/static/history_tasks.js'))).replace('FIND_HELPER', json.dumps(str(ROOT / 'codex_desk/static/history_find.js')))


@unittest.skipUnless(shutil.which('node'), 'Node is required for source controller checks')
class HistoryTaskControllerTests(unittest.TestCase):
    def js(self, body):
        result = subprocess.run(['node', '-e', SETUP + TASKS + '\n(async()=>{' + body + '})().catch(error=>{console.error(error);process.exitCode=1;});'], text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_item_own_instruction_response_then_exact_passage_snapshot(self):
        self.js(r'''
const originalRequested={...requested},originalGroups=findGroups;
assert(openTaskContext(requested));assert.equal(taskReview.capture.turn_id,'target');
assert(contextText().includes('ACTUAL target instruction'));assert(contextText().includes('ACTUAL supplied correction'));
assert(!contextText().includes('UNRELATED earlier instruction'));assert(contextText().includes('native task failed exactly'));
assert(!el('task-passage').hidden);assert(el('task-return').hidden);
assert(readTaskItem('instruction','instruction-1'));assert.equal(requested.item_id,'instruction-1');assert.equal(page,0);
assert(returnTaskContext());assert(readTaskItem('response'));assert.equal(requested.turn_id,'target');assert.equal(requested.item_id,'answer');
assert(taskReview.itemLabel.includes('Final answer'));assert(taskReview.itemLabel.includes('failed'));assert(!el('task-return').hidden);
assert(returnTaskContext());assert(await returnTaskPassage());assert.equal(taskReview,null);assert.deepEqual(requested,originalRequested);
assert.strictEqual(findGroups,originalGroups);assert(findSubmitted);assert.equal(findCursor,0);assert.equal(el('find-query').value,'quote');
assert.strictEqual(restored.at(-1).view,capturedView);assert.equal(restored.at(-1).view.selection.backward,true);assert.equal(restored.at(-1).view.outer,44);
''')

    def test_missing_instruction_retains_same_turn_partial_response(self):
        self.js(r'''
assert(openTaskContext({thread_id:'A',turn_id:'no-user',item_id:'answer'}));
assert(contextText().includes('No user instruction was supplied'));assert(!contextText().includes('UNRELATED earlier instruction'));
assert.equal(controls().filter(button=>button.dataset.taskAction.startsWith('instruction:')).length,0);
assert(readTaskItem('response'));assert.equal(requested.turn_id,'no-user');assert.equal(requested.item_id,'answer');
assert(taskReview.itemLabel.includes('Partial answer'));assert(taskReview.itemLabel.includes('inProgress'));
''')

    def test_adjacent_tasks_keep_empty_outcome_and_supplied_boundaries(self):
        self.js(r'''
openTaskContext({thread_id:'A',turn_id:'target'});action('next').onclick();assert.equal(taskReview.capture.turn_id,'empty');
assert(contextText().includes('empty task interrupted'));assert(contextText().includes('No user instruction was supplied'));
assert.equal(readTaskItem('response'),false);assert(contextText().includes('No readable assistant response'));
action('next').onclick();assert.equal(taskReview.capture.turn_id,'no-user');action('next').onclick();assert.equal(taskReview.capture.turn_id,'later');
assert(action('next').disabled);assert(contextText().includes('End of supplied tasks'));
action('previous').onclick();assert.equal(taskReview.capture.turn_id,'no-user');
''')

    def test_ambiguous_item_never_changes_current_context_or_borrows_response(self):
        self.js(r'''
openTaskContext({thread_id:'A',turn_id:'target'});const captured=taskReview.capture;
source.turns[1].items.push({...source.turns[1].items.find(item=>item.id==='command')});
assert.throws(()=>openTaskContext({thread_id:'A',turn_id:'target',item_id:'command'}),/ambiguous captured item/);assert.strictEqual(taskReview.capture,captured);
source.turns[1].items.push(answer('answer','ambiguous own final'));assert.equal(readTaskItem('response'),false);
assert(contextText().includes('ambiguous response item'));assert.equal(taskReview.capture.turn_id,'target');
''')

    def test_return_after_refreshed_source_keeps_exact_lost_item_and_query_anchor(self):
        self.js(r'''
const originalRequested={...requested};openTaskContext(requested);source={...source,turns:source.turns.map(turn=>({...turn,items:turn.items.filter(item=>item.id!=='command')}))};
rows=source.turns.flatMap(turn=>turn.items.length?turn.items.map(item=>({turn,item})):[{turn,item:null}]);++refreshVersion;
assert(await returnTaskPassage());assert.deepEqual(requested,originalRequested);assert.equal(targetIndex,-1);
assert(el('match').textContent.includes('not present'));assert.equal(recomputations.length,1);assert.equal(recomputations[0].query,'quote');
assert.deepEqual(recomputations[0].anchor.key,JSON.stringify(['target','command']));
''')

    def test_failed_refresh_message_survives_return_to_unchanged_original(self):
        self.js(r'''
openTaskContext(requested);++refreshVersion;el('status').textContent='Refresh failed. The last successfully read original stays available.';
el('error').textContent='original read unavailable';el('error').hidden=false;el('retry').hidden=false;
assert(await returnTaskPassage());assert(el('status').textContent.includes('Refresh failed'));assert(!el('error').hidden);assert(!el('retry').hidden);
''')

    def test_canceled_inflight_find_and_lost_owner_keep_original_source(self):
        self.js(r'''
finding=true;openTaskContext(requested);assert(!finding);assert(!taskReview.passage.find.submitted);assert(taskReview.passage.find.message.includes('Find canceled'));
assert(await returnTaskPassage());assert(!findSubmitted);assert(el('find-status').textContent.includes('Find canceled'));
const count=rendered.length;live=false;assert.equal(openTaskContext(requested),false);assert.equal(rendered.length,count);assert.equal(taskReview,null);
''')

if __name__ == '__main__':
    unittest.main()
