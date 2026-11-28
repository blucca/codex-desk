"""Exact original-character availability is independent of viewport clipping."""
from pathlib import Path
import shutil
import subprocess
import unittest

import test_original_visible_character as glyph_tests

ROOT=Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/history_reader.js').read_text()
RESTORE=SOURCE[SOURCE.index('  function restoreView('):SOURCE.index('  function refreshControls(')]
HARNESS=glyph_tests.HARNESS.replace("const el=id=>id==='body'?body:reader;", "const status={textContent:'Original refreshed.'};const el=id=>id==='body'?body:id==='status'?status:reader;")+r'''
let readingUnavailable=false,readingCharacterNotice=null,readingIntentEpoch=0;
const key=JSON.stringify(['turn','item']);let live=true;
const current=ticket=>live&&ticket===7;
let visibleItems=[item];const viewItems=()=>visibleItems,elementKey=()=>key,restoreSelectedText=()=>{};
const view=saved=>({items:new Map([[key,{start:50000,scroll:700,open:true,...saved}]]),scroll:0});
'''

@unittest.skipUnless(shutil.which('node'),'Node is required for original-character notice units')
class OriginalCharacterNoticeTests(unittest.TestCase):
    def check(self,body):
        p=subprocess.run(['node','-e',HARNESS+glyph_tests.POINT+glyph_tests.VISIBLE+RESTORE+body],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_valid_glyph_offscreen_is_pending_geometry_without_missing_notice(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre),before=pre.scrollTop;
preTop=500;
assert.equal(restoreVisibleCharacter(item,{start:50000,character:saved}),null);
assert.equal(pre.scrollTop,before,'Offscreen neighbour does not steal the requested viewport');
restoreView(view({character:saved}),7);
assert.equal(status.textContent,'Original refreshed.');assert.equal(readingCharacterNotice,null);assert(!readingUnavailable);
preTop=30;restoreView(view({character:saved}),7);
const rect=characterRect(pre,text,saved.offset-50000),clip=visibleTextClip(pre);
assert.equal(rect.top-clip.top,saved.top);
''')

    def test_invalid_source_offset_still_reports_unavailable_when_offscreen(self):
        self.check(r'''
preTop=500;
for(const offset of [49999,50000+text.length,50000+text.indexOf('😀')+1,50000+text.indexOf('\n')]){
 readingCharacterNotice=null;status.textContent='Original refreshed.';
 restoreView(view({character:{offset,top:0}}),7);
 assert.equal(status.textContent,'Previous original character unavailable in this fresh text window.');
 assert.deepEqual(readingCharacterNotice.previous,'Original refreshed.');assert(!readingUnavailable);
}
''')

    def test_genuine_window_or_disclosure_loss_reports_unavailable(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre);
restoreView(view({start:49999,character:saved}),7);
assert(status.textContent.includes('Previous original character unavailable'));
item.open=false;restoreView(view({character:saved}),7);
assert(status.textContent.includes('Previous original character unavailable'));
''')

    def test_exact_target_success_clears_only_owned_notice(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre),target=view({start:49999,character:saved});
restoreView(target,7);assert(readingCharacterNotice);assert(!readingUnavailable);
item.dataset.windowStart='49999';restoreView(target,7);
assert.equal(status.textContent,'Original refreshed.');assert.equal(readingCharacterNotice,null);
item.dataset.windowStart='50000';restoreView(target,7);
status.textContent='Original refreshed. Selected original text changed.';
item.dataset.windowStart='49999';restoreView(target,7);
assert.equal(status.textContent,'Original refreshed. Selected original text changed.');assert.equal(readingCharacterNotice,null);
''')

    def test_source_catalog_failure_is_not_cleared_by_glyph_success(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre),target=view({start:49999,character:saved});
readingUnavailable=true;status.textContent='Previous original reading place unavailable in this fresh native read.';
restoreView(target,7);assert(readingCharacterNotice);
item.dataset.windowStart='49999';restoreView(target,7);
assert(readingUnavailable);assert(status.textContent.includes('reading place unavailable'));assert.equal(readingCharacterNotice,null);
''')

    def test_recaptured_surviving_glyph_does_not_clear_missing_exact_target(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre),target=view({character:{...saved,offset:50000+text.length}});
restoreView(target,7);assert(readingCharacterNotice);
restoreView(view({character:saved}),7);
assert(status.textContent.includes('character unavailable'));assert(readingCharacterNotice.failures.has(key));
restoreView(view({}),7);assert(status.textContent.includes('character unavailable'));
status.textContent='Newer original selection message.';restoreView(view({character:saved}),7);
assert(readingCharacterNotice);assert.equal(readingCharacterNotice.previous,'Newer original selection message.');
++readingIntentEpoch;restoreView(view({character:saved}),7);
assert.equal(readingCharacterNotice,null);assert.equal(status.textContent,'Newer original selection message.');
''')

    def test_disappeared_item_keeps_target_notice_until_new_reading_intent(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre);
restoreView(view({character:{...saved,offset:50000+text.length}}),7);
visibleItems=[];restoreView({items:new Map(),scroll:0},7);
assert(status.textContent.includes('character unavailable'));assert(readingCharacterNotice);
++readingIntentEpoch;restoreView({items:new Map(),scroll:0},7);
assert.equal(status.textContent,'Original refreshed.');assert.equal(readingCharacterNotice,null);
''')

    def test_closed_or_newer_reader_cannot_set_or_clear_notice(self):
        self.check(r'''
const saved=captureVisibleCharacter(item,pre),invalid=view({character:{...saved,offset:50000+text.length}});
live=false;restoreView(invalid,7);assert.equal(status.textContent,'Original refreshed.');assert.equal(readingCharacterNotice,null);
live=true;restoreView(invalid,7);const owned=readingCharacterNotice;assert(owned);
restoreView(view({character:saved}),8);assert.strictEqual(readingCharacterNotice,owned);assert(status.textContent.includes('character unavailable'));
''')

if __name__=='__main__':unittest.main()
