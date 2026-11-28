"""Loaded-original instruction search uses exact supplied task ownership and returns."""
import importlib.util
from pathlib import Path
import shutil
import subprocess
import unittest

SPEC = importlib.util.spec_from_file_location('task_controller_fixture', Path(__file__).with_name('test_history_task_controller.py'))
base = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(base)
SETUP = base.SETUP.replace("if(taskReview?.mode==='context')renderTaskContext(scroll,value);", "if(taskReview?.mode==='instructions')renderInstructionSearch(scroll,value);else if(taskReview?.mode==='context')renderTaskContext(scroll,value);") + r'''
globalThis.DeskHistoryFind=root.DeskHistoryFind;
const markText=(element,text,start,end)=>{element.textContent=text;element.children=[];if(start>=0 && end>start)element.append(node('mark',text.slice(start,end)));};
const searchField=()=>descendants(el('body')).find(element=>element.tag==='input');
const searchForm=()=>descendants(el('body')).find(element=>element.tag==='form');
const setQuery=query=>{const field=searchField();field.value=query;field.oninput();};
const submitQuery=query=>{setQuery(query);searchForm().onsubmit({preventDefault(){}});};
const matchingButtons=()=>controls().filter(button=>button.dataset.taskAction.startsWith('instruction-match:'));
const readSourceRows=()=>{rows=source.turns.flatMap(turn=>turn.items.length?turn.items.map(item=>({turn,item})):[{turn,item:null}]);};
'''

@unittest.skipUnless(shutil.which('node'), 'Node is required for instruction controller checks')
class InstructionJumpControllerTests(unittest.TestCase):
    def js(self, body):
        result = subprocess.run(['node', '-e', SETUP + base.TASKS + '\n(async()=>{' + body + '})().catch(error=>{console.error(error);process.exitCode=1;});'], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_explicit_submit_literal_unicode_user_text_only_and_exact_own_response(self):
        self.js(r'''
source.turns[1].items[0].content[0].text='Original Café Straße .*[retry] 🌱 supplied wording';
source.turns[0].items.push(answer('response-needle','Café Straße .*[retry]'));
source.turns[2].items.push({id:'tool-needle',type:'commandExecution',command:'Café Straße .*[retry]'});
readSourceRows();openTaskContext(requested);
const originalSearch=root.DeskHistoryTasks.search;let calls=0;root.DeskHistoryTasks.search=(...args)=>{calls++;return originalSearch(...args);};
setQuery('CAFE\u0301 STRASSE .*[retry]');assert.equal(calls,0);searchForm().onsubmit({preventDefault(){}});
assert.equal(calls,1);assert.equal(taskReview.mode,'instructions');assert.equal(matchingButtons().length,1);
assert(contextText().includes('Original Café Straße .*[retry] 🌱 supplied wording'));
matchingButtons()[0].onclick();assert.equal(taskReview.capture.turn_id,'target');assert.equal(taskReview.instructionTarget.item_id,'instruction-1');
assert(el('task-return').hidden);assert(!el('task-instructions-return').hidden);
readTaskItem('instruction','instruction-1');assert.equal(requested.match_text,'Café Straße .*[retry]');
assert.equal(requested.match_start,'User\nOriginal '.length);returnTaskContext();readTaskItem('response');
assert.equal(requested.turn_id,'target');assert.equal(requested.item_id,'answer');assert(taskReview.itemLabel.includes('failed'));
assert(returnInstructionMatches());assert.equal(matchingButtons().length,1);assert.equal(taskReview.instructionSearch.query,'CAFE\u0301 STRASSE .*[retry]');
''')

    def test_bounded_pages_keep_duplicate_item_ids_per_turn_and_exact_result_return(self):
        self.js(r'''
for(let i=0;i<37;i++)source.turns.push({id:'jump-'+i,status:'completed',items:[user('same-instruction','literal remembered task '+i),answer('answer','OWN jump response '+i)]});
readSourceRows();openTaskContext(requested);submitQuery('literal remembered task');
assert.equal(taskReview.instructionSearch.result.matches.length,37);assert.equal(matchingButtons().length,20);
action('instruction-matches-next').onclick();assert.equal(taskReview.instructionSearch.offset,20);assert.equal(matchingButtons().length,17);
const chosen=matchingButtons()[13],before={items:new Map(),anchor:null,scroll:219,outer:101,taskFocus:chosen.dataset.taskAction,page:1};view=before;
chosen.onclick();assert.equal(taskReview.capture.turn_id,'jump-33');assert.equal(taskReview.instructionTarget.item_id,'same-instruction');
readTaskItem('response');assert.equal(requested.turn_id,'jump-33');assert.equal(requested.item_id,'answer');
returnInstructionMatches();assert.equal(taskReview.instructionSearch.offset,20);assert.strictEqual(restored.at(-1).view,before);
assert.equal(searchField().value,'literal remembered task');assert.equal(matchingButtons().length,17);
''')

    def test_reader_role_label_is_not_supplied_user_instruction_text(self):
        self.js(r'''
openTaskContext(requested);submitQuery('User');assert.equal(matchingButtons().length,0);
assert(contextText().includes('No supplied user instruction matches'));
''')

    def test_unaddressable_nontext_and_ambiguous_instruction_rows_never_selected(self):
        self.js(r'''
source.turns.push({id:'ambiguous-turn',items:[user('u','needle')]},{id:'ambiguous-turn',items:[user('v','needle')]});
source.turns[1].items.push(user('duplicate-user','needle'),user('duplicate-user','needle'),user('','needle'),{id:'image-only',type:'userMessage',content:[{type:'image',url:'needle'}]});
readSourceRows();openTaskContext(requested);submitQuery('needle');
assert.equal(matchingButtons().length,0);assert(contextText().includes('No supplied user instruction matches'));
assert.equal(chooseInstructionMatch({thread_id:'A',turn_id:'target',item_id:'duplicate-user'}),false);assert.equal(taskReview.mode,'instructions');
''')

    def test_entered_unsubmitted_query_refresh_uses_only_last_submission(self):
        self.js(r'''
openTaskContext(requested);submitQuery('ACTUAL');setQuery('UNRELATED');
source={...source,turns:[...source.turns,{id:'fresh',items:[user('new-user','ACTUAL fresh instruction'),answer('answer','fresh own response')]}]};readSourceRows();++refreshVersion;
render(false,captureView());assert.equal(searchField().value,'UNRELATED');assert.equal(taskReview.instructionSearch.submitted,'ACTUAL');
assert.equal(matchingButtons().length,3);assert(matchingButtons().every(button=>!button.dataset.taskAction.includes('earlier')));
searchForm().onsubmit({preventDefault(){}});assert.equal(taskReview.instructionSearch.submitted,'UNRELATED');assert.equal(matchingButtons().length,2);
''')

    def test_lost_result_does_not_jump_to_other_turn_same_text(self):
        self.js(r'''
openTaskContext(requested);submitQuery('ACTUAL target');const captured={thread_id:'A',turn_id:'target',item_id:'instruction-1'};
source={...source,turns:source.turns.map(turn=>turn.id==='target'?{...turn,items:turn.items.filter(item=>item.id!=='instruction-1')}:turn)};
source.turns.push({id:'other-same-text',items:[user('instruction-1','ACTUAL target instruction 🌱')]});readSourceRows();
assert.equal(chooseInstructionMatch(captured),false);assert.equal(taskReview.capture.turn_id,'target');assert(contextText().includes('exact supplied instruction no longer matches'));
assert.equal(matchingButtons().length,1);assert(matchingButtons()[0].dataset.taskAction.includes('other-same-text'));
''')

    def test_captured_instruction_span_not_shifted_to_repeated_phrase_after_refresh(self):
        self.js(r'''
source.turns[1].items[0].content[0].text='x'.repeat(45000)+'Café Straße .*[retry] tail';readSourceRows();
openTaskContext(requested);submitQuery('café strasse .*[retry]');matchingButtons()[0].onclick();
readTaskItem('instruction','instruction-1');assert.equal(requested.match_start,45005);assert.equal(requested.match_text,'Café Straße .*[retry]');returnTaskContext();
source.turns[1].items[0].content[0].text='Café Straße .*[retry] shifted';readTaskItem('instruction','instruction-1');
assert.equal(requested.match_text,undefined);assert.equal(requested.match_start,undefined);assert.equal(requested.item_id,'instruction-1');
''')

    def test_stale_form_or_match_cannot_change_new_reader_owner(self):
        self.js(r'''
openTaskContext(requested);const staleForm=searchForm();submitQuery('ACTUAL');const stale=matchingButtons()[0];
const captured=taskReview.capture;live=false;const before=rendered.length;stale.onclick();staleForm.onsubmit({preventDefault(){}});
assert.strictEqual(taskReview.capture,captured);assert.equal(rendered.length,before);assert.equal(returnInstructionMatches(),false);
''')

    def test_search_return_preserves_original_find_window_and_backward_quote(self):
        self.js(r'''
const originalRequested={...requested},originalGroups=findGroups;openTaskContext(requested);submitQuery('ACTUAL');matchingButtons()[0].onclick();
readTaskItem('response');returnInstructionMatches();assert(await returnTaskPassage());
assert.equal(taskReview,null);assert.deepEqual(requested,originalRequested);assert.strictEqual(findGroups,originalGroups);
assert.equal(findCursor,0);assert(findSubmitted);assert.equal(el('find-query').value,'quote');assert.strictEqual(restored.at(-1).view,capturedView);
assert.equal(restored.at(-1).view.selection.backward,true);assert(el('task-instructions-return').hidden);
''')

if __name__=='__main__':unittest.main()
