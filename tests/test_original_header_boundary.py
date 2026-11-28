"""Command output positions survive changing generated headers without changing v1 text."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest
ROOT=Path(__file__).resolve().parents[1]
S=(ROOT/'codex_desk/static/history_reader.js').read_text()
HELPERS=S[S.index('  function commandOutputStart('):S.index('  function saveOriginalReading(')]
TEXT=S[S.index('  function textFor('):S.index('  function flatten(')]
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
SETUP=r'''const assert=require('assert/strict'),h=require(process.argv[1]),loaded=require(process.argv[2]),E=globalThis.DeskEvidencePreparation,root={},str=v=>typeof v==='string'?v:'';
const command={id:'native-command',type:'commandExecution',command:'fixture inspect source',status:'inProgress',exitCode:null,aggregatedOutput:'Line 1\r\nCafé 项目 😀 exact output\nLine 3'};
const fresh={...command,status:'completed',exitCode:0};
const row=item=>({turn:{id:'native-turn'},item}),key=JSON.stringify(['native-turn',command.id]),rowKey=r=>r?.item?JSON.stringify([r.turn.id,r.item.id]):null;
const clone=v=>JSON.parse(JSON.stringify(v));
'''
@unittest.skipUnless(NODE,'Node is required for original boundary units')
class OriginalHeaderBoundaryTests(unittest.TestCase):
 def check(self,body):
  r=subprocess.run([NODE,'-e',SETUP+TEXT+HELPERS+body,str(ROOT/'codex_desk/static/reading_checkpoint.js'),str(ROOT/'codex_desk/static/evidence-preparation.js')],capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_numeric_output_mapping_keeps_original_projection_and_body_relative_glyph(self):
  self.check(r'''
const before=commandOutputStart(command),after=commandOutputStart(fresh);assert.equal(before,69);assert.equal(after,57);
assert.equal(textFor(command).slice(before),command.aggregatedOutput);assert.equal(textFor(fresh).slice(after),command.aggregatedOutput);
const source={items:new Map([[key,{start:before+3,scroll:77,character:{offset:before+9,top:-3},commandOutputStart:before}]]),selection:{key,start:before+9,end:before+13,text:'Café',backward:true},anchor:{key,offset:-3}};
const mapped=mapOriginalOutput(source,[row(fresh)]),saved=mapped.items.get(key);
assert.equal(saved.start,after+3);assert.deepEqual(saved.character,{offset:after+9,top:-3});assert.equal(saved.scroll,77);
assert.equal(mapOutputAnchor(source.selection,source,[row(fresh)]).start,after+9);
assert.equal(mapped.selection.start,after+9);assert.equal(mapped.selection.end,after+13);assert(mapped.selection.backward);
assert.equal(source.items.get(key).start,before+3);assert.equal(source.selection.start,before+9);
assert.deepEqual(mapOriginalOutput(mapped,[row(fresh)]),mapped);
''')
 def test_header_cross_boundary_legacy_removed_ambiguous_or_changed_kind_never_invent_mapping(self):
  self.check(r'''
const before=commandOutputStart(command),after=commandOutputStart(fresh),saved={start:0,scroll:77,character:{offset:before-1,top:0},commandOutputStart:before};
const source={items:new Map([[key,saved]]),selection:{key,start:before-1,end:before+9,text:'header/body'}};
const mapped=mapOriginalOutput(source,[row(fresh)]);assert.equal(mapped.items.get(key).start,0);assert.equal(mapped.items.get(key).character.offset,before-1);assert.deepEqual(mapped.selection,source.selection);
assert.deepEqual(outputSpan(source.selection,before,after),source.selection);
for(const rows of [[],[row(fresh),row(fresh)],[row({...fresh,type:'agentMessage'})],[row({...fresh,aggregatedOutput:null})]])assert.deepEqual(mapOriginalOutput(source,rows),source);
const legacy={items:new Map([[key,{start:800,character:{offset:900,top:0}}]])};assert.deepEqual(mapOriginalOutput(legacy,[row(fresh)]),legacy);
''')
 def test_passive_resize_reuses_only_exact_glyph_not_later_scroll_selection_or_window(self):
  self.check(r'''const before={items:new Map([[key,{start:30000,open:true,scroll:88,character:{offset:38721,top:-4}}]]),anchor:{key,offset:-70,screenTop:180}};
const current={items:new Map([[key,{start:30000,open:true,scroll:244,character:{offset:37965,top:-2}}]]),scroll:17,outer:31,selection:{text:'latest selection'}};
const retained=resizeOriginalCharacters(before,current);assert.deepEqual(retained.items.get(key).character,before.items.get(key).character);
assert.deepEqual(retained.anchor,before.anchor);assert.equal(retained.items.get(key).scroll,244);assert.equal(retained.scroll,17);assert.equal(retained.outer,31);assert.strictEqual(retained.selection,current.selection);
current.items.get(key).start=40000;assert.deepEqual(resizeOriginalCharacters(before,current),current);
current.items.get(key).start=30000;current.items.get(key).open=false;assert.deepEqual(resizeOriginalCharacters(before,current),current);
''')
 def test_existing_storage_whitelists_one_numeric_boundary_only(self):
  self.check(r'''
const values=new Map(),store=h.createOriginal({getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,v)},{now:()=>1}),owner={native_home:'a'.repeat(64),thread_id:'source'};
const view={latest:false,anchor:{turn_id:'native-turn',item_id:command.id},item_views:[{turn_id:'native-turn',item_id:command.id,command_output_start:69,body:'SECRET SOURCE',header:'SECRET HEADER',quote:'SECRET QUOTE'}]};
store.put(owner,view);assert.equal(store.get(owner).view.item_views[0].command_output_start,69);assert(!values.get(h.ORIGINAL_STORAGE_KEY).includes('SECRET'));
for(const n of [-1,1.5,NaN,Infinity,'69',1e9+1]){view.item_views[0].command_output_start=n;assert.throws(()=>store.put(owner,view));}
delete view.item_views[0].command_output_start;store.put(owner,view);assert(!Object.hasOwn(store.get(owner).view.item_views[0],'command_output_start'));
''')
 def test_saved_evidence_projection_and_literal_span_do_not_follow_header_change(self):
  self.check(r'''
const home='a'.repeat(64),thread={id:'source',turns:[{id:'native-turn',status:'inProgress',items:[command]}]},start=textFor(command).indexOf('Café');
const reference=E.capture(thread,{native_home:home,thread_id:'source',turn_id:'native-turn',item_id:command.id,start_utf16:start,end_utf16:start+4,textFor:textFor});
assert.equal(E.resolve(reference,home,thread,textFor).available,true);
const result=E.resolve(reference,home,{...thread,turns:[{...thread.turns[0],items:[fresh]}]},textFor);
assert.equal(result.available,false);assert.equal(reference.projection,'history-reader-text/v1');assert.equal(reference.quote,'Café');
''')
if __name__=='__main__':unittest.main()
