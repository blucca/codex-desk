"""Actual private HTTP Handoff recovery never repeats native creation/admission."""
import http.client,json,threading,uuid,unittest
from urllib.parse import urlencode
from codex_desk.server import handler,ThreadingHTTPServer
from codex_desk.server import Desk
import test_handoff_dispatch as dispatch_tests

class HandoffRequestApiTests(unittest.TestCase):
    mount=dispatch_tests.HandoffDispatchTests.mount
    def setUp(self):
        dispatch_tests.HandoffDispatchTests.setUp(self);owner=self
        class Handler(handler(self.desk,'local-fixture-access')):
            dropped=False
            def reply(self,value,status=200):
                if getattr(owner,'lose_reply',False) and self.path=='/api/handoff/start' and not Handler.dropped and status==200:
                    Handler.dropped=True;self.close_connection=True;return
                super().reply(value,status)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler);self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
    def tearDown(self):
        if self.gate:self.gate.set()
        self.server.shutdown();self.server.server_close();self.worker.join(3);dispatch_tests.HandoffDispatchTests.tearDown(self)
    def request(self,path,data=None,access=True):
        connection=http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)
        headers={'X-Codex-Desk-Access':'local-fixture-access'} if access else {}
        if data is not None:headers['Content-Type']='application/json'
        try:
            connection.request('POST' if data is not None else 'GET',path,json.dumps(data) if data is not None else None,headers)
            r=connection.getresponse();return r.status,json.loads(r.read())
        finally:connection.close()
    def status(self):return self.request('/api/handoff/request?'+urlencode({'token':self.data['token']}))
    def test_http_accepted_lost_reply_retry_recovers_one_target_and_one_task(self):
        self.lose_reply=True
        with self.assertRaises(http.client.RemoteDisconnected):self.request('/api/handoff/start',self.data)
        status,result=self.request('/api/handoff/start',self.data)
        self.assertEqual(status,200);self.assertEqual(result['handoff']['status'],'accepted')
        self.assertEqual(self.status(),(200,result));self.assertEqual([c[0] for c in self.calls],['open','turn']);self.assertEqual(len(self.desk.store.sessions()),1)
    def test_http_unknown_admission_retry_keeps_existing_review_blocker(self):
        self.mode='unknown';status,result=self.request('/api/handoff/start',self.data)
        self.assertEqual(status,200);self.assertEqual(result['handoff']['admission']['outcome'],'unknown')
        self.assertEqual(self.request('/api/handoff/start',self.data),(200,result));self.assertEqual(self.status(),(200,result))
        status,_=self.request('/api/turn',{'session':result['id'],'text':'Do not admit twice','mode':'native'})
        self.assertEqual(status,409);self.assertEqual(len(self.calls),2)
    def test_http_changed_body_returns409_with_original_target_and_no_new_task(self):
        _,result=self.request('/api/handoff/start',self.data)
        status,conflict=self.request('/api/handoff/start',{**self.data,'text':'Changed body'})
        self.assertEqual(status,409);self.assertEqual(conflict['current']['id'],result['id']);self.assertEqual(len(self.calls),2)
    def test_http_explicit_retained_rejection_retry_updates_read_only_request(self):
        self.mode='rejected';_,first=self.request('/api/handoff/start',self.data)
        entry=first['preparation']['entries'][0];self.mode='accepted'
        status,retried=self.request('/api/followups/send',{'session':first['id'],'id':entry['id'],'revision':entry['revision']})
        self.assertEqual(status,200);status,recovered=self.status()
        self.assertEqual(status,200);self.assertEqual(recovered['id'],first['id'])
        self.assertEqual(recovered['handoff']['status'],'accepted')
        self.assertEqual(recovered['handoff']['admission'],retried['receipt'])
        self.assertEqual(retried['entries'],[]);self.assertIsNone(retried['reservation'])
        self.assertEqual(self.calls[-1][1],first['id']);self.assertEqual(self.calls[-1][2],self.calls[-2][2])
        self.assertEqual(self.request('/api/handoff/start',self.data),(200,recovered))
        self.assertEqual([c[0] for c in self.calls],['open','turn','turn']);self.assertEqual(len(self.desk.store.sessions()),1)
    def test_http_exact_unknown_acceptance_review_refreshes_request_without_native_replay(self):
        self.mode='unknown';_,first=self.request('/api/handoff/start',self.data)
        captured=first['preparation']['reservation'];before=list(self.calls)
        data={'session':first['id'],'token':captured['token'],'id':captured['entry_id'],
              'revision':captured['revision'],'outcome':'accepted'}
        self.assertEqual(self.request('/api/followups/resolve',{**data,'token':'not-the-reservation'})[0],409)
        self.assertEqual(self.status(),(200,first))
        status,reviewed=self.request('/api/followups/resolve',data);self.assertEqual(status,200)
        status,recovered=self.status();self.assertEqual(status,200)
        self.assertEqual(recovered['handoff']['status'],'accepted')
        self.assertEqual(recovered['handoff']['admission'],reviewed['receipt'])
        self.assertNotIn('turn',recovered['handoff']);self.assertIsNone(recovered['preparation']['reservation'])
        self.assertEqual(self.request('/api/handoff/start',self.data),(200,recovered));self.assertEqual(self.calls,before)
    def test_http_pending_duplicate_recovers_same_reservation_without_second_task(self):
        self.gate=threading.Event();completed=[]
        worker=threading.Thread(target=lambda:completed.append(self.request('/api/handoff/start',self.data)));worker.start()
        try:
            self.assertTrue(self.entered.wait(3));status,pending=self.request('/api/handoff/start',self.data)
            self.assertEqual(status,200);self.assertEqual(pending['handoff']['status'],'pending');self.assertEqual(len(self.calls),2)
        finally:self.gate.set();worker.join(5)
        self.assertEqual(completed[0][1]['id'],pending['id'])
    def test_http_request_access_missing_invalid_and_duplicate_options_are_read_only(self):
        self.assertEqual(self.status()[0],404)
        self.assertEqual(self.request('/api/handoff/request?token=not-an-id')[0],400)
        self.assertEqual(self.request('/api/handoff/request?token=x&token=y')[0],400)
        self.assertEqual(self.request('/api/handoff/start',self.data,access=False)[0],403)
        self.assertEqual(self.request('/api/handoff/request?'+urlencode({'token':self.data['token']}),access=False)[0],403)
        self.assertEqual(self.calls,[]);self.assertEqual(self.desk.store.sessions(),[])
    def test_http_cold_same_port_state_status_only_never_opens_or_dispatches(self):
        self.mode='unknown';_,original=self.request('/api/handoff/start',self.data);before=list(self.calls)
        port=self.server.server_port
        self.server.shutdown();self.server.server_close();self.worker.join(3)
        self.desk.close();self.desk.store.db.close();self.desk=Desk('not-called',self.home,self.state)
        self.desk.runtime=lambda id:self.fail('Cold status dispatched native work')
        self.desk.open=lambda id:self.fail('Cold status opened native work')
        self.server=ThreadingHTTPServer(('127.0.0.1',port),handler(self.desk,'local-fixture-access'))
        self.worker=threading.Thread(target=self.server.serve_forever,daemon=True);self.worker.start()
        self.assertEqual(self.status(),(200,original));self.assertEqual(self.calls,before)
        self.assertEqual(self.server.server_port,port);self.assertEqual(len(self.desk.store.sessions()),1)
