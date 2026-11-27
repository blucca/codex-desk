from pathlib import Path
import os, shutil, subprocess, unittest
ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
HARNESS=r'''
const assert=require('assert');
const document={activeElement:null};
class E{
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;this.value='';this.textContent='';this.disabled=false;this.selectionStart=0;this.selectionEnd=0;this.scrollTop=0;}
 get firstChild(){return this.children[0]||null;} get nextSibling(){if(!this.parentNode)return null;return this.parentNode.children[this.parentNode.children.indexOf(this)+1]||null;}
 append(...nodes){for(const node of nodes)this.insertBefore(node,null);}
 insertBefore(node,other){if(node===other)return;if(node.parentNode)node.remove();node.parentNode=this;const n=other?this.children.indexOf(other):this.children.length;this.children.splice(n,0,node);}
 remove(){if(this.parentNode){this.parentNode.children.splice(this.parentNode.children.indexOf(this),1);this.parentNode=null;}if(this.contains(document.activeElement))document.activeElement=null;}
 replaceChildren(...nodes){for(const n of [...this.children])n.remove();this.append(...nodes);}
 contains(node){return this===node||this.children.some(n=>n.contains(node));}
 setAttribute(k,v){this[k]=v;} focus(){document.activeElement=this;}
 querySelector(){const nodes=all(this);return nodes.find(n=>['BUTTON','INPUT','SELECT'].includes(n.tagName)&&!n.disabled)||null;}
}
const all=node=>node.children.flatMap(child=>[child,...all(child)]);
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new E());return elements.get(id);};
const make=(tag,text='',cls='')=>Object.assign(new E(tag),{textContent:text,className:cls});
let selected='A',generation=1,requests=new Map();let calls=[],reads=0,transport=async()=>{};
const api=async(path,body)=>{calls.push({path,body});return transport(path,body);}, refresh=async()=>{reads++;},error=()=>{};
const question=(id,secret=false)=>({id,method:'item/tool/requestUserInput',params:{threadId:'native-A',questions:[{id:'choice',header:'Mode',question:'Which?',options:[{label:'Safe',description:'Read'},{label:'Edit',description:'Write'}]},{id:'note',header:'Note',question:'Next check?',isSecret:secret}]}});
const approval=id=>({id,method:'item/commandExecution/requestApproval',params:{command:'pytest parser'}});
const deferred=()=>{let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b});return {promise,resolve,reject};};
const card=id=>interactionCards.get(selected).get(id),input=(id,field='note')=>card(id).fields.get(field);
'''

@unittest.skipUnless(NODE,'Node required')
class PendingInteractionsTests(unittest.TestCase):
 def check(self,body):
  path=os.environ.get('DESK_INTERACTIONS_SOURCE',str(ROOT/'codex_desk/static/app.js'))
  source=Path(path).read_text();source=source[source.index("let approvalsSignature='';"):source.index('function consume(m)')]
  run=subprocess.run([NODE,'-e',HARNESS+source+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1});'],capture_output=True,text=True,timeout=20)
  self.assertEqual(run.returncode,0,run.stdout+run.stderr)
 def test_sibling_arrival_resolution_and_snapshot_keep_editor(self):
  self.check(r'''
requests.set('1',question(1));approvals();const node=input('1');node.value='Only the parser check';node.selectionStart=3;node.selectionEnd=11;node.scrollTop=44;node.focus();const box=card('1').box;
requests.set('2',approval(2));approvals();assert.strictEqual(input('1'),node);assert.strictEqual(card('1').box,box);assert.strictEqual(node.value,'Only the parser check');assert.strictEqual(document.activeElement,node);assert.strictEqual(node.selectionStart,3);assert.strictEqual(node.selectionEnd,11);assert.strictEqual(node.scrollTop,44);
requests=new Map(JSON.parse(JSON.stringify([...requests])));approvals();assert.strictEqual(input('1'),node);requests.delete('2');approvals();assert.strictEqual(input('1'),node);assert.strictEqual(document.activeElement,node);assert.strictEqual(calls.length,0);
''')
 def test_one_exact_answer_while_held_and_sibling_updates(self):
  self.check(r'''
requests.set('1',question(1,true));approvals();input('1','choice').value='Edit';input('1').value='Private exact answer';const form=all(card('1').box).find(n=>n.tagName==='FORM'), held=deferred();transport=()=>held.promise;
const send=form.onsubmit({preventDefault(){}});await form.onsubmit({preventDefault(){}});assert.strictEqual(calls.length,1);assert.deepStrictEqual(calls[0],{path:'/api/answer',body:{session:'A',request:'1',answers:{choice:['Edit'],note:['Private exact answer']}}});assert(card('1').controls.every(n=>n.disabled));
requests.set('2',approval(2));approvals();assert(card('1').controls.every(n=>n.disabled));const secret=input('1');held.resolve({});await send;assert(!requests.has('1'));assert(requests.has('2'));assert.strictEqual(secret.value,'');assert.strictEqual(reads,1);
''')
 def test_allow_once_lock_and_rejected_response_keeps_pending(self):
  self.check(r'''
requests.set('1',approval(1));approvals();const buttons=card('1').controls,held=deferred();transport=()=>held.promise;const send=buttons[0].onclick();await buttons[1].onclick();assert.strictEqual(calls.length,1);assert(buttons.every(n=>n.disabled));held.reject(new Error('lost local reply'));await send;assert(requests.has('1'));assert(buttons.every(n=>!n.disabled));assert(card('1').status.textContent.includes('lost local reply'));
''')
 def test_session_switch_keeps_unsent_edit_and_old_ack_not_current(self):
  self.check(r'''
requests.set('1',question(1));approvals();const node=input('1');node.value='A unsent';const aRequests=requests;
selected='B';generation++;requests=new Map([['1',question(1)]]);approvals();input('1').value='B independent';const b=input('1');
selected='A';generation++;requests=aRequests;approvals();assert.strictEqual(input('1'),node);assert.strictEqual(node.value,'A unsent');
const held=deferred();transport=()=>held.promise;const form=all(card('1').box).find(n=>n.tagName==='FORM'), send=form.onsubmit({preventDefault(){}});
selected='B';generation++;requests=new Map([['1',question(1)]]);approvals();assert.strictEqual(input('1'),b);held.resolve({});await send;assert(requests.has('1'));assert.strictEqual(input('1'),b);assert.strictEqual(b.value,'B independent');assert.strictEqual(node.value,'');
''')
 def test_native_resolution_clears_secret_and_returns_focus(self):
  self.check(r'''
requests.set('1',question(1,true));requests.set('2',approval(2));approvals();const node=input('1');node.value='Secret transient';node.focus();requests.delete('1');approvals();assert.strictEqual(node.value,'');assert(!interactionCards.get('A').has('1'));assert.strictEqual(document.activeElement,card('2').controls[0]);
card('2').controls[0].focus();requests.delete('2');approvals();assert.strictEqual(document.activeElement,$('stop'));
''')
 def test_replaced_native_request_id_is_not_retired_by_old_ack(self):
  self.check(r'''
requests.set('1',question(1));approvals();input('1').value='old';const held=deferred();transport=()=>held.promise;const form=all(card('1').box).find(n=>n.tagName==='FORM'),send=form.onsubmit({preventDefault(){}});
const next=question(1);next.params.questions[1].question='A different native question';requests.set('1',next);approvals();const node=input('1');node.value='new unsent';held.resolve({});await send;assert(requests.has('1'));assert.strictEqual(input('1'),node);assert.strictEqual(node.value,'new unsent');
''')

 def test_background_native_resolution_clears_detached_secret(self):
  self.check(r'''
requests.set('1',question(1,true));approvals();const secret=input('1');secret.value='A background secret';
selected='B';requests=new Map([['2',approval(2)]]);approvals();syncInteractionCards({A:[question(1,true)],B:[approval(2)]});assert.strictEqual(secret.value,'A background secret');
syncInteractionCards({A:[],B:[approval(2)]});assert.strictEqual(secret.value,'');assert(!interactionCards.has('A'));assert(requests.has('2'));assert.strictEqual(calls.length,0);
''')
