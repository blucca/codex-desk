"""Actual app event/open/Latest bindings for independently reviewed native activity."""
import json
import subprocess
import unittest
from pathlib import Path

from test_session_reading_controller import SETUP

ROOT = Path(__file__).resolve().parents[1]


class NewActivityController(unittest.TestCase):
    def check(self, body):
        app = (ROOT/'codex_desk/static/app.js').read_text()
        setup = SETUP.replace('HELPER', json.dumps(str(ROOT/'codex_desk/static/reading_checkpoint.js')))
        setup += r'''
Element.prototype.scrollIntoView=function(){window.scrollTo({top:positions[this.dataset.itemId] || 0});};
const N=require(NEW_HELPER);require(NEW_VIEW);
const nativeOwner={native_home:'a'.repeat(64),session:'A',thread_id:'native-A'};
let statePollAt=Date.now();
const reviewed=()=>JSON.parse(stored.get(N.STORAGE_KEY)).reviews.find(row=>row.owner.session==='A').reviewed_seq;
const update=(seq,item='toolA',method='item/commandExecution/outputDelta',extra={})=>({seq,event:{method,
 params:{threadId:'native-A',turnId:'turn-A',itemId:item,delta:'New native evidence',...extra}}});
async function deliver(...rows){for(const row of rows){after=row.seq;consume(row.event);}await DeskNewActivityView.observe(rows);}
'''.replace('NEW_HELPER', json.dumps(str(ROOT/'codex_desk/static/new-activity.js'))).replace(
            'NEW_VIEW', json.dumps(str(ROOT/'codex_desk/static/new-activity-view.js')))
        setup += 'function scheduleDraft(){};const DeskEvidencePreparation={sync(){}};\n'
        fragments = [(ROOT/'codex_desk/static/evidence.js').read_text(),
                     (ROOT/'codex_desk/static/activity.js').read_text(),
                     (ROOT/'codex_desk/static/native-steps.js').read_text(),
                     (ROOT/'codex_desk/static/turn-changes.js').read_text(),
                     'DeskNativeSteps.configure({$,make});DeskTurnChanges.configure({$,writeText:()=>{}});',
                     app[app.index('const sessionReadingViews='):app.index('async function api(')],
                     app[app.index('function itemText(i) {'):app.index('let approvalsSignature=')],
                     app[app.index('function consume(m) {'):app.index('async function refresh() {')],
                     app[app.index('let ordinaryTurnSource='):app.index('function drawOrdinaryRequestSources(')],
                     app[app.index('async function open('):app.index('function profileInfo()')],
                     app[app.index('async function pollActivity()'):app.index('async function tick()')],
                     next(line for line in app.splitlines() if line.startswith("$('prompt').oninput="))]
        script = setup + '\n' + '\n'.join(fragments) + '\n(async()=>{' + body + r'''
assert.equal(JSON.stringify(preparation),before);
assert.equal($('prompt').value,drafts.get(selected));
assert(apiCalls.every(call=>call.path==='/api/open'||call.path.startsWith('/api/events?')||call.path==='/api/native/home'));
})().catch(error=>{console.error(error.stack);process.exitCode=1;});
'''
        result = subprocess.run(['node', '-e', script], capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_first_open_seeds_then_earlier_changed_command_is_exact_without_review(self):
        self.check(r'''
await open('A');flush();assert.equal(reviewed(),4);assert($('native-activity-first').disabled);
readA();await deliver(update(5),update(6,'answerA','item/agentMessage/delta'));
assert.equal(DeskNewActivityView.snapshot().batch.updates[0].item_id,'toolA');
$('native-activity-first').onclick();assert.equal(document.activeElement.dataset.itemId,'toolA');
assert.equal(window.scrollY,positions.toolA);assert.equal(reviewed(),4);
assert(nodes.get('toolA').querySelector('.activity-tool').open);assert(!DeskSessionReading.follow());
''')

    def test_mark_displayed_only_and_later_activity_remains_new(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));$('native-activity-mark').onclick();assert.equal(reviewed(),5);
await deliver(update(6));assert.equal(DeskNewActivityView.snapshot().batch.updates[0].seq,6);
assert($('native-activity-status').textContent.includes('New native activity'));
''')

    def test_explicit_latest_freezes_current_frontier_before_later_delivery(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));$('latest-output').onclick();
await deliver(update(6));flush();assert.equal(reviewed(),5);
assert.equal(DeskNewActivityView.snapshot().batch.updates[0].seq,6);
''')

    def test_actual_automatic_poll_follow_cannot_cancel_queued_explicit_review(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));
const previous=transport;transport=async(path,body)=>path.startsWith('/api/events?')?[update(6)]:previous(path,body);
await pollActivity();$('latest-output').onclick();flush();assert.equal(reviewed(),6);
await deliver(update(7));assert.equal(DeskNewActivityView.state().first.first_seq,7);
''')

    def test_automatic_latest_and_manual_reading_do_not_review(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));goLatest();flush();assert.equal(reviewed(),4);
$('latest-output').onclick();inputListeners.wheel.forEach(fn=>fn());window.scrollTo({top:350});
flush();assert.equal(reviewed(),4);assert($('native-activity-status').textContent.includes('New native activity'));
''')

    def test_late_latest_review_cannot_affect_new_owner(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));$('latest-output').onclick();await open('C');flush();
assert.equal(selected,'C');assert.equal(reviewed(),4);assert.equal(document.activeElement.dataset.itemId,undefined);
''')

    def test_replay_cannot_resurrect_missing_fresh_native_item_or_mark_it(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));await open('B');flush();
originals.A.turns[0].items=originals.A.turns[0].items.filter(item=>item.id!=='toolA');
const previous=transport;transport=async(path,body)=>path.startsWith('/api/events?session=A')?[...eventRows('A'),update(5)]:previous(path,body);
await open('A');flush();assert(nodes.has('toolA'));assert.equal(reviewed(),4);
assert.equal(DeskNewActivityView.readFirst(),false);assert($('native-activity-status').textContent.includes('item_unavailable'));
$('native-activity-mark').onclick();assert.equal(reviewed(),4);
''')

    def test_stale_plan_delta_is_received_but_not_a_rendered_frontier(self):
        self.check(r'''
await open('A');flush();await deliver(update(5),update(6,'old-plan','item/plan/delta'));
assert(!items.has('old-plan'));assert.equal(DeskNewActivityView.snapshot().batch.frontier,5);
assert.equal(DeskNewActivityView.state().received_seq,6);
renderItem({id:'final-plan',type:'plan',text:'Final plan',_deskPlan:'complete'},'turn-A');
await deliver(update(7,'final-plan','item/plan/delta'));assert.equal(items.get('final-plan').text,'Final plan');
assert.equal(DeskNewActivityView.state().frontier,5);
$('native-activity-mark').onclick();assert.equal(reviewed(),5);
''')

    def test_changed_home_binding_and_native_snapshots_stay_separate(self):
        self.check(r'''
await open('A');flush();await deliver(update(5,'toolA','desk/nativeTaskSnapshot'));
assert($('native-activity-first').disabled);assert.equal(reviewed(),4);
await deliver(update(6,'toolA','item/commandExecution/outputDelta',{threadId:'child'}));
assert($('native-activity-first').disabled);assert.equal(reviewed(),4);
''')

    def test_review_metadata_is_detached_read_only_and_notifies_only_boundary_changes(self):
        self.check(r'''
assert.deepEqual(DeskNewActivityView.reviewMetadata(),{native_home:null,reviews:[]});
assert.equal(stored.get(N.STORAGE_KEY),undefined);
const changes=[],unsubscribe=DeskNewActivityView.subscribe(metadata=>changes.push(metadata));
await open('A');flush();assert.equal(changes.length,1);assert.equal(changes[0].reviews[0].reviewed_seq,4);
const raw=stored.get(N.STORAGE_KEY),metadata=DeskNewActivityView.reviewMetadata();
metadata.reviews[0].owner.session='not-A';metadata.reviews[0].reviewed_seq=999;
assert.equal(stored.get(N.STORAGE_KEY),raw);assert.equal(DeskNewActivityView.reviewMetadata().reviews[0].owner.session,'A');
await deliver(update(5));DeskNewActivityView.readFirst();goLatest({readingIntent:false});flush();
assert.equal(changes.length,1);assert.equal(reviewed(),4);
$('native-activity-mark').onclick();assert.equal(changes.length,2);assert.equal(changes[1].reviews[0].reviewed_seq,5);
await deliver(update(6));unsubscribe();$('native-activity-mark').onclick();assert.equal(changes.length,2);assert.equal(reviewed(),6);
''')

    def test_home_review_wait_does_not_delay_capture_of_new_reading_intent(self):
        self.check(r'''
const home=deferred(),previous=transport;
transport=async(path,body)=>path==='/api/native/home'?home.promise:previous(path,body);
const loading=open('C');for(let i=0;i<40;i++)await Promise.resolve();
assert.equal(opening,false);assert.equal(selected,'C');assert(sessionReadingPending);
inputListeners.wheel.forEach(fn=>fn());window.scrollTo({top:77});const intent=DeskSessionReading.intent();
home.resolve({home_namespace:homeNamespace});await loading;flush();
assert.equal(selected,'C');assert.equal(nativeThreadId,'native-C');assert.equal(window.scrollY,77);
assert.equal(DeskSessionReading.intent(),intent);
''')

    def test_new_editor_input_cancels_namespace_delayed_reading_restore(self):
        self.check(r'''
const home=deferred(),previous=transport;
transport=async(path,body)=>path==='/api/native/home'?home.promise:previous(path,body);
const loading=open('C');for(let i=0;i<40;i++)await Promise.resolve();assert(sessionReadingPending);
window.scrollTo({top:77});$('prompt').oninput();assert(!sessionReadingPending);const intent=DeskSessionReading.intent();
home.resolve({home_namespace:homeNamespace});await loading;flush();
assert.equal(selected,'C');assert.equal(nativeThreadId,'native-C');assert.equal(window.scrollY,77);
assert.equal(DeskSessionReading.intent(),intent);
''')

    def test_new_editor_input_cancels_frozen_human_latest_without_marking_or_follow_change(self):
        self.check(r'''
await open('A');flush();await deliver(update(5));$('latest-output').onclick();
const intent=DeskSessionReading.intent(),follow=DeskSessionReading.follow();$('prompt').oninput();
assert(DeskSessionReading.intent()>intent);assert.equal(DeskSessionReading.follow(),follow);
flush();assert.equal(reviewed(),4);assert.equal(DeskNewActivityView.state().first.first_seq,5);
''')

    def test_failed_native_home_never_reports_activity_reviewed(self):
        self.check(r'''
const previous=transport;transport=async(path,body)=>path==='/api/native/home'?{home_namespace:null}:previous(path,body);
await open('A');flush();assert.equal(stored.get(N.STORAGE_KEY),undefined);
assert($('native-activity-first').disabled);assert($('native-activity-mark').disabled);
assert($('native-activity-status').textContent.includes('Native home unavailable'));
assert(!$('native-activity-status').textContent.includes('No new recorded'));
assert.equal(DeskNewActivityView.state().status,'baseline_missing');
''')


if __name__ == '__main__':
    unittest.main()
