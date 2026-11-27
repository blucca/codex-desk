"""Explicit successful-reader refresh preserves the latest same-source intent."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/history_reader.js').read_text()
HELPERS=SOURCE[SOURCE.index('  function refreshControls()'):SOURCE.index('  async function read()')]
ROW=SOURCE[SOURCE.index('  function rowKey('):SOURCE.index('  function itemNode(')]

@unittest.skipUnless(shutil.which('node'),'Node is required for controller checks')
class ReaderRefreshTests(unittest.TestCase):
    def run_js(self,body):
        setup=r'''
const assert=require('assert/strict'),root={DeskHistoryFind:require(FIND),DeskHistoryTasks:require(TASKS)};let taskReview=null;
const elements=new Map();function el(id){if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,value:'',textContent:''});return elements.get(id);}
const PAGE_ENTRIES=40;const str=x=>typeof x==='string'?x:'';let version=1,refreshVersion=0,refreshing=false,loading=false,findVersion=0,finding=false,findGroups=[],findTotal=0,findCursor=-1,findSubmitted=false,findQuery='';
let options=null;let source={id:'original',name:'First original'},requested={thread_id:'original'},rows=[{turn:{id:'turn'},item:{id:'old',type:'agentMessage',text:'exact old evidence'}}],page=0,targetIndex=-1;
let live=true,view={items:new Map(),anchor:null,first:JSON.stringify(['turn','old']),page:0,scroll:17},renders=[],findMessages=[],apiCalls=[];
function current(ticket){return live && ticket===version;}function available(){return current(version);}
function restoreView(){}function captureView(){return view;}function render(scroll,v){renders.push({scroll,view:v,source:source.id,rows:rows.map(x=>x.item.id)});}
function flatten(thread){return thread.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));}
function textFor(item){return item.text;}const visibleTypes=new Set(['agentMessage']);
function findControls(message){findMessages.push(message);}function findMatch(){if(findCursor<0)return null;const group=findGroups.findLast(g=>g.first<=findCursor);return {index:group.index,...group.spans.at(findCursor-group.first)};}
let response,release;async function api(path){apiCalls.push(path);return await new Promise((resolve,reject)=>{release=()=>response instanceof Error?reject(response):resolve(response);});}
const thread=(items)=>({id:'original',name:'Updated original',cwd:'/retained',turns:[{id:'turn',items:items.map(([id,text])=>({id,type:'agentMessage',text}))}]});
'''.replace('FIND',json.dumps(str(ROOT/'codex_desk/static/history_find.js'))).replace('TASKS',json.dumps(str(ROOT/'codex_desk/static/history_tasks.js')))
        script=setup+ROW+HELPERS+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'
        result=subprocess.run(['node','-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_referenced_refresh_preserves_home_and_exact_quote_resolver(self):
        self.run_js("""options={savedReference:{native_home:'a'.repeat(64),thread_id:'original',turn_id:'turn',item_id:'old',quote:'exact old evidence'}};
let resolved=0;root.DeskEvidencePreparation={resolve(reference,home,original,project){++resolved;assert.equal(home,reference.native_home);assert.equal(original.id,'original');return {available:true};}};
response={home_namespace:options.savedReference.native_home,thread:thread([['old','exact old evidence']])};let pending=refresh();release();assert(await pending);
assert.equal(apiCalls[0],'/api/native/evidence-source?home='+options.savedReference.native_home+'&thread=original');assert.equal(resolved,1);
const retained=source;response={home_namespace:'b'.repeat(64),thread:thread([['old','foreign home']])};pending=refresh();release();assert.equal(await pending,false);assert.strictEqual(source,retained);assert.equal(resolved,1);""")

    def test_pending_duplicate_keeps_snapshot_and_latest_unsent_query(self):
        self.run_js("""response=thread([['old','exact old evidence'],['new','fresh result']]);const old=source,oldRows=rows;
view.outer=31;const pending=refresh();assert.strictEqual(source,old);assert.strictEqual(rows,oldRows);assert(refreshing);await refresh();assert.equal(apiCalls.length,1);
view={...view,scroll:88,outer:244,page:0};el('find-query').value='new unsent phrase';release();assert(await pending);
assert.equal(source.name,'Updated original');assert.equal(rows.length,2);assert.equal(el('find-query').value,'new unsent phrase');assert.equal(renders.at(-1).view.scroll,88);assert.equal(renders.at(-1).view.outer,244,'Refresh commits the outer scroll at reply time, not click time');assert.equal(findTotal,0);assert(!refreshing);""")

    def test_failed_refresh_keeps_last_original_and_query_then_explicit_retry(self):
        self.run_js("""response=Error('Native original unavailable');const old=source,oldRows=rows;el('find-query').value='keep query';
let errorText='';Object.defineProperty(el('error'),'textContent',{get:()=>errorText,set:value=>{errorText=value;el('').scrollTop=0;}});
el('').scrollTop=31;let pending=refresh();el('').scrollTop=244;release();assert.equal(await pending,false);assert.strictEqual(source,old);assert.strictEqual(rows,oldRows);assert.equal(el('find-query').value,'keep query');assert(!el('error').hidden);assert(!el('retry').hidden);assert(!el('retry').disabled);assert.equal(el('').scrollTop,244,'Error layout restores the latest outer reading position');
response=thread([['old','exact old evidence']]);pending=refresh();release();assert(await pending);assert(el('error').hidden);assert.equal(apiCalls.length,2);""")

    def test_recomputes_submitted_query_with_compressed_spans_exact_anchor(self):
        self.run_js("""findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';
const spans=root.DeskHistoryFind.spans(rows[0].item.text,'evidence');findGroups=[{index:0,spans,first:0}];findTotal=1;findCursor=0;
response=thread([['old','exact old evidence'],['new','new evidence']]);const pending=refresh();release();assert(await pending);
assert.equal(findTotal,2);assert.equal(findCursor,0);assert.equal(findMatch().start,10);assert(!finding);assert.equal(renders.at(-1).view.scroll,17);""")

    def test_changed_query_during_pending_is_not_searched_or_overwritten(self):
        self.run_js("""findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';response=thread([['old','exact old evidence']]);
const pending=refresh();el('find-query').value='later typing';findSubmitted=false;++findVersion;release();assert(await pending);assert.equal(findTotal,0);assert.equal(el('find-query').value,'later typing');assert(!finding);""")

    def test_closed_or_newer_source_ignores_held_refresh(self):
        self.run_js("""response=thread([['old','updated']]);const old=source,oldRows=rows,pending=refresh();live=false;++version;++refreshVersion;refreshing=false;release();assert.equal(await pending,false);assert.strictEqual(source,old);assert.strictEqual(rows,oldRows);assert.equal(renders.length,0);""")

    def test_vanished_item_and_occurrence_are_not_silently_substituted(self):
        self.run_js("""findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';findGroups=[{index:0,spans:root.DeskHistoryFind.spans(rows[0].item.text,'evidence'),first:0}];findTotal=1;findCursor=0;
response=thread([['different','other evidence']]);const pending=refresh();release();assert(await pending);assert.equal(findTotal,1);assert.equal(findCursor,-1);assert(el('status').textContent.includes('no longer present'));assert(findMessages.some(x=>x?.includes('previous occurrence')));""")

if __name__=='__main__':unittest.main()
