"""Bounded browser reading metadata, exact fresh-source identity and precedence."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from examples.build_browser_preview import sample_threads

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
HARNESS = r'''
const assert=require('assert/strict');
const forbidden=()=>{throw Error('Reading metadata cannot perform native or DOM operations');};
globalThis.fetch=globalThis.api=forbidden;
Object.defineProperty(globalThis,'document',{get:forbidden});
globalThis.localStorage=globalThis.sessionStorage={getItem:forbidden,setItem:forbidden};
const h=require(process.argv[1]);assert.equal(globalThis.DeskReadingCheckpoint,h);
const home='4'.repeat(64),owner={native_home:home,session:'saved-A',thread_id:'thread-A'};
const view={latest:false,anchor:{turn_id:'turn-A',item_id:'item-A',offset:-13.75,screen_top:86.5},
 window_scroll:{top:777.25,left:2},item_views:[
  {turn_id:'turn-A',item_id:'item-A',open:true,window_start:20000,scroll_top:401.5,scroll_left:7},
  {turn_id:'turn-A',item_id:'plain-A',open:null,scroll_top:12}],turn_views:[
  {turn_id:'turn-A',kind:'collaboration',open:true,scroll_top:11},
  {turn_id:'turn-A',kind:'native_steps',open:true,scroll_top:21},
  {turn_id:'turn-A',kind:'turn_changes',open:false,scroll_top:31}]};
const source={...owner,turn_ids:['turn-A','turn-B'],items:[
 {turn_id:'turn-A',item_id:'item-A'},{turn_id:'turn-A',item_id:'plain-A'},
 {turn_id:'turn-B',item_id:'item-A'}],native_steps_turn:'turn-A',turn_changes_turn:'turn-A'};
const clone=value=>JSON.parse(JSON.stringify(value));
const freeze=value=>{if(value && typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
function storage(){const values=new Map([['unrelated','keep']]);let reads=0,writes=0;
 return {values,get reads(){return reads;},get writes(){return writes;},
  getItem:key=>{++reads;return values.get(key) ?? null;},
  setItem:(key,value)=>{++writes;values.set(key,value);}};}
const memory=storage(),store=h.create(memory,{now:()=>123});
'''


@unittest.skipUnless(NODE, 'Node is required for browser reading metadata units')
class ReadingCheckpointTests(unittest.TestCase):
    def check(self, body, fixture=None):
        result = subprocess.run([NODE, '-e', HARNESS + body,
            str(ROOT / 'codex_desk/static/reading_checkpoint.js')],
            input=json.dumps(fixture) if fixture is not None else None,
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_metadata_whitelist_cannot_persist_native_or_preparation_content(self):
        self.check(r'''
const secret='PRIVATE native body draft queue answers quote';
const decorated=clone(view);decorated.text=decorated.draft=decorated.body=secret;
decorated.anchor.quote=secret;decorated.window_scroll.answer=secret;
decorated.item_views.forEach(row=>{row.text=secret;row.node={textContent:secret};});
decorated.turn_views.forEach(row=>{row.plan=row.diff=secret;});
const saved=store.put({...owner,cwd:secret,profile:secret},decorated);
assert(saved.stored);const raw=memory.values.get(h.STORAGE_KEY);
assert(!raw.includes(secret));assert.equal(memory.values.get('unrelated'),'keep');
assert.deepEqual(Object.keys(saved.checkpoint.owner),['native_home','session','thread_id']);
assert.deepEqual(Object.keys(saved.checkpoint.view),['latest','anchor','window_scroll','item_views','turn_views']);
assert.equal(saved.checkpoint.view.item_views[1].open,null);
assert.equal(saved.checkpoint.view.item_views[1].window_start,0);
''')

    def test_validates_actual_opaque_ids_and_finite_scroll_window_metadata(self):
        self.check(r'''
for(const id of ['', '   ', 'x'.repeat(201), null, 1]){
 assert.throws(()=>store.put({...owner,session:id},view));
 const bad=clone(view);bad.anchor.item_id=id;assert.throws(()=>h.normalizeView(bad));
}
store.put({...owner,session:'🙂'.repeat(200)},view);
assert.throws(()=>store.put({...owner,session:'🙂'.repeat(201)},view));
assert.throws(()=>store.put({...owner,native_home:'A'.repeat(64)},view));
for(const n of [NaN,Infinity,-Infinity,-1,1e9+1,'4',null]){
 const bad=clone(view);bad.item_views[0].scroll_top=n;assert.throws(()=>h.normalizeView(bad));
}
for(const n of [0.5,-1,Infinity]){const bad=clone(view);bad.item_views[0].window_start=n;assert.throws(()=>h.normalizeView(bad));}
for(const field of ['item_views','turn_views'])for(const badValue of [null,0,'']){
 const bad=clone(view);bad[field]=badValue;assert.throws(()=>h.normalizeView(bad));
}
assert.throws(()=>h.normalizeView({...view,latest:'true'}));
assert.throws(()=>h.normalizeView({...view,item_views:[...view.item_views,view.item_views[0]]}));
assert.throws(()=>h.normalizeView({...view,turn_views:[{turn_id:'turn-A',kind:'answer',open:true}]}));
assert.equal(memory.writes,1);
''')

    def test_same_browser_restart_resolves_only_fresh_native_identity_metadata(self):
        self.check(r'''
store.put(owner,view);const before=memory.values.get(h.STORAGE_KEY),writes=memory.writes;
const reopened=h.create(memory),fresh=clone(source);
Object.defineProperty(fresh,'native_body',{get:forbidden});
fresh.items.forEach(row=>Object.defineProperty(row,'text',{get:forbidden}));
const restored=reopened.restore(owner,fresh);
assert.equal(restored.status,'restored');assert(restored.available);
assert.deepEqual(restored.view,h.normalizeView(view));
assert.equal(memory.writes,writes);assert.equal(memory.values.get(h.STORAGE_KEY),before);
assert.equal(restored.view.anchor.turn_id,'turn-A');assert.equal(restored.view.anchor.item_id,'item-A');
''')

    def test_home_session_and_changed_thread_never_restore_another_owner(self):
        self.check(r'''
const saved=store.put(owner,view).checkpoint;
for(const [field,value,status] of [['native_home','5'.repeat(64),'home_mismatch'],
 ['session','saved-B','session_mismatch'],['thread_id','thread-B','thread_mismatch']]){
 assert.equal(h.resolve({...owner,[field]:value},saved,source).status,status);
 assert.equal(h.resolve(owner,saved,{...source,[field]:value}).status,status);
 assert.equal(store.get({...owner,[field]:value}),null);
 assert.equal(store.restore({...owner,[field]:value},{...source,[field]:value}).status,'checkpoint_missing');
}
''')

    def test_missing_anchor_cannot_borrow_equal_item_id_from_another_task(self):
        self.check(r'''
const saved=store.put(owner,view).checkpoint;
const fresh={...source,items:source.items.filter(row=>row.turn_id!=='turn-A' || row.item_id!=='item-A')};
const restored=h.resolve(owner,saved,fresh);
assert.equal(restored.status,'anchor_unavailable');assert.equal(restored.view,null);
assert.deepEqual(restored.unavailable,[{kind:'anchor',turn_id:'turn-A',item_id:'item-A',reason:'item_unavailable'}]);
assert.equal(h.resolveView({...view,anchor:null},source).status,'anchor_unavailable');
''')

    def test_ambiguous_exact_turn_or_item_is_availability_not_a_substitute(self):
        self.check(r'''
assert.equal(h.resolveView(view,{...source,items:[...source.items,source.items[0]]}).status,'anchor_ambiguous');
assert.equal(h.resolveView(view,{...source,turn_ids:[...source.turn_ids,'turn-A']}).status,'anchor_ambiguous');
assert.equal(h.resolveView(view,{...source,turn_ids:['turn-B']}).status,'anchor_unavailable');
assert.equal(h.resolveView(view,{...source,items:[{turn_id:'turn-A',item_id:''}]}).status,'source_unavailable');
''')

    def test_explicit_source_search_evidence_and_response_destinations_win_first(self):
        self.check(r'''
const unreadable=h.create({getItem:forbidden,setItem:forbidden});
for(const kind of ['source','search','evidence','response']){
 const options={explicitTarget:{kind,available:false,turn_id:'missing',item_id:'missing'}};
 assert.equal(h.resolve(null,null,null,options).status,'explicit_target');
 assert.equal(h.resolveView(null,null,options).status,'explicit_target');
 assert.equal(unreadable.restore(null,null,options).status,'explicit_target');
}
assert.equal(h.resolveView(null,null,{explicitTarget:true}).status,'explicit_target');
assert.equal(h.resolveView(view,source,{explicitTarget:false}).status,'restored');
''')

    def test_deliberate_latest_intent_survives_new_output_without_old_anchor(self):
        self.check(r'''
const latest={...view,latest:true};store.put(owner,latest);
const fresh={...source,items:source.items.filter(row=>row.item_id!=='item-A')};
const restored=store.restore(owner,fresh);
assert.equal(restored.status,'latest');assert(restored.available);assert.equal(restored.view.anchor,null);
assert.equal(restored.view.item_views.length,1);assert.equal(restored.view.item_views[0].item_id,'plain-A');
assert.equal(restored.unavailable[0].reason,'item_unavailable');
assert.equal(store.get(owner).view.latest,true);
''')

    def test_turn_readouts_and_collaboration_restore_only_their_actual_turns(self):
        self.check(r'''
const fresh={...source,native_steps_turn:'turn-B',turn_changes_turn:null};
const restored=h.resolveView(view,fresh);
assert.equal(restored.status,'restored');
assert.deepEqual(restored.view.turn_views.map(row=>row.kind),['collaboration']);
assert.deepEqual(restored.unavailable.map(row=>[row.kind,row.turn_id,row.reason]),[
 ['native_steps','turn-A','turn_changed'],['turn_changes','turn-A','turn_changed']]);
''')

    def test_recent_owner_and_view_bounds_preserve_exact_anchor_and_do_not_promote_reads(self):
        self.check(r'''
const large={...view,item_views:Array.from({length:70},(_,n)=>({turn_id:'turn-A',item_id:'extra-'+n,open:false})),
 turn_views:Array.from({length:70},(_,n)=>({turn_id:'turn-'+n,kind:'collaboration',open:false}))};
large.item_views.push(view.item_views[0]);large.turn_views.push(view.turn_views[1]);
const normalized=h.normalizeView(large);
assert.equal(normalized.item_views.length,40);assert.equal(normalized.turn_views.length,40);
assert.equal(normalized.item_views[0].item_id,'item-A');assert.equal(normalized.turn_views[0].kind,'native_steps');
for(let n=0;n<105;n++)store.put({...owner,session:'saved-'+n},view);
assert.equal(store.read().checkpoints.length,100);assert.equal(store.get({...owner,session:'saved-0'}),null);
const before=memory.values.get(h.STORAGE_KEY);store.get({...owner,session:'saved-5'});
assert.equal(memory.values.get(h.STORAGE_KEY),before);
store.put({...owner,session:'saved-5'},view);store.put({...owner,session:'saved-105'},view);
assert(store.get({...owner,session:'saved-5'}));assert.equal(store.get({...owner,session:'saved-6'}),null);
''')

    def test_serialized_metadata_budget_evicts_oldest_without_content_storage(self):
        self.check(r'''
const heavy={latest:true,anchor:null,item_views:Array.from({length:40},(_,n)=>({
 turn_id:'t'.repeat(190)+n,item_id:'i'.repeat(190)+n,open:true,window_start:100000,scroll_top:10000})),
 turn_views:Array.from({length:40},(_,n)=>({turn_id:'z'.repeat(190)+n,kind:'collaboration',open:true,scroll_top:10000}))};
for(let n=0;n<100;n++)assert(store.put({...owner,session:'owner-'+n},heavy).stored);
const raw=memory.values.get(h.STORAGE_KEY);
assert(raw.length<=h.LIMITS.characters);assert(store.read().checkpoints.length<100);
assert(store.get({...owner,session:'owner-99'}));assert.equal(store.get({...owner,session:'owner-0'}),null);
assert.equal(memory.values.get('unrelated'),'keep');
''')

    def test_corrupt_storage_read_is_read_only_and_scoped_remove_preserves_other_owners(self):
        self.check(r'''
memory.values.set(h.STORAGE_KEY,'bad json');assert.equal(store.read().status,'invalid_storage');assert.equal(memory.writes,0);
assert.equal(store.restore(owner,source).status,'invalid_storage');
store.put(owner,view);const other={...owner,native_home:'5'.repeat(64)};store.put(other,view);
const tainted=JSON.parse(memory.values.get(h.STORAGE_KEY));tainted.checkpoints.push({version:8});
tainted.checkpoints[0].body='discard this unexpected native body';memory.values.set(h.STORAGE_KEY,JSON.stringify(tainted));
const writes=memory.writes;assert.equal(store.read().checkpoints.length,2);assert.equal(memory.writes,writes);
assert(!JSON.stringify(store.get(other)).includes('unexpected native body'));
assert(store.remove(owner).removed);assert(store.get(other));assert.equal(store.get(owner),null);
const after=memory.writes;assert.equal(store.remove(owner).status,'not_found');assert.equal(memory.writes,after);
assert.equal(memory.values.get('unrelated'),'keep');
''')

    def test_storage_failure_does_not_change_previous_saved_metadata_or_other_keys(self):
        self.check(r'''
store.put(owner,view);const before=memory.values.get(h.STORAGE_KEY);
const blocked=h.create({getItem:key=>memory.getItem(key),setItem:()=>{throw Error('Quota exceeded');}},{now:()=>124});
const changed={...view,latest:true};assert.equal(blocked.put(owner,changed).stored,false);
assert.equal(memory.values.get(h.STORAGE_KEY),before);assert.equal(blocked.get(owner).view.latest,false);
assert.equal(blocked.remove(owner).removed,false);
const denied=h.create({getItem:()=>{throw Error('Storage disabled');},setItem:forbidden});
assert.equal(denied.put(owner,view).status,'storage_unavailable');
assert.equal(denied.restore(owner,source).status,'storage_unavailable');
assert.equal(memory.values.get('unrelated'),'keep');
''')

    def test_immutable_supplied_sample_catalog_uses_only_native_identity_fields(self):
        self.check(r'''
const fs=require('fs'),threads=freeze(JSON.parse(fs.readFileSync(0,'utf8')));
for(const thread of threads){
 const turn=thread.turns[0],item=turn.items.find(row=>row.type==='commandExecution');
 const at={latest:false,anchor:{turn_id:turn.id,item_id:item.id},item_views:[{turn_id:turn.id,item_id:item.id,open:true}]};
 const fresh={...owner,thread_id:thread.id,turn_ids:thread.turns.map(row=>row.id),items:thread.turns.flatMap(t=>t.items.map(i=>({turn_id:t.id,item_id:i.id})))};
 const frozen=freeze(at),before=JSON.stringify(frozen);store.put({...owner,thread_id:thread.id},frozen);
 const restored=store.restore({...owner,thread_id:thread.id},freeze(fresh));assert.equal(restored.status,'restored');
 assert.equal(restored.view.anchor.item_id,item.id);assert.equal(JSON.stringify(frozen),before);
 assert(!memory.values.get(h.STORAGE_KEY).includes(item.aggregatedOutput));
}
''', fixture=sample_threads())


if __name__ == '__main__':
    unittest.main()
