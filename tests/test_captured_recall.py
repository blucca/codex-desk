"""Current ordinary captures participate in one literal mixed-source read snapshot."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from codex_desk import recall, turn_records
from codex_desk.drafts import save_draft
from codex_desk.followups import add_followup, edit_followup
from codex_desk.runtime import Store
from codex_desk.server import Desk
from codex_desk.turn_dispatch import _binding

ROOT=Path(os.environ.get('DESK_TEST_TEMP',Path.cwd()/'temp'));ROOT.mkdir(parents=True,exist_ok=True)
PHRASE='cobalt recall 保留'
BODY=('Exact '+PHRASE+' Plan — résumé Straße\n'*80)+'ORIGINAL END  '


def history(identifier,cwd,text):
    return {'id':identifier,'cwd':str(cwd),'name':identifier,'updatedAt':1795600000,
            'turns':[{'id':'original-turn','status':'completed','items':[{'id':'original-item','type':'agentMessage','text':text}]}]}


class CapturedRecallTests(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory(dir=ROOT,prefix='captured-recall-');self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);self.state=self.root/'state'
        self.desk=Desk('never-executed',self.root/'home',self.state)
        self.addCleanup(self.desk.store.db.close);self.addCleanup(self.desk.close)
        self.store=self.desk.store
        for id,project in [('a','removed-a'),('b','other-project')]:
            self.store.create(str(self.root/project),'default',identifier=id,name=id)
            self.store.update(id,thread_id='native-'+id,status='saved')
        self.saved=save_draft(self.store,'b','Other saved Plan remains unsent.  ','plan',0,'other-writer',1)
        self.queues=[add_followup(self.store,'b','Other Work remains queued.  ','native'),
                     add_followup(self.store,'b','Other Plan remains queued.  ','plan')]

    def intent(self,id='a',status='needs_review',token=None,text=BODY,mode='plan'):
        token=token or str(uuid.uuid4())
        body=dict(session=id,token=token,text=text,mode=mode,revision=0,writer='captured',sequence=1)
        self.store.event(id,{'method':turn_records.INTENT,'params':dict(token=token,payload=body,binding=_binding(self.desk,id))})
        if status is not None:self.receipt(id,token,status)
        return token

    def receipt(self,id,token,status):
        self.store.event(id,{'method':turn_records.RECEIPT,'params':dict(token=token,status=status,attempt=1)})

    def search(self,q=PHRASE,**kwargs):return self.desk.recall(q,**kwargs)

    def test_request_only_exact_identity_mode_snippet_read_only_and_ordinary_shapes(self):
        before_ordinary=self.search('Other')
        token=self.intent();before=list(self.store.db.iterdump());changes=self.store.db.total_changes
        with patch.object(self.desk,'open') as opened,patch.object(self.desk,'catalog') as catalog, \
             patch('codex_desk.runtime.subprocess.Popen') as spawned:
            result=self.search();standalone=self.store.recall(PHRASE)
            opened.assert_not_called();catalog.assert_not_called();spawned.assert_not_called()
        self.assertEqual(result['total'],1);hit,=result['results']
        self.assertEqual(set(hit),{'session_id','session_name','cwd','profile','archived','kind','token','status','mode','snippet','match_text','updated'})
        self.assertEqual((hit['kind'],hit['session_id'],hit['token'],hit['status'],hit['mode']),('turn_request','a',token,'needs_review','plan'))
        self.assertEqual(hit['match_text'],PHRASE);self.assertLessEqual(len(hit['snippet']),recall.SNIPPET_CHARS+2)
        self.assertNotIn('ORIGINAL END',hit['snippet']);self.assertNotIn('text',hit)
        self.assertEqual(standalone['results'],result['results']);self.assertEqual(result['coverage']['turn_requests'],1)
        self.assertEqual(before_ordinary['results'],self.search('Other')['results'])
        self.assertEqual(before,list(self.store.db.iterdump()));self.assertEqual(changes,self.store.db.total_changes)

    def test_request_read_creates_no_preparation_schema_and_survives_cold_store(self):
        bare=Desk('never-executed',self.root/'bare-home',self.root/'bare-state')
        self.addCleanup(bare.store.db.close);self.addCleanup(bare.close)
        bare.store.create(str(self.root/'removed'),'default',identifier='bare')
        token=str(uuid.uuid4());body=dict(session='bare',token=token,text=BODY,mode='plan',revision=0,writer='writer',sequence=0)
        bare.store.event('bare',{'method':turn_records.INTENT,'params':dict(token=token,payload=body,binding=_binding(bare,'bare'))})
        before=list(bare.store.db.iterdump());result=bare.recall(PHRASE)
        self.assertEqual(result['results'][0]['status'],'pending');self.assertEqual(before,list(bare.store.db.iterdump()))
        tables={r[0] for r in bare.store.db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertFalse(tables & {'drafts','followups','followup_reservations'})
        cold=Desk('never-executed',bare.home,self.root/'bare-state')
        self.addCleanup(cold.store.db.close);self.addCleanup(cold.close)
        before=list(cold.store.db.iterdump());self.assertEqual(cold.recall(PHRASE),result)
        self.assertEqual(before,list(cold.store.db.iterdump()));self.assertEqual(cold.runtimes,{})

    def test_latest_receipts_and_current_uuid_match_prepared_projection(self):
        older=self.intent();known=self.intent(status='accepted')
        self.receipt('a',known,'rejected')
        for status in ('needs_review','pending'):
            self.receipt('a',older,status);hit,=self.search()['results']
            self.assertEqual(hit['token'],turn_records.unresolved_requests(self.store)['a']['token'])
            self.assertEqual(hit['status'],status)
        for status in ('accepted','rejected'):
            self.receipt('a',older,status);self.assertEqual(self.search()['total'],0)
            self.assertNotIn('turn_requests',self.search()['coverage'])
        first=self.intent(status=None);second=self.intent(status=None)
        self.intent(status=None,token=first,text='Changed attachment '+PHRASE,mode='native')
        hit,=self.search()['results'];self.assertEqual(hit['token'],second)
        self.receipt('a',second,'accepted');hit,=self.search()['results']
        self.assertEqual((hit['token'],hit['mode']),(first,'native'))
        self.assertTrue(hit['snippet'].startswith('Changed attachment'))

    def test_latest_intent_body_literal_unicode_mode_and_original_binding_not_guessed(self):
        token=self.intent(text='Old phrase only',status=None)
        self.intent(token=token,text='Prefix STRASSE Cafe\u0301 ＡＢＣ 项目 — tail  ',mode='native',status=None)
        self.store.update('a',thread_id='replacement',cwd=str(self.root/'new-project'),profile='changed-profile')
        self.assertEqual(self.search('Old phrase')['total'],0)
        for query,match in [('Straße','STRASSE'),('café','Cafe\u0301'),('abc','ＡＢＣ'),('项目','项目')]:
            hit,=self.search(query)['results'];self.assertEqual(hit['match_text'],match)
            self.assertEqual(hit['token'],token);self.assertEqual(hit['mode'],'native');self.assertNotIn('thread_id',hit)

    def test_scope_archive_removed_folder_and_native_catalog(self):
        token=self.intent()
        self.assertEqual(self.search(cwd=str(self.root/'removed-a'))['results'][0]['token'],token)
        self.assertEqual(self.search(cwd=str(self.root/'other-project'))['total'],0)
        self.assertEqual(self.search(cwd=str(self.root/'removed-a'/'child'))['total'],0)
        self.store.archive('a',True);self.assertEqual(self.search()['total'],0)
        self.assertEqual(self.search(include_archived=True)['total'],1)
        self.store.create(str(self.root/'removed-a'),'default',identifier='native-catalog')
        native_token=str(uuid.uuid4())
        self.store.event('native-catalog',{'method':turn_records.INTENT,'params':dict(token=native_token,payload=dict(text=BODY,mode='plan'))})
        self.assertEqual(self.search(include_archived=True)['total'],1)

    def test_distinct_duplicate_wording_and_page_count_across_all_sources(self):
        token=self.intent();save_draft(self.store,'a',BODY,'plan',0,'newer',1)
        one=add_followup(self.store,'a',BODY,'native');two=add_followup(self.store,'a',BODY,'plan')
        self.store.recall_snapshot('a',history('native-a',self.root/'removed-a',BODY))
        self.desk.native_index.replace_snapshot(history('unbound',self.root/'removed-a',BODY))
        complete=self.search(limit=50);self.assertEqual(complete['total'],6)
        pages=[]
        with patch('codex_desk.recall._snippet',wraps=recall._snippet) as snippets:
            for offset in (0,2,4):
                page=self.search(limit=2,offset=offset);self.assertEqual(page['total'],6)
                self.assertEqual(page['has_more'],offset<4);pages.extend(page['results'])
            self.assertEqual(snippets.call_count,6)
        self.assertEqual(pages,complete['results'])
        identities=[(h['kind'],h.get('session_id'),h.get('thread_id'),h.get('token'),h.get('followup_id'),h.get('item_id')) for h in pages]
        self.assertEqual(len(set(identities)),6)
        self.assertEqual({h['kind'] for h in pages},{'activity','native-activity','draft','followup','turn_request'})
        self.assertEqual(next(h for h in pages if h['kind']=='turn_request')['token'],token)
        self.assertEqual({h['followup_id'] for h in pages if h['kind']=='followup'},{one['id'],two['id']})

    def test_sql_method_selection_never_materializes_native_delta_payloads(self):
        self.intent()
        for _ in range(60):
            self.store.event('a',{'method':'item/agentMessage/delta','params':{'delta':(PHRASE+' desk/turnIntent desk/turnReceipt ')*500}})
        with patch.object(turn_records.json,'loads',wraps=json.loads) as decoded:
            self.assertEqual(self.search()['total'],1);self.assertEqual(decoded.call_count,0)

    def test_combined_count_page_and_coverage_keep_one_wal_snapshot(self):
        self.store.db.execute('PRAGMA journal_mode=WAL')
        token=self.intent();saved=save_draft(self.store,'b',BODY,'plan',self.saved['revision'],'snapshot',1)
        queues=[edit_followup(self.store,'b',q['id'],BODY,q['mode'],q['revision']) for q in self.queues]
        self.store.recall_snapshot('a',history('native-a',self.root/'removed-a',BODY))
        self.desk.native_index.replace_snapshot(history('unbound',self.root/'removed-a',BODY))
        before=self.search(limit=50);self.assertEqual(before['total'],6)
        second=Desk('never-executed',self.desk.home,self.state)
        self.addCleanup(second.store.db.close);self.addCleanup(second.close)
        entered,release=threading.Event(),threading.Event();original=self.desk.native_index._search_query
        def held(*args,**kwargs):
            result=original(*args,**kwargs);entered.set();self.assertTrue(release.wait(5));return result
        with patch.object(self.desk.native_index,'_search_query',side_effect=held),ThreadPoolExecutor(max_workers=1) as pool:
            reading=pool.submit(self.search,limit=50)
            try:
                self.assertTrue(entered.wait(5))
                second.store.event('a',{'method':turn_records.RECEIPT,'params':dict(token=token,status='rejected',attempt=1)})
                save_draft(second.store,'b','Newer nonmatching Plan','plan',saved['revision'],'second',1)
                for q in queues:edit_followup(second.store,'b',q['id'],'Newer nonmatching queue',q['mode'],q['revision'])
                second.store.recall_snapshot('a',history('native-a',self.root/'removed-a','Newer nonmatching activity'))
                second.native_index.replace_snapshot(history('unbound',self.root/'removed-a','Newer nonmatching native'))
            finally:release.set()
            self.assertEqual(reading.result(timeout=5),before)
        self.assertEqual(self.search()['total'],0)

    def test_caller_owned_transaction_is_not_committed_by_search(self):
        self.intent();self.store.db.execute('BEGIN')
        self.store.db.execute("UPDATE sessions SET name='Caller-owned edit' WHERE id='a'")
        self.assertEqual(self.search()['results'][0]['session_name'],'Caller-owned edit')
        self.assertTrue(self.store.db.in_transaction);self.store.db.rollback()
        self.assertEqual(self.search()['results'][0]['session_name'],'a')


if __name__=='__main__':unittest.main()
