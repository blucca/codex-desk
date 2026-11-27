"""First-use index context uses global coverage and the existing explicit action."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest


NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
SOURCE = Path(__file__).resolve().parents[1] / 'codex_desk/static/recall.js'
HARNESS = r"""
const fs=require('fs'),vm=require('vm');
const scenario=JSON.parse(process.argv[2]);
class Element {
  constructor(id=''){this.id=id;this.children=[];this.parentElement=null;this.textContent='';this.value='';this.hidden=false;
    this.checked=false;this.disabled=false;this.open=false;this.classes=new Set();
    this.classList={toggle:(name,on)=>on?this.classes.add(name):this.classes.delete(name)};}
  prepend(child){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(n=>n!==child);
    this.children.unshift(child);child.parentElement=this;}
  replaceChildren(...children){this.children=children;for(const child of children)child.parentElement=this;}
  setAttribute(){}
  addEventListener(){}
  querySelectorAll(){return [];}
  contains(){return false;}
  focus(){document.activeElement=this;}
  showModal(){this.open=true;}
}
const elements=new Map();
function element(id){if(!elements.has(id))elements.set(id,new Element(id));return elements.get(id);}
global.document={getElementById:element,createElement:()=>new Element(),activeElement:null};
element('recall-index-actions').prepend(element('recall-index'));
global.setTimeout=()=>1;global.clearTimeout=()=>{};
let status=scenario.status||'idle',threads=scenario.threads||0,failGet=!!scenario.failGet,projects=scenario.projects;
const requests=[];
const api=async(path,data)=>{
  requests.push({path,method:data?'POST':'GET'});
  if(path==='/api/history/index'){
    if(failGet && !data)throw new Error('Controlled unavailable index status');
    if(data){status='completed';if(scenario.refreshedProjects)projects=scenario.refreshedProjects;return {status,seen:0,indexed:0,failed:0,limit:200};}
    return {job:{status,seen:0,indexed:0,failed:0,limit:200},coverage:{indexed_threads:threads,indexed_items:0},projects};
  }
  if(path.startsWith('/api/recall?'))return {results:[],total:0,coverage:{native:{indexed_threads:0,indexed_items:0}}};
  throw new Error('Unexpected request '+path);
};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8')+'\nglobalThis.recall=DeskRecall;');
element('recall-project').value=scenario.scope||'';
recall.configure({api,state:()=>({sessions:[]}),make:()=>new Element(),selected:()=>null,generation:()=>0});
const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const snapshot=()=>({parent:element('recall-index').parentElement.id,disabled:element('recall-index').disabled,
  primary:element('recall-index').classes.has('recall-index-primary'),summary:element('recall-summary').textContent,
  indexStatus:element('recall-index-status').textContent,error:element('recall-index-error').hidden?null:element('recall-index-error').textContent,
  retryVisible:!element('recall-index-retry').hidden,query:element('recall-query').value,scope:element('recall-project').value,
  projects:element('recall-project').children.map(n=>n.value),requests:requests.map(r=>({...r}))});
(async()=>{
  element('home-content').onclick();await settle();const initial=snapshot();
  element('recall-query').value='retry budget';element('recall-query').oninput();
  element('recall-form').onsubmit({preventDefault(){}});await settle();
  const before=snapshot();
  if(scenario.scan){element('recall-index').onclick();await settle();}
  if(scenario.recover){failGet=false;element('recall-index-retry').onclick();await settle();}
  process.stdout.write(JSON.stringify({initial,before,after:snapshot()}));
})().catch(e=>{process.stderr.write(e.stack);process.exitCode=1;});
"""


@unittest.skipUnless(NODE, 'Node is needed for browser controller units')
class RecallFirstUseTests(unittest.TestCase):
    def run_context(self, **scenario):
        result = subprocess.run([NODE, '-e', HARNESS, str(SOURCE), json.dumps(scenario)],
                                capture_output=True, text=True, check=True, timeout=10)
        return json.loads(result.stdout)

    def test_fresh_cache_promotes_one_existing_explicit_action_and_completed_empty_scan_is_truthful(self):
        result = self.run_context(scan=True)
        before, after = result['before'], result['after']
        self.assertEqual(before['parent'], 'recall-actions')
        self.assertTrue(before['primary'])
        self.assertFalse(before['disabled'])
        self.assertIn('not indexed yet', before['summary'])
        self.assertFalse(any(r['method'] == 'POST' for r in before['requests']))
        self.assertEqual(after['parent'], 'recall-index-actions')
        self.assertFalse(after['primary'])
        self.assertIn('No saved content matches', after['summary'])
        self.assertNotIn('not indexed yet', after['summary'])
        self.assertEqual(after['query'], 'retry budget')
        self.assertEqual(sum(r['method'] == 'POST' for r in after['requests']), 1)
        self.assertEqual(sum(r['path'].startswith('/api/recall?') for r in after['requests']), 2)

    def test_scoped_zero_coverage_does_not_promote_a_populated_global_index(self):
        before = self.run_context(threads=3)['before']
        self.assertEqual(before['parent'], 'recall-index-actions')
        self.assertIn('No saved content matches', before['summary'])
        self.assertNotIn('not indexed yet', before['summary'])
        self.assertFalse(any(r['method'] == 'POST' for r in before['requests']))

    def test_cached_projects_are_available_before_query_and_refresh_preserves_exact_saved_scope(self):
        result = self.run_context(threads=3, projects=['/missing/alpha', '/missing/beta'],
                                  scope='/missing/alpha', refreshedProjects=['/missing/beta', '/missing/gamma'], scan=True)
        self.assertEqual(result['initial']['projects'], ['', '/missing/alpha', '/missing/beta'])
        self.assertFalse(any(r['path'].startswith('/api/recall?') for r in result['initial']['requests']))
        self.assertEqual(result['after']['projects'], ['', '/missing/beta', '/missing/gamma', '/missing/alpha'])
        self.assertEqual(result['after']['scope'], '/missing/alpha')
        self.assertNotIn('not indexed yet', result['before']['summary'])

    def test_empty_project_metadata_does_not_turn_nonempty_global_index_into_first_use(self):
        result = self.run_context(threads=3, projects=[], scope='/missing/saved-project')
        self.assertEqual(result['initial']['projects'], ['', '/missing/saved-project'])
        self.assertEqual(result['before']['parent'], 'recall-index-actions')
        self.assertFalse(result['before']['primary'])
        self.assertNotIn('not indexed yet', result['before']['summary'])

    def test_unavailable_status_stays_explicit_and_recovery_does_not_start_a_scan(self):
        result = self.run_context(failGet=True, recover=True)
        before, after = result['before'], result['after']
        self.assertEqual(before['parent'], 'recall-index-actions')
        self.assertTrue(before['disabled'])
        self.assertTrue(before['retryVisible'])
        self.assertIn('unavailable index status', before['error'])
        self.assertNotIn('not indexed yet', before['summary'])
        self.assertEqual(after['parent'], 'recall-actions')
        self.assertFalse(after['disabled'])
        self.assertIsNone(after['error'])
        self.assertIn('not indexed yet', after['summary'])
        self.assertFalse(any(r['method'] == 'POST' for r in after['requests']))


if __name__ == '__main__':
    unittest.main()
