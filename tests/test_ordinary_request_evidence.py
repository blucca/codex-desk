"""Actual ordinary retained request source host plus real evidence controller."""
import json,subprocess,unittest
from test_navigation_controllers import DOM,APP,NODE
S=APP.read_text();HOST=S[S.index('let ordinaryTurnSource='):S.index('function drawCapturedTurn(')]
READ=S[S.index('async function readTurnRequest('):S.index('async function discoverTurnRequest(')]
SETUP=DOM[:DOM.index('let state=')]+r'''
Element.prototype.setSelectionRange=function(a,b,d){this.selectionStart=a;this.selectionEnd=b;this.selectionDirection=d;};
const fs=require('fs'),vm=require('vm');vm.runInThisContext(fs.readFileSync(EVIDENCE,'utf8'));
const E=DeskEvidencePreparation,clone=x=>JSON.parse(JSON.stringify(x));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const settle=async()=>{for(let i=0;i<40;i++)await Promise.resolve();};
const original={id:'source-A',name:'Original A',turns:[{id:'source-turn',status:'completed',items:[{id:'source-item',type:'agentMessage',phase:'final_answer',text:'Exact café🙂 original.'}]}]};
const projection=E.textForItem(original.turns[0].items[0]),reference=E.capture(original,{native_home:'a'.repeat(64),thread_id:'source-A',turn_id:'source-turn',item_id:'source-item',start_utf16:6,end_utf16:projection.length});
const token='12345678-1234-4234-8234-123456789abc';let selected='b',generation=12,opening=false;
const request={session:'b',token,body:Object.freeze({session:'b',token,text:'Retained original instruction\n\n'+E.format(reference),mode:'plan',revision:3,writer:'fixture',sequence:4}),receiptVersion:0,reading:null,writing:null,status:'pending'};
let active=request;const turnRequest=()=>active;
const drafts=new Map([['b','Keep current unsent prompt']]),draftModes=new Map([['b','plan']]),draftRevisions=new Map(),draftSaved=new Map(),draftTimers=new Map(),draftSaves=new Map(),draftConflicts=new Map(),draftEdits=new Map();
const DeskTurnReview={captured:r=>r?.body || null};
const window={scrollY:237,scrollTo:value=>window.scrollY=value.top};$('history-reader').open=false;
$('prompt').value='Keep current unsent prompt';$('prompt').setSelectionRange(3,8,'backward');$('prompt').scrollTop=71;
$('turn-request-captured-text').textContent=request.body.text;$('turn-request-captured-text').scrollTop=88;$('turn-request-captured').open=true;
let receiptGate=null,sourceGate=null,changed=false;const calls=[],readers=[],closes=[];
async function api(path){calls.push(path);if(path.startsWith('/api/turn/request?')){if(receiptGate)await receiptGate;return {session:'b',token,request:{status:'needs_review',payload:{...request.body,...(changed?{text:'Different token body'}:{})}}};}
if(path.startsWith('/api/native/evidence-source?')){if(sourceGate)await sourceGate;return {home_namespace:reference.native_home,thread:clone(original)};}throw Error('Unexpected '+path);}
function applyTurnReceipt(r,result){if(result.token!==r.token || ['text','mode','revision','writer','sequence'].some(k=>result.request.payload[k]!==r.body[k]))r.conflict=true;r.status=result.request.status;++r.receiptVersion;}
const draw=()=>{},drawTurnRequest=()=>{},DeskHistoryReader={close:callback=>closes.push(callback)};
E.configure({render:false,api,destination:()=>null,save:()=>{throw Error('Source reads cannot write');},showOriginal:async(target,callbacks)=>{readers.push({target,callbacks});return true;}});
const sourceButton=()=> $('turn-request-captured').querySelectorAll('button').find(n=>n.textContent.startsWith('Read referenced original'));
'''
@unittest.skipUnless(NODE,'Node required')
class OrdinaryRequestEvidenceTests(unittest.TestCase):
 def check(self,body):
  script=SETUP.replace('EVIDENCE',json.dumps(str(APP.parent/'evidence-preparation.js')))+HOST+READ+'\n(async()=>{drawOrdinaryRequestSources(request);'+body+r'''
assert.equal($('prompt').value,'Keep current unsent prompt');console.log('PASS ordinary retained request host');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
  r=subprocess.run([NODE,'-e',script],text=True,capture_output=True,timeout=20);self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_exact_retained_UUID_original_and_return_current_prompt(self):
  self.check(r'''
await sourceButton().onclick();assert.equal(readers.length,1);const reader=readers[0];assert.equal(reader.target.thread_id,'source-A');assert.equal(reader.target.item_id,'source-item');assert.equal(reader.callbacks.savedReference.quote,reference.quote);assert.equal(reader.callbacks.backLabel,'Return to retained Run request');assert.equal(calls.length,2);assert(calls[0].includes(token));
$('turn-request-captured').open=false;$('turn-request-captured-text').scrollTop=0;$('prompt').scrollTop=0;window.scrollY=0;reader.callbacks.onReturn();
assert($('turn-request-captured').open);assert.equal($('turn-request-captured-text').scrollTop,88);assert.equal($('prompt').scrollTop,71);assert.equal(window.scrollY,237);assert.strictEqual(document.activeElement,sourceButton());assert.equal(request.status,'needs_review');
''')
 def test_changed_body_or_newer_owner_suppresses_original(self):
  self.check(r'''
changed=true;await sourceButton().onclick();assert(request.conflict);assert.equal(readers.length,0);assert.equal(calls.length,1);
''')
 def test_held_receipt_after_same_ID_new_generation_cannot_read_source(self):
  self.check(r'''
const gate=deferred();receiptGate=gate.promise;const pending=sourceButton().onclick();await settle();generation++;gate.resolve();await pending;assert.equal(readers.length,0);assert.equal(calls.length,1);
''')
 def test_held_source_after_current_request_retirement_cannot_open(self):
  self.check(r'''
const gate=deferred();sourceGate=gate.promise;const pending=sourceButton().onclick();await settle();active=null;gate.resolve();await pending;assert.equal(readers.length,0);
''')
 def test_routine_host_draw_keeps_source_control_and_owner_close_exact_callback(self):
  self.check(r'''
const read=sourceButton();drawOrdinaryRequestSources(request);assert.strictEqual(sourceButton(),read);await read.onclick();const reader=readers[0];active=null;drawOrdinaryRequestSources(null);assert.strictEqual(closes[0],reader.callbacks);assert(!reader.callbacks.valid());$('prompt').focus();reader.callbacks.onReturn();assert.strictEqual(document.activeElement,$('prompt'));
''')
