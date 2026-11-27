"""Submitted-page navigation, retained-page recovery and stale response units."""
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
class Element {
  constructor(tag='div',id='',text='',cls=''){
    this.tagName=tag.toUpperCase();this.id=id;this.textContent=text;this.children=[];this.parentElement=null;
    this.dataset={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.open=false;
    this.isConnected=!!id;this.listeners=new Map();this.classes=new Set(cls.split(' ').filter(Boolean));
    this.classList={add:n=>this.classes.add(n),remove:n=>this.classes.delete(n),
      toggle:(n,on)=>on?this.classes.add(n):this.classes.delete(n)};
  }
  connect(value){this.isConnected=value;for(const child of this.children)child.connect(value);}
  append(...children){for(const child of children){child.parentElement=this;child.connect(this.isConnected);this.children.push(child);}}
  prepend(child){if(child.parentElement)child.parentElement.children=child.parentElement.children.filter(n=>n!==child);
    child.parentElement=this;child.connect(this.isConnected);this.children.unshift(child);}
  replaceChildren(...children){for(const child of this.children)child.connect(false);this.children=[];this.append(...children);}
  setAttribute(){}
  addEventListener(name,handler){if(!this.listeners.has(name))this.listeners.set(name,[]);this.listeners.get(name).push(handler);}
  matches(selector){return selector.startsWith('.')?this.classes.has(selector.slice(1)):this.tagName===selector.toUpperCase();}
  querySelectorAll(selector){const parts=selector.split(',').map(s=>s.trim()),result=[];
    for(const child of this.children){if(parts.some(s=>child.matches(s)))result.push(child);result.push(...child.querySelectorAll(selector));}
    return result;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  contains(node){return node===this || this.children.some(child=>child.contains(node));}
  focus(){document.activeElement=this;}
  scrollIntoView(){}
  showModal(){this.open=true;}
  close(){this.open=false;for(const handler of this.listeners.get('close')||[])handler();}
  get firstElementChild(){return this.children[0]||null;}
}
const elements=new Map();
const el=id=>{if(!elements.has(id))elements.set(id,new Element('div',id));return elements.get(id);};
global.document={getElementById:el,createElement:tag=>new Element(tag),
  createTextNode:text=>new Element('text','',text),activeElement:null};
global.setTimeout=()=>1;global.clearTimeout=()=>{};
const requests=[],reads=[];let hold=false,pending=null;
const response=(q,offset)=>({query:q,offset,limit:30,total:65,coverage:{native:{indexed_threads:3}},
  results:Array.from({length:Math.min(30,65-offset)},(_,n)=>({kind:'native-activity',thread_id:q+'-thread',
    item_id:'item-'+(offset+n),turn_id:'turn-'+(offset+n),title:'Saved '+q,cwd:'/work/alpha',
    profile:'default',snippet:q+' retained decision '+(offset+n),match_text:q,updated:1795600000-offset-n}))});
const api=async(path,data)=>{
  if(path==='/api/history/index')return {job:{status:'completed',seen:3,indexed:3,failed:0,limit:200},coverage:{indexed_threads:3}};
  if(path.startsWith('/api/recall?')){
    const params=new URL(path,'http://127.0.0.1').searchParams,query=Object.fromEntries(params);
    requests.push(query);const result=response(query.q,Number(query.offset));
    if(hold){hold=false;return new Promise((resolve,reject)=>{pending={resolve:()=>resolve(result),reject};});}
    return result;
  }
  throw new Error('Unexpected request '+path);
};
global.DeskHistoryReader={show:(result,callbacks)=>{if(callbacks.valid()){
  reads.push(result.item_id);el('history-reader').open=true;}}};
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8')+'\nglobalThis.recall=DeskRecall;');
recall.configure({api,state:()=>({sessions:[{cwd:'/work/alpha'}]}),make:(tag,text,cls)=>new Element(tag,'',text||'',cls||''),
  selected:()=>null,generation:()=>0,profileLabel:()=> 'Current Codex settings'});
const settle=async()=>{for(let i=0;i<5;i++)await new Promise(resolve=>setImmediate(resolve));};
const submit=async()=>{el('recall-form').onsubmit({preventDefault(){}});await settle();};
const snapshot=()=>({query:el('recall-query').value,first:el('recall-results').firstElementChild?.dataset.item||null,
  rows:el('recall-results').children.length,summary:el('recall-summary').textContent,
  previousDisabled:el('recall-previous').disabled,nextDisabled:el('recall-next').disabled,
  previousHidden:el('recall-previous').hidden,nextHidden:el('recall-next').hidden,
  readDisabled:el('recall-results').querySelector('.recall-read')?.disabled||false});
(async()=>{
  el('home-content').onclick();await settle();
  el('recall-query').value='retry budget';el('recall-query').oninput();
  el('recall-project').value='/work/alpha';el('recall-project').onchange();
  el('recall-archived').checked=true;el('recall-archived').onchange();await submit();
  const first=snapshot();el('recall-next').onclick();await settle();const second=snapshot();
  const read=el('recall-results').querySelector('.recall-read');read.onclick();el('history-reader').open=false;read.focus();
  const returned=snapshot();el('recall').close();el('home-content').onclick();await settle();const reopened=snapshot();
  hold=true;el('recall-next').onclick();await settle();const busy=snapshot();pending.reject(new Error('Controlled page unavailable'));await settle();
  const failed=snapshot();el('recall-results').querySelector('.recall-read').onclick();el('history-reader').open=false;
  hold=true;el('recall-next').onclick();await settle();const old=pending;
  el('recall-query').value='new phrase';el('recall-query').oninput();const edited=snapshot();await submit();
  old.resolve();await settle();const replaced=snapshot();
  hold=true;el('recall-next').onclick();await settle();const closing=pending;el('recall').close();closing.resolve();await settle();
  el('home-content').onclick();await settle();const cancelled=snapshot();
  process.stdout.write(JSON.stringify({first,second,returned,reopened,busy,failed,edited,replaced,cancelled,requests,reads}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
"""


@unittest.skipUnless(NODE, 'Node is needed for browser controller units')
class RecallPageNavigationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run([NODE, '-e', HARNESS, str(SOURCE)], capture_output=True,
                                text=True, check=True, timeout=10)
        cls.states = json.loads(result.stdout)

    def test_next_reader_return_and_reopen_preserve_submitted_page(self):
        states = self.states
        self.assertEqual((states['first']['first'], states['first']['rows']), ('item-0', 30))
        self.assertTrue(states['first']['previousDisabled'])
        self.assertFalse(states['first']['nextDisabled'])
        for key in ('second', 'returned', 'reopened'):
            self.assertEqual((states[key]['first'], states[key]['rows']), ('item-30', 30))
            self.assertIn('Items 31–60', states[key]['summary'])
            self.assertFalse(states[key]['previousDisabled'])
        self.assertEqual(states['reads'], ['item-30', 'item-30'])
        self.assertTrue(all(request['cwd'] == '/work/alpha' and request['archived'] == 'true'
                            for request in states['requests']))

    def test_failed_page_retains_readable_rows_and_rebinds_their_current_actions(self):
        self.assertTrue(self.states['busy']['readDisabled'])
        self.assertTrue(self.states['busy']['nextDisabled'])
        self.assertEqual(self.states['busy']['first'], 'item-30')
        failed = self.states['failed']
        self.assertEqual((failed['first'], failed['rows']), ('item-30', 30))
        self.assertFalse(failed['readDisabled'])
        self.assertFalse(failed['nextDisabled'])
        self.assertIn('current results are kept', failed['summary'])

    def test_edits_new_submission_and_close_ignore_old_page_response(self):
        edited = self.states['edited']
        self.assertEqual(edited['rows'], 0)
        self.assertTrue(edited['nextHidden'])
        replaced = self.states['replaced']
        self.assertEqual((replaced['query'], replaced['first'], replaced['rows']), ('new phrase', 'item-0', 30))
        self.assertIn('Items 1–30', replaced['summary'])
        self.assertEqual(self.states['requests'][-2]['offset'], '0')
        cancelled = self.states['cancelled']
        self.assertEqual((cancelled['query'], cancelled['first']), ('new phrase', 'item-0'))
        self.assertTrue(cancelled['previousDisabled'])


if __name__ == '__main__':
    unittest.main()
