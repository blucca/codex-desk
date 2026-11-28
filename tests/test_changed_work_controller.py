"""Captured quiet-overview ownership: metadata-only until ordinary saved-task navigation."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest
import test_recent_work_controller as fixture

ROOT=Path(__file__).resolve().parents[1]
NODE=shutil.which('node')
HARNESS=fixture.HARNESS[:fixture.HARNESS.index("let selected='a'")]+r'''
globalThis.document=document;
const H='a'.repeat(64),OTHER='b'.repeat(64);
const owner=(session,thread_id='native-'+session,native_home=H)=>({native_home,session,thread_id});
const task=(id,cwd='/one',status='completed',archived=false)=>({id,cwd,status,archived,thread_id:'native-'+id,name:'Saved '+id,profile:'default'});
const material=(session,material_seq,received_seq=material_seq)=>({owner:owner(session),status:'available',material_seq,received_seq});
const review=(session,reviewed_seq)=>({owner:owner(session),reviewed_seq});
const W=require(process.argv[1]);
let selected='A',generation=7,opening=false;
const draft={text:'Exact unsent Plan',mode:'plan',revision:8},queue=['First prepared','Second prepared'];
const state={sessions:[task('A','/one','running'),task('B'),task('C','/two'),task('D','/two','completed',true),task('E','/two','approval',true)],
 native_material:{native_home:H,summaries:[material('A',10,200),material('B',15,220),material('C',40,250),material('D',20,290),material('E',30,300)]}};
let metadata={native_home:H,reviews:[review('A',10),review('B',10),review('D',10),review('E',20)]},callback=null,opens=[],sidebar=0;
const before=JSON.stringify({selected,generation,draft,queue}),calls=[],sourceBefore=JSON.stringify(state);
const groups=()=>{
 const out=new Map();for(const s of state.sessions){if(!out.has(s.cwd))out.set(s.cwd,{cwd:s.cwd,name:s.cwd.slice(1),active:[],recent:[],archived:[]});
 out.get(s.cwd)[active(s)?'active':s.archived?'archived':'recent'].push(s);}return [...out.values()];
};
const active=s=>['starting','running','approval'].includes(s.status);
$('session-filter').value='';$('show-archived').checked=false;
$('changed-work-mode').value='changed';$('changed-work-project').value='';
$('changed-work-list').scrollTop=0;
$('changed-work').append($('changed-work-close'),$('changed-work-mode'),$('changed-work-project'),$('changed-work-list'));
$('changed-work-back').hidden=true;
const make=(tag,text,cls)=>{const node=document.createElement(tag);if(text)node.textContent=text;if(cls)node.className=cls;return node;};
const forbidden=()=>{throw Error('No fetch, native source or storage/review write in overview');};
globalThis.fetch=forbidden;globalThis.localStorage=new Proxy({}, {get:forbidden});
const source=root=>root.children.flatMap(child=>[child,...source(child)]);
const rows=()=>source($('changed-work-list')).filter(node=>node.className==='changed-work-row');
const button=id=>rows().find(node=>node.dataset.session===id)?.children[0];
const ids=()=>rows().map(node=>node.dataset.session);
const text=id=>button(id)?.children[1].textContent;
const quiet=()=>{assert.strictEqual(JSON.stringify({selected,generation,draft,queue}),before);assert.strictEqual(JSON.stringify(state),sourceBefore);assert.strictEqual(calls.length,0);assert.strictEqual(opens.length,0);};
'''


@unittest.skipUnless(NODE,'Node is needed for captured overview ownership')
class ChangedWorkControllerTests(unittest.TestCase):
    def run_js(self,script,setup=''):
        source=HARNESS+'\n'+(ROOT/'codex_desk/static/changed-work-view.js').read_text()+'\n'+setup+r'''
DeskChangedWorkView.configure({$,make,state:()=>state,groups,active,opening:()=>opening,
 reviews:()=>metadata,subscribe:listener=>{callback=listener;return ()=>{callback=null;}},sidebar:()=>{++sidebar;},
 open:async(id,options)=>{opens.push({id,options});selected=id;++generation;}});
(async()=>{
'''+script+"\nprocess.stdout.write(JSON.stringify({passed:true}));\n})().catch(error=>{process.stderr.write(error.stack);process.exit(1);});"
        result=subprocess.run([NODE,'-e',source,str(ROOT/'codex_desk/static/changed-work.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_quiet_dots_only_for_material_not_transport_status_or_unknown(self):
        self.run_js(r'''
for(const [id,expected] of [['A',false],['B',true],['C',false],['E',true]]){
 const node=make('button');DeskChangedWorkView.badge(id,node);assert.equal(node.children.length,Number(expected));
 assert.equal(node.dataset.nativeActivity,{A:'up_to_date',B:'new_activity',C:'baseline_missing',E:'new_activity'}[id]);
}
$('show-changed-work').focus();$('show-changed-work').onclick();
assert.deepEqual(ids(),['E','A','B']);assert($('changed-work-status').textContent.includes('2 changed'));
assert($('changed-work-status').textContent.includes('1 without a review baseline'));
$('changed-work-close').onclick();assert.equal(document.activeElement,$('show-changed-work'));quiet();
''')

    def test_all_saved_work_keeps_unknown_and_unavailable_distinct_without_seed(self):
        self.run_js(r'''
state.sessions.push({...task('F','/two'),thread_id:null});DeskChangedWorkView.sync();
$('show-changed-work').onclick();$('changed-work-mode').value='all';$('changed-work-mode').onchange();
assert.deepEqual(new Set(ids()),new Set(['A','B','C','E','F']));
assert.equal(text('C'),'completed · Review baseline unavailable');assert.equal(text('F'),'completed · Native binding unavailable');
assert(button('F').disabled);assert(!button('C').disabled);
assert.equal(metadata.reviews.length,4);assert.equal(opens.length,0);assert.equal(calls.length,0);
''')

    def test_sidebar_title_archive_scope_keeps_active_and_project_scope_is_stable(self):
        self.run_js(r'''
$('show-changed-work').onclick();$('session-filter').value='not a matching title';DeskChangedWorkView.sync();
assert.deepEqual(ids(),['E','A']);
$('show-archived').checked=true;$('session-filter').value='Saved D';DeskChangedWorkView.sync();assert(ids().includes('D'));assert(ids().includes('E'));assert(ids().includes('A'));
$('changed-work-project').value='1';$('changed-work-project').onchange();assert.deepEqual(ids(),['A']);
state.sessions.reverse();DeskChangedWorkView.sync();assert.deepEqual(ids(),['A']);assert.equal($('changed-work-project').value,'1');
assert.equal(opens.length,0);assert.equal(calls.length,0);
''')

    def test_ordinary_open_keeps_old_anchor_and_exact_overview_row_focus_on_return(self):
        self.run_js(r'''
$('show-changed-work').focus();$('show-changed-work').onclick();const original=button('B');original.focus();$('changed-work-list').scrollTop=57;
await original.onclick();assert.deepEqual(opens,[{id:'B',options:undefined}]);
assert(!$('changed-work').open);assert(!$('changed-work-back').hidden);assert.equal(selected,'B');
assert.deepEqual(draft,{text:'Exact unsent Plan',mode:'plan',revision:8});assert.deepEqual(queue,['First prepared','Second prepared']);
$('changed-work-back').onclick();assert($('changed-work').open);assert.equal(button('B'),original);assert.equal(document.activeElement,original);assert.equal($('changed-work-list').scrollTop,57);
assert.equal(calls.length,0);assert.equal(metadata.reviews.find(row=>row.owner.session==='B').reviewed_seq,10);
''')

    def test_explicit_review_subscription_updates_dot_and_pins_exact_return_row(self):
        self.run_js(r'''
$('show-changed-work').onclick();const original=button('B');original.focus();await original.onclick();
metadata={native_home:H,reviews:metadata.reviews.map(row=>row.owner.session==='B'?review('B',15):row)};callback(metadata);
assert.equal(sidebar,1);const badge=make('button');DeskChangedWorkView.badge('B',badge);assert.equal(badge.children.length,0);
$('changed-work-back').onclick();assert.equal(button('B'),original);assert.equal(document.activeElement,original);
assert.equal(text('B'),'completed · No new recorded material');assert.equal(opens.length,1);assert.equal(calls.length,0);
''')

    def test_return_row_does_not_escape_a_new_explicit_project_title_archive_scope(self):
        self.run_js(r'''
$('show-changed-work').onclick();const original=button('B');await original.onclick();
metadata={native_home:H,reviews:metadata.reviews.map(row=>row.owner.session==='B'?review('B',15):row)};callback(metadata);
$('changed-work-back').onclick();assert(button('B'));
$('changed-work-project').value='2';$('changed-work-project').onchange();assert(!button('B'));assert(button('E'));
$('changed-work-project').value='';$('changed-work-project').onchange();$('session-filter').value='Saved E';DeskChangedWorkView.sync();assert(!button('B'));
assert.equal(opens.length,1);assert.equal(calls.length,0);
''')

    def test_poll_updates_preserve_live_row_focus_without_writing_review_or_owner(self):
        self.run_js(r'''
$('show-changed-work').onclick();const original=button('B');original.focus();$('changed-work-list').scrollTop=33;
state.native_material.summaries=state.native_material.summaries.map(row=>row.owner.session==='B'?material('B',25,400):row);DeskChangedWorkView.sync();
assert.equal(button('B'),original);assert.equal(document.activeElement,original);assert.equal($('changed-work-list').scrollTop,33);
assert.equal(metadata.reviews.find(row=>row.owner.session==='B').reviewed_seq,10);assert.equal(opens.length,0);assert.equal(calls.length,0);
''')

    def test_cold_missing_bridge_is_baseline_unknown_not_false_up_to_date(self):
        self.run_js(r'''
metadata={native_home:null,reviews:[]};DeskChangedWorkView.sync();$('show-changed-work').onclick();
assert.equal($('changed-work-status').textContent,'0 changed · 4 without a review baseline · 0 unavailable');
const node=make('button');DeskChangedWorkView.badge('B',node);assert.equal(node.dataset.nativeActivity,'baseline_missing');assert.equal(node.children.length,0);
$('changed-work-mode').value='all';$('changed-work-mode').onchange();assert.equal(text('B'),'completed · Review baseline unavailable');assert.equal(opens.length,0);assert.equal(calls.length,0);
''')

    def test_changed_home_or_thread_does_not_borrow_review_or_allow_stale_row_open(self):
        self.run_js(r'''
$('show-changed-work').onclick();const stale=button('B');
state.sessions.find(row=>row.id==='B').thread_id='replacement-B';
state.native_material.summaries=state.native_material.summaries.map(row=>row.owner.session==='B'?{...material('B',30),owner:owner('B','replacement-B')}:row);
DeskChangedWorkView.sync();assert.equal(await stale.onclick(),false);assert.equal(opens.length,0);
$('changed-work-mode').value='all';$('changed-work-mode').onchange();assert.equal(text('B'),'completed · Review baseline unavailable');
state.native_material={native_home:OTHER,summaries:state.native_material.summaries.map(row=>({...row,owner:{...row.owner,native_home:OTHER}}))};DeskChangedWorkView.sync();
assert.equal(text('A'),'running · Review baseline unavailable');assert.equal(calls.length,0);
''')

    def test_missing_compact_metadata_does_not_fabricate_no_changes(self):
        self.run_js(r'''
state.native_material=null;DeskChangedWorkView.sync();$('show-changed-work').onclick();assert.deepEqual(ids(),[]);
assert.equal($('changed-work-status').textContent,'Compact native material metadata is unavailable.');
const node=make('button');DeskChangedWorkView.badge('B',node);assert.equal(node.dataset.nativeActivity,'summary_unavailable');assert.equal(node.children.length,0);
assert.equal(opens.length,0);assert.equal(calls.length,0);
''')

    def test_reviewed_sole_last_page_row_keeps_exact_return_focus_without_escaping_explicit_page_change(self):
        self.run_js(r'''
state.sessions=Array.from({length:31},(_,i)=>task('task-'+i,'/one'));
state.native_material.summaries=state.sessions.map((row,i)=>material(row.id,200+i));metadata={native_home:H,reviews:state.sessions.map(row=>review(row.id,100))};DeskChangedWorkView.sync();
$('show-changed-work').onclick();$('changed-work-next').onclick();assert.deepEqual(ids(),['task-0']);
const original=button('task-0');original.focus();await original.onclick();
metadata={native_home:H,reviews:metadata.reviews.map(row=>row.owner.session==='task-0'?review('task-0',200):row)};callback(metadata);
$('changed-work-back').onclick();assert.deepEqual(ids(),['task-0']);assert.equal(button('task-0'),original);assert.equal(document.activeElement,original);
assert.equal(text('task-0'),'completed · No new recorded material');assert($('changed-work-status').textContent.includes('30 changed'));
$('changed-work-previous').onclick();assert.equal(ids().length,30);assert(!button('task-0'));assert.equal(opens.length,1);assert.equal(calls.length,0);
''')

    def test_bounded_pages_have_no_duplicates_and_navigation_does_not_fetch_bodies(self):
        self.run_js(r'''
state.sessions=Array.from({length:83},(_,i)=>task('task-'+i,'/group-'+i%3));
state.native_material.summaries=state.sessions.map((row,i)=>material(row.id,200+i));metadata={native_home:H,reviews:state.sessions.map(row=>review(row.id,100))};DeskChangedWorkView.sync();
$('show-changed-work').onclick();const first=ids();assert.equal(first.length,30);assert(!$('changed-work-next').disabled);
$('changed-work-next').onclick();const second=ids();assert.equal(second.length,30);
$('changed-work-next').onclick();const third=ids();assert.equal(third.length,23);assert($('changed-work-next').disabled);
assert.equal(new Set([...first,...second,...third]).size,83);assert.equal(opens.length,0);assert.equal(calls.length,0);
$('changed-work-previous').onclick();assert.deepEqual(ids(),second);
''')


if __name__=='__main__':unittest.main()
