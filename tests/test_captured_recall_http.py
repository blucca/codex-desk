"""Actual ordinary unknown Run, explicit clear/cold recall and original review."""
import copy
from pathlib import Path
import unittest
from urllib.parse import urlencode
from unittest.mock import patch

import test_turn_request_integration as fixtures
from codex_desk.drafts import load_draft
from codex_desk.followups import followup_snapshot
from codex_desk.server import Desk

PHRASE='Copper lantern recall marker 保留'
BODY=('Review '+PHRASE+' exactly.\n'*150)+'CAPTURED ORIGINAL END  '


class CapturedRecallHttpTests(fixtures.TurnRequestIntegrationTests):
    def test_unknown_clear_cold_request_hit_and_resolution_keep_newer_preparation(self):
        capture=self.capture(BODY,'plan');self.native_mode='unknown'
        status,unknown=self.request('/api/turn',capture)
        self.assertEqual(status,200);self.assertEqual(unknown['request']['status'],'needs_review')
        self.assertEqual(len(self.requests),1)
        self.assertFalse(any(e['event']['method'] in ('turn/started','turn/completed','item/started','item/completed')
                             for e in self.desk.store.events(self.identifier)))
        current=load_draft(self.desk.store,self.identifier)
        self.assertEqual(self.request('/api/draft',dict(session=self.identifier,text='',mode='plan',revision=current['revision'],
                          writer=capture['writer'],sequence=capture['sequence']+1))[0],200)
        order=[e['id'] for e in followup_snapshot(self.desk.store,self.identifier)['entries']]
        self.assertEqual(self.request('/api/followups/clear',dict(session=self.identifier,order=order))[0],200)
        other=self.desk.store.create(str(self.path/'other-project'),'default',identifier='other-prepared')
        self.assertEqual(self.request('/api/draft',dict(session=other,text='Other unsent Plan  ',mode='plan',revision=0,writer='other',sequence=1))[0],200)
        for text,mode in [('Other queued Work  ','native'),('Other queued Plan  ','plan')]:
            self.assertEqual(self.request('/api/followups',dict(session=other,text=text,mode=mode))[0],200)
        prepared=lambda id:dict(draft=load_draft(self.desk.store,id),followups=followup_snapshot(self.desk.store,id))
        other_before=copy.deepcopy(prepared(other))
        query='/api/recall?'+urlencode(dict(q=PHRASE,limit=1,offset=0))
        before=list(self.desk.store.db.iterdump());changes=self.desk.store.db.total_changes
        with patch.object(self.desk,'open',side_effect=AssertionError('Search opened native')), \
             patch.object(self.desk,'catalog',side_effect=AssertionError('Search read native')):
            status,result=self.request(query)
        self.assertEqual(status,200);self.assertEqual(result['total'],1)
        hit,=result['results'];self.assertEqual((hit['kind'],hit['token'],hit['status'],hit['mode']),('turn_request',capture['token'],'needs_review','plan'))
        self.assertEqual(hit['match_text'],PHRASE);self.assertNotIn('CAPTURED ORIGINAL END',hit['snippet'])
        self.assertEqual(self.read_request(capture)[1]['request']['payload'],capture)
        self.assertEqual(before,list(self.desk.store.db.iterdump()));self.assertEqual(changes,self.desk.store.db.total_changes)
        # Cold means replacing the real handler as well as the Desk and connection.
        self.close_server();old=self.desk
        state=Path(old.store.db.execute('PRAGMA database_list').fetchone()[2]).parent
        self.desk=Desk(old.binary,old.home,state);self.start_server()
        self.addCleanup(self.desk.store.db.close);self.addCleanup(self.desk.close)
        before=list(self.desk.store.db.iterdump());changes=self.desk.store.db.total_changes
        with patch('codex_desk.runtime.subprocess.Popen',side_effect=AssertionError('Cold search started native')):
            status,cold=self.request(query)
        self.assertEqual((status,cold),(200,result));self.assertEqual(self.desk.runtimes,{})
        self.assertEqual(before,list(self.desk.store.db.iterdump()));self.assertEqual(changes,self.desk.store.db.total_changes)
        self.assertEqual(prepared(other),other_before)
        current=load_draft(self.desk.store,self.identifier)
        self.assertEqual(self.request('/api/draft',dict(session=self.identifier,text='Newer '+BODY,mode='plan',revision=current['revision'],writer='newer-page',sequence=1))[0],200)
        for mode in ('native','plan'):
            self.assertEqual(self.request('/api/followups',dict(session=self.identifier,text='Newer queue '+PHRASE,mode=mode))[0],200)
        original_newer=copy.deepcopy(prepared(self.identifier))
        full='/api/recall?'+urlencode(dict(q=PHRASE,limit=50))
        self.assertEqual(self.request(full)[1]['total'],4)
        status,resolved=self.request('/api/turn/resolve',dict(session=self.identifier,token=capture['token'],outcome='accepted'))
        self.assertEqual(status,200);self.assertEqual(resolved['request']['status'],'accepted')
        after=self.request(full)[1];self.assertEqual(after['total'],3)
        self.assertFalse(any(r['kind']=='turn_request' for r in after['results']))
        self.assertEqual(prepared(self.identifier),original_newer);self.assertEqual(prepared(other),other_before)
        self.assertEqual(len(self.requests),1);self.assertEqual(self.desk.runtimes,{})
        old.close()


def load_tests(loader, tests, pattern):
    return unittest.TestSuite([CapturedRecallHttpTests('test_unknown_clear_cold_request_hit_and_resolution_keep_newer_preparation')])


if __name__=='__main__':unittest.main()
