"""Independent source-handler review of original Refresh identity and Find intent."""
import shutil
import unittest

import test_history_reader_refresh as refresh_tests

SOURCE=refresh_tests.SOURCE
CONFIGURE=SOURCE[SOURCE.index('  function configure('):SOURCE.index('  root.DeskHistoryReader=')]
MANUAL=SOURCE[SOURCE.index('  function manualFindNavigation('):SOURCE.index('  function findMatch(')]
ITEM=SOURCE[SOURCE.index('  function itemNode('):SOURCE.index('  function render(')]
BOUNDS=SOURCE[SOURCE.index('  function bounds('):SOURCE.index('  function findControls(')]
HANDLERS=r'''
el('').addEventListener=()=>{};
function close(){}function read(){}function movePage(){}function submitFind(){}function jumpFind(){}function invalidate(){}
'''+CONFIGURE+"\nconfigure({api});\n"


@unittest.skipUnless(shutil.which('node'),'Node is required for independent Refresh review')
class ReaderRefreshReviewTests(unittest.TestCase):
    run_js=refresh_tests.ReaderRefreshTests.run_js

    def test_edited_then_restored_query_is_unsent_until_explicit_find(self):
        self.run_js(HANDLERS+"""
findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';
findGroups=[{index:0,spans:root.DeskHistoryFind.spans(rows[0].item.text,'evidence'),first:0}];findTotal=1;findCursor=0;
response=thread([['old','exact old evidence'],['new','new evidence']]);const pending=refresh();
el('find-query').value='different unsent query';el('find-query').oninput();
el('find-query').value='evidence';el('find-query').oninput();
release();assert(await pending);assert.equal(el('find-query').value,'evidence');
assert.equal(findTotal,0,'Editing the query starts a new unsent intent, even when its text returns to the old query');
assert.equal(findCursor,-1);assert(!finding);assert.equal(apiCalls.length,1);
""")

    def test_find_canceled_by_navigation_does_not_restart_on_refresh(self):
        self.run_js(MANUAL+"""
findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';finding=true;
manualFindNavigation();assert(!finding);assert(findMessages.at(-1).includes('canceled'));
response=thread([['old','exact old evidence']]);const pending=refresh();release();assert(await pending);
assert.equal(findTotal,0,'A navigation-canceled Find stays canceled until explicit Find, not Refresh');
assert(!finding);assert.equal(apiCalls.length,1);
""")

    def test_unreported_native_item_id_cannot_establish_retained_occurrence(self):
        self.run_js("""
delete rows[0].item.id;view.first=null;
findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';
findGroups=[{index:0,spans:root.DeskHistoryFind.spans(rows[0].item.text,'evidence'),first:0}];findTotal=1;findCursor=0;
response=thread([['different','other new evidence']]);delete response.turns[0].items[0].id;
const pending=refresh();release();assert(await pending);assert.equal(findTotal,1);
assert.equal(findCursor,-1,'Matching null identities and offsets cannot prove the same original native item');
assert.equal(apiCalls.length,1);
""")

    def test_wrong_native_thread_reply_preserves_original_snapshot_and_find(self):
        self.run_js("""
findQuery='evidence';findSubmitted=true;el('find-query').value='evidence';
findGroups=[{index:0,spans:root.DeskHistoryFind.spans(rows[0].item.text,'evidence'),first:0}];findTotal=1;findCursor=0;
const old=source,oldRows=rows,oldGroups=findGroups;response=thread([['new','wrong-thread evidence']]);response.id='other-original';
const pending=refresh();release();assert.equal(await pending,false);
assert.strictEqual(source,old);assert.strictEqual(rows,oldRows);assert.strictEqual(findGroups,oldGroups);
assert.equal(findTotal,1);assert.equal(findCursor,0);assert.equal(el('find-query').value,'evidence');
assert(!el('error').hidden);assert(el('error').textContent.includes('did not return this conversation'));
assert.equal(renders.length,0);assert.equal(apiCalls.length,1);assert(!refreshing);
""")

    def test_query_edit_during_held_refresh_preserves_readable_item_window(self):
        nodes=r'''
const TEXT_CHARS=20000,labels={commandExecution:'Command'};
function node(tag,text,cls){return {tag,textContent:text||'',className:cls||'',dataset:{},children:[],scrollTop:0,
  classList:{add(){}},append(...children){this.children.push(...children);},
  querySelector(selector){for(const child of this.children){if(selector==='.'+child.className)return child;const found=child.querySelector(selector);if(found)return found;}return null;}};}
function markText(container,value){container.textContent=value;}function copyControls(){}
rows[0].item={id:'old',type:'commandExecution',text:'x'.repeat(65000)};
'''
        self.run_js(nodes+BOUNDS+ITEM+HANDLERS+"""
let detail=itemNode(rows[0],0,version);
detail.open=true;detail.querySelector('.history-reader-text-controls').children[1].onclick();
detail.querySelector('.history-reader-text-controls').children[1].onclick();
assert.equal(Number(detail.dataset.windowStart),40000);detail.querySelector('.history-reader-text').scrollTop=72;
captureView=()=>({items:new Map([[rowKey(rows[0]),{start:Number(detail.dataset.windowStart),open:detail.open,scroll:detail.querySelector('.history-reader-text').scrollTop}]]),anchor:null,first:rowKey(rows[0]),page:0,scroll:17});
render=(scroll,snapshot)=>{detail=itemNode(rows[0],0,version,snapshot);};
response=thread([['old','x'.repeat(65000)]]);const pending=refresh();
el('find-query').value='a new unsent query';el('find-query').oninput();
assert.equal(Number(detail.dataset.windowStart),40000,'Typing in Find must not replace the readable tool window during held Refresh');
assert(detail.open);assert.equal(detail.querySelector('.history-reader-text').scrollTop,72);
release();assert(await pending);assert.equal(Number(detail.dataset.windowStart),40000);
assert.equal(el('find-query').value,'a new unsent query');assert.equal(apiCalls.length,1);
""")


if __name__=='__main__':unittest.main()
