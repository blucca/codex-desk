"""Native source references stay namespaced and read-only across launch homes."""
import copy, unittest
from urllib.parse import urlencode
from test_task_response_api import TaskResponseApiTests

class EvidenceSourceApiTests(TaskResponseApiTests):
 # Reuse the actual subprocess native/HTTP/SQLite fixture, not its tests.
 pass
for name in list(TaskResponseApiTests.__dict__):
 if name.startswith('test_'):setattr(EvidenceSourceApiTests,name,None)

def path(self,home=None,thread='parent'):
 return '/api/native/evidence-source?'+urlencode({'home':home if home is not None else self.desk.native_home_namespace(),'thread':thread})
EvidenceSourceApiTests.source_path=path

def exact(self):
 before=self.state();status,result,cache=self.request(path=self.source_path())
 self.assertEqual((status,cache),(200,'no-store'));self.assertEqual(result['thread'],self.source)
 self.assertEqual(result['home_namespace'],self.desk.native_home_namespace());self.assertNotIn('home',result)
 self.assert_read_only(before,1)
EvidenceSourceApiTests.test_exact_native_source_one_read_zero_writes=exact

def namespace(self):
 before=self.state();status,result,_=self.request(path='/api/native/home')
 self.assertEqual(status,200);self.assertEqual(result,{'home_namespace':self.desk.native_home_namespace()})
 self.assertEqual(len(result['home_namespace']),64);self.assertNotIn(str(self.home),str(result));self.assert_read_only(before,0)
EvidenceSourceApiTests.test_discovery_is_opaque_and_no_native_read=namespace

def foreign(self):
 before=self.state()
 for value in ['','other','x'*100000,'0'*64]:
  # Avoid HTTP request-line limits unrelated to native namespace validation.
  if len(value)>200:continue
  status,_,_=self.request(path=self.source_path(value));self.assertEqual(status,400)
 self.assert_read_only(before,0)
EvidenceSourceApiTests.test_wrong_home_rejected_before_native_read=foreign

def strict(self):
 before=self.state();home=self.desk.native_home_namespace()
 for query in ['','thread=parent','home='+home,'home='+home+'&thread=', 'home='+home+'&thread=parent&extra=1','home='+home+'&home='+home+'&thread=parent','home='+home+'&thread=parent&thread=other','home='+home+'&thread='+('x'*201)]:
  status,_,_=self.request(path='/api/native/evidence-source?'+query);self.assertEqual(status,400)
 status,_,_=self.request(path='/api/native/home?home='+home);self.assertEqual(status,400);self.assert_read_only(before,0)
EvidenceSourceApiTests.test_strict_query_before_native_read=strict

def source_mismatch(self):
 before=self.state();self.set_reply({'thread':{**self.source,'id':'foreign'}})
 status,_,_=self.request(path=self.source_path());self.assertEqual(status,400);self.assert_read_only(before,1)
EvidenceSourceApiTests.test_foreign_thread_not_substituted=source_mismatch

def failed(self):
 before=self.state();self.set_reply({'native_error':'Original temporarily unavailable'})
 status,body,_=self.request(path=self.source_path());self.assertEqual(status,400);self.assert_read_only(before,1)
 self.set_reply({'thread':self.source});status,body,_=self.request(path=self.source_path());self.assertEqual(status,200);self.assert_read_only(before,2)
EvidenceSourceApiTests.test_native_failure_explicit_same_source_retry=failed

def different_home(self):
 before=self.state();original_home=self.desk.home;namespace=self.desk.native_home_namespace()
 self.desk.home=self.root/'different-home'
 status,_,_=self.request(path=self.source_path(namespace));self.assertEqual(status,400)
 self.desk.home=original_home;self.assert_read_only(before,0)
EvidenceSourceApiTests.test_launch_home_change_preserves_old_reference_identity=different_home

def post(self):
 before=self.state();status,_,_=self.request(method='POST',path='/api/native/evidence-source',data={'home':self.desk.native_home_namespace(),'thread':'parent'})
 self.assertEqual(status,404);self.assert_read_only(before,0)
EvidenceSourceApiTests.test_post_not_admission_route=post
# Do not rediscover inherited fixture's existing task-response cases here.
del TaskResponseApiTests


def static_asset(self):
 import http.client
 from pathlib import Path
 import codex_desk
 before=self.state();c=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
 try:
  c.request('GET','/evidence-preparation.js');r=c.getresponse();self.assertEqual(r.status,200)
  self.assertEqual(r.getheader('Content-Type'),'text/javascript; charset=utf-8')
  self.assertEqual(r.read(),(Path(codex_desk.__file__).parent/'static/evidence-preparation.js').read_bytes())
 finally:c.close()
 self.assert_read_only(before,0)
EvidenceSourceApiTests.test_public_static_module_bootstrap_exact_source_zero_writes=static_asset
