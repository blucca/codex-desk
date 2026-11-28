"""Independent native outcome survives readiness reset and cold read-only state."""
import copy
from email.message import Message
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock,patch

from codex_desk.runtime import Runtime
from codex_desk.server import Desk,handler
from codex_desk.native_outcome import outcomes
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot

ROOT=Path(os.environ.get('DESK_TEST_TEMP',Path.cwd()/'temp')).resolve()
ROOT.mkdir(parents=True,exist_ok=True)

class NativeOutcomeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(dir=ROOT);self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name);self.home=self.root/'home';self.home.mkdir()
  self.guard=patch('codex_desk.server.Runtime',side_effect=AssertionError('Native process forbidden'));self.guard.start();self.addCleanup(self.guard.stop)
  self.desk=Desk('never-executed',self.home,self.root/'state');self.addCleanup(lambda:self.desk.store.db.close());self.addCleanup(self.desk.close)
  self.id=self.desk.store.create(str(self.root),'default',name='Failed saved task');self.desk.store.update(self.id,thread_id='native-parent',thread_saved=1,name_pending=0,status='failed',error='Prior failure',mode='plan')
  save_draft(self.desk.store,self.id,'Unsent retry preparation','plan',0);add_followup(self.desk.store,self.id,'Check error evidence only','native');add_followup(self.desk.store,self.id,'Review the patch','plan')
  self.calls=[];self.thread=self.snapshot('failed-turn','failed',{'message':'parser test failed','codexErrorInfo':'sandboxError'})
  self.runtime=object.__new__(Runtime);self.runtime.store,self.runtime.id,self.runtime.home=self.desk.store,self.id,self.home;self.runtime.approvals={};self.runtime.closing=False;self.runtime._flush_name=lambda:None
  def request(method,params):
   self.calls.append((method,params));self.assertEqual(method,'thread/resume');return {'thread':copy.deepcopy(self.thread),'model':'fixture','modelProvider':'fixture'}
  self.runtime.request=request
 def snapshot(self,id,status,error=None):return {'id':'native-parent','cwd':str(self.root),'turns':[{'id':id,'status':status,'error':error,'items':[]}]}
 def state(self,desk=None):
  h=object.__new__(handler(desk or self.desk));h.path='/api/state';h.server=Mock(server_port=18787);h.headers=Message();h.headers['Host']='127.0.0.1:18787';out=[];h.reply=lambda value,status=200:out.append((status,value));h.do_GET();self.assertEqual(out[0][0],200);return out[0][1]
 def preparation(self):return load_draft(self.desk.store,self.id),followup_snapshot(self.desk.store,self.id)
 def event(self,method,id,status=None,error=None,thread='native-parent'):
  self.runtime._message({'method':method,'params':{'threadId':thread,'turn':{'id':id,'status':status,'error':error,'items':[]}}})
 def test_actual_attach_and_http_keep_outcome_separate_from_ready_and_error_clear(self):
  prep=self.preparation();self.runtime.attach();s=self.state();row=next(r for r in s['sessions'] if r['id']==self.id);out=s['native_outcomes'][self.id]
  self.assertEqual((row['status'],row['error']),('ready',None));self.assertEqual((out['turn_id'],out['status'],out['error']['message']),('failed-turn','failed','parser test failed'));self.assertEqual(out['source'],'native history read');self.assertEqual(self.preparation(),prep);self.assertEqual(len(self.calls),1)
 def test_cold_state_uses_retained_snapshot_without_native_call_or_new_schema(self):
  self.runtime.attach();before=self.state()['native_outcomes'];tables=self.desk.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall();self.calls.clear()
  cold=Desk('never-executed',self.home,self.root/'state')
  try:
   with patch.object(cold,'catalog',side_effect=AssertionError('Native read forbidden')):
    self.assertEqual(self.state(cold)['native_outcomes'],before);self.assertEqual(cold.runtimes,{});self.assertIsNone(cold.history_scanner.worker)
   self.assertEqual(self.calls,[]);self.assertEqual(cold.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall(),tables)
  finally:cold.close();cold.store.db.close()
 def test_same_snapshot_dedupes_and_metadata_only_read_preserves_outcome(self):
  self.runtime.attach();before=self.desk.store.events(self.id);self.desk.store.recall_snapshot(self.id,self.thread);self.desk.store.recall_snapshot(self.id,{'id':'native-parent'});self.assertEqual(self.desk.store.events(self.id),before);self.assertEqual(self.state()['native_outcomes'][self.id]['turn_id'],'failed-turn')
 def test_live_new_parent_and_old_snapshot_child_completion_cannot_demote_it(self):
  self.runtime.attach();self.event('turn/started','new-turn','inProgress');self.desk.store.recall_snapshot(self.id,self.thread);self.event('turn/completed','child-turn','failed',{'message':'child failed'},thread='native-child');self.event('turn/completed','failed-turn','failed',{'message':'late older failure'})
  out=self.state()['native_outcomes'][self.id];self.assertEqual((out['turn_id'],out['status'],out['error']),('new-turn','inProgress',None))
  self.event('turn/completed','new-turn','completed');self.assertEqual(self.state()['native_outcomes'][self.id]['status'],'completed')
 def test_empty_native_terminal_turns_keep_failure_interruption_and_completion_truth(self):
  history=[]
  for status,error in [('failed',{'message':'empty turn failed','codexErrorInfo':{'serverOverloaded':{'httpStatusCode':503}}}),('interrupted',None),('completed',None)]:
   with self.subTest(status=status):
    self.thread=self.snapshot(status+'-turn',status,error);self.thread['turns']=history+self.thread['turns'];history=copy.deepcopy(self.thread['turns']);self.runtime.attach();out=self.state()['native_outcomes'][self.id];self.assertEqual((out['turn_id'],out['status'],out['error']),(status+'-turn',status,error))
 def test_native_complete_notification_error_remains_after_actual_reattach(self):
  self.event('turn/started','last-turn','inProgress');self.event('turn/completed','last-turn','failed',{'message':'final timeout check failed','codexErrorInfo':'sandboxError'})
  self.thread=self.snapshot('last-turn','failed',{'message':'final timeout check failed','codexErrorInfo':'sandboxError'});self.runtime.attach();out=self.state()['native_outcomes'][self.id];self.assertEqual(out['source'],'native turn notification');self.assertEqual(out['error']['message'],'final timeout check failed');self.assertEqual(self.desk.store.get(self.id)['status'],'ready')

if __name__=='__main__':unittest.main()
