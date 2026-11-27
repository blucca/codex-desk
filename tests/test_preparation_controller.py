"""Focused Node controller acceptance; no browser, native runtime or provider."""
import os
from pathlib import Path
import shutil
import subprocess
import unittest


ROOT = Path(__file__).resolve().parents[1]
NODE = os.environ.get('DESK_TEST_NODE') or shutil.which('node')
HARNESS = r'''
const fs=require('fs'),vm=require('vm'),assert=require('assert/strict');
const ids=['preparation','preparation-title','preparation-project','preparation-archived',
  'preparation-refresh','preparation-close','preparation-status','preparation-error','preparation-list',
  'preparation-editor','preparation-editor-title','preparation-editor-binding','preparation-text',
  'preparation-mode','preparation-draft-status','preparation-conflict','preparation-keep','preparation-load',
  'preparation-save','preparation-save-open','preparation-copy','preparation-open','preparation-followups','preparation-reuse',
  'preparation-reuse-text','preparation-append','preparation-replace','preparation-reuse-cancel'];
class Element{
  constructor(tag,id=''){this.tagName=tag.toUpperCase();this.id=id;this.value='';this.checked=false;this.hidden=false;this.disabled=false;this.open=false;this.dataset={};this.children=[];this.listeners={};this.attributes={};this.text='';}
  append(...nodes){for(const n of nodes){n.parentElement=this;this.children.push(n);}}
  contains(node){for(let current=node;current;current=current.parentElement)if(current===this)return true;return false;}
  replaceChildren(...nodes){if(this.children.some(child=>child.contains(global.document?.activeElement)))document.activeElement=document.body;for(const n of this.children)n.parentElement=null;this.children=[];this.append(...nodes);}
  set textContent(v){this.text=String(v);this.replaceChildren();}
  get textContent(){return this.text+this.children.map(c=>c.textContent).join('');}
  setAttribute(key,v){this.attributes[key]=String(v);}
  addEventListener(type,fn){(this.listeners[type]??=[]).push(fn);}
  dispatch(type){for(const fn of this.listeners[type]||[])fn();}
  showModal(){this.open=true;}
  close(){this.open=false;this.dispatch('close');}
  focus(options){if(this.disabled)return;document.activeElement=this;this.focusOptions=options;}
  querySelectorAll(selector){return this.children.flatMap(child=>[...(selector==='button'&&child.tagName==='BUTTON'?[child]:[]),...child.querySelectorAll(selector)]);}
  scrollIntoView(){}
  click(){if(this.disabled)return;return this.onclick?.({preventDefault(){}});}
}
const nodes=Object.fromEntries(ids.map(id=>[id,new Element(id==='preparation'?'dialog':id.endsWith('text')?'textarea':'div',id)]));
global.document={getElementById:id=>{assert(nodes[id],'Missing ID '+id);return nodes[id];},activeElement:null};
document.body=new Element('body');document.body.append(...Object.values(nodes));document.activeElement=document.body;
Object.defineProperty(global,'crypto',{value:{randomUUID:()=> 'preparation-private-writer'},configurable:true});
const clipboard={values:[],fail:false};
Object.defineProperty(global,'navigator',{value:{clipboard:{async writeText(value){if(clipboard.fail)throw Error('denied');clipboard.values.push(value);}}},configurable:true});
vm.runInThisContext(fs.readFileSync(process.argv[1],'utf8'));
const n=id=>nodes['preparation'+(id?'-'+id:'')];
const all=node=>[node,...node.children.flatMap(all)];
const button=(node,label)=>all(node).find(e=>e.tagName==='BUTTON'&&e.textContent===label);
const clone=value=>JSON.parse(JSON.stringify(value));
const world={
  a:{id:'a',name:'A decision',cwd:'/projects/a',profile:'default',archived:false,status:'running',draft:{text:'A saved Plan',mode:'plan',revision:1},followups:{entries:[],reservation:null}},
  b:{id:'b',name:'B next work',cwd:'/gone/project',profile:'default',archived:false,status:'failed',draft:{text:'',mode:'native',revision:0},followups:{entries:[
    {id:'b-one',text:'Inspect original evidence',mode:'native',order:1,revision:1,state:'queued'},
    {id:'b-two',text:'Clarify the next acceptance',mode:'plan',order:2,revision:1,state:'queued'}],reservation:null}},
  c:{id:'c',name:'C archived',cwd:'/projects/c',profile:'old',archived:true,status:'saved',draft:{text:'C saved',mode:'native',revision:1},followups:{entries:[],reservation:null}},
  d:{id:'d',name:'D start review',cwd:'/projects/a',profile:'default',archived:false,status:'ready',draft:{text:'',mode:'native',revision:0},followups:{entries:[
    {id:'d-one',text:'Reviewable instruction',mode:'plan',order:1,revision:2,state:'needs_review'}],reservation:{session_id:'d',token:'not-rendered',entry_id:'d-one',revision:1,text:'Captured instruction',mode:'plan',state:'unknown'}}}
};
const calls=[],saved=[],opened=[],activeDraft={session:'a',text:'ACTIVE UNSENT PLAN — do not alter',mode:'plan'};
const control={overview:null,draft:null,post:null,failOverview:false,failDraft:false,failPost:false};
function snapshot(path){
  const q=new URL(path,'http://local.invalid').searchParams;
  return {sessions:Object.values(world).filter(row=>(q.get('archived')==='true'||!row.archived)&&(!q.get('cwd')||row.cwd===q.get('cwd')))
    .filter(row=>row.draft.text||row.followups.entries.length||row.followups.reservation)
    .map(row=>({...clone(row),draft:row.draft.text?clone(row.draft):null}))};
}
async function api(path,data){
  calls.push({path,data:clone(data??null)});
  if(path.startsWith('/api/preparation?')){if(control.failOverview)throw Error('Overview temporarily unavailable');const result=snapshot(path);if(control.overview)return control.overview(path,result);return result;}
  if(path.startsWith('/api/draft?')){if(control.failDraft)throw Error('Draft temporarily unavailable');const result=clone(world[new URL(path,'http://local.invalid').searchParams.get('session')].draft);if(control.draft)return control.draft(path,result);return result;}
  if(path==='/api/draft'&&data){
    if(control.failPost)throw Error('Save temporarily unavailable');
    const current=world[data.session].draft;
    if(current.revision!==data.revision){const error=Error('Draft changed elsewhere');error.status=409;error.current=clone(current);throw error;}
    const next={text:data.text,mode:data.mode,revision:current.revision+1};world[data.session].draft=next;
    if(control.post)return control.post(data,clone(next));return clone(next);
  }
  throw Error('Unexpected/native API '+path);
}
DeskPreparation.configure({api,make:(tag,text,cls)=>{const e=new Element(tag);if(text)e.textContent=text;if(cls)e.className=cls;return e;},profileLabel:id=>'Profile '+id,
  onSaved:async(id,draft)=>saved.push({id,draft:clone(draft)}),openConversation:async id=>{opened.push(id);return true;}});
const sessions=()=>all(n('list')).filter(e=>e.className==='preparation-session').map(e=>e.dataset.session);
const review=id=>{const source=all(n('list')).find(e=>e.dataset.session===id&&e.dataset.control==='review');source.focus();return source.click();};
function fill(text,mode){n('text').value=text;n('text').oninput();if(mode){n('mode').value=mode;n('mode').onchange();}}
const followup=id=>all(n('followups')).find(e=>e.tagName==='ARTICLE'&&e.dataset.followup===id);
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};
const settle=async()=>{await Promise.resolve();await Promise.resolve();};
(async()=>{
  const testcase=process.argv[2];await DeskPreparation.show();
  if(testcase==='discover'){
    assert.deepEqual(sessions(),['a','d','b']);assert.equal(opened.length,0);assert.equal(saved.length,0);
    assert.equal(n('editor').hidden,true);assert.equal(calls.length,1);
    await review('b');assert.equal(n('text').value,'');assert.equal(n('text').disabled,false);
    assert.match(n('editor-binding').textContent,/\/gone\/project/);assert(calls.some(c=>c.path==='/api/draft?session=b'));
    n('archived').checked=true;await n('archived').onchange();assert(sessions().includes('c'));
    n('project').value='/gone/project';await n('project').onchange();assert.deepEqual(sessions(),['b']);
    assert(calls.some(c=>c.path==='/api/preparation?archived=true&cwd=%2Fgone%2Fproject'));
  }else if(testcase==='draft-save'){
    await review('b');fill('Saved B preparation','plan');await n('save').click();
    assert.deepEqual(world.b.draft,{text:'Saved B preparation',mode:'plan',revision:1});
    assert.equal(saved[0].id,'b');const post=calls.find(c=>c.path==='/api/draft');
    assert.equal(post.data.writer,'preparation-private-writer');assert(post.data.sequence>=2);
    fill('B unsaved newer','native');await n('close').click();await DeskPreparation.show();
    assert.equal(n('text').value,'B unsaved newer');await review('a');await review('b');
    assert.equal(n('text').value,'B unsaved newer');assert.equal(n('mode').value,'native');
    assert.equal(calls.filter(c=>c.path==='/api/draft').length,1);
  }else if(testcase==='conflict'){
    await review('b');fill('B mine','plan');world.b.draft={text:'B changed elsewhere',mode:'native',revision:1};
    await n('save').click();assert.equal(n('conflict').hidden,false);assert.equal(n('save').disabled,true);
    assert.equal(n('text').value,'B mine');assert.equal(n('mode').value,'plan');assert.equal(saved.length,0);
    await n('keep').click();assert.equal(n('conflict').hidden,true);assert.equal(world.b.draft.text,'B mine');assert.equal(world.b.draft.revision,2);
    world.b.draft={text:'B explicit saved choice',mode:'native',revision:3};fill('B uncommitted own change','plan');await n('refresh').click();
    assert.equal(n('conflict').hidden,false);assert.equal(n('text').value,'B uncommitted own change');
    await n('load').click();assert.equal(n('text').value,'B explicit saved choice');assert.equal(n('mode').value,'native');
    assert.equal(world.b.draft.revision,3);assert.equal(calls.filter(c=>c.path==='/api/draft').length,2);
  }else if(testcase==='reuse'){
    const original=clone(world.b.followups);await review('b');fill('My reviewed destination','plan');
    await button(followup('b-one'),'Use in this session draft').click();
    assert.equal(n('text').value,'My reviewed destination');assert.equal(n('reuse').hidden,false);
    assert.equal(calls.filter(c=>c.data).length,0);await n('append').click();
    assert.equal(n('text').value,'My reviewed destination\n\nInspect original evidence');assert.equal(n('mode').value,'plan');
    assert.equal(world.b.draft.text,'');assert.deepEqual(world.b.followups,original);
    await n('save').click();assert.equal(world.b.draft.text,n('text').value);assert.deepEqual(world.b.followups,original);
    await button(followup('b-one'),'Use in this session draft').click();await n('replace').click();
    assert.equal(n('text').value,'Inspect original evidence');assert.equal(n('mode').value,'native');
    await button(followup('b-two'),'Copy instruction').click();assert.equal(clipboard.values.at(-1),'Clarify the next acceptance');
    assert.deepEqual(world.b.followups,original);assert.equal(calls.filter(c=>c.data).length,1);
    await button(followup('b-one'),'Use in this session draft').click();world.b.followups.entries[0].revision=2;world.b.followups.entries[0].text='Changed later';await n('refresh').click();
    assert.equal(n('reuse').hidden,true);assert.equal(n('text').value,'Inspect original evidence');
  }else if(testcase==='pending-open'){
    await review('d');assert.match(n('followups').textContent,/Start unconfirmed/);
    assert.match(n('followups').textContent,/Captured instruction/);
    assert(!button(n('followups'),'Use in this session draft'));assert(!all(n('')).some(e=>/Send next|Run task/.test(e.textContent)));
    await button(n('followups'),'Copy captured instruction').click();assert.equal(clipboard.values.at(-1),'Captured instruction');
    assert.deepEqual(opened,[]);await n('open').click();assert.deepEqual(opened,['d']);assert.equal(n('').open,false);
  }else if(testcase==='stale-read-and-refresh'){
    const held=deferred();control.draft=(path,result)=>path.endsWith('=b')?held.promise:result;
    const loading=review('b');await settle();assert.equal(n('text').disabled,true);await review('a');
    held.resolve(clone(world.b.draft));await loading;assert.equal(n('text').value,'A saved Plan');assert.match(n('editor-title').textContent,/A decision/);
    control.draft=null;const old=deferred();control.overview=(path,result)=>path.includes('archived=false')?old.promise:result;
    const refresh=n('refresh').click();n('archived').checked=true;await n('archived').onchange();assert(sessions().includes('c'));
    old.resolve({sessions:[clone(world.b)]});await refresh;assert(sessions().includes('c'));
    assert.equal(n('text').value,'A saved Plan');
  }else if(testcase==='late-save-keeps-edits'){
    await review('a');fill('Reviewed A saved capture','plan');const held=deferred();control.post=(data,result)=>held.promise;
    const saving=n('save').click();await settle();fill('A newer unsaved local text','native');await review('b');fill('B untouched local text','plan');
    held.resolve(clone(world.a.draft));await saving;assert.equal(n('text').value,'B untouched local text');assert.equal(n('mode').value,'plan');
    assert.equal(saved[0].id,'a');assert.equal(saved[0].draft.text,'Reviewed A saved capture');
    await review('a');assert.equal(n('text').value,'A newer unsaved local text');assert.equal(n('mode').value,'native');
    assert.match(n('draft-status').textContent,/Newer edits/);control.post=null;await n('save').click();
    assert.equal(world.a.draft.text,'A newer unsaved local text');assert.equal(world.a.draft.revision,3);
    await review('b');assert.equal(n('text').value,'B untouched local text');
  }else if(testcase==='failures'){
    await review('a');fill('A retained unsaved','plan');control.failOverview=true;await n('refresh').click();
    assert.equal(n('text').value,'A retained unsaved');assert.equal(n('error').hidden,false);
    control.failOverview=false;await n('refresh').click();assert.equal(n('error').hidden,true);
    control.failDraft=true;await review('b');assert.equal(n('text').disabled,true);control.failDraft=false;await review('b');assert.equal(n('text').disabled,false);
    fill('B not lost','plan');control.failPost=true;await n('save').click();assert.equal(n('text').value,'B not lost');assert.match(n('draft-status').textContent,/not saved/);
    control.failPost=false;await n('save').click();clipboard.fail=true;await n('copy').click();assert.match(n('draft-status').textContent,/Copy failed/);
    clipboard.fail=false;await n('copy').click();assert.equal(clipboard.values.at(-1),'B not lost');
  }else if(testcase==='filter-keeps-editor-and-focus'){
    await review('b');fill('B scoped unsaved','plan');const focused=all(n('list')).find(e=>e.dataset.session==='a'&&e.dataset.control==='review');focused.focus();
    await n('refresh').click();assert.equal(document.activeElement.dataset.session,'a');assert.equal(document.activeElement.dataset.control,'review');
    n('project').value='/projects/a';await n('project').onchange();assert.deepEqual(sessions(),['a','d']);assert.equal(n('text').value,'B scoped unsaved');
    assert.match(n('editor-binding').textContent,/Not listed in the current scope/);await n('save').click();assert.equal(world.b.draft.text,'B scoped unsaved');
    n('project').value='';await n('project').onchange();await review('b');assert.equal(n('text').value,'B scoped unsaved');
  }else if(testcase==='cleared-draft-refresh'){
    await review('a');fill('A unsaved review kept across clearing','native');
    world.a.draft={text:'',mode:'plan',revision:2};
    await n('refresh').click();
    assert(!sessions().includes('a'));assert.equal(n('conflict').hidden,false);assert.equal(n('save').disabled,true);
    assert.equal(n('text').value,'A unsaved review kept across clearing');assert.equal(n('mode').value,'native');
    assert.match(n('editor-binding').textContent,/Not listed in the current scope/);
    assert(calls.some(c=>c.path==='/api/draft?session=a'));assert.equal(calls.filter(c=>c.data).length,0);
    await n('load').click();assert.equal(n('text').value,'');assert.equal(n('mode').value,'plan');assert.equal(n('conflict').hidden,true);
    await n('refresh').click();assert.equal(n('text').value,'');assert.equal(n('conflict').hidden,true);
    assert.equal(world.a.draft.revision,2);assert.equal(saved.length,0);
  }else if(testcase==='cleared-draft-with-followups'){
    await review('a');world.a.followups.entries=[{id:'a-queued',text:'Still prepared',mode:'native',order:1,revision:1,state:'queued'}];
    world.a.draft={text:'',mode:'native',revision:2};await n('refresh').click();
    assert(sessions().includes('a'));assert.equal(n('text').value,'A saved Plan');assert.equal(n('mode').value,'plan');
    assert.equal(n('conflict').hidden,false);assert.equal(n('save').disabled,true);
    await n('keep').click();assert.equal(world.a.draft.text,'A saved Plan');assert.equal(world.a.draft.mode,'plan');assert.equal(world.a.draft.revision,3);
    assert.equal(world.a.followups.entries[0].text,'Still prepared');assert.equal(n('conflict').hidden,true);
  }else if(testcase==='filtered-draft-is-not-cleared'){
    await review('a');fill('A unsaved retained outside the list','native');
    n('project').value='/gone/project';await n('project').onchange();
    assert(!sessions().includes('a'));assert.equal(n('conflict').hidden,true);assert.equal(n('save').disabled,false);
    assert.equal(n('text').value,'A unsaved retained outside the list');assert.equal(n('mode').value,'native');
    assert.equal(world.a.draft.text,'A saved Plan');assert.equal(calls.filter(c=>c.data).length,0);
  }else if(testcase==='old-overview-after-save'){
    await review('a');const held=deferred();const old=snapshot('/api/preparation?archived=false');control.overview=()=>held.promise;
    const reading=n('refresh').click();fill('A newly saved draft','plan');await n('save').click();
    held.resolve(old);await reading;assert.equal(n('conflict').hidden,true);assert.equal(n('text').value,'A newly saved draft');
    assert.equal(world.a.draft.revision,2);assert.match(n('status').textContent,/saved while Refresh/);
    control.overview=null;await n('refresh').click();assert.equal(n('conflict').hidden,true);
  }else if(testcase==='old-draft-read-after-initializing-refresh'){
    const held=deferred();control.draft=()=>held.promise;const reading=review('b');await settle();
    world.b.draft={text:'B initialized from fresh overview',mode:'plan',revision:1};await n('refresh').click();
    assert.equal(n('text').disabled,false);fill('B latest own edit','plan');
    held.resolve({text:'',mode:'native',revision:0});await reading;
    assert.equal(n('text').value,'B latest own edit');assert.equal(n('mode').value,'plan');assert.equal(n('conflict').hidden,true);
    await n('save').click();assert.equal(world.b.draft.text,'B latest own edit');assert.equal(world.b.draft.revision,2);
  }else if(testcase==='followup-focus-refresh-and-save'){
    const odd='instruction \" ] +/';world.b.followups.entries[0].id=odd;
    world.a.followups.entries=[{...clone(world.b.followups.entries[0]),text:'Other session instruction'}];
    await n('refresh').click();await review('b');const old=button(followup(odd),'Copy instruction');old.focus();
    world.b.followups.entries.reverse();await n('refresh').click();
    const replacement=button(followup(odd),'Copy instruction');assert.notEqual(replacement,old);
    assert(document.activeElement===replacement,'Keyboard focus must reach the intended visible control');assert.deepEqual(replacement.focusOptions,{preventScroll:true});
    assert.equal(replacement.dataset.session,'b');assert.equal(replacement.dataset.followup,odd);
    fill('B explicit saved draft','plan');replacement.focus();await n('save').click();
    assert(document.activeElement===button(followup(odd),'Copy instruction'),'Keyboard focus must reach the intended visible control');
    n('mode').focus();await n('refresh').click();assert(document.activeElement===n('mode'),'Keyboard focus must reach the intended visible control');
    const use=button(followup(odd),'Use in this session draft');use.focus();
    world.b.followups.entries.find(e=>e.id===odd).state='needs_review';await n('refresh').click();
    assert(!button(followup(odd),'Use in this session draft'));assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');
    assert.equal(n('text').value,'B explicit saved draft');assert.equal(calls.filter(c=>c.data).length,1);
  }else if(testcase==='captured-instruction-focus'){
    await review('d');const copy=button(n('followups'),'Copy captured instruction');copy.focus();await n('refresh').click();
    assert(document.activeElement===button(n('followups'),'Copy captured instruction'),'Keyboard focus must reach the intended visible control');assert.notEqual(document.activeElement,copy);
    world.d.followups.reservation=null;await n('refresh').click();assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');
    assert.equal(calls.filter(c=>c.data).length,0);
  }else if(testcase==='delayed-review-does-not-steal-focus'){
    const held=deferred();control.draft=()=>held.promise;const loading=review('b');await settle();
    n('project').focus();held.resolve(clone(world.b.draft));await loading;
    assert(document.activeElement===n('project'),'Keyboard focus must reach the intended visible control');assert.equal(n('text').disabled,false);
    assert.equal(n('text').value,'');assert.equal(calls.filter(c=>c.data).length,0);
  }else if(testcase==='delayed-review-retains-source-intent'){
    const held=deferred();control.draft=()=>held.promise;const loading=review('b');await settle();
    assert.equal(document.activeElement.dataset.session,'b');assert.equal(document.activeElement.dataset.control,'review');
    held.resolve(clone(world.b.draft));await loading;assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');
    assert.deepEqual(n('text').focusOptions,{preventScroll:true});
  }else if(testcase==='queued-reuse-focus-and-cancel'){
    const original=clone(world.b.followups);await review('b');fill('B reviewed unsaved draft','plan');
    const use=button(followup('b-two'),'Use in this session draft');use.focus();await use.click();
    assert(document.activeElement===n('reuse-text'),'Keyboard focus must reach the intended visible control');assert.equal(n('text').value,'B reviewed unsaved draft');
    n('reuse-cancel').focus();await n('reuse-cancel').click();
    assert(document.activeElement===use,'Keyboard focus must reach the intended visible control');assert.equal(n('reuse').hidden,true);
    use.focus();await use.click();n('append').focus();await n('append').click();
    assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');assert.equal(n('reuse').hidden,true);
    assert.equal(n('text').value,'B reviewed unsaved draft\n\nClarify the next acceptance');
    assert.deepEqual(world.b.followups,original);assert.equal(calls.filter(c=>c.data).length,0);
    await use.click();n('reuse-cancel').focus();world.b.followups.entries=world.b.followups.entries.filter(e=>e.id!=='b-two');
    await n('refresh').click();assert.equal(n('reuse').hidden,true);assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');
  }else if(testcase==='conflict-choice-focus'){
    await review('b');fill('B kept draft','plan');world.b.draft={text:'B changed saved',mode:'native',revision:1};await n('save').click();
    n('load').focus();await n('load').click();assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');assert.equal(n('conflict').hidden,true);
    fill('B keep mine','plan');world.b.draft={text:'B changed again',mode:'native',revision:2};await n('save').click();
    const held=deferred();control.post=()=>held.promise;n('keep').focus();const saving=n('keep').click();await settle();
    assert(document.activeElement===n('text'),'Keyboard focus must reach the intended visible control');n('mode').focus();held.resolve(clone(world.b.draft));await saving;
    assert(document.activeElement===n('mode'),'Keyboard focus must reach the intended visible control');assert.equal(n('conflict').hidden,true);
  }else throw Error('Unknown case '+testcase);
  assert.deepEqual(activeDraft,{session:'a',text:'ACTIVE UNSENT PLAN — do not alter',mode:'plan'});
  assert(!calls.some(c=>/^\/api\/(open|import|turn|sessions|followups)/.test(c.path)));
  console.log(JSON.stringify({case:testcase,passed:true,local_api_calls:calls.length,explicit_saves:saved.length,open_callbacks:opened.length}));
})().catch(e=>{console.error(e);process.exitCode=1;});
'''


@unittest.skipUnless(NODE, 'Node is required for the preparation controller')
class PreparationControllerTests(unittest.TestCase):
    def run_case(self, case):
        result = subprocess.run([NODE, '-e', HARNESS, str(ROOT / 'codex_desk/static/preparation.js'), case],
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('"passed":true', result.stdout)

    def test_query_free_discovery_and_exact_scope(self): self.run_case('discover')
    def test_explicit_revisioned_save_and_page_editor_recovery(self): self.run_case('draft-save')
    def test_conflict_keep_mine_or_load_saved(self): self.run_case('conflict')
    def test_explicit_append_replace_copy_and_stale_source(self): self.run_case('reuse')
    def test_pending_review_is_read_only_and_open_is_separate(self): self.run_case('pending-open')
    def test_late_local_reads_do_not_change_current_editor(self): self.run_case('stale-read-and-refresh')
    def test_late_save_keeps_newer_edits_and_other_session(self): self.run_case('late-save-keeps-edits')
    def test_read_save_clipboard_failure_and_recovery(self): self.run_case('failures')
    def test_scope_and_refresh_preserve_editor_and_keyboard_focus(self): self.run_case('filter-keeps-editor-and-focus')
    def test_refresh_reads_cleared_draft_revision_and_keeps_unsaved_editor_until_load(self): self.run_case('cleared-draft-refresh')
    def test_refresh_reads_cleared_draft_even_when_queued_work_keeps_session_listed(self): self.run_case('cleared-draft-with-followups')
    def test_filtered_retained_editor_is_not_mistaken_for_a_cleared_draft(self): self.run_case('filtered-draft-is-not-cleared')
    def test_old_overview_cannot_reintroduce_conflict_after_save(self): self.run_case('old-overview-after-save')
    def test_initial_draft_read_cannot_overwrite_newer_overview_or_edits(self): self.run_case('old-draft-read-after-initializing-refresh')

    def test_followup_refresh_and_save_preserve_exact_action_focus(self): self.run_case('followup-focus-refresh-and-save')
    def test_captured_instruction_refresh_preserves_action_focus(self): self.run_case('captured-instruction-focus')
    def test_delayed_review_does_not_steal_newer_navigation_focus(self): self.run_case('delayed-review-does-not-steal-focus')
    def test_delayed_review_focuses_editor_when_source_still_owns_focus(self): self.run_case('delayed-review-retains-source-intent')
    def test_queued_reuse_review_and_cancel_have_keyboard_destinations(self): self.run_case('queued-reuse-focus-and-cancel')
    def test_conflict_choices_move_focus_once_without_late_save_steal(self): self.run_case('conflict-choice-focus')


if __name__ == '__main__':
    unittest.main()
