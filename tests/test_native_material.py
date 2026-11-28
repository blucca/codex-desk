"""Actual state metadata agrees with the parent-native review producer."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
from unittest.mock import patch

import test_native_outcome as fixture
from codex_desk.native_material import summaries
from codex_desk.server import Desk

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = Path(os.environ.get('DESK_TEST_NEW_ACTIVITY', ROOT / 'codex_desk/static/new-activity.js'))
APP = Path(os.environ.get('DESK_TEST_NEW_ACTIVITY_APP', REFERENCE.parent / 'app.js'))
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')


class NativeMaterialTests(unittest.TestCase):
    setUp = fixture.NativeOutcomeTests.setUp
    state = fixture.NativeOutcomeTests.state
    preparation = fixture.NativeOutcomeTests.preparation
    snapshot = fixture.NativeOutcomeTests.snapshot

    def emit(self, method, **params):
        self.desk.store.event(self.id, {'method': method, 'params': {'threadId': 'native-parent', **params}})
        return self.desk.store.events(self.id)[-1]['seq']

    def compact(self, desk=None):
        return self.state(desk)['native_material']['summaries'][0]

    def start(self, turn='turn-A'):
        return self.emit('turn/started', turn={'id': turn, 'status': 'inProgress'})

    def item(self, kind, item_id='item-A', turn='turn-A', method='item/completed', **fields):
        return self.emit(method, turnId=turn, item={'id': item_id, 'type': kind, **fields})

    def test_material_is_parent_readable_items_and_nonempty_deltas_only(self):
        self.start()
        frontier = self.item('agentMessage', text='Exact parent response')
        self.emit('turn/diff/updated', turnId='turn-A', diff='native aggregate is not an item')
        self.item('agentMessage', text=' \u00a0\ufeff ')
        self.item('userMessage', content=[{'type': 'image', 'url': 'synthetic'}])
        self.item('plan', text='')
        self.item('futureUnknown', text='Not a native material type')
        self.desk.store.event(self.id, {'id': 50, 'method': 'item/completed', 'params': {'threadId': 'native-parent', 'turnId': 'turn-A', 'item': {'id': 'request', 'type': 'commandExecution'}}})
        self.emit('item/commandExecution/outputDelta', turnId='turn-A', itemId='command', delta='')
        self.desk.store.event(self.id, {'method': 'item/completed', 'params': {'threadId': 'native-child', 'turnId': 'child-turn', 'item': {'id': 'child-command', 'type': 'commandExecution'}}})
        self.emit('turn/completed', turn={'id': 'turn-A', 'status': 'completed'})
        compact = self.compact()
        self.assertEqual(compact['material_seq'], frontier)
        self.assertGreater(compact['received_seq'], frontier)
        frontier = self.emit('item/commandExecution/outputDelta', turnId='turn-A', itemId='command', delta=' ')
        self.assertEqual(self.compact()['material_seq'], frontier)

    def test_empty_streaming_plan_delta_requires_original_same_current_turn(self):
        self.start()
        self.item('plan', 'plan-A', method='item/started', text='')
        first = self.emit('item/plan/delta', turnId='turn-A', itemId='plan-A', delta='Now readable')
        self.assertEqual(self.compact()['material_seq'], first)
        self.start('turn-B')
        self.emit('item/plan/delta', turnId='turn-A', itemId='plan-A', delta='Late retired plan')
        self.emit('item/plan/delta', turnId='turn-B', itemId='unknown-plan', delta='No original item')
        self.assertEqual(self.compact()['material_seq'], first)
        self.item('plan', 'plan-B', 'turn-B', method='item/started', text='')
        second = self.emit('item/plan/delta', turnId='turn-B', itemId='plan-B', delta='Second valid plan')
        self.emit('turn/completed', turn={'id': 'turn-B', 'status': 'completed', 'items': []})
        self.emit('item/plan/delta', turnId='turn-B', itemId='plan-B', delta='Dropped after terminal')
        self.assertEqual(self.compact()['material_seq'], second)

    def test_original_item_completion_and_terminal_final_plan_retire_deltas(self):
        self.start()
        self.item('plan', 'plan-A', method='item/started', text='')
        completed = self.item('plan', 'plan-A', text='Final native plan')
        self.emit('item/plan/delta', turnId='turn-A', itemId='plan-A', delta='Late delta')
        self.assertEqual(self.compact()['material_seq'], completed)
        self.item('plan', 'other-plan', method='item/started', text='')
        self.emit('turn/completed', turn={'id': 'turn-A', 'status': 'completed', 'items': [{'id': 'other-plan', 'type': 'plan', 'text': 'Final plan from turn'}]})
        self.emit('item/plan/delta', turnId='turn-A', itemId='other-plan', delta='Late final delta')
        self.assertEqual(self.compact()['material_seq'], completed)

    def test_exact_binding_new_home_and_unbound_rows_do_not_borrow_material(self):
        frontier = self.item('commandExecution', command='synthetic verify')
        self.assertEqual(self.compact()['material_seq'], frontier)
        self.desk.store.update(self.id, thread_id='replacement-parent')
        compact = self.compact()
        self.assertEqual(compact['material_seq'], 0)
        self.assertEqual(compact['owner']['thread_id'], 'replacement-parent')
        self.assertEqual(compact['received_seq'], frontier)
        self.desk.store.update(self.id, thread_id=None)
        self.assertEqual(self.state()['native_material']['summaries'], [])
        self.desk.store.update(self.id, thread_id='native-parent')
        other_home = self.root / 'other-home'; other_home.mkdir()
        cold = Desk('never-executed', other_home, self.root / 'state')
        try:
            self.assertNotEqual(self.compact(cold)['owner']['native_home'], self.compact()['owner']['native_home'])
        finally:
            cold.close(); cold.store.db.close()

    def test_actual_state_and_cold_are_read_only_with_draft_queue_outcome_unchanged(self):
        self.runtime.attach(); self.start(); self.item('fileChange', changes=[{'path': 'synthetic.py'}])
        preparation = self.preparation();before = self.state();events = self.desk.store.events(self.id)
        tables = self.desk.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
        self.calls.clear();changes = self.desk.store.db.total_changes
        with patch.object(self.desk, 'catalog', side_effect=AssertionError('No native reads')):
            for _ in range(3):
                self.assertEqual(self.state(), before)
        self.assertEqual(changes, self.desk.store.db.total_changes)
        self.assertEqual(preparation, self.preparation()); self.assertEqual(events, self.desk.store.events(self.id)); self.assertEqual(self.calls, [])
        cold = Desk('never-executed', self.home, self.root / 'state')
        try:
            with patch.object(cold, 'catalog', side_effect=AssertionError('No native reads')):
                self.assertEqual(self.state(cold)['native_material'], before['native_material'])
            self.assertEqual(cold.runtimes, {})
            self.assertEqual(cold.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(), tables)
        finally:
            cold.close(); cold.store.db.close()

    def test_sql_uses_material_index_and_only_compact_flags_ids_reach_python(self):
        secret = 'Source body /home/private and private unsent content.\n' * 1000
        self.start(); frontier = self.item('commandExecution', command='synthetic verify', aggregatedOutput=secret)
        self.item('agentMessage', 'empty-answer', text='')
        queries=[];self.desk.store.db.set_trace_callback(queries.append)
        compact = self.compact();self.desk.store.db.set_trace_callback(None)
        sql = next(sql for sql in queries if sql.lstrip().startswith('SELECT seq,session_id,'))
        plan = self.desk.store.db.execute('EXPLAIN QUERY PLAN ' + sql).fetchall()
        self.assertTrue(any('SEARCH events USING INDEX native_material_events (session_id=?)' in row[3] for row in plan), plan)
        self.assertFalse(any(row[3] == 'SCAN events' for row in plan), plan)
        self.assertNotIn(secret[:50], json.dumps(compact));self.assertEqual(compact['material_seq'], frontier)
        self.assertNotIn('aggregatedOutput', sql);self.assertNotIn('$.params.item.command', sql)

    def test_malformed_nonmaterial_fields_cannot_break_compact_state(self):
        self.start();frontier=self.item('userMessage', content=[{'type': 'text', 'text': '\ufeffExact native context'}])
        self.item('userMessage', 'broken-content', content=['not an object', 5, None, {'type': 'text', 'text': 7}])
        self.item('plan', 'broken-plan', text={'body': 'Not native text'})
        self.emit('turn/completed', turn={'id': 'turn-A', 'items': [None, 'not an object', {'id': 'plan', 'type': 'plan'}]})
        with self.desk.store.lock,self.desk.store.db:
            self.desk.store.db.execute('INSERT INTO events(session_id,payload) VALUES(?,?)', (self.id,'not JSON'))
        self.assertEqual(self.compact()['material_seq'],frontier)

    def test_opaque_identifiers_match_codepoint_limit_and_malformed_values_are_rejected(self):
        self.start()
        frontier=self.item('commandExecution','🧭'*200)
        self.item('commandExecution','🧭'*201)
        self.item('commandExecution',' \ufeff ')
        self.item('commandExecution',{'unexpected':'object ID'})
        self.emit('item/agentMessage/delta',turnId={'unexpected':'object turn'},itemId='answer',delta='Not a valid turn')
        self.emit('item/completed',turnId='turn-A',itemId=None,item={'id':'mismatch','type':'commandExecution'})
        self.assertEqual(self.compact()['material_seq'],frontier)

    @unittest.skipUnless(NODE, 'Node is needed for exact producer parity')
    def test_compact_frontier_matches_actual_next1_consumer_admission_order(self):
        self.assertTrue(REFERENCE.is_file(), 'Set DESK_TEST_NEW_ACTIVITY to accepted next1 source')
        self.start();self.item('plan', 'plan-A', method='item/started', text='')
        self.emit('item/plan/delta', turnId='turn-A', itemId='plan-A', delta='First plan')
        self.item('commandExecution', 'command', command='synthetic verify')
        self.emit('item/commandExecution/outputDelta',turnId='turn-A',itemId='command',delta='Output')
        self.item('agentMessage','answer',text='Exact native answer')
        self.start('turn-B');self.emit('item/plan/delta',turnId='turn-A',itemId='plan-A',delta='Dropped old plan')
        self.item('plan','plan-B','turn-B',method='item/started',text='')
        self.emit('item/plan/delta',turnId='turn-B',itemId='plan-B',delta='Second plan')
        self.emit('turn/completed',turn={'id':'turn-B','status':'completed','items':[]})
        self.emit('item/plan/delta',turnId='turn-B',itemId='plan-B',delta='Dropped terminal plan')
        self.emit('item/agentMessage/delta',turnId='turn-B',itemId='answer-B',delta='Later response')
        self.emit('turn/completed',turn={'id':'turn-B','status':'completed','items':[]})
        app=APP.read_text();consume=app[app.index('function consume(m) {'):app.index('\nasync function refresh()',app.index('function consume(m) {'))]
        script=r'''
const N=require(process.argv[1]),fs=require('fs'),rows=JSON.parse(fs.readFileSync(0,'utf8'));
const nativeThreadId='native-parent',selected='saved-A',generation=1,items=new Map(),itemTurns=new Map(),requests=new Map(),accepted=new WeakSet();let currentTurn=null;
const DeskSteering={consume:()=>false},DeskStopTask={consume:()=>false},DeskNativeSteps={consume:()=>false},DeskTurnChanges={consume:()=>false};
const DeskNewActivityView={accept:event=>{const p=event.params || {},item=items.get(p.itemId);if(event.method!=='item/plan/delta' || (item?.type==='plan' && item._deskPlan==='streaming' && p.turnId===currentTurn && itemTurns.get(p.itemId)===p.turnId))accepted.add(event);}};
const approvals=()=>{};const renderItem=(item,turn)=>{if(item?.id){items.set(item.id,item);itemTurns.set(item.id,turn);}};
globalThis.DeskNewActivityView=DeskNewActivityView;
''' + consume + r'''
for(const row of rows)consume(row.event);
const batch=N.capture({native_home:'a'.repeat(64),session:selected,thread_id:nativeThreadId},rows,row=>accepted.has(row.event));
process.stdout.write(JSON.stringify({frontier:batch.frontier,received_seq:batch.received_seq}));
'''
        result=subprocess.run([NODE,'-e',script,str(REFERENCE)],input=json.dumps(self.desk.store.events(self.id)),capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr);batch=json.loads(result.stdout);compact=self.compact()
        self.assertEqual((compact['material_seq'],compact['received_seq']),(batch['frontier'],batch['received_seq']))


if __name__ == '__main__':
    unittest.main()
