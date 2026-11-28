"""Previous successful original snapshot identities, not consumed reading."""
import json
from pathlib import Path
import subprocess
import unittest

HELPER=Path(__file__).resolve().parents[1]/'codex_desk/static/original_frontier.js'
SETUP=r'''
const assert=require('assert/strict'),h=require(process.argv[1]),values=new Map();
const storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)};
const owner={native_home:'a'.repeat(64),thread_id:'original-A'};
const thread=(ids)=>({id:'original-A',turns:[{id:'turn',items:ids.map(id=>({id,type:'agentMessage',text:'PRIVATE source body'}))}]});
const a=thread(['old-1','old-2']),b=thread(['old-1','old-2','new-1','new-2']);
'''
class OriginalFrontier(unittest.TestCase):
    def check(self,body):
        r=subprocess.run(['node','-e',SETUP+body,str(HELPER)],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr+r.stdout)

    def test_exact_previous_tail_identifies_first_later_native_item(self):
        self.check("const old=h.snapshot(a);assert.deepEqual(old,{item_count:2,boundary:{turn_id:'turn',item_id:'old-2'}});assert.deepEqual(h.resolve(old,b),{status:'new_items',count:2,target:{turn_id:'turn',item_id:'new-1'},index:2});")

    def test_first_read_and_unchanged_are_distinct(self):
        self.check("assert.equal(h.resolve(null,a).status,'first_read');assert.equal(h.resolve(h.snapshot(a),a).status,'unchanged');")

    def test_new_native_turn_first_item_comes_before_later_response(self):
        self.check("const fresh=structuredClone(a);fresh.turns.push({id:'first-new-turn',items:[{id:'first-new-user'}]},{id:'later-turn',items:[{id:'latest-response'}]});const result=h.resolve(h.snapshot(a),fresh);assert.deepEqual(result.target,{turn_id:'first-new-turn',item_id:'first-new-user'});assert.equal(result.count,2);")

    def test_empty_prior_snapshot_resolves_first_new_supplied_item(self):
        self.check("const empty=thread([]);assert.deepEqual(h.snapshot(empty),{item_count:0,boundary:null});assert.equal(h.resolve(h.snapshot(empty),a).index,0);assert.equal(h.resolve(h.snapshot(empty),empty).status,'unchanged');")

    def test_mutable_existing_text_is_not_a_new_item(self):
        self.check("const fresh=structuredClone(a);fresh.turns[0].items[0].text+=' changed';assert.equal(h.resolve(h.snapshot(a),fresh).status,'unchanged');")

    def test_missing_prior_boundary_never_guesses_latest_or_equal_text(self):
        self.check("assert.equal(h.resolve(h.snapshot(a),thread(['same-body','new-1'])).status,'previous_boundary_unavailable');")

    def test_duplicate_item_or_turn_prior_boundary_reports_ambiguity(self):
        self.check("assert.equal(h.resolve(h.snapshot(a),thread(['old-1','old-2','old-2','new-1'])).status,'previous_boundary_ambiguous');const fresh=structuredClone(b);fresh.turns.push({id:'turn',items:[]});assert.equal(h.resolve(h.snapshot(a),fresh).status,'previous_boundary_ambiguous');")

    def test_displaced_prior_boundary_reports_changed_source_order(self):
        self.check("assert.equal(h.resolve(h.snapshot(a),thread(['inserted-before','old-1','old-2','new-1'])).status,'previous_boundary_changed');")

    def test_unaddressable_first_later_item_is_not_skipped(self):
        self.check("const fresh=thread(['old-1','old-2','new-1']);fresh.turns[0].items.splice(2,0,{text:'Missing ID'});assert.equal(h.resolve(h.snapshot(a),fresh).status,'new_item_unavailable');")

    def test_ambiguous_first_new_item_is_not_replaced_by_second(self):
        self.check("assert.equal(h.resolve(h.snapshot(a),thread(['old-1','old-2','new-1','new-1','new-2'])).status,'new_item_ambiguous');")

    def test_stored_metadata_has_no_bodies_and_home_thread_owners_separate(self):
        self.check("const store=h.create(storage,{now:()=>10});assert.equal(store.get(owner),null);store.put(owner,h.snapshot(a));const raw=values.get(h.STORAGE_KEY);assert(!raw.includes('PRIVATE'));assert.deepEqual(store.get(owner),h.snapshot(a));assert.equal(store.get({...owner,native_home:'b'.repeat(64)}),null);assert.equal(store.get({...owner,thread_id:'other'}),null);")

    def test_captured_previous_snapshot_stays_frozen_when_latest_storage_advances(self):
        self.check("const store=h.create(storage);store.put(owner,h.snapshot(a));const previous=store.get(owner);store.put(owner,h.snapshot(b));assert.equal(h.resolve(previous,b).target.item_id,'new-1');assert.equal(h.resolve(store.get(owner),b).status,'unchanged');")

    def test_corrupt_storage_is_availability_and_next_capture_can_recover(self):
        self.check("const store=h.create(storage);values.set(h.STORAGE_KEY,'broken');assert.throws(()=>store.get(owner));store.put(owner,h.snapshot(a));assert.deepEqual(store.get(owner),h.snapshot(a));")

    def test_owners_and_metadata_size_bounded(self):
        self.check("let now=0;const store=h.create(storage,{now:()=>++now});for(let i=0;i<105;i++)store.put({...owner,thread_id:'original-'+i},h.snapshot(a));assert.equal(JSON.parse(values.get(h.STORAGE_KEY)).snapshots.length,100);assert(values.get(h.STORAGE_KEY).length<h.LIMITS.characters);assert.equal(store.get({...owner,thread_id:'original-0'}),null);")

if __name__=='__main__':unittest.main()
