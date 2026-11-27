"""Captured native response UI ownership without admission side effects."""
import json, pathlib, shutil, subprocess, unittest
ROOT=pathlib.Path(__file__).resolve().parents[1]
SOURCE=(ROOT/'codex_desk/static/app.js').read_text()
FRAGMENT=SOURCE[SOURCE.index('let selectedOriginalReview=null;'):SOURCE.index('function draw() {')]
SETUP="\nconst assert=require('assert/strict');let selected='session',generation=2,opening=false;\nlet state={sessions:[{id:'session',thread_id:'parent',cwd:'/project'},{id:'other',thread_id:'other-parent',cwd:'/other'}],native_outcomes:{session:{thread_id:'parent',turn_id:'captured',status:'failed'}}};\nconst elements=new Map();function $(id){if(!elements.has(id))elements.set(id,{hidden:false,disabled:false,open:false,isConnected:true,focus(o){this.focused=o;}});return elements.get(id);}\nlet captured=[],release=null,closeCalls=0;\nconst DeskHistoryReader={async show(target,callbacks){captured.push({target,callbacks});$('history-reader').open=true;return await new Promise(resolve=>{release=()=>{if(!callbacks.valid()){$('history-reader').open=false;callbacks.onReturn();resolve(false);}else resolve(true);};});},close(){++closeCalls;$('history-reader').open=false;captured.at(-1)?.callbacks.onReturn();}};\n"
@unittest.skipUnless(shutil.which('node'),'Node required')
class TaskResponseControllerTests(unittest.TestCase):
 def run_js(self,body):
  r=subprocess.run(['node','-e',SETUP+FRAGMENT+'\n(async()=>{'+body+'})().catch(e=>{console.error(e);process.exitCode=1;});'],capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stdout+r.stderr)
 def test_captures_displayed_parent_turn_and_single_pending(self):
  self.run_js("const p=readSelectedOriginal({taskResponse:true,returnFocus:$('read-task-response')});assert.deepEqual(captured[0].target,{thread_id:'parent',cwd:'/project',turn_id:'captured'});assert(captured[0].callbacks.taskResponse);assert.equal(await readSelectedOriginal({taskResponse:true}),false);assert.equal(captured.length,1);release();assert(await p);")
 def test_newer_parent_turn_does_not_retarget_capture(self):
  self.run_js("const p=readSelectedOriginal({taskResponse:true});state.native_outcomes.session.turn_id='new-turn';assert(captured[0].callbacks.valid());release();assert(await p);assert.equal(captured[0].target.turn_id,'captured');")
 def test_switch_suppresses_held_response(self):
  self.run_js("const p=readSelectedOriginal({taskResponse:true});selected='other';++generation;syncSelectedOriginal();assert.equal(closeCalls,1);release();assert.equal(await p,false);assert.equal(selectedOriginalReview,null);")
 def test_changed_parent_suppresses_held_response(self):
  self.run_js("const p=readSelectedOriginal({taskResponse:true});state.sessions[0].thread_id='replacement';syncSelectedOriginal();release();assert.equal(await p,false);")
 def test_generation_change_same_session_invalidates(self):
  self.run_js("const p=readSelectedOriginal({taskResponse:true});++generation;syncSelectedOriginal();release();assert.equal(await p,false);")
 def test_opening_or_missing_or_foreign_outcome_has_no_read(self):
  self.run_js("opening=true;assert.equal(await readSelectedOriginal({taskResponse:true}),false);opening=false;delete state.native_outcomes.session;assert.equal(await readSelectedOriginal({taskResponse:true}),false);state.native_outcomes.session={thread_id:'child',turn_id:'captured'};assert.equal(await readSelectedOriginal({taskResponse:true}),false);assert.equal(captured.length,0);")
 def test_blank_and_oversize_turn_has_no_read(self):
  self.run_js("for(const turn of ['', ' ', 'x'.repeat(201),null]){state.native_outcomes.session.turn_id=turn;assert.equal(await readSelectedOriginal({taskResponse:true}),false);}assert.equal(captured.length,0);")
 def test_owned_return_restores_button_focus_without_scroll(self):
  self.run_js("const button=$('read-task-response'),p=readSelectedOriginal({taskResponse:true,returnFocus:button});release();assert(await p);$('history-reader').open=false;captured[0].callbacks.onReturn();assert.deepEqual(button.focused,{preventScroll:true});assert.equal(selectedOriginalReview,null);assert.equal(button.disabled,false);")
 def test_unowned_return_does_not_steal_focus(self):
  self.run_js("const button=$('read-task-response'),p=readSelectedOriginal({taskResponse:true,returnFocus:button});selected='other';++generation;$('history-reader').open=false;captured[0].callbacks.onReturn();release();assert.equal(await p,false);assert.equal(button.focused,undefined);")
 def test_original_read_keeps_original_mode(self):
  self.run_js("const p=readSelectedOriginal();assert.deepEqual(captured[0].target,{thread_id:'parent',cwd:'/project'});assert.equal(captured[0].callbacks.taskResponse,false);release();assert(await p);")
