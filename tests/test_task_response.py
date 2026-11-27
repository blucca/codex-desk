import copy,unittest
from codex_desk.task_response import select_task_response

def msg(i,phase=None,text='Supplied native response'):
 return {'id':i,'type':'agentMessage','text':text,'phase':phase}
def original(items,status='completed'):
 return {'id':'parent','turns':[{'id':'earlier','status':'completed','items':[msg('prior','final_answer')]},{'id':'captured','status':status,'items':items},{'id':'newer','status':'completed','items':[msg('next','final_answer')]}]}
class ResponseTests(unittest.TestCase):
 def read(self,thread):return select_task_response(thread,'parent','captured')
 def test_prefers_explicit_final_over_later_commentary(self):
  r=self.read(original([msg('a','final_answer'),msg('later','commentary')]))
  self.assertEqual(r['item_id'],'a');self.assertEqual(r['phase'],'final_answer');self.assertEqual(r['turn_status'],'completed')
 def test_last_supplied_final(self):self.assertEqual(self.read(original([msg('a','final_answer'),msg('b','final_answer')]))['item_id'],'b')
 def test_legacy_last_message_not_earlier_or_newer(self):
  r=self.read(original([msg('a'),msg('b')],'failed'));self.assertEqual(r['item_id'],'b');self.assertIsNone(r['phase']);self.assertEqual(r['turn_status'],'failed');self.assertEqual(r['selection'],'last_assistant_message')
 def test_commentary_retains_actual_phase(self):
  r=self.read(original([msg('a','commentary')],'inProgress'));self.assertEqual(r['label'],'Commentary');self.assertEqual(r['turn_status'],'inProgress')
 def test_partial_and_future_phase(self):
  for phase in ('partial_answer','future_phase'):
   self.assertEqual(self.read(original([msg('a',phase)]))['phase'],phase)
 def test_empty_turn_no_substitution(self):self.assertEqual(self.read(original([]))['status'],'response_unavailable')
 def test_absent_turn_no_substitution(self):self.assertEqual(self.read({'id':'parent','turns':original([])['turns'][::2]})['status'],'turn_unavailable')
 def test_tool_output_is_not_response(self):self.assertEqual(self.read(original([{'id':'tool','type':'commandExecution','aggregatedOutput':'assistant answer'}]))['status'],'response_unavailable')
 def test_unreadable_message_is_not_response(self):
  for item in (msg('', 'final_answer'),msg('x'*201,'final_answer'),msg('blank','final_answer','  '),{**msg('bad'),'text':None}):
   self.assertEqual(self.read(original([item]))['status'],'response_unavailable')
 def test_wrong_parent_rejected(self):
  with self.assertRaises(ValueError):self.read({'id':'child','turns':original([msg('answer')])['turns']})
 def test_invalid_capture_rejected(self):
  for value in ('',None,3,'x'*201):
   with self.assertRaises(ValueError):select_task_response(original([]),value,'captured')
 def test_duplicate_turn_rejected(self):
  t=original([msg('a')]);t['turns'].append(copy.deepcopy(t['turns'][1]))
  with self.assertRaises(ValueError):self.read(t)
 def test_duplicate_item_rejected(self):
  with self.assertRaises(ValueError):self.read(original([msg('a'),msg('a')]))
 def test_native_original_never_mutated(self):
  t=original([msg('a')]);before=copy.deepcopy(t);self.read(t);self.assertEqual(t,before)
 def test_boolean_availability_and_explicit_reason_keep_capture(self):
  for thread,reason in ((original([]),'response_unavailable'),({'id':'parent','turns':[]},'turn_unavailable')):
   r=self.read(thread);self.assertFalse(r['available']);self.assertEqual(r['reason'],reason)
   self.assertEqual((r['thread_id'],r['turn_id']),('parent','captured'));self.assertNotIn('item_id',r)
   self.assertEqual(r['source'],'native history read')
 def test_blank_assistant_item_id_is_unavailable(self):
  self.assertFalse(self.read(original([msg(' \t\n','final_answer')]))['available'])
 def test_phase_is_independent_of_failed_interrupted_and_active_outcome(self):
  for status in ('failed','interrupted','inProgress'):
   t=original([msg('a','final_answer')],status);t['turns'][1]['error']={'message':'Original native error','codexErrorInfo':'sandboxError'}
   r=self.read(t);self.assertTrue(r['available']);self.assertIsNone(r['reason']);self.assertEqual(r['turn_status'],status)
   self.assertEqual(r['turn_error'],t['turns'][1]['error']);self.assertEqual(r['phase'],'final_answer')
 def test_phase_omitted_is_fallback_not_final(self):
  item=msg('legacy');item.pop('phase');r=self.read(original([item]))
  self.assertEqual(r['selection'],'last_assistant_message');self.assertIsNone(r['phase'])
 def test_malformed_native_root_and_turn_collection_reject(self):
  for t in (None,[],{'id':'parent'},{'id':'parent','turns':{}},{'id':'parent','turns':None}):
   with self.assertRaises(ValueError):self.read(t)
if __name__=='__main__':unittest.main()
