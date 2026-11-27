"""State polling reads the fixed native-turn index instead of command bodies."""
import json
import unittest
import test_native_outcome as fixture

class NativeOutcomeIndexTests(unittest.TestCase):
 setUp=fixture.NativeOutcomeTests.setUp
 snapshot=fixture.NativeOutcomeTests.snapshot
 state=fixture.NativeOutcomeTests.state
 preparation=fixture.NativeOutcomeTests.preparation
 def test_actual_state_query_uses_partial_index_and_keeps_read_only_native_evidence(self):
  self.runtime.attach()
  output='Retained command/tool result text.\n'*600
  with self.desk.store.lock,self.desk.store.db:
   self.desk.store.db.executemany('INSERT INTO events(session_id,payload) VALUES(?,?)',((self.id,json.dumps({'method':'item/completed','params':{'threadId':'native-parent','turnId':'failed-turn','item':{'id':str(i),'type':'commandExecution','command':'fixture check','status':'completed','aggregatedOutput':output}}})) for i in range(200)))
  statements=[];self.desk.store.db.set_trace_callback(statements.append)
  before=self.desk.store.db.total_changes;state=self.state();self.desk.store.db.set_trace_callback(None)
  sql=next(s for s in statements if s.lstrip().startswith('SELECT session_id,') and 'FROM events WHERE' in s)
  plan=self.desk.store.db.execute('EXPLAIN QUERY PLAN '+sql).fetchall()
  self.assertTrue(any('USING INDEX native_outcome_events' in row[3] for row in plan),plan)
  self.assertFalse(any(row[3]=='SCAN events' for row in plan),plan)
  self.assertFalse(any('TEMP B-TREE' in row[3] for row in plan),plan)
  self.assertEqual(self.desk.store.db.total_changes,before)
  self.assertEqual(state['native_outcomes'][self.id]['turn_id'],'failed-turn')
  self.assertEqual(state['native_outcomes'][self.id]['error']['message'],'parser test failed')

if __name__=='__main__':unittest.main()
