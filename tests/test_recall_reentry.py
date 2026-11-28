"""Live result-place recovery; actual controller and existing grouped fixture."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

from test_recall_conversation_navigation import HARNESS as GROUP_HARNESS

NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
SOURCE = Path(__file__).resolve().parents[1] / 'codex_desk/static/recall.js'
PREFIX = GROUP_HARNESS.split('\n(async()=>{', 1)[0]
PREFIX = PREFIX.replace('focus(){document.activeElement=this;}', '''focus(){
 document.activeElement=this;
 for(let node=this;node;node=node.parentElement)
  for(const fn of node.listeners.get('focusin')||[])fn({target:this});
}''')
PREFIX = PREFIX.replace('showModal(){this.open=true;}', '''showModal(){
 this.open=true;this.scrollTop=0;
 const node=document.activeElement;
 if(el('recall-results').contains(node))node.focus();
}''')
PREFIX = PREFIX.replace('recall.configure({api,', "let currentOwner='B',ownerGeneration=0;\nrecall.configure({api,")
PREFIX = PREFIX.replace('selected:()=>null,generation:()=>0', 'selected:()=>currentOwner,generation:()=>ownerGeneration')
PREFIX += '\nglobal.requestAnimationFrame=fn=>setImmediate(fn);\n'
HARNESS = PREFIX + r'''
const place=()=>({focus:document.activeElement.id || [...document.activeElement.classes][0],
 item:document.activeElement.parentElement?.dataset.item || null,
 group:document.activeElement.parentElement?.dataset.group || null,
 scroll:el('recall').scrollTop,resultsScroll:el('recall-results').scrollTop,
 ...snapshot()});
const reopen=async()=>{for(const fn of el('recall').listeners.get('cancel')||[])fn();el('recall').close();el('home-content').onclick();await settle();return place();};
(async()=>{
 el('home-content').onclick();await settle();el('recall-query').value='Café 项目 😀';el('recall-query').oninput();await submit();
 el('recall-next').onclick();await settle();
 const picked=el('recall-results').children[12].querySelector('.recall-read');picked.focus();
 el('recall').scrollTop=3494;el('recall-results').scrollTop=42;
 const before=place(),n=requests.length;const ordinary=await reopen();const noNewSearch=requests.length===n;
 el('recall-grouped').checked=true;el('recall-grouped').onchange();await submit();
 el('recall').scrollTop=93;el('recall-results').scrollTop=17;
 const group=el('recall-results').children[0].querySelector('.recall-group');group.focus();await group.onclick();
 el('recall-next').onclick();await settle();
 const read=el('recall-results').children[12].querySelector('.recall-read');read.focus();read.onclick();
 el('history-reader').open=false;readerReturn();el('recall').scrollTop=4556;el('recall-results').scrollTop=41;
 const sourceBefore=place(),source=await reopen();
 el('recall-source-back').onclick();await settle();const groupBefore=place(),grouped=await reopen();
 el('recall-query').value='new literal';el('recall-query').oninput();const edited=await reopen();
 el('recall-grouped').checked=false;el('recall-grouped').onchange();await submit();el('recall-results').children[0].querySelector('.recall-read').focus();
 await submit();const replaced=await reopen();
 el('recall-results').children[0].querySelector('.recall-read').focus();
 el('recall').close();currentOwner='C';ownerGeneration++;recall.selectionChanged();
 el('home-content').onclick();await settle();const owner=place();
 const frames=[];global.requestAnimationFrame=fn=>frames.push(fn);
 const row=el('recall-results').children[0].querySelector('.recall-read');row.focus();el('recall').scrollTop=1500;
 for(const fn of el('recall').listeners.get('cancel')||[])fn();el('recall').close();el('home-content').onclick();
 el('recall-query').value='interrupted query';el('recall-query').oninput();el('recall-query').focus();el('recall').scrollTop=7;
 for(const fn of frames)fn();const interrupted=place();
 process.stdout.write(JSON.stringify({before,ordinary,noNewSearch,sourceBefore,source,groupBefore,grouped,edited,replaced,owner,interrupted,reads}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
'''


@unittest.skipUnless(NODE, 'Node required for actual controller units')
class RecallReentryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = subprocess.run([NODE, '-e', HARNESS, str(SOURCE)], capture_output=True,
                           text=True, check=True, timeout=10)
        cls.s = json.loads(p.stdout)

    def test_ordinary_result_page_and_exact_picked_action_scroll_recover(self):
        self.assertEqual(self.s['ordinary'], self.s['before'])
        self.assertEqual(self.s['ordinary']['item'], 'item-42')
        self.assertTrue(self.s['noNewSearch'])

    def test_group_source_item_page_read_return_and_reentry_are_exact(self):
        self.assertEqual(self.s['source'], self.s['sourceBefore'])
        self.assertEqual(self.s['source']['item'], 'item-42')
        self.assertEqual(self.s['reads'], ['item-42'])

    def test_back_to_conversation_group_keeps_group_focus_and_scroll_on_reentry(self):
        self.assertEqual(self.s['grouped'], self.s['groupBefore'])
        self.assertEqual(self.s['grouped']['group'], 'A')
        self.assertEqual(self.s['grouped']['scroll'], 93)

    def test_changed_literal_does_not_restore_removed_row(self):
        self.assertEqual(self.s['edited']['focus'], 'recall-query')
        self.assertEqual(self.s['edited']['rows'], 0)
        self.assertEqual(self.s['edited']['query'], 'new literal')

    def test_fresh_replaced_results_do_not_reuse_disconnected_picked_action(self):
        self.assertEqual(self.s['replaced']['focus'], 'recall-query')
        self.assertIsNone(self.s['replaced']['item'])

    def test_new_owner_preserves_query_but_not_old_owner_result_focus(self):
        self.assertEqual(self.s['owner']['focus'], 'recall-query')
        self.assertEqual(self.s['owner']['query'], 'new literal')
        self.assertIsNone(self.s['owner']['group'])

    def test_delayed_modal_layout_restore_never_moves_a_new_query_or_focus(self):
        self.assertEqual(self.s['interrupted']['focus'], 'recall-query')
        self.assertEqual(self.s['interrupted']['query'], 'interrupted query')
        self.assertEqual(self.s['interrupted']['scroll'], 7)


if __name__ == '__main__':
    unittest.main()
