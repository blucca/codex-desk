"""Exact supplied task/instruction context and same-turn response selection."""
import copy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from codex_desk.task_response import select_task_response
from examples.build_browser_preview import sample_threads

ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which('node')
HARNESS = r"""
const assert=require('assert/strict'),fs=require('fs');
const forbidden=()=>{throw Error('Pure supplied-history work cannot request or persist');};
globalThis.fetch=globalThis.api=forbidden;
globalThis.localStorage=globalThis.sessionStorage={getItem:forbidden,setItem:forbidden};
const find=require(process.argv[2]);require(process.argv[3]);
const h=require(process.argv[1]),reader=DeskHistoryReader;
const input=JSON.parse(fs.readFileSync(0,'utf8'));
const freeze=value=>{if(value && typeof value==='object'){Object.values(value).forEach(freeze);Object.freeze(value);}return value;};
const thread=freeze(input),before=JSON.stringify(thread);
const capture={thread_id:'parent',turn_id:'selected'};
const clone=value=>JSON.parse(JSON.stringify(value));
"""


def message(item_id, text, phase=None):
    return {'id': item_id, 'type': 'agentMessage', 'text': text, 'phase': phase}


def instruction(item_id, text):
    return {'id': item_id, 'type': 'userMessage', 'content': [{'type': 'text', 'text': text}]}


def supplied():
    return {'id': 'parent', 'turns': [
        {'id': 'earlier', 'status': 'completed', 'items': [
            instruction('prompt', 'Same instruction Café Straße'),
            message('answer', 'Same response text', 'final_answer')]},
        {'id': 'selected', 'status': 'failed', 'error': {'message': 'Actual native failure'}, 'items': [
            instruction('prompt-a', 'Same instruction Cafe\u0301 STRASSE'),
            {'id': 'prompt-b', 'type': 'userMessage', 'content': [
                {'type': 'text', 'text': 'Second supplied instruction'},
                {'type': 'image', 'url': 'retained-native-image'},
                {'type': 'text', 'text': 'Literal a%b_c[0].*'}]},
            {'id': 'tool', 'type': 'commandExecution', 'aggregatedOutput': 'Only tool needle'},
            message('answer', 'Same response text', 'final_answer'),
            message('commentary', 'Only response needle', 'commentary')]},
        {'id': 'later', 'status': 'interrupted', 'items': [
            instruction('prompt', 'Same instruction Café Straße'),
            message('answer', 'Same response text', 'future_phase')]},
        {'id': 'outcome-only', 'status': 'interrupted', 'error': {'message': 'Turn-only outcome'}, 'items': []}]}


@unittest.skipUnless(NODE, 'Node is required for supplied-history task context')
class HistoryTasksTests(unittest.TestCase):
    def check(self, body, thread=None):
        script = HARNESS + '\n' + body + '\nassert.equal(JSON.stringify(thread),before);'
        result = subprocess.run([NODE, '-e', script,
            str(ROOT/'codex_desk/static/history_tasks.js'),
            str(ROOT/'codex_desk/static/history_find.js'),
            str(ROOT/'codex_desk/static/history_reader.js')],
            input=json.dumps(supplied() if thread is None else thread, ensure_ascii=False),
            text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_containing_turn_uses_identity_not_same_text_elsewhere(self):
        self.check(r"""
const task=h.containing(thread,{...capture,item_id:'answer'});
assert.equal(task.turn_id,'selected');assert.equal(task.item_id,'answer');
assert.equal(task.index,1);assert.equal(task.item_index,3);assert(task.available);
assert.equal(task.turn_status,'failed');assert.deepEqual(task.turn_error,{message:'Actual native failure'});
const instructions=h.instructions(thread,task,reader.textForItem);
assert.deepEqual(instructions.items.map(item=>item.item_id),['prompt-a','prompt-b']);
assert.deepEqual(instructions.items.map(item=>item.turn_id),['selected','selected']);
assert.equal(instructions.items[0].text,'User\nSame instruction Cafe\u0301 STRASSE');
assert.equal(instructions.items[1].text,'User\nSecond supplied instruction\nLiteral a%b_c[0].*');
assert.equal(h.response(thread,task).item_id,'answer');assert.equal(h.response(thread,task).turn_status,'failed');
const missing=h.containing(thread,{...capture,item_id:'not-supplied'});
assert.equal(missing.status,'item_unavailable');assert(!missing.available);assert.equal(missing.turn_id,'selected');
""")

    def test_maintained_native_sample_threads_resolve_instruction_and_response(self):
        for thread in sample_threads():
            with self.subTest(thread=thread['id']):
                self.check(r"""
const nativeTurn=thread.turns[0],answer=nativeTurn.items[1],prompt=nativeTurn.items[0];
const task=h.containing(thread,{thread_id:thread.id,turn_id:nativeTurn.id,item_id:answer.id});
assert(task.available);assert.equal(h.list(thread,thread.id).length,1);
const supplied=h.instructions(thread,task,reader.textForItem);
assert.equal(supplied.user_message_count,1);assert.equal(supplied.items[0].item_id,prompt.id);
assert.equal(supplied.items[0].text,reader.textForItem(prompt));assert(supplied.items[0].available);
assert.equal(h.response(thread,task).item_id,answer.id);
assert.equal(h.response(thread,task).selection,answer.phase==='final_answer'?'final_answer':'last_assistant_message');
assert.equal(h.adjacent(thread,task,1),null);assert.equal(h.adjacent(thread,task,-1),null);
""", thread)

    def test_supplied_native_snapshot_with_missing_prompt_does_not_invent_one(self):
        snapshot = json.loads((ROOT/'examples/native-answer-snapshot.json').read_text())['thread']
        self.check(r"""
const task=h.containing(thread,{thread_id:thread.id,turn_id:thread.turns[0].id,item_id:'synthetic-command'});
assert(task.available);const result=h.instructions(thread,task);
assert.equal(result.status,'instruction_unavailable');assert(!result.available);
assert.equal(result.user_message_count,0);assert.deepEqual(result.items,[]);
assert.equal(h.response(thread,task).item_id,'synthetic-answer');
""", snapshot)

    def test_all_user_items_retained_and_nontext_or_blank_prompt_unavailable(self):
        self.check(r"""
const original=clone(thread);original.turns[1].items=[
 {id:'image',type:'userMessage',content:[{type:'image',url:'native-image'}]},
 {id:'blank',type:'userMessage',content:[{type:'text',text:' \n '}]},
 {id:'bad-text',type:'userMessage',content:[{type:'text',text:3}]},
 {id:'absent-content',type:'userMessage'},
 {id:'actual',type:'userMessage',content:[{type:'text',text:'Actual prompt'}]}
];freeze(original);
const result=h.instructions(original,capture,reader.textForItem);
assert.equal(result.user_message_count,5);assert.equal(result.items.length,5);
assert.deepEqual(result.items.map(item=>item.available),[false,false,false,false,true]);
assert(result.items.slice(0,4).every(item=>item.reason==='instruction_unavailable'));
const unavailable=clone(original);unavailable.turns[1].items.pop();freeze(unavailable);
const missing=h.instructions(unavailable,capture,()=> 'Invented readable prompt');
assert.equal(missing.status,'instruction_unavailable');assert(!missing.available);
assert.equal(h.response(unavailable,capture).status,'response_unavailable');
""")

    def test_supplied_turn_order_includes_outcomes_and_invalid_unselectable_rows(self):
        self.check(r"""
const original=clone(thread);original.turns.splice(2,0,null,[],{status:'failed',items:[]});freeze(original);
const rows=h.list(original,'parent');assert.equal(rows.length,5);
assert.deepEqual(rows.map(row=>row.index),[0,1,4,5,6]);
const next=h.adjacent(original,capture,1);assert.equal(next.index,4);
assert.equal(next.turn_id,null);assert(!next.available);assert.equal(next.reason,'invalid_turn_id');
assert.equal(h.adjacent(original,capture,-1).turn_id,'earlier');
const last=rows.at(-1);assert.equal(last.turn_id,'outcome-only');assert.equal(last.turn_status,'interrupted');
assert.deepEqual(last.turn_error,{message:'Turn-only outcome'});assert(last.available);
assert.equal(h.instructions(original,last).status,'instruction_unavailable');
assert.equal(h.response(original,last).status,'response_unavailable');
assert.equal(h.adjacent(original,last,1),null);
assert.throws(()=>h.adjacent(original,capture,0),TypeError);
""")

    def test_missing_or_duplicate_turn_and_item_ids_never_select_another(self):
        self.check(r"""
const absent={...capture,turn_id:'not-supplied'};
assert.equal(h.containing(thread,{...absent,item_id:'answer'}).status,'turn_unavailable');
assert.equal(h.instructions(thread,absent).status,'turn_unavailable');
assert.equal(h.response(thread,absent).status,'turn_unavailable');assert.equal(h.adjacent(thread,absent,1),null);
const duplicated=clone(thread);duplicated.turns.push(clone(duplicated.turns[1]));freeze(duplicated);
assert(h.list(duplicated,'parent').filter(row=>row.turn_id==='selected').every(row=>!row.available && row.reason==='ambiguous_turn'));
for(const read of [()=>h.containing(duplicated,{...capture,item_id:'answer'}),()=>h.instructions(duplicated,capture),
 ()=>h.response(duplicated,capture),()=>h.adjacent(duplicated,capture,1)])assert.throws(read,error=>error.code==='ambiguous_turn');
const items=clone(thread);items.turns[1].items.push({id:'answer',type:'commandExecution'},
 {id:'prompt-a',type:'commandExecution'}, {type:'userMessage',content:[{type:'text',text:'Missing ID'}]});freeze(items);
assert.throws(()=>h.containing(items,{...capture,item_id:'answer'}),error=>error.code==='ambiguous_item');
assert.throws(()=>h.response(items,capture),error=>error.code==='ambiguous_item');
const prompts=h.instructions(items,capture);assert.equal(prompts.user_message_count,3);
assert.equal(prompts.items[0].reason,'ambiguous_item');assert.equal(prompts.items[2].reason,'invalid_item_id');
assert(prompts.items[1].available);assert(!prompts.items[0].available);
const search=h.search(items,'parent','Same instruction');assert(search.matches.every(item=>item.turn_id!=='selected'));
""")

    def test_literal_normalized_instruction_search_never_searches_response_or_tool(self):
        self.check(r"""
const hits=h.search(thread,'parent','café strasse',reader.textForItem);
assert.equal(hits.total,3);assert.deepEqual(hits.matches.map(item=>item.turn_id),['earlier','selected','later']);
assert.deepEqual(hits.matches.map(item=>item.item_id),['prompt','prompt-a','prompt']);
for(const hit of hits.matches){assert.equal(hit.spans.length,1);const span=hit.spans.at(0);
 assert.equal(find.normalize(hit.text.slice(span.start,span.end)),'café strasse');}
const literal=h.search(thread,'parent','a%b_c[0].*');assert.equal(literal.total,1);
assert.equal(literal.matches[0].item_id,'prompt-b');
assert.equal(h.search(thread,'parent','Only tool needle').total,0);
assert.equal(h.search(thread,'parent','Only response needle').total,0);
assert.equal(h.search(thread,'parent','').total,0);
assert.equal(h.search(thread,'parent','absent').total,0);
assert.throws(()=>h.search(thread,'parent',null),TypeError);
""")

    def test_long_unicode_instruction_search_keeps_original_utf16_offsets(self):
        self.check(r"""
const text='🧪 Cafe\u0301 Straße\n'+'項'.repeat(2000000)+'\nＬＡＳＴ Café STRASSE';
const original={id:'unicode',turns:[{id:'long',items:[{id:'prompt',type:'userMessage',content:[{type:'text',text}]}]}]};freeze(original);
const result=h.search(original,'unicode','café strasse');assert.equal(result.total,2);
const item=result.matches[0],spans=Array.from(item.spans);assert.equal(item.text,'User\n'+text);
assert.equal(item.spans.values.data instanceof Uint32Array,true);
assert.equal(spans[0].start,8);assert.equal(item.text.slice(spans[0].start,spans[0].end),'Cafe\u0301 Straße');
assert.equal(item.text.slice(spans[1].start,spans[1].end),'Café STRASSE');
assert(spans[1].start>2000000);assert.equal(original.turns[0].items[0].content[0].text,text);
""")

    def test_default_projection_matches_shipped_reader_and_is_injectable(self):
        self.check(r"""
const defaults=h.instructions(thread,capture),actual=h.instructions(thread,capture,reader.textForItem);
assert.deepEqual(defaults,actual);
const projected=h.instructions(thread,capture,item=>reader.textForItem(item).slice(5));
assert.equal(projected.items[0].text,'Same instruction Cafe\u0301 STRASSE');
assert(projected.items.every(item=>item.available));
assert.throws(()=>h.instructions(thread,capture,3),TypeError);
assert(!h.instructions(thread,capture,()=>null).available);
""")

    def test_malformed_capture_and_original_cannot_fall_back_to_loaded_source(self):
        self.check(r"""
for(const value of ['',null,3,' '.repeat(2),'x'.repeat(201)]) {
 assert.throws(()=>h.list(thread,value),error=>error.code==='invalid_capture');
 assert.throws(()=>h.instructions(thread,{...capture,turn_id:value}),error=>error.code==='invalid_capture');
 assert.throws(()=>h.containing(thread,{...capture,item_id:value}),error=>error.code==='invalid_capture');
}
assert.throws(()=>h.list(thread,'child'),error=>error.code==='thread_mismatch');
for(const original of [null,[],{id:'parent'},{id:'parent',turns:null},{id:'parent',turns:{}}]) {
 assert.throws(()=>h.list(original,'parent'));assert.throws(()=>h.response(original,capture));
}
const unicodeId='🧪'.repeat(200),original={id:unicodeId,turns:[{id:unicodeId,items:[]}]};freeze(original);
assert.equal(h.list(original,unicodeId)[0].turn_id,unicodeId);
""")

    def test_javascript_response_matches_actual_python_selector(self):
        cases = []
        for status in ('completed', 'failed', 'interrupted', 'inProgress', 'future_status', None):
            for phase in ('final_answer', 'commentary', 'partial_answer', 'future_phase', None, 3):
                thread = supplied()
                thread['turns'][1]['status'] = status
                thread['turns'][1]['items'] = [message('chosen', 'Actual response', phase)]
                cases.append(thread)
        for items in (
                [], [message('a', 'Final', 'final_answer'), message('b', 'Later commentary', 'commentary')],
                [message('a', 'Final', 'final_answer'), message('b', 'Last final', 'final_answer')],
                [message('a', 'Legacy'), message('b', 'Last legacy')],
                [message('a', '   ', 'final_answer')], [message('', 'Invalid ID', 'final_answer')],
                [message('x'*201, 'Invalid ID', 'final_answer')], [message('a', None, 'final_answer')],
                [message('same', 'A'), message('same', 'B')],
                [{'id': 'tool', 'type': 'commandExecution', 'aggregatedOutput': 'Not assistant'}],
                [message('a', 'Constructor phase', 'constructor')],
                [message('a', 'Proto phase', '__proto__')]):
            thread = supplied()
            thread['turns'][1]['items'] = items
            cases.append(thread)
        missing = supplied()
        missing['turns'].pop(1)
        cases.append(missing)
        duplicated = supplied()
        duplicated['turns'].append(copy.deepcopy(duplicated['turns'][1]))
        cases.append(duplicated)
        malformed = supplied()
        malformed['turns'][1]['items'] = None
        cases.append(malformed)
        expected = []
        for thread in cases:
            try:
                expected.append({'response': select_task_response(thread, 'parent', 'selected')})
            except ValueError:
                expected.append({'error': True})
        self.check(r"""
const actual=thread.cases.map(original=>{try{return {response:h.response(original,capture)};}catch{return {error:true};}});
assert.deepEqual(actual,thread.expected);
""", {'cases': cases, 'expected': expected})


if __name__ == '__main__':
    unittest.main()
