"""Bounded supplied-task skim uses exact native identities and actual response phase."""
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]

@unittest.skipUnless(shutil.which('node'),'Node is required for task overview source checks')
class TaskOverviewTests(unittest.TestCase):
    def check(self, body):
        script=r"""
const assert=require('assert/strict'),h=require(process.argv[1]);
const forbidden=()=>{throw Error('Task overview cannot fetch or persist');};
globalThis.fetch=forbidden;globalThis.localStorage={getItem:forbidden,setItem:forbidden};
const u=(id,text)=>({id,type:'userMessage',content:[{type:'text',text}]}),a=(id,text,phase)=>({id,type:'agentMessage',text,phase});
const thread={id:'source',turns:Array.from({length:43},(_,i)=>({id:'task-'+i,status:i===33?'failed':'completed',
 items:[u('same-user','Repeated instruction '+i),a('same-answer','Own response '+i,'final_answer'),a('later-comment','Own commentary '+i,'commentary')]}))};
const freeze=value=>{if(value&&typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
"""+body
        result=subprocess.run(['node','-e',script,str(ROOT/'codex_desk/static/history_tasks.js')],capture_output=True,text=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)

    def test_twenty_task_pages_not_item_pages_and_no_mutation(self):
        self.check(r"""
freeze(thread);const before=JSON.stringify(thread),first=h.overview(thread,'source'),second=h.overview(thread,'source',1),last=h.overview(thread,'source',999);
assert.equal(first.entries.length,20);assert.equal(first.total,43);assert.equal(first.pages,3);assert.equal(first.page,0);
assert.equal(second.entries.length,20);assert.equal(second.entries[13].turn_id,'task-33');assert.equal(second.entries[13].ordinal,34);
assert.equal(last.entries.length,3);assert.equal(last.page,2);assert.equal(last.first,40);assert.equal(JSON.stringify(thread),before);
""")

    def test_own_final_wins_over_later_commentary_and_same_ids_elsewhere(self):
        self.check(r"""
thread.turns[33].error={message:'Own native failure'};freeze(thread);
const task=h.overview(thread,'source',1).entries[13];assert.equal(task.turn_status,'failed');assert.deepEqual(task.turn_error,{message:'Own native failure'});
assert.equal(task.instructions[0].text,'Repeated instruction 33');assert.equal(task.response.item_id,'same-answer');
assert.equal(task.response.phase,'final_answer');assert.equal(task.response.preview.text,'Own response 33');assert.equal(task.response.label,'Final answer');
""")

    def test_actual_fallback_phase_empty_instruction_and_turn_only_outcomes(self):
        self.check(r"""
thread.turns[0].items=[a('comment','Own commentary','commentary')];thread.turns[1].items=[a('no-phase','Actual phase absent')];
thread.turns[2]={id:'empty',status:'interrupted',error:{message:'Own interruption'},items:[]};freeze(thread);
const [comment,absent,empty]=h.overview(thread,'source').entries;
assert.equal(comment.user_message_count,0);assert.equal(comment.response.phase,'commentary');assert.equal(comment.response.label,'Commentary');
assert.equal(absent.response.phase,null);assert.equal(absent.response.label,'Last assistant message');assert.equal(absent.response.preview.text,'Actual phase absent');
assert.equal(empty.turn_id,'empty');assert.equal(empty.turn_status,'interrupted');assert.equal(empty.user_message_count,0);
assert.equal(empty.response.available,false);assert.equal(empty.response.status,'response_unavailable');
""")

    def test_unicode_previews_bound_three_instructions_and_do_not_return_full_text(self):
        self.check(r"""
thread.turns[0].items=[...Array.from({length:5},(_,i)=>u('user-'+i,'😀'.repeat(10000)+i)),a('answer','界'.repeat(10000),'final_answer')];freeze(thread);
const row=h.overview(thread,'source').entries[0];assert.equal(row.user_message_count,5);assert.equal(row.instructions.length,3);
for(const preview of [...row.instructions,row.response.preview]){assert.equal(Array.from(preview.text).length,320);assert(preview.truncated);}
assert.equal(row.response.text,undefined);assert.equal(JSON.stringify(row).includes('界'.repeat(321)),false);
""")

    def test_unaddressable_rows_and_ambiguous_response_never_borrow_another(self):
        self.check(r"""
thread.turns[0].items.push(a('same-answer','Ambiguous own response','final_answer'));thread.turns[1].id='duplicate';thread.turns[2].id='duplicate';
thread.turns[3]={status:'failed',items:[]};freeze(thread);const rows=h.overview(thread,'source').entries;
assert.equal(rows[0].response.available,false);assert.equal(rows[0].response.status,'ambiguous_item');
for(const row of rows.slice(1,4)){assert.equal(row.available,false);assert.equal(row.response.available,false);assert.equal(row.user_message_count,null);}
assert.equal(rows[1].reason,'ambiguous_turn');assert.equal(rows[3].reason,'invalid_turn_id');
""")

    def test_wrong_source_invalid_pages_and_empty_original(self):
        self.check(r"""
assert.throws(()=>h.overview(thread,'other'),e=>e.code==='thread_mismatch');
for(const page of [-1,1.2,NaN,Infinity,'1'])assert.throws(()=>h.overview(thread,'source',page),TypeError);
const empty=h.overview({id:'empty',turns:[]},'empty');assert.equal(empty.total,0);assert.equal(empty.pages,1);assert.deepEqual(empty.entries,[]);
""")

if __name__=='__main__':unittest.main()
