"""Literal, native-item-scoped selection restoration across original windows."""
from pathlib import Path
import shutil
import subprocess
import unittest

SOURCE = (Path(__file__).resolve().parents[1] / 'codex_desk/static/history_reader.js').read_text()
HELPERS = SOURCE[SOURCE.index('  function textPoint('):SOURCE.index('  function captureView(')]
SETUP = r'''
const assert=require('assert/strict'),NodeFilter={SHOW_TEXT:4};
const nodes=[{data:'Before '},{data:'retry budget'},{data:' after'}],prefix='x'.repeat(50000);
const full=prefix+nodes.map(n=>n.data).join(''),key=JSON.stringify(['native-turn','native-item']);
const row={turn:{id:'native-turn'},item:{id:'native-item',text:full}},pre={nodes};
let rows=[row],items=[{dataset:{turnId:'native-turn',itemId:'native-item',windowStart:'50000'},querySelector:()=>pre}],calls=[];
const status={textContent:''},root={getSelection:()=>({setBaseAndExtent(...args){calls.push(args);}})};
const document={createTreeWalker:pre=>{let i=0;return {nextNode:()=>pre.nodes[i++]||null};}};
const rowKey=row=>JSON.stringify([row.turn.id,row.item.id]);
const elementKey=item=>JSON.stringify([item.dataset.turnId,item.dataset.itemId]);
const viewItems=()=>items,el=()=>status,textFor=item=>item.text;
const saved={key,start:50007,end:50019,text:'retry budget',backward:false};
'''


@unittest.skipUnless(shutil.which('node'), 'Node is required for original selection checks')
class OriginalSelectionTests(unittest.TestCase):
    def run_js(self, body):
        result = subprocess.run(['node', '-e', SETUP + HELPERS + body], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_window_offsets_and_mark_text_nodes_restore_backward_selection(self):
        self.run_js("""
restoreSelectedText(saved);assert.equal(calls.length,1);
assert.strictEqual(calls[0][0],nodes[0]);assert.equal(calls[0][1],7);
assert.strictEqual(calls[0][2],nodes[1]);assert.equal(calls[0][3],12);
calls=[];restoreSelectedText({...saved,backward:true});
assert.strictEqual(calls[0][0],nodes[1]);assert.equal(calls[0][1],12);
assert.strictEqual(calls[0][2],nodes[0]);assert.equal(calls[0][3],7);
""")

    def test_changed_text_or_native_item_never_selects_repeated_text_elsewhere(self):
        self.run_js("""
row.item.text=full.replace('retry budget','other budget');
rows.push({turn:{id:'other-turn'},item:{id:'other-item',text:full}});
restoreSelectedText(saved);assert.equal(calls.length,0);assert(status.textContent.includes('selected original text changed'));
rows.shift();restoreSelectedText(saved);assert.equal(calls.length,0);
assert(status.textContent.includes('not moved to another source'));
""")

    def test_window_not_containing_original_span_reports_location_without_substitution(self):
        self.run_js("""
items[0].dataset.windowStart='50020';restoreSelectedText(saved);assert.equal(calls.length,0);
assert(status.textContent.includes('original location'));
restoreSelectedText(null);assert.equal(calls.length,0);
""")


if __name__ == '__main__':
    unittest.main()
