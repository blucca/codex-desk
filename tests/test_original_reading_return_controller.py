"""Reader checkpoint bridge remains source/intent-owned across Close and fresh read."""
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/history_reader.js').read_text()
HELPERS=SOURCE[SOURCE.index('  function originalFrontierControls()'):SOURCE.index('  function originalReadingStore()')]+SOURCE[SOURCE.index('  function originalReadingStore()'):SOURCE.index('  function invalidate()')]
CLOSE=SOURCE[SOURCE.index('  function close('):SOURCE.index('  function available(')]
HOME=SOURCE[SOURCE.index('      if(!explicitReadingTarget() && root.DeskReadingCheckpoint)'):SOURCE.index('      let thread=preloaded;')]
HARNESS=r'''
const PAGE_ENTRIES=40;const assert=require('assert/strict'),h=require(process.argv[1]),values=new Map();
const root={DeskReadingCheckpoint:h,localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)}};
let readingRestoreEpoch=0,findVersion=0,live=true;const current=t=>live && t===7;
let readingUnavailable=false,readingStorage=null,readingHome='a'.repeat(64),requested={thread_id:'original-A'},options={valid:()=>true},loading=false,taskReview=null,page=0;
let source={id:'original-A',turns:[{id:'turn',items:[{id:'item'}]}]},rows=[{turn:source.turns[0],item:source.turns[0].items[0]}];
const key=JSON.stringify(['turn','item']),rowKey=row=>JSON.stringify([row.turn.id,row.item.id]);
let captured={items:new Map([[key,{start:26332,open:true,scroll:7774,left:4}]]),anchor:{key,offset:-123,screenTop:134},
 scroll:1781,scrollLeft:2,outer:526,outerLeft:3,page:1,selection:{text:'DO NOT SAVE POINTER QUOTE'}};
const restoreView=()=>{},captureView=()=>captured,status={textContent:'',open:true,close(){this.open=false;captured.anchor=null;}},el=()=>status;
function invalidate(){}
'''
@unittest.skipUnless(shutil.which('node'),'Node is required for reader ownership units')
class OriginalReadingReturnControllerTests(unittest.TestCase):
 def check(self,body):
  p=subprocess.run(['node','-e',HARNESS+SOURCE[SOURCE.index('  function preserveChrome('):SOURCE.index('  async function refreshFind(')]+HELPERS+CLOSE+'function startHome(ticket){'+HOME+'}'+body,str(ROOT/'codex_desk/static/reading_checkpoint.js')],capture_output=True,text=True,timeout=15)
  self.assertEqual(p.returncode,0,p.stdout+p.stderr)
 def test_pending_metadata_does_not_gate_read_or_move_newer_reader_intent(self):
  self.check(r'''
saveOriginalReading();readingHome=null;let release,renders=[];
const api=()=>new Promise(r=>release=r),render=(scroll,v)=>renders.push(v);
startHome(7);assert.equal(readingHome,null);assert.equal(renders.length,0);
++readingRestoreEpoch;
release({home_namespace:'a'.repeat(64)});
Promise.resolve().then(()=>{assert.equal(readingHome,'a'.repeat(64));assert.equal(renders.length,0);});
''')
 def test_late_metadata_after_close_cannot_rebind_or_restore(self):
  self.check(r'''
saveOriginalReading();readingHome=null;let release,renders=[];
const api=()=>new Promise(r=>release=r),render=(scroll,v)=>renders.push(v);
startHome(7);live=false;release({home_namespace:'a'.repeat(64)});
Promise.resolve().then(()=>{assert.equal(readingHome,null);assert.equal(renders.length,0);});
''')
 def test_same_owned_pending_metadata_resolves_from_fresh_ids(self):
  self.check(r'''
saveOriginalReading();readingHome=null;let release,renders=[],frames=[];
root.requestAnimationFrame=callback=>frames.push(callback);
const api=()=>new Promise(r=>release=r),render=(scroll,v)=>renders.push(v);
startHome(7);release({home_namespace:'a'.repeat(64)});
Promise.resolve().then(()=>{assert.equal(readingHome,'a'.repeat(64));assert.equal(renders.length,1);
assert.equal(renders[0].items.get(key).start,26332);assert.equal(frames.length,1);});
''')
 def test_real_close_captures_before_modal_geometry_disappears(self):
  self.check(r'''
assert.equal(close({}),false);assert.equal(values.size,0);assert(status.open);
assert.equal(close(),true);assert(!status.open);
const entry=JSON.parse(values.get(h.ORIGINAL_STORAGE_KEY)).checkpoints[0];
assert.equal(entry.view.anchor.item_id,'item');assert.equal(entry.view.reader_scroll.top,1781);
''')
 def test_character_metadata_bridge_stays_with_exact_native_item(self):
  self.check(r'''
captured.items.get(key).character={offset:36332,top:-4.75};saveOriginalReading();
assert.deepEqual(originalReadingView().items.get(key).character,captured.items.get(key).character);
const row=JSON.parse(values.get(h.ORIGINAL_STORAGE_KEY)).checkpoints[0].view.item_views[0];
assert.deepEqual(row.visible_character,{offset:36332,top:-4.75});assert.equal(row.item_id,'item');
''')
 def test_capture_restore_metadata_and_page_by_exact_identity(self):
  self.check(r'''
saveOriginalReading();const raw=values.get(h.ORIGINAL_STORAGE_KEY);assert(!raw.includes('POINTER QUOTE'));
rows=[...Array.from({length:45},(_,i)=>({turn:source.turns[0],item:{id:'neighbor-'+i}})),...rows];
source.turns[0].items=rows.map(r=>r.item);
const restored=originalReadingView();assert.equal(page,1);assert.deepEqual(restored.items,captured.items);
for(const k of ['anchor','scroll','scrollLeft','outer','outerLeft'])assert.deepEqual(restored[k],captured[k]);
''')
 def test_explicit_targets_do_not_restore_or_overwrite_normal_passage(self):
  self.check(r'''
saveOriginalReading();const raw=values.get(h.ORIGINAL_STORAGE_KEY);
for(const patch of [{turn_id:'turn'},{item_id:'item'},{match_text:'quote'}]){
 requested={thread_id:'original-A',...patch};assert.equal(originalReadingView(),null);saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);}
requested={thread_id:'original-A'};
for(const patch of [{taskResponse:true},{savedReference:{native_home:readingHome}}]){
 options={...patch,valid:()=>true};assert.equal(originalReadingView(),null);saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);}
''')
 def test_pending_close_invalid_owner_failed_read_cannot_save(self):
  self.check(r'''
saveOriginalReading();const raw=values.get(h.ORIGINAL_STORAGE_KEY);captured.scroll=4;
loading=true;saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);loading=false;
options.valid=()=>false;saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);
options.valid=()=>true;source=null;saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);
''')
 def test_nested_task_context_remembers_original_passage_not_task_disclosure(self):
  self.check(r'''
const passage=captured;taskReview={passage:{view:passage}};captured={anchor:null,items:new Map()};saveOriginalReading();
assert.equal(originalReadingView().scroll,passage.scroll);
''')
 def test_unavailable_and_other_home_use_existing_readable_page_not_substitute(self):
  self.check(r'''
saveOriginalReading();rows=[{turn:source.turns[0],item:{id:'different-item'}}];source.turns[0].items=rows.map(r=>r.item);
assert.equal(originalReadingView(),null);assert.equal(page,0);assert(status.textContent.includes('unavailable'));
const raw=values.get(h.ORIGINAL_STORAGE_KEY);saveOriginalReading();assert.equal(values.get(h.ORIGINAL_STORAGE_KEY),raw);
readingHome='b'.repeat(64);assert.equal(originalReadingView(),null);
''')
if __name__=='__main__':unittest.main()
