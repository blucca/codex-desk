"""Recent inspection never selects or reopens the mounted workbench."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import unittest

HOME=Path(__file__).resolve().parents[1]/'codex_desk/static/home.js'
NODE=shutil.which('node')
HARNESS=r"""
const assert=require('assert');
class Element {
  constructor(id='',tag='div'){this.id=id;this.tagName=tag.toUpperCase();this.children=[];this.parentNode=null;
    this.textContent='';this.attributes={};this.dataset={};this.hidden=false;this.disabled=false;this.open=false;this.handlers={};}
  get isConnected(){return this===document.body || !!this.parentNode?.isConnected;}
  get nextSibling(){return this.parentNode?.children[this.parentNode.children.indexOf(this)+1] || null;}
  detach(){if(this.parentNode)this.parentNode.children=this.parentNode.children.filter(c=>c!==this);this.parentNode=null;}
  append(...children){for(const c of children){c.detach();this.children.push(c);c.parentNode=this;}}
  insertBefore(child,next){child.detach();const i=this.children.indexOf(next);this.children.splice(i<0?this.children.length:i,0,child);child.parentNode=this;}
  replaceChildren(...children){for(const c of [...this.children])c.detach();this.append(...children);}
  setAttribute(name,value){this.attributes[name]=value;}
  querySelectorAll(selector){return this.children.flatMap(c=>[...(selector==='button'?c.tagName==='BUTTON':c.className===selector.slice(1))?[c]:[],...c.querySelectorAll(selector)]);}
  querySelector(selector){return this.querySelectorAll(selector)[0] || null;}
  focus(options){if(this.disabled)return;document.activeElement=this;this.focusOptions=options;}
  addEventListener(name,callback){this.handlers[name]=callback;}
  showModal(){this.open=true;this.origin=document.activeElement;this.querySelector('button')?.focus();}
  close(){this.open=false;this.origin?.focus();this.handlers.close?.();}
}
const document={body:new Element('body'),activeElement:null},elements=new Map();
document.activeElement=document.body;
document.getElementById=id=>{if(!elements.has(id)){const n=new Element(id);elements.set(id,n);document.body.append(n);}return elements.get(id);};
document.createElement=tag=>new Element('',tag);
const $=document.getElementById;
$('main').append($('welcome'),$('activity'));
$('recent-work').append($('recent-return'));
$('welcome').append($('home-list'));
let selected='a',generation=7,opening=false,nativeThreadId='native-a';
const state={sessions:[{id:'a',name:'Retained active Plan',cwd:'/active',status:'running'}]};
const draft={text:'Exact unsent Plan',mode:'plan'},queue=['First prepared','Second prepared'];
const initial=JSON.stringify({selected,generation,nativeThreadId,draft,queue});
const calls=[],opens=[],reads=[];
let request=async path=>({data:[{id:'removed',name:'Decision',cwd:'/removed',cwdExists:false},
 {id:'available',name:'Next check',cwd:'/available',cwdExists:true}]});
const DeskHistoryReader={show:async(result,callbacks)=>{if(!callbacks.valid())return false;reads.push({result,callbacks});return true;}};
const row=(thread,resume,handoff,label,read)=>{
 const n=new Element();n.dataset.thread=thread.id;
 if(resume){const b=new Element('', 'button');b.className='resume';b.onclick=resume;n.append(b);}
 const b=new Element('', 'button');b.className='native-read';b.onclick=read;n.append(b);return n;
};
"""


@unittest.skipUnless(NODE,'Node is required for Recent controller contracts')
class RecentWorkControllerTests(unittest.TestCase):
    def check(self,body,setup=''):
        script=HARNESS+'\n'+HOME.read_text()+'\n'+setup+r"""
DeskHome.configure({api:async(path,data)=>{calls.push({path,data});return request(path,data);},row,
 selected:()=>selected,generation:()=>generation,opening:()=>opening,state:()=>state,
 open:async id=>{opens.push(id);selected=id;++generation;DeskHome.selectionChanged();},browse:()=>{},project:()=>{}});
const settle=async()=>{for(let i=0;i<4;i++)await new Promise(resolve=>setImmediate(resolve));};
const unchanged=()=>assert.strictEqual(JSON.stringify({selected,generation,nativeThreadId,draft,queue}),initial);
(async()=>{
"""+body+"\nprocess.stdout.write(JSON.stringify({passed:true}));\n})().catch(e=>{process.stderr.write(e.stack);process.exit(1);});"
        result=subprocess.run([NODE,'-'],input=script,capture_output=True,text=True,timeout=10)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_active_plan_recent_read_back_and_return_keep_exact_workbench(self):
        self.check(r"""
assert.strictEqual($('welcome').hidden,true);assert.strictEqual($('show-recent').hidden,false);
$('show-recent').focus();$('show-recent').onclick();await settle();
assert($('recent-work').open);assert.strictEqual($('welcome').parentNode,$('recent-work'));
assert($('recent-selected-status').textContent.includes('Retained active Plan · running'));
const rows=$('home-list').children;assert.strictEqual(rows.length,2);
assert.strictEqual(rows[0].querySelector('.resume'),null);
await rows[0].querySelector('.native-read').onclick();
assert.deepStrictEqual(reads[0].result,{thread_id:'removed',cwd:'/removed'});assert(reads[0].callbacks.valid());
assert.strictEqual(reads[0].callbacks.backLabel,'Back to recent work');reads[0].callbacks.onReturn();
assert.strictEqual(document.activeElement,rows[0].querySelector('.native-read'));
assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
assert.strictEqual($('home-list').children[0],rows[0]);assert.strictEqual(calls.length,1);
state.sessions[0].status='approval';DeskHome.sync();assert($('recent-selected-status').textContent.includes('· approval'));
$('recent-return').onclick();assert(!$('recent-work').open);assert.strictEqual($('welcome').parentNode,$('main'));
assert.strictEqual($('welcome').nextSibling,$('activity'));assert($('welcome').hidden);
assert.strictEqual(document.activeElement,$('show-recent'));assert(!reads[0].callbacks.valid());unchanged();
assert.strictEqual(opens.length,0);assert(calls.every(c=>!c.data));
""")

    def test_first_use_remains_inline_and_only_explicit_resume_opens(self):
        self.check(r"""
selected=null;DeskHome.sync();await DeskHome.load();
assert(!$('welcome').hidden);assert($('show-recent').hidden);assert(!$('recent-work').open);
assert.strictEqual($('home-list').children.length,2);assert.strictEqual(opens.length,0);
request=async(path,data)=>{assert.strictEqual(path,'/api/import');assert.deepStrictEqual(data,{thread:'available',profile:'default'});return {id:'imported'};};
await $('home-list').children[1].querySelector('.resume').onclick();
assert.deepStrictEqual(opens,['imported']);assert.strictEqual(selected,'imported');assert($('welcome').hidden);
assert.strictEqual(calls.filter(c=>c.data).length,1);
""")

    def test_close_reopen_rejects_old_result_and_preserves_new_row_source(self):
        self.check(r"""
let release;request=()=>new Promise(resolve=>release=resolve);
$('show-recent').onclick();assert($('recent-work').open);$('recent-return').onclick();
request=async()=>({data:[{id:'current',name:'Latest source',cwd:'/current'}]});
$('show-recent').onclick();await settle();const row=$('home-list').children[0];
release({data:[{id:'stale',cwd:'/stale'}]});await settle();
assert.strictEqual($('home-list').children[0],row);assert.strictEqual(row.dataset.thread,'current');
await row.querySelector('.native-read').onclick();const callbacks=reads[0].callbacks;assert(callbacks.valid());
++generation;assert(!callbacks.valid());--generation;$('home-list').replaceChildren();assert(!callbacks.valid());
callbacks.onReturn();assert.strictEqual(opens.length,0);unchanged();
""")

    def test_selection_change_closes_surface_and_invalidates_pending_read(self):
        self.check(r"""
$('show-recent').onclick();await settle();const row=$('home-list').children[0];
await row.querySelector('.native-read').onclick();selected='different';++generation;DeskHome.selectionChanged();
assert(!$('recent-work').open);assert($('welcome').hidden);assert(!reads[0].callbacks.valid());
assert.strictEqual($('welcome').parentNode,$('main'));assert.strictEqual(opens.length,0);
""")

    def test_load_failure_and_explicit_retry_do_not_resume(self):
        self.check(r"""
request=async()=>{throw Error('Controlled catalog unavailable');};$('show-recent').onclick();await settle();
assert(!$('home-error').hidden);assert(!$('home-retry').hidden);
request=async()=>({data:[]});await $('home-retry').onclick();assert($('home-error').hidden);
assert.strictEqual($('home-list').attributes['aria-busy'],'false');assert.strictEqual(calls.length,2);
$('recent-return').onclick();unchanged();assert.strictEqual(opens.length,0);
""")

    def test_latest_six_missing_folders_and_busy_opening_are_truthful(self):
        self.check(r"""
opening=true;DeskHome.sync();$('show-recent').onclick();assert(!$('recent-work').open);assert.strictEqual(calls.length,0);
opening=false;request=async()=>({data:Array.from({length:8},(_,i)=>({id:'t'+i,cwd:'/removed/'+i,cwdExists:false,name:'X'.repeat(200)}))});
$('show-recent').onclick();await settle();assert.strictEqual($('home-list').children.length,6);
assert($('home-list').children.every(row=>!row.querySelector('.resume') && row.querySelector('.native-read')));
assert($('home-status').textContent.includes('8 recent project folder(s) unavailable'));
unchanged();assert.strictEqual(opens.length,0);
""")

    def test_restored_static_sample_recent_is_read_only_without_a_backend(self):
        root=HOME.parents[2]
        spec=importlib.util.spec_from_file_location('recent_preview_build',root/'examples/build_browser_preview.py')
        build=importlib.util.module_from_spec(spec);spec.loader.exec_module(build)
        threads=build.sample_threads();session='desk-'+threads[0]['id']
        fixture={'threads':threads,'saved':{'sessions':[{'id':session,'thread_id':threads[0]['id'],
            'name':threads[0]['name'],'cwd':threads[0]['cwd'],'status':'saved','profile':'default'}],
            'drafts':{session:{'text':'Exact restored sample Plan','mode':'plan','revision':1}},
            'followups':{session:{'entries':[{'id':'one','text':'First saved check','mode':'native','state':'queued'},
                {'id':'two','text':'Second saved Plan','mode':'plan','state':'queued'}],'reservation':None}},
            'indexed':False,'nextId':3}}
        setup=r"""
const fixture=FIXTURE,vm=require('vm');let stored=JSON.stringify(fixture.saved),external=0;
global.localStorage={getItem:()=>stored,setItem:(_key,value)=>stored=value};
global.location={href:'http://127.0.0.1/demo/',origin:'http://127.0.0.1'};
document.addEventListener=()=>{};
global.window={DeskPreviewThreads:fixture.threads,open:()=>{throw Error('Unexpected installer');},fetch:()=>{++external;throw Error('Unexpected backend');}};
vm.runInThisContext(API_SOURCE);
request=async(path,data)=>{const response=await window.fetch(path,data?{method:'POST',body:JSON.stringify(data)}:{});
assert.strictEqual(response.status,200);return response.json();};
selected=fixture.saved.sessions[0].id;state.sessions=fixture.saved.sessions;
const sampleBefore=window.DeskBrowserPreview.snapshot(),storedBefore=stored;
""".replace('FIXTURE',json.dumps(fixture)).replace('API_SOURCE',json.dumps((root/'examples/browser-preview/preview-api.js').read_text()))
        self.check(r"""
$('show-recent').focus();$('show-recent').onclick();await settle();
assert($('recent-work').open);assert.strictEqual($('home-list').children.length,3);
assert.strictEqual(fixture.threads.at(-1).archived,true);
assert($('recent-selected-status').textContent.includes('Sample checkout retry decision · saved'));
const second=$('home-list').children[1];await second.querySelector('.native-read').onclick();
assert.strictEqual(reads[0].result.thread_id,fixture.threads[1].id);
const original=await request('/api/native/thread?id='+encodeURIComponent(reads[0].result.thread_id));
assert.deepStrictEqual(original,fixture.threads[1]);reads[0].callbacks.onReturn();
assert.strictEqual(document.activeElement,second.querySelector('.native-read'));
$('recent-return').onclick();assert.strictEqual(document.activeElement,$('show-recent'));
assert.strictEqual(selected,fixture.saved.sessions[0].id);assert.strictEqual(generation,7);
assert.deepStrictEqual(window.DeskBrowserPreview.snapshot(),sampleBefore);assert.strictEqual(stored,storedBefore);
assert.strictEqual(opens.length,0);assert.strictEqual(external,0);
assert(window.DeskBrowserPreview.requests.every(r=>r.method==='GET'));
assert.strictEqual(window.DeskBrowserPreview.requests.length,2);
""",setup)


if __name__=='__main__':unittest.main()
