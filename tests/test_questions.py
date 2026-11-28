import threading
import unittest
from codex_desk.runtime import Runtime

class QuestionsTests(unittest.TestCase):
    def runtime(self):
        runtime = object.__new__(Runtime)
        runtime.id = 'workspace'
        runtime.lifecycle_lock = threading.Lock()
        runtime.approvals = {'9': {'id': 9, 'method': 'item/tool/requestUserInput', 'params': {
            'questions': [{'id':'mode','header':'Mode','question':'Which mode?', 'options': [
                {'label':'Safe','description':'Read only'}, {'label':'Edit','description':'Make changes'}]},
                {'id':'note','header':'Note','question':'Anything else?', 'isSecret':True}]}}}
        runtime.sent=[]
        runtime.send=runtime.sent.append
        class Store:
            def update(self,*args,**kwargs): pass
        runtime.store=Store()
        return runtime

    def test_native_question_shape_and_stale_response(self):
        runtime=self.runtime()
        self.assertEqual(runtime.answer('9', {'mode':['Safe'],'note':['private-fixture']}), {'answered':True})
        self.assertEqual(runtime.sent, [{'id':9, 'result': {'answers': {
            'mode':{'answers':['Safe']}, 'note':{'answers':['private-fixture']}}}}])
        self.assertEqual(runtime.approvals,{})
        with self.assertRaises(ValueError):runtime.answer('9',{'mode':['Safe']})

    def test_incomplete_and_invalid_choice_keeps_pending(self):
        runtime=self.runtime()
        for value in ({'mode':['Unknown'],'note':['note']},):
            with self.assertRaises(ValueError):runtime.answer('9',value)
        self.assertIn('9',runtime.approvals)
        self.assertEqual(runtime.sent,[])
