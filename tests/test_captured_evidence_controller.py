"""References remain actionable in the exact independently captured Run request."""
import json,subprocess,unittest
from test_prepared_request_controller import SETUP,NODE,ROOT
EXTRA=r'''
vm.runInThisContext(fs.readFileSync(EVIDENCE,'utf8'));
const E=DeskEvidencePreparation;
const native={id:'source-A',name:'Decisive original A',cwd:'/removed/A',turns:[{id:'source-turn',status:'failed',items:[{id:'source-item',type:'agentMessage',phase:'commentary',text:'Exact native café🙂 evidence.'}]}]};
const projection=E.textForItem(native.turns[0].items[0]),reference=E.capture(native,{native_home:'a'.repeat(64),thread_id:'source-A',turn_id:'source-turn',item_id:'source-item',start_utf16:6,end_utf16:projection.length});
const block=E.format(reference),captured='Captured original unsent B\n\n'+block;
requests.r.request.payload.text=captured;
const readerCalls=[],closes=[];let readHold=null;
const nativeApi=api;
api=async(path,data)=>{
 if(path.startsWith('/api/native/evidence-source?')){calls.push({path,data:null});if(readHold)await readHold;return {home_namespace:reference.native_home,thread:clone(native)};}
 return nativeApi(path,data);
};
E.configure({render:false,api:(path,data)=>api(path,data),destination:()=>DeskPreparation.evidenceDestination(),save:()=>{throw Error('Captured reference cannot write drafts');},
 showOriginal:async(target,callbacks)=>{readerCalls.push({target,callbacks});return true;}});
global.DeskHistoryReader={close:expected=>closes.push(expected)};
const sourceButton=()=>all(req('captured')).find(e=>e.tagName==='BUTTON'&&e.textContent.startsWith('Read referenced original'));
'''
S=SETUP.replace('DeskPreparation.configure({api,',EXTRA+"\nDeskPreparation.configure({api,readEvidenceReference:(reference,callbacks)=>E.readReference(reference,callbacks),",1)
@unittest.skipUnless(NODE,'Node required')
class CapturedEvidenceControllerTests(unittest.TestCase):
 def js(self,body):
  script=S.replace('EVIDENCE',json.dumps(str(ROOT/'codex_desk/static/evidence-preparation.js'))) + '\n(async()=>{await DeskPreparation.show();await requestReview("r");'+body+'\nunchanged();})().catch(e=>{console.error(e);process.exitCode=1;});'
  r=subprocess.run([NODE,'-e',script,str(ROOT/'codex_desk/static/preparation.js')],capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_exact_request_reference_source_read_one_get_and_return_disclosure_scroll(self):
  self.js(r'''
assert(sourceButton());req('').scrollTop=49;req('captured-text').scrollTop=71;req('captured').open=true;
await sourceButton().click();assert.equal(readerCalls.length,1);
const read=readerCalls[0];assert.equal(read.target.thread_id,'source-A');assert.equal(read.target.turn_id,'source-turn');assert.equal(read.target.item_id,'source-item');assert.equal(read.callbacks.savedReference.quote,reference.quote);
assert.equal(calls.filter(c=>c.path.startsWith('/api/native/evidence-source?')).length,1);assert.equal(read.callbacks.backLabel,'Return to task request');
req('').scrollTop=0;req('captured-text').scrollTop=0;req('captured').open=false;read.callbacks.onReturn();
assert.equal(req('').scrollTop,49);assert.equal(req('captured-text').scrollTop,71);assert(req('captured').open);assert.strictEqual(document.activeElement,sourceButton());assert.equal(req('captured-text').textContent,captured);assert.equal(resolvePosts().length,0);
''')
 def test_owner_close_closes_actual_installed_reader_callback_identity(self):
  self.js(r'''
await sourceButton().click();assert.equal(readerCalls.length,1);const read=readerCalls[0];
await req('return').click();assert.equal(closes.length,1);assert.strictEqual(closes[0],read.callbacks);assert(!read.callbacks.valid());read.callbacks.onReturn();assert(!req('').open);
''')
 def test_held_reply_after_request_close_never_opens_source(self):
  self.js(r'''
const wait=deferred();readHold=wait.promise;const pending=sourceButton().click();await settle();await req('return').click();wait.resolve();await pending;
assert.equal(readerCalls.length,0);assert.equal(closes.length,0);assert(!req('').open);
''')
 def test_newer_request_reopen_cannot_use_previous_return(self):
  self.js(r'''
await sourceButton().click();const old=readerCalls[0];await req('return').click();await requestReview('r');req('captured-text').scrollTop=99;
assert(!old.callbacks.valid());old.callbacks.onReturn();assert.equal(req('captured-text').scrollTop,99);assert(req('').open);
''')
 def test_routine_request_refresh_preserves_existing_source_control_and_text(self):
  self.js(r'''
const button=sourceButton();req('captured-text').scrollTop=64;await req('refresh').click();assert.strictEqual(sourceButton(),button);assert.equal(req('captured-text').scrollTop,64);assert.equal(readerCalls.length,0);
''')
