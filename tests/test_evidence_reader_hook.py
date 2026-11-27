"""Loaded original evidence capture and duplicate-phrase exact-span reading."""
import json,pathlib,shutil,subprocess,unittest
P=pathlib.Path(__file__).resolve().parents[1]
S=(P/'codex_desk/static/history_reader.js').read_text()
COPY=S[S.index('  function copyControls('):S.index('  function scrollMatch(')]
AT=S[S.index('    const exactStart='):S.index('    const matchEnd=')]
SETUP=r'''
const assert=require('assert/strict');let live=true,records=[],returned=[];
const source={id:'native-A',cwd:'/removed/A',name:'Original A'},row={turn:{id:'turn-A'},item:{id:'item-A',type:'agentMessage'}};
const root={navigator:{clipboard:{writeText:async()=>{throw Error('Unexpected clipboard action');}}}};
const visibleTypes=new Set(['agentMessage']),str=v=>typeof v==='string'?v:'';
const current=()=>live,available=()=>live,rowKey=r=>JSON.stringify([r.turn.id,r.item.id]);
const captureView=()=>({selection:'exact original range',scroll:72}),restoreView=(v,t)=>returned.push({v,t});
const range={key:rowKey(row),start:23,end:31},selectedText=()=>range;
function node(tag,text,cls){return {tag,text,cls,children:[],isConnected:true,disabled:false,append(...n){this.children.push(...n);},setAttribute(){}};}
const detail=node('details'),status=()=>detail.children[0].children.find(n=>n.cls==='history-reader-copy-status');
const review=()=>detail.children[0].children.find(n=>n.cls==='history-reader-review-evidence');
const textFor=()=> 'Exact source 🌱 duplicate duplicate';
let evidenceReview=async payload=>{records.push(payload);payload.onReturn();};
'''
@unittest.skipUnless(shutil.which('node'),'Node required')
class EvidenceReaderHookTests(unittest.TestCase):
 def js(self,body,snippet=COPY):
  r=subprocess.run(['node','-e',SETUP+snippet+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'],capture_output=True,text=True,timeout=10)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_loaded_exact_source_range_and_owned_return(self):
  self.js("copyControls(detail,row,textFor(row.item),9);await review().onclick();assert.equal(records.length,1);assert.strictEqual(records[0].thread,source);assert.equal(records[0].turn_id,'turn-A');assert.equal(records[0].item_id,'item-A');assert.strictEqual(records[0].text_for_item,textFor);assert.deepEqual(records[0].selection_utf16,{start:23,end:31});assert(records[0].valid());assert.equal(returned.length,1);assert.equal(returned[0].t,9);assert(!review().disabled);")
 def test_other_item_selection_not_used_as_this_quote(self):
  self.js("range.key=JSON.stringify(['other','item']);copyControls(detail,row,textFor(row.item),9);await review().onclick();assert.equal(records[0].selection_utf16,null);")
 def test_unconfigured_reader_no_new_action(self):
  self.js("evidenceReview=null;copyControls(detail,row,textFor(row.item),9);assert.equal(review(),undefined);assert.equal(detail.children[0].children.length,3);")
 def test_stale_reader_does_not_capture_or_restore(self):
  self.js("copyControls(detail,row,textFor(row.item),9);live=false;await review().onclick();assert.equal(records.length,0);assert.equal(returned.length,0);")
 def test_review_failure_keeps_source_and_reenables(self):
  self.js("evidenceReview=async()=>{throw Error('Wait for draft saved');};copyControls(detail,row,textFor(row.item),9);await review().onclick();assert.equal(status().textContent,'Wait for draft saved');assert(!review().disabled);assert.equal(source.id,'native-A');")
 def test_exact_repeated_phrase_location_not_first_equal_phrase(self):
  self.js("const text='duplicate 🌱 duplicate',matched=true,occurrence=null,phrase='duplicate';let requested={match_start:text.lastIndexOf(phrase)};"+AT+"assert.equal(at,text.lastIndexOf(phrase));",snippet='')
 def test_changed_exact_quote_not_replaced_by_equal_phrase_elsewhere(self):
  self.js("const text='duplicate changed',matched=true,occurrence=null,phrase='duplicate';let requested={match_start:10};"+AT+"assert.equal(at,-1);",snippet='')
