"""Prospective black-box steering contracts on an isolated product source.

Set DESK_SOURCE to the private implementation candidate. The source under test supplies both the native reducer and HTTP handlers.
"""
from pathlib import Path
import json,os,sys,threading,unittest,uuid
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
from unittest.mock import Mock,patch
W=Path('/home/i/workspace');S=Path(os.environ.get('DESK_SOURCE',Path(__file__).resolve().parents[1]))
T=W/'temp/round159-steer/contract-scratch';T.mkdir(parents=True,exist_ok=True)
os.environ['DESK_TEST_TEMP']=str(T);sys.path[:0]=[str(S),str(S/'tests')]
from test_approval_lifecycle import NativeHTTPFixture
from codex_desk.runtime import NativeRequestRejected,NativeRequestUnknown
from codex_desk.server import Desk,handler
from codex_desk.drafts import save_draft,load_draft
from codex_desk.followups import add_followup,followup_snapshot
from codex_desk.turn_records import request_records
THREAD='native-original';TURN='active-inspect-test';TEXT='Run parser unit tests only — 保留  '

class SteerFixture(NativeHTTPFixture):
 def setUp(self):
  super().setUp();spawn=patch('codex_desk.runtime.subprocess.Popen',side_effect=AssertionError('Steer must not launch a native process'));spawn.start();self.addCleanup(spawn.stop);self.other='other-plan';self.desk.store.create(str(self.path),'default',identifier=self.other,name='Other saved Plan')
  self.desk.store.update(self.other,thread_id='native-other',status='ready',mode='plan')
  self.desk.store.update(self.identifier,status='ready',mode='native')
  for sid in [self.identifier,self.other]:
   save_draft(self.desk.store,sid,'Exact unsent Plan '+sid,'plan',0)
   add_followup(self.desk.store,sid,'Prepared Work '+sid,'native');add_followup(self.desk.store,sid,'Prepared Plan '+sid,'plan')
  self.emit('turn/started',{'threadId':THREAD,'turn':{'id':TURN,'status':'inProgress','items':[]}})
  self.emit('turn/plan/updated',{'threadId':THREAD,'turnId':TURN,'plan':[{'step':'Inspect','status':'completed'},{'step':'Test','status':'inProgress'}]})
  self.initial=self.preparation();self.tables=self.table_names();self.native_mode='accept'
  self.entered=threading.Event();self.release=threading.Event();self.release.set();self.addCleanup(self.release.set)
  self.runtime.request=self.controlled_native
  self.desk.open=Mock(side_effect=AssertionError('Steer must not open/resume'))
  self.desk.runtime=Mock(side_effect=AssertionError('Steer must not auto-acquire/open runtime'))
  self.desk.retire_runtime=Mock(side_effect=AssertionError('Transport-unknown must not stop the current task'))
 def emit(self,method,params):
  with self.runtime.lifecycle_lock:self.runtime._message({'method':method,'params':params})
 def preparation(self):
  return {sid:{'draft':load_draft(self.desk.store,sid),'queue':followup_snapshot(self.desk.store,sid),'mode':self.desk.store.get(sid)['mode']} for sid in [self.identifier,self.other]}
 def table_names(self):return [r[0] for r in self.desk.store.db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
 def payload(self,**extra):return {'session':self.identifier,'token':str(uuid.uuid4()),'threadId':THREAD,'expectedTurnId':TURN,'text':TEXT,**extra}
 def controlled_native(self,method,params):
  self.requests.append({'method':method,'params':params});self.assertEqual(method,'turn/steer');self.entered.set()
  self.assertTrue(self.release.wait(5),'Unreleased contract native request')
  if self.native_mode=='reject':raise NativeRequestRejected('activeTurnNotSteerable: review')
  if self.native_mode in ('finish','unknown-finish'):self.emit('turn/completed',{'threadId':THREAD,'turn':{'id':TURN,'status':'completed','items':[]}})
  if self.native_mode=='unknown-new':
   self.emit('turn/completed',{'threadId':THREAD,'turn':{'id':TURN,'status':'completed','items':[]}})
   self.emit('turn/started',{'threadId':THREAD,'turn':{'id':'genuine-new-turn','status':'inProgress','items':[]}})
  if self.native_mode.startswith('unknown'):raise NativeRequestUnknown('Native request timed out')
  if self.native_mode=='malformed':return {'turn':{'id':TURN}}
  return {'turnId':params['expectedTurnId']}
 def call(self,path,data=None):
  q=Request(f'http://127.0.0.1:{self.server.server_port}'+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
  try:
   with urlopen(q,timeout=7) as r:return r.status,json.load(r)
  except HTTPError as r:
   with r:return r.code,json.load(r)
 def send(self,body,expected='accepted'):
  status,result=self.call('/api/steer',body);self.assertEqual(status,200,result)
  self.assertEqual((result['session'],result['token']),(body['session'],body['token']))
  self.assertEqual(result['request']['status'],expected);self.assertEqual(result['request']['payload'],body);return result
 def read(self,body):return self.call('/api/steer/request?'+urlencode({'session':body['session'],'token':body['token']}))
 def unchanged(self):
  self.assertEqual(self.preparation(),self.initial);self.assertEqual(self.table_names(),self.tables);self.assertFalse(self.sent)
  self.desk.open.assert_not_called();self.desk.runtime.assert_not_called();self.desk.retire_runtime.assert_not_called()
 def cold_owner(self):
  self.close_server();self.desk=Desk('unused-fake-native',self.path,self.path/'state');self.addCleanup(self.desk.store.db.close)
  self.desk.open=Mock(side_effect=AssertionError('Cold receipt must not open'));self.desk.runtime=Mock(side_effect=AssertionError('Cold receipt must not resume'));self.desk.retire_runtime=Mock(side_effect=AssertionError('Cold read must not retire'))
  self.server=ThreadingHTTPServer(('127.0.0.1',0),handler(self.desk));self.server_thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.server_thread.start()

class CurrentBaselineContracts(SteerFixture):
 def test_native_schema_is_same_turn_not_start_response(self):
  schema=json.loads((W/'temp/codex-protocol-0.171/v2/TurnSteerParams.json').read_text());self.assertEqual(set(schema['required']),{'threadId','expectedTurnId','input'})
  reply=json.loads((W/'temp/codex-protocol-0.171/v2/TurnSteerResponse.json').read_text());self.assertEqual(reply['required'],['turnId'])
 def test_current_stop_resolver_is_not_a_steer_active_turn_precondition(self):
  self.emit('turn/completed',{'threadId':THREAD,'turn':{'id':TURN,'status':'completed','items':[]}})
  calls=[];self.runtime.request=lambda m,p:calls.append((m,p))
  self.runtime.interrupt();self.assertEqual(calls,[('turn/interrupt',{'threadId':THREAD,'turnId':TURN})])
 def test_turn_projection_does_not_read_steer_events(self):
  body=self.payload();self.desk.store.event(self.identifier,{'method':'desk/steerIntent','params':{'token':body['token'],'payload':body,'binding':{}}})
  self.desk.store.event(self.identifier,{'method':'desk/steerReceipt','params':{'token':body['token'],'status':'accepted','result':{'turnId':TURN}}})
  self.assertEqual(request_records(self.desk.store,self.identifier),{});self.unchanged()

class SteeringAdmissionContracts(SteerFixture):
 def test_positive_exact_native_payload_and_no_start_mode_draft_or_queue_change(self):
  body=self.payload();before=self.desk.store.get(self.identifier);result=self.send(body)
  self.assertEqual(result['request']['result'],{'turnId':TURN});self.assertTrue(result['request']['target_current'])
  self.assertEqual(self.requests,[{'method':'turn/steer','params':{'threadId':THREAD,'expectedTurnId':TURN,'input':[{'type':'text','text':TEXT}]}}])
  self.assertEqual(self.desk.store.get(self.identifier),before);self.assertEqual(request_records(self.desk.store,self.identifier),{});self.unchanged()
 def test_native_rejection_is_recoverable_without_retry_or_current_task_change(self):
  self.native_mode='reject';body=self.payload();before=self.desk.store.get(self.identifier);result=self.send(body,'rejected')
  self.assertIn('activeTurnNotSteerable',result['request']['error']);self.send(body,'rejected');self.assertEqual(len(self.requests),1)
  self.assertEqual(self.desk.store.get(self.identifier),before);self.unchanged()
 def test_unknown_never_resends_or_stops_and_new_same_turn_request_is_blocked(self):
  self.native_mode='unknown';body=self.payload();before=self.desk.store.get(self.identifier);self.send(body,'needs_review');self.send(body,'needs_review')
  status,result=self.read(body);self.assertEqual(status,200);self.assertEqual(result['request']['status'],'needs_review')
  status,_=self.call('/api/steer',self.payload());self.assertEqual(status,409);self.assertEqual(len(self.requests),1)
  self.assertEqual(self.desk.store.get(self.identifier),before);self.unchanged()
 def test_completion_during_native_reply_keeps_genuine_terminal_status(self):
  self.native_mode='finish';body=self.payload();result=self.send(body);self.assertFalse(result['request']['target_current'])
  self.assertEqual(self.desk.store.get(self.identifier)['status'],'completed');self.send(body);self.assertEqual(len(self.requests),1);self.unchanged()
 def test_completed_target_and_new_turn_precondition_reject_before_native_dispatch(self):
  self.emit('turn/completed',{'threadId':THREAD,'turn':{'id':TURN,'status':'completed','items':[]}});self.send(self.payload(),'rejected');self.assertFalse(self.requests)
  self.emit('turn/started',{'threadId':THREAD,'turn':{'id':'new-target','status':'inProgress','items':[]}})
  self.send(self.payload(),'rejected');self.assertFalse(self.requests);self.send(self.payload(expectedTurnId='new-target'));self.assertEqual(len(self.requests),1);self.unchanged()
 def test_unknown_is_not_proven_by_later_parent_turn_started(self):
  self.native_mode='unknown-new';body=self.payload();result=self.send(body,'needs_review');self.assertFalse(result['request']['target_current'])
  self.assertEqual(self.desk.store.get(self.identifier)['status'],'running');self.native_mode='accept';self.send(self.payload(expectedTurnId='genuine-new-turn'))
  self.assertEqual(len(self.requests),2);self.send(body,'needs_review');self.assertEqual(len(self.requests),2);self.unchanged()
 def test_malformed_turn_start_shaped_success_is_unknown_not_accepted(self):
  self.native_mode='malformed';body=self.payload();self.send(body,'needs_review');self.send(body,'needs_review');self.assertEqual(len(self.requests),1);self.unchanged()
 def test_duplicate_pending_and_get_are_read_only_while_native_is_held(self):
  body=self.payload();self.release.clear();result=[];errors=[]
  def first():
   try:result.append(self.send(body))
   except BaseException as e:errors.append(e)
  worker=threading.Thread(target=first);worker.start()
  try:
   self.assertTrue(self.entered.wait(2));before=self.desk.store.events(self.identifier);status,current=self.read(body)
   self.assertEqual(status,200);self.assertEqual(current['request']['status'],'pending');self.send(body,'pending')
   self.assertEqual(self.desk.store.events(self.identifier),before);self.assertEqual(len(self.requests),1)
  finally:self.release.set();worker.join(8)
  self.assertFalse(worker.is_alive());self.assertFalse(errors,errors);self.assertEqual(len(result),1);self.unchanged()
 def test_changed_body_same_uuid_is_conflict_and_other_session_cannot_take_it(self):
  body=self.payload();self.send(body);status,_=self.call('/api/steer',{**body,'text':'Different correction'});self.assertEqual(status,409)
  status,_=self.call('/api/steer',{**body,'session':self.other,'threadId':'native-other'});self.assertEqual(status,409);self.assertEqual(len(self.requests),1);self.unchanged()
 def test_missing_runtime_and_wrong_thread_reject_without_open_or_fallback(self):
  self.send(self.payload(threadId='native-child'),'rejected');self.assertFalse(self.requests)
  self.desk.runtimes.pop(self.identifier);self.send(self.payload(),'rejected');self.assertFalse(self.requests);self.unchanged()
 def test_accepted_cold_owner_replacement_get_and_duplicate_do_not_resume(self):
  body=self.payload();self.send(body);self.cold_owner();before=self.desk.store.events(self.identifier);status,result=self.read(body)
  self.assertEqual(status,200);self.assertEqual(result['request']['status'],'accepted');self.send(body);self.assertEqual(self.desk.store.events(self.identifier),before);self.assertEqual(len(self.requests),1);self.unchanged()
 def test_abandoned_pending_cold_read_is_unknown_without_new_receipt_write(self):
  body=self.payload();binding={'session':self.identifier,'native_home':os.path.normcase(str(self.desk.home)),'profile':'default','cwd':str(self.path),'thread_id':THREAD}
  self.desk.store.event(self.identifier,{'method':'desk/steerIntent','params':{'token':body['token'],'payload':body,'binding':binding}})
  self.desk.store.event(self.identifier,{'method':'desk/steerReceipt','params':{'token':body['token'],'status':'pending'}})
  self.cold_owner();before=self.desk.store.events(self.identifier);status,result=self.read(body);self.assertEqual(status,200);self.assertEqual(result['request']['status'],'needs_review')
  self.send(body,'needs_review');self.assertEqual(self.desk.store.events(self.identifier),before);self.assertFalse(self.requests);self.unchanged()

if __name__=='__main__':unittest.main(verbosity=2)
