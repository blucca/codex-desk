"""Immediate original-reader keyboard ownership, independently of animation frames."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

READER=Path(__file__).resolve().parents[1]/'codex_desk/static/history_reader.js'
NODE=shutil.which('node')
FIXTURE=r"""
const assert=require('assert'),frames=[],targets=[];
const document={body:{},activeElement:null};document.activeElement=document.body;
class Element {
  constructor(){this.children=[];this.isConnected=true;this.scrollTop=0;this.dataset={};this.className='';this.classList={add:()=>{}};}
  append(...children){this.children.push(...children);}
  replaceChildren(){for(const child of this.children)child.disconnect();this.children=[];if(document.activeElement!==queryInput)document.activeElement=document.body;}
  disconnect(){this.isConnected=false;for(const child of this.children)child.disconnect();}
  querySelector(selector){if(selector==='mark')return null;for(const child of this.children){if(child.className==='history-reader-target')return child;const found=child.querySelector(selector);if(found)return found;}return null;}
  addEventListener(){}
  getBoundingClientRect(){return {top:100};}
  focus(options){document.activeElement=this;this.focusOptions=options;}
}
const queryInput=new Element(),elements=new Map(),el=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
const node=()=>new Element(),str=value=>typeof value==='string'?value:'';
const requestAnimationFrame=callback=>frames.push(callback);
const current=()=>true,available=()=>true;
let api;const close=()=>{},read=()=>{},submitFind=()=>{},jumpFind=()=>{},invalidate=()=>{};
const PAGE_ENTRIES=40,TEXT_CHARS=20000;let source={},version=1,page=0,originalItems=1,unsupportedItems=0,turnOnlyRows=0;
let manualNavigations=0;const manualFindNavigation=()=>{++manualNavigations;};
const rows=[{turn:{id:'turn',status:'completed',items:[]},item:{id:'item'}}];
let itemNode=()=>{const item=new Element();item.className='history-reader-target';targets.push(item);return item;};
"""


@unittest.skipUnless(NODE,'Node.js is required for the pure reader focus contract')
class HistoryReaderFocusTests(unittest.TestCase):
    def run_case(self,body):
        source=READER.read_text()
        snippets=[source[source.index('  function scrollMatch('):source.index('  function itemNode(')],
                  source[source.index('  function render('):source.index('  async function read(')],
                  source[source.index('  function configure('):source.index('  root.DeskHistoryReader=')]]
        result=subprocess.run([NODE,'-e',FIXTURE+'\n'+'\n'.join(snippets)+'\nconfigure({api(){}});\nconst pageClick=direction=>el(direction>0?"next":"previous").onclick();\n'+body+
            "\nprocess.stdout.write(JSON.stringify({passed:true}));"],text=True,capture_output=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_consecutive_rendered_targets_own_focus_before_any_animation_frame(self):
        self.run_case(r"""
render();assert.strictEqual(document.activeElement,targets[0]);
render();assert.strictEqual(document.activeElement,targets[1]);
assert.deepStrictEqual(targets[1].focusOptions,{preventScroll:true});
assert.strictEqual(frames.length,2);frames.shift()();
assert.strictEqual(document.activeElement,targets[1]);frames.shift()();
assert.strictEqual(document.activeElement,targets[1]);
""")

    def test_query_edit_render_and_late_geometry_never_steal_input_focus(self):
        self.run_case(r"""
render();document.activeElement=queryInput;const top=el('body').scrollTop;
frames.shift()();assert.strictEqual(document.activeElement,queryInput);assert.strictEqual(el('body').scrollTop,top);
render(false);assert.strictEqual(document.activeElement,queryInput);assert.strictEqual(frames.length,0);
""")

    def test_unmatched_final_page_immediately_focuses_new_reader_body(self):
        self.run_case(r"""
while(rows.length<81)rows.push({turn:rows[0].turn,item:{id:'item-'+rows.length}});
render();const old=targets[0];el('next').focus();itemNode=()=>new Element();
pageClick(1);assert.strictEqual(page,1);assert(document.activeElement===el('body'),'Fresh unmatched item page must own keyboard focus');
assert.deepStrictEqual(el('body').focusOptions,{preventScroll:true});assert.strictEqual(manualNavigations,1);
el('next').focus();pageClick(1);assert.strictEqual(page,2);assert(el('next').disabled);
assert(document.activeElement===el('body'),'Fresh unmatched item page must own keyboard focus');assert.strictEqual(el('body').scrollTop,0);
assert.strictEqual(old.isConnected,false);frames.shift()();assert(document.activeElement===el('body'),'Fresh unmatched item page must own keyboard focus');
pageClick(1);assert.strictEqual(page,2);assert.strictEqual(manualNavigations,2);
el('previous').focus();pageClick(-1);assert.strictEqual(page,1);assert(document.activeElement===el('body'),'Fresh unmatched item page must own keyboard focus');
""")

    def test_manual_match_page_retains_its_immediate_target_focus(self):
        self.run_case(r"""
while(rows.length<41)rows.push({turn:rows[0].turn,item:{id:'item-'+rows.length}});
el('next').focus();pageClick(1);assert.strictEqual(page,1);assert.strictEqual(document.activeElement,targets[0]);
assert.strictEqual(manualNavigations,1);assert.strictEqual(frames.length,1);
""")

    def test_turn_only_page_gets_keyboard_destination_and_bounds_do_not_move_focus(self):
        self.run_case(r"""
while(rows.length<41)rows.push({turn:rows[0].turn,item:null});turnOnlyRows=40;
el('next').focus();pageClick(1);assert.strictEqual(page,1);assert(document.activeElement===el('body'),'Fresh unmatched item page must own keyboard focus');
assert(el('next').disabled);assert(el('coverage').textContent.includes('Page 2 of 2'));
queryInput.focus();pageClick(1);assert.strictEqual(document.activeElement,queryInput);assert.strictEqual(manualNavigations,1);
page=0;pageClick(-1);assert.strictEqual(document.activeElement,queryInput);
source=null;pageClick(1);assert.strictEqual(page,0);assert.strictEqual(document.activeElement,queryInput);
""")


if __name__=='__main__':
    unittest.main()
