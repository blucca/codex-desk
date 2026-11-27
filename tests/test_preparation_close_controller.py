"""Prepared editor views are captured before native dialog geometry disappears."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

SOURCE = Path(os.environ.get('DESK_SOURCE', Path(__file__).resolve().parents[1])).resolve()
sys.path.insert(0, str(SOURCE / 'tests'))
from test_prepared_queue_editor import SETUP as QUEUE_SETUP, NODE

SETUP = QUEUE_SETUP.replace(
    "close(){this.open=false;this.dispatch('close');}",
    """close(){
      this.open=false;
      pendingClose.push(()=>this.dispatch('close'));
    }""")
SETUP += r'''
// Hidden native dialog textareas report zero without erasing their stored scroll.
Object.defineProperty(Element.prototype,'scrollTop',{
  get(){return !n('').open && this.tagName==='TEXTAREA'?0:(this._scrollTop??0);},
  set(value){this._scrollTop=value;}
});
const pendingClose=[];
const flushClose=()=>{while(pendingClose.length)pendingClose.shift()();};
const view=node=>({text:node.value,start:node.selectionStart,end:node.selectionEnd,
  direction:node.selectionDirection,scroll:node.scrollTop});
const position=(node,start,end,direction,scroll)=>{node.focus();node.setSelectionRange(start,end,direction);node.scrollTop=scroll;return view(node);};
const reopen=async()=>{await DeskPreparation.show();assert(n('').open);};
'''

@unittest.skipUnless(NODE, 'Node required')
class PreparationCloseControllerTests(unittest.TestCase):
    def check(self, body, opens=0):
        script = SETUP + '\n(async()=>{await DeskPreparation.show();\n' + body + r'''
assert.equal(saved.length,0);
assert.equal(calls.filter(c=>c.data).length,0);
assert.equal(queuePosts().length,0);
assert.equal(activeDraft.text,'ACTIVE UNSENT PLAN — do not alter');
assert.equal(opened.length,''' + str(opens) + r''');
console.log(JSON.stringify({passed:true,queued_close_events:pendingClose.length,explicit_saves:saved.length,open_callbacks:opened.length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''
        result = subprocess.run([NODE, '-e', script, str(SOURCE / 'codex_desk/static/preparation.js')],
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"passed":true', result.stdout)

    def test_button_close_event_after_hidden_geometry_keeps_latest_draft_view(self):
        self.check(r'''
await review('b');fill('Exact unsaved draft '.repeat(100),'plan');
const before=position(n('text'),310,345,'forward',195);
await n('close').click();assert.equal(n('text').scrollTop,0);assert.equal(pendingClose.length,1);
flushClose();await reopen();assert.deepEqual(view(n('text')),before);
assert.equal(world.b.draft.text,'');
''')

    def test_escape_cancel_captures_draft_range_direction_scroll_before_close(self):
        self.check(r'''
await review('b');fill('Exact unsaved Escape draft '.repeat(100),'plan');
const before=position(n('text'),410,455,'backward',280);
n('').dispatch('cancel');n('').close();assert.equal(n('text').scrollTop,0);
flushClose();await reopen();assert.deepEqual(view(n('text')),before);
assert.equal(world.b.draft.text,'');
''')

    def test_successful_open_captures_current_prepared_view_before_native_close(self):
        self.check(r'''
await review('b');fill('Locally kept when opening saved draft '.repeat(100),'plan');
const before=position(n('text'),530,580,'backward',355);
await n('open').click();assert.equal(n('text').scrollTop,0);flushClose();
await reopen();assert.deepEqual(view(n('text')),before);assert.deepEqual(opened,['b']);
assert.equal(world.b.draft.text,'');
''', opens=1)

    def test_delayed_old_close_event_does_not_touch_reopened_editor(self):
        self.check(r'''
await review('b');fill('Unsaved reopened draft '.repeat(100),'plan');
position(n('text'),310,345,'forward',195);await n('close').click();
await reopen();const newer=position(n('text'),630,680,'backward',455);
const callsBefore=calls.length;flushClose();assert.equal(calls.length,callsBefore);
assert.deepEqual(view(n('text')),newer);await n('refresh').click();assert.deepEqual(view(n('text')),newer);
await n('close').click();flushClose();await reopen();assert.deepEqual(view(n('text')),newer);
''')

    def test_button_close_keeps_independent_unsaved_queue_editor_view(self):
        self.queue_case(False)

    def test_escape_keeps_independent_unsaved_queue_editor_view(self):
        self.queue_case(True)

    def queue_case(self, escape):
        self.check(r'''
const savedQueue=clone(world.b.followups);await start();input('Exact unsaved queued instruction '.repeat(100),'plan');
const before=position(queueControl('b-one','queue-text'),110,155,'backward',185);
''' + ("n('').dispatch('cancel');n('').close();" if escape else "await n('close').click();") + r'''
assert.equal(queueControl('b-one','queue-text').scrollTop,0);flushClose();await reopen();
assert.deepEqual(view(queueControl('b-one','queue-text')),before);
assert.equal(queueControl('b-one','queue-mode').value,'plan');assert.deepEqual(world.b.followups,savedQueue);
''')


if __name__ == '__main__':
    unittest.main()
