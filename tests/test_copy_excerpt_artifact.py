"""One source-bound clipboard artifact, independent of any destination draft."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
from test_history_reader_keyboard_evidence import SETUP

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'codex_desk/static/history_reader.js').read_text()
CONTROLS = SOURCE[SOURCE.index('  function copyControls('):SOURCE.index('  async function readEmbeddedReference(')]
SETUP = SETUP.replace("const root={DeskEvidencePreparation:E}", "const root={DeskEvidencePreparation:E,navigator:{clipboard:{writeText:async value=>{writes.push(value);if(copyHold)await copyHold;}}}}")
SETUP = SETUP.replace('const evidenceReview=payload=>', 'let evidenceReview=payload=>')
SETUP += r'''
let writes=[],copyHold=null,namespaceHold=null,readingIntentEpoch=0;
const api=async path=>{calls.push(path);if(namespaceHold)await namespaceHold;return {home_namespace:'a'.repeat(64)};};
'''

@unittest.skipUnless(shutil.which('node'), 'Node required')
class CopyExcerptArtifactTests(unittest.TestCase):
    def check(self, body):
        code = SETUP.replace('MODULE', json.dumps(str(ROOT / 'codex_desk/static/evidence-preparation.js')))
        code += CONTROLS + r'''
copyControls(detail,row,text,version);const actions=detail.children[0];
const artifact=actions.children.find(n=>n.className==='history-reader-copy-excerpt');
const status=actions.children.find(n=>n.className==='history-reader-copy-status');
const tab=()=>{detail.fire('keydown',{key:'Tab'});liveSelection=null;};
const enter=()=>{currentFocus={key:selection.key,index:6};detail.fire('keydown',{key:'Enter',target:artifact});return artifact.onclick();};
(async()=>{
'''
        result = subprocess.run(['node', '-e', code + body + r'''
assert.equal(saves.length,0);process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''], cwd=ROOT, capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout), {'passed': True})

    def test_one_exact_output_relative_unicode_artifact_without_review_destination(self):
        self.check(r'''
evidenceReview=null;assert(await artifact.onclick());assert.equal(writes.length,1);const saved=E.parse(writes[0])[0].reference;
assert.equal(saved.quote,quote);assert.equal(saved.native_home,'a'.repeat(64));assert.equal(saved.thread_id,'native-A');assert.equal(saved.turn_id,'turn-A');assert.equal(saved.item_id,'item-A');
assert.equal(saved.projection,E.COMMAND_OUTPUT_PROJECTION);assert.equal(saved.quote_start,9000);
assert.equal(saved.quote_end,9000+Array.from(quote).length);assert.equal(writes[0],E.format(saved));
assert.deepEqual(calls,['/api/native/home']);assert.equal(controller.state(),null);assert.deepEqual(liveSelection,selection);assert(!artifact.disabled);
''')

    def test_keyboard_tab_preserves_exact_quote_direction_and_prior_reader_place(self):
        self.check(r'''
tab();scroll=400;tab();assert(await enter());const saved=E.parse(writes[0])[0].reference;
assert.equal(saved.quote,quote);assert.equal(restored.at(-1).view.scroll,120);assert.deepEqual(liveSelection,selection);
assert.equal(restored.at(-1).view.focus.index,6);assert.equal(status.textContent,'Excerpt with source copied.');
''')

    def test_unchanged_live_range_through_tabs_retains_first_keyboard_view(self):
        self.check(r'''
detail.fire('keydown',{key:'Tab'});scroll=194;detail.fire('keydown',{key:'Tab'});scroll=240;
assert(await enter());assert.equal(restored.at(-1).view.scroll,120);assert.deepEqual(liveSelection,selection);
''')

    def test_unselected_and_other_item_do_not_copy_or_read_namespace(self):
        self.check(r'''
liveSelection=null;assert.equal(await artifact.onclick(),false);assert.equal(writes.length,0);assert.equal(calls.length,0);
liveSelection={...selection,key:JSON.stringify(['wrong-turn','wrong-item'])};assert.equal(await artifact.onclick(),false);assert.equal(writes.length,0);
''')

    def test_arbitrary_click_cannot_reuse_old_keyboard_selection(self):
        self.check(r'''
tab();assert.equal(await artifact.onclick(),false);assert.equal(writes.length,0);assert.equal(calls.length,0);
''')

    def test_held_namespace_after_owner_or_literal_text_change_never_writes(self):
        for change in ['version++', 'findVersion++', 'refreshVersion++', 'readingIntentEpoch++',
                       'source={...source}', "taskReview={mode:'other'}",
                       "row.item.aggregatedOutput=row.item.aggregatedOutput.replace('Exact','Other')", 'detail.isConnected=false']:
            with self.subTest(change=change):
                self.check(r'''
let release;namespaceHold=new Promise(r=>release=r);const pending=artifact.onclick();
''' + change + r''';release();assert.equal(await pending,false);assert.equal(writes.length,0);
''')

    def test_late_clipboard_completion_does_not_restore_newer_range_or_claim_success(self):
        self.check(r'''
let release;copyHold=new Promise(r=>release=r);const pending=artifact.onclick();await Promise.resolve();await Promise.resolve();assert.equal(writes.length,1);
const newer={...selection,start:start+6,text:quote.slice(6)};liveSelection=newer;readingIntentEpoch++;const restores=restored.length;release();assert.equal(await pending,false);
assert.equal(restored.length,restores);assert.deepEqual(liveSelection,newer);assert.notEqual(status.textContent,'Excerpt with source copied.');assert(!artifact.disabled);
''')

    def test_failed_clipboard_releases_controls_and_exact_retry_uses_one_artifact(self):
        self.check(r'''
root.navigator.clipboard.writeText=async()=>{throw Error('Denied clipboard');};assert.equal(await artifact.onclick(),false);assert(!artifact.disabled);assert.deepEqual(liveSelection,selection);
root.navigator.clipboard.writeText=async value=>writes.push(value);assert(await artifact.onclick());assert.equal(writes.length,1);assert.equal(E.parse(writes[0])[0].reference.quote,quote);
''')

    def test_header_crossing_selection_keeps_literal_v1_projection(self):
        self.check(r'''
const prefix=E.textForItem({...row.item,aggregatedOutput:''});const first=prefix.length-4,last=prefix.length+4;
liveSelection={key:selection.key,start:first,end:last,text:text.slice(first,last),backward:false};assert(await artifact.onclick());
assert.equal(E.parse(writes[0])[0].reference.projection,E.PROJECTION);assert.equal(E.parse(writes[0])[0].reference.quote_start,Array.from(text.slice(0,first)).length);
''')

    def test_duplicate_captured_item_identity_rejected_without_clipboard(self):
        self.check(r'''
source.turns[0].items.push({...row.item});assert.equal(await artifact.onclick(),false);assert.equal(writes.length,0);assert(!artifact.disabled);
''')

if __name__ == '__main__':
    unittest.main()
