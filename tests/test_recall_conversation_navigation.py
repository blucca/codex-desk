"""Actual grouped/scoped recall controller, ownership and forward/return units."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import unittest
NODE=os.environ.get('DESK_TEST_NODE') or shutil.which('node')
SOURCE=Path(__file__).resolve().parents[1]/'codex_desk/static/recall.js'
HARNESS=r"""
const fs=require('fs'),vm=require('vm');
class Element {
  constructor(tag='div',id='',text='',cls=''){
    this.tagName=tag.toUpperCase();this.id=id;this.textContent=text;this.children=[];this.parentElement=null;
    this.dataset={};this.value='';this.checked=false;this.disabled=false;this.hidden=false;this.open=false;
    this.scrollTop=0;this.isConnected=!!id;this.listeners=new Map();this.classes=new Set(cls.split(' ').filter(Boolean));
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
const response=(q,offset,options)=>{
 const item=n=>({kind:'native-activity',thread_id:options.source_thread||'A',item_id:'item-'+(offset+n),turn_id:'turn-'+n,
  title:'Original '+(options.source_thread||'A'),cwd:'/work/alpha',profile:'default',snippet:q+' source evidence',match_text:q});
 if(options.view==='conversations')return {offset,limit:30,total:2,item_total:66,results:[
  {...item(0),group_kind:'native',group_id:'A',match_count:65},
  {...item(1),thread_id:'B',title:'Original B',group_kind:'native',group_id:'B',match_count:1}]};
 return {offset,limit:30,total:options.source_thread==='B'?1:65,results:Array.from({length:options.source_thread==='B'?1:Math.min(30,65-offset)},(_,n)=>item(n))};
};
const api=async(path,data)=>{
  if(path==='/api/history/index')return {job:{status:'completed',seen:3,indexed:3,failed:0,limit:200},coverage:{indexed_threads:3}};
  if(path.startsWith('/api/recall?')){
    const params=new URL(path,'http://127.0.0.1').searchParams,query=Object.fromEntries(params);
    requests.push(query);const result=response(query.q,Number(query.offset),query);
    if(hold){hold=false;return new Promise((resolve,reject)=>{pending={resolve:()=>resolve(result),reject};});}
    return result;
  }
  throw new Error('Unexpected request '+path);
};
global.DeskHistoryReader={show:(result,callbacks)=>{if(callbacks.valid()){
  reads.push(result.item_id);el('history-reader').open=true;global.readerReturn=callbacks.onReturn;}}};
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
 el('home-content').onclick();await settle();el('recall-query').value='Café 项目 😀';el('recall-query').oninput();
 el('recall-grouped').checked=true;el('recall-grouped').onchange();await submit();
 const groups=()=>[...el('recall-results').children].map(r=>r.dataset.group);
 const initial=groups();el('recall').scrollTop=93;el('recall-results').scrollTop=17;
 const pick=()=>el('recall-results').children[0].querySelector('.recall-group').onclick();
 await pick();const selected=snapshot();el('recall-next').onclick();await settle();const page=snapshot();
 el('recall').scrollTop=141;el('recall-results').scrollTop=42;el('recall-results').querySelector('.recall-read').onclick();
 el('history-reader').open=false;readerReturn();const returned={...snapshot(),scroll:el('recall').scrollTop,focus:document.activeElement.classes.has('recall-read')};
 el('recall-source-back').onclick();await settle();const back={groups:groups(),scroll:el('recall').scrollTop,focus:document.activeElement.classes.has('recall-group')};
 hold=true;pick();await settle();const held=pending;el('recall-source-back').onclick();await settle();held.resolve();await settle();const superseded=groups();
 await pick();el('recall-query').value='new literal';el('recall-query').oninput();await submit();el('recall-source-back').onclick();await settle();
 const edited={groups:groups(),query:el('recall-query').value,summary:el('recall-summary').textContent};
 process.stdout.write(JSON.stringify({initial,selected,page,returned,back,superseded,edited,requests,reads}));
})().catch(error=>{process.stderr.write(error.stack);process.exitCode=1;});
"""
@unittest.skipUnless(NODE,'Node required')
class RecallConversationNavigationTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  p=subprocess.run([NODE,'-e',HARNESS,str(SOURCE)],capture_output=True,text=True,check=True,timeout=10);cls.s=json.loads(p.stdout)
 def test_conversation_choice_and_source_page_read_return_are_exact(self):
  self.assertEqual(self.s['initial'],['A','B']);self.assertEqual(self.s['selected']['first'],'item-0');self.assertEqual(self.s['page']['first'],'item-30')
  self.assertEqual((self.s['returned']['first'],self.s['returned']['scroll'],self.s['returned']['focus']),('item-30',141,True));self.assertEqual(self.s['reads'],['item-30'])
 def test_back_restores_conversation_row_and_scroll_and_rejects_held_items(self):
  self.assertEqual(self.s['back'],{'groups':['A','B'],'scroll':93,'focus':True});self.assertEqual(self.s['superseded'],['A','B'])
 def test_changed_literal_back_runs_new_group_query_not_previous_rows(self):
  self.assertEqual(self.s['edited']['query'],'new literal');self.assertEqual(self.s['edited']['groups'],['A','B'])
  self.assertEqual(self.s['requests'][-1]['q'],'new literal');self.assertEqual(self.s['requests'][-1]['view'],'conversations');self.assertNotIn('source_thread',self.s['requests'][-1])
 def test_source_scope_is_explicit_exact_and_preserves_unicode_literal(self):
  scoped=[q for q in self.s['requests'] if 'source_thread' in q];self.assertTrue(scoped);self.assertTrue(all(q['source_thread']=='A' for q in scoped))
  self.assertEqual(scoped[0]['q'],'Café 项目 😀');self.assertEqual(scoped[1]['offset'],'30')
if __name__=='__main__':unittest.main()
