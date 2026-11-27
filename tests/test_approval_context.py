"""Exact supplied native request context and original-read ownership."""
import subprocess,unittest
from test_pending_interactions import HARNESS,ROOT,NODE
APP=(ROOT/'codex_desk/static/app.js').read_text();SOURCE=APP[APP.index("let approvalsSignature='';"):APP.index('function consume(m)')]
EXTRA=r'''
let readerView=null,closeCalls=0;
Object.defineProperty(E.prototype,'isConnected',{get(){return !!this.parentNode;}});
const DeskHistoryReader={show:async(result,callbacks)=>{readerView={result,callbacks};$('history-reader').open=true;return true;},close:callbacks=>{if(readerView?.callbacks===callbacks){closeCalls++;$('history-reader').open=false;readerView.callbacks.onReturn();return true;}return false;}};
const command=(id=3)=>({id,method:'item/commandExecution/requestApproval',params:{threadId:'native-child',turnId:'child-turn',itemId:'child-item',command:'pytest parser --label résumé',cwd:'/work/child/验证',reason:'Recheck the child parser before proposing the patch.'}});
const readButton=id=>all(card(id).box).find(n=>n.className==='approval-context-read');
'''
class ApprovalContextTests(unittest.TestCase):
 def check(self,body):
  run=subprocess.run([NODE,'-e',HARNESS+EXTRA+SOURCE+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1});'],capture_output=True,text=True,timeout=20)
  self.assertEqual(run.returncode,0,run.stdout+run.stderr)
 def test_exact_reported_fields_and_child_request_identity(self):
  self.check(r'''requests.set('3',command());approvals();const text=all(card('3').box).map(n=>n.textContent).join('\n');for(const value of Object.values(command().params))assert(text.includes(value));assert(text.includes('Selected parent thread native-A'));assert(text.includes('Native request 3'));assert(text.includes('related thread'));assert.strictEqual(calls.length,0);''')
 def test_related_read_uses_child_turn_and_item_without_response(self):
  self.check(r'''requests.set('3',command());approvals();await readButton('3').onclick();assert.deepStrictEqual(readerView.result,{thread_id:'native-child',turn_id:'child-turn',item_id:'child-item'});assert(readerView.callbacks.valid());assert.strictEqual(readerView.callbacks.backLabel,'Return to native request');assert.strictEqual(calls.length,0);assert.strictEqual(reads,0);''')
 def test_sibling_question_and_read_button_survive_arrivals(self):
  self.check(r'''requests.set('1',question(1,true));requests.set('3',command());approvals();const answer=input('1');answer.value='Transient answer';answer.selectionStart=2;answer.selectionEnd=8;const read=readButton('3');await read.onclick();requests.set('4',command(4));approvals();assert.strictEqual(readButton('3'),read);assert.strictEqual(input('1'),answer);assert.strictEqual(answer.value,'Transient answer');assert.strictEqual(answer.selectionStart,2);assert.strictEqual(answer.selectionEnd,8);readerView.callbacks.onReturn();assert.strictEqual(document.activeElement,read);assert.strictEqual(calls.length,0);''')
 def test_native_resolution_closes_only_owned_reader(self):
  self.check(r'''requests.set('3',command());approvals();await readButton('3').onclick();const callbacks=readerView.callbacks;requests.delete('3');approvals();assert.strictEqual(closeCalls,1);assert(!callbacks.valid());assert.strictEqual(calls.length,0);''')
 def test_changed_generation_cannot_read_old_request(self):
  self.check(r'''requests.set('3',command());approvals();const read=readButton('3');generation++;await read.onclick();assert.strictEqual(readerView,null);assert.strictEqual(calls.length,0);''')
 def test_missing_thread_does_not_substitute_parent(self):
  self.check(r'''const m=command();delete m.params.threadId;requests.set('3',m);approvals();assert.strictEqual(readButton('3'),undefined);assert(all(card('3').box).some(n=>n.textContent.includes('Request thread unreported')));assert.strictEqual(calls.length,0);''')
 def test_read_not_added_to_one_time_decision_controls(self):
  self.check(r'''requests.set('3',command());approvals();assert.strictEqual(card('3').controls.length,2);const held=deferred();transport=()=>held.promise;const send=card('3').controls[0].onclick();await card('3').controls[1].onclick();assert.strictEqual(calls.length,1);assert.strictEqual(calls[0].body.request,'3');held.resolve({});await send;''')
 def test_parent_context_uses_store_binding_with_null_or_child_stream(self):
  self.check(r'''requests.set('3',command());nativeThreadId=null;approvals();assert(card('3').box.children.some(n=>all(n).some(e=>e.textContent.includes('Selected parent thread native-A'))));nativeThreadId='native-child';approvals();assert(card('3').contextIdentity.textContent.includes('Selected parent thread native-A'));assert(card('3').contextSummary.textContent.includes('related thread'));assert.strictEqual(calls.length,0);''')
 def test_parent_binding_reprojects_without_replacing_card_or_sibling_editor(self):
  self.check(r'''requests.set('1',question(1,true));requests.set('3',command());approvals();const owned=card('3'),read=readButton('3'),answer=input('1');answer.value='Kept transient';state.sessions[0].thread_id='native-rebound-parent';approvals();assert.strictEqual(card('3'),owned);assert.strictEqual(readButton('3'),read);assert.strictEqual(input('1'),answer);assert.strictEqual(answer.value,'Kept transient');assert(owned.contextIdentity.textContent.includes('Selected parent thread native-rebound-parent'));assert.strictEqual(calls.length,0);''')
if __name__=='__main__':unittest.main()
