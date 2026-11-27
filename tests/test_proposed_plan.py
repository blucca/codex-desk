"""Native proposed-plan projection and reuse, separate from task preparation."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from codex_desk.handoff import build_handoff, visible_text
from codex_desk.native_recall import NativeRecallIndex
from codex_desk.runtime import Store
from codex_desk import recall

SOURCE = Path(__file__).resolve().parents[1]
TEMP = Path(os.environ.get('DESK_TEST_TEMP', Path.cwd() / 'temp'))
TEMP.mkdir(parents=True, exist_ok=True)
NODE = shutil.which('node')
TEXT = '# Proposed plan — résumé 保留\n1. Inspect <script>literal</script>.\n2. Run parser unit tests.\n'
PLAN = {'id': 'plan-item', 'type': 'plan', 'text': TEXT}


class ProposedPlanReuseTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(dir=TEMP, prefix='proposed-plan-')
        self.addCleanup(self.folder.cleanup)
        self.path = Path(self.folder.name) / 'desk.sqlite3'
        self.store = Store(self.path)
        self.addCleanup(lambda: self.store.db.close())
        self.session = self.store.create(str(Path(self.folder.name)), 'default', name='Plan evidence')
        self.store.update(self.session, thread_id='parent', status='saved', thread_saved=1)

    def event(self, method, **params):
        self.store.event(self.session, {'method': method, 'params': {'threadId': 'parent', 'turnId': 'turn', **params}})

    def text(self):
        return self.store.db.execute('SELECT visible_text FROM recall_items WHERE session_id=? AND item_id=?',
            (self.session, PLAN['id'])).fetchone()[0]

    def test_handoff_contains_the_exact_full_native_plan(self):
        self.assertEqual(visible_text(PLAN), 'Proposed plan\n' + TEXT)
        thread = {'id': 'parent', 'turns': [{'id': 'turn', 'status': 'completed', 'items': [PLAN]}]}
        self.assertIn('Item plan-item\nProposed plan\n' + TEXT, build_handoff(thread))

    def test_live_plan_deltas_final_replacement_terminal_and_cold_recall(self):
        self.event('item/started', item={**PLAN, 'text': ''})
        self.event('item/plan/delta', itemId=PLAN['id'], delta='Provisional tokenizer')
        self.assertEqual(self.text(), 'Proposed plan\nProvisional tokenizer')
        self.event('item/completed', item=PLAN)
        self.assertEqual(self.text(), 'Proposed plan\n' + TEXT)
        self.event('item/plan/delta', itemId=PLAN['id'], delta='LATE MUST NOT APPEND')
        self.event('turn/completed', turn={'id': 'turn', 'status': 'completed', 'items': [PLAN]})
        before = recall.search(self.store, 'parser unit tests')
        self.assertEqual(before['total'], 1)
        self.assertEqual(before['results'][0]['item_id'], PLAN['id'])
        self.assertEqual(self.text(), 'Proposed plan\n' + TEXT)
        self.store.db.close(); self.store = Store(self.path)
        self.assertEqual(recall.search(self.store, 'parser unit tests'), before)

    def test_partial_plan_retains_only_reported_text_after_interruption(self):
        self.event('item/started', item={**PLAN, 'text': ''})
        self.event('item/plan/delta', itemId=PLAN['id'], delta='Partial inspection decision')
        self.event('turn/completed', turn={'id': 'turn', 'status': 'interrupted', 'items': []})
        self.event('item/plan/delta', itemId=PLAN['id'], delta='IGNORED')
        self.assertEqual(self.text(), 'Proposed plan\nPartial inspection decision')

    def test_native_original_index_retains_plan_type_full_text_and_ids(self):
        index = NativeRecallIndex(self.store)
        thread = {'id': 'unopened', 'cwd': str(Path(self.folder.name)), 'name': 'Original plan',
            'updatedAt': 1795700000, 'turns': [{'id': 'native-turn', 'status': 'completed', 'items': [PLAN]}]}
        index.replace_snapshot(thread)
        hit = index.search('parser unit tests')['results'][0]
        self.assertEqual((hit['thread_id'], hit['turn_id'], hit['item_id'], hit['item_type']),
            ('unopened', 'native-turn', 'plan-item', 'plan'))
        retained = self.store.db.execute('SELECT visible_text FROM native_recall_items WHERE thread_id=?', ('unopened',)).fetchone()[0]
        self.assertEqual(retained, 'Proposed plan\n' + TEXT)


HARNESS = r'''
const assert=require('assert');
const document={activeElement:null};
class Element {
  constructor(tag='div',text='',cls=''){this.tagName=tag.toUpperCase();this._text=text;this.className=cls;this.classList={add(){}};this.children=[];this.parentNode=null;this.dataset={};this.hidden=false;this.scrollTop=0;this.scrollLeft=0;this.attributes={};}
  get textContent(){return this._text+this.children.map(n=>n.textContent).join('');}
  set textContent(value){this._text=value;this.children=[];this.scrollTop=0;this.scrollLeft=0;}
  append(...nodes){for(const node of nodes){node.parentNode=this;this.children.push(node);}}
  replaceChildren(...nodes){this.children=[];this._text='';this.append(...nodes);}
  setAttribute(key,value){this.attributes[key]=value;}
  addEventListener(){}
  focus(){document.activeElement=this;}
}
document.createElement=tag=>new Element(tag);document.createTextNode=text=>new Element('text',text);
const elements=new Map(),$=id=>{if(!elements.has(id))elements.set(id,new Element());return elements.get(id);};
function make(tag,text='',cls=''){return new Element(tag,text,cls);}
const items=new Map(),nodes=new Map(),itemTurns=new Map(),requests=new Map(),collaborationTypes=new Set(['collabAgentToolCall','subAgentActivity']);
let selected='desk-plan',nativeThreadId='parent',currentTurn=null,generation=7;
const DeskNativeSteps={consume(){return false;}},DeskTurnChanges={consume(){return false;}},DeskSteering={consume(){}},DeskStopTask={consume(){}};
const DeskNativeState={card(){throw Error('unexpected error');}},DeskEvidence={};
function approvals(){throw Error('unexpected interaction');}
const scope={threadId:'parent',turnId:'turn'};
const start=id=>consume({method:'turn/started',params:{threadId:'parent',turn:{id,status:'inProgress',items:[]}}});
const item=(method,text='',extra={})=>consume({method,params:{...scope,item:{id:'plan-item',type:'plan',text},...extra}});
const delta=(text,extra={})=>consume({method:'item/plan/delta',params:{...scope,itemId:'plan-item',delta:text,...extra}});
const terminal=(status,entries=[])=>consume({method:'turn/completed',params:{threadId:'parent',turn:{id:'turn',status,items:entries}}});
const displayed=()=>nodes.get('plan-item').children[1].textContent;
const label=()=>nodes.get('plan-item').children[0].textContent;
'''


@unittest.skipUnless(NODE, 'Node required')
class ProposedPlanControllerTests(unittest.TestCase):
    def check(self, body):
        app = (SOURCE / 'codex_desk/static/app.js').read_text()
        source = HARNESS + '\n' + (SOURCE / 'codex_desk/static/activity.js').read_text()
        source += '\n' + app[app.index('function itemText(i) {'):app.index('function updateCollaboration(group) {')]
        source += app[app.index('function renderItem(i,turnId) {'):app.index('let approvalsSignature=')]
        source += app[app.index('function consume(m) {'):app.index('async function refresh() {')]
        source += '\n' + body
        result = subprocess.run([NODE, '-e', source], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_live_exact_literal_stream_final_replacement_and_reading_position(self):
        self.check(r'''
start('turn');item('item/started');assert(nodes.get('plan-item').hidden);
delta('# Plan 保留\n');delta('1. Inspect <script>literal</script>.\n');
assert.strictEqual(displayed(),'# Plan 保留\n1. Inspect <script>literal</script>.\n');
assert.strictEqual(label(),'Proposed plan · Streaming');
const node=nodes.get('plan-item'),reader=node.children[1];reader.scrollTop=41;reader.scrollLeft=7;reader.focus();
delta('2. Run tests.\n');assert.strictEqual(nodes.get('plan-item'),node);assert.strictEqual(node.children[1],reader);
assert.strictEqual(document.activeElement,reader);assert.strictEqual(reader.scrollTop,41);assert.strictEqual(reader.scrollLeft,7);
item('item/completed','# Revised final plan\nDifferent exact text.');
assert.strictEqual(displayed(),'# Revised final plan\nDifferent exact text.');
assert.strictEqual(label(),'Proposed plan · Final native item');delta('LATE');
assert.strictEqual(displayed(),'# Revised final plan\nDifferent exact text.');
''')

    def test_terminal_without_final_retains_partial_with_actual_outcome(self):
        self.check(r'''
for(const status of ['completed','interrupted','failed']) {
  items.clear();nodes.clear();itemTurns.clear();start('turn');item('item/started');delta('Partial actual proposal');terminal(status);
  assert.strictEqual(displayed(),'Partial actual proposal');assert.strictEqual(label(),'Partial proposed plan · Task '+status);
  delta('POST TERMINAL');assert.strictEqual(displayed(),'Partial actual proposal');
}
''')

    def test_native_terminal_final_items_are_authoritative(self):
        self.check(r'''
start('turn');item('item/started');delta('Provisional');terminal('completed',[{id:'plan-item',type:'plan',text:'Final terminal native item'}]);
assert.strictEqual(displayed(),'Final terminal native item');assert.strictEqual(label(),'Proposed plan · Final native item');
''')

    def test_parent_turn_item_and_selected_map_scope(self):
        self.check(r'''
start('turn');item('item/started');delta('Current parent proposal');
delta('CHILD',{threadId:'child'});delta('WRONG ITEM',{itemId:'other'});delta('WRONG TURN',{turnId:'older'});
assert.strictEqual(displayed(),'Current parent proposal');start('new-turn');delta('RETIRED');
assert.strictEqual(displayed(),'Current parent proposal');assert.strictEqual(label(),'Partial proposed plan · Earlier task');
items.clear();nodes.clear();itemTurns.clear();currentTurn=null;selected='other';nativeThreadId='other-parent';generation++;
delta('FOREIGN OLD OWNER');assert.strictEqual(nodes.size,0);
''')

    def test_original_reader_plan_text_is_exact_and_supported(self):
        reader = (SOURCE / 'codex_desk/static/history_reader.js').read_text()
        text_for = reader[reader.index('  function textFor(item) {'):reader.index('  function flatten(thread) {')]
        result = subprocess.run([NODE, '-e', "const str=v=>typeof v==='string'?v:'';" + text_for +
            "\nprocess.stdout.write(textFor(JSON.parse(process.argv[1])));", json.dumps(PLAN)], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, 'Proposed plan\n' + TEXT)


if __name__ == '__main__':
    unittest.main()
