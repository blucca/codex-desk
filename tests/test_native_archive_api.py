"""Native archive scope passes to read-only catalog without local archive writes."""
import copy
from urllib.parse import urlencode
import unittest
import test_native_history_api as base


class NativeArchiveApi(unittest.TestCase):
    setUp=base.NativeHistoryApiTests.setUp
    stop_server=base.NativeHistoryApiTests.stop_server
    request=base.NativeHistoryApiTests.request

    def native_request(self, method, params):
        self.calls.append((method,dict(params)))
        if method=='thread/read':
            return {'thread':copy.deepcopy(self.histories[params['threadId']])}
        self.assertEqual(method,'thread/list')
        scope='archived' if params.get('archived') is True else 'current'
        return copy.deepcopy(self.pages[(scope,params.get('cursor'))])

    def sources(self):
        old={'id':'native-archived','cwd':str(self.root/'removed'),'name':'Retry + Café decision','modelProvider':'fixture'}
        current={**old,'id':'native-current'}
        self.pages={('current',None):{'data':[current],'nextCursor':'current-cursor'},
            ('archived',None):{'data':[old],'nextCursor':'archive+页 /='},
            ('archived','archive+页 /='):{'data':[{**old,'id':'older-archive'}],'nextCursor':None}}
        self.histories['native-archived']={**old,'turns':[{'id':'archived-turn','status':'completed','items':[
            {'id':'archived-answer','type':'agentMessage','phase':'final_answer','text':'Retain the retry budget.'}]}]}
        return list(self.desk.store.db.iterdump())

    def test_explicit_archived_title_pages_and_exact_fresh_original_are_get_only(self):
        before=self.sources()
        for cursor,expected in [(None,'native-archived'),('archive+页 /=','older-archive')]:
            q={'archived':'true','search':'Retry + Café decision','cwd':str(self.root/'removed')}
            if cursor:q['cursor']=cursor
            status,result,cache=self.request('GET','/api/native?'+urlencode(q))
            self.assertEqual((status,cache),(200,'no-store'))
            self.assertEqual(result['data'][0]['id'],expected)
            self.assertFalse(result['data'][0]['cwdExists'])
            self.assertEqual(self.calls[-1][1]['archived'],True)
            self.assertEqual(self.calls[-1][1]['searchTerm'],q['search'])
            self.assertEqual(self.calls[-1][1]['cwd'],q['cwd'])
            self.assertEqual(self.calls[-1][1].get('cursor'),cursor)
        status,original,_=self.request('GET','/api/native/thread?id=native-archived')
        self.assertEqual(status,200);self.assertEqual(original,self.histories['native-archived'])
        self.assertEqual(self.calls[-1],('thread/read',{'threadId':'native-archived','includeTurns':True}))
        self.assertEqual(list(self.desk.store.db.iterdump()),before)
        self.assertFalse(self.desk.runtimes);self.runtime.assert_not_called()
        self.assertIsNone(self.desk.history_scanner.worker)

    def test_current_default_and_false_leave_native_archive_out(self):
        before=self.sources()
        for path,explicit in [('/api/native',False),('/api/native?archived=false',True),('/api/native?recent=1',False)]:
            status,result,_=self.request('GET',path)
            self.assertEqual((status,result['data'][0]['id']),(200,'native-current'))
            self.assertEqual('archived' in self.calls[-1][1],explicit)
            if explicit:self.assertIs(self.calls[-1][1]['archived'],False)
        self.assertEqual(list(self.desk.store.db.iterdump()),before)

    def test_invalid_and_duplicate_archive_query_never_contact_native(self):
        before=self.sources()
        for query in ('archived=', 'archived=1','archived=TRUE','archived=yes','archived=true&archived=false','archived=false&archived=false'):
            with self.subTest(query=query):
                status,result,_=self.request('GET','/api/native?'+query)
                self.assertEqual(status,400);self.assertIn('archived=true or archived=false',result['error'])
        self.assertEqual(self.calls,[]);self.catalog_factory.assert_not_called()
        self.assertEqual(list(self.desk.store.db.iterdump()),before)

    def test_local_desk_archive_does_not_set_native_scope(self):
        self.sources()
        sid=self.desk.store.create(str(self.root/'local'),'default',identifier='local-B',name='Saved B')
        self.desk.store.archive(sid,True);before=list(self.desk.store.db.iterdump())
        status,result,_=self.request('GET','/api/native?archived=false')
        self.assertEqual((status,result['data'][0]['id']),(200,'native-current'))
        self.assertIs(self.calls[-1][1]['archived'],False)
        self.assertEqual(list(self.desk.store.db.iterdump()),before)

if __name__=='__main__':unittest.main()
