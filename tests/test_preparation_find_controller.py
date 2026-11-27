"""Literal lookup ownership with held reads and no native/mutation operations."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest

ROOT=Path(__file__).resolve().parents[1]
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
SCRIPT=r'''
const assert=require('assert/strict'),core=require(process.argv[1]);
const clone=v=>JSON.parse(JSON.stringify(v));
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
let current={open:true,q:'retry',cwd:'/b',archived:false,owner:'modal1'},responses=[],states=[],reviewed=[],error=[];
const result=()=>({sessions:[{id:'b',draft:{text:'retry',mode:'plan',revision:2},followups:{entries:[],reservation:null}}],lookup:{q:'retry',offset:0,limit:30,total:1,has_more:false,results:[{session_id:'b',kind:'draft',control:'draft',revision:2,mode:'plan',snippet:'retry',match_text:'retry'}]}});
let handler=async()=>result();
const c=core.create({current:()=>current,api:async path=>{assert(path.startsWith('/api/preparation?'));assert(!path.includes('native'));responses.push(path);return handler(path);},onState:s=>states.push(s),onResults:r=>{},onError:e=>error.push(e.message),reviewMatch:async(hit,owner)=>{reviewed.push({hit,owner});return true;}});
(async()=>{
 const testcase=process.argv[2];
 if(testcase==='exact'){
  assert(await c.search());assert(await c.select(0));assert.equal(reviewed[0].hit.session_id,'b');assert.equal(reviewed[0].hit.revision,2);assert.equal(reviewed[0].hit.mode,'plan');assert(responses[0].includes('cwd=%2Fb'));
 }else if(testcase==='query-switch'){
  const held=deferred();handler=()=>held.promise;const reading=c.search();current={...current,q:'different'};held.resolve(result());assert.equal(await reading,false);assert.equal(await c.select(0),false);assert.equal(reviewed.length,0);
 }else if(testcase==='scope-switch'){
  const held=deferred();handler=()=>held.promise;const reading=c.search();current={...current,cwd:'/a',archived:true};held.resolve(result());assert.equal(await reading,false);assert.equal(await c.select(0),false);
 }else if(testcase==='close-newer'){
  const held=deferred();handler=()=>held.promise;const first=c.search();c.invalidate();current={...current,owner:'modal2'};handler=async()=>result();assert(await c.search());held.resolve(result());assert.equal(await first,false);assert(await c.select(0));assert.equal(reviewed[0].owner.owner.owner,'modal2');
 }else if(testcase==='malformed-owner'){
  handler=async()=>{const r=result();r.lookup.results[0].session_id='other';return r;};assert.equal(await c.search(),false);assert.equal(await c.select(0),false);assert.equal(error.length,1);
 }else if(testcase==='revision'){
  handler=async()=>{const r=result();r.lookup.results[0].revision=1;return r;};assert.equal(await c.search(),false);assert.equal(reviewed.length,0);
 }else if(testcase==='late-selection'){
  await c.search();const held=deferred();const c2=core.create({current:()=>current,api:async()=>result(),reviewMatch:async(hit,owner)=>{await held.promise;assert.equal(owner.valid(),false);return true;}});
  await c2.search();const pending=c2.select(0);current={...current,owner:'different-modal'};held.resolve();assert.equal(await pending,false);
 }else throw Error('Unknown case');
 console.log('PASS');
})().catch(e=>{console.error(e);process.exitCode=1;});
'''

@unittest.skipUnless(NODE,'Node is required for lookup controller tests')
class PreparationFindControllerTests(unittest.TestCase):
    def check(self,case):
        r=subprocess.run([NODE,'-e',SCRIPT,str(ROOT/'codex_desk/static/preparation-find.js'),case],capture_output=True,text=True,timeout=15)
        self.assertEqual(r.returncode,0,r.stdout+r.stderr)
    def test_exact_owner_mode_and_revision(self):self.check('exact')
    def test_held_query_change(self):self.check('query-switch')
    def test_held_project_archive_change(self):self.check('scope-switch')
    def test_closed_reply_cannot_replace_newer_modal(self):self.check('close-newer')
    def test_missing_owner_rejected(self):self.check('malformed-owner')
    def test_old_revision_rejected(self):self.check('revision')
    def test_late_selection_loses_owner_before_activation(self):self.check('late-selection')
