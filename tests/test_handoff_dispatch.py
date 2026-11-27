"""Staged one-target Handoff uses existing prepared-task admission receipts."""
import copy,json,tempfile,threading,unittest,uuid
from pathlib import Path
from types import SimpleNamespace
from codex_desk.server import Desk
from codex_desk.runtime import NativeRequestUnknown,NativeRequestRejected
from codex_desk.handoff_dispatch import start_handoff,handoff_status,HandoffConflict

class HandoffDispatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]/'temp');self.root=Path(self.tmp.name);self.project=self.root/'project';self.project.mkdir()
        self.home=self.root/'home';self.state=self.root/'state';self.desk=Desk('not-called',self.home,self.state)
        self.calls=[];self.mode='accepted';self.gate=None;self.entered=threading.Event()
        self.data={'token':str(uuid.uuid4()),'source':'native-original','cwd':str(self.project),'profile':'default','goal':'Verify the remaining check','text':'Exact reviewed original evidence'}
        self.mount(self.desk)
    def tearDown(self):
        if self.gate:self.gate.set()
        self.desk.close();self.desk.store.db.close();self.tmp.cleanup()
    def mount(self,desk):
        owner=self
        class Loaded:
            def __init__(self,id):
                self.id=id;self.process=SimpleNamespace(poll=lambda:None)
            def close(self):self.process.poll=lambda:0
            def turn(self,text,mode):
                owner.calls.append(('turn',self.id,text,mode));owner.entered.set()
                if owner.gate:assert owner.gate.wait(5)
                if owner.mode=='unknown':raise NativeRequestUnknown('Admission not confirmed')
                if owner.mode=='rejected':raise NativeRequestRejected('Native rejected before start')
                if owner.mode=='event-proof':
                    desk.store.event(self.id,{'method':'turn/started','params':{'threadId':'native-'+self.id,'turn':{'id':'accepted-turn','status':'inProgress'}}})
                    raise NativeRequestUnknown('Reply lost after event')
                return {'turn':{'id':'accepted-turn','status':'completed'}}
        def runtime(id):
            if id not in desk.runtimes:
                owner.calls.append(('open',id));desk.store.update(id,thread_id='native-'+id,status='ready',model='fixture')
                desk.runtimes[id]=Loaded(id)
            return desk.runtimes[id]
        desk.runtime=runtime
    def test_accepted_retry_reuses_one_target_and_one_admission(self):
        first=start_handoff(self.desk,self.data);second=start_handoff(self.desk,self.data)
        self.assertEqual(first,second);self.assertEqual(first['handoff']['status'],'accepted')
        self.assertEqual([c[0] for c in self.calls],['open','turn']);self.assertEqual(len(self.desk.store.sessions()),1)
        self.assertEqual(first['preparation'],{'entries':[],'reservation':None})
    def test_unknown_retry_retains_exact_blocking_reservation_without_native_work(self):
        self.mode='unknown';first=start_handoff(self.desk,self.data);before=copy.deepcopy(self.calls)
        second=start_handoff(self.desk,self.data);self.assertEqual(first,second);self.assertEqual(self.calls,before)
        self.assertEqual(first['handoff']['admission']['outcome'],'unknown')
        self.assertEqual(first['preparation']['reservation']['state'],'unknown')
        self.assertEqual(first['preparation']['entries'][0]['state'],'needs_review')
    def test_rejected_retry_retains_same_target_queued_preparation(self):
        self.mode='rejected';first=start_handoff(self.desk,self.data);again=start_handoff(self.desk,self.data)
        self.assertEqual(first,again);self.assertEqual(first['handoff']['admission']['outcome'],'rejected')
        self.assertIsNone(first['preparation']['reservation']);self.assertEqual(first['preparation']['entries'][0]['state'],'queued')
        self.assertEqual(len(self.calls),2)
    def test_explicit_rejected_followup_retry_updates_retained_request_and_cold_status(self):
        self.mode='rejected';first=start_handoff(self.desk,self.data)
        entry=first['preparation']['entries'][0];self.mode='accepted'
        retry=self.desk.send_followup({'session':first['id'],'id':entry['id'],'revision':entry['revision']})
        recovered=handoff_status(self.desk,self.data['token'])
        self.assertEqual(recovered['id'],first['id']);self.assertEqual(recovered['handoff']['status'],'accepted')
        self.assertEqual(recovered['handoff']['admission'],retry['receipt'])
        self.assertEqual(recovered['handoff']['turn'],retry['turn'])
        self.assertEqual([c[0] for c in self.calls],['open','turn','turn'])
        self.desk.close();self.desk.store.db.close();self.desk=Desk('not-called',self.home,self.state)
        self.desk.runtime=lambda id:self.fail('Cold recovery invoked native')
        self.assertEqual(handoff_status(self.desk,self.data['token']),recovered)
        self.assertEqual(start_handoff(self.desk,self.data),recovered)
    def test_failed_native_open_retains_preparation_for_explicit_same_target_retry(self):
        self.desk.runtime=lambda id:(_ for _ in ()).throw(OSError('Fixture native open failed'))
        first=start_handoff(self.desk,self.data)
        self.assertEqual(first['handoff']['admission']['outcome'],'rejected')
        self.assertEqual(self.calls,[]);self.assertIsNone(first['preparation']['reservation'])
        self.assertEqual(start_handoff(self.desk,self.data),first)
        self.mount(self.desk);entry=first['preparation']['entries'][0]
        self.desk.send_followup({'session':first['id'],'id':entry['id'],'revision':entry['revision']})
        self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff']['status'],'accepted')
        self.assertEqual([c[0] for c in self.calls],['open','turn'])
        self.assertEqual(len(self.desk.store.sessions()),1)
    def test_unknown_explicit_acceptance_updates_request_without_start_or_invented_turn(self):
        self.mode='unknown';first=start_handoff(self.desk,self.data);captured=first['preparation']['reservation']
        reviewed=self.desk.resolve_followup({'session':first['id'],'token':captured['token'],
            'id':captured['entry_id'],'revision':captured['revision'],'outcome':'accepted'})
        recovered=handoff_status(self.desk,self.data['token'])
        self.assertEqual(recovered['handoff']['status'],'accepted')
        self.assertEqual(recovered['handoff']['admission'],reviewed['receipt'])
        self.assertNotIn('turn',recovered['handoff']);self.assertEqual(len(self.calls),2)
        self.assertEqual(start_handoff(self.desk,self.data),recovered)
    def test_unknown_explicit_rejection_updates_request_then_allows_same_target_retry(self):
        self.mode='unknown';first=start_handoff(self.desk,self.data);captured=first['preparation']['reservation']
        reviewed=self.desk.resolve_followup({'session':first['id'],'token':captured['token'],
            'id':captured['entry_id'],'revision':captured['revision'],'outcome':'rejected'})
        recovered=handoff_status(self.desk,self.data['token'])
        self.assertEqual(recovered['handoff']['admission']['outcome'],'rejected')
        self.assertIsNone(recovered['preparation']['reservation']);self.assertEqual(len(self.calls),2)
        self.assertEqual(start_handoff(self.desk,self.data),recovered)
        self.mode='accepted';entry=reviewed['entries'][0]
        self.desk.send_followup({'session':first['id'],'id':entry['id'],'revision':entry['revision']})
        self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff']['status'],'accepted')
        self.assertEqual(len(self.desk.store.sessions()),1)
    def test_explicit_retry_is_pending_until_exact_same_target_admission_returns(self):
        self.mode='rejected';first=start_handoff(self.desk,self.data);entry=first['preparation']['entries'][0]
        self.mode='accepted';self.gate=threading.Event();self.entered.clear();values=[]
        worker=threading.Thread(target=lambda:values.append(self.desk.send_followup(
            {'session':first['id'],'id':entry['id'],'revision':entry['revision']})));worker.start()
        try:
            self.assertTrue(self.entered.wait(3));pending=handoff_status(self.desk,self.data['token'])
            self.assertEqual(pending['handoff']['status'],'pending')
            self.assertEqual(start_handoff(self.desk,self.data),pending);self.assertEqual(len(self.calls),3)
        finally:self.gate.set();worker.join(5)
        self.assertEqual(len(values),1);self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff']['status'],'accepted')
    def test_edited_or_removed_preparation_never_infers_original_request_acceptance(self):
        from codex_desk.followups import edit_followup,remove_followup,add_followup
        self.mode='rejected';first=start_handoff(self.desk,self.data);entry=first['preparation']['entries'][0]
        newer=edit_followup(self.desk.store,first['id'],entry['id'],entry['text'],'plan',entry['revision'])
        self.mode='accepted';self.desk.send_followup({'session':first['id'],'id':newer['id'],'revision':newer['revision']})
        self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff'],first['handoff'])
        other=add_followup(self.desk.store,first['id'],'A separate task','native')
        remove_followup(self.desk.store,first['id'],other['id'],other['revision'])
        self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff'],first['handoff'])
    def test_first_rejected_response_cannot_overwrite_a_later_live_retry_receipt(self):
        from codex_desk.server import FollowupDispatchError
        self.mode='rejected';initial_returned=threading.Event();release_initial=threading.Event()
        send=self.desk.send_followup;initial=[];retried=[]
        def held_initial(data):
            try:return send(data)
            except FollowupDispatchError:
                initial_returned.set();assert release_initial.wait(5)
                raise
        self.desk.send_followup=held_initial
        first=threading.Thread(target=lambda:initial.append(start_handoff(self.desk,self.data)));first.start()
        retry=None
        try:
            self.assertTrue(initial_returned.wait(3));retained=handoff_status(self.desk,self.data['token'])
            entry=retained['preparation']['entries'][0]
            self.mode='accepted';self.gate=threading.Event();self.entered.clear()
            retry=threading.Thread(target=lambda:retried.append(send(
                {'session':retained['id'],'id':entry['id'],'revision':entry['revision']})));retry.start()
            self.assertTrue(self.entered.wait(3));pending=handoff_status(self.desk,self.data['token'])
            release_initial.set();first.join(3);self.assertFalse(first.is_alive())
            self.assertEqual(initial[0],pending)
            self.assertEqual(handoff_status(self.desk,self.data['token']),pending)
        finally:
            release_initial.set()
            if self.gate:self.gate.set()
            first.join(5)
            if retry:retry.join(5)
        self.assertEqual(len(retried),1)
        self.assertEqual(handoff_status(self.desk,self.data['token'])['handoff']['status'],'accepted')
    def test_lost_reply_after_started_event_recovers_exact_native_proof(self):
        self.mode='event-proof';first=start_handoff(self.desk,self.data);again=start_handoff(self.desk,self.data)
        self.assertEqual(first['handoff']['status'],'accepted');self.assertEqual(first,again);self.assertEqual(len(self.calls),2)
        self.assertEqual(first['handoff']['turn']['turn']['id'],'accepted-turn')
    def test_pending_duplicate_is_read_only_and_never_dispatches(self):
        self.gate=threading.Event();values=[]
        worker=threading.Thread(target=lambda:values.append(start_handoff(self.desk,self.data)));worker.start()
        try:
            self.assertTrue(self.entered.wait(3));pending=start_handoff(self.desk,self.data)
            self.assertEqual(pending['handoff']['status'],'pending');self.assertEqual(len(self.calls),2)
            self.assertIsNotNone(pending['preparation']['reservation'])
        finally:self.gate.set();worker.join(5)
        self.assertEqual(len(values),1);self.assertEqual(values[0]['id'],pending['id'])
    def test_changed_body_source_profile_or_cwd_rejected_without_mutation(self):
        original=start_handoff(self.desk,self.data)
        for key,value in [('text','Changed evidence'),('goal','Changed task'),('source','different-native'),('profile','different-profile'),('cwd',str(self.root/'different'))]:
            data={**self.data,key:value};before=list(self.calls)
            with self.assertRaises(HandoffConflict):start_handoff(self.desk,data)
            self.assertEqual(self.calls,before);self.assertEqual(handoff_status(self.desk,self.data['token']),original)
    def test_cold_accepted_and_unknown_recovery_calls_no_native(self):
        self.mode='unknown';original=start_handoff(self.desk,self.data)
        self.desk.close();self.desk.store.db.close();self.desk=Desk('not-called',self.home,self.state)
        self.desk.runtime=lambda id:self.fail('Cold recovery invoked native')
        self.assertEqual(handoff_status(self.desk,self.data['token']),original)
        self.assertEqual(start_handoff(self.desk,self.data),original)
    def test_removed_project_retry_recovers_existing_target_without_recreating_folder(self):
        first=start_handoff(self.desk,self.data);self.project.rmdir()
        self.assertEqual(start_handoff(self.desk,self.data),first);self.assertFalse(self.project.exists());self.assertEqual(len(self.calls),2)
    def test_changed_native_home_cannot_reuse_an_original_request(self):
        start_handoff(self.desk,self.data);self.desk.home=self.root/'different-home'
        with self.assertRaises(ValueError):start_handoff(self.desk,self.data)
        self.assertEqual(len(self.calls),2);self.assertEqual(len(self.desk.store.sessions()),1)
    def test_changed_home_cannot_open_or_send_retained_preparation(self):
        from codex_desk.followups import followup_snapshot
        self.mode='rejected';first=start_handoff(self.desk,self.data);entry=first['preparation']['entries'][0]
        self.desk.home=self.root/'different-home';self.mode='accepted'
        with self.assertRaises(ValueError):self.desk.send_followup(
            {'session':first['id'],'id':entry['id'],'revision':entry['revision']})
        with self.assertRaises(ValueError):self.desk.open(first['id'])
        self.assertEqual(followup_snapshot(self.desk.store,first['id']),first['preparation'])
        self.assertEqual(len(self.calls),2)
    def test_missing_project_and_invalid_token_create_nothing(self):
        with self.assertRaises(ValueError):start_handoff(self.desk,{**self.data,'token':'not-an-id'})
        with self.assertRaises(FileNotFoundError):start_handoff(self.desk,{**self.data,'cwd':str(self.root/'absent')})
        self.assertEqual(self.calls,[]);self.assertEqual(self.desk.store.sessions(),[])
    def test_missing_or_invalid_source_is_rejected_before_target_or_native_work(self):
        for value in (None,'','  ',42,{'id':'native-original'}):
            with self.assertRaises(ValueError):start_handoff(self.desk,{**self.data,'source':value})
        missing={key:value for key,value in self.data.items() if key!='source'}
        with self.assertRaises(ValueError):start_handoff(self.desk,missing)
        self.assertEqual(self.calls,[]);self.assertEqual(self.desk.store.sessions(),[])

    def test_cold_pending_or_missing_intent_target_is_review_only_not_replayed(self):
        token=self.data['token'];identifier='handoff-'+uuid.UUID(token).hex
        self.desk.store.create(str(self.project),'default',identifier=identifier)
        status=handoff_status(self.desk,token)
        self.assertEqual(status['handoff']['status'],'needs_review')
        with self.assertRaises(HandoffConflict):start_handoff(self.desk,self.data)
        self.assertEqual(self.calls,[]);self.assertEqual(len(self.desk.store.sessions()),1)
    def test_source_draft_and_two_followups_stay_exact(self):
        from codex_desk.drafts import save_draft,load_draft
        from codex_desk.followups import add_followup,followup_snapshot
        self.desk.store.create(str(self.project),'default',identifier='original-source')
        self.desk.store.update('original-source',thread_id=self.data['source'],status='ready')
        save_draft(self.desk.store,'original-source','Unsent source Plan','plan',0)
        add_followup(self.desk.store,'original-source','Source Work','native')
        add_followup(self.desk.store,'original-source','Source Plan','plan')
        before=(load_draft(self.desk.store,'original-source'),followup_snapshot(self.desk.store,'original-source'),self.desk.store.get('original-source'))
        retained=start_handoff(self.desk,self.data)
        self.assertEqual(before,(load_draft(self.desk.store,'original-source'),followup_snapshot(self.desk.store,'original-source'),self.desk.store.get('original-source')))
        intent=next(r['event']['params']['identity'] for r in self.desk.store.events(retained['id'])
                    if r['event'].get('method')=='desk/handoffIntent')
        self.assertEqual(intent,{key:self.data[key] for key in ('source','cwd','profile','goal','text')} |
            {'native_home':str(self.home.resolve())})
        sent=self.calls[-1]
        self.assertEqual(sent[2],'Next task: '+self.data['goal']+'\n\n'+self.data['text'])
        self.assertEqual(sent[3],'native')

if __name__=='__main__':unittest.main()
