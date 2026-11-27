"""Shipped activity/app open bindings for exact same-page reading returns."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from test_navigation_controllers import DOM

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
SETUP = DOM[:DOM.index('let state=')] + r"""
Object.defineProperty(Element.prototype,'classList',{get(){const node=this;return {
 contains:name=>node.className.split(/\s+/).includes(name),add:name=>{if(!node.className.split(/\s+/).includes(name))node.className+=' '+name;}};}});
Object.defineProperty(Element.prototype,'parentNode',{get(){return this.parentElement;}});
Element.prototype.addEventListener=function(name,callback){(this.listeners ||= {})[name]=callback;};
const positions={toolA:400,childA:950,answerA:1400,promptB:100,answerB:500,answerC:600};
Element.prototype.getBoundingClientRect=function(){const top=(positions[this.dataset.itemId] ?? 0)-window.scrollY;
 let visible=!this.hidden;for(let parent=this.parentElement;parent;parent=parent.parentElement)if(parent.tagName==='DETAILS'&&!parent.open)visible=false;
 const height=visible?300:0;return {top,bottom:top+height,height,left:0,right:700,width:700};};
document.createElement=tag=>new Element(tag);document.createTextNode=text=>new Element('text',text);
document.documentElement={scrollHeight:10000};
document.querySelector=selector=>selector==='dialog[open]'?['history-reader','preparation','preparation-request'].map($).find(n=>n.open)||null:null;
const scrollListeners=[],inputListeners={},frames=[];
const window={scrollY:0,scrollX:0,innerHeight:900,addEventListener:(name,fn)=>{if(name==='scroll')scrollListeners.push(fn);else (inputListeners[name] ||= []).push(fn);},
 scrollTo(value){this.scrollY=Math.max(0,Math.min(value.top,document.documentElement.scrollHeight-this.innerHeight));this.scrollX=value.left || 0;scrollListeners.forEach(fn=>fn());}};
const requestAnimationFrame=fn=>frames.push(fn),flush=()=>{while(frames.length)frames.shift()();};
const fs=require('fs');require(HELPER);
let state={sessions:['A','B','C'].map(id=>({id,thread_id:'native-'+id,status:'completed'})),pending:{}},selected=null,nativeThreadId=null,
 generation=0,opening=false,modeSelected=null,after=0,currentTurn=null,latestUpdates=0;
const items=new Map(),nodes=new Map(),itemTurns=new Map(),collaborationGroups=new Map(),requests=new Map();
const collaborationTypes=new Set(['collabAgentToolCall','subAgentActivity']);
const drafts=new Map([['A','Independent A unsent Plan'],['B','Independent B unsent Work'],['C','Independent C unsent Plan']]);
const modes=new Map([['A','plan'],['B','native'],['C','plan']]);
const preparation={drafts:[...drafts],queues:{A:['A Work','A Plan'],B:['B Work','B Plan']},answers:{B:{question:'B independently retained answer'}}};
const before=JSON.stringify(preparation),apiCalls=[];
const originals={A:{id:'native-A',turns:[{id:'turn-A',status:'completed',items:[
 {id:'toolA',type:'commandExecution',command:'inspect retained A',status:'completed',exitCode:0,aggregatedOutput:'Exact retained evidence A\n'+'line\n'.repeat(300)},
 {id:'childA',type:'subAgentActivity',kind:'started',agentPath:'A/helper',agentThreadId:'child-A'},
 {id:'answerA',type:'agentMessage',text:'A response stays exact.'}]}]},
 B:{id:'native-B',turns:[{id:'turn-B',status:'completed',items:[{id:'promptB',type:'userMessage',content:[{type:'text',text:'B actual task'}]},{id:'answerB',type:'agentMessage',text:'B response stays exact.'}]}]},
 C:{id:'native-C',turns:[{id:'turn-C',status:'completed',items:[{id:'answerC',type:'agentMessage',text:'C response stays exact.'}]}]}};
let eventTurn='turn-A';
let homeNamespace='a'.repeat(64);
function eventRows(id){return id==='A'?[
 {seq:1,event:{method:'turn/started',params:{threadId:'native-A',turn:{id:eventTurn,status:'inProgress'}}}},
 {seq:2,event:{method:'turn/plan/updated',params:{threadId:'native-A',turnId:eventTurn,plan:[{step:'Exact A native step',status:'completed'}]}}},
 {seq:3,event:{method:'turn/diff/updated',params:{threadId:'native-A',turnId:eventTurn,diff:'Exact A native diff'}}},
 {seq:4,event:{method:'turn/completed',params:{threadId:'native-A',turn:{id:eventTurn,status:'completed',items:[]}}}}]:[];}
let transport=async(path,body)=>{
 if(path==='/api/native/home')return {home_namespace:homeNamespace};
 if(path==='/api/open')return {thread:JSON.parse(JSON.stringify(originals[body.session]))};
 if(path.startsWith('/api/events?'))return eventRows(new URL(path,'http://local').searchParams.get('session'));
 throw Error('Unexpected '+path);
};
async function api(path,body){apiCalls.push({path,body});return transport(path,body);}
const DeskHome={selectionChanged(){}},DeskRecall={selectionChanged(){}},DeskFollowups={select(){}};
const DeskSteering={select(){},restoreThread(){},consume(){},opened:async()=>false,reading:()=>false};
const DeskStopTask={select(){},restoreThread(){},consume(){},opened:async()=>false,reading:()=>false};
const DeskNativeState={card(){throw Error('Unexpected native error');}};
function rememberDraft(){}function persistDraft(){}function approvals(){}function draftStatus(){}function syncDraftEvidence(){}
function loadDraft(id){$('prompt').value=drafts.get(id);$('turn-mode').value=modes.get(id);return Promise.resolve();}
function turnRequest(){return null;}async function discoverTurnRequest(){return null;}
function draw(){if(selected){$('prompt').value=drafts.get(selected);$('turn-mode').value=modes.get(selected);}}
async function refresh(){draw();}
function error(error){throw error;}
const stored=new Map(),storageWrites=[];
const localStorage={getItem:key=>stored.get(key) ?? null,setItem(key,value){stored.set(key,value);storageWrites.push({key,value});}};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const cloned=value=>JSON.parse(JSON.stringify(value));
function readA(){
 const tool=nodes.get('toolA');tool.querySelector('.activity-tool').open=true;
 const evidence=tool.querySelector('.activity-evidence');evidence.scrollTop=83;evidence.scrollLeft=7;
 collaborationGroups.get('turn-A').node.open=true;collaborationGroups.get('turn-A').body.scrollTop=21;
 $('native-steps').open=true;$('native-steps-body').scrollTop=65;
 $('turn-changes').open=true;$('turn-changes-body').scrollTop=47;
 window.scrollTo({top:350,left:3});
}
function cold(){
 selected=null;nativeThreadId=null;opening=false;++generation;sessionReadingViews.clear();sessionReadingHomes.clear();
 sessionReadingHomeValue=null;sessionReadingHomeRequest=null;sessionReadingStorage=null;sessionReadingKey=null;
 ++sessionReadingEpoch;sessionReadingPending=false;sessionReadingRestoring=false;
}
"""


@unittest.skipUnless(NODE, 'Node is required for activity reading continuity')
class SessionReadingControllerTests(unittest.TestCase):
    def check(self, body):
        app = (ROOT/'codex_desk/static/app.js').read_text()
        fragments = [(ROOT/'codex_desk/static/evidence.js').read_text(),
                     (ROOT/'codex_desk/static/activity.js').read_text(),
                     (ROOT/'codex_desk/static/native-steps.js').read_text(),
                     (ROOT/'codex_desk/static/turn-changes.js').read_text(),
                     "DeskNativeSteps.configure({$,make});DeskTurnChanges.configure({$,writeText:()=>{throw Error('Copy is not part of a reading return');}});",
                     app[app.index('const sessionReadingViews='):app.index('async function api(')],
                     app[app.index('function itemText(i) {'):app.index('let approvalsSignature=')],
                     app[app.index('function consume(m) {'):app.index('async function refresh() {')],
                     app[app.index('let ordinaryTurnSource='):app.index('function drawOrdinaryRequestSources(')],
                     app[app.index('async function open('):app.index('function profileInfo()')]]
        script = SETUP.replace('HELPER', json.dumps(str(ROOT/'codex_desk/static/reading_checkpoint.js')))
        script += '\n'+'\n'.join(fragments)+'\n(async()=>{'+body+r"""
assert.equal(JSON.stringify(preparation),before);
assert.equal($('prompt').value,drafts.get(selected));assert.equal($('turn-mode').value,modes.get(selected));
assert(apiCalls.every(call=>call.path==='/api/open'||call.path.startsWith('/api/events?')||call.path==='/api/native/home'));
assert(apiCalls.filter(call=>call.path==='/api/native/home').every(call=>call.body===undefined));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
"""
        result = subprocess.run([NODE, '-e', script], text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_A_B_A_restores_exact_tool_collaboration_readouts_and_viewport(self):
        self.check(r"""
await open('A');flush();readA();const saved=DeskSessionReading.capture();assert(!saved.latest);
assert.equal(saved.anchor.item_id,'toolA');assert.equal(saved.anchor.turn_id,'turn-A');
assert(!JSON.stringify(saved).includes('Exact retained evidence'));assert(!JSON.stringify(saved).includes('Independent A'));
await open('B');flush();assert.equal(selected,'B');assert.equal($('prompt').value,'Independent B unsent Work');
await open('A');flush();assert.equal(window.scrollY,350);assert.equal(window.scrollX,3);
assert(nodes.get('toolA').querySelector('.activity-tool').open);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,83);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollLeft,7);
assert(collaborationGroups.get('turn-A').node.open);assert.equal(collaborationGroups.get('turn-A').body.scrollTop,21);
assert($('native-steps').open);assert.equal($('native-steps-body').scrollTop,65);
assert($('turn-changes').open);assert.equal($('turn-changes-body').scrollTop,47);
assert.deepEqual(DeskSessionReading.capture(),saved);assert(!DeskSessionReading.follow());
DeskActivity.render(nodes.get('toolA'),{...items.get('toolA'),aggregatedOutput:'Longer native stream'},'Longer native stream');
assert(nodes.get('toolA').querySelector('.activity-tool').open);assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,83);
""")

    def test_new_native_turn_does_not_inherit_old_steps_or_diff_disclosure(self):
        self.check(r"""
await open('A');flush();readA();await open('B');flush();
originals.A.turns.push({id:'new-turn-A',status:'completed',items:[]});eventTurn='new-turn-A';positions.toolA=760;
await open('A');flush();assert.equal(DeskNativeSteps.state().turn,'new-turn-A');assert.equal(DeskTurnChanges.state().turn,'new-turn-A');
assert(!$('native-steps').open);assert(!$('turn-changes').open);
assert.equal($('native-steps-body').scrollTop,0);assert.equal($('turn-changes-body').scrollTop,0);
assert.equal(nodes.get('toolA').getBoundingClientRect().top,50);assert.equal(window.scrollY,710);
assert(nodes.get('toolA').querySelector('.activity-tool').open);
""")

    def test_missing_anchor_and_ambiguous_native_identity_keep_latest_explicit(self):
        self.check(r"""
await open('A');flush();readA();await open('B');flush();
originals.A.turns[0].items=originals.A.turns[0].items.filter(item=>item.id!=='toolA');
const beforeScroll=window.scrollY;await open('A');flush();assert.equal(window.scrollY,beforeScroll);
assert(!nodes.has('toolA'));assert($('latest-output').textContent.includes('Previous reading place unavailable'));
assert(!DeskSessionReading.follow());goLatest();assert(DeskSessionReading.follow());
assert.equal(window.scrollY,9100);assert.equal($('latest-output').textContent,'Latest output ↓');
await open('B');flush();originals.A.turns[0].items.unshift({id:'toolA',type:'commandExecution',status:'completed',aggregatedOutput:'No borrowed text'});
await open('A');flush();readA();await open('B');flush();
originals.A.turns.push(cloned(originals.A.turns[0]));await open('A');flush();
assert($('latest-output').textContent.includes('Previous reading place unavailable'));assert(!nodes.get('toolA').querySelector('.activity-tool').open);
""")

    def test_explicit_source_target_and_pending_reader_target_win_over_checkpoint(self):
        self.check(r"""
await open('A');flush();readA();await open('B');flush();window.scrollTo({top:120});
await open('A',{revealLatest:false});flush();assert.equal(window.scrollY,120);
assert(!nodes.get('toolA').querySelector('.activity-tool').open);
await open('B');flush();window.scrollTo({top:90});
await open('A',{readingTarget:{turn_id:'turn-A',item_id:'answerA'}});flush();assert.equal(window.scrollY,90);
assert(!nodes.get('toolA').querySelector('.activity-tool').open);
await open('B');flush();await open('A');DeskSessionReading.target();window.scrollTo({top:77});flush();assert.equal(window.scrollY,77);
""")

    def test_losing_native_open_and_queued_restore_cannot_move_new_owner(self):
        self.check(r"""
await open('A');flush();readA();const original=DeskSessionReading.capture();await open('B');flush();
const normal=transport,held=deferred();transport=async(path,body)=>path==='/api/open'&&body.session==='A'?held.promise:normal(path,body);
const losing=open('A');await Promise.resolve();await Promise.resolve();await Promise.resolve();
await open('C');flush();held.resolve({thread:cloned(originals.A)});await losing;flush();assert.equal(selected,'C');assert.equal(nativeThreadId,'native-C');
transport=normal;await open('A');await open('C');flush();assert.equal(selected,'C');
await open('A');flush();assert.deepEqual(DeskSessionReading.capture(),original);
""")

    def test_latest_intent_follows_fresh_source_and_wrong_binding_does_not_borrow(self):
        self.check(r"""
await open('A');flush();readA();goLatest();const latest=DeskSessionReading.capture();assert(latest.latest);
await open('B');flush();document.documentElement.scrollHeight=12000;await open('A');flush();assert.equal(window.scrollY,11100);
assert(DeskSessionReading.follow());assert(nodes.get('toolA').querySelector('.activity-tool').open);
await open('B');flush();state.sessions.find(row=>row.id==='A').thread_id='changed-A';originals.A={id:'changed-A',turns:[{id:'new-binding-turn',items:[{id:'toolA',type:'commandExecution',status:'completed',aggregatedOutput:'Different actual source'}]}]};
await open('A');flush();assert.equal(nativeThreadId,'changed-A');assert(!nodes.get('toolA').querySelector('.activity-tool').open);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,0);
""")

    def test_display_fallback_turn_keys_are_never_native_reading_identities(self):
        self.check(r"""
delete originals.A.turns[0].id;await open('A');flush();window.scrollTo({top:350});
assert.equal(itemTurns.get('toolA'),'snapshot:0');
const view=DeskSessionReading.capture();assert.equal(view.anchor,null);assert.equal(view.item_views.length,0);
assert(!JSON.stringify(view).includes('snapshot:0'));await open('B');flush();await open('A');flush();
assert($('latest-output').textContent.includes('Previous reading place unavailable'));
assert(!nodes.get('toolA').querySelector('.activity-tool').open);
""")

    def test_new_manual_reading_intent_cancels_pending_same_owner_restore(self):
        self.check(r"""
await open('A');flush();readA();await open('B');flush();await open('A');
window.scrollTo({top:600,left:9});flush();assert.equal(selected,'A');assert.equal(window.scrollY,600);assert.equal(window.scrollX,9);
assert(!nodes.get('toolA').querySelector('.activity-tool').open);assert(!DeskSessionReading.follow());
await open('B');flush();await open('A');flush();assert.equal(window.scrollY,600);assert.equal(window.scrollX,9);
await open('B');flush();await open('A');frames.shift()();inputListeners.wheel.forEach(fn=>fn());
window.scrollTo({top:750,left:11});flush();assert.equal(window.scrollY,750);assert.equal(window.scrollX,11);
await open('C');window.scrollTo({top:250,left:5});flush();assert.equal(selected,'C');assert.equal(window.scrollY,250);assert.equal(window.scrollX,5);assert(!DeskSessionReading.follow());
await open('B');flush();window.scrollTo({top:170,left:8});state.sessions.find(row=>row.id==='A').thread_id='native-A-input';originals.A.id='native-A-input';
await open('A');inputListeners.wheel.forEach(fn=>fn());flush();assert.equal(window.scrollY,170);assert.equal(window.scrollX,8);
""")

    def test_pagehide_metadata_restores_from_fresh_native_source_after_cold_page(self):
        self.check(r"""
await open('A');flush();readA();const view=DeskSessionReading.capture();inputListeners.pagehide.forEach(fn=>fn());
const saved=JSON.parse(stored.get(DeskReadingCheckpoint.STORAGE_KEY));assert.equal(saved.checkpoints.length,1);
assert.deepEqual(saved.checkpoints[0].owner,{native_home:'a'.repeat(64),session:'A',thread_id:'native-A'});
assert.deepEqual(saved.checkpoints[0].view,view);assert(!JSON.stringify(saved).includes('Exact retained evidence A'));
assert(!JSON.stringify(saved).includes('Independent A'));assert(!JSON.stringify(saved).includes('B independently retained answer'));
cold();originals.A.turns[0].items[0].aggregatedOutput='Fresh native body\n'+'fresh\n'.repeat(400);
const beforeReads=apiCalls.filter(call=>call.path==='/api/open').length;await open('A');flush();
assert.equal(apiCalls.filter(call=>call.path==='/api/open').length,beforeReads+1);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').textContent,'$ inspect retained A\nFresh native body\n'+'fresh\n'.repeat(400)+'\nExit 0');
assert.equal(window.scrollY,350);assert.equal(window.scrollX,3);assert(nodes.get('toolA').querySelector('.activity-tool').open);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,83);
assert.equal(apiCalls.filter(call=>call.path==='/api/native/home').length,2);
""")

    def test_cold_home_and_explicit_target_precedence_never_borrow_checkpoint(self):
        self.check(r"""
await open('A');flush();readA();DeskSessionReading.save();const raw=stored.get(DeskReadingCheckpoint.STORAGE_KEY);
cold();homeNamespace='b'.repeat(64);await open('A');flush();assert(!nodes.get('toolA').querySelector('.activity-tool').open);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,0);assert.equal(window.scrollY,9100);
assert.equal(stored.get(DeskReadingCheckpoint.STORAGE_KEY),raw);
cold();homeNamespace='a'.repeat(64);window.scrollTo({top:120,left:4});const reads=apiCalls.length;
await open('A',{readingTarget:{turn_id:'turn-A',item_id:'answerA'}});flush();assert.equal(window.scrollY,120);assert.equal(window.scrollX,4);
assert(!nodes.get('toolA').querySelector('.activity-tool').open);assert(!apiCalls.slice(reads).some(call=>call.path==='/api/native/home'));
cold();originals.A.turns[0].items=originals.A.turns[0].items.filter(item=>item.id!=='toolA');
await open('A');flush();assert(!nodes.has('toolA'));assert($('latest-output').textContent.includes('Previous reading place unavailable'));
""")

    def test_storage_failure_keeps_same_page_memory_and_corrupt_cold_metadata_is_read_only(self):
        self.check(r"""
const read=localStorage.getItem,write=localStorage.setItem;
localStorage.getItem=()=>{throw Error('storage unavailable');};localStorage.setItem=()=>{throw Error('storage unavailable');};
await open('A');flush();readA();await open('B');flush();await open('A');flush();assert.equal(window.scrollY,350);
assert.equal(nodes.get('toolA').querySelector('.activity-evidence').scrollTop,83);assert(nodes.get('toolA').querySelector('.activity-tool').open);
localStorage.getItem=read;localStorage.setItem=write;cold();stored.set(DeskReadingCheckpoint.STORAGE_KEY,'{corrupt');stored.set('independent-other-key','unchanged');
await open('A');flush();assert(!nodes.get('toolA').querySelector('.activity-tool').open);
assert.equal(stored.get(DeskReadingCheckpoint.STORAGE_KEY),'{corrupt');assert.equal(stored.get('independent-other-key'),'unchanged');
""")

    def test_delayed_namespace_cannot_apply_old_owner_or_override_new_reading_intent(self):
        self.check(r"""
await open('A');flush();readA();DeskSessionReading.save();cold();
const normal=transport,held=deferred();transport=async(path,body)=>path==='/api/native/home'?held.promise:normal(path,body);
const priorHome=apiCalls.filter(call=>call.path==='/api/native/home').length;
const pending=open('A');for(let i=0;i<100&&apiCalls.filter(call=>call.path==='/api/native/home').length===priorHome;i++)await Promise.resolve();
assert(sessionReadingPending);const chosen=open('C');for(let i=0;i<100&&opening;i++)await Promise.resolve();assert.equal(selected,'C');assert(!opening);
held.resolve({home_namespace:'a'.repeat(64)});await pending;await chosen;flush();assert.equal(selected,'C');assert.equal(nativeThreadId,'native-C');
assert.equal($('prompt').value,'Independent C unsent Plan');
transport=normal;cold();const heldAgain=deferred();transport=async(path,body)=>path==='/api/native/home'?heldAgain.promise:normal(path,body);
const original=open('A');for(let i=0;i<100&&!sessionReadingPending;i++)await Promise.resolve();assert(sessionReadingPending);DeskSessionReading.target();window.scrollTo({top:630,left:13});
heldAgain.resolve({home_namespace:'a'.repeat(64)});await original;flush();assert.equal(window.scrollY,630);assert.equal(window.scrollX,13);
assert(!nodes.get('toolA').querySelector('.activity-tool').open);
""")


if __name__ == '__main__':
    unittest.main()
