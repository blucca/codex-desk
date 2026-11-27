"""Targeted shipped sidebar/project controllers without browser or native calls."""
import json
from pathlib import Path
import shutil
import subprocess
import unittest

APP = Path(__file__).resolve().parents[1] / 'codex_desk' / 'static' / 'app.js'
NODE = shutil.which('node')
DOM = r"""
const assert=require('assert');
const document={activeElement:null};
class Element {
  constructor(tag='div',text='',cls=''){this.tagName=tag.toUpperCase();this._text=text;this.className=cls;
    this.children=[];this.parentElement=null;this.dataset={};this.attributes={};this.disabled=false;
    this.hidden=false;this.value='';this.checked=false;this.open=false;this.isConnected=false;this.scrollLeft=0;this.scrollTop=0;}
  get classList(){return {contains:name=>this.className.split(/\s+/).includes(name)};}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set textContent(text){this._text=text;this.children=[];}
  setAttribute(key,value){this.attributes[key]=value;}
  getAttribute(key){return this.attributes[key]??null;}
  connect(value){this.isConnected=value;for(const child of this.children)child.connect(value);}
  append(...children){for(const child of children){child.parentElement=this;child.connect(this.isConnected);this.children.push(child);}}
  contains(node){for(let current=node;current;current=current.parentElement)if(current===this)return true;return false;}
  closest(selector){for(let current=this;current;current=current.parentElement)if(current.classList.contains(selector.slice(1)))return current;return null;}
  querySelectorAll(selector){const found=[];for(const child of this.children){
    if(selector==='button'?child.tagName==='BUTTON':child.classList.contains(selector.slice(1)))found.push(child);
    found.push(...child.querySelectorAll(selector));}return found;}
  querySelector(selector){return this.querySelectorAll(selector)[0]||null;}
  replaceChildren(...children){if(this.contains(document.activeElement))document.activeElement=document.body;
    for(const child of this.children){child.connect(false);child.parentElement=null;}this.children=[];this._text='';this.append(...children);}
  remove(){if(this.parentElement){const parent=this.parentElement;parent.children=parent.children.filter(child=>child!==this);this.parentElement=null;this.connect(false);}}
  focus(options){if(this.disabled)return;document.activeElement=this;this.focusOptions=options;}
}
document.body=new Element('body');document.body.connect(true);document.activeElement=document.body;
const elements=new Map(),$=id=>{if(!elements.has(id)){const element=new Element();elements.set(id,element);document.body.append(element);}return elements.get(id);};
const make=(tag,text='',cls='')=>new Element(tag,text,cls);
let state={sessions:[],profiles:[]},selected='active',projectVersion=0,projectCursor=null,projectQuery=null,projectScope=null,projectOpening=false;
const archiving=new Set(),profileLabel=()=> 'Current settings';
function open(){throw Error('Navigation fixture must not open or resume');}
function setArchived(){throw Error('Rendering must not archive');}
const mutations=[],reads=[];
function openProjectChoice(){mutations.push('openProjectChoice');throw Error('Read must not select a continuation');}
const DeskHistoryReader={show:async(result,callbacks)=>{reads.push({result,callbacks});return true;}};
let api=async()=>{throw Error('Unexpected API request');};
"""


@unittest.skipUnless(NODE, 'Node.js is required for the pure navigation controller contract')
class NavigationControllerTests(unittest.TestCase):
    def run_controller(self, body):
        source=APP.read_text()
        fragments=[]
        for begin,end in [('function activeSession(', 'async function setArchived('),
                          ('function resetProject()', 'async function openProjectChoice('),
                          ('function nativeRow(', 'function resetNative(')]:
            fragments.append(source[source.index(begin):source.index(end)])
        code=DOM+'\n'+'\n'.join(fragments)+'\n'+r"""
(async()=>{
"""+body+r"""
process.stdout.write(JSON.stringify({passed:true}));
})().catch(error=>{process.stderr.write(error.stack);process.exit(1);});
"""
        result=subprocess.run([NODE,'-e',code],text=True,capture_output=True,timeout=20)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(json.loads(result.stdout),{'passed':True})

    def test_sidebar_retains_exact_session_control_focus_through_reorder(self):
        self.run_controller(r"""
state.sessions=[{id:'quoted "] session',name:'Same title',cwd:'/project/a',profile:'default',status:'ready'},
                {id:'active',name:'Same title',cwd:'/project/b',profile:'default',status:'ready'}];
drawSidebar();const list=$('sessions');list.scrollTop=123;list.scrollLeft=7;
const old=list.querySelectorAll('.session-row').find(row=>row.dataset.session==='quoted "] session').querySelector('.session');old.focus();
state.sessions[0].status='running';state.sessions.reverse();drawSidebar();
assert.notStrictEqual(document.activeElement,old);
assert.strictEqual(document.activeElement.closest('.session-row').dataset.session,'quoted "] session');
assert(document.activeElement.classList.contains('session'));assert.deepStrictEqual(document.activeElement.focusOptions,{preventScroll:true});
assert.strictEqual(list.scrollTop,123);assert.strictEqual(list.scrollLeft,7);
const selectedButton=list.querySelectorAll('.session-row').find(row=>row.dataset.session==='active').querySelector('.session');
assert.strictEqual(selectedButton.getAttribute('aria-current'),'page');
assert.strictEqual(document.activeElement.getAttribute('aria-current'),null);
""")

    def test_sidebar_retains_archive_identity_but_never_steals_other_focus(self):
        self.run_controller(r"""
state.sessions=[{id:'one',name:'Saved task',cwd:'/project/a',profile:'default',status:'ready'}];$('show-archived').checked=true;
drawSidebar();$('sessions').querySelector('.session-archive').focus();state.sessions[0].archived=true;drawSidebar();
assert(document.activeElement.classList.contains('session-archive'));assert.strictEqual(document.activeElement.textContent,'Restore');
$('session-filter').focus();drawSidebar();assert.strictEqual(document.activeElement,$('session-filter'));
$('sessions').querySelector('.session').focus();$('show-archived').checked=false;drawSidebar();
assert.strictEqual(document.activeElement,document.body);assert.strictEqual($('sessions').querySelectorAll('.session-row').length,0);
""")

    def test_project_read_retains_exact_query_pages_and_returns_to_source_button(self):
        self.run_controller(r"""
$('project').open=true;$('cwd').value='/work/a folder';$('project-search').value=' Release + status? ';$('profile').value='retained';
const calls=[],reply=[{data:[{id:'first',cwd:'/work/a folder',name:'Release + status? first'}],nextCursor:'page-two'},
 {data:[{id:'older',cwd:'/work/a folder',name:'Release + status? older'}],nextCursor:null}];
api=async path=>{calls.push(path);return reply.shift();};
await findProject();await findProject('page-two');
assert.strictEqual(calls.length,2);const params=new URL(calls[1],'http://local').searchParams;
assert.strictEqual(params.get('cwd'),'/work/a folder');assert.strictEqual(params.get('search'),'Release + status?');assert.strictEqual(params.get('cursor'),'page-two');
const rows=$('project-list').children;assert.strictEqual(rows.length,2);assert.strictEqual(rows[1].dataset.cursor,'page-two');
await rows[1].querySelector('.native-read').onclick();assert.strictEqual(reads.length,1);
assert.deepStrictEqual(reads[0].result,{thread_id:'older',cwd:'/work/a folder'});assert(reads[0].callbacks.valid());
assert.strictEqual(reads[0].callbacks.backLabel,'Back to project results');reads[0].callbacks.onReturn();
assert.strictEqual(document.activeElement,rows[1].querySelector('.native-read'));
await rows[0].querySelector('.native-read').onclick();assert.strictEqual(reads.length,2);
assert.strictEqual(selected,'active');assert.strictEqual($('profile').value,'retained');assert.strictEqual($('project-search').value,' Release + status? ');
assert.strictEqual(mutations.length,0);assert.strictEqual(calls.length,2);
""")

    def test_removed_project_read_back_preserves_plan_queue_query_pages_and_row(self):
        self.run_controller(r"""
$('project').open=true;$('cwd').value='/removed/a folder';$('project-search').value=' 决策 + résumé ';$('profile').value='retained';
const plan={text:'Exact unsent Plan',mode:'plan'},queue=['First check','Second prepared Plan'];
const before=JSON.stringify({selected,plan,queue});
const scope={cwd:'/removed/a folder',cwdExists:false},calls=[];
const reply=[{projectScope:scope,data:[{id:'first',cwd:scope.cwd,cwdExists:false,name:'决策 + résumé'}],nextCursor:'opaque+页 /='},
 {projectScope:scope,data:[{id:'older',cwd:scope.cwd,cwdExists:false,name:'决策 + résumé older'}],nextCursor:null}];
api=async path=>{calls.push(path);return reply.shift();};
await findProject();assert($('project-new').disabled);await findProject('opaque+页 /=');
const rows=$('project-list').children;assert.strictEqual(rows.length,2);
assert(rows.every(row=>row.querySelectorAll('button').length===1));
assert(rows.every(row=>row.textContent.includes('Original evidence is still readable')));
assert($('project-summary').textContent.includes('restore the folder to resume or start'));
assert(!$('project-summary').textContent.includes('Start a new conversation below'));
await rows[1].querySelector('.native-read').onclick();
assert.deepStrictEqual(reads[0].result,{thread_id:'older',cwd:'/removed/a folder'});reads[0].callbacks.onReturn();
assert.strictEqual(document.activeElement,rows[1].querySelector('.native-read'));
assert.strictEqual($('project-list').children[1],rows[1]);assert.strictEqual(rows[1].dataset.cursor,'opaque+页 /=');
assert.strictEqual($('project-search').value,' 决策 + résumé ');assert.strictEqual($('cwd').value,scope.cwd);
assert.strictEqual(calls.length,2);assert.strictEqual(mutations.length,0);
const params=new URL(calls[1],'http://local').searchParams;
assert.strictEqual(params.get('cwd'),scope.cwd);assert.strictEqual(params.get('search'),'决策 + résumé');
assert.strictEqual(params.get('cursor'),'opaque+页 /=');assert.strictEqual(JSON.stringify({selected,plan,queue}),before);
projectBusy(true);projectBusy(false);assert($('project-new').disabled);
$('cwd').value='/available';resetProject();assert(!$('project-new').disabled);assert.strictEqual(projectScope,null);
""")

    def test_empty_missing_scope_is_read_only_and_stale_scope_cannot_disable_new(self):
        self.run_controller(r"""
$('project').open=true;$('cwd').value='/removed';$('project-search').value='Unmatched';
api=async()=>({projectScope:{cwd:'/removed',cwdExists:false},data:[],nextCursor:null});
await findProject();assert($('project-new').disabled);assert(!$('project-results').hidden);
assert($('project-summary').textContent.includes('No saved conversation titles match'));
assert($('project-summary').textContent.includes('Project folder unavailable'));
let release;api=async path=>new URL(path,'http://local').searchParams.get('cwd')==='/removed'
 ?new Promise(resolve=>release=resolve):{projectScope:{cwd:'/available',cwdExists:true},data:[],nextCursor:null};
const old=findProject();$('cwd').value='/available';await findProject();
release({projectScope:{cwd:'/removed',cwdExists:false},data:[],nextCursor:null});await old;
assert(!$('project-new').disabled);assert.strictEqual(projectScope.cwd,'/available');
assert($('project-summary').textContent.includes('Start a new conversation below'));
assert.strictEqual(mutations.length,0);
""")

    def test_project_source_invalidates_on_query_close_detach_and_wrong_cursor(self):
        self.run_controller(r"""
$('project').open=true;$('cwd').value='/work/a';$('project-search').value='Decision';
let requests=0;api=async()=>{++requests;return {data:[{id:'source',cwd:'/work/a',name:'Decision'}],nextCursor:'next-page'};};
await findProject();const row=$('project-list').children[0];await row.querySelector('.native-read').onclick();
const callbacks=reads[0].callbacks;assert(callbacks.valid());await findProject('not-the-current-cursor');assert.strictEqual(requests,1);
projectOpening=true;assert(!callbacks.valid());await row.querySelector('.native-read').onclick();assert.strictEqual(reads.length,1);projectOpening=false;
$('project').open=false;assert(!callbacks.valid());$('project').open=true;
$('project-search').value='Different';assert(!callbacks.valid());$('project-search').value='Decision';
$('project-list').replaceChildren();assert(!callbacks.valid());callbacks.onReturn();assert.strictEqual(reads.length,1);
""")

    def test_pending_old_project_page_cannot_replace_current_results(self):
        self.run_controller(r"""
$('project').open=true;$('cwd').value='/work/a';$('project-search').value='Old';let release;
api=async path=>new URL(path,'http://local').searchParams.get('search')==='Old'
 ?new Promise(resolve=>{release=resolve;}):{data:[{id:'new',cwd:'/work/a',name:'New'}],nextCursor:null};
const old=findProject();$('project-search').value='New';await findProject();
release({data:[{id:'old',cwd:'/work/a',name:'Old'}],nextCursor:'old-cursor'});await old;
assert.strictEqual($('project-list').children.length,1);assert.strictEqual($('project-list').children[0].dataset.thread,'new');
assert.strictEqual(projectCursor,null);assert.strictEqual(mutations.length,0);
""")


if __name__=='__main__':
    unittest.main()
