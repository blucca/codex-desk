"""Exact Tab-captured source excerpts use the actual review controller only at activation."""
from pathlib import Path
import json
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
READER = (ROOT / 'codex_desk/static/history_reader.js').read_text()
CONTROLS = READER[READER.index('  function copyControls('):READER.index('  async function readEmbeddedReference(')]
SETUP = r'''
const assert=require('assert/strict'),vm=require('vm'),fs=require('fs');vm.runInThisContext(fs.readFileSync(MODULE,'utf8'));const E=global.DeskEvidencePreparation;
class Element {
 constructor(tag,cls=''){this.tag=tag;this.className=cls;this.children=[];this.events={};this.isConnected=true;this.disabled=false;this.textContent='';}
 append(...children){this.children.push(...children);}setAttribute(){}
 contains(target){return this===target || this.children.some(child=>child.contains(target));}
 addEventListener(type,fn){(this.events[type] ||= []).push(fn);}
 fire(type,event={}){for(const fn of this.events[type]||[])fn({...event,target:event.target||this});}
}
const node=(tag,text,cls='')=>{const n=new Element(tag,cls);if(text!==undefined)n.textContent=text;return n;};
const root={DeskEvidencePreparation:E},str=value=>typeof value==='string'?value:'',visibleTypes=new Set(['commandExecution']);
let source={id:'native-A',turns:[{id:'turn-A',status:'completed',items:[{id:'item-A',type:'commandExecution',command:'inspect native original',status:'completed',exitCode:0,aggregatedOutput:'x'.repeat(9000)+'Exact Café 项目 😀 quote'+'z'.repeat(50)}]}]},row={turn:source.turns[0],item:source.turns[0].items[0]};
const textFor=E.textForItem,text=textFor(row.item),quote='Exact Café 项目 😀 quote',start=text.indexOf(quote),end=start+quote.length;
const rowKey=row=>JSON.stringify([row.turn.id,row.item.id]);
const selection={key:rowKey(row),start,end,text:quote,backward:true};let liveSelection=selection,live=true,version=4,findVersion=5,refreshVersion=2,taskReview=null;
const selectedText=()=>liveSelection,available=ticket=>live&&ticket===version,current=available;
let currentFocus=null,scroll=120,restored=[],calls=[],saves=[],homeHold=null;
const captureView=()=>({selection:liveSelection,focus:currentFocus,items:new Map(),scroll,outer:40,anchor:{key:selection.key,offset:12}});
const restoreView=(view,ticket)=>{restored.push({view,ticket});liveSelection=view.selection;};
const controller=E.createController({render:false,destination:()=>({session:'B',generation:3,revision:2,sequence:4,writer:'writer',text:'Exact unsent B Plan',mode:'plan'}),
 api:async path=>{calls.push(path);if(homeHold)await homeHold;return {home_namespace:'a'.repeat(64)};},save:async payload=>{saves.push(payload);return {...payload,revision:3};}});
const evidenceReview=payload=>controller.reviewLoaded({thread:payload.thread,thread_id:payload.thread.id,turn_id:payload.turn_id,item_id:payload.item_id,start_utf16:payload.selection_utf16?.start,end_utf16:payload.selection_utf16?.end},{valid:payload.valid,onReturn:payload.onReturn});
const detail=new Element('details');
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required for source keyboard review checks')
class ReaderKeyboardEvidenceTests(unittest.TestCase):
    def run_js(self, body):
        setup = SETUP.replace('MODULE', json.dumps(str(ROOT / 'codex_desk/static/evidence-preparation.js')))
        setup += CONTROLS + r'''
copyControls(detail,row,text,version);const actions=detail.children[0],review=actions.children.find(n=>n.className==='history-reader-review-evidence');
const tab=()=>{detail.fire('keydown',{key:'Tab'});liveSelection=null;};
const enter=()=>{currentFocus={key:selection.key,index:7};detail.fire('keydown',{key:'Enter',target:review});return review.onclick();};
(async()=>{
'''
        result = subprocess.run(['node', '-e', setup + body + r'''
assert.equal(saves.length,0);process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_real_controller_retains_literal_utf16_direction_and_pre_tab_view(self):
        self.run_js(r'''
tab();scroll=260;for(let i=0;i<7;i++)tab();await enter();const reference=controller.state().reference;
assert.equal(reference.quote,quote);assert.equal(reference.thread_id,'native-A');assert.equal(reference.turn_id,'turn-A');assert.equal(reference.item_id,'item-A');
const prefix=textFor({...row.item,aggregatedOutput:''});assert.equal(reference.projection,E.COMMAND_OUTPUT_PROJECTION);assert.equal(reference.quote_start,Array.from(text.slice(prefix.length,start)).length);assert.equal(reference.quote_end,Array.from(text.slice(prefix.length,end)).length);
controller.cancel();assert.equal(restored.length,1);assert.deepEqual(restored[0].view.selection,selection);assert.equal(restored[0].view.scroll,120);assert.equal(restored[0].view.focus.index,7);assert.equal(restored[0].ticket,4);
''')

    def test_arbitrary_no_selection_click_cannot_reuse_tab_quote(self):
        self.run_js(r'''
tab();await review.onclick();assert.equal(controller.state(),null);assert.equal(calls.length,0);
''')

    def test_pointer_or_non_tab_clear_cannot_reuse_held_quote(self):
        self.run_js(r'''
for(const clear of [()=>detail.fire('pointerdown'),()=>detail.fire('keydown',{key:'Escape'}),()=>detail.fire('keydown',{key:'ArrowRight'}),()=>detail.fire('focusout',{relatedTarget:new Element('outside')})]){
 liveSelection=selection;tab();clear();await enter();assert.equal(controller.state(),null);
}assert.equal(calls.length,0);
''')

    def test_new_native_selection_supersedes_prior_tab_quote(self):
        self.run_js(r'''
tab();const next={...selection,start:start+6,text:quote.slice(6)};liveSelection=next;tab();await enter();assert.equal(controller.state().reference.quote,next.text);controller.cancel();assert.deepEqual(restored.at(-1).view.selection,next);
''')

    def test_source_query_refresh_task_close_and_reader_epoch_invalidate_capture(self):
        self.run_js(r'''
const initialSource=source;
for(const replace of [()=>{source={...source};},()=>{findVersion++;},()=>{refreshVersion++;},()=>{taskReview={mode:'context'};},()=>{version++;},()=>{live=false;},()=>{detail.isConnected=false;}]){
 source=initialSource;findVersion=5;refreshVersion=2;taskReview=null;version=4;live=true;detail.isConnected=true;liveSelection=selection;tab();replace();await enter();assert.equal(controller.state(),null);
}assert.equal(calls.length,0);
''')

    def test_same_task_mode_or_literal_projection_replacement_invalidate_capture(self):
        self.run_js(r'''
taskReview={mode:'item'};tab();taskReview.mode='context';await enter();assert.equal(controller.state(),null);
liveSelection=selection;tab();row.item.aggregatedOutput=row.item.aggregatedOutput.replace('Exact','Other');await enter();assert.equal(controller.state(),null);assert.equal(calls.length,0);
''')

    def test_held_namespace_reply_after_owner_replacement_never_enables_append(self):
        self.run_js(r'''
let release;homeHold=new Promise(resolve=>release=resolve);tab();const pending=enter();assert(controller.state().pending);version++;detail.isConnected=false;release();await pending;
assert.equal(controller.state().reference,null);assert.equal(await controller.append(),false);controller.cancel();assert.equal(restored.length,0);
''')

    def test_pointer_review_uses_current_quote_without_keyboard_capture(self):
        self.run_js(r'''
detail.fire('pointerdown');await review.onclick();assert.equal(controller.state().reference.quote,quote);controller.cancel();assert.deepEqual(restored[0].view.selection,selection);
''')


if __name__ == '__main__':
    unittest.main()
