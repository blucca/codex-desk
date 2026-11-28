"""Actual reader overview actions preserve exact task and original return ownership."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import unittest

SPEC=importlib.util.spec_from_file_location('task_overview_fixture',Path(__file__).with_name('test_history_task_controller.py'))
base=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(base)
SETUP=base.SETUP.replace("if(taskReview?.mode==='context')renderTaskContext(scroll,value);", "if(taskReview?.mode==='overview')renderTaskOverview(scroll,value);else if(taskReview?.mode==='context')renderTaskContext(scroll,value);")+r"""
const appendTasks=()=>{for(let i=0;i<37;i++)source.turns.push({id:'skim-'+i,status:'completed',items:[user('same-user','Repeated skim instruction '+i),answer('answer','OWN skim response '+i)]});
 rows=source.turns.flatMap(turn=>turn.items.length?turn.items.map(item=>({turn,item})):[{turn,item:null}]);};
"""

@unittest.skipUnless(shutil.which('node'),'Node is required for task overview controller checks')
class TaskOverviewControllerTests(unittest.TestCase):
    def js(self,body):
        result=subprocess.run(['node','-e',SETUP+base.TASKS+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_passage_to_exact_response_same_overview_page_focus_and_original_return(self):
        self.js(r"""
appendTasks();const original={...requested},originalGroups=findGroups;assert(showTaskOverview());assert.equal(taskReview.mode,'overview');
assert.equal(controls().filter(b=>b.dataset.taskAction.startsWith('overview-context:')).length,20);action('overview-next').onclick();
const chosen=action('overview-response:skim-28'),overviewView={items:new Map(),anchor:null,scroll:219,outer:101,taskFocus:chosen.dataset.taskAction,page:1};view=overviewView;
chosen.onclick();assert.equal(requested.turn_id,'skim-28');assert.equal(requested.item_id,'answer');assert.equal(taskReview.mode,'item');
assert(showTaskOverview());assert.equal(taskReview.overview.page,1);assert.strictEqual(restored.at(-1).view,overviewView);
assert(await returnTaskPassage());assert.equal(taskReview,null);assert.deepEqual(requested,original);assert.strictEqual(findGroups,originalGroups);
assert.strictEqual(restored.at(-1).view,capturedView);assert(restored.at(-1).view.selection.backward);
""")

    def test_own_status_phase_and_empty_outcome_row_exact_context(self):
        self.js(r"""
assert(showTaskOverview());assert(contextText().includes('native task failed exactly'));assert(contextText().includes('Final answer · Phase: final_answer'));
assert(contextText().includes('Partial answer · Phase: partial_answer'));assert(contextText().includes('empty task interrupted'));
assert(action('overview-response:empty').disabled);action('overview-context:empty').onclick();assert.equal(taskReview.capture.turn_id,'empty');
assert(contextText().includes('empty task interrupted'));assert(!contextText().includes('UNRELATED earlier answer'));assert(showTaskOverview());
""")

    def test_stale_page_source_and_closed_owner_actions_never_navigate(self):
        self.js(r"""
appendTasks();showTaskOverview();const stale=action('overview-response:target');action('overview-next').onclick();const before={...requested};stale.onclick();assert.deepEqual(requested,before);
const oldSourceAction=action('overview-response:skim-28');source={...source,turns:[...source.turns]};oldSourceAction.onclick();assert.deepEqual(requested,before);
renderTaskOverview();const closed=action('overview-context:skim-28');live=false;closed.onclick();assert.deepEqual(requested,before);assert.equal(showTaskOverview(),false);
""")

    def test_fresh_source_missing_selected_turn_keeps_identity_and_overview_notice(self):
        self.js(r"""
appendTasks();showTaskOverview();action('overview-next').onclick();action('overview-response:skim-28').onclick();const captured={...taskReview.capture};
source={...source,turns:source.turns.filter(turn=>turn.id!=='skim-28')};rows=source.turns.flatMap(turn=>turn.items.length?turn.items.map(item=>({turn,item})):[{turn,item:null}]);
assert(showTaskOverview());assert(contextText().includes('previously selected from this overview is no longer available'));assert.deepEqual(taskReview.capture,captured);
assert.equal(requested.turn_id,'skim-28');assert.equal(requested.item_id,'answer');
""")

if __name__=='__main__':unittest.main()
