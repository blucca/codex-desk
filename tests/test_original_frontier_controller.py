"""Execute the shipped frontier bridge, frozen comparison and exact navigation."""
from pathlib import Path
import json
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/history_reader.js').read_text()
HELPERS=SOURCE[SOURCE.index('  function originalFrontierControls()'):SOURCE.index('  function originalReadingStore()')]
SETUP=r'''
const assert=require('assert/strict'),values=new Map();
const root={DeskOriginalFrontier:require(process.argv[1]),localStorage:{getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)}};
let originalFrontier=null,frontierStorage=null,readingHome='a'.repeat(64),version=7,live=true,loading=false,refreshing=false,taskReview=null;
let findVersion=0,finding=false,findSubmitted=true,findQuery='old quote',findGroups=[1],findTotal=1,findCursor=0;
let requested={thread_id:'A'},targetIndex=0,page=0;
const sourceOf=ids=>({id:'A',turns:[{id:'turn',items:ids.map(id=>({id,type:'agentMessage',text:'Original source text'}))}]});
let source=sourceOf(['old-1','old-2']);let rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));
const elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,{textContent:'',hidden:false,disabled:false,value:''});return elements.get(id);};
const PAGE_ENTRIES=40,current=t=>live&&t===version,available=()=>current(version),explicitReadingTarget=()=>!!requested.item_id;
const passage={source,requested:{...requested},view:{anchor:{key:'old-native-anchor'},selection:{text:'Original quote'}},find:{query:'old quote'}};
const taskSnapshot=()=>passage,findControls=()=>{},rendered=[],render=()=>rendered.push({requested:{...requested},page,targetIndex,taskReview});
function supplied(ids){source=sourceOf(ids);rows=source.turns.flatMap(turn=>turn.items.map(item=>({turn,item})));}
'''
class OriginalFrontierController(unittest.TestCase):
    def check(self,body):
        r=subprocess.run(['node','-e',SETUP+HELPERS+body,str(ROOT/'codex_desk/static/original_frontier.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stderr+r.stdout)

    def test_first_success_initializes_and_second_read_resolves_prior_boundary(self):
        self.check("captureOriginalFrontier(7);assert.equal(originalFrontier.result.status,'first_read');resetOriginalFrontier();supplied(['old-1','old-2','new-1']);captureOriginalFrontier(7);assert.equal(originalFrontier.result.target.item_id,'new-1');assert(el('new-status').textContent.includes('New since previous fresh original read'));assert(!el('first-new').disabled);")

    def test_refresh_keeps_frozen_previous_comparison_but_commits_latest_for_next_visit(self):
        self.check("captureOriginalFrontier(7);resetOriginalFrontier();supplied(['old-1','old-2','new-1']);captureOriginalFrontier(7);const frozen=originalFrontier.previous;supplied(['old-1','old-2','new-1','later-2']);captureOriginalFrontier(7);assert.strictEqual(originalFrontier.previous,frozen);assert.equal(originalFrontier.result.target.item_id,'new-1');assert.equal(originalFrontier.result.count,2);resetOriginalFrontier();captureOriginalFrontier(7);assert.equal(originalFrontier.result.status,'unchanged');")

    def test_exact_first_new_action_captures_prior_passage_and_target(self):
        self.check("captureOriginalFrontier(7);resetOriginalFrontier();supplied(['old-1','old-2','new-1']);captureOriginalFrontier(7);assert(readFirstNewOriginalItem());assert.deepEqual(requested,{thread_id:'A',turn_id:'turn',item_id:'new-1'});assert.strictEqual(taskReview.passage,passage);assert.equal(targetIndex,2);assert.equal(findSubmitted,false);assert.equal(readFirstNewOriginalItem(),false);")

    def test_explicit_target_does_not_acquire_or_change_normal_original_baseline(self):
        self.check("captureOriginalFrontier(7);const saved=values.get(root.DeskOriginalFrontier.STORAGE_KEY);resetOriginalFrontier();requested.item_id='exact-quote';supplied(['old-1','old-2','new-1']);captureOriginalFrontier(7);assert.equal(originalFrontier,null);assert.equal(values.get(root.DeskOriginalFrontier.STORAGE_KEY),saved);")

    def test_late_closed_or_newer_read_cannot_commit_metadata_or_open_target(self):
        self.check("live=false;captureOriginalFrontier(7);assert.equal(values.size,0);live=true;captureOriginalFrontier(6);assert.equal(values.size,0);assert.equal(readFirstNewOriginalItem(),false);")

    def test_changed_native_home_keeps_owned_boundary_unavailable(self):
        self.check("captureOriginalFrontier(7);const saved=values.get(root.DeskOriginalFrontier.STORAGE_KEY);readingHome='b'.repeat(64);supplied(['old-1','old-2','new-1']);captureOriginalFrontier(7);assert.equal(originalFrontier.result.status,'home_unavailable');assert.equal(values.get(root.DeskOriginalFrontier.STORAGE_KEY),saved);assert.equal(readFirstNewOriginalItem(),false);")

    def test_missing_boundary_retains_truthful_availability(self):
        self.check("captureOriginalFrontier(7);resetOriginalFrontier();supplied(['other','new-1']);captureOriginalFrontier(7);assert.equal(originalFrontier.result.status,'previous_boundary_unavailable');assert(el('first-new').hidden);assert(el('new-status').textContent.includes('unavailable'));")

if __name__=='__main__':unittest.main()
