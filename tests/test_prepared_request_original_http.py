"""Original request evidence reads reuse the private native read-only route."""
import json
import uuid
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

import test_preparation_api as fixtures
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup
from codex_desk.turn_dispatch import _binding, _payload


class PreparedRequestOriginalHttpTests(unittest.TestCase):
    setUp = fixtures.PreparationApiTests.setUp
    stop_server = fixtures.PreparationApiTests.stop_server
    request = fixtures.PreparationApiTests.request

    def captured(self):
        token = str(uuid.uuid4())
        self.native_id = 'native/original + 保留?'
        self.desk.store.update(self.session, thread_id=self.native_id)
        body = _payload(dict(session=self.session, token=token, text='Exact captured Plan 保留  ',
                             mode='plan', revision=0, writer='original', sequence=1))
        original = _binding(self.desk, self.session)
        self.desk.store.event(self.session, {'method':'desk/turnIntent', 'params':dict(token=token,payload=body,binding=original)})
        self.desk.store.event(self.session, {'method':'desk/turnReceipt', 'params':dict(token=token,status='needs_review',attempt=1)})
        self.desk.store.update(self.session, thread_id='replacement-current-thread')
        other=self.desk.store.create(str(self.root/'other'), 'default', identifier='selected-other')
        save_draft(self.desk.store, other, 'Other saved Plan stays exact  ', 'plan', 0, 'other', 1)
        add_followup(self.desk.store, other, 'Other Work stays queued  ', 'native')
        add_followup(self.desk.store, other, 'Other Plan stays queued  ', 'plan')
        return body, original

    def test_exact_original_get_then_encoded_history_is_private_read_only_and_not_current_target(self):
        body, original = self.captured()
        calls=[]
        thread={'id':self.native_id,'cwd':original['cwd'],'turns':[{'id':'original-turn','status':'completed','items':[]}]}
        class Catalog:
            def request(self, method, params):
                calls.append((method,params));return {'thread':thread}
        self.desk.catalog=lambda:Catalog()
        before=list(self.desk.store.db.iterdump());changes=self.desk.store.db.total_changes
        with patch.object(self.desk,'open',side_effect=AssertionError('Read opened a native task')), \
             patch('codex_desk.runtime.subprocess.Popen',side_effect=AssertionError('Read spawned native')):
            status, receipt, _=self.request('/api/turn/request?'+urlencode({'session':self.session,'token':body['token']}),self.token)
            self.assertEqual(status,200);self.assertEqual(receipt['request']['binding'],original)
            self.assertEqual(receipt['request']['current_binding']['thread_id'],'replacement-current-thread')
            self.assertEqual(receipt['request']['payload'],body);self.assertTrue(receipt['request']['binding_mismatch'])
            path='/api/native/thread?'+urlencode({'id':receipt['request']['binding']['thread_id']})
            for capability in (None,'wrong-capability'):
                code, response, _=self.request(path,capability)
                self.assertEqual(code,403);self.assertEqual(calls,[])
                self.assertNotIn(self.native_id,json.dumps(response))
            status, read, headers=self.request(path,self.token)
            self.assertEqual(status,200);self.assertEqual(read,thread);self.assertEqual(headers['Cache-Control'],'no-store')
        self.assertEqual(calls,[('thread/read',{'threadId':self.native_id,'includeTurns':True})])
        self.assertEqual(before,list(self.desk.store.db.iterdump()));self.assertEqual(changes,self.desk.store.db.total_changes)
        self.assertEqual(self.desk.runtimes,{})

    def test_missing_original_read_reports_existing_error_without_touching_retained_request_or_preparation(self):
        body, original=self.captured();calls=[]
        class Catalog:
            def request(self, method, params):
                calls.append((method,params));raise FileNotFoundError('The original native rollout is missing')
        self.desk.catalog=lambda:Catalog()
        before=list(self.desk.store.db.iterdump());changes=self.desk.store.db.total_changes
        status, result, _=self.request('/api/native/thread?'+urlencode({'id':self.native_id}),self.token)
        self.assertEqual(status,400);self.assertIn('original native rollout is missing',result['error'])
        status, retained, _=self.request('/api/turn/request?'+urlencode({'session':self.session,'token':body['token']}),self.token)
        self.assertEqual(status,200);self.assertEqual(retained['request']['status'],'needs_review')
        self.assertEqual(retained['request']['payload'],body);self.assertEqual(retained['request']['binding'],original)
        self.assertEqual(calls,[('thread/read',{'threadId':self.native_id,'includeTurns':True})])
        self.assertEqual(before,list(self.desk.store.db.iterdump()));self.assertEqual(changes,self.desk.store.db.total_changes)
        self.assertEqual(self.desk.runtimes,{})


if __name__=='__main__':
    unittest.main()
