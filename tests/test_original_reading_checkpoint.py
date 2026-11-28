"""Original home/thread metadata uses recovery primitives without a Desk session."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
HARNESS=r'''
const assert=require('assert/strict'),h=require(process.argv[1]);
const owner={native_home:'a'.repeat(64),thread_id:'A/接口?+'};
const key=JSON.stringify(['turn','item']);
const view={latest:false,anchor:{turn_id:'turn',item_id:'item',offset:-123.5,screen_top:134},
 window_scroll:{top:526,left:3},reader_scroll:{top:1781,left:2},item_views:[
 {turn_id:'turn',item_id:'item',window_start:26332,open:true,scroll_top:7774,scroll_left:5}],turn_views:[]};
const source={...owner,turn_ids:['turn'],items:[{turn_id:'turn',item_id:'item'}]};
const values=new Map(),storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
const store=h.createOriginal(storage,{now:()=>12});
const clone=v=>JSON.parse(JSON.stringify(v));
'''
@unittest.skipUnless(NODE,'Node is required for original reading units')
class OriginalReadingCheckpointTests(unittest.TestCase):
 def check(self,body):
  p=subprocess.run([NODE,'-e',HARNESS+body,str(ROOT/'codex_desk/static/reading_checkpoint.js')],capture_output=True,text=True,timeout=15)
  self.assertEqual(p.returncode,0,p.stdout+p.stderr)
 def test_visible_character_is_whitelisted_utf16_offset_geometry_only(self):
  self.check(r'''
const enriched=clone(view);enriched.item_views[0].visible_character={offset:36332,top:-4.75,text:'SECRET SOURCE',range:{quote:'SECRET QUOTE'}};
store.put(owner,enriched);const point=store.get(owner).view.item_views[0].visible_character;
assert.deepEqual(point,{offset:36332,top:-4.75});assert(!values.get(h.ORIGINAL_STORAGE_KEY).includes('SECRET'));
assert.deepEqual(store.restore(owner,source).view.item_views[0].visible_character,point);
for(const invalid of [{},{offset:1},{top:0},null]){enriched.item_views[0].visible_character=invalid;if(invalid!==null)assert.throws(()=>store.put(owner,enriched));}
for(const offset of [-1,0.5,NaN,Infinity,'36332']){
 enriched.item_views[0].visible_character={offset,top:0};assert.throws(()=>store.put(owner,enriched));}
for(const top of [NaN,Infinity,'2']){
 enriched.item_views[0].visible_character={offset:36332,top};assert.throws(()=>store.put(owner,enriched));}
assert(!Object.hasOwn(h.normalizeOriginalView(view).item_views[0],'visible_character'));
''')
 def test_no_session_and_separate_activity_owner(self):
  self.check(r'''
const saved=store.put({...owner,session:'WRONG B',draft:'SECRET B'},view).checkpoint;
assert.deepEqual(saved.owner,owner);assert.deepEqual(Object.keys(saved.owner),['native_home','thread_id']);
const activity=h.create(storage);activity.put({...owner,session:'B'},view);
assert.equal(values.size,2);assert(values.has(h.STORAGE_KEY));assert(values.has(h.ORIGINAL_STORAGE_KEY));
assert.deepEqual(h.createOriginal(storage).restore(owner,source).view,h.normalizeOriginalView(view));
assert.equal(activity.get({...owner,session:'B'}).owner.session,'B');
assert(!values.get(h.ORIGINAL_STORAGE_KEY).includes('SECRET B'));
''')
 def test_exact_home_thread_mismatch_and_explicit_precedence(self):
  self.check(r'''
const saved=store.put(owner,view).checkpoint;
assert.equal(h.resolveOriginal({...owner,native_home:'b'.repeat(64)},saved,source).status,'home_mismatch');
assert.equal(h.resolveOriginal({...owner,thread_id:'other'},saved,source).status,'thread_mismatch');
assert.equal(store.restore({...owner,thread_id:'other'},source).status,'checkpoint_missing');
assert.equal(store.restore(owner,{...source,native_home:'b'.repeat(64)}).status,'home_mismatch');
for(const explicitTarget of [true,{turn_id:'missing',item_id:'missing'}]){
 assert.equal(store.restore(owner,null,{explicitTarget}).status,'explicit_target');
 assert.equal(h.resolveOriginal(null,null,null,{explicitTarget}).status,'explicit_target');}
''')
 def test_removed_and_ambiguous_anchor_never_use_repeated_other_item(self):
  self.check(r'''
store.put(owner,view);
for(const fresh of [ {...source,turn_ids:[]},{...source,items:[]},
 {...source,items:[{turn_id:'turn',item_id:'other'}]} ]){
 const r=store.restore(owner,fresh);assert.equal(r.status,'anchor_unavailable');assert.equal(r.view,null);}
assert.equal(store.restore(owner,{...source,turn_ids:['turn','turn']}).status,'anchor_ambiguous');
assert.equal(store.restore(owner,{...source,items:[...source.items,...source.items]}).status,'anchor_ambiguous');
''')
 def test_only_metadata_retained_not_selection_find_or_content(self):
  self.check(r'''
const secret='FULL ORIGINAL BODY QUOTE FIND QUERY';
const decorated={...view,body:secret,quote:secret,selection:{text:secret},findQuery:secret,
 reader_scroll:{...view.reader_scroll,text:secret},anchor:{...view.anchor,text:secret},
 item_views:view.item_views.map(v=>({...v,text:secret,source:secret}))};
store.put({...owner,nativeBody:secret},decorated);assert(!values.get(h.ORIGINAL_STORAGE_KEY).includes(secret));
assert.deepEqual(Object.keys(store.get(owner).view),['latest','anchor','window_scroll','item_views','turn_views','reader_scroll']);
''')
 def test_bounded_owners_items_and_anchor_priority(self):
  self.check(r'''
const many={...view,item_views:[...Array.from({length:80},(_,i)=>({...view.item_views[0],item_id:'other-'+i})),...view.item_views]};
for(let i=0;i<110;i++)store.put({...owner,thread_id:'thread-'+i},many);
const rows=store.read().checkpoints;assert.equal(rows.length,100);assert.equal(rows[0].owner.thread_id,'thread-109');
assert.equal(rows[0].view.item_views.length,40);assert.equal(rows[0].view.item_views[0].item_id,'item');
assert(values.get(h.ORIGINAL_STORAGE_KEY).length<=h.LIMITS.characters);
''')
 def test_storage_denied_corrupt_and_bad_geometry_keep_recovery_result(self):
  self.check(r'''
const denied=h.createOriginal({getItem:()=>{throw Error('denied');},setItem:()=>{throw Error('denied');}});
assert.equal(denied.put(owner,view).stored,false);assert.equal(denied.restore(owner,source).status,'storage_unavailable');
values.set(h.ORIGINAL_STORAGE_KEY,'broken');assert.equal(store.restore(owner,source).status,'invalid_storage');
assert(store.put(owner,view).stored);assert.equal(store.restore(owner,source).status,'restored');
assert.throws(()=>store.put(owner,{...view,latest:true}));assert.throws(()=>store.put(owner,{...view,anchor:null}));
for(const bad of [-1,NaN,Infinity,'123',1e9+1])assert.throws(()=>store.put(owner,{...view,reader_scroll:{top:bad}}));
assert(store.remove(owner).removed);assert.equal(store.restore(owner,source).status,'checkpoint_missing');
''')
if __name__=='__main__':unittest.main()
