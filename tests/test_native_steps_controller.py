"""Native-reported task steps: selected-turn event projection without task writes."""
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
HARNESS=r"""
const assert=require('assert');
const document={activeElement:null};
class Element {
  constructor(tag='div',text='',cls='') {this.tagName=tag.toUpperCase();this._text=text;this.className=cls;this.children=[];this.parentNode=null;this.dataset={};this.hidden=false;this.open=false;this.scrollTop=0;this.scrollLeft=0;}
  get textContent(){return this._text+this.children.map(e=>e.textContent).join('');}
  set textContent(value){this._text=value;for(const e of this.children){e.parentNode=null;}this.children=[];}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
  remove(){if(this.parentNode){const parent=this.parentNode;parent.children.splice(parent.children.indexOf(this),1);this.parentNode=null;}if(document.activeElement===this)document.activeElement=document.body;}
  focus(){document.activeElement=this;}
}
document.body=new Element('body');document.activeElement=document.body;
const elements=new Map(),$=id=>{if(!elements.has(id)){const e=new Element();elements.set(id,e);document.body.append(e);}return elements.get(id);};
function make(tag,text='',cls=''){return new Element(tag,text,cls);}
$('native-steps').hidden=true;$('native-steps').append($('native-steps-current'),$('native-steps-body'));
$('native-steps-body').append($('native-steps-status'),$('native-steps-explanation'),$('native-steps-list'));
const ctx={session:'desk-a',thread:'native-parent',generation:7};
const started=id=>({method:'turn/started',params:{threadId:ctx.thread,turn:{id,rootTurnId:id,items:[],status:'inProgress',error:null}}});
const plan=(id,entries,extra={})=>({method:'turn/plan/updated',params:{threadId:ctx.thread,turnId:id,explanation:'Inspect → fix → tests',plan:entries,...extra}});
const terminal=(id,status)=>({method:'turn/completed',params:{threadId:ctx.thread,turn:{id,status,items:[],error:status==='failed'?{message:'focused test failed'}:null}}});
const steps=index=>['Inspect — 保留','Apply <fix>','Test'].map((step,i)=>({step,status:i<index?'completed':i===index?'inProgress':'pending'}));
const report=()=>DeskNativeSteps.state().reported;
const accept=m=>DeskNativeSteps.consume(m,ctx);
"""

@unittest.skipUnless(NODE,'Node required')
class NativeStepsControllerTests(unittest.TestCase):
    def check(self,body):
        script=HARNESS+'\n'+(ROOT/'codex_desk/static/native-steps.js').read_text()+"\nDeskNativeSteps.configure({$,make});DeskNativeSteps.select(ctx);\n"+body
        result=subprocess.run([NODE,'-e',script],capture_output=True,text=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_latest_native_progress_and_literal_text(self):
        self.check(r"""
assert($('native-steps').hidden);assert.strictEqual(accept(started('turn-a')),false);
for(let index=0;index<3;index++){
  const event=plan('turn-a',steps(index));assert(accept(event));
  assert.deepStrictEqual(report().plan,event.params.plan);assert.strictEqual(report().explanation,event.params.explanation);
  assert($('native-steps-current').textContent.includes(event.params.plan[index].step));
  assert.strictEqual($('native-steps-list').children.length,3);
  assert.strictEqual($('native-steps-list').children[1].children[0].textContent,'Apply <fix>');
  assert.strictEqual(accept(event),false,'duplicate update must not count');
}
""")

    def test_native_terminal_retains_exact_unfinished_statuses(self):
        self.check(r"""
for(const status of ['completed','interrupted','failed']){
  DeskNativeSteps.select({...ctx,generation:100+['completed','interrupted','failed'].indexOf(status)});
  const value=DeskNativeSteps.state().context;
  DeskNativeSteps.consume(started('turn-a'),value);DeskNativeSteps.consume(plan('turn-a',steps(1)),value);
  const before=JSON.stringify(report());
  assert(DeskNativeSteps.consume(terminal('turn-a',status),value));
  assert.strictEqual(DeskNativeSteps.state().terminal,status);assert.strictEqual(JSON.stringify(report()),before);
  assert.strictEqual($('native-steps-status').textContent,'Task '+status);
  assert.strictEqual(DeskNativeSteps.consume(plan('turn-a',[{step:'late overwrite',status:'completed'}]),value),false);
  assert.strictEqual(JSON.stringify(report()),before);
  assert.strictEqual(DeskNativeSteps.consume(started('turn-a'),value),false);
}
""")

    def test_new_turn_and_session_thread_generation_isolation(self):
        self.check(r"""
accept(started('turn-a'));accept(plan('turn-a',steps(0)));
assert(accept(started('turn-b')));assert($('native-steps').hidden);assert.strictEqual(report(),null);
assert.strictEqual(accept(plan('turn-a',steps(2))),false);assert.strictEqual(report(),null);
assert.strictEqual(accept({...started('child-turn'),params:{...started('child-turn').params,threadId:'child'}}),false);
assert.strictEqual(accept(plan('turn-b',steps(0),{threadId:'child'})),false);
assert.strictEqual(accept(plan('turn-b',steps(0),{threadId:undefined,thread:{id:'child'}})),false);
assert.strictEqual(DeskNativeSteps.consume(plan('turn-b',steps(0)),{...ctx,generation:6}),false);
assert.strictEqual(DeskNativeSteps.consume(plan('turn-b',steps(0)),{...ctx,session:'desk-b'}),false);
assert.strictEqual(DeskNativeSteps.consume(plan('turn-b',steps(0)),{...ctx,thread:'other'}),false);
const noThread=plan('turn-b',steps(1));delete noThread.params.threadId;assert(accept(noThread));assert.deepStrictEqual(report().plan,steps(1));
DeskNativeSteps.select({...ctx,session:'desk-b',generation:8});assert($('native-steps').hidden);assert.strictEqual(report(),null);
assert.strictEqual(accept(plan('turn-b',steps(2))),false);
""")

    def test_disclosure_focus_scroll_and_replacement(self):
        self.check(r"""
accept(started('turn-a'));accept(plan('turn-a',steps(0)));
const disclosure=$('native-steps'),body=$('native-steps-body'),list=$('native-steps-list'),first=list.children[0];
disclosure.open=true;body.scrollTop=91;body.scrollLeft=3;body.focus();
accept(plan('turn-a',steps(1)));
assert.strictEqual($('native-steps'),disclosure);assert.strictEqual($('native-steps-body'),body);assert.strictEqual(list.children[0],first);
assert(disclosure.open);assert.strictEqual(document.activeElement,body);assert.strictEqual(body.scrollTop,91);assert.strictEqual(body.scrollLeft,3);
accept(plan('turn-a',[{step:'Replacement checklist',status:'pending'}],{explanation:''}));
assert.strictEqual(list.children.length,1);assert.strictEqual(first.children[0].textContent,'Replacement checklist');assert($('native-steps-explanation').hidden);
assert.strictEqual(document.activeElement,body);assert(disclosure.open);
accept(terminal('turn-a','failed'));assert.strictEqual(document.activeElement,body);assert(disclosure.open);
""")

    def test_ordered_replay_and_newer_snapshot_boundary(self):
        self.check(r"""
const events=[started('old'),plan('old',steps(0)),terminal('old','completed'),plan('old',steps(2)),started('new'),plan('new',steps(1)),terminal('new','interrupted'),plan('new',steps(2))];
for(const event of events)accept(event);const before=DeskNativeSteps.state();
DeskNativeSteps.select({...ctx,generation:8});for(const event of events)DeskNativeSteps.consume(event,{...ctx,generation:8});
const after=DeskNativeSteps.state();assert.strictEqual(after.turn,'new');assert.strictEqual(after.terminal,'interrupted');assert.deepStrictEqual(after.reported,before.reported);
DeskNativeSteps.select(ctx);accept(started('old'));accept(plan('old',steps(0)));
DeskNativeSteps.restoreThread({id:ctx.thread,turns:[{id:'old',status:'completed'},{id:'snapshot-new',status:'inProgress'}]},ctx);
assert.strictEqual(DeskNativeSteps.state().turn,'snapshot-new');assert.strictEqual(report(),null);assert($('native-steps').hidden);
accept(started('stream-new'));accept(plan('stream-new',steps(2)));
DeskNativeSteps.restoreThread({id:ctx.thread,turns:[{id:'old',status:'completed'},{id:'snapshot-new',status:'inProgress'}]},ctx);
assert.strictEqual(DeskNativeSteps.state().turn,'stream-new');assert.deepStrictEqual(report().plan,steps(2));
""")

    def test_session_process_exit_retains_checklist(self):
        self.check(r"""
accept(started('turn-a'));accept(plan('turn-a',steps(1)));const before=JSON.stringify(report());
assert.strictEqual(DeskNativeSteps.sync({id:'desk-b',thread_id:ctx.thread,status:'failed'},ctx),false);
assert.strictEqual(DeskNativeSteps.sync({id:ctx.session,thread_id:'child',status:'failed'},ctx),false);
assert.strictEqual(DeskNativeSteps.sync({id:ctx.session,thread_id:ctx.thread,status:'interrupted'},ctx),true);
assert.strictEqual(DeskNativeSteps.state().terminal,'interrupted');assert.strictEqual(JSON.stringify(report()),before);
assert.strictEqual(accept(plan('turn-a',steps(2))),false);
""")
