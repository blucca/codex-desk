"""Quiet overview uses exact compact material ownership, never transport/status review."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
REFERENCE = Path(os.environ.get('DESK_TEST_NEW_ACTIVITY', ROOT / 'codex_desk/static/new-activity.js'))

PREFIX = r'''
'use strict';
const assert=require('assert/strict'),W=require(process.argv[1]);
const H='a'.repeat(64),OTHER='b'.repeat(64);
const own=(session,thread_id='native-'+session,native_home=H)=>({native_home,session,thread_id});
const task=(session,group_id='project-1',active=false,archived=false,thread_id='native-'+session)=>({session,group_id,active,archived,thread_id});
const summary=(session,material_seq,received_seq=material_seq,thread_id='native-'+session,native_home=H)=>({owner:own(session,thread_id,native_home),status:'available',material_seq,received_seq});
const review=(session,reviewed_seq,thread_id='native-'+session,native_home=H)=>({owner:own(session,thread_id,native_home),reviewed_seq});
const input=(tasks,summaries,reviews=[])=>({native_home:H,tasks,summaries,reviews});
const rows=view=>view.groups.flatMap(group=>group.rows);
const projected=(session,material_seq=20,reviewed_seq=10)=>rows(W.project(input([task(session)],[summary(session,material_seq)],[review(session,reviewed_seq)]),{mode:'all'}))[0];
const item=(seq,itemId='command',turnId='turn-A',threadId='native-A',type='commandExecution')=>({seq,event:{method:'item/completed',params:{threadId,turnId,item:{id:itemId,type,command:'synthetic verify',status:'completed'}}}});
const delta=(seq,itemId='command',turnId='turn-A',threadId='native-A')=>({seq,event:{method:'item/commandExecution/outputDelta',params:{threadId,turnId,itemId,delta:'source text stays outside overview'}}});
const source=(items=[{turn_id:'turn-A',item_id:'command',item_type:'commandExecution'}],turn_ids=['turn-A'])=>({...own('A'),kind:'fresh_native',turn_ids,items});
'''


@unittest.skipUnless(NODE, 'Node is needed for the pure overview helper')
class ChangedWorkHelperTests(unittest.TestCase):
    def run_js(self, script, activity=False):
        extra = ''
        if activity:
            self.assertTrue(REFERENCE.is_file(), 'Set DESK_TEST_NEW_ACTIVITY to the accepted pure next1 helper')
            extra = "const N=require(process.argv[2]);\n"
        code = PREFIX + extra + script + "\nprocess.stdout.write(JSON.stringify({passed:true}));\n"
        result = subprocess.run([NODE, '-e', code, str(ROOT / 'codex_desk/static/changed-work.js'), str(REFERENCE)], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(json.loads(result.stdout)['passed'])

    def test_a_b_c_baseline_is_unknown_not_no_new_material(self):
        self.run_js(r'''
const value=input([task('A'),task('B'),task('C')],[summary('A',15,50),summary('B',0,80),summary('C',20,90)],[review('A',10),review('B',0)]);
const result=W.project(value,{mode:'all'}),all=new Map(rows(result).map(row=>[row.session,row]));
assert.equal(all.get('A').activity_status,'new_activity');assert.equal(all.get('A').changed,true);
assert.equal(all.get('B').activity_status,'up_to_date');assert.equal(all.get('B').changed,false);assert.equal(all.get('B').reviewed_seq,0);
assert.equal(all.get('C').activity_status,'baseline_missing');assert.equal(all.get('C').changed,null);
assert.equal(all.get('C').material_seq,20);assert.equal(all.get('C').reviewed_seq,null);
assert.deepEqual(result.counts,{new_activity:1,up_to_date:1,baseline_missing:1,summary_unavailable:0,binding_unavailable:0,review_baseline_missing:1});
assert.deepEqual(rows(W.project(value)).map(row=>row.session),['A']);
''')

    def test_transport_completion_and_pending_request_do_not_make_a_dot(self):
        self.run_js(r'''
const events=[item(1),item(2,'child-command','child-turn','native-child'),
{seq:3,event:{method:'desk/nativeTaskSnapshot',params:{threadId:'native-A',turnId:'turn-A',status:'completed'}}},
{seq:4,event:{method:'turn/completed',params:{threadId:'native-A',turn:{id:'turn-A',status:'completed'}}}},
{seq:5,event:{id:801,method:'item/tool/requestUserInput',params:{threadId:'native-A',turnId:'turn-A',itemId:'request'}}},
{seq:6,event:{method:'item/commandExecution/outputDelta',params:{threadId:'native-A',turnId:'turn-A',itemId:'command',delta:''}}}];
const batch=N.capture(own('A'),events);assert.equal(batch.frontier,1);assert.equal(batch.received_seq,6);
const row=rows(W.project(input([task('A','project-1',true)],[summary('A',batch.frontier,batch.received_seq)],[review('A',1)])))[0];
assert.equal(row.changed,false);assert.equal(row.active,true);assert.equal(row.activity_status,'up_to_date');
const completionOnly=W.project(input([{...task('A'),status:'completed',pending:[{id:801}]}],[summary('A',1,600)],[review('A',1)]));
assert.equal(completionOnly.total_tasks,0);assert.equal(completionOnly.counts.up_to_date,1);
''', activity=True)

    def test_exact_native_home_and_binding_never_borrow_old_review(self):
        self.run_js(r'''
const mixed=input([task('A','project-1',false,false,'new-A'),task('B')],
[summary('A',30,30,'native-A'),summary('B',40,40,'native-B',OTHER)],
[review('A',100,'native-A'),review('B',100,'native-B',OTHER)]);
const all=new Map(rows(W.project(mixed,{mode:'all'})).map(row=>[row.session,row]));
assert.equal(all.get('A').summary_status,'thread_mismatch');assert.equal(all.get('A').reviewed_seq,null);
assert.equal(all.get('B').summary_status,'home_mismatch');assert.equal(all.get('B').reviewed_seq,null);
assert.equal(all.get('A').changed,null);assert.equal(all.get('B').changed,null);
const fresh=W.project(input([task('A','project-1',false,false,'new-A')],[summary('A',0,100,'new-A')],[review('A',100,'native-A')]),{mode:'all'});
assert.equal(rows(fresh)[0].activity_status,'baseline_missing');assert.equal(rows(fresh)[0].reviewed_seq,null);
''')

    def test_archive_title_filter_and_explicit_project_scope_keep_their_roles(self):
        self.run_js(r'''
const value=input([task('A','project-1',false,true),task('B','project-2',true,true),task('C','project-1')],
[summary('A',20),summary('B',10),summary('C',20)],[review('A',10),review('B',10),review('C',10)]);
assert.deepEqual(rows(W.project(value)).map(row=>row.session),['B','C']);
assert.deepEqual(rows(W.project(value,{query_sessions:[]})).map(row=>row.session),['B']);
assert.deepEqual(rows(W.project(value,{show_archived:true,query_sessions:['A']})).map(row=>row.session),['B','A']);
assert.deepEqual(rows(W.project(value,{show_archived:true,group_id:'project-1'})).map(row=>row.session),['C','A']);
assert.equal(rows(W.project(value,{show_archived:true,query_sessions:[]}))[0].section,'active');
''')

    def test_grouped_sort_and_paging_use_material_not_status_or_received_cursor(self):
        self.run_js(r'''
const value=input([task('A','project-1'),task('B','project-1'),task('C','project-2'),task('D','project-3',true),task('E','project-1')],
[summary('A',20,900),summary('B',30,30),summary('C',40,40),summary('D',10,1000),summary('E',25,25)],
[review('A',10),review('B',10),review('C',10),review('D',10),review('E',10)]);
const complete=W.project(value,{limit:100});assert.deepEqual(rows(complete).map(row=>row.session),['D','C','B','E','A']);
assert.deepEqual(complete.groups.map(group=>group.group_id),['project-3','project-2','project-1']);
const first=W.project(value,{limit:3}),later=W.project(value,{limit:2,offset:3});
assert.deepEqual(rows(first).map(row=>row.session),['D','C','B']);assert.equal(first.has_more,true);
assert.equal(first.groups.at(-1).continued_after,true);assert.equal(first.groups.at(-1).continued_before,false);
assert.deepEqual(rows(later).map(row=>row.session),['E','A']);assert.equal(later.has_more,false);
assert.equal(later.groups[0].continued_before,true);assert.equal(later.groups[0].continued_after,false);
assert.equal(later.total_tasks,5);assert.equal(later.total_groups,3);
const absent=W.project(value,{offset:99});assert.equal(absent.groups.length,0);assert.equal(absent.total_tasks,5);assert.equal(absent.has_more,false);
''')

    def test_boundaries_and_ambiguous_material_are_explicit(self):
        self.run_js(r'''
assert.throws(()=>W.project(input([task('A'),task('A')],[],[])),/ambiguous/);
assert.throws(()=>W.project(input([task('A')],[summary('A',20,10)],[])),/exceed/);
assert.throws(()=>W.project(input(Array.from({length:W.LIMITS.tasks+1},(_,n)=>task('A'+n)),[],[])),/bounded/);
for(const options of [{limit:0},{limit:101},{offset:-1},{offset:1.5},{mode:'inbox'},{show_archived:'true'}])assert.throws(()=>W.project(input([],[],[]),options));
const all=rows(W.project(input([task('A')],[summary('A',20),summary('A',30)],[review('A',10)]),{mode:'all'}));
assert.equal(all[0].summary_status,'summary_ambiguous');assert.equal(all[0].activity_status,'summary_unavailable');assert.equal(all[0].changed,null);
const monotonic=projected('A');const duplicateReviews=rows(W.project(input([task('A')],[summary('A',20)],[review('A',15),review('A',10)]),{mode:'all'}))[0];
assert.equal(duplicateReviews.reviewed_seq,15);assert.equal(monotonic.reviewed_seq,10);
''')

    def test_projection_is_immutable_source_metadata_and_has_no_io(self):
        self.run_js(r'''
const forbidden=()=>{throw Error('No fetch/DOM/storage/open/review writes belong to a projection');};
global.fetch=forbidden;global.document=new Proxy({}, {get:forbidden});global.localStorage=new Proxy({}, {get:forbidden});global.open=forbidden;
const secret='Private unsent text /home/private/path and source body';
const value=input([{...task('A'),title:secret,cwd:secret,draft:secret,queue:[secret],pendingAnswers:secret}],
[{...summary('A',20),body:secret,native_text:secret}],[{...review('A',10),text:secret}]);
const original=JSON.stringify(value),projection=W.project(value,{mode:'all'});
assert.equal(JSON.stringify(value),original);assert.equal(JSON.stringify(projection).includes(secret),false);
assert(Object.isFrozen(projection));assert(Object.isFrozen(projection.groups));assert(Object.isFrozen(rows(projection)[0].owner));
assert.throws(()=>{rows(projection)[0].reviewed_seq=20;},TypeError);
assert.equal(W.STORAGE_KEY,undefined);assert.equal(W.mark,undefined);assert.equal(W.seed,undefined);
''')

    def test_read_first_uses_earliest_grouped_event_not_latest_item(self):
        self.run_js(r'''
const batch=N.capture(own('A'),[delta(15),item(18,'answer','turn-A','native-A','agentMessage'),delta(20)]);
// Supply readable assistant text for classification; command remains first.
const exact=N.capture(own('A'),[delta(15),{seq:18,event:{method:'item/completed',params:{threadId:'native-A',turnId:'turn-A',item:{id:'answer',type:'agentMessage',text:'Later answer'}}}},delta(20)]);
const row=projected('A',20,2),before=JSON.stringify(row);
const resolved=W.resolveFresh(row,exact,source(),N);
assert.equal(resolved.first_new.available,true);assert.equal(resolved.first_new.target.item_id,'command');
assert.equal(resolved.first_new.target.first_seq,15);assert.equal(resolved.first_new.target.last_seq,20);
assert.equal(resolved.reviewed_seq,2);assert.equal(JSON.stringify(row),before);
const reviewed=N.capture(own('A'),[delta(12),delta(14),delta(20)]);
const afterMark=W.resolveFresh(projected('A',20,11),reviewed,source(),N);
assert.equal(afterMark.first_new.target.first_seq,12);assert.equal(afterMark.reviewed_seq,11);
assert.equal(W.resolveFresh(projected('A',20,20),reviewed,source(),N).first_new.status,'up_to_date');
''', activity=True)

    def test_fresh_source_unavailable_fields_do_not_recreate_cached_target(self):
        self.run_js(r'''
const row=projected('A'),batch=N.capture(own('A'),[delta(15),delta(20)]);
const notRead=W.resolveFresh(row,batch,null,N);assert.equal(notRead.first_new.status,'source_not_read');
assert.equal(notRead.fresh_source_status,'not_read');assert.equal(notRead.first_new.pending_target.item_id,'command');assert.equal(notRead.first_new.target,null);
const replay=W.resolveFresh(row,batch,{...source(),kind:'receipt_only'},N);
assert.equal(replay.first_new.status,'source_not_fresh');assert.equal(replay.fresh_source_status,'receipt_only');assert.equal(replay.first_new.target,null);
const failed=W.resolveFresh(row,batch,{...own('A'),kind:'read_failed',errorText:'source body and private path'},N);
assert.equal(failed.first_new.status,'source_read_failed');assert.equal(failed.fresh_source_status,'read_failed');assert(!JSON.stringify(failed).includes('private path'));
const moved=W.resolveFresh(row,batch,source([{turn_id:'later-turn',item_id:'command',item_type:'commandExecution'}],['turn-A','later-turn']),N);
assert.equal(moved.fresh_source_status,'fresh');assert.equal(moved.first_new.status,'item_unavailable');assert.equal(moved.first_new.target,null);
const missing=W.resolveFresh(row,batch,source([],['later-turn']),N);assert.equal(missing.first_new.status,'turn_unavailable');
const duplicate=W.resolveFresh(row,batch,source([source().items[0],source().items[0]]),N);assert.equal(duplicate.first_new.status,'item_ambiguous');
assert.equal(W.resolveFresh(row,batch,source(source().items,['turn-A','turn-A']),N).first_new.status,'turn_ambiguous');
assert.equal(W.resolveFresh(row,batch,source([{turn_id:'turn-A',item_id:'command',item_type:'mcpToolCall'}]),N).first_new.status,'item_type_changed');
const missingCatalog=W.resolveFresh(row,batch,{...source(),items:null},N);
assert.equal(missingCatalog.first_new.status,'source_unavailable');assert.equal(missingCatalog.fresh_source_status,'catalog_unavailable');
''', activity=True)

    def test_source_namespace_session_and_thread_mismatch_are_separate(self):
        self.run_js(r'''
const row=projected('A'),batch=N.capture(own('A'),[delta(20)]);
for(const [field,value,status] of [['native_home',OTHER,'home_mismatch'],['session','B','session_mismatch'],['thread_id','new-A','thread_mismatch']]){
 const result=W.resolveFresh(row,batch,{...source(),[field]:value},N);
 assert.equal(result.first_new.status,status);assert.equal(result.fresh_source_status,status);assert.equal(result.first_new.target,null);
 assert.equal(result.source_owner[field],value);assert.equal(result.owner[field],row.owner[field]);
}
assert.equal(W.resolveFresh(row,batch,{kind:'fresh_native'},N).first_new.status,'owner_unavailable');
''', activity=True)

    def test_stale_or_material_absent_event_capture_stays_unknown_not_reviewed(self):
        self.run_js(r'''
const row=projected('A');
const stale=W.resolveFresh(row,N.capture(own('A'),[delta(19)]),source(),N);
assert.equal(stale.first_new.status,'events_stale');assert.equal(stale.first_new.target,null);assert.equal(stale.activity_status,'new_activity');
const statusOnly=N.capture(own('A'),[{seq:20,event:{method:'turn/completed',params:{threadId:'native-A',turn:{id:'turn-A',status:'completed'}}}}]);
const absent=W.resolveFresh(row,statusOnly,source(),N);
assert.equal(absent.first_new.status,'material_not_located');assert.equal(absent.first_new.target,null);assert.equal(absent.reviewed_seq,10);
assert.equal(JSON.stringify(row),JSON.stringify(projected('A')));
''', activity=True)

    def test_unknown_baseline_and_missing_summary_cannot_seed_through_overview(self):
        self.run_js(r'''
const unknown=rows(W.project(input([task('A')],[summary('A',20)]),{mode:'all'}))[0];
const never={pending:()=>{throw Error('Overview must not establish baseline');},resolveTarget:()=>{throw Error('Overview must not read source');}};
assert.equal(W.resolveFresh(unknown,null,null,never).first_new.status,'baseline_missing');assert.equal(unknown.reviewed_seq,null);
const missing=rows(W.project(input([task('A')],[],[review('A',10)]),{mode:'all'}))[0];
assert.equal(missing.summary_status,'not_reported');assert.equal(W.resolveFresh(missing,null,null,never).first_new.status,'summary_unavailable');
const unbound=rows(W.project(input([task('B','project-1',true,false,null)],[]),{mode:'all'}))[0];
assert.equal(unbound.activity_status,'binding_unavailable');assert.equal(unbound.changed,null);
''')

    def test_newer_summary_and_review_are_projected_without_mutating_old_capture(self):
        self.run_js(r'''
const first=projected('A',11,10),before=JSON.stringify(first);
const later=projected('A',14,11);assert.equal(later.activity_status,'new_activity');assert.equal(later.material_seq,14);assert.equal(later.reviewed_seq,11);
assert.equal(JSON.stringify(first),before);assert.equal(first.reviewed_seq,10);assert.equal(first.material_seq,11);
const complete=projected('A',14,14);assert.equal(complete.changed,false);
const unavailable=rows(W.project(input([task('A')],[{owner:own('A'),status:'unavailable',body:'source text'}],[review('A',11)]),{mode:'all'}))[0];
assert.equal(unavailable.summary_status,'read_failed');assert.equal(unavailable.material_seq,null);assert.equal(unavailable.changed,null);
''')

    def test_resolver_cannot_substitute_an_equal_or_newer_source_identity(self):
        self.run_js(r'''
const row=projected('A'),batch=N.capture(own('A'),[delta(20)]);
const rogue={pending:N.pending,resolveTarget:(owner,target)=>({available:true,status:'available',target:{...target,item_id:'other'}})};
assert.throws(()=>W.resolveFresh(row,batch,source(),rogue),/cannot replace/);
assert.throws(()=>W.resolveFresh(row,batch,{...source(),kind:'cached'},N),/fresh native/);
assert.throws(()=>W.resolveFresh({...row,material_seq:{text:'private body'}},batch,source(),N),/sequence/);
assert.throws(()=>W.resolveFresh({...row,activity_status:'private body'},batch,source(),N),/row metadata/);
''', activity=True)


if __name__ == '__main__':
    unittest.main()
